import concurrent.futures
import copy
import pathlib
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from agent_manager import Manager


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.values = {'p': {'project': {'id': 'p', 'goal': '保留原问题'}, 'tasks': []},
                       'q': {'project': {'id': 'q'}, 'tasks': []}}
        self.calls = []
        self.events = []
        def runner(value):
            self.calls.append(value)
            return {k: '待核验' for k in ('summary','changes','risks','next_step','human_decision')}
        self.runner = runner
        self.m = self.make()

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, runner=None):
        return Manager(self.tmp.name, lambda p: copy.deepcopy(self.values[p]),
                       lambda *args: self.events.append(args), runner or self.runner, debounce=0)

    def enable(self, p='p', budget=4):
        self.m.configure(p, {'enabled':True, 'max_calls_per_day':budget, 'consent':'codex-project-records-v1'})

    def test_opt_in_read_only_and_no_self_loop(self):
        self.m.tick()
        self.assertFalse(self.calls)
        with self.assertRaises(ValueError):
            self.m.configure('p', {'enabled':True})
        self.enable()
        for _ in range(5): self.m.tick()
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.m.status('p')['jobs'][0]['verification_status'],'UNVERIFIED')
        self.assertEqual(len(self.m.status('p')['handoffs']),1)
        self.assertEqual(self.m.status('p')['handoffs'][0]['state'],'draft')
        self.assertEqual(self.values['p']['project']['goal'],'保留原问题')

    def test_coalescing_and_restart(self):
        self.enable()
        self.values['p']['tasks'] = [{'id':'a'}]
        self.m.enqueue('p')
        self.values['p']['tasks'].append({'id':'b'})
        self.m.enqueue('p')
        self.make().tick()
        self.assertEqual(len(self.calls),1)
        self.assertEqual(len(self.calls[0]['current']['tasks']),2)
        self.m.tick()
        self.assertEqual(len(self.calls),1)

    def test_oversize_registered_records_have_read_only_current_diagnostic(self):
        self.enable()
        before=self.m.status('p')
        self.values['p']['artifacts']=[{'id':'large','description':'原始负结果' * 20000}]
        status=self.m.status('p')
        diagnostic=status['input_readiness']
        self.assertFalse(diagnostic['ready'])
        self.assertEqual(diagnostic['code'],'input_too_large')
        self.assertGreater(diagnostic['input_bytes'],diagnostic['limit_bytes'])
        self.assertEqual(next(s for s in diagnostic['sections'] if s['section']=='artifacts')['records'],1)
        self.assertEqual(status['used_today'],before['used_today'])
        self.assertEqual(len(status['jobs']),len(before['jobs']))
        self.assertFalse(self.calls)
        with self.assertRaisesRegex(ValueError,'单条登记记录过大'):self.m.enqueue('p')
        self.assertIn('原始负结果',self.values['p']['artifacts'][0]['description'])
        self.values['p']['artifacts']=[]
        self.assertTrue(self.m.status('p')['input_readiness']['ready'])

    def test_old_blocked_queue_does_not_spend_attempt_or_starve_other_project(self):
        self.values['p']['project']['workspace']=str(pathlib.Path(self.tmp.name).resolve())
        self.m.configure_runtime('p',{'enabled':True,'consent':'registered-file-metadata-and-review-v1'})
        self.enable('p');self.enable('q')
        self.values['p']['project']['workspace']='/tmp'
        self.m.tick()
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.calls[0]['current']['project']['id'],'q')
        self.assertEqual(self.m.status('p')['used_today'],0)
        self.assertEqual(self.m.status('p')['jobs'][0]['state'],'queued')
        self.m.tick()
        self.assertEqual(len(self.calls),1)

    def test_continuity_read_only_without_budget_or_queue_change(self):
        self.enable()
        self.m.tick()
        before = self.m.status('p')
        self.values['p']['tasks'] = [{'id':'changed','title':'继续原问题'}]
        for _ in range(3):
            status = self.m.status('p')
            self.assertEqual(status['used_today'], before['used_today'])
            self.assertEqual(len(status['jobs']), len(before['jobs']))
            self.assertEqual(status['continuity']['changes'][0]['id'], 'changed')
            self.assertEqual(status['continuity']['source_hash'], status['source_hash'])
        self.assertEqual(len(self.calls), 1)

    def test_success_baseline_survives_long_queue_history(self):
        self.enable(budget=1)
        self.m.tick()
        baseline_id = self.m.status('p')['jobs'][0]['id']
        for i in range(16):
            self.values['p']['tasks'] = [{'id':'a','title':str(i)}]
            self.m.enqueue('p')
        status = self.m.status('p')
        self.assertEqual(status['continuity']['baseline']['job_id'], baseline_id)
        baseline = next(j for j in status['jobs'] if j['id']==baseline_id)
        self.assertTrue(baseline['stale'])
        self.assertIsNotNone(baseline['analysis'])
        self.assertEqual(status['used_today'], 1)

    def test_one_extra_call_bound_to_today_and_input(self):
        self.enable(budget=1)
        self.m.tick()
        self.values['p']['tasks'] = [{'id':'second'}]
        self.m.tick()
        status = self.m.status('p')
        body = {'job_id':status['jobs'][0]['id'],'source_hash':status['source_hash'],
                'consent':'one-extra-call-today-v1','reason':'一次真实验收'}
        self.m.grant_extra_call('p', dict(body,dry=True))
        self.m.tick()
        self.assertEqual(len(self.calls),1)
        self.m.grant_extra_call('p',body)
        self.m.tick()
        self.m.tick()
        self.assertEqual(len(self.calls),2)
        self.assertEqual(self.m.status('p')['base_calls_per_day'],1)
        self.values['p']['tasks'].append({'id':'third'})
        self.m.tick()
        self.assertEqual(len(self.calls),2)
        new = self.m.status('p')
        with self.assertRaises(ValueError):
            self.m.grant_extra_call('p',dict(body,job_id=new['jobs'][0]['id'],source_hash=new['source_hash']))

    def test_expired_extra_call_does_not_raise_next_day_limit(self):
        self.enable(budget=1)
        self.m.tick()
        self.values['p']['tasks'] = [{'id':'second'}]
        self.m.tick()
        status = self.m.status('p')
        self.m.grant_extra_call('p', {'job_id':status['jobs'][0]['id'],'source_hash':status['source_hash'],
                                    'consent':'one-extra-call-today-v1','reason':'一次验收'})
        with self.m.db() as c: c.execute("UPDATE call_grants SET day='2000-01-01'")
        self.m.tick()
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.m.status('p')['max_calls_per_day'],1)

    def test_concurrent_claim_once(self):
        self.enable()
        second = self.make()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            list(pool.map(lambda m:m.tick(), [self.m,second]))
        self.assertEqual(len(self.calls),1)

    def test_inflight_edit_is_stale(self):
        self.enable()
        def edit(value):
            self.values['p']['tasks'].append({'id':'changed'})
            return self.runner(value)
        self.m.runner = edit
        self.m.tick()
        self.assertEqual(self.m.status('p')['jobs'][0]['state'],'stale')

    def test_pause_and_inflight_output(self):
        self.enable()
        def pause(value):
            self.m.configure('p', {'enabled':False})
            return self.runner(value)
        self.m.runner = pause
        self.m.tick()
        self.assertEqual(self.m.status('p')['jobs'][0]['state'],'cancelled')
        self.m.tick()
        self.assertEqual(len(self.calls),1)

    def test_failure_no_retry_and_budget(self):
        self.enable(budget=1)
        def fail(value):
            self.calls.append(value)
            raise RuntimeError('synthetic failure')
        self.m.runner = fail
        self.m.tick()
        self.m.tick()
        self.assertEqual(len(self.calls),1)
        self.values['p']['tasks'].append({'id':'new'})
        self.m.tick()
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.m.status('p')['used_today'],1)

    def test_other_project_does_not_trigger(self):
        self.enable()
        self.m.tick()
        self.values['q']['tasks'].append({'id':'unrelated'})
        self.m.tick()
        self.assertEqual(len(self.calls),1)

    def test_exhausted_project_does_not_block_others(self):
        self.enable(budget=1)
        self.m.tick()
        self.values['p']['tasks'].append({'id':'budget-full'})
        self.m.enqueue('p')
        self.enable('q')
        self.m.tick()
        self.assertEqual(len(self.calls),2)
        self.assertEqual(self.calls[-1]['current']['project']['id'],'q')

    def test_oversized_context_not_sent(self):
        self.values['p']['tasks'] = [{'note':'x'*180001}]
        with self.assertRaises(ValueError): self.enable()
        self.assertFalse(self.calls)

    def test_expired_lease_does_not_rerun(self):
        self.enable()
        with self.m.db() as c:
            c.execute("UPDATE jobs SET state='running',started=?,day='2000-01-01'", (time.time()-241,))
        self.m.tick()
        self.assertFalse(self.calls)
        self.assertEqual(self.m.status('p')['jobs'][0]['state'],'failed')


if __name__ == '__main__': unittest.main()
