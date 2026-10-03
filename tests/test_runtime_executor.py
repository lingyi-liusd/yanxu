"""Real database/Gateway integration, isolated subprocess, synthetic model only."""
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class ExecutorIntegration(unittest.TestCase):
    def run_worker(self, mode='normal'):
        with tempfile.TemporaryDirectory(prefix='yanxu-runtime-test-') as directory:
            env = dict(os.environ, RESEARCH_DESK_DATA_DIR=directory, RESEARCH_DESK_TEST_RUNTIME_WORKER='isolated-v1')
            result = subprocess.run([sys.executable, str(pathlib.Path(__file__).resolve()), '--worker',mode],
                                    cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_approved_execution_shared_budget_receipt_and_no_self_trigger(self): self.run_worker()
    def test_pause_quarantines_model_output(self): self.run_worker('pause')
    def test_source_change_quarantines_model_output(self): self.run_worker('stale')
    def test_failure_consumes_budget_without_retry(self): self.run_worker('fail')
    def test_interruption_closes_action_without_rerun(self): self.run_worker('interrupted')
    def test_unlimited_review_inherits_contract_and_usage(self): self.run_worker('unlimited')
    def test_enabling_executor_after_approval_without_new_information_keeps_contract(self): self.run_worker('enable-after-approval')
    def test_large_review_full_coverage_contract_and_single_writeback(self): self.run_worker('batch-normal')
    def test_large_review_restart_does_not_repeat_completed_parts(self): self.run_worker('batch-restart')
    def test_large_review_pause_after_reply_discards_partial_output(self): self.run_worker('batch-pause')
    def test_large_review_source_change_before_next_batch_stops(self): self.run_worker('batch-stale')
    def test_large_review_pause_reenable_does_not_inherit_changed_grant(self): self.run_worker('batch-regrant')
    def test_large_review_tampered_contract_is_rejected(self): self.run_worker('batch-contract')
    def test_malformed_contract_keeps_status_and_http_available(self): self.run_worker('batch-contract-invalid')
    def test_nonobject_contract_is_not_ready_or_execution_authority(self): self.run_worker('batch-contract-nonobject')
    def test_incomplete_contract_is_not_ready_or_execution_authority(self): self.run_worker('batch-contract-incomplete')
    def test_large_review_interruption_unknown_and_no_replay(self): self.run_worker('batch-interrupted')
    def test_large_review_budget_shared_per_part(self): self.run_worker('batch-budget')
    def test_large_review_corrupt_output_never_becomes_final(self): self.run_worker('batch-corrupt')
    def test_large_review_failed_call_not_replayed(self): self.run_worker('batch-fail')
    def test_large_review_final_reply_crash_reconciles_without_model(self): self.run_worker('batch-writeback')
    def test_large_review_noncommitted_writeback_requires_attention(self): self.run_worker('batch-writeback-fail')
    def test_large_review_concurrent_claims_do_not_repeat_parts(self): self.run_worker('batch-parallel')
    def test_large_review_revocation_at_result_commit_quarantines_output(self): self.run_worker('batch-commit-revoke')
    def test_direct_worker_without_isolation_is_rejected_before_server_import(self):
        env=dict(os.environ);env.pop('RESEARCH_DESK_DATA_DIR',None);env.pop('RESEARCH_DESK_TEST_RUNTIME_WORKER',None)
        result=subprocess.run([sys.executable,str(pathlib.Path(__file__).resolve()),'--worker','normal'],
                              cwd=ROOT,env=env,capture_output=True,text=True,timeout=10)
        self.assertNotEqual(result.returncode,0);self.assertIn('isolated runtime test directory',result.stderr)

def worker(mode):
    import json
    sys.path.insert(0,str(ROOT))
    import server
    if mode.startswith('batch-'):
        return batch_worker(server,mode)
    m = server.MANAGER
    calls = []
    def runner(payload):
        calls.append(payload)
        assert 'approved_read_only_contract' in payload
        assert '若另行允许正文，也含所选正文片段' in payload['execution_boundary']
        assert '不额外打开原文件或网页' in payload['execution_boundary']
        assert '不读原文/网页' not in payload['execution_boundary']
        if mode=='pause': m.configure_runtime('p', {'enabled':False})
        if mode=='stale':
            with server.connect() as c:
                state = json.loads(c.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
                state['projects'][0]['name'] = 'changed while model in flight'
                c.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(state),))
        if mode=='fail': raise RuntimeError('synthetic error')
        return {k:'合成输入；科学结果未知' for k in ('summary','changes','risks','next_step','human_decision')}
    m.runner = runner
    root = str(server.DATA)
    with server.connect() as c:
        c.execute('UPDATE state SET body=? WHERE id=1', (json.dumps({'projects':[{'id':'p','workspace':root,'name':'测试'}],'tasks':[],'files':[],'decisions':[]}),))
    m.configure('p', {'enabled':True,'consent':'codex-project-records-v1','max_calls_per_day':1})
    if mode == 'unlimited':
        m.configure_schedule('p', {'max_calls_per_day':None,'summary_interval_minutes':30,
                                  'if_schedule_revision':1,'schedule_consent':'scheduled-codex-management-v1'})
        import datetime
        with m.db() as c:
            for i in range(25):
                c.execute("INSERT INTO jobs(project,signature,generation,state,input,day,kind) VALUES('p',?,1,'failed','{}',?,'reflection')",
                          ('old-failure:'+str(i),datetime.date.today().isoformat()))
    if mode!='enable-after-approval':
        m.configure_runtime('p', {'enabled':True,'consent':'registered-file-metadata-and-review-v1'})
    signature = m.source('p')[1]
    with server.connect() as c:
        revision = server.get_rev(c)
    contract = {'scope':'read_only_review','goal':'核查登记记录','reason':'合成测试',
                'expected_output':'记录与未知分开','success_condition':'来源清楚','failure_condition':'不足写未知',
                'stop_condition':'只读快照，禁止实验和读原文','budget':{'max_progress_reports':1}}
    body = {'project_id':'p','source_hash':signature,'ifRev':revision,'operation':'create','contract':contract}
    server._manager_review(dict(body,dry=True))
    assert not m.status('p')['handoffs']
    server._manager_review(body)
    if mode=='enable-after-approval':
        m.configure_runtime('p', {'enabled':True,'consent':'registered-file-metadata-and-review-v1'})
        assert m.source('p')[1]==signature, 'Empty observations must not stale an approved snapshot'
        assert m.status('p')['handoffs'][0]['ready']
        mode='normal'
    if mode=='interrupted':
        import datetime, time
        plan = m.status('p')['handoffs'][0]
        with m.db() as c:
            c.execute("INSERT INTO jobs(project,signature,generation,state,started,owner,input,day,kind) VALUES(?, ?, 1,'running',?,'interrupted','{}',?,'execution')",
                      ('p','execution:'+str(plan['id'])+':'+signature,time.time()-300,datetime.date.today().isoformat()))
        server._manager_execute('claim','p',plan,None)
        m.tick()
    else:
        assert m.execute_ready('p')
    status = m.status('p')
    count = 0 if mode=='interrupted' else 1
    assert len(calls)==count
    assert status['used_today']==(26 if mode=='unlimited' else 1)
    if mode=='unlimited': assert status['max_calls_per_day'] is None
    assert status['handoffs'][0]['state']=='completed',status
    assert status['handoffs'][0]['outcome']=='UNKNOWN'
    assert not status['handoffs'][0]['orphaned']
    if mode in ('normal','unlimited'): assert m.source('p')[1]==signature, 'own Action/Result must not trigger reflection'
    expected = {'normal':'succeeded','unlimited':'succeeded','pause':'cancelled','stale':'stale','fail':'failed','interrupted':'failed'}[mode]
    assert status['executions'][0]['state']==expected,status
    receipt=status['executions'][0]['writeback_receipt']
    assert receipt['recorded'] and receipt['result_matches_source'] and receipt['evidence_ids']
    assert receipt['outcome']=='UNKNOWN' and receipt['scientific_status']=='NOT_ASSESSED'
    assert status['executions'][0]['contract']==contract
    for _ in range(3): m.tick()
    assert len(calls)==count
    with server.connect() as c:
        result = c.execute('SELECT source_version FROM action_results').fetchone()
        assert result[0]=='sha256:'+signature
        assert c.execute("SELECT count(*) FROM actions WHERE status='finished'").fetchone()[0]==1
        assert c.execute('SELECT count(*) FROM evidence').fetchone()[0]==1
        if mode not in ('normal','unlimited'):
            assert '合成输入' not in c.execute('SELECT summary FROM action_results').fetchone()[0]
    if mode=='normal':
        # The receipt join must not depend on the UI's last-20 handoff window.
        with m.db() as c:
            old=c.execute('SELECT * FROM handoffs WHERE id=?',(status['executions'][0]['handoff_id'],)).fetchone()
            for index in range(21):
                jid=c.execute("INSERT INTO jobs(project,signature,generation,state,input,kind) VALUES('p',?,1,'human_authorized','{}','approval')",('history-window:'+str(index),)).lastrowid
                c.execute("INSERT INTO handoffs(job_id,project,signature,state,suggestion) VALUES(?,?,?,'draft','合成历史窗口')",(jid,'p',signature))
        fresh=m.status('p')
        assert not any(h['id']==old['id'] for h in fresh['handoffs'])
        assert fresh['executions'][0]['handoff_id']==old['id']
        assert fresh['executions'][0]['writeback_receipt']['recorded']
    print('synthetic executor integration PASS')


def batch_worker(server,mode):
    import copy,json,time
    import agent_manager,registered_batches
    m=server.MANAGER
    original_executor=m.executor
    source={'projects':[{'id':'p','workspace':str(server.DATA),'name':'大登记核查测试'}],
            'tasks':[],'files':[{'id':'f'+str(i),'project':'p','name':'合成记录'+str(i),
                'title':'限定条件、负结果、未经独立核验。'*1100} for i in range(14)],'decisions':[]}
    source['files'].sort(key=lambda r:r['id'])
    with server.connect() as c:
        c.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(source),))
    # No paths are registered: this test cannot read user file bytes.
    m.configure('p',{'enabled':True,'consent':'codex-project-records-v1','max_calls_per_day':1 if mode=='batch-budget' else 20})
    m.configure_runtime('p',{'enabled':True,'consent':'registered-file-metadata-and-review-v1'})
    signature=m.source('p')[1]
    assert len(agent_manager.encode(m.source('p')[0]).encode())>agent_manager.MAX_REGISTERED_INPUT_BYTES
    contract={'scope':'read_only_review','goal':'只核查14条合成登记记录','reason':'不改变原资料',
              'expected_output':'明确负结果与未知','success_condition':'逐批覆盖后交付，不等于科学通过',
              'failure_condition':'不能覆盖就报告未知','stop_condition':'暂停、来源变化即停止；不运行工具或实验',
              'budget':{'max_progress_reports':1}}
    with server.connect() as c: rev=server.get_rev(c)
    body={'project_id':'p','ifRev':rev,'source_hash':signature,'operation':'create','contract':contract}
    server._manager_review(dict(body,dry=True)); assert not m.status('p')['handoffs']
    server._manager_review(body)
    hid=m.status('p')['handoffs'][0]['id']
    calls=[]
    def runner(payload):
        assert payload['approved_read_only_contract']==contract
        assert payload['source_hash']==signature
        assert len(agent_manager.encode(payload).encode())<=agent_manager.MAX_REGISTERED_INPUT_BYTES
        calls.append(copy.deepcopy(payload))
        if mode=='batch-pause':m.configure_runtime('p',{'enabled':False})
        if mode=='batch-fail':raise RuntimeError('synthetic batch failure')
        return {k:'合成核查交付；负结果保留，科学未知。' for k in agent_manager.SCHEMA['required']}
    m.runner=runner
    assert m.execute_ready('p') # durable claim and full batch plan, no model yet
    assert len(calls)==0
    assert m.status('p')['used_today']==0
    assert m.status('p')['handoffs'][0]['state']=='claimed'
    assert m.execute_ready('p')
    assert len(calls)==1
    with server.connect() as c: assert c.execute('SELECT count(*) FROM action_results').fetchone()[0]==0
    if mode=='batch-restart':
        workspace=m.workspace
        m=agent_manager.Manager(server.DATA,server._manager_snapshot,lambda *a:None,runner,debounce=0)
        m.workspace=workspace
        m.executor=original_executor;server.MANAGER=m
    elif mode=='batch-stale':
        with server.connect() as c:
            state=json.loads(c.execute('SELECT body FROM state WHERE id=1').fetchone()[0]);state['files'][0]['title']+='改版'
            c.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(state),))
    elif mode=='batch-regrant':
        m.configure_runtime('p',{'enabled':False})
        m.configure_runtime('p',{'enabled':True,'consent':'registered-file-metadata-and-review-v1'})
    elif mode=='batch-contract':
        with m.db() as c:
            changed=dict(contract,goal='未获授权的新目标')
            c.execute('UPDATE handoffs SET contract=? WHERE id=?',(agent_manager.encode(changed),hid))
    elif mode in ('batch-contract-invalid','batch-contract-nonobject','batch-contract-incomplete'):
        damaged={'batch-contract-invalid':'{broken', 'batch-contract-nonobject':'[]',
                 'batch-contract-incomplete':agent_manager.encode({'goal':'缺失判据'})}[mode]
        with m.db() as c:
            c.execute("UPDATE handoffs SET contract=?,state='approved' WHERE id=?",(damaged,hid))
        # Exercise the actual human HTTP route, not just a parsing helper. The
        # listener never starts manager/connection loops or a real model.
        import threading,urllib.request
        http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        try:
            request=urllib.request.Request('http://127.0.0.1:'+str(http.server_port)+'/api/project/manager?project_id=p',
                headers={'Authorization':'Bearer '+server.TOKEN})
            with urllib.request.urlopen(request,timeout=5) as response:
                assert response.status==200
                readback=json.load(response)
            plan=readback['handoffs'][0]
            assert not plan['ready'] and not plan['contract_valid'],plan
            assert plan['contract_error'] and plan['state']=='approved'
            assert plan['contract_parse_error']==(mode!='batch-contract-incomplete')
            assert readback['executions'][0]['contract']==contract
            assert readback['executions'][0]['approval_record_changed']
            assert readback['used_today']==1 and len(calls)==1
            assert m.status('p')['handoffs'][0]==plan
            with m.db() as c:
                assert c.execute('SELECT contract FROM handoffs WHERE id=?',(hid,)).fetchone()[0]==damaged
        finally:
            http.shutdown();http.server_close();thread.join(timeout=3)
            with m.db() as c:c.execute("UPDATE handoffs SET state='claimed' WHERE id=?",(hid,))
    elif mode=='batch-interrupted':
        with m.db() as c:
            jid=m.status('p')['executions'][0]['id']
            c.execute("UPDATE jobs SET state='running',started=? WHERE id=?",(time.time()-241,jid))
            c.execute("UPDATE reflection_parts SET state='running',started=?,day=? WHERE job_id=? AND ordinal=1",
                      (time.time()-241,__import__('datetime').date.today().isoformat(),jid))
    elif mode=='batch-corrupt':
        with m.db() as c:
            c.execute("UPDATE reflection_parts SET output='{}' WHERE ordinal=0 AND job_id=(SELECT id FROM jobs WHERE kind='execution')")
    elif mode=='batch-parallel':
        import concurrent.futures
        other=agent_manager.Manager(server.DATA,server._manager_snapshot,lambda *a:None,runner,debounce=0)
        other.workspace=m.workspace
        other.executor=original_executor
        with concurrent.futures.ThreadPoolExecutor() as pool:
            list(pool.map(lambda manager:manager.execute_ready('p'),[m,other]))
    elif mode in ('batch-writeback','batch-writeback-fail','batch-commit-revoke'):
        def interrupted(operation,project,record,report):
            if operation=='complete':
                if mode=='batch-commit-revoke':
                    m.configure_runtime('p',{'enabled':False})
                    return original_executor(operation,project,record,report)
                if mode=='batch-writeback':original_executor(operation,project,record,report)
                raise RuntimeError('synthetic local writeback failure')
            return original_executor(operation,project,record,report)
        m.executor=interrupted
    for _ in range(40):
        m.recover_execution()
        status=m.status('p')
        if status['executions'][0]['state'] not in ('queued','running','review_ready'):break
        if not m.execute_ready('p'):break
    m.recover_execution();status=m.status('p');job=status['executions'][0]
    expected={'batch-normal':'succeeded','batch-restart':'succeeded','batch-parallel':'succeeded',
        'batch-writeback':'succeeded','batch-writeback-fail':'failed_orphaned',
        'batch-stale':'stale','batch-pause':'cancelled','batch-regrant':'cancelled',
        'batch-contract':'cancelled','batch-contract-invalid':'cancelled',
        'batch-contract-nonobject':'cancelled','batch-contract-incomplete':'cancelled',
        'batch-interrupted':'failed','batch-corrupt':'failed',
        'batch-fail':'failed','batch-budget':'queued','batch-commit-revoke':'cancelled'}[mode]
    assert job['state']==expected,(mode,job['state'],job['error'],signature,status['source_hash'])
    assert job['handoff_id']==hid and job['contract']==contract
    assert job['contract_origin']=='execution_context'
    assert job['approval_record_changed']==mode.startswith('batch-contract')
    assert job['contract_hash']==__import__('action_contracts').digest(contract)
    assert job['writeback_receipt']['recorded']==(mode not in ('batch-budget','batch-writeback-fail'))
    assert job['writeback_receipt']['scientific_status']=='NOT_ASSESSED'
    assert status['used_today']==len(calls)+(1 if mode=='batch-interrupted' else 0)
    assert len({registered_batches.digest(p) for p in calls})==len(calls),'batch replay'
    if mode=='batch-budget':assert len(calls)==1
    with server.connect() as c:
        c.row_factory=__import__('sqlite3').Row
        results=c.execute('SELECT * FROM action_results').fetchall()
        assert len(results)==(0 if mode in ('batch-budget','batch-writeback-fail') else 1)
        if results:
            assert results[0]['outcome']=='UNKNOWN'
            assert results[0]['source_version']=='sha256:'+signature
            assert c.execute('SELECT count(*) FROM evidence').fetchone()[0]==1
            if expected!='succeeded':assert '合成核查交付' not in results[0]['summary']
        assert c.execute('SELECT count(*) FROM actions').fetchone()[0]==1
    if expected=='succeeded':
        coverage=job['registered_coverage'];assert coverage['aggregation_complete']
        assert coverage['leaf_total']==coverage['leaf_replied']
        records=[r for p in calls if p['registered_batch']['stage']=='leaf' for r in p['current'].get('files',[])]
        assert records==source['files']
        assert m.source('p')[1]==signature
        with m.db() as c: saved=c.execute('SELECT contract FROM handoffs WHERE id=?',(hid,)).fetchone()[0]
        assert saved==agent_manager.encode(contract)
    count=len(calls)
    with m.db() as c: finished=c.execute('SELECT finished FROM jobs WHERE id=?',(job['id'],)).fetchone()[0]
    for _ in range(3):m.recover_execution();m.execute_ready('p')
    assert len(calls)==count,'terminal review silently retried'
    with m.db() as c: assert c.execute('SELECT finished FROM jobs WHERE id=?',(job['id'],)).fetchone()[0]==finished,'terminal receipt self-trigger loop'
    print('synthetic batched review integration PASS',mode)

if __name__=='__main__':
    if '--worker' in sys.argv:
        # Guard before importing server: a manual worker invocation must never open default data.
        directory=pathlib.Path(os.environ.get('RESEARCH_DESK_DATA_DIR','')).resolve()
        if (os.environ.get('RESEARCH_DESK_TEST_RUNTIME_WORKER')!='isolated-v1'
                or not directory.name.startswith('yanxu-runtime-test-')
                or directory.parent!=pathlib.Path(tempfile.gettempdir()).resolve()):
            raise SystemExit('An isolated runtime test directory is required; server was not imported.')
        worker(sys.argv[-1])
    else: unittest.main()
