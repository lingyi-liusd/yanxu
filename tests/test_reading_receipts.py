"""Synthetic adversarial reading provenance; no real files, model or production DB."""
import copy
import hashlib
import json
import pathlib
import sys
import tempfile
import unittest
import sqlite3
import threading
from unittest import mock

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from agent_manager import Manager, encode, management_prompt
from management_runtime import validate_analysis
from source_bridge import Bridge
from workspace_registry import Registry
import agent_manager


class ReadingReceiptTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='yanxu-receipt-')
        self.addCleanup(temporary.cleanup)
        self.root=pathlib.Path(temporary.name).resolve()
        self.data=self.root/'data';self.data.mkdir()
        self.folder=self.root/'sources';self.folder.mkdir()
        (self.folder/'a.md').write_text('SOURCE_A: failed startup, not independently verified')
        (self.folder/'b.md').write_text('SOURCE_B: Windows NOT_RUN, UNKNOWN')
        (self.folder/'unsupported.pdf').write_text('Not a real PDF; unsupported content must stay unknown')
        self.bridge=Bridge(self.data,self.root/'codex')
        self.bridge.configure('p',dict(enabled=True,send_content=True,folders=[str(self.folder)],threads=[],
            if_revision=0,consent='selected-local-sources-v1',content_consent='selected-source-text-to-codex-v1'))
        self.calls=[]
        self.value={'project':{'id':'p','goal':'Only synthetic reading tests'},'tasks':[]}
        self.manager=Manager(self.data,lambda p:copy.deepcopy(self.value),lambda *args:None,self.runner,debounce=0)
        self.manager.bridge=self.bridge

    def runner(self,payload):
        self.calls.append(copy.deepcopy(payload))
        return {key:'待核验' for key in ('summary','changes','risks','next_step','human_decision')}

    def poll(self):
        self.bridge.last_poll.clear();self.bridge.poll()
        return self.bridge.model_snapshot('p')

    def enable(self):
        self.manager.configure('p',dict(enabled=True,max_calls_per_day=8,consent='codex-project-records-v1'))

    def test_historical_batch_and_current_receipt_are_distinct_without_self_trigger(self):
        batch=self.poll()
        self.assertFalse(batch['coverage_context']['is_live'])
        self.assertEqual(batch['coverage']['pending'],2)
        pending=self.bridge.read_receipt('p',batch)
        self.assertEqual(pending['counts']['pending'],2)
        self.bridge.accept_batch('p',batch)
        self.assertEqual(self.poll(),batch)
        done=self.bridge.read_receipt('p',batch)
        self.assertEqual(done['counts']['processed'],2)
        self.assertEqual(done['counts']['pending'],0)
        self.assertEqual(done['counts']['unsupported'],1)
        self.assertTrue(all(row['processing_state']=='accepted' for row in done['batch_chunks']))
        self.assertNotIn('SOURCE_A',json.dumps(done))
        self.enable();self.manager.tick()
        signature=self.manager.source('p')[1]
        for _ in range(8):self.manager.tick()
        self.assertEqual(len(self.calls),1)
        self.assertEqual(signature,self.manager.source('p')[1])

    def test_saved_receipt_matches_exact_request_and_survives_restart(self):
        self.poll();self.enable();self.manager.tick()
        payload=self.calls[0]
        job=self.manager.status('p')['jobs'][0]
        context=job['analysis_context']
        self.assertEqual(context['source_read_receipt'],payload['source_read_receipt'])
        self.assertEqual(context['model_input_sha256'],'sha256:'+hashlib.sha256(encode(payload).encode()).hexdigest())
        self.assertEqual(context['source_read_receipt']['counts']['pending'],2)
        self.assertEqual(self.bridge.status('p')['coverage']['pending'],0)
        restarted=Manager(self.data,lambda p:copy.deepcopy(self.value),lambda *args:None,self.runner,debounce=0)
        restarted.tick()
        self.assertEqual(len(self.calls),1)
        self.assertEqual(restarted.status('p')['jobs'][0]['analysis_context'],context)

    def test_second_trigger_uses_current_ledger_not_previous_batch_counts(self):
        self.poll();self.enable();self.manager.tick()
        self.value['tasks'].append({'id':'changed','title':'A new registered task, no source content change'})
        self.manager.tick()
        payload=self.calls[-1]
        self.assertEqual(len(self.calls),2)
        self.assertEqual(payload['current']['source_bridge']['coverage']['pending'],2)
        self.assertEqual(payload['source_read_receipt']['counts']['pending'],0)
        self.assertEqual(payload['source_read_receipt']['counts']['processed'],2)
        self.assertIn('历史统计',management_prompt(payload))

    def test_receipt_cannot_cross_project(self):
        batch=self.poll();receipt=self.bridge.read_receipt('q',batch)
        self.assertEqual(receipt['state'],'scope_or_batch_changed')
        self.assertIsNone(receipt['counts'])
        self.assertEqual(receipt['batch_chunks'],[])

    def test_revoked_scope_does_not_disclose_old_receipt_counts_or_items(self):
        batch=self.poll()
        self.bridge.configure('p',dict(enabled=False,if_revision=1))
        receipt=self.bridge.read_receipt('p',batch)
        self.assertIsNone(receipt['counts']);self.assertEqual(receipt['batch_chunks'],[])

    def test_changed_manifest_blocks_old_receipt(self):
        batch=self.poll()
        (self.folder/'new.md').write_text('new version not present in old batch')
        self.poll()
        self.assertEqual(self.bridge.read_receipt('p',batch)['state'],'scope_or_batch_changed')

    def test_forged_items_cannot_borrow_another_projects_batch_headers(self):
        batch=self.poll()
        other=self.root/'other';other.mkdir();(other/'q.md').write_text('OTHER_PROJECT_MARKER')
        self.bridge.configure('q',dict(enabled=True,send_content=True,folders=[str(other)],threads=[],
            if_revision=0,consent='selected-local-sources-v1',content_consent='selected-source-text-to-codex-v1'))
        self.poll();forged=self.bridge.model_snapshot('q');forged['items']=batch['items']
        receipt=self.bridge.read_receipt('q',forged)
        self.assertEqual(receipt['state'],'scope_or_batch_changed')
        self.assertIsNone(receipt['counts']);self.assertEqual(receipt['batch_chunks'],[])

    def test_revocation_during_receipt_binding_prevents_any_runner_call(self):
        self.poll();self.enable();original=self.bridge.read_receipt
        def revoke(project,batch):
            self.bridge.configure(project,dict(enabled=False,if_revision=1))
            return original(project,batch)
        self.bridge.read_receipt=revoke;self.manager.tick()
        self.assertEqual(self.calls,[])
        self.assertEqual(self.manager.status('p')['jobs'][0]['state'],'failed')

    def test_final_send_gate_rejects_source_or_policy_change(self):
        batch=self.poll();self.enable();value,signature=self.manager.source('p')
        payload={'current':value,'source_hash':signature}
        with self.manager.db() as c:generation=c.execute('SELECT generation FROM policies WHERE project=\'p\'').fetchone()[0]
        with self.manager.model_send_guard(payload,'p',generation):pass
        self.bridge.configure('p',dict(enabled=False,if_revision=1))
        with self.assertRaisesRegex(RuntimeError,'未发送'):
            with self.manager.model_send_guard(payload,'p',generation):self.fail('should not submit')

    def test_failed_processing_does_not_get_a_success_receipt(self):
        batch=self.poll();self.enable()
        def fail(payload):
            self.calls.append(copy.deepcopy(payload));raise RuntimeError('synthetic failure')
        self.manager.runner=fail;self.manager.tick();self.manager.tick()
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.manager.status('p')['jobs'][0]['state'],'failed')
        receipt=self.bridge.read_receipt('p',batch)
        self.assertEqual(receipt['counts']['processed'],0)
        self.assertTrue(all(row['processing_state']=='pending' for row in receipt['batch_chunks']))

    def test_explicit_bad_current_counts_flagged_but_original_analysis_preserved(self):
        batch=self.poll();self.bridge.accept_batch('p',batch)
        receipt=self.bridge.read_receipt('p',batch)
        analysis={'summary':'当前待处理资料2项。当前已处理文件0个。','changes':'历史批次有2个文件待处理。'}
        original=copy.deepcopy(analysis)
        self.assertEqual(len(validate_analysis({},analysis,receipt)),2)
        self.assertEqual(analysis,original)
        self.assertFalse(validate_analysis({}, {'summary':'当前待处理资料0项，当前已处理文件2个。'},receipt))
        self.assertFalse(validate_analysis({}, {'summary':'历史有2项资料待处理；当前有2个任务待处理'},receipt))

    def test_no_receipt_never_invents_current_counts(self):
        self.assertIsNone(self.bridge.read_receipt('p',{}))
        self.assertFalse(validate_analysis({}, {'summary':'当前待处理资料2项'},None))
        self.assertIn('没有回执则写当前处理进度未确认',management_prompt({}))

    def test_historical_jobs_are_not_given_fabricated_receipts(self):
        self.poll();self.enable()
        with self.manager.db() as c:
            c.execute("UPDATE jobs SET state='succeeded',output=?",(encode(self.runner({})),))
        self.assertIsNone(self.manager.status('p')['jobs'][0]['analysis_context'])

    def test_resume_inherits_current_reading_and_review_scope_without_self_trigger(self):
        self.poll();self.enable();self.manager.tick()
        self.value['result_reviews']=[{'id':'human-review','project_id':'p','result_id':'negative-result',
            'conclusion':'accepted','review_kind':'software','criteria':'Only app display',
            'scientific_status':'NOT_ASSESSED','source_version':'v1'},
            {'id':'other-review','project_id':'q','result_id':'foreign','notes':'OTHER_PROJECT_MARKER'}]
        before=self.manager.source('p')[1]
        status=self.manager.status('p')
        handoff=status['resume_brief']['handoff']
        self.assertEqual(handoff['reading_coverage']['current_ledger']['processed'],2)
        self.assertEqual(handoff['reading_coverage']['latest_summary_read_receipt']['counts']['processed'],0)
        self.assertEqual([row['id'] for row in handoff['result_review_receipts']],['human-review'])
        self.assertNotIn('OTHER_PROJECT_MARKER',json.dumps(handoff))
        self.manager.tick()
        self.assertEqual(self.manager.source('p')[1],before)
        self.assertEqual(len(self.calls),1)

    def test_local_only_index_is_not_claimed_as_model_processing(self):
        self.bridge.configure('p',dict(enabled=True,send_content=False,folders=[str(self.folder)],threads=[],
            if_revision=1,consent='selected-local-sources-v1'))
        self.poll()
        self.assertEqual(self.bridge.index_page('p')['processing_mode'],'local_read')
        self.assertEqual(self.bridge.status('p')['coverage']['processed'],2)
        self.assertEqual(self.bridge.model_snapshot('p')['items'],[])

    def test_revocation_removes_old_receipt_from_resumption_without_rewriting_history(self):
        self.poll();self.enable();self.manager.tick()
        context=copy.deepcopy(self.manager.status('p')['jobs'][0]['analysis_context'])
        self.bridge.configure('p',dict(enabled=False,if_revision=1))
        status=self.manager.status('p')
        self.assertIsNone(status['resume_brief']['handoff']['reading_coverage']['latest_summary_read_receipt'])
        self.assertEqual(status['jobs'][0]['analysis_context'],context)

    def test_runtime_uses_bound_directory_not_old_note_and_rejects_changed_exclusions(self):
        self.value['project']['workspace']=str(self.root/'old-note-only')
        registry=Registry(self.data,lambda p:copy.deepcopy(self.value));self.manager.workspace=registry
        registry.configure('p',dict(root=str(self.folder),relative_path='.',exclusions=[],if_revision=0,
            consent='project-workspace-binding-v1'))
        body=dict(enabled=True,consent='registered-file-metadata-and-review-v1')
        with self.assertRaisesRegex(ValueError,'版本'):self.manager.configure_runtime('p',body)
        status=self.manager.configure_runtime('p',dict(body,workspace_revision=1))
        self.assertEqual(status['runtime']['workspace'],str(self.folder))
        self.assertEqual(status['runtime']['workspace_revision'],1)
        registry.configure('p',dict(root=str(self.folder),relative_path='.',exclusions=['a.md'],if_revision=1,
            consent='project-workspace-binding-v1'))
        with self.assertRaisesRegex(ValueError,'排除范围已变'):self.manager.source('p')
        status=self.manager.configure_runtime('p',dict(enabled=False))
        self.assertFalse(status['runtime']['enabled'])
        self.manager.configure_runtime('p',dict(body,workspace_revision=2))

    def test_default_cli_path_rechecks_after_prompt_preparation(self):
        self.poll();self.enable();self.manager.runner=agent_manager.codex_analyze
        def revoke(payload):
            self.manager.configure('p',{'enabled':False});return 'Synthetic prompt'
        with mock.patch.dict('os.environ',RESEARCH_DESK_CODEX_BIN='synthetic-not-executed'), \
             mock.patch.object(agent_manager,'management_prompt',side_effect=revoke), \
             mock.patch.object(agent_manager.subprocess,'Popen') as launch:
            self.manager.tick();launch.assert_not_called()
        self.assertNotEqual(self.manager.status('p')['jobs'][0]['state'],'succeeded')

    def test_desk_first_lock_order_allows_pending_human_approval_and_releases(self):
        self.poll();self.enable();value,signature=self.manager.source('p')
        payload={'current':value,'source_hash':signature}
        with sqlite3.connect(self.data/'desk.sqlite3') as c:c.execute('CREATE TABLE dummy(value INTEGER)')
        ready=threading.Event();release=threading.Event();errors=[]
        def approval():
            try:
                with sqlite3.connect(self.data/'desk.sqlite3',timeout=2) as c:
                    c.execute('BEGIN IMMEDIATE');ready.set();release.wait(1)
                    c.execute('ATTACH DATABASE ? AS manager_store',(str(self.manager.path),))
                    c.execute('UPDATE manager_store.policies SET budget=budget WHERE project=\'p\'')
            except Exception as exc:errors.append(str(exc))
        worker=threading.Thread(target=approval);worker.start();self.assertTrue(ready.wait(1))
        timer=threading.Timer(.05,release.set);timer.start()
        with self.manager.model_send_guard(payload,'p',1):pass
        worker.join(2);timer.join();self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
        with self.assertRaisesRegex(RuntimeError,'synthetic'):
            with self.manager.model_send_guard(payload,'p',1):raise RuntimeError('synthetic')
        self.manager.configure('p',{'enabled':False})
        with sqlite3.connect(self.data/'desk.sqlite3',timeout=.2) as c:c.execute('INSERT INTO dummy VALUES(1)')


if __name__=='__main__':unittest.main()
