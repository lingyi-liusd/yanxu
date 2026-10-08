# -*- coding: utf-8 -*-
"""Group-directed radar deliveries; synthetic sources/models only."""
import copy,json,unittest
import test_ecosystem as f
import ecosystem,agent_gateway,group_chat
D=ecosystem.APP_SPACES['discussion'];R=ecosystem.APP_SPACES['radar']
class RadarGroupCase(unittest.TestCase):
    setUp=f.EcosystemCase.setUp
    tearDown=f.EcosystemCase.tearDown
    connect=f.EcosystemCase.connect
    rev=f.EcosystemCase.rev
    bump=f.EcosystemCase.bump
    post=f.EcosystemCase.post
    profile=f.EcosystemCase.profile
    get=f.EcosystemCase.get
    snapshot=f.EcosystemCase.snapshot
    external=f.EcosystemCase.external
    def prepare(self,external=False):
        self.eco.init_apps({'ifRev':self.eco.apps('discussion')['rev']})
        agent=self.external(project=D) if external else None
        self.member=self.profile(project=D,agent=agent['id'] if agent else None)
        self.group=self.post('group.create',D,name='雷达接收群',profile_ids=[self.member['id']])
        self.watch=self.post('watch.save',R,name='合成动态',url='https://example.org/news',keywords=['AI'],interval_minutes=60,enabled=False,auto_push=True,push_target='personal',push_group_id=self.group['id'])
        return agent
    def check(self,text):
        self.eco.fetcher=lambda url:self.snapshot(text);self.eco.check_watch(R,self.watch['id'])
    def deliver(self):
        self.prepare();self.check('AI baseline');self.check('AI update');return self.eco.view(D)['inbox'][0]
    def confirm(self,i,**overrides):
        g=self.eco.view(D)['groups'][0];v=dict(id=g['id'],expected_rev=g['object_rev'],content='分析变化',reply_profile_ids=[self.member['id']],history_count=5,inbox_id=i['id'],inbox_expected_rev=i['object_rev'],source_version=i['source_version'],consent=group_chat.CONSENT);v.update(overrides);return self.post('group.send',D,**v)
    def test_baseline_filter_push_dedup_no_models(self):
        self.prepare();self.check('AI baseline');self.check('AI baseline\nother');self.assertEqual(self.eco.view(D)['inbox'],[])
        self.check('AI update');v=self.eco.view(D);self.assertEqual(v['groups'][0]['unread_count'],1);self.assertEqual(len(v['groups'][0]['pending_inbox']),1);self.assertFalse(v['groups'][0]['entries']);self.assertFalse(self.executor.calls)
        i=v['inbox'][0];self.post('alert.push',R,id=i['origin_alert_id'],target=D,group_id=self.group['id']);self.check('AI update');self.assertEqual(len(self.eco.view(D)['inbox']),1)
    def test_confirm_source_bound_reply_duplicate_rejected(self):
        i=self.deliver();g=self.confirm(i);room=self.get({'id':g['entries'][-1]['room_id'],'project_id':D},'room');self.assertEqual(room['source_change'],i['source_change']);self.assertEqual(room['source_version'],i['source_version']);self.assertEqual(self.eco.view(D)['groups'][0]['pending_inbox'],[])
        self.eco.run_room(D,room['id']);self.assertIn(i['source_change']['after_hash'],self.executor.calls[0]['prompt'])
        with self.assertRaises(ValueError):self.confirm(i)
        self.assertEqual(len(self.executor.calls),1)
    def test_end_to_end_confirm_adopt_and_project_readback(self):
        incoming=self.deliver()
        self.assertFalse(self.executor.calls,'delivery must not invoke a model')
        group=self.confirm(incoming)
        room_id=group['entries'][-1]['room_id']
        self.eco.run_room(D,room_id)
        self.assertEqual(len(self.executor.calls),1)
        room=self.get({'id':room_id,'project_id':D},'room')
        target_context=self.eco.view('p1')['context']
        adopted=self.post('room.adopt',D,id=room_id,title='合成闭环 · 复核变化',rationale='合成建议只作为待验证任务',target='task',target_project_id='p1',target_context_hash=target_context['context_hash'])
        task=next(t for t in self.eco.view('p1')['context']['tasks'] if t['id']==adopted['adopted_id'])
        self.assertEqual(task['verification_status'],'UNVERIFIED')
        self.assertEqual(task['source_ref'],'yanxu://room/'+room_id)
        self.assertEqual(task['source_version'],adopted['adoptions'][0]['source_version'])
        self.assertEqual(room['source_version'],incoming['source_version'])
        self.assertFalse(self.eco.view('p2')['context']['tasks'])
        self.assertFalse(self.eco.view(D)['groups'][0]['pending_inbox'])
        with self.assertRaises(ValueError):self.confirm(incoming)
        self.assertEqual(len(self.executor.calls),1,'readback and duplicate rejection add no model calls')
    def test_dry_no_resolution_no_calls(self):
        i=self.deliver();before=self.eco.view(D);self.confirm(i,dry=True);self.assertEqual(before,self.eco.view(D));self.assertFalse(self.executor.calls)
    def test_stale_hash_members_consent_atomic(self):
        i=self.deliver();before=self.eco.view(D)
        for v in ({'inbox_expected_rev':0},{'inbox_expected_rev':True},{'source_version':'0'*64},{'reply_profile_ids':[]},{'consent':''}):
            with self.assertRaises(ValueError):self.confirm(i,**v)
            self.assertEqual(before,self.eco.view(D))
    def test_seen_dismiss_preserve_original(self):
        i=self.deliver();self.post('inbox.review',D,id=i['id'],status='seen');v=self.eco.view(D);self.assertEqual(v['unread_count'],0);self.assertEqual(len(v['groups'][0]['pending_inbox']),1)
        self.post('inbox.review',D,id=i['id'],status='dismissed');self.assertEqual(self.eco.view(D)['groups'][0]['pending_inbox'],[])
        with self.assertRaises(ValueError):self.confirm(self.eco.view(D)['inbox'][0])
    def test_cross_scope_wrong_group_and_room_bypass(self):
        i=self.deliver();other=self.post('group.create','p2',name='other',profile_ids=[])
        with self.assertRaises(agent_gateway.GatewayError):self.post('alert.push',R,id=i['origin_alert_id'],target=D,group_id=other['id'])
        other=self.post('group.create',D,name='other',profile_ids=[self.member['id']])
        with self.assertRaises(ValueError):self.confirm(i,id=other['id'],expected_rev=other['object_rev'])
        with self.assertRaises(ValueError):self.post('room.create',D,title='bypass',question='Q',profile_ids=[self.member['id']],max_rounds=1,max_calls=1,inbox_id=i['id'])
    def test_missing_destination_preserves_discovery(self):
        self.prepare();self.check('AI baseline')
        with self.connect() as c:c.execute('DELETE FROM ecosystem_items WHERE id=?',(self.group['id'],))
        self.check('AI update');v=self.eco.view(R);self.assertEqual(len(v['alerts']),1);self.assertTrue(v['watches'][0]['delivery_error']);self.assertEqual(v['watches'][0]['snapshot']['hash'],self.snapshot('AI update')['hash'])
        self.check('AI update');self.assertEqual(len(self.eco.view(R)['alerts']),1);self.assertEqual(self.eco.view(D)['inbox'],[])
    def test_backup_tamper_rejected(self):
        i=self.deliver();self.confirm(i)
        with self.connect() as c:
            c.row_factory=__import__('sqlite3').Row;rows=[dict(r) for r in c.execute('SELECT * FROM ecosystem_items')];state=json.loads(c.execute('SELECT body FROM state').fetchone()[0])
        ecosystem.validate_backup(rows,state,[])
        for key in ('inbox_id', 'room_id'):
            bad=copy.deepcopy(rows);row=next(r for r in bad if r['kind']=='group');v=json.loads(row['body']);v['entries'][0].pop(key);row['body']=json.dumps(v)
            with self.assertRaises(ValueError):ecosystem.validate_backup(bad,state,[])
        for kind,key in [('watch','push_group_id'),('inbox','group_id')]:
            bad=copy.deepcopy(rows);row=next(r for r in bad if r['kind']==kind);v=json.loads(row['body']);v[key]='nonexistent';row['body']=json.dumps(v)
            with self.assertRaises(ValueError):ecosystem.validate_backup(bad,state,[])
    def test_external_source_snapshot(self):
        agent=self.prepare(external=True);self.check('AI baseline');self.check('AI update');i=self.eco.view(D)['inbox'][0];self.confirm(i);r=self.eco.agent_get(agent)['requests'][0];self.assertEqual(r['source_change'],i['source_change']);self.assertEqual(r['group_source']['group_id'],self.group['id'])
if __name__=='__main__':unittest.main()
