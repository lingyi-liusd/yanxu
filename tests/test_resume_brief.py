import copy
import pathlib
import sys
import unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from project_continuity import build, resume_brief


class ResumeBriefTests(unittest.TestCase):
    def brief(self, source, plans=()):
        return resume_brief(source, 'snapshot-v1', build(source, 'snapshot-v1'), plans)

    def test_negative_unknown_and_sources_survive_delivery(self):
        source = {'project':{'id':'p','goal':'验证原问题','current_state':'尚未闭合','constraints':['保留旧契约']},
                  'actions':[{'id':'a','status':'finished'}],
                  'results':[{'id':'r','created_at':'2026-10-01','summary':'负结果 1/12，实车 NOT_RUN',
                              'outcome':'failure','verification_status':'UNVERIFIED','source_ref':'probe','source_version':'v0.2'}]}
        before = copy.deepcopy(source)
        b = self.brief(source)
        self.assertEqual(len(b['cards']),3)
        self.assertEqual(b['counts']['active'],0)
        self.assertEqual(b['counts']['negative'],1)
        self.assertEqual(b['handoff']['negative_results'][0]['source_version'],'v0.2')
        self.assertEqual(b['handoff']['latest_result']['verification_status'],'UNVERIFIED')
        self.assertIn('NOT_RUN',b['cards'][0]['detail'])
        self.assertEqual(b['handoff']['goal'],'验证原问题')
        self.assertEqual(source,before)

    def test_active_keeps_contract_and_consumed_budget(self):
        b = self.brief({'actions':[{'id':'a','status':'running','goal':'不重复实验',
            'budget':'{"max_progress_reports":20}','progress_reports_used':7,'version':3,
            'stop_condition':'一次后停止','success_condition':'判据','failure_condition':'保留失败'}]})
        self.assertEqual(b['next_reason'],'active_action')
        a=b['handoff']['active_actions'][0]
        self.assertEqual(a['progress_reports_used'],7)
        self.assertEqual(a['stop_condition'],'一次后停止')
        self.assertIn('不要另起重复',b['cards'][2]['text'])

    def test_decision_then_active_then_blocker_then_approved(self):
        source={'project':{'id':'p','goal':'原目标'},'decisions':[{'id':'d','status':'pending','question':'是否改方向'}],
                'actions':[{'id':'a','status':'running'}],'tasks':[{'id':'t','status':'受阻'}]}
        self.assertEqual(self.brief(source)['next_reason'],'decision')
        source['decisions']=[]
        self.assertEqual(self.brief(source)['next_reason'],'active_action')
        source['actions']=[]
        self.assertEqual(self.brief(source)['next_reason'],'blocker')
        source['tasks']=[]
        plans=[{'id':1,'ready':True,'orphaned':True},{'id':2,'ready':True,'orphaned':False}]
        b=self.brief(source,plans)
        self.assertEqual(b['next_reason'],'approved_review')
        self.assertEqual(b['handoff']['ready_review_ids'],[2])

    def test_no_raw_sources_no_model_claim_and_not_new_permission(self):
        b=self.brief({'source_bridge':{'items':[{'content':'PRIVATE BODY'}]},'tasks':[{'id':'n','noteType':'note','status':'待开始'}]})
        self.assertNotIn('PRIVATE BODY',str(b))
        self.assertEqual(b['handoff']['open_tasks'],[])
        self.assertIn('不是新授权',b['handoff']['boundary'])
        self.assertIn('project.get_context',b['handoff']['entrypoint'])
        self.assertIn('不能从任务完成',b['cards'][1]['text'])

    def test_latest_is_by_record_time_not_id_order(self):
        b=self.brief({'results':[{'id':'z','created_at':'2026-09-01','summary':'old'},
                                {'id':'a','created_at':'2026-10-01','summary':'new','outcome':'partial'}]})
        self.assertEqual(b['handoff']['latest_result']['id'],'a')
        self.assertEqual(b['cards'][0]['detail'],'new')

    def test_removed_negative_and_both_constraint_layers_are_retained(self):
        source={'project':{'constraints':['当前条件'],'frozen_constraints':['原冻结契约']},'results':[]}
        old={'id':1,'input':'{"results":[{"id":"r","normalized_status":"FAIL","summary":"原负结果","source_version":"v1"}]}','signature':'old','finished':1}
        c=build(source,'new',old)
        h=resume_brief(source,'new',c)['handoff']
        self.assertEqual(h['historical_negative_records'][0]['summary'],'原负结果')
        self.assertEqual(h['constraints'],['当前条件'])
        self.assertEqual(h['frozen_constraints'],['原冻结契约'])

    def test_next_step_has_specific_record_and_readonly_risk_checks(self):
        source={'project':{'id':'p','goal':''},'actions':[{'id':'a','status':'running','goal':'任务'}],
                'results':[{'id':'r','outcome':'success','verification_status':'UNVERIFIED'}]}
        b=self.brief(source)
        self.assertEqual(b['cards'][2]['target']['id'],'a')
        self.assertEqual(b['cards'][2]['target']['view'],'actions')
        codes=[c['code'] for c in b['handoff']['record_checks']]
        self.assertIn('GOAL_MISSING',codes)
        self.assertIn('CONTRACT_INCOMPLETE',codes)
        self.assertIn('WORK_IN_PROGRESS',codes)
        self.assertIn('UNVERIFIED',codes)
        self.assertIn('不代表',b['handoff']['checks_scope'])
        self.assertIn('context_hash',b['handoff']['entrypoint'])

    def test_latest_result_source_target_and_no_fabricated_source_review(self):
        b=self.brief({'project':{'goal':'原目标'},'results':[{'id':'r','outcome':'partial'}]})
        self.assertEqual(b['cards'][2]['target']['id'],'r')
        self.assertEqual(b['cards'][2]['target']['kind'],'result')
        self.assertNotIn('SOURCE_REVIEW',[c['code'] for c in b['handoff']['record_checks']])

    def test_one_snapshot_choice_for_person_and_agent_without_mutation(self):
        source={'project':{'id':'p','goal':'原目标'},'tasks':[
            {'id':'queued','project':'p','title':'下一项','status':'待开始','priority':'P0'},
            {'id':'current','project':'p','title':'原工作','status':'进行中','deps':['done']},
            {'id':'done','project':'p','status':'已完成'},
            {'id':'foreign','project':'other','status':'受阻'},
            {'id':'note','project':'p','noteType':'evidence','status':'受阻'}],
            'results':[{'id':'old','summary':'旧结果','outcome':'failure','verification_status':'UNVERIFIED'}]}
        before=copy.deepcopy(source)
        b=self.brief(source)
        choice=b['next_explanation']
        self.assertEqual(choice,b['handoff']['next_navigation'])
        self.assertEqual(choice['target'],b['cards'][2]['target'])
        self.assertEqual(choice['rule'],'task_current')
        self.assertEqual(choice['target']['id'],'current')
        self.assertEqual(choice['source_hash'],b['source_hash'])
        self.assertEqual(choice['dependencies'][0]['status'],'已完成')
        self.assertEqual(choice['task_counts'],{'total':3,'completed':1})
        self.assertEqual([t['id'] for t in b['handoff']['open_tasks']],['queued','current'])
        self.assertEqual(b['handoff']['negative_results'][0]['id'],'old')
        self.assertEqual(source,before)

    def test_dependencies_unknown_and_deterministic_order(self):
        source={'project':{'id':'p','goal':'原目标'},'tasks':[
            {'id':'blocked-by-missing','status':'待开始','priority':'P0','deps':['absent']},
            {'id':'ready-b','status':'待开始','priority':'P2'},
            {'id':'ready-a','status':'待开始','priority':'P1'}]}
        b=self.brief(source)
        self.assertEqual(b['next_reason'],'task_ready')
        self.assertEqual(b['cards'][2]['target']['id'],'ready-a')
        source['tasks'].reverse()
        self.assertEqual(self.brief(source)['next_explanation'],b['next_explanation'])
        source['tasks']=[{'id':'t','status':'进行中','deps':['absent']}]
        choice=self.brief(source)['next_explanation']
        self.assertEqual(choice['rule'],'task_current')
        self.assertEqual(choice['dependencies'],[{'id':'absent','title':'当前任务范围未找到','status':'UNKNOWN','found':False}])
        source['tasks'][0]['status']='待开始'
        self.assertEqual(self.brief(source)['next_reason'],'task_dependencies')
        source['tasks'][0]['deps']=['t']
        self.assertEqual(self.brief(source)['next_reason'],'task_dependencies')

    def test_direct_affected_result_not_unrelated_newest(self):
        source={'project':{'id':'p','goal':'原目标'},'results':[
            {'id':'newest','created_at':'2026-10-02','source_ref':'/other/a','outcome':'success'},
            {'id':'affected','created_at':'2026-10-01','summary':'原负结果 NOT_RUN',
             'source_ref':'/scope/a','source_version':'a'*64,'outcome':'failure','verification_status':'UNVERIFIED'}],
            'file_observations':[{'path':'/scope/a','state':'present','observed_version':'sha256:'+'b'*64,'matches_registered':False}]}
        b=self.brief(source)
        self.assertEqual(b['next_reason'],'source_review')
        self.assertEqual(b['cards'][2]['target']['id'],'affected')
        self.assertEqual(b['handoff']['latest_result']['id'],'newest')
        choice=b['next_explanation']
        self.assertEqual(choice['basis_records'][0]['outcome'],'failure')
        self.assertEqual(choice['basis_records'][0]['verification_status'],'UNVERIFIED')
        self.assertEqual(choice['source_checks'][0]['version_status'],'VERSION_CHANGED')
        self.assertEqual(choice['source_checks'][0]['record_version'],'a'*64)
        self.assertIn('不等于结论错误',choice['summary'])
        source['file_observations'][0]['state']='missing'
        missing=self.brief(source)['next_explanation']['source_checks'][0]
        self.assertEqual(missing['version_status'],'UNKNOWN')
        self.assertIsNone(missing['observed_version'])
        source['results'][1]['source_ref']='/scope/a.backup'
        self.assertEqual(self.brief(source)['next_reason'],'review')

    def test_goal_missing_and_completed_tasks_are_not_scientific_success(self):
        source={'project':{'id':'p','goal':' '},'tasks':[{'id':'t','status':'受阻'}]}
        b=self.brief(source,[{'id':2,'ready':True}])
        self.assertEqual(b['next_reason'],'goal_missing')
        self.assertIsNone(b['cards'][2]['target'])
        source['project']['goal']='原问题'
        source['tasks'][0]['status']='已完成'
        b=self.brief(source)
        self.assertIn('尚无结果登记',b['cards'][0]['text'])
        self.assertIn('不能从任务完成',b['cards'][1]['text'])
        self.assertIsNone(b['cards'][2]['target'])
