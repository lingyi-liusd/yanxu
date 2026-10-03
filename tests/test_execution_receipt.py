"""Pure readback gates: never infer writeback from a successful model/job."""
import copy
import json
import unittest
from agent_manager import Manager


class ExecutionReceiptTests(unittest.TestCase):
    def setUp(self):
        self.e={'id':1,'state':'succeeded','handoff_id':2,'handoff_state':'completed',
                'source_hash':'old','action_id':'a','result_id':'r'}
        self.raw={'project':{'id':'p'},'actions':[{'id':'a','project_id':'p','status':'finished'}],
                  'results':[{'id':'r','action_id':'a','project_id':'p','source_ref':'research-desk:management-handoff/2',
                              'source_version':'sha256:old','outcome':'UNKNOWN','verification_status':'UNVERIFIED'}]}
        self.raw['evidence']=[dict(self.raw['results'][0],id='ev')]

    def receipt(self):return Manager.execution_receipt(self.e,self.raw,'old')
    def test_exact_readback_preserves_unknown_without_mutating_source(self):
        before=copy.deepcopy((self.e,self.raw));r=self.receipt()
        self.assertTrue(r['recorded']);self.assertEqual(r['outcome'],'UNKNOWN')
        self.assertEqual(r['verification_status'],'UNVERIFIED');self.assertEqual(r['scientific_status'],'NOT_ASSESSED')
        self.assertEqual((self.e,self.raw),before)
    def test_source_change_preserves_historical_receipt_but_flags_version(self):
        r=Manager.execution_receipt(self.e,self.raw,'new')
        self.assertTrue(r['recorded']);self.assertTrue(r['source_changed'])
    def test_success_without_result_is_not_writeback(self):
        self.raw['results']=[];self.assertFalse(self.receipt()['recorded'])
    def test_missing_or_unfinished_action_is_not_writeback(self):
        self.raw['actions'][0]['status']='running';self.assertFalse(self.receipt()['recorded'])
        self.raw['actions']=[];self.assertFalse(self.receipt()['recorded'])
    def test_no_evidence_or_wrong_evidence_version_is_not_writeback(self):
        self.raw['evidence'][0]['source_version']='sha256:new';self.assertFalse(self.receipt()['recorded'])
        self.raw['evidence']=[];self.assertFalse(self.receipt()['recorded'])
    def test_wrong_result_action_source_or_version_is_not_writeback(self):
        original=copy.deepcopy(self.raw['results'][0])
        for key,value in [('action_id','other'),('source_ref','wrong'),('source_version','sha256:new'),('project_id','q')]:
            self.raw['results'][0]=dict(original,**{key:value});self.assertFalse(self.receipt()['recorded'])
    def test_other_project_action_or_evidence_is_not_writeback(self):
        self.raw['actions'][0]['project_id']='q';self.assertFalse(self.receipt()['recorded'])
        self.raw['actions'][0]['project_id']='p';self.raw['evidence'][0]['project_id']='q'
        self.assertFalse(self.receipt()['recorded'])
    def test_claimed_handoff_is_not_complete_even_with_matching_rows(self):
        self.e['handoff_state']='claimed';self.assertFalse(self.receipt()['recorded'])
    def test_failure_receipt_is_recorded_but_never_success(self):
        self.e['state']='failed';r=self.receipt()
        self.assertTrue(r['recorded']);self.assertEqual(r['outcome'],'UNKNOWN')
    def test_changed_record_cannot_replace_frozen_execution_contract(self):
        original={'goal':'原批准目标','stop_condition':'不进行实验'}
        e={'contract':json.dumps({'goal':'未批准目标'}),
           'review_context':json.dumps({'approved_read_only_contract':original})}
        before=copy.deepcopy(e);r=Manager.execution_contract(e)
        self.assertEqual(r['contract'],original);self.assertTrue(r['approval_record_changed'])
        self.assertEqual(r['contract_origin'],'execution_context');self.assertEqual(e,before)
        self.assertNotEqual(r['contract_hash'],r['approval_record_contract_hash'])
    def test_matching_frozen_contract_has_no_change_warning(self):
        original={'goal':'原批准目标'}
        r=Manager.execution_contract({'contract':json.dumps(original),'review_context':json.dumps({'approved_read_only_contract':original})})
        self.assertFalse(r['approval_record_changed']);self.assertEqual(r['contract_hash'],r['approval_record_contract_hash'])
    def test_missing_approval_still_preserves_frozen_execution_contract(self):
        original={'goal':'原批准目标'}
        r=Manager.execution_contract({'contract':None,'review_context':json.dumps({'approved_read_only_contract':original})})
        self.assertEqual(r['contract'],original);self.assertTrue(r['approval_record_changed'])
    def test_old_execution_explicitly_reports_ledger_origin(self):
        original={'goal':'旧记录，不补造冻结版本'}
        r=Manager.execution_contract({'contract':json.dumps(original),'review_context':None})
        self.assertEqual(r['contract'],original);self.assertEqual(r['contract_origin'],'handoff_record')
    def test_malformed_approval_does_not_hide_frozen_contract(self):
        original={'goal':'原批准目标'}
        r=Manager.execution_contract({'contract':'corrupted','review_context':json.dumps({'approved_read_only_contract':original})})
        self.assertEqual(r['contract'],original);self.assertTrue(r['approval_record_parse_error'])
        self.assertTrue(r['approval_record_changed'])
    def test_unavailable_contract_is_unknown_not_fabricated(self):
        r=Manager.execution_contract({'contract':'[]','review_context':'corrupted'})
        self.assertIsNone(r['contract']);self.assertIsNone(r['contract_hash']);self.assertEqual(r['contract_origin'],'unavailable')
    def test_unapproved_draft_does_not_fabricate_or_report_damaged_conditions(self):
        r=Manager.handoff_contract(None)
        self.assertIsNone(r['contract']);self.assertFalse(r['contract_valid'])
        self.assertFalse(r['contract_parse_error']);self.assertEqual(r['contract_error'],'')
    def test_damaged_handoff_contract_is_explicit_not_repaired(self):
        for raw in ('{broken','[]','null','"text"',''):
            with self.subTest(raw=raw):
                r=Manager.handoff_contract(raw)
                self.assertIsNone(r['contract']);self.assertFalse(r['contract_valid'])
                self.assertTrue(r['contract_parse_error']);self.assertTrue(r['contract_error'])
    def test_incomplete_handoff_object_is_preserved_but_invalid(self):
        for contract in ({},{'goal':'只有目标，没有停止条件'}):
            r=Manager.handoff_contract(json.dumps(contract))
            self.assertEqual(r['contract'],contract);self.assertIsNotNone(r['contract_hash'])
            self.assertFalse(r['contract_parse_error']);self.assertFalse(r['contract_valid'])
            self.assertTrue(r['contract_error'])
    def test_valid_handoff_preserves_conditions_verbatim(self):
        contract={'scope':'read_only_review','budget':{'max_progress_reports':1},
            **{key:' 原批准条件，不裁剪。 ' for key in ('goal','reason','expected_output','success_condition','failure_condition','stop_condition')}}
        r=Manager.handoff_contract(json.dumps(contract))
        self.assertEqual(r['contract'],contract);self.assertTrue(r['contract_valid'])
        self.assertFalse(r['contract_parse_error']);self.assertEqual(r['contract_error'],'')


if __name__=='__main__':unittest.main()
