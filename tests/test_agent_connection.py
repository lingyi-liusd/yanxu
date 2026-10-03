import copy
import json
import pathlib
import queue
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import agent_connection as runtime
from agent_manager import Manager, SCHEMA


class FakeRPC:
    serial = 0
    instances = []

    def __init__(self, executable, workspace, settings):
        self.calls = []
        self.dead = threading.Event()
        self.events = queue.Queue()
        self.unsafe = False
        self.mode = 'success'
        self.instances.append(self)

    def send(self, value):
        self.calls.append((value['method'], value.get('params')))

    def call(self, method, params, timeout=15):
        self.calls.append((method, copy.deepcopy(params)))
        if method == 'config/read':
            return {'config':{'model':'test-model','model_reasoning_effort':'medium','features':{k:False for k in runtime.DISABLED_FEATURES},'mcp_servers':{},'web_search':'disabled'}}
        if method == 'model/list':
            return {'data':[{'model':'test-model','displayName':'Test model','isDefault':True,
                            'supportedReasoningEfforts':[{'reasoningEffort':'medium'}], 'defaultReasoningEffort':'medium'},
                           {'model':'second-model','defaultReasoningEffort':'low','supportedReasoningEfforts':[{'reasoningEffort':'low'}]}], 'nextCursor':None}
        if method == 'account/read':
            return {'account':{'type':'chatgpt'}}
        if method == 'thread/start':
            FakeRPC.serial += 1
            return {'thread':{'id':'thread-'+str(FakeRPC.serial)}}
        if method == 'thread/resume':
            return {'thread':{'id':params['threadId']}}
        if method == 'turn/start':
            thread = params['threadId']
            turn = 'turn-'+str(len(self.calls))
            if self.mode == 'drop':
                self.dead.set()
                return {'turn':{'id':turn}}
            # A foreign/stale completion must not win the current turn.
            self.events.put({'method':'turn/completed','params':{'threadId':'foreign','turn':{'id':turn,'status':'completed','items':[]}}})
            if self.mode == 'tool':
                self.events.put({'method':'item/started','params':{'threadId':thread,'turnId':turn,'item':{'id':'bad','type':'commandExecution'}}})
            output = {k:'失败和未知保留；尚未独立核验' for k in SCHEMA['required']}
            if self.mode == 'invalid':
                output = {'summary':'cannot accept incomplete output'}
            item = {'id':'final','type':'agentMessage','text':json.dumps(output,ensure_ascii=False)}
            status = 'failed' if self.mode == 'failed' else 'completed'
            self.events.put({'method':'item/completed','params':{'threadId':thread,'turnId':turn,'item':item}})
            self.events.put({'method':'turn/completed','params':{'threadId':thread,'turn':{'id':turn,'status':status,'items':[item]}}})
            return {'turn':{'id':turn}}
        return {}

    def close(self):
        self.dead.set()


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patcher = mock.patch.object(runtime, 'profile', return_value={})
        self.patcher.start()
        self.executable = mock.patch.object(runtime.shutil, 'which', return_value=sys.executable)
        self.executable.start()
        self.addCleanup(self.executable.stop)
        self.connection = runtime.Connection(self.tmp.name, factory=FakeRPC, heartbeat=.02)
        self.snapshot = {'current':{'project':{'id':'p','goal':'原问题'},'source_bridge':{'revision':1}},'source_hash':'v1'}

    def tearDown(self):
        self.connection.close()
        if self.connection.worker:
            self.connection.worker.join(timeout=2)
        self.patcher.stop()
        self.tmp.cleanup()

    def enable(self):
        c = self.connection
        c.configure({'enabled':True,'if_revision':c.revision,'consent':'codex-persistent-management-v1'})
        end = time.monotonic()+3
        while not c.status()['connected'] and time.monotonic()<end:
            time.sleep(.005)
        self.assertTrue(c.status()['connected'])

    def test_default_dry_consent_revision_and_pause(self):
        c = self.connection
        self.assertFalse(c.configured)
        with self.assertRaises(ValueError):c.configure({'enabled':True,'if_revision':0})
        preview = c.configure({'enabled':True,'if_revision':0,'dry':True,'consent':'codex-persistent-management-v1'})
        self.assertTrue(preview['preview']);self.assertFalse(c.enabled);self.assertIsNone(c.worker)
        self.enable()
        with self.assertRaises(ValueError):c.configure({'enabled':False,'if_revision':0})
        client = c.client
        c.configure({'enabled':False,'if_revision':c.revision})
        self.assertTrue(client.dead.is_set());self.assertFalse(c.available());self.assertEqual(c.status()['state'],'paused')

    def test_resume_same_project_and_scope_isolation(self):
        self.enable();c = self.connection
        first = c.analyze(self.snapshot,'p',1)
        c.accept(self.snapshot,'p',1,'reflection',True)
        self.assertIn('未知',first['summary'])
        c.analyze(self.snapshot,'p',1)
        c.accept(self.snapshot,'p',1,'reflection',True)
        methods = [m for m,_ in c.client.calls]
        self.assertEqual(methods.count('thread/start'),1);self.assertEqual(methods.count('thread/resume'),1)
        for project,generation,purpose,revision in [('q',1,'reflection',1),('p',2,'reflection',1),('p',1,'review',1),('p',1,'reflection',2)]:
            value = copy.deepcopy(self.snapshot);value['current']['source_bridge']['revision'] = revision
            c.analyze(value,project,generation,purpose)
        self.assertEqual(c.status('p')['session_count'],4);self.assertEqual(c.status('q')['session_count'],1)
        turns = [p for m,p in c.client.calls if m=='turn/start']
        self.assertTrue(all(p['sandboxPolicy']=={'type':'readOnly','networkAccess':False} for p in turns))
        self.assertTrue(all(p['approvalPolicy']=='on-request' for p in turns))

    def test_service_restart_restores_id_but_starts_no_turn(self):
        self.enable();c=self.connection;c.analyze(self.snapshot,'p',1);c.accept(self.snapshot,'p',1,'reflection',True)
        identifier=c.status('p')['thread_id'];c.close();c.worker.join(timeout=2)
        self.connection=runtime.Connection(self.tmp.name,factory=FakeRPC)
        self.connection.start()
        end=time.monotonic()+3
        while not self.connection.status()['connected'] and time.monotonic()<end:time.sleep(.005)
        self.assertNotIn('turn/start',[m for m,_ in self.connection.client.calls])
        self.connection.analyze(self.snapshot,'p',1)
        resume=[p for m,p in self.connection.client.calls if m=='thread/resume']
        self.assertEqual(resume[0]['threadId'],identifier)

    def test_failed_invalid_and_tool_output_quarantined(self):
        self.enable();c=self.connection
        for generation,mode in enumerate(('failed','invalid','tool'),1):
            if not c.client:self.enable()
            client=c.client;client.mode=mode
            with self.assertRaises((RuntimeError,ValueError)):c.analyze(self.snapshot,'p',generation)
            self.assertTrue(client.dead.is_set());self.assertEqual(c.status('p')['needs_review'],generation)
        self.enable()
        before=len(c.client.calls)
        with self.assertRaisesRegex(RuntimeError,'未重跑'):c.analyze(self.snapshot,'p',3)
        self.assertEqual(before,len(c.client.calls))

    def test_transport_drop_never_replays_turn(self):
        self.enable();c=self.connection;client=c.client;client.mode='drop'
        with self.assertRaises(RuntimeError):c.analyze(self.snapshot,'p',1)
        self.assertEqual([m for m,_ in client.calls].count('turn/start'),1)
        self.enable()
        self.assertNotIn('turn/start',[m for m,_ in c.client.calls])
        self.assertEqual(c.status('p')['needs_review'],1)

    def test_heartbeat_is_read_only(self):
        self.enable();c=self.connection
        time.sleep(1.05)
        self.assertGreater([m for m,_ in c.client.calls].count('account/read'),1)
        self.assertNotIn('turn/start',[m for m,_ in c.client.calls])
        self.assertEqual(c.status()['activity'],'idle')

    def test_idle_drop_reconnects_without_starting_turn(self):
        self.enable();c=self.connection;old=c.client;old.close();c.wake.set()
        end=time.monotonic()+3
        while (c.client is old or not c.status()['connected']) and time.monotonic()<end:time.sleep(.005)
        self.assertIsNot(c.client,old);self.assertTrue(c.status()['connected']);self.assertGreater(c.reconnects,0)
        self.assertNotIn('turn/start',[m for m,_ in c.client.calls])

    def test_stale_summary_is_not_in_resumed_history(self):
        self.enable();c=self.connection;c.analyze(self.snapshot,'p',1)
        with self.assertRaisesRegex(RuntimeError,'回写'):c.analyze(self.snapshot,'p',1)
        c.accept(self.snapshot,'p',1,'reflection',False)
        c.analyze(self.snapshot,'p',1)
        self.assertEqual([m for m,_ in c.client.calls].count('thread/start'),2)
        self.assertNotIn('thread/resume',[m for m,_ in c.client.calls])

    def test_offline_and_paused_do_not_reserve_budget_or_fall_back(self):
        c=self.connection
        c.configure({'enabled':False,'if_revision':0})
        legacy=mock.Mock(side_effect=AssertionError('Paused runtime must not fall back'))
        runner=runtime.Runner(c,legacy)
        m=Manager(self.tmp.name,lambda p:self.snapshot['current'],lambda *args:None,runner=runner,debounce=0)
        m.configure('p',{'enabled':True,'max_calls_per_day':4,'consent':'codex-project-records-v1'})
        for _ in range(3):m.tick()
        self.assertEqual(m.status('p')['used_today'],0);legacy.assert_not_called()
        self.assertEqual(m.status('p')['jobs'][0]['state'],'queued')

    def test_running_session_needs_review_after_restart(self):
        with self.connection.db() as db:db.execute('INSERT INTO sessions(scope,project,thread_id,state,updated) VALUES(?,?,?,?,?)',('scope','p','old-thread','running','old'))
        c=runtime.Connection(self.tmp.name,factory=FakeRPC)
        self.assertEqual(c.status('p')['needs_review'],1);self.assertFalse(c.enabled);c.close()

    def test_bounded_context_rotates_without_resetting_project_budget(self):
        self.enable();c=self.connection
        for _ in range(runtime.SESSION_TURNS+1):
            c.analyze(self.snapshot,'p',1);c.accept(self.snapshot,'p',1,'reflection',True)
        methods=[m for m,_ in c.client.calls]
        self.assertEqual(methods.count('thread/start'),2);self.assertEqual(methods.count('thread/resume'),runtime.SESSION_TURNS-1)

    def test_manager_accepts_only_current_summary_for_reuse(self):
        self.enable();c=self.connection;values={'project':{'id':'p','goal':'原问题'}}
        runner=runtime.Runner(c,lambda value:None)
        m=Manager(self.tmp.name,lambda p:copy.deepcopy(values),lambda *args:None,runner=runner,debounce=0)
        m.configure('p',{'enabled':True,'max_calls_per_day':4,'consent':'codex-project-records-v1'});m.tick()
        self.assertEqual(m.status('p')['jobs'][0]['state'],'succeeded')
        with c.db() as db:self.assertEqual(db.execute('SELECT state FROM sessions').fetchone()[0],'idle')
        original=c.analyze
        def stale(*args,**kwargs):
            output=original(*args,**kwargs);values['tasks']=[{'title':'input changed in flight'}];return output
        c.analyze=stale;values['tasks']=[{'title':'new input'}];m.tick()
        self.assertEqual(m.status('p')['jobs'][0]['state'],'stale')
        with c.db() as db:self.assertEqual(db.execute('SELECT state FROM sessions').fetchone()[0],'discarded')

    def test_manager_rechecks_permission_after_thread_setup_before_turn_submission(self):
        self.enable();c=self.connection;values={'project':{'id':'p','goal':'Synthetic revoked input'}}
        m=Manager(self.tmp.name,lambda p:copy.deepcopy(values),lambda *args:None,
                  runner=runtime.Runner(c,lambda value:None),debounce=0)
        m.configure('p',{'enabled':True,'max_calls_per_day':4,'consent':'codex-project-records-v1'})
        client=c.client;original=client.call
        def revoke(method,params,timeout=15):
            output=original(method,params,timeout)
            if method=='thread/start':m.configure('p',{'enabled':False})
            return output
        client.call=revoke;m.tick()
        self.assertNotIn('turn/start',[method for method,_ in client.calls])
        self.assertNotEqual(m.status('p')['jobs'][0]['state'],'succeeded')

    def test_submission_guard_released_before_waiting_for_completion(self):
        self.enable();c=self.connection;values={'project':{'id':'p','goal':'Synthetic wait boundary'}}
        m=Manager(self.tmp.name,lambda p:copy.deepcopy(values),lambda *args:None,
                  runner=runtime.Runner(c,lambda value:None),debounce=0)
        m.configure('p',{'enabled':True,'max_calls_per_day':4,'consent':'codex-project-records-v1'})
        client=c.client;original=client.events.get;revoked=[]
        def event(*args,**kwargs):
            if not revoked:
                m.configure('p',{'enabled':False});revoked.append(True)
            return original(*args,**kwargs)
        client.events.get=event;m.tick()
        self.assertEqual(revoked,[True])
        self.assertEqual([method for method,_ in client.calls].count('turn/start'),1)
        self.assertNotEqual(m.status('p')['jobs'][0]['state'],'succeeded')

    def test_unsupported_legacy_runner_is_rejected_without_invocation(self):
        called=[];runner=runtime.Runner(self.connection,lambda value:called.append(value))
        runner.set_send_guard(lambda *args:None)
        with self.assertRaisesRegex(RuntimeError,'未发送'):runner.analyze(self.snapshot,'p',1)
        self.assertEqual(called,[])

    def test_legacy_branch_pause_before_launch_is_rejected(self):
        submitted=[]
        def legacy(value,send_guard=None):
            self.connection.configure({'enabled':False,'if_revision':0})
            with send_guard():submitted.append(value)
        runner=runtime.Runner(self.connection,legacy)
        with self.assertRaisesRegex(RuntimeError,'未发送'):runner.analyze(self.snapshot,'p',1)
        self.assertEqual(submitted,[])

    def test_profile_requires_all_tools_disabled(self):
        safe={'features':{k:False for k in runtime.DISABLED_FEATURES},'mcp_servers':{'one':{'enabled':False}},'web_search':'disabled'}
        runtime.verify_profile(safe)
        for field in ('features','mcp_servers','web_search'):
            unsafe=copy.deepcopy(safe)
            if field=='features':unsafe[field]['shell_tool']=True
            elif field=='mcp_servers':unsafe[field]['one']['enabled']=True
            else:unsafe[field]='enabled'
            with self.assertRaises(RuntimeError):runtime.verify_profile(unsafe)

    def test_unavailable_inherited_model_blocks_before_inference_and_budget(self):
        self.enable();c=self.connection;c.inherited_model='desktop-only-alias'
        self.assertTrue(c.status()['connected']);self.assertFalse(c.available())
        m=Manager(self.tmp.name,lambda p:self.snapshot['current'],lambda *args:None,runner=runtime.Runner(c,lambda x:None),debounce=0)
        m.configure('p',{'enabled':True,'max_calls_per_day':4,'consent':'codex-project-records-v1'});m.tick()
        self.assertEqual(m.status('p')['used_today'],0)
        self.assertEqual(m.status('p')['jobs'][0]['state'],'queued')
        with self.assertRaisesRegex(RuntimeError,'可用列表'):c.analyze(self.snapshot,'p',1)
        self.assertNotIn('thread/start',[m for m,_ in c.client.calls])

    def test_model_choice_explicit_dry_revision_and_current_catalog(self):
        self.enable();c=self.connection
        body={'model':'second-model','if_revision':c.revision,'consent':'codex-management-model-v1'}
        preview=c.choose_model(dict(body,dry=True));self.assertTrue(preview['preview'])
        self.assertIsNone(c.selected_model);self.assertEqual(c.model_revision,0)
        for bad in [dict(body,consent=''),dict(body,model='not-advertised'),dict(body,if_revision=-1),dict(body,model='bad\nmodel')]:
            with self.assertRaises(ValueError):c.choose_model(bad)
        value=c.choose_model(body)
        self.assertEqual(value['model_selection']['effective_model'],'second-model')
        self.assertEqual(value['model_selection']['revision'],1)
        c.analyze(self.snapshot,'p',1)
        start=[p for m,p in c.client.calls if m=='thread/start'][-1]
        turn=[p for m,p in c.client.calls if m=='turn/start'][-1]
        self.assertEqual(start['model'],'second-model');self.assertEqual(start['config']['model_reasoning_effort'],'low')
        self.assertEqual(turn['model'],'second-model');self.assertEqual(turn['effort'],'low')
        self.assertNotIn('config/value/write',[m for m,_ in c.client.calls])
        self.assertNotIn('config/batchWrite',[m for m,_ in c.client.calls])

    def test_model_change_preserves_old_failure_and_does_not_replay(self):
        self.enable();c=self.connection;c.client.mode='failed'
        with self.assertRaises(RuntimeError):c.analyze(self.snapshot,'p',1)
        self.enable();client=c.client
        c.choose_model({'model':'second-model','if_revision':c.revision,'consent':'codex-management-model-v1'})
        self.assertNotIn('turn/start',[m for m,_ in client.calls])
        self.assertEqual(c.status('p')['needs_review'],1)
        self.assertEqual(c.status('p')['last_failure']['code'],'turn_failed')
        c.analyze(self.snapshot,'p',1)
        self.assertNotIn('thread/resume',[m for m,_ in client.calls])

    def test_model_selection_survives_restart_without_call(self):
        self.enable();c=self.connection
        c.choose_model({'model':'second-model','if_revision':c.revision,'consent':'codex-management-model-v1'})
        c.close();c.worker.join(timeout=2)
        self.connection=runtime.Connection(self.tmp.name,factory=FakeRPC)
        self.connection.start()
        end=time.monotonic()+3
        while not self.connection.status()['connected'] and time.monotonic()<end:time.sleep(.005)
        self.assertEqual(self.connection.status()['model_selection']['selected_model'],'second-model')
        self.assertNotIn('turn/start',[m for m,_ in self.connection.client.calls])

    def test_model_change_refuses_in_flight_and_paused(self):
        self.enable();c=self.connection
        body={'model':'second-model','if_revision':c.revision,'consent':'codex-management-model-v1'}
        c.call_lock.acquire()
        try:
            with self.assertRaisesRegex(ValueError,'仍在运行'):c.choose_model(body)
        finally:c.call_lock.release()
        c.configure({'enabled':False,'if_revision':c.revision})
        with self.assertRaisesRegex(ValueError,'先启用'):c.choose_model(dict(body,if_revision=c.revision))

    def test_model_cannot_change_between_turn_and_acceptance(self):
        self.enable();c=self.connection;c.analyze(self.snapshot,'p',1)
        body={'model':'second-model','if_revision':c.revision,'consent':'codex-management-model-v1'}
        with self.assertRaisesRegex(ValueError,'回写尚未确认'):c.choose_model(body)
        c.accept(self.snapshot,'p',1,'reflection',True)
        c.choose_model(body)
        with c.db() as db:self.assertEqual(db.execute('SELECT state FROM sessions').fetchone()[0],'idle')

    def test_model_catalog_pagination_text_only_and_fail_closed(self):
        client=mock.Mock()
        client.call.side_effect=[{'data':[{'model':'one','inputModalities':['text']},{'model':'hidden','hidden':True}], 'nextCursor':'next'},
                                 {'data':[{'model':'one'},{'model':'image','inputModalities':['image']},{'model':'two'}]}]
        catalog=runtime.model_catalog(client)
        self.assertEqual([m['model'] for m in catalog],['one','hidden','two'])
        self.assertTrue(catalog[1]['hidden'])
        self.assertTrue(all(call.args[1]['includeHidden'] for call in client.call.call_args_list))
        self.assertEqual(client.call.call_args[0][1]['cursor'],'next')
        client.call.side_effect=None;client.call.return_value={'data':[{'model':'one'}],'nextCursor':'same'}
        with self.assertRaisesRegex(RuntimeError,'不完整'):runtime.model_catalog(client)

    def test_errors_categorized_and_secrets_not_persisted(self):
        for error,code in [('The model is not supported','model_unavailable'),('rate_limit_exceeded','rate_limit'),
                           ('insufficient_quota','quota'),('authentication_error','authentication'),
                           ('ContextWindowExceeded','context_limit'),('timed out','timeout'),('400 invalid_request_error','request_rejected')]:
            item=runtime.safe_failure({'message':error+' sk-private-secret https://secret.test/?token=secret'},'test-model')
            self.assertEqual(item['code'],code);self.assertNotIn('secret',json.dumps(item))
        self.enable();c=self.connection
        c.record_failure({'message':'model is not supported sk-private-secret'}, {'project':'p','thread_id':'t','turn_id':'v'}, 'test-model')
        self.assertEqual(c.status('p')['last_failure']['code'],'model_unavailable')
        self.assertIsNone(c.status('other')['last_failure'])
        self.assertNotIn('private-secret',json.dumps(c.status()))


if __name__=='__main__':unittest.main()
