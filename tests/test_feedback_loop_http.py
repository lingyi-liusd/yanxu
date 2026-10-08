"""Stage D: real HTTP/MCP protocol, isolated synthetic records, zero model calls.

Proves adopted material -> task -> Action -> negative Result -> follow-up review,
with the old decision and verification level preserved. This is software evidence,
not an independent user trial or a scientific result.
"""
import copy
import json
import os
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import review_service
import test_agent_gateway as support
import test_ecosystem_http as ecosystem_support


@unittest.skipUnless(support.NODE, 'node required')
class FeedbackLoopHTTPCase(unittest.TestCase):
    setUp = support.AgentGatewayCase.setUp
    tearDown = support.AgentGatewayCase.tearDown
    request = support.AgentGatewayCase.request
    agent = support.AgentGatewayCase.agent
    mcp = support.AgentGatewayCase.mcp
    view = ecosystem_support.EcosystemHTTPCase.view
    post = ecosystem_support.EcosystemHTTPCase.post

    def test_external_registration_dry_and_stale_revision_do_not_mint_tokens(self):
        before=self.view()
        body={'project_id':'p1','name':'外部只读建议','type':'external_review_client',
              'permission':'PROPOSE','contract_mode':'strict_v2','ifRev':before['rev']}
        code,_,preview=self.request('/api/agents/connect',dict(body,dry=True))
        self.assertEqual(code,200,preview)
        self.assertTrue(preview['preview'])
        self.assertNotIn('token',preview)
        self.assertEqual(self.view()['agents'],before['agents'])
        code,_,_=self.request('/api/action',{'ifRev':before['rev'],'collection':'tasks',
            'item':{'id':'changed','project':'p1','title':'并发新增记录'}})
        self.assertEqual(code,200)
        code,_,_=self.request('/api/agents/connect',body)
        self.assertEqual(code,409)
        self.assertEqual(self.view()['agents'],before['agents'])
        body['ifRev']=self.view()['rev']
        code,_,connection=self.request('/api/agents/connect',body)
        self.assertEqual(code,200,connection)
        self.assertEqual(connection['permission'],'PROPOSE')
        self.assertEqual(connection['contract_mode'],'strict_v2')
        self.assertFalse(connection['connected'])

    def client(self, *arguments, core=None):
        env=dict(os.environ, YANXU_AGENT_TOKEN=self.agent_token, PYTHONDONTWRITEBYTECODE='1')
        return subprocess.run([sys.executable, str(support.ROOT/'examples/review-client.py'),
                               '--core', core or self.base, *arguments],
                              env=env, capture_output=True, text=True, timeout=15)

    def test_standalone_client_reads_only_reviews_and_replies_explicitly(self):
        role=self.post('profile.save', name='合成外部客户端', instructions='仅本项目评审',
                       engine='external', model='', agent_id=self.connection['agent_id'])
        old=self.post('room.create', title='原讨论兼容记录', question='原讨论保持',
                      profile_ids=[role['id']], max_rounds=1, max_calls=1)
        room=self.post('review.create', title='独立客户端合成接入', question='明确材料是否保留？',
                       constraints='合成数据，不调用模型', materials=[{'title':'来源','content':'合成材料仅用于接入检查。'}],
                       profile_ids=[role['id']], max_rounds=1, max_calls=1)
        for item in (old,room):
            self.post('room.start', id=item['id'], consent='discussion-project-records-v1')
        read=self.client()
        self.assertEqual(read.returncode,0,read.stderr)
        requests=json.loads(read.stdout)['requests']
        self.assertEqual([r['room_id'] for r in requests],[room['id']])
        self.assertEqual(requests[0]['materials'][0]['content'],'合成材料仅用于接入检查。')
        self.assertEqual(next(r for r in self.view()['rooms'] if r['id']==room['id'])['used_calls'],0)
        output={k:'合成接入结果，仍未核验。' for k in review_service.FIELDS}
        output['citations']=[{'claim':'材料用于接入检查','material_id':'M1','locator':'L1','relation':'source'}]
        selected=self.dir/'explicit-reply.json'
        selected.write_text(json.dumps(output,ensure_ascii=False),encoding='utf-8')
        reply=self.client('--room',room['id'],'--reply',str(selected))
        self.assertEqual(reply.returncode,0,reply.stderr)
        self.assertTrue(json.loads(reply.stdout)['accepted'])
        self.assertNotIn(self.agent_token,read.stdout+read.stderr+reply.stdout+reply.stderr)
        view=self.view()
        self.assertEqual(next(r for r in view['rooms'] if r['id']==room['id'])['status'],'completed')
        untouched=next(r for r in view['rooms'] if r['id']==old['id'])
        self.assertEqual(untouched['status'],'running')
        self.assertEqual(untouched['used_calls'],0)
        self.post('room.stop',id=old['id'])

    def test_standalone_client_refuses_unknown_core_before_project_read(self):
        paths=[]
        class FutureCore(BaseHTTPRequestHandler):
            def do_GET(self):
                paths.append(self.path)
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
                self.wfile.write(json.dumps({'capabilities':{'product':'yanxu',
                    'contracts':{'ecosystem':3,'external_reply':2}}}).encode())
            def log_message(self,*args):pass
        server=HTTPServer(('127.0.0.1',0),FutureCore)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            result=self.client(core='http://127.0.0.1:'+str(server.server_port))
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(paths,['/healthz'])
            self.assertIn('incompatible',result.stderr)
            self.assertNotIn(self.agent_token,result.stdout+result.stderr)
        finally:
            server.shutdown();worker.join(timeout=2);server.server_close()

    def review(self, role, title, material, review_of='', selection=None):
        room = self.post('review.create', title=title, question=title,
            constraints='仅隔离合成接续验收，保留失败和未知，不调用模型',
            materials=[{'title':'本次明确选取的记录', 'content':material,
                        'reference':'synthetic://feedback-loop/material-v1'}],
            profile_ids=[role['id']], max_rounds=1, max_calls=1,
            review_of=review_of,context_selection=selection)
        self.mcp('project.get_context')
        self.post('room.start', id=room['id'], consent='discussion-project-records-v1')
        requests = self.mcp('project.get_discussion_requests')['requests']
        request = next(r for r in requests if r['room_id']==room['id'])
        output = {k:'合成评审：材料范围有限，保持原判断，结论未核验。'
                  for k in review_service.FIELDS}
        output['citations']=[{'claim':'记录仅属于本次材料范围', 'material_id':'M1',
                             'locator':'L1', 'relation':'source'}]
        body={k:request[k] for k in ('room_id','participant_id','run_id')}
        body['output']=output
        self.assertTrue(self.mcp('project.reply_review', body)['accepted'])
        return self.view()['rooms'][0] if self.view()['rooms'][0]['id']==room['id'] else next(
            r for r in self.view()['rooms'] if r['id']==room['id']), request

    def test_negative_result_returns_to_review_and_old_judgment_is_kept(self):
        role=self.post('profile.save', name='合成接续核查', instructions='只读取获准记录，保留负结果',
            engine='external', model='', agent_id=self.connection['agent_id'])
        original,_=self.review(role, '原判断：暂不扩大范围', '材料范围：本次仅核对已有链路。\n真实收益未知。')
        self.post('room.adopt', id=original['id'], target='decision', title='暂不扩大范围',
                  rationale='先核对已有链路，不声称收益通过', brief_revision=1)
        decision=copy.deepcopy(self.view()['context']['decisions'][0])
        first,_=self.review(role, '核对已有链路', '材料范围：先做已有链路的只读检查。\n缺少外部证据则失败。', review_of=decision['id'])
        adopted=self.post('room.adopt', id=first['id'], target='task', title='只读链路核查',
                          rationale='按明确材料范围核查，缺证据应记录失败', brief_revision=1)
        task_id=adopted['adopted_id']
        watch=self.post('watch.save',name='合成已有关联来源',url='https://example.org/feedback-feed',question='已采纳判断的外部依据是否变化？',
                        decision_ids=[decision['id']],keywords=['依据'],interval_minutes=60,enabled=False,auto_push=False)
        context=self.mcp('project.get_context')
        claim=self.mcp('project.claim_action', {
            'task_id':task_id, 'reason':'依据本次人工采纳的材料进行合成接续核查',
            'expected_output':'保留版本与未知的核查记录',
            'success_condition':'所需外部证据存在且可复核',
            'failure_condition':'所需外部证据缺失',
            'context_hash':context['management']['resume_brief']['source_hash'],
            'budget':{'max_progress_reports':1}, 'stop_condition':'结果登记后停止'})
        artifact=self.mcp('project.add_artifact', {'action_id':claim['action_id'],
            'type':'report', 'title':'缺证据的合成记录', 'reference':'synthetic://feedback-loop/report',
            'source_version':'feedback-report-v1', 'summary':'所需外部证据缺失，没有科学成功结论'})
        self.assertTrue(artifact['artifact_id'])
        result=self.mcp('project.record_result', {'action_id':claim['action_id'],
            'outcome':'failure', 'summary':'所需外部证据缺失；本次核查失败，收益仍未知',
            'source_ref':'synthetic://feedback-loop/report', 'source_version':'feedback-report-v1'})
        self.assertEqual(result['normalized_status'],'failure')
        self.assertEqual(result['verification_status'],'UNVERIFIED')
        view=self.view()
        traced=next(x for x in view['lineage'] if x['entry_id']==task_id)
        self.assertTrue(traced['origin_available'])
        self.assertEqual(traced['review_ref']['room_id'],first['id'])
        self.assertEqual(traced['material_refs'][0]['version'],first['materials'][0]['version'])
        action=next(x for x in traced['actions'] if x['id']==claim['action_id'])
        negative=next(x for x in action['results'] if x['id']==result['result_id'])
        self.assertEqual(negative['source_version'],'feedback-report-v1')
        self.assertEqual(negative['verification_status'],'UNVERIFIED')
        self.assertEqual(next(d for d in view['context']['decisions'] if d['id']==decision['id']),decision)
        candidate=next(p for p in view['result_observation']['candidates'] if p['source']['result']['id']==result['result_id'])
        self.assertEqual(candidate['watch_id'],watch['id']);self.assertEqual(candidate['source']['result']['outcome'],negative['outcome'])
        self.assertEqual(candidate['source']['result']['source_version'],'feedback-report-v1')
        resolve=dict(operation='watch.result.resolve',project_id='p1',id=watch['id'],expected_rev=watch['object_rev'],proposal_id=candidate['id'],basis_hash=candidate['basis_hash'],
                     resolution='modify',rule=candidate['proposed'],reason='将未核验负结果纳入原问题，维持暂停，等待真实外部材料',consent='result-observation-adjustment-v1')
        self.assertEqual(self.request('/api/ecosystem',resolve,token=self.agent_token)[0],401,'Agent cannot confirm observation-rule changes')
        code,_,dry=self.request('/api/ecosystem',dict(resolve,dry=True));self.assertEqual(code,200,dry)
        self.assertEqual(self.view()['watches'][0]['question'],watch['question'])
        code,_,saved=self.request('/api/ecosystem',resolve);self.assertEqual(code,200,saved)
        saved=saved['item'];self.assertFalse(saved['enabled']);self.assertFalse(saved['auto_push']);self.assertEqual(saved['url'],watch['url'])
        self.assertEqual(saved['result_adjustments'][0]['source']['result']['verification_status'],'UNVERIFIED')
        self.assertEqual(self.view()['result_observation']['total'],0)
        self.assertEqual(self.request('/api/ecosystem',dict(resolve,expected_rev=saved['object_rev']))[0],400)
        self.assertEqual(next(d for d in self.view()['context']['decisions'] if d['id']==decision['id']),decision)
        self.assertEqual(next(r for r in self.mcp('project.get_context')['results'] if r['id']==result['result_id'])['outcome'],negative['outcome'])
        followup,request=self.review(role, '失败后仍维持原判断',
            '材料范围：所需外部证据缺失；本次核查失败，收益仍未知。\n结果来源版本：feedback-report-v1',
            review_of=decision['id'],selection={'tasks':[task_id],'decisions':[],'results':[result['result_id']]})
        self.assertEqual(request['review_of'],decision)
        included=next(x for x in request['context']['results'] if x['id']==result['result_id'])
        self.assertEqual(included['summary'],negative['summary'])
        self.assertEqual(included['source_version'],negative['source_version'])
        self.assertEqual(included['verification_status'],'UNVERIFIED')
        self.post('room.adopt', id=followup['id'], target='decision', title='复核后维持原判断',
                  rationale='核查失败仅说明外部证据不足；继续暂不扩大范围', brief_revision=1)
        decisions=self.view()['context']['decisions']
        self.assertEqual(next(d for d in decisions if d['id']==decision['id']),decision)
        revised=next(d for d in decisions if d.get('revisits_decision_id')==decision['id'])
        self.assertEqual(revised['verification_status'],'UNVERIFIED')
        self.assertEqual(revised['review_ref']['room_id'],followup['id'])
        code,_,export=self.request('/api/ecosystem/brief?project_id=p1&room_id='+followup['id'])
        self.assertEqual(code,200,export)
        self.assertIn('feedback-report-v1',export['markdown'])
        self.assertIn('未核验',export['markdown'])


if __name__=='__main__':
    unittest.main()
