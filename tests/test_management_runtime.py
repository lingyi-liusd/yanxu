import copy
import hashlib
import pathlib
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from agent_manager import Manager
from management_runtime import observe, validate_analysis


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name).resolve()
        self.source = self.root / 'registered.md'
        self.source.write_text('synthetic-only')
        self.value = {'project': {'id':'p', 'workspace':str(self.root)},
                      'artifacts':[{'reference':str(self.source), 'source_version':'sha256:'+hashlib.sha256(b'synthetic-only').hexdigest()}]}
        self.calls = []
        def runner(payload):
            self.calls.append(payload)
            return {k:'synthetic' for k in ('summary','changes','risks','next_step','human_decision')}
        self.m = Manager(self.root, lambda p:copy.deepcopy(self.value), lambda *a:None, runner, debounce=0)
        self.m.configure('p', {'enabled':True,'consent':'codex-project-records-v1','max_calls_per_day':1})

    def tearDown(self):
        self.temp.cleanup()

    def enable(self):
        self.m.configure_runtime('p', {'enabled':True,'consent':'registered-file-metadata-and-review-v1'})

    def test_runtime_preview_is_not_a_grant(self):
        preview=self.m.configure_runtime('p', {'enabled':True,'dry':True,
            'if_runtime_revision':0,'consent':'registered-file-metadata-and-review-v1'})
        self.assertTrue(preview['preview'])
        self.assertFalse(self.m.status('p')['runtime']['enabled'])
        with self.m.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM runtime_policies').fetchone()[0],0)
        self.assertEqual(self.calls,[])

    def test_runtime_stale_dialog_cannot_overwrite_and_pause_preserves_grant(self):
        self.enable()
        before=self.m.status('p')
        self.value['project']['workspace']='/tmp'
        with self.assertRaises(ValueError):
            self.m.configure_runtime('p', {'enabled':False,'if_runtime_revision':0})
        preview=self.m.configure_runtime('p', {'enabled':False,'if_runtime_revision':1,'dry':True})
        self.assertEqual(preview['workspace'],str(self.root))
        self.assertTrue(self.m.status('p')['runtime']['scope_blocked'])
        after=self.m.configure_runtime('p', {'enabled':False,'if_runtime_revision':1})
        self.assertEqual(after['runtime']['workspace'],str(self.root))
        self.assertEqual(after['runtime']['revision'],2)
        self.assertFalse(after['runtime']['scope_blocked'])
        self.assertEqual(after['used_today'],before['used_today'])
        self.assertEqual(after['enabled'],before['enabled'])
        self.m.tick()
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.m.status('p')['file_observations'],[])

    def test_runtime_unknown_project_has_no_policy(self):
        with self.assertRaises(ValueError):
            self.m.configure_runtime('missing',{'enabled':False})
        with self.m.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM runtime_policies').fetchone()[0],0)

    def test_consent_and_no_raw_content(self):
        with self.assertRaises(ValueError): self.m.configure_runtime('p', {'enabled':True})
        self.enable()
        self.m.tick()
        self.assertNotIn('synthetic-only', str(self.calls))
        self.assertEqual(self.m.status('p')['reviews'][0]['state'],'completed')
        self.assertEqual(self.m.status('p')['reviews'][0]['report']['outcome'],'NO_RULE_FINDING')

    def test_version_change_budget_and_no_self_loop(self):
        self.enable()
        self.m.tick()
        for _ in range(5): self.m.tick()
        self.assertEqual(len(self.m.status('p')['reviews']),1)
        self.assertEqual(len(self.calls),1)
        self.source.write_text('changed synthetic source')
        self.m.tick()
        status = self.m.status('p')
        self.assertEqual(len(status['reviews']),2)
        self.assertEqual(status['reviews'][0]['report']['outcome'],'NEEDS_REVIEW')
        self.assertEqual(status['jobs'][0]['state'],'queued')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.value['artifacts'][0]['source_version'], 'sha256:'+hashlib.sha256(b'synthetic-only').hexdigest())

    def test_restart_and_concurrent_claim(self):
        self.enable()
        second = Manager(self.root, lambda p:copy.deepcopy(self.value), lambda *a:None, debounce=0)
        with ThreadPoolExecutor() as pool: list(pool.map(lambda m:m.review_tick('p'), [self.m,second]))
        self.assertEqual(len(second.status('p')['reviews']),1)

    def test_scope_and_symlink_and_secrets(self):
        outside = self.root / 'other.md'
        outside.write_text('never registered')
        link = self.root / 'link.md'
        link.symlink_to(self.source)
        secret = self.root / 'api-token'
        secret.write_text('never open')
        self.value['artifacts'] += [{'reference':str(link)}, {'reference':str(secret)}, {'reference':'/etc/hosts'}]
        result = observe(self.value, str(self.root))
        self.assertEqual(len(result),3)
        self.assertEqual(next(r for r in result if r['path']==str(link))['state'],'inaccessible_or_symlink')
        self.assertEqual(next(r for r in result if r['path']==str(secret))['state'],'excluded')
        self.assertNotIn('never open',str(result))

    def test_missing_and_oversize(self):
        self.source.unlink()
        self.assertEqual(observe(self.value,str(self.root))[0]['state'],'missing')
        self.source.write_bytes(b'a'*(2*1024*1024+1))
        self.assertEqual(observe(self.value,str(self.root))[0]['state'],'oversize')

    def test_pause_and_workspace_change(self):
        self.enable()
        self.m.configure('p', {'enabled':False})
        self.m.tick()
        self.assertEqual(len(self.m.status('p')['reviews']),0)
        self.value['project']['workspace'] = '/tmp'
        with self.assertRaises(ValueError): self.m.source('p')
        status=self.m.status('p')
        self.assertTrue(status['runtime']['scope_blocked'])
        self.assertFalse(status['runtime']['effective_enabled'])
        self.assertEqual(status['file_observations'],[])

    def test_rebound_runtime_never_observes_files_or_runs_model_but_status_is_readable(self):
        from unittest.mock import patch
        self.enable()
        before=self.m.status('p')['used_today']
        self.value['project']['workspace']='/tmp'
        with patch('agent_manager.management_runtime.observe',side_effect=AssertionError('No observation after scope change')):
            status=self.m.status('p')
            self.assertTrue(status['runtime']['scope_blocked'])
            with self.assertRaises(ValueError):self.m.source('p')
            self.m.tick()
        self.assertFalse(self.calls)
        self.assertEqual(self.m.status('p')['used_today'],before)

    def test_model_file_count_is_checked_not_promoted_to_fact(self):
        snapshot = {'file_observations':[{},{}]}
        self.assertTrue(validate_analysis(snapshot, {'changes':'所列3个文件均存在'}))
        self.assertFalse(validate_analysis(snapshot, {'changes':'所列2个文件均存在'}))
        self.assertFalse(validate_analysis({}, {'changes':'所列3个文件'}))


if __name__ == '__main__': unittest.main()
