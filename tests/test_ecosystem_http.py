"""Synthetic HTTP + stdio MCP acceptance; no model/account/network source calls."""
import unittest
import test_agent_gateway as support


class EcosystemHTTPCase(unittest.TestCase):
    setUp=support.AgentGatewayCase.setUp
    tearDown=support.AgentGatewayCase.tearDown
    request=support.AgentGatewayCase.request
    agent=support.AgentGatewayCase.agent
    mcp=support.AgentGatewayCase.mcp

    def view(self):
        code,_,value=self.request('/api/ecosystem?project_id=p1')
        self.assertEqual(code,200,value)
        return value

    def post(self,op,**values):
        body=dict(operation=op,project_id='p1',ifRev=self.view()['rev'],**values)
        code,_,value=self.request('/api/ecosystem',dict(body,dry=True))
        self.assertEqual(code,200,value);self.assertTrue(value['preview'])
        code,_,value=self.request('/api/ecosystem',body)
        self.assertEqual(code,200,value)
        return value['item']

    def room(self):
        role=self.post('profile.save',name='核查角色',instructions='合成核查；仅提出建议',engine='external',model='',agent_id=self.connection['agent_id'])
        return self.post('room.create',title='合成讨论',question='如何核查来源？',profile_ids=[role['id']],max_rounds=1,max_calls=1)

    @unittest.skipUnless(support.NODE,'node required')
    def test_mcp_request_reply_adoption_and_project_isolation(self):
        room=self.room()
        self.mcp('project.get_context')
        self.assertEqual(self.mcp('project.get_discussion_requests')['requests'],[])
        self.post('room.start',id=room['id'],consent='discussion-project-records-v1')
        requests=self.mcp('project.get_discussion_requests')['requests']
        self.assertEqual(len(requests),1);request=requests[0]
        self.assertEqual(request['context']['project']['id'],'p1')
        self.assertEqual(request['previous_messages'],[])
        output=dict(position='合成观点',evidence='UNKNOWN',objections='保持负结果',next_step='人工核查')
        body={k:request[k] for k in ('room_id','participant_id','run_id')};body['output']=output
        self.assertTrue(self.mcp('project.reply_discussion',body)['accepted'])
        self.assertNotEqual(self.agent('discussion/reply',body)[0],200)
        self.assertEqual(self.mcp('project.get_radar_alerts')['alerts'],[])
        self.assertEqual(self.view()['rooms'][0]['status'],'completed')
        self.post('room.adopt',id=room['id'],target='task',title='合成复核任务',rationale='人工仅采纳核查计划，不声明事实通过')
        _,_,state=self.request('/api/state')
        task=next(t for t in state['tasks'] if t['title']=='合成复核任务')
        self.assertEqual(task['project'],'p1');self.assertEqual(task['verification_status'],'UNVERIFIED')
        self.request('/api/action',{'collection':'projects','item':{'id':'p2','name':'其他项目'}})
        code,_,other=self.request('/api/agents/connect',{'project_id':'p2','name':'Other','permission':'PROPOSE'})
        self.assertEqual(code,200,other)
        self.request('/api/agent/context',token=other['token'])
        self.assertEqual(self.request('/api/agent/discussion/reply',body,token=other['token'])[0],404)

    def test_human_only_api_and_handshake_required(self):
        self.assertEqual(self.request('/api/ecosystem?project_id=p1',token=self.agent_token)[0],401)
        room=self.room();self.post('room.start',id=room['id'],consent='discussion-project-records-v1')
        code,_,requests=self.agent('ecosystem')
        self.assertEqual(code,200,requests);r=requests['requests'][0]
        body={k:r[k] for k in ('room_id','participant_id','run_id')}
        body['output']=dict(position='合成',evidence='UNKNOWN',objections='未知',next_step='核查')
        self.assertEqual(self.agent('discussion/reply',body)[0],400)
        self.agent('context')
        self.assertEqual(self.agent('discussion/reply',body)[0],200)
        self.assertEqual(self.request('/api/ecosystem',dict(operation='room.stop',project_id='p1',id=room['id'],ifRev=self.view()['rev']),token=self.agent_token)[0],401)

    @unittest.skipUnless(support.NODE,'node required')
    def test_review_mcp_schema_and_human_export_scope(self):
        import review_service
        role=self.post('profile.save',name='评审基线',instructions='材料范围内评审',engine='external',model='',agent_id=self.connection['agent_id'])
        room=self.post('review.create',title='方案取舍',question='选择哪一个？',constraints='保留未知',materials=[{'title':'来源','content':'A\nB'}],profile_ids=[role['id']],max_rounds=1,max_calls=1)
        self.mcp('project.get_context');self.post('room.start',id=room['id'],consent='discussion-project-records-v1')
        request=self.mcp('project.get_discussion_requests')['requests'][0]
        self.assertEqual(request['reply_tool'],'project.reply_review')
        output={k:'未核验合成内容' for k in review_service.FIELDS};output['citations']=[{'claim':'存在方案 A','material_id':'M1','locator':'L1','relation':'source'}]
        body={k:request[k] for k in ('room_id','participant_id','run_id')};body['output']=output
        self.assertTrue(self.mcp('project.reply_review',body)['accepted'])
        path='/api/ecosystem/brief?project_id=p1&room_id='+room['id']
        code,_,brief=self.request(path);self.assertEqual(code,200,brief);self.assertIn('L1: A',brief['markdown']);self.assertEqual(brief['brief_revision'],1)
        self.assertEqual(self.request(path,token=self.agent_token)[0],401)
        self.request('/api/action',{'collection':'projects','item':{'id':'p2','name':'其他项目'}})
        self.assertEqual(self.request(path.replace('project_id=p1','project_id=p2'))[0],404)


if __name__=='__main__':unittest.main()
