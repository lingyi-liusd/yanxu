"""Human receipt HTTP, history/backup and stale guards with synthetic records."""
import sqlite3
import unittest
import test_agent_gateway as support


class ReviewHTTPCase(unittest.TestCase):
    setUp=support.AgentGatewayCase.setUp
    tearDown=support.AgentGatewayCase.tearDown
    request=support.AgentGatewayCase.request
    agent=support.AgentGatewayCase.agent

    def result(self):
        _,_,a=self.agent('activity',{'phase':'claim','task_id':'t1','reason':'合成依据','expected_output':'保持负结果'})
        code,_,result=self.agent('result',{'action_id':a['action_id'],'outcome':'failure','summary':'未解决原问题',
            'source_ref':'synthetic:not-a-file','source_version':'sha256:'+'a'*64})
        self.assertEqual(code,200,result)
        return result['result_id']

    def view(self,rid):
        code,_,value=self.request('/api/project/result-review?project_id=p1&result_id='+rid)
        self.assertEqual(code,200,value)
        return value

    def body(self,v):
        return dict(project_id='p1',result_id=v['result']['id'],ifRev=v['rev'],target_hash=v['target_hash'],
            source_version=v['source_version'],checked_source_version=v['source_version'],source_assessment='matched',
            review_kind='software',criteria='人工仅核对已报告软件条件',reviewer='临时测试审查者',conclusion='accepted',
            notes='仅人工声明所查版本，科学尚未评估；原失败不能改成通过',consent='human-result-review-v1')

    def test_dry_then_review_is_append_only_does_not_promote_failure(self):
        rid=self.result();v=self.view(rid);body=self.body(v)
        self.assertEqual(self.request('/api/project/result-review',dict(body,dry=True))[0],200)
        self.assertEqual(self.view(rid),v)
        code,_,saved=self.request('/api/project/result-review',body)
        self.assertEqual(code,200,saved)
        after=self.view(rid)
        self.assertEqual(after['result'],v['result']);self.assertEqual(after['evidence'],v['evidence'])
        self.assertEqual(after['result']['outcome'],'FAILURE')
        self.assertEqual(after['result']['verification_status'],'UNVERIFIED')
        self.assertEqual(after['reviews'][0]['scientific_status'],'NOT_ASSESSED')
        self.assertEqual(after['target_hash'],v['target_hash'])
        self.assertEqual(self.request('/api/project/result-review',self.body(after))[0],409)
        self.assertEqual(len(self.view(rid)['reviews']),1)

    def test_human_scope_version_and_claimed_hash_guards(self):
        rid=self.result();v=self.view(rid);body=self.body(v)
        self.assertEqual(self.request('/api/project/result-review',body,token=self.agent_token)[0],401)
        for changes in ({'ifRev':True},{'ifRev':v['rev']-1},{'target_hash':'forged'},
                        {'source_version':'v-invented'},{'checked_source_version':'sha256:'+'b'*64},
                        {'consent':''},{'scientific_status':'VERIFIED'},{'evidence_id':'other-project-evidence'}):
            with self.subTest(changes=changes):
                self.assertNotEqual(self.request('/api/project/result-review',dict(body,**changes))[0],200)
        self.assertEqual(self.view(rid),v)
        self.assertEqual(self.request('/api/project/result-review?project_id=p1&result_id=missing')[0],404)

    def test_missing_source_review_is_preserved_by_portable_restore(self):
        rid=self.result();v=self.view(rid);body=self.body(v)
        body.update(source_assessment='missing',checked_source_version='',conclusion='needs_more')
        self.assertEqual(self.request('/api/project/result-review',body)[0],200)
        before=self.view(rid)
        _,_,backup=self.request('/api/backup');_,rev,_=self.request('/api/state')
        self.assertIn('result_reviews',backup['gateway'])
        self.assertEqual(self.request('/api/restore',{'backup':backup,'ifRev':rev})[0],200)
        after=self.view(rid)
        self.assertEqual(after['reviews'],before['reviews'])
        self.assertEqual(after['result'],before['result'])
        self.assertEqual(after['result']['verification_status'],'UNVERIFIED')


if __name__=='__main__':unittest.main()
