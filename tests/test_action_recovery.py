"""Human-only reconciliation against isolated HTTP service, no tool/model replay."""
import sqlite3
import unittest
import test_agent_gateway as support


class RecoveryCase(unittest.TestCase):
    setUp=support.AgentGatewayCase.setUp
    tearDown=support.AgentGatewayCase.tearDown
    request=support.AgentGatewayCase.request
    agent=support.AgentGatewayCase.agent

    def claim(self):
        body={'phase':'claim','task_id':'t1','goal':'中断后仍回答原问题','reason':'合成旧授权',
              'expected_output':'结果与未知','success_condition':'有原始依据','failure_condition':'缺依据保留未知',
              'stop_condition':'完成即停，不重做外部实验','budget':{'max_progress_reports':2}}
        code,_,value=self.agent('activity',body)
        self.assertEqual(code,200,value)
        return value['action_id']

    def view(self,aid):
        code,_,v=self.request('/api/project/action-recovery?project_id=p1&action_id='+aid)
        self.assertEqual(code,200,v)
        return v

    def payload(self,v,operation,**extra):
        a=v['action']
        return dict(project_id='p1',action_id=a['id'],ifRev=v['rev'],action_version=a['version'],
                    contract_hash=a['contract_hash'],source_hash=v['source_hash'],operation=operation,
                    consent='human-action-recovery-v1',external_work_stopped=True,
                    checked_no_registered_output=True,checked_records=[r['id'] for r in v['results']+v['artifacts']],
                    summary='人工核对已停，外部效果仍未知',**extra)

    def test_transfer_preserves_id_contract_progress_and_old_owner_is_fenced(self):
        aid=self.claim()
        self.assertEqual(self.agent('activity',{'phase':'progress','action_id':aid,'summary':'一次原进度'})[0],200)
        _,_,next_agent=self.request('/api/agents/connect',{'project_id':'p1','name':'Next','permission':'EXECUTE','contract_mode':'strict_v2'})
        self.request('/api/agent/context',token=next_agent['token'])
        v=self.view(aid);body=self.payload(v,'continue',to_agent_id=next_agent['agent_id'])
        self.assertEqual(v['used_progress_reports'],1)
        self.assertEqual(self.request('/api/project/action-recovery',dict(body,dry=True))[0],200)
        self.assertEqual(self.view(aid)['action'],v['action'])
        code,_,receipt=self.request('/api/project/action-recovery',body)
        self.assertEqual(code,200,receipt)
        fresh=self.view(aid)
        self.assertEqual(fresh['action']['id'],aid)
        self.assertEqual(fresh['action']['contract_hash'],v['action']['contract_hash'])
        self.assertEqual(fresh['used_progress_reports'],1)
        self.assertEqual(fresh['max_progress_reports'],2)
        self.assertEqual(self.agent('activity',{'phase':'progress','action_id':aid,'summary':'迟到原worker'})[0],409)
        progress={'phase':'progress','action_id':aid,'summary':'接续仍使用原进度预算'}
        self.assertEqual(self.request('/api/agent/activity',progress,token=next_agent['token'])[0],200)
        self.assertEqual(self.request('/api/agent/activity',progress,token=next_agent['token'])[0],409)
        self.assertEqual(self.view(aid)['used_progress_reports'],2)

    def test_version_human_consent_and_output_checks_reject_without_side_effect(self):
        aid=self.claim();v=self.view(aid);body=self.payload(v,'mark_interrupted')
        for changed in ({'ifRev':v['rev']-1},{'action_version':0},{'contract_hash':'forged'},
                        {'source_hash':'forged'},{'external_work_stopped':False},{'consent':''},
                        {'checked_records':['other-project-output']},{'checked_no_registered_output':False}):
            with self.subTest(changed=changed):
                self.assertNotEqual(self.request('/api/project/action-recovery',dict(body,**changed))[0],200)
        self.assertEqual(self.request('/api/project/action-recovery',body,token=self.agent_token)[0],401)
        self.assertEqual(self.view(aid)['action'],v['action'])
        self.assertEqual(self.request('/api/project/action-recovery?project_id=other&action_id='+aid)[0],404)
        self.assertEqual(self.request('/api/project/action-recovery',body)[0],200)
        self.assertEqual(self.view(aid)['action']['status'],'interrupted')
        self.assertEqual(self.agent('activity',{'phase':'start','action_id':aid,'summary':'未核对重跑'})[0],409)
        self.assertEqual(self.agent('activity',{'phase':'fail','action_id':aid,'summary':'规避人工锁'})[0],409)

    def test_close_unknown_keeps_no_result_and_releases_delivery_only(self):
        aid=self.claim();v=self.view(aid)
        code,_,receipt=self.request('/api/project/action-recovery',self.payload(v,'close_unknown'))
        self.assertEqual(code,200,receipt)
        self.assertEqual(receipt['scientific_status'],'UNKNOWN')
        after=self.view(aid)
        self.assertEqual(after['action']['status'],'failed')
        self.assertEqual(after['results'],[])
        self.assertEqual(after['action']['stop_condition'],v['action']['stop_condition'])
        self.assertEqual(self.request('/api/project/action-recovery',self.payload(after,'continue'))[0],409)

    def test_already_recorded_result_never_replayed(self):
        aid=self.claim()
        result={'action_id':aid,'outcome':'failure','summary':'原负结果',
                'source_ref':'synthetic:report','source_version':'v1'}
        self.assertEqual(self.agent('result',result)[0],200)
        # Simulate a partial restored delivery row; results are already durable.
        with sqlite3.connect(self.dir/'desk.sqlite3') as c:
            c.execute("UPDATE actions SET status='running' WHERE id=?",(aid,))
        v=self.view(aid)
        self.assertEqual(self.request('/api/project/action-recovery',self.payload(v,'continue'))[0],409)
        code,_,receipt=self.request('/api/project/action-recovery',self.payload(v,'reconcile_completed'))
        self.assertEqual(code,200,receipt)
        after=self.view(aid)
        self.assertEqual(after['action']['status'],'finished')
        self.assertEqual(after['results'],v['results'])
        self.assertEqual(after['results'][0]['verification_status'],'UNVERIFIED')

    def test_portable_restore_lost_token_can_resume_only_after_human_reconcile(self):
        aid=self.claim()
        self.agent('activity',{'phase':'progress','action_id':aid,'summary':'备份前已耗一次'})
        _,_,backup=self.request('/api/backup')
        _,rev,_=self.request('/api/state')
        self.assertEqual(self.request('/api/restore',{'backup':backup,'ifRev':rev})[0],200)
        self.assertEqual(self.agent('context')[0],401)
        _,_,next_agent=self.request('/api/agents/connect',{'project_id':'p1','name':'RestoredNext','permission':'EXECUTE','contract_mode':'strict_v2'})
        v=self.view(aid);body=self.payload(v,'continue',to_agent_id=next_agent['agent_id'])
        self.assertEqual(self.request('/api/project/action-recovery',body)[0],409)
        self.request('/api/agent/context',token=next_agent['token'])
        v=self.view(aid);body=self.payload(v,'continue',to_agent_id=next_agent['agent_id'])
        self.assertEqual(self.request('/api/project/action-recovery',body)[0],200)
        after=self.view(aid)
        self.assertEqual(after['used_progress_reports'],1)
        self.assertEqual(after['action']['contract_hash'],v['action']['contract_hash'])
        self.assertEqual(self.request('/api/agent/activity',{'phase':'progress','action_id':aid,'summary':'只能用剩余次数'},token=next_agent['token'])[0],200)
        self.assertEqual(self.request('/api/agent/activity',{'phase':'progress','action_id':aid,'summary':'不会恢复新预算'},token=next_agent['token'])[0],409)

    def test_pre_upgrade_backup_without_additive_tables_still_restores_originals(self):
        aid=self.claim();_,_,backup=self.request('/api/backup')
        for table in ('action_contracts','action_recoveries','result_reviews'):
            backup['gateway'].pop(table)
        _,rev,_=self.request('/api/state')
        self.assertEqual(self.request('/api/restore',{'backup':backup,'ifRev':rev})[0],200)
        self.assertEqual(self.view(aid)['action']['goal'],'中断后仍回答原问题')


if __name__=='__main__':unittest.main()
