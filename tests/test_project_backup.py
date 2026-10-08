import copy
import json
import unittest
import urllib.request
import urllib.error
import test_agent_gateway as gateway

class BackupCase(unittest.TestCase):
    setUp = gateway.AgentGatewayCase.setUp
    tearDown = gateway.AgentGatewayCase.tearDown
    request = gateway.AgentGatewayCase.request
    agent = gateway.AgentGatewayCase.agent

    def populate(self):
        self.agent('context')
        code,_,claim = self.agent('activity', {'phase':'claim','title':'Isolated verification', 'reason':'Verify records',
            'expected_output':'test result','success_condition':'confirmed','failure_condition':'missing source'})
        self.assertEqual(code,200)
        aid=claim['action_id']
        self.agent('activity',{'phase':'start','action_id':aid,'summary':'start'})
        self.agent('artifact',{'action_id':aid,'title':'test artifact','type':'report','reference':'fixtures/output.md','source_version':'v1'})
        self.assertEqual(self.agent('proposal',{'kind':'direction_change','title':'test proposal','body':'keep bounded'})[0],200)
        self.agent('decision-request',{'question':'Approve scope?','context':'test','options':['yes','no'],'blocking':True})
        return aid

    def test_untrusted_host_and_origin_do_not_reveal_token(self):
        for headers in ({'Host':'untrusted.invalid'}, {'Host':'localhost:'+str(self.port),'Origin':'https://untrusted.invalid'}, {'Host':'127.0.0.1:1'}, {'Origin':'null'}):
            req=urllib.request.Request(self.base+'/',headers=headers)
            with self.assertRaises(urllib.error.HTTPError) as caught: urllib.request.urlopen(req,timeout=3)
            self.assertEqual(caught.exception.code,403)
            self.assertNotIn(self.human_token,caught.exception.read().decode())
        with urllib.request.urlopen(self.base+'/',timeout=3) as res: self.assertEqual(res.status,200)
        self.assertEqual(self.request('/api/state')[0],200)

    def test_full_backup_portable_restore_and_credentials(self):
        aid=self.populate()
        self.assertEqual(self.agent('result',{'action_id':aid,'outcome':'failure','summary':'negative result','source_ref':'fixture','source_version':'v1'})[0],200)
        code,_,backup=self.request('/api/backup');self.assertEqual(code,200)
        original_tables={'agents','actions','artifacts','evidence','action_results','decision_requests','proposals','project_events'}
        self.assertEqual(set(backup['gateway']),original_tables|{'action_contracts','action_recoveries','result_reviews','ecosystem_items'})
        self.assertTrue(all(backup['gateway'][k] for k in original_tables))
        self.assertTrue(all(backup['gateway'][k]==[] for k in ('action_contracts','action_recoveries','result_reviews')))
        self.assertNotIn('token_hash',json.dumps(backup))
        self.assertNotIn(self.agent_token,json.dumps(backup))
        code,rev,_=self.request('/api/state')
        code,_,_=self.request('/api/restore',{'backup':backup,'ifRev':rev})
        self.assertEqual(code,200)
        self.assertEqual(self.agent('context')[0],401)
        _,_,after=self.request('/api/backup')
        for table in backup['gateway']:
            if table not in ('project_events','agents'): self.assertEqual(backup['gateway'][table],after['gateway'][table])
        for collection,items in backup['state'].items():
            restored={item['id']:item for item in after['state'][collection]}
            self.assertEqual(len(items),len(restored))
            for item in items:
                for key,value in item.items(): self.assertEqual(value,restored[item['id']][key])
        # Undo keeps the local credentials and complete prior result chain.
        self.assertEqual(self.request('/api/undo',{})[0],200)
        self.assertEqual(self.agent('context')[0],200)

    def test_agent_result_undo_restores_running_action_and_all_records(self):
        aid=self.populate()
        _,_,before=self.request('/api/backup')
        code,_,_=self.agent('result',{'action_id':aid,'outcome':'partial','summary':'partial','source_ref':'fixture','source_version':'v1'})
        self.assertEqual(code,200)
        self.assertEqual(self.request('/api/undo',{})[0],200)
        _,_,after=self.request('/api/backup')
        for table in ('actions','action_results','evidence','artifacts','decision_requests','proposals'):
            self.assertEqual(before['gateway'][table],after['gateway'][table])
        self.assertEqual(self.agent('context')[0],200)

    def test_rejected_backup_is_atomic_and_revision_checked(self):
        self.populate();_,rev,backup=self.request('/api/backup')
        bad=copy.deepcopy(backup);bad['gateway']['artifacts'][0]['action_id']='missing'
        self.assertEqual(self.request('/api/restore',{'backup':bad,'ifRev':rev})[0],400)
        self.assertEqual(self.request('/api/restore',{'backup':backup,'ifRev':rev-1})[0],400)
        _,after_rev,after=self.request('/api/backup')
        self.assertEqual(after_rev,rev)
        self.assertEqual(after['gateway'],backup['gateway'])

    def test_delete_project_and_undo_cover_gateway(self):
        self.populate();_,rev,before=self.request('/api/backup')
        self.assertEqual(self.request('/api/action',{'collection':'projects','op':'delete','id':'p1','ifRev':rev})[0],200)
        _,_,after=self.request('/api/backup')
        for table in after['gateway']:
            if table!='project_events':self.assertEqual(after['gateway'][table],[])
        self.assertEqual(self.request('/api/undo',{})[0],200)
        _,_,restored=self.request('/api/backup')
        for table in ('actions','action_results','evidence','artifacts','decision_requests','proposals','agents'):
            self.assertEqual(restored['gateway'][table],before['gateway'][table])

    def test_restore_into_another_database(self):
        self.populate();_,_,backup=self.request('/api/backup')
        other=BackupCase();other.setUp()
        try:
            _,rev,_=other.request('/api/state')
            self.assertEqual(other.request('/api/action',{'collection':'projects','op':'delete','id':'p1','ifRev':rev})[0],200)
            _,rev,_=other.request('/api/state')
            self.assertEqual(other.request('/api/restore',{'backup':backup,'ifRev':rev})[0],200)
            _,_,after=other.request('/api/backup')
            for table in ('actions','action_results','artifacts','evidence','decision_requests','proposals'):
                self.assertEqual(backup['gateway'][table],after['gateway'][table])
        finally: other.tearDown()

    def test_gateway_change_advances_revision_and_daily_snapshot_is_full(self):
        _,before,_=self.request('/api/state')
        for p in (self.dir/'snapshots').glob('*'): p.unlink()
        self.populate();_,after,_=self.request('/api/state')
        self.assertGreater(after,before)
        snapshots=list((self.dir/'snapshots').glob('auto-*.json'))
        self.assertEqual(len(snapshots),1)
        snap=json.loads(snapshots[0].read_text())
        self.assertEqual(snap['format'],'research-desk-project-backup')
        self.assertEqual(set(snap['gateway']),{'agents','actions','artifacts','evidence','action_results','decision_requests','proposals','project_events','action_contracts','action_recoveries','result_reviews','ecosystem_items'})
        self.assertNotIn('token_hash',json.dumps(snap))
        _,rev,state=self.request('/api/state');state['projects']=[];state['tasks']=[]
        self.assertEqual(self.request('/api/state',{'state':state,'ifRev':rev})[0],400)
