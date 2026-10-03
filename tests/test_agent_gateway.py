import json
import os
import pathlib
import shutil
import socket
import sqlite3
import datetime
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
NODE = shutil.which('node')


class AgentGatewayCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='research-desk-agent-')
        self.dir = pathlib.Path(self.tmp.name)
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        self.port = sock.getsockname()[1]
        sock.close()
        self.base = 'http://127.0.0.1:' + str(self.port)
        env = os.environ.copy()
        env.update(RESEARCH_DESK_DATA_DIR=str(self.dir), PORT=str(self.port))
        for key in ('RESEARCH_FOCUS_API_URL','RESEARCH_FOCUS_API_KEY','RESEARCH_FOCUS_MODEL'):
            env.pop(key, None)
        self.proc = subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=str(ROOT),env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        deadline = time.time() + 5
        while time.time() < deadline:
            token_path = self.dir/'api-token'
            if token_path.exists():
                self.human_token = token_path.read_text().strip()
                try:
                    if self.request('/api/state')[0] == 200: break
                except Exception: pass
            time.sleep(.05)
        else: self.fail('server did not start')
        code, _, s = self.request('/api/action',{'collection':'projects','item':{'id':'p1','name':'科研测试项目','goal':'核对迁移链路','stages':['验证']}})
        self.assertEqual(code,200)
        code, _, s = self.request('/api/action',{'collection':'tasks','item':{'id':'t1','project':'p1','title':'核对 Agent 事件链','note':'人类原始笔记，不可被 Agent 改写'}})
        self.assertEqual(code,200)
        code, _, self.connection = self.request('/api/agents/connect',{'project_id':'p1','name':'Codex','permission':'EXECUTE'})
        self.assertEqual(code,200)
        self.agent_token = self.connection['token']
        self.assertIn('[mcp_servers.',self.connection['codex_config_toml'])
        self.assertIn('RESEARCH_DESK_AGENT_TOKEN',self.connection['codex_config_toml'])
        self.assertNotIn('default_tools_approval_mode',self.connection['codex_config_toml'])
        self.assertIn('required = false',self.connection['codex_config_toml'])
        self.assertNotIn('[features]',self.connection['codex_config_toml'])
        self.assertIn('codex mcp add ',self.connection['codex_command'])

    def tearDown(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=3)
        self.tmp.cleanup()

    def test_codex_generated_config_isolated_parse_and_no_global_write(self):
        executable = shutil.which('codex')
        if not executable: self.skipTest('Codex CLI unavailable')
        real = pathlib.Path.home()/'.codex'/'config.toml'
        before = real.read_bytes() if real.exists() else None
        with tempfile.TemporaryDirectory(prefix='desk-config-check-') as directory:
            config = pathlib.Path(directory)/'config.toml'
            config.write_text('[features]\nshell_tool = false\n\n'+self.connection['codex_config_toml'])
            env = os.environ.copy(); env['CODEX_HOME'] = directory
            result = subprocess.run([executable,'mcp','list','--json'],env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,'Generated config failed isolated CLI parse')
            config.write_text(config.read_text()+'\n[features]\nweb_search = false\n')
            broken = subprocess.run([executable,'mcp','list','--json'],env=env,capture_output=True,text=True,timeout=15)
            self.assertNotEqual(broken.returncode,0)
        self.assertEqual(real.read_bytes() if real.exists() else None,before)

    def test_manager_context_and_human_consent(self):
        code, _, status = self.request('/api/project/manager?project_id=p1')
        self.assertEqual(code,200)
        self.assertFalse(status['enabled'])
        self.assertEqual(status['used_today'],0)
        code, _, context = self.request('/api/project/context?project_id=p1')
        self.assertEqual(code,200)
        self.assertIsNone(context['management']['latest_analysis'])
        brief = context['management']['resume_brief']
        self.assertEqual(brief['handoff']['project_id'],'p1')
        self.assertEqual(brief['source_hash'],status['source_hash'])
        self.assertEqual(len(brief['cards']),3)
        self.assertEqual(brief['next_explanation'],status['resume_brief']['next_explanation'])
        self.assertEqual(brief['next_explanation'],brief['handoff']['next_navigation'])
        self.assertEqual(brief['cards'][2]['target']['id'],'t1')
        self.assertEqual(status['used_today'],0)
        code, _, _ = self.request('/api/project/manager', {'project_id':'p1','enabled':True})
        self.assertEqual(code,400)
        code, _, _ = self.request('/api/project/manager?project_id=p1', token=self.agent_token)
        self.assertEqual(code,401)

    def test_context_bound_claim_rejects_stale_and_accepts_current(self):
        _, _, status=self.request('/api/project/manager?project_id=p1')
        old=status['source_hash']
        self.request('/api/action',{'collection':'tasks','item':{'id':'new-task','project':'p1','title':'新增边界'}})
        body={'phase':'claim','goal':'接续版本测试','reason':'现有范围','expected_output':'记录','context_hash':old}
        self.assertEqual(self.agent('activity',body)[0],409)
        with sqlite3.connect(self.dir/'desk.sqlite3') as c:
            self.assertEqual(c.execute('SELECT count(*) FROM actions WHERE project_id=?',('p1',)).fetchone()[0],0)
        _, _, status=self.request('/api/project/manager?project_id=p1')
        self.assertEqual(self.agent('activity',dict(body,context_hash=status['source_hash']))[0],200)
        self.assertEqual(status['used_today'],0)

    def test_exact_independent_work_concurrent_claim_is_atomic(self):
        from concurrent.futures import ThreadPoolExecutor
        _, _, second=self.request('/api/agents/connect',{'project_id':'p1','name':'Other','permission':'EXECUTE'})
        body={'phase':'claim','goal':'同一核查','reason':'合成测试','expected_output':'同一产物','dependencies':['x','y']}
        with ThreadPoolExecutor(2) as pool:
            outcomes=list(pool.map(lambda token:self.request('/api/agent/activity',body,token=token)[0], [self.agent_token,second['token']]))
        self.assertEqual(sorted(outcomes),[200,409])
        with sqlite3.connect(self.dir/'desk.sqlite3') as c:
            self.assertEqual(c.execute('SELECT count(*) FROM actions WHERE project_id=?',('p1',)).fetchone()[0],1)

    def test_different_work_not_fuzzily_blocked(self):
        _, _, second=self.request('/api/agents/connect',{'project_id':'p1','name':'Other','permission':'EXECUTE'})
        body={'phase':'claim','goal':'同一领域','reason':'不同明确对象','expected_output':'数据集A报告'}
        self.assertEqual(self.agent('activity',body)[0],200)
        self.assertEqual(self.request('/api/agent/activity',dict(body,expected_output='数据集B报告'),token=second['token'])[0],200)

    def test_resume_inherits_real_action_budget_without_new_call(self):
        code, _, action = self.agent('activity',{'phase':'claim','goal':'一次核查','reason':'接续测试',
            'expected_output':'记录','budget':{'max_progress_reports':3},'stop_condition':'一次后停止'})
        self.assertEqual(code,200)
        aid=action['action_id']
        self.assertEqual(self.agent('activity',{'phase':'progress','action_id':aid,'summary':'已用一次进度报告'})[0],200)
        _, _, before=self.request('/api/project/manager?project_id=p1')
        _, _, context=self.agent('context')
        h=context['management']['resume_brief']['handoff']
        self.assertEqual(h['active_actions'][0]['progress_reports_used'],1)
        self.assertEqual(h['active_actions'][0]['stop_condition'],'一次后停止')
        self.assertEqual(h['management_budget']['used_today'],0)
        _, _, after=self.request('/api/project/manager?project_id=p1')
        self.assertEqual(before['source_hash'],after['source_hash'])
        self.assertEqual(after['used_today'],0)

    def test_source_scope_human_only_dry_and_revision(self):
        _, _, status = self.request('/api/project/manager?project_id=p1')
        self.assertFalse(status['source_bridge']['enabled'])
        body = {'project_id':'p1', 'enabled':True, 'send_content':False,
                'folders':[], 'threads':['01234567-1234-1234-1234-123456789abc'],
                'if_revision':0, 'consent':'selected-local-sources-v1', 'dry':True}
        self.assertEqual(self.request('/api/project/manager/sources',body,token=self.agent_token)[0],401)
        self.assertEqual(self.request('/api/project/manager/sources',dict(body,consent=''))[0],400)
        self.assertEqual(self.request('/api/project/manager/sources',dict(body,send_content=True))[0],400)
        self.assertEqual(self.request('/api/project/manager/sources',body)[0],200)
        _, _, status = self.request('/api/project/manager?project_id=p1')
        self.assertEqual(status['source_bridge']['revision'],0)
        self.assertEqual(self.request('/api/project/manager/sources',dict(body,dry=False))[0],200)
        self.assertEqual(self.request('/api/project/manager/sources',dict(body,dry=False))[0],400)
        self.assertEqual(self.request('/api/project/manager/sources',dict(body,enabled=False,if_revision=1,dry=False))[0],200)
        _, _, status = self.request('/api/project/manager?project_id=p1')
        self.assertFalse(status['source_bridge']['enabled'])
        self.assertEqual(status['used_today'],0)

    def seed_management_handoff(self):
        code, _, status = self.request('/api/project/manager?project_id=p1')
        self.assertEqual(code,200)
        signature = status['source_hash']
        output = {key:'只读核对，科学结果未知' for key in ('summary','changes','risks','next_step','human_decision')}
        # Fixture-only completed synthetic model call; budget exhausted so no real model is invoked.
        with sqlite3.connect(self.dir/'manager.sqlite3') as c:
            c.execute('INSERT OR REPLACE INTO policies(project,enabled,budget,generation) VALUES(?,1,1,1)', ('p1',))
            job = c.execute("INSERT INTO jobs(project,signature,generation,state,available,input,output,day) VALUES(?,?,1,'succeeded',0,'{}',?,?)",
                            ('p1',signature,json.dumps(output),datetime.date.today().isoformat())).lastrowid
            handoff = c.execute("INSERT INTO handoffs(job_id,project,signature,state,suggestion) VALUES(?,? ,?,'draft','核对既有依据')", (job,'p1',signature)).lastrowid
        _, _, context = self.request('/api/project/context?project_id=p1')
        contract = {'scope':'read_only_review','goal':'核对既有依据','reason':'确认现有来源版本',
                    'expected_output':'一个带来源与未知边界的核查报告','success_condition':'来源与版本可核对',
                    'failure_condition':'来源不可访问，明确记录未知','stop_condition':'只读，不实验、不改文件；提交报告后停止',
                    'budget':{'max_progress_reports':3}}
        return {'project_id':'p1','handoff_id':handoff,'source_hash':signature,'ifRev':context['rev'],
                'operation':'approve','contract':contract}

    def test_management_approved_claim_and_negative_receipt(self):
        body = self.seed_management_handoff()
        code, _, _ = self.request('/api/agent/management/claim',{'handoff_id':body['handoff_id']},token=self.agent_token)
        self.assertEqual(code,409)
        code, _, _ = self.request('/api/project/manager/handoff',dict(body,dry=True))
        self.assertEqual(code,200)
        _, _, status = self.request('/api/project/manager?project_id=p1')
        self.assertEqual(status['handoffs'][0]['state'],'draft')
        self.assertEqual(self.request('/api/project/manager/handoff',body)[0],200)
        _, _, context = self.request('/api/agent/context',token=self.agent_token)
        self.assertEqual(len(context['management']['ready_handoffs']),1)
        code, _, claim = self.request('/api/agent/management/claim',{'handoff_id':body['handoff_id'],'goal':'试图改变契约'},token=self.agent_token)
        self.assertEqual(code,200)
        _, _, actions = self.request('/api/agent/actions',token=self.agent_token)
        action = next(a for a in actions['actions'] if a['id']==claim['action_id'])
        self.assertEqual(action['goal'],body['contract']['goal'])
        _, _, retry = self.request('/api/agent/management/claim',{'handoff_id':body['handoff_id']},token=self.agent_token)
        self.assertTrue(retry['already_claimed'])
        self.assertEqual(retry['action_id'],claim['action_id'])
        code, _, result = self.request('/api/agent/result',{'action_id':claim['action_id'],'outcome':'failure',
                     'summary':'来源不可访问，没有科学成功结论','source_ref':'synthetic://source','source_version':'test-v1'},token=self.agent_token)
        self.assertEqual(code,200)
        _, _, status = self.request('/api/project/manager?project_id=p1')
        receipt = status['handoffs'][0]
        self.assertEqual(receipt['state'],'completed')
        self.assertEqual(receipt['result_id'],result['result_id'])
        self.assertEqual(receipt['outcome'],result['outcome'])
        self.assertEqual(receipt['verification_status'],'UNVERIFIED')

    def test_management_stale_revision_scope_and_permissions(self):
        body = self.seed_management_handoff()
        self.assertEqual(self.request('/api/project/manager/handoff',body,token=self.agent_token)[0],401)
        unsafe = dict(body,contract=dict(body['contract'],scope='experiment'))
        self.assertEqual(self.request('/api/project/manager/handoff',unsafe)[0],400)
        stale_revision = dict(body,ifRev=body['ifRev']-1)
        self.assertEqual(self.request('/api/project/manager/handoff',stale_revision)[0],400)
        self.assertEqual(self.request('/api/project/manager/handoff',body)[0],200)
        self.request('/api/action',{'collection':'tasks','item':{'id':'t1','project':'p1','title':'来源已修改'}})
        code, _, _ = self.request('/api/agent/management/claim',{'handoff_id':body['handoff_id']},token=self.agent_token)
        self.assertEqual(code,409)
        _, _, status = self.request('/api/project/manager?project_id=p1')
        self.assertTrue(status['handoffs'][0]['stale'])

    def test_management_concurrent_single_owner(self):
        import concurrent.futures
        body = self.seed_management_handoff()
        self.assertEqual(self.request('/api/project/manager/handoff',body)[0],200)
        _, _, second = self.request('/api/agents/connect',{'project_id':'p1','name':'Second','permission':'EXECUTE'})
        with concurrent.futures.ThreadPoolExecutor() as pool:
            replies = list(pool.map(lambda token:self.request('/api/agent/management/claim',{'handoff_id':body['handoff_id']},token=token), [self.agent_token,second['token']]))
        self.assertEqual(sorted(r[0] for r in replies),[200,409])
        _, _, actions = self.request('/api/agent/actions',token=self.agent_token)
        self.assertEqual(len(actions['actions']),1)

    def test_management_pause_and_busy_agent(self):
        body = self.seed_management_handoff()
        self.assertEqual(self.request('/api/project/manager/handoff',body)[0],200)
        self.request('/api/agent/activity',{'phase':'claim','goal':'另一个既有行动','reason':'测试原有行动锁','expected_output':'已有行动报告'},token=self.agent_token)
        code, _, _ = self.request('/api/agent/management/claim',{'handoff_id':body['handoff_id']},token=self.agent_token)
        self.assertEqual(code,409)
        self.assertEqual(self.request('/api/project/manager',{'project_id':'p1','enabled':False})[0],200)
        code, _, _ = self.request('/api/agent/management/claim',{'handoff_id':body['handoff_id']},token=self.agent_token)
        self.assertEqual(code,409)

    @unittest.skipUnless(NODE,'node required')
    def test_real_mcp_management_handoff(self):
        body = self.seed_management_handoff()
        self.assertEqual(self.request('/api/project/manager/handoff',body)[0],200)
        context = self.mcp('project.get_context')
        self.assertEqual(len(context['management']['ready_handoffs']),1)
        claim = self.mcp('project.claim_management_action',{'handoff_id':body['handoff_id']})
        self.assertEqual(claim['approved_contract'],body['contract'])
        result = self.mcp('project.record_result',{'action_id':claim['action_id'],'outcome':'inconclusive',
            'summary':'隔离MCP协议测试；研究问题未验证','source_ref':'synthetic://mcp-management-test','source_version':'v2-test'})
        self.assertEqual(result['verification_status'],'UNVERIFIED')
        _, _, status = self.request('/api/project/manager?project_id=p1')
        self.assertEqual(status['handoffs'][0]['state'],'completed')

    def test_restore_invalidates_pending_management_approval(self):
        body = self.seed_management_handoff()
        self.assertEqual(self.request('/api/project/manager/handoff',body)[0],200)
        _, _, backup = self.request('/api/backup')
        _, rev, _ = self.request('/api/state')
        self.assertEqual(self.request('/api/restore',{'backup':backup,'ifRev':rev})[0],200)
        _, _, status = self.request('/api/project/manager?project_id=p1')
        self.assertEqual(status['handoffs'][0]['state'],'invalidated')
        self.assertFalse(status['handoffs'][0]['ready'])
        # Restore intentionally revokes old Agent credentials too; new Agent still cannot claim it.
        _, _, reconnected = self.request('/api/agents/connect',{'project_id':'p1','name':'Reconnected','permission':'EXECUTE'})
        code, _, _ = self.request('/api/agent/management/claim',{'handoff_id':body['handoff_id']},token=reconnected['token'])
        self.assertEqual(code,409)

    def request(self,path,body=None,token=None,method=None):
        payload = None if body is None else json.dumps(body,ensure_ascii=False).encode()
        req = urllib.request.Request(self.base+path,data=payload,
              headers={'Authorization':'Bearer '+(token or self.human_token),'Content-Type':'application/json'},
              method=method or ('POST' if body is not None else 'GET'))
        try:
            with urllib.request.urlopen(req,timeout=4) as res:
                return res.status,int(res.headers.get('X-Rev') or 0),json.loads(res.read())
        except urllib.error.HTTPError as exc:
            return exc.code,int(exc.headers.get('X-Rev') or 0),json.loads(exc.read())

    def agent(self,path,body=None,method=None):
        return self.request('/api/agent/'+path,body,self.agent_token,method)

    def mcp(self,name,args=None):
        env=os.environ.copy()
        env.update(RESEARCH_DESK_BASE_URL=self.base,RESEARCH_DESK_AGENT_TOKEN=self.agent_token,RESEARCH_DESK_PROJECT_ID='p1')
        msgs=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'gateway-test','version':'1.0'}}},
              {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':name,'arguments':args or {}}}]
        proc=subprocess.run([NODE,str(ROOT/'mcp-server.js')],cwd=str(ROOT),env=env,
             input='\n'.join(json.dumps(x,ensure_ascii=False) for x in msgs)+'\n',text=True,capture_output=True,timeout=10)
        self.assertEqual(proc.returncode,0,proc.stderr)
        rows=[json.loads(x) for x in proc.stdout.splitlines()]
        self.assertTrue(rows)
        self.assertTrue(all(row.get('jsonrpc') == '2.0' for row in rows), rows)
        self.assertEqual(next(row['result'] for row in rows if row.get('id') == 1)['protocolVersion'],'2024-11-05')
        result=next(x['result'] for x in rows if x.get('id')==2)
        self.assertFalse(result.get('isError'),result)
        return json.loads(result['content'][0]['text'])

    @unittest.skipUnless(NODE,'node required')
    def test_project_os_context_independent_action_artifact_and_result(self):
        context=self.mcp('project.get_context')
        self.assertEqual(context['project']['id'],'p1')
        self.assertIn('goal',context)
        self.assertIn('current_state',context)
        self.assertIn('artifacts',context)
        self.assertIn('decisions',context)
        self.assertEqual(context['active_tasks'][0]['id'],'t1')
        claim=self.mcp('project.claim_action',{'title':'核对通用项目闭环','reason':'需要验证无旧任务的 Action',
            'expected_output':'一份可追溯的输出','success_condition':'输出可复核','failure_condition':'来源缺失',
            'context_hash':context['management']['resume_brief']['source_hash'],
            'budget':{'max_progress_reports':3},'stop_condition':'结果登记后停止'})
        aid=claim['action_id']
        code,_,status=self.request('/api/project-focus?scope=p1')
        self.assertEqual(code,200)
        self.assertTrue(status['needs_generation'])
        code,_,focus=self.request('/api/project-focus',{'scope':'p1','trigger':'task_changed'})
        self.assertEqual(code,200)
        self.assertEqual(focus['focus']['entity_type'],'action')
        self.assertEqual(focus['focus']['entity_id'],aid)
        artifact=self.mcp('project.add_artifact',{'action_id':aid,'type':'report','title':'项目闭环报告',
            'reference':'reports/project-check.md','source_version':'sha256:test-v1','summary':'隔离测试产物'})
        self.assertTrue(artifact['artifact_id'].startswith('artifact-'))
        result=self.mcp('project.record_result',{'action_id':aid,'outcome':'partial','summary':'流程可运行，独立核验未完成',
            'source_ref':'tests/test_agent_gateway.py','source_version':'test-v1'})
        self.assertEqual(result['normalized_status'],'partial')
        self.assertEqual(result['verification_status'],'UNVERIFIED')
        self.assertIn('current_state',self.mcp('project.get_state'))
        self.assertIn('entity_type',self.mcp('project.get_focus'))
        self.assertIn('actions',self.mcp('project.get_actions'))
        self.assertIn('artifacts',self.mcp('project.get_artifacts'))
        self.assertIn('evidence',self.mcp('project.get_evidence'))
        self.assertIn('results',self.mcp('project.get_results'))
        self.assertIn('decisions',self.mcp('project.get_decisions'))
        self.assertIn('events',self.mcp('project.get_events'))
        code,_,artifacts=self.request('/api/project/artifacts?project_id=p1')
        self.assertEqual(code,200)
        self.assertEqual(artifacts['artifacts'][0]['type'],'report')
        code,_,results=self.request('/api/project/results?project_id=p1')
        self.assertEqual(code,200)
        self.assertEqual(results['results'][0]['outcome'],'PARTIAL')
        self.assertEqual(results['results'][0]['normalized_status'],'partial')
        code,_,today=self.request('/api/project/today?project_id=p1')
        self.assertEqual(code,200)
        self.assertIn('where_are_we',today)
        self.assertIn('what_needs_me',today)
        code,_,state=self.request('/api/state')
        self.assertEqual(code,200)
        self.assertEqual(state['tasks'][0]['note'],'人类原始笔记，不可被 Agent 改写')
        self.assertEqual(self.mcp('research.get_project_context')['project']['id'],'p1')

    def test_project_description_fields_and_legacy_project_roundtrip(self):
        code,rev,_=self.request('/api/state')
        self.assertEqual(code,200)
        item={'id':'software','name':'软件开发','description':'维护一个长期软件产品',
              'goal':'发布稳定版本','success_definition':'测试和发布检查完成',
              'current_state':'登录回调仍有阻塞','constraints':['不能丢失用户数据'],
              'workspace':'/tmp/software','type':'Software','stages':['开发','验证']}
        code,_,_=self.request('/api/action',{'ifRev':rev,'ops':[{'collection':'projects','item':item}]})
        self.assertEqual(code,200)
        code,_,context=self.request('/api/project/context?project_id=software')
        self.assertEqual(code,200)
        self.assertEqual(context['project']['description'],item['description'])
        self.assertEqual(context['goal']['success_definition'],item['success_definition'])
        self.assertEqual(context['current_state']['recorded'],item['current_state'])
        self.assertEqual(context['constraints'],item['constraints'])
        code,_,legacy=self.request('/api/state')
        self.assertEqual(code,200)
        self.assertEqual(len(legacy['tasks']),1)
        self.assertEqual(legacy['projects'][0]['name'],'科研测试项目')

    def test_blocking_human_decision_becomes_focus_then_clears(self):
        code,_,decision=self.agent('decision-request',{
            'question':'是否暂停当前方向？','context':'需要人选择后续范围',
            'options':['暂停','继续'],'blocking':True})
        self.assertEqual(code,200)
        did=decision['decision_id']
        code,_,focus=self.request('/api/project-focus?scope=p1')
        self.assertEqual(code,200)
        self.assertFalse(focus['needs_generation'])
        self.assertEqual(focus['focus']['entity_type'],'decision')
        self.assertEqual(focus['focus']['entity_id'],did)
        code,_,resolved=self.request('/api/project/decisions/'+did,{
            'status':'approved','resolution':'暂不暂停，保留现有边界'})
        self.assertEqual(code,200)
        self.assertEqual(resolved['status'],'approved')
        code,_,focus=self.request('/api/project-focus?scope=p1')
        self.assertEqual(code,200)
        self.assertFalse(focus['needs_generation'])
        self.assertNotEqual(focus['focus']['entity_type'],'decision')

    def test_legacy_decision_visible_in_project_context_and_today(self):
        code,rev,_=self.request('/api/state')
        self.assertEqual(code,200)
        decision={'id':'old-decision','project':'p1','title':'旧决策节点',
                  'question':'是否调整验证范围？','status':'待决','recommendation':'等待人审'}
        code,_,_=self.request('/api/action',{'ifRev':rev,'collection':'decisions','item':decision})
        self.assertEqual(code,200)
        code,_,context=self.request('/api/project/context?project_id=p1')
        self.assertEqual(code,200)
        self.assertIn('old-decision',[d['id'] for d in context['decisions']])
        self.assertIn('old-decision',[d['id'] for d in context['legacy_decisions']])
        code,_,today=self.request('/api/project/today?project_id=p1')
        self.assertEqual(code,200)
        self.assertEqual(today['decision']['source'],'legacy')
        self.assertEqual(today['pulse'],'Needs Decision')

    @unittest.skipUnless(NODE,'node required')
    def test_real_mcp_action_evidence_planner_today_chain(self):
        self.assertFalse(self.connection['connected'])
        context=self.mcp('research.get_project_context')
        self.assertEqual(context['project']['id'],'p1')
        self.assertIn('t1',[x['id'] for x in context['active_tasks']])
        code,_,agents=self.request('/api/agents')
        self.assertTrue(agents['agents'][0]['connected'])
        before=self.request('/api/research-focus?scope=p1')[2]['context_hash']
        claim=self.mcp('research.claim_action',{'task_id':'t1','reason':'验证 Agent Gateway 与真实 MCP 事件顺序','expected_output':'可追溯的协议测试结果','budget':{'max_progress_reports':2}})
        aid=claim['action_id']
        self.mcp('research.report_activity',{'action_id':aid,'phase':'start','summary':'开始验证 MCP 协议'})
        code,_,today=self.request('/api/research/today?project_id=p1')
        self.assertEqual(today['pulse'],'Advancing')
        self.assertEqual(today['action']['id'],aid)
        self.mcp('research.report_activity',{'action_id':aid,'phase':'progress','summary':'完成握手与 Running 状态核验'})
        result=self.mcp('research.record_result',{'action_id':aid,'outcome':'INCONCLUSIVE','summary':'协议链路工作；科研主张未验证','source_ref':'tests/test_agent_gateway.py::test_real_mcp_action_evidence_planner_today_chain','source_version':'test-run-1','evidence_title':'协议链路核验'})
        self.assertEqual(result['scientific_status'],'INCONCLUSIVE')
        self.assertEqual(result['delivery_status'],'finished')
        self.assertEqual(result['verification_status'],'UNVERIFIED')
        code,_,ledger=self.request('/api/research/evidence?project_id=p1')
        self.assertEqual(ledger['evidence'][0]['id'],result['evidence_id'])
        self.assertEqual(ledger['evidence'][0]['source_version'],'test-run-1')
        focus=self.request('/api/research-focus?scope=p1')[2]
        self.assertNotEqual(focus['context_hash'],before)
        self.assertFalse(focus['needs_generation'])
        self.assertEqual(focus['focus']['focus_type'],'review')
        code,_,today=self.request('/api/research/today?project_id=p1')
        self.assertIsNone(today['action'])
        self.assertEqual(today['focus']['focus_id'],focus['focus']['focus_id'])
        code,_,events=self.request('/api/research/events?project_id=p1')
        kinds=[e['type'] for e in reversed(events['events'])]
        for kind in ('agent.connected','agent.claimed','agent.start','agent.progress','result.inconclusive','evidence.added','agent.finish','focus.changed'):
            self.assertIn(kind,kinds)
        self.assertLess(kinds.index('agent.claimed'),kinds.index('result.inconclusive'))
        code,_,state=self.request('/api/state')
        self.assertEqual(state['tasks'][0]['note'],'人类原始笔记，不可被 Agent 改写')

    def test_permissions_conflict_and_human_gate(self):
        code,_,context=self.agent('context')
        self.assertEqual(code,200)
        code,_,claim=self.agent('activity',{'phase':'claim','task_id':'t1','reason':'检查写入冲突','expected_output':'冲突测试'})
        self.assertEqual(code,200)
        aid=claim['action_id']
        code,rev,state=self.request('/api/state')
        code,_,bad=self.agent('task/t1',{'ifRev':rev,'action_id':aid,'changes':{'note':'Agent 覆盖'},'reason':'bad'},'PATCH')
        self.assertEqual(code,403)
        code,_,bad=self.agent('task/t1',{'ifRev':rev-1,'action_id':aid,'changes':{'status':'进行中'},'reason':'stale'},'PATCH')
        self.assertEqual(code,409)
        code,_,ok=self.agent('task/t1',{'ifRev':rev,'action_id':aid,'changes':{'status':'进行中'},'reason':'开始协议测试'},'PATCH')
        self.assertEqual(code,200)
        code,_,decision=self.agent('decision-request',{'question':'是否改变科研目标？','context':'需要人类授权','options':['维持','修改'],'impact':'目标范围变化','blocking':True})
        self.assertEqual(code,200)
        code,_,today=self.request('/api/research/today?project_id=p1')
        self.assertEqual(today['pulse'],'Needs Decision')
        code,_,resolved=self.request('/api/research/decisions/'+decision['decision_id'],{'status':'rejected','resolution':'维持原目标'})
        self.assertEqual(code,200)
        code,_,state=self.request('/api/state')
        self.assertEqual(state['projects'][0]['goal'],'核对迁移链路')
        self.assertEqual(state['tasks'][0]['note'],'人类原始笔记，不可被 Agent 改写')

    def test_read_only_agent_cannot_execute(self):
        code,_,read=self.request('/api/agents/connect',{'project_id':'p1','name':'Reviewer','permission':'READ'})
        self.assertEqual(code,200)
        code,_,denied=self.request('/api/agent/activity',{'phase':'claim','task_id':'t1','reason':'x','expected_output':'x'},read['token'])
        self.assertEqual(code,403)
        code,_,state=self.request('/api/state')
        self.assertEqual(len(state['tasks']),1)

    def test_named_sse_event_and_connection_status(self):
        request=urllib.request.Request(self.base+'/api/events',headers={'Authorization':'Bearer '+self.human_token})
        with urllib.request.urlopen(request,timeout=4) as stream:
            code,_,context=self.agent('context')
            self.assertEqual(code,200)
            line=stream.readline().decode().strip()
            self.assertEqual(line,'event: agent.connected')
            payload=stream.readline().decode().strip()
            self.assertTrue(payload.startswith('data: '))
            ev=json.loads(payload[6:])
            self.assertEqual(ev['type'],'agent.connected')
            self.assertEqual(ev['actor'],self.connection['agent_id'])


if __name__=='__main__':
    unittest.main(verbosity=2)
