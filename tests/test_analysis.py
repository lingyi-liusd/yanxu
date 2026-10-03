# -*- coding: utf-8 -*-
import json, unittest, urllib.request
import test_agent_gateway as fixture

class AnalysisCase(unittest.TestCase):
    setUp=fixture.AgentGatewayCase.setUp
    tearDown=fixture.AgentGatewayCase.tearDown
    request=fixture.AgentGatewayCase.request
    agent=fixture.AgentGatewayCase.agent
    mcp=fixture.AgentGatewayCase.mcp

    def analyze(self):
        code,rev,response=self.request('/api/project-focus',{'scope':'p1','trigger':'manual_refresh'})
        self.assertEqual(code,200)
        self.assertEqual(response['focus']['provider'],'fallback')
        return rev,response['focus']

    def test_read_is_read_only_and_model_requires_explicit_approval(self):
        code,rev,before=self.request('/api/project-focus?scope=p1')
        self.assertEqual(code,200);self.assertFalse(before['model_allowed']);self.assertFalse(before['automatic_analysis'])
        for _ in range(3):
            code,current,value=self.request('/api/project-focus?scope=p1')
            self.assertEqual(current,rev);self.assertIsNone(value['focus'])
        self.assertFalse((self.dir/'daily-focus.json').exists())
        code,_,_=self.request('/api/project-focus',{'scope':'p1','use_provider':True})
        self.assertEqual(code,400)
        self.assertFalse((self.dir/'daily-focus.json').exists())

    def test_preview_preserves_human_content_and_repeated_accept_is_rejected(self):
        _,focus=self.analyze()
        _,rev,state=self.request('/api/state')
        original=state['tasks'][0]
        payload={'scope':'p1','ifRev':rev,'focus_id':focus['focus_id']}
        code,new_rev,result=self.request('/api/project-focus/accept',payload)
        self.assertEqual(code,200);self.assertEqual(result['execution'],'not_sent');self.assertGreater(new_rev,rev)
        code,_,state=self.request('/api/state')
        self.assertEqual(len(state['tasks']),1)
        for key in ('title','note','status'):
            self.assertEqual(state['tasks'][0][key],original.get(key))
        self.assertEqual(state['tasks'][0]['source_focus_id'],focus['focus_id'])
        self.assertEqual(self.request('/api/project-focus/accept',payload)[0],400)

    def test_input_change_expires_suggestion_and_blocks_old_preview(self):
        _,focus=self.analyze();_,rev,state=self.request('/api/state')
        task=dict(state['tasks'][0],note='Updated human note')
        self.assertEqual(self.request('/api/action',{'ifRev':rev,'collection':'tasks','item':task})[0],200)
        code,_,status=self.request('/api/project-focus?scope=p1')
        self.assertTrue(status['stale']);self.assertIsNone(status['focus']);self.assertEqual(status['previous_focus']['focus_id'],focus['focus_id'])
        self.assertEqual(self.request('/api/project-focus/accept',{'scope':'p1','ifRev':rev,'focus_id':focus['focus_id']})[0],400)
        self.assertEqual(self.request('/api/state')[2]['tasks'][0]['note'],'Updated human note')

    def test_analysis_adopt_mcp_result_and_live_event(self):
        _,focus=self.analyze();_,rev,_=self.request('/api/state')
        code,_,accepted=self.request('/api/project-focus/accept',{'scope':'p1','ifRev':rev,'focus_id':focus['focus_id']})
        self.assertEqual(code,200)
        context=self.mcp('project.get_context');self.assertEqual(context['project']['id'],'p1')
        claim=self.mcp('project.claim_action',{'task_id':accepted['task_id'],'reason':'Isolated roundtrip','expected_output':'Fixture result','success_condition':'Recorded with source','failure_condition':'Missing source',
            'context_hash':context['management']['resume_brief']['source_hash'],
            'budget':{'max_progress_reports':3},'stop_condition':'Stop after the fixture result'})
        aid=claim['action_id']
        self.mcp('project.report_activity',{'action_id':aid,'phase':'start','summary':'Fixture work only'})
        req=urllib.request.Request(self.base+'/api/events',headers={'Authorization':'Bearer '+self.human_token})
        with urllib.request.urlopen(req,timeout=4) as stream:
            result=self.mcp('project.record_result',{'action_id':aid,'outcome':'partial','summary':'Fixture returned; not independently verified','source_ref':'tests/test_analysis.py','source_version':'fixture-v1'})
            names=[]
            for _ in range(20):
                line=stream.readline().decode().strip()
                if line.startswith('event: '):names.append(line[7:])
                if 'result.partial' in names:break
            self.assertIn('result.partial',names)
        self.assertEqual(result['verification_status'],'UNVERIFIED')
        latest=self.request('/api/project/context?project_id=p1')[2]
        self.assertEqual(latest['results'][0]['action_id'],aid)
        self.assertEqual(latest['results'][0]['normalized_status'],'partial')
        self.assertEqual(self.request('/api/project-focus?scope=p1')[2]['focus']['provider'],'fallback')

    def test_agent_proposal_expires_after_edit(self):
        self.agent('context')
        code,_,proposal=self.agent('proposal',{'kind':'task','title':'Fixture proposal','body':'Review before adoption'})
        self.assertEqual(code,200)
        context=self.request('/api/project/context?project_id=p1')[2]
        self.assertFalse(context['proposals'][0]['stale'])
        _,rev,state=self.request('/api/state')
        self.request('/api/action',{'ifRev':rev,'collection':'tasks','item':dict(state['tasks'][0],note='New input')})
        context=self.request('/api/project/context?project_id=p1')[2]
        self.assertTrue(context['proposals'][0]['stale'])

    def test_provider_scope_budget_and_inflight_edit(self):
        import os, subprocess, sys, tempfile
        with tempfile.TemporaryDirectory(prefix='research-desk-policy-') as folder:
            env=os.environ.copy();env['RESEARCH_DESK_DATA_DIR']=folder
            script='''import json, server
state={'projects':[{'id':'p1','name':'Fixture','stages':[]}],'tasks':[{'id':'t1','project':'p1','title':'Fixture task','status':'待开始','note':'original','deps':[]}],'files':[],'decisions':[]}
with server.connect() as c: c.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(state),))
raw=server._generate_focus({'scope':'p1'})['focus']
class Provider:
    available=True
    url='http://127.0.0.1:1/unused'
    model='fixture-model'
    calls=0
    def generate(self, context, previous):
        assert set(context)=={'tasks'}, context.keys()
        assert previous is None
        self.calls+=1
        with server.connect() as c:
            s=json.loads(c.execute('SELECT body FROM state WHERE id=1').fetchone()[0]);s['tasks'][0]['note']='new human input'
            c.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(s),));server.bump_rev(c)
        return raw
provider=Provider();server.get_focus_provider=lambda:provider
server.DATA.joinpath('analysis-policy.json').write_text(json.dumps({'projects':{'p1':{'approved':True,'provider_url':provider.url,'model':provider.model,'context_fields':['tasks'],'max_calls_per_day':1}}}))
result=server._generate_focus({'scope':'p1','use_provider':True,'force':True})
assert result['stale'] is True
assert server._focus_status('p1')['focus'] is None
try: server._generate_focus({'scope':'p1','use_provider':True,'force':True})
except ValueError: pass
else: raise AssertionError('budget was ignored')
assert provider.calls==1
print(json.dumps({'calls':provider.calls,'stale':result['stale'],'provider':'mock, no network'}))
'''
            output=subprocess.check_output([sys.executable,'-c',script],cwd=str(fixture.ROOT),env=env,text=True)
            self.assertEqual(json.loads(output)['calls'],1)
