"""Persistent groups tested with synthetic executors only."""
import copy
import json
import unittest
import test_ecosystem as fixture
import agent_gateway
import ecosystem
import group_chat

class GroupChatCase(unittest.TestCase):
    setUp=fixture.EcosystemCase.setUp
    tearDown=fixture.EcosystemCase.tearDown
    connect=fixture.EcosystemCase.connect
    rev=fixture.EcosystemCase.rev
    bump=fixture.EcosystemCase.bump
    post=fixture.EcosystemCase.post
    profile=fixture.EcosystemCase.profile
    get=fixture.EcosystemCase.get
    external=fixture.EcosystemCase.external

    def group(self, members=()):
        return self.post('group.create',name='产品讨论群',profile_ids=[m['id'] for m in members])

    def send(self,g,members=(),**kwargs):
        return self.post('group.send',id=g['id'],content='这一版先做什么？',reply_profile_ids=[m['id'] for m in members],history_count=20,consent=group_chat.CONSENT,**kwargs)

    def test_empty_group_and_human_only_persist_without_call(self):
        g=self.group();g=self.send(g)
        self.assertEqual(len(g['entries']),1)
        self.assertFalse(g['entries'][0]['room_id'])
        state=self.eco.view('p1')
        self.assertEqual(state['groups'][0]['timeline'][0]['content'],'这一版先做什么？')
        self.assertEqual(state['groups'][0]['used_calls'],0)
        self.assertEqual(self.executor.calls,[])

    def test_two_models_single_turn_then_subset_with_frozen_history(self):
        a,b=self.profile(),self.profile('model-b');g=self.group([a,b]);g=self.send(g,[a,b]);rid=g['entries'][-1]['room_id']
        with self.assertRaisesRegex(ValueError,'正在回复'):self.send(g)
        self.eco.run_room('p1', rid)
        state=self.eco.view('p1');self.assertEqual(len(state['groups'][0]['timeline']),3)
        self.assertEqual(state['groups'][0]['used_calls'],2)
        self.assertEqual([c['model'] for c in self.executor.calls],['model-a','model-b'])
        g=self.send(g,[b]);room=self.get({'id':g['entries'][-1]['room_id'],'project_id':'p1'},'room')
        self.assertEqual(len(room['group_source']['history']),3)
        self.assertEqual(room['max_calls'],1)
        self.assertEqual(room['context']['tasks'],[])
        self.assertEqual(room['context']['decisions'],[])
        self.eco.run_room('p1', room['id']);self.assertEqual(self.eco.view('p1')['groups'][0]['used_calls'],3)
        self.assertEqual(self.get(room,'room')['status'],'completed')

    def test_edit_members_does_not_rewrite_running_contract(self):
        a,b=self.profile(),self.profile('model-b');g=self.send(self.group([a]),[a]);room=self.get({'id':g['entries'][-1]['room_id'],'project_id':'p1'},'room');before=ecosystem.room_contract(room)
        g=self.post('group.update',id=g['id'],expected_rev=g['object_rev'],name='改名群',profile_ids=[b['id']])
        self.assertEqual(before,ecosystem.room_contract(self.get(room,'room')))
        self.eco.run_room('p1', room['id']);self.assertEqual(self.executor.calls[0]['model'],'model-a')
        with self.assertRaisesRegex(ValueError,'当前群成员'):self.send(g,[a])

    def test_missing_consent_is_atomic_and_dry_never_launches(self):
        a=self.profile();g=self.group([a]);before=self.eco.view('p1')
        with self.assertRaisesRegex(ValueError,'确认本条'):self.post('group.send',id=g['id'],content='私密文字',reply_profile_ids=[a['id']])
        self.assertEqual(before,self.eco.view('p1'))
        self.post('group.send',id=g['id'],content='预览',reply_profile_ids=[a['id']],consent=group_chat.CONSENT,dry=True)
        self.assertEqual(before,self.eco.view('p1'))
        self.assertEqual(self.executor.calls,[])

    def test_project_duplicate_and_stale_revision_rejected(self):
        a=self.profile();other=self.profile(project='p2')
        with self.assertRaises(ValueError):self.group([a,a])
        with self.assertRaises(agent_gateway.GatewayError):self.group([other])
        g=self.group([a]);old=g['object_rev'];self.send(g)
        with self.assertRaises(ValueError):self.post('group.update',id=g['id'],expected_rev=old,name='过期',profile_ids=[])

    def test_stop_then_send_retains_usage_and_no_replay(self):
        a=self.profile();g=self.send(self.group([a]),[a]);room=self.get({'id':g['entries'][-1]['room_id'],'project_id':'p1'},'room')
        self.executor.hook=lambda:self.post('room.stop',id=room['id'])
        self.eco.run_room('p1', room['id']);self.assertEqual(self.eco.view('p1')['groups'][0]['used_calls'],1)
        self.assertFalse(any(m['kind']=='agent' for m in self.eco.view('p1')['groups'][0]['timeline']))
        self.executor.hook=None;g=self.send(g,[a]);self.eco.run_room('p1', g['entries'][-1]['room_id'])
        self.assertEqual(len(self.executor.calls),2)
        self.assertEqual(self.eco.view('p1')['groups'][0]['used_calls'],2)

    def test_backup_graph_and_failure_history(self):
        a=self.profile();g=self.send(self.group([a]),[a]);self.executor.error=True
        self.eco.run_room('p1',g['entries'][-1]['room_id'])
        timeline=self.eco.view('p1')['groups'][0]['timeline']
        self.assertEqual(timeline[-1]['kind'],'system')
        self.assertIn('synthetic failure',timeline[-1]['content'])
        with self.connect() as c:
            rows=[dict(zip(('id','project_id','kind','body'),r)) for r in c.execute('SELECT id,project_id,kind,body FROM ecosystem_items')]
            state=json.loads(c.execute('SELECT body FROM state').fetchone()[0])
        ecosystem.validate_backup(rows,state,[])
        tampered=copy.deepcopy(rows)
        group_row=next(r for r in tampered if r['kind']=='group');body=json.loads(group_row['body']);body['entries'][0]['content']='替换';group_row['body']=json.dumps(body)
        with self.assertRaisesRegex(ValueError,'不一致'):ecosystem.validate_backup(tampered,state,[])

    def test_external_member_gets_frozen_history_and_revoke_blocks_send(self):
        agent=self.external();a=self.profile(agent=agent['id']);g=self.group([a]);g=self.send(g);g=self.send(g,[a])
        request=self.eco.agent_get(agent)['requests'][0]
        self.assertEqual(request['group_source']['group_id'],g['id'])
        self.assertEqual(len(request['previous_messages']),1)
        self.eco.agent_reply(agent,dict(room_id=request['room_id'],participant_id=a['id'],run_id=request['run_id'],output=dict(position='合成',evidence='fixture',objections='待验',next_step='核验')))
        self.assertEqual(self.eco.view('p1')['groups'][0]['used_calls'],1)
        with self.connect() as c:c.execute("UPDATE agents SET permission='READ' WHERE id=?",(agent['id'],))
        with self.assertRaisesRegex(ValueError,'撤权'):self.send(g,[a])

    def test_history_hash_and_count_validation(self):
        g=self.group();g=self.send(g)
        source=group_chat.freeze(g,[],20);group_chat.validate_source(source,'p1')
        corrupted=copy.deepcopy(source);corrupted['history'][0]['content']='篡改'
        with self.assertRaises(ValueError):group_chat.validate_source(corrupted,'p1')
        for count in (-1,21,True,'20'):
            with self.assertRaises(ValueError):group_chat.freeze(g,[],count)
        self.assertEqual(group_chat.freeze(g,[],0)['history'],[])

if __name__=='__main__':unittest.main()
