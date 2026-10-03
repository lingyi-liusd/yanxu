import copy
import concurrent.futures
import json
import pathlib
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import registered_batches as batching
from agent_manager import Manager, SCHEMA, MAX_REGISTERED_INPUT_BYTES


class RegisteredBatchesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data=pathlib.Path(self.tmp.name).resolve()/'desk';self.data.mkdir()
        self.source = {'project':{'id':'p','goal':'不可将负结果改成通过'},
            'workspace_scope':{'revision':7,'state':'ready'},
            'tasks':[], 'artifacts':[{'id':str(i),'source_version':'sha256:'+str(i),
                'status':'FAIL' if i%2 else 'UNKNOWN','note':'条件与负结果' * 1400} for i in range(14)]}
        self.original = copy.deepcopy(self.source)
        self.calls = []
        def runner(payload):
            self.calls.append(copy.deepcopy(payload))
            return {k:'未独立核验，保留负结果和条件。' for k in SCHEMA['required']}
        self.runner = runner
        self.manager = self.make()

    def tearDown(self): self.tmp.cleanup()

    def make(self,runner=None):
        return Manager(self.data,lambda _:copy.deepcopy(self.source),lambda *args:None,runner or self.runner,debounce=0)

    def enable(self,budget=20):
        self.manager.configure('p',{'enabled':True,'consent':'codex-project-records-v1','max_calls_per_day':budget})

    def drive(self,limit=60):
        for _ in range(limit):
            self.manager.tick()
            status=self.manager.status('p')
            if status['jobs'][0]['state'] not in ('queued','running'): return status
        return status

    def test_lossless_complete_plan_even_without_ids(self):
        self.source['artifacts'][0].pop('id')
        self.source['decisions']=[{'id':'same','note':'一'},{'id':'same','note':'二'}]
        plan=batching.plan(self.source)
        rebuilt={k:self.source[k] for k in ('project','workspace_scope')}
        seen=[]
        for batch in plan['batches']:
            self.assertEqual(batch['input_sha256'],batching.digest(batch['current']))
            for record in batch['records']:
                section,index=record['section'],record['index']
                original=self.source[section] if index is None else self.source[section][index]
                self.assertEqual(record['sha256'],batching.digest(original))
                if index is None: rebuilt[section]=copy.deepcopy(original)
                else: rebuilt.setdefault(section,[]).append(copy.deepcopy(original))
                seen.append((section,index))
        self.assertEqual(rebuilt,self.source)
        self.assertEqual(len(seen),len(set(seen)))
        self.assertEqual(plan['source_hash'],batching.digest(rebuilt))

    def test_only_final_complete_aggregate_is_actionable(self):
        self.enable()
        initial=self.manager.status('p')
        self.assertTrue(initial['input_readiness']['ready'])
        self.assertTrue(initial['input_readiness']['batched'])
        self.manager.tick()
        middle=self.manager.status('p')
        self.assertEqual(middle['used_today'],1)
        self.assertIsNone(middle['jobs'][0]['analysis'])
        self.assertFalse(middle['handoffs'])
        final=self.drive()
        self.assertEqual(final['jobs'][0]['state'],'succeeded')
        self.assertEqual(final['used_today'],len(self.calls))
        self.assertEqual(len(final['handoffs']),1)
        coverage=final['jobs'][0]['registered_coverage']
        self.assertEqual(coverage['leaf_replied'],coverage['leaf_total'])
        self.assertTrue(coverage['aggregation_complete'])
        self.assertEqual(final['jobs'][0]['verification_status'],'UNVERIFIED')
        self.assertEqual(self.source,self.original)
        self.assertTrue(all(len(batching.encode(p).encode())<=MAX_REGISTERED_INPUT_BYTES for p in self.calls))
        self.assertTrue(all(p['source_hash']==final['source_hash'] for p in self.calls))
        leafrecords=[r for p in self.calls if p['registered_batch']['stage']=='leaf' for r in p['current'].get('artifacts',[])]
        self.assertEqual(leafrecords,self.source['artifacts'])
        calls=len(self.calls)
        for _ in range(4):self.manager.tick()
        self.assertEqual(len(self.calls),calls)

    def test_successful_parts_resume_but_not_repeat_after_restart(self):
        self.enable()
        self.manager.tick()
        first=batching.digest(self.calls[0])
        self.manager=self.make()
        final=self.drive()
        self.assertEqual(final['jobs'][0]['state'],'succeeded')
        self.assertEqual(sum(batching.digest(p)==first for p in self.calls),1)

    def test_failure_and_crash_have_no_summary_no_retry(self):
        self.enable()
        self.manager.tick()
        def fail(payload):
            self.calls.append(copy.deepcopy(payload))
            raise RuntimeError('synthetic failure')
        self.manager.runner=fail
        self.manager.tick()
        failed=self.manager.status('p')
        self.assertEqual(failed['jobs'][0]['state'],'failed')
        self.assertEqual(failed['used_today'],2)
        self.assertFalse(failed['handoffs'])
        self.manager=self.make()
        for _ in range(3):self.manager.tick()
        self.assertEqual(len(self.calls),2)

    def test_interrupted_part_is_not_replayed(self):
        self.enable()
        with self.manager.db() as c:
            c.execute("UPDATE jobs SET state='running',started=?",(time.time()-241,))
            c.execute("UPDATE reflection_parts SET state='running',started=?,day='2000-01-01' WHERE ordinal=0",(time.time()-241,))
        self.manager=self.make()
        self.manager.tick()
        self.assertFalse(self.calls)
        self.assertEqual(self.manager.status('p')['jobs'][0]['state'],'failed')
        with self.manager.db() as c:
            self.assertEqual(c.execute('SELECT state FROM reflection_parts WHERE ordinal=0').fetchone()[0],'failed')

    def test_each_call_honors_existing_budget_and_extra_is_only_one(self):
        self.enable(budget=1)
        self.manager.tick()
        self.manager.tick()
        status=self.manager.status('p')
        self.assertEqual(status['used_today'],1)
        self.assertEqual(status['jobs'][0]['state'],'queued')
        self.manager.grant_extra_call('p',{'job_id':status['jobs'][0]['id'],'source_hash':status['source_hash'],
            'consent':'one-extra-call-today-v1','reason':'只加一次'})
        for _ in range(8):self.manager.tick()
        self.assertEqual(len(self.calls),2)
        status=self.manager.status('p')
        self.assertEqual(status['used_today'],2)
        self.assertEqual(status['base_calls_per_day'],1)
        self.assertFalse(status['handoffs'])

    def test_parallel_managers_claim_each_part_once(self):
        self.enable()
        second=self.make()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            list(pool.map(lambda m:m.tick(),[self.manager,second]))
        self.assertEqual(len({batching.digest(p) for p in self.calls}),len(self.calls))
        self.assertIn(len(self.calls),(1,2))

    def test_changed_source_rejects_old_batch_next_call(self):
        self.enable()
        self.manager.tick()
        oldhash=self.calls[0]['source_hash']
        self.source['artifacts'][0]['status']='PARTIAL'
        self.manager.tick()
        self.assertNotEqual(self.calls[-1]['source_hash'],oldhash)
        self.assertEqual(sum(p['source_hash']==oldhash for p in self.calls),1)
        self.assertFalse(self.manager.status('p')['handoffs'])

    def test_pause_during_reply_quarantines_and_stops(self):
        self.enable()
        def pause(payload):
            self.manager.configure('p',{'enabled':False})
            return self.runner(payload)
        self.manager.runner=pause
        self.manager.tick()
        status=self.manager.status('p')
        self.assertEqual(status['jobs'][0]['state'],'cancelled')
        self.assertFalse(status['handoffs'])
        self.manager.tick()
        self.assertEqual(len(self.calls),1)

    def test_bad_or_oversized_reply_preserved_not_truncated(self):
        self.enable()
        def large(payload):
            self.calls.append(payload)
            return {k:'中'*12000 for k in SCHEMA['required']}
        self.manager.runner=large
        status=self.drive()
        self.assertEqual(status['jobs'][0]['state'],'failed')
        self.assertFalse(status['handoffs'])
        self.assertIn('回包过大',status['jobs'][0]['error'])
        with self.manager.db() as c:
            saved=json.loads(c.execute('SELECT output FROM reflection_parts WHERE ordinal=0').fetchone()[0])
        self.assertEqual(saved['risks'],'中'*12000)
        count=len(self.calls)
        self.manager.tick()
        self.assertEqual(len(self.calls),count)

    def test_response_corruption_before_aggregation_is_rejected(self):
        self.enable()
        self.manager.tick()
        with self.manager.db() as c:
            c.execute("UPDATE reflection_parts SET output=? WHERE ordinal=0",(json.dumps({k:'篡改摘要' for k in SCHEMA['required']}),))
        status=self.drive()
        self.assertEqual(status['jobs'][0]['state'],'failed')
        self.assertIn('回包版本不符',status['jobs'][0]['error'])
        self.assertFalse(status['handoffs'])

    def test_real_bridge_receipt_waits_for_whole_aggregate_and_recovers_commit(self):
        folder=pathlib.Path(self.tmp.name).resolve()/'fixture';folder.mkdir()
        (folder/'negative.md').write_text('合成文件：负结果，未独立核验。')
        bridge=self.manager.bridge
        bridge.configure('p',{'enabled':True,'send_content':True,'folders':[str(folder)],'threads':[],
            'if_revision':0,'consent':'selected-local-sources-v1','content_consent':'selected-source-text-to-codex-v1'})
        bridge.last_poll.clear();bridge.poll()
        self.enable()
        self.manager.tick()
        self.assertEqual(bridge.status('p')['coverage']['processed'],0)
        with patch.object(bridge,'accept_batch'):
            status=self.drive()
        self.assertEqual(status['jobs'][0]['state'],'succeeded')
        self.assertEqual(bridge.status('p')['coverage']['processed'],0)
        receipt=status['jobs'][0]['analysis_context']['source_read_receipt']
        self.assertEqual(receipt['counts']['pending'],1)
        self.assertEqual(receipt['state'],'current_ledger')
        count=len(self.calls)
        self.manager.tick()
        self.assertEqual(bridge.status('p')['coverage']['processed'],1)
        self.assertEqual(len(self.calls),count)
        for part in status['jobs'][0]['registered_coverage']['parts']:
            payload=next(p for p in self.calls if p['registered_batch']['ordinal']==part['ordinal'])
            self.assertEqual(part['model_input_sha256'],'sha256:'+batching.digest(payload))

    def test_source_revocation_during_batch_preserves_zero_read_acceptance(self):
        folder=pathlib.Path(self.tmp.name).resolve()/'fixture';folder.mkdir()
        (folder/'a.md').write_text('只用于合成测试')
        bridge=self.manager.bridge
        bridge.configure('p',{'enabled':True,'send_content':True,'folders':[str(folder)],'threads':[],
            'if_revision':0,'consent':'selected-local-sources-v1','content_consent':'selected-source-text-to-codex-v1'})
        bridge.last_poll.clear();bridge.poll()
        self.enable()
        def revoke(payload):
            bridge.configure('p',{'enabled':False,'send_content':False,'folders':[],'threads':[],
                'if_revision':1})
            return self.runner(payload)
        self.manager.runner=revoke
        self.manager.tick()
        status=self.manager.status('p')
        self.assertEqual(status['jobs'][0]['state'],'stale')
        self.assertFalse(status['handoffs'])
        self.assertEqual(bridge.status('p')['coverage']['processed'],0)


if __name__=='__main__':unittest.main()
