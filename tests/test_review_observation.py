"""Material-bound review and coverage behavior; isolated fixtures, no model/network calls."""
import copy
import hashlib
import json
import time
import sqlite3
import unittest

import test_ecosystem as support
import agent_gateway
import ecosystem
import observation_service
import project_backup
import review_service


def output():
    value = {key: '合成评审，未核验：' + label for key, label in review_service.FIELDS.items()}
    value['citations'] = [{'claim': '方案 A 有成本约束', 'material_id': 'M1', 'locator': 'L1-L2', 'relation': 'source'}]
    return value


class ReviewCase(unittest.TestCase):
    setUp = support.EcosystemCase.setUp
    tearDown = support.EcosystemCase.tearDown
    connect = support.EcosystemCase.connect
    rev = support.EcosystemCase.rev
    bump = support.EcosystemCase.bump
    post = support.EcosystemCase.post
    profile = support.EcosystemCase.profile
    get = support.EcosystemCase.get
    start = support.EcosystemCase.start
    external = support.EcosystemCase.external

    def review(self, **kw):
        self.review_counter = getattr(self, 'review_counter', 0) + 1
        agent = self.external('reviewer' + str(self.review_counter))
        profile = self.profile(agent=agent['id'])
        values = dict(title='选择方案', question='如何控制成本？', constraints='每月费用不超过预算',
                      materials=[{'title': '方案说明', 'content': '方案 A\n成本上限 100\n未做真实试用', 'reference': 'fixture'}],
                      profile_ids=[profile['id']], max_rounds=1, max_calls=1)
        values.update(kw)
        return agent, self.post('review.create', **values)

    def completed(self):
        agent, room = self.review()
        self.start(room)
        request = self.eco.agent_get(agent)['requests'][0]
        self.eco.agent_reply(agent, dict(request, output=output()))
        return self.get(room, 'room')

    def test_material_snapshot_reply_edit_adopt_and_export(self):
        room = self.completed()
        self.assertEqual(room['status'], 'completed')
        self.assertEqual(room['used_calls'], 1)
        self.assertEqual(room['brief']['revision'], 1)
        self.assertEqual(room['materials'][0]['version'], hashlib.sha256(room['materials'][0]['content'].encode()).hexdigest())
        modified = output(); modified['recommendation'] = '人工修改为先访谈再选择'
        # A unrelated profile write must not invalidate this object-level edit.
        rev = self.eco.view('p1')['rev']
        self.profile('model-b')
        edited = self.eco.post(dict(operation='review.brief.save', project_id='p1', id=room['id'], ifRev=rev,
            expected_rev=room['object_rev'], brief_revision=1, content=modified, reason='需要真实用户依据'))['item']
        self.assertEqual(edited['brief']['revision'], 2)
        self.assertEqual(edited['messages'][0]['output'], output())
        self.assertEqual(edited['brief']['edits'][0]['content'], output())
        self.assertIn('L2: 成本上限 100', review_service.markdown(edited))
        self.assertIn('人工修改为先访谈再选择', review_service.markdown(edited))
        with self.assertRaisesRegex(ValueError, '对象已变化'):
            self.eco.post(dict(operation='review.brief.save', project_id='p1', id=room['id'], expected_rev=room['object_rev'], brief_revision=2, content=modified, reason='过期编辑'))
        with self.assertRaisesRegex(ValueError, '简报版本'):
            self.post('room.adopt', id=room['id'], target='decision', title='先访谈', rationale='待核实', brief_revision=1)
        adopted = self.post('room.adopt', id=room['id'], target='decision', title='先访谈', rationale='保留未知', brief_revision=2)
        decision = self.eco.view('p1')['context']['decisions'][0]
        self.assertEqual(decision['review_ref']['brief_revision'], 2)
        self.assertEqual(decision['material_refs'][0]['version'], room['materials'][0]['version'])
        self.assertEqual(decision['verification_status'], 'UNVERIFIED')
        with self.assertRaises(ValueError):
            self.post('review.brief.save', id=adopted['id'], brief_revision=2, content=modified, reason='覆盖已采纳')

    def test_external_contract_and_citation_rejection_do_not_consume_budget(self):
        agent, room = self.review()
        self.start(room)
        request = self.eco.agent_get(agent)['requests'][0]
        self.assertEqual(request['reply_tool'], 'project.reply_review')
        self.assertEqual(request['materials'], room['materials'])
        self.assertEqual(request['output_schema'], review_service.SCHEMA)
        for material, locator, relation in [('M2','L1','source'),('M1','L9','source'),('M1','L2-L1','source'),('','','source')]:
            bad = output();bad['citations'][0].update(material_id=material, locator=locator, relation=relation)
            with self.assertRaises(ValueError):
                self.eco.agent_reply(agent, dict(request, output=bad))
        self.assertEqual(self.get(room, 'room')['used_calls'], 0)
        self.assertEqual(self.get(room, 'room')['messages'], [])
        self.eco.agent_reply(agent, dict(request, output=output()))
        with self.assertRaises(ValueError):
            self.eco.agent_reply(agent, dict(request, output=output()))
        self.assertEqual(self.get(room, 'room')['used_calls'], 1)

    def test_without_executor_draft_and_pack_import_are_side_effect_free_until_confirmed(self):
        body=dict(operation='review.create',project_id='p1',ifRev=self.eco.view('p1')['rev'],title='先记录问题',question='如何选择？',materials=[{'title':'材料','content':'A\nB'}],constraints='',profile_ids=[],max_calls=1,max_rounds=1)
        before=self.eco.view('p1')
        self.eco.post(dict(body,dry=True))
        self.assertEqual(self.eco.view('p1'),before)
        room=self.eco.post(body)['item']
        with self.assertRaisesRegex(ValueError,'请选择一个执行器'):self.start(room)
        profile=self.profile()
        configured=self.post('review.executor',id=room['id'],expected_rev=room['object_rev'],profile_id=profile['id'])
        self.assertEqual(configured['used_calls'],0)
        self.assertEqual(len(configured['participants']),1)
        with self.connect() as c:
            snapshot=project_backup.envelope(c)
            project_backup.validate(snapshot['state'],snapshot['gateway'],c,portable=True)
        pack={'schema_version':'yanxu.source-pack.v1','name':'验收来源包','question':'价格是否改变？','sources':[{'name':'公开例子','url':'https://example.org/feed','keywords':[],'interval_minutes':60}]}
        payload=dict(operation='source.pack.import',project_id='p1',ifRev=self.eco.view('p1')['rev'],pack=pack)
        before=self.eco.view('p1');self.eco.post(dict(payload,dry=True));self.assertEqual(self.eco.view('p1'),before)
        imported=self.eco.post(payload)['item']['watches'][0]
        self.assertFalse(imported['enabled']);self.assertFalse(imported['auto_push']);self.assertEqual(imported['question'],pack['question'])
        bad=copy.deepcopy(pack);bad['sources'][0]['url']='http://127.0.0.1/secret'
        with self.assertRaises(ValueError):self.post('source.pack.import',pack=bad)

    def test_project_context_change_rejects_late_external_reply(self):
        agent,room=self.review();self.start(room);request=self.eco.agent_get(agent)['requests'][0]
        with self.connect() as c:
            state=self.gateway.state(c);state['projects'][0]['goal']='新的真实目标';c.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(state),))
        with self.assertRaisesRegex(ValueError,'项目记录已变化'):self.eco.agent_reply(agent,dict(request,output=output()))
        self.assertEqual(self.get(room,'room')['messages'],[])

    def selected_records(self):
        with self.connect() as c:
            state = self.gateway.state(c)
            state['tasks'] = [{'id':'t1','project':'p1','title':'选定任务'}, {'id':'t2','project':'p1','title':'未选任务'}]
            state['decisions'] = [{'id':'d1','project':'p1','title':'复核原判断'}, {'id':'d2','project':'p2','title':'另一项目'}]
            c.execute('UPDATE state SET body=? WHERE id=1', (json.dumps(state),))

    def test_selected_wire_context_survives_unrelated_record_changes(self):
        self.selected_records()
        agent,room=self.review(context_selection={'tasks':['t1'],'decisions':[],'results':[]},review_of='d1')
        self.assertEqual([r['id'] for r in room['context']['tasks']],['t1'])
        self.assertEqual([r['id'] for r in room['context']['decisions']],['d1'])
        with self.connect() as c:
            state=self.gateway.state(c);state['tasks'][1]['title']='未选任务更新';c.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(state),));self.bump(c)
        self.assertFalse(self.eco.view('p1')['rooms'][0]['context_stale'])
        self.start(room);request=self.eco.agent_get(agent)['requests'][0]
        self.assertEqual(request['context'],room['context'])
        self.assertNotIn('未选任务更新',review_service.prompt(room,room['participants'][0]))
        with self.connect() as c:
            state=self.gateway.state(c);state['tasks'][1]['title']='再次更新';c.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(state),));self.bump(c)
        self.eco.agent_reply(agent,dict(request,output=output()))
        current=self.get(room,'room')
        self.post('room.adopt',id=room['id'],expected_rev=current['object_rev'],target='decision',title='小范围判断',rationale='只根据选定记录',brief_revision=1)
        self.assertEqual(self.eco.view('p1')['context']['decisions'][0]['id'],'d1','Old decision preserved')

    def test_selected_change_or_removal_blocks_dispatch_and_late_reply(self):
        for remove in (False,True):
            self.selected_records()
            agent,room=self.review(context_selection={'tasks':['t1'],'decisions':[],'results':[]})
            room=self.start(room);request=next(r for r in self.eco.agent_get(agent)['requests'] if r['room_id']==room['id'])
            with self.connect() as c:
                state=self.gateway.state(c)
                if remove:state['tasks']=[r for r in state['tasks'] if r['id']!='t1']
                else:state['tasks'][0]['title']='选定任务变化'
                c.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(state),));self.bump(c)
            view=self.eco.view('p1');self.assertTrue(next(r for r in view['rooms'] if r['id']==room['id'])['context_stale'])
            self.assertFalse(any(r['room_id']==room['id'] for r in self.eco.agent_get(agent)['requests']))
            with self.assertRaisesRegex(ValueError,'项目记录已变化'):self.eco.agent_reply(agent,dict(request,output=output()))
            with self.assertRaisesRegex(RuntimeError,'记录变化'):
                with self.eco.send_guard('p1',room,room['participants'][0]):pass
            self.assertEqual(self.get(room,'room')['used_calls'],0)

    def test_material_only_context_has_no_implicit_records_and_goal_still_gates(self):
        self.selected_records()
        agent,room=self.review(context_selection={'tasks':[],'decisions':[],'results':[]})
        self.assertEqual(room['context']['tasks'],[]);self.assertEqual(room['context']['decisions'],[])
        with self.connect() as c:
            state=self.gateway.state(c);state['projects'][0]['goal']='变化的目标';c.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(state),))
        with self.assertRaisesRegex(ValueError,'上下文已变化'):self.start(room)

    def test_selection_rejects_cross_project_duplicate_and_unknown_ids(self):
        self.selected_records()
        for selected in ({'tasks':[],'decisions':['d2'],'results':[]}, {'tasks':['missing'],'decisions':[],'results':[]}, {'tasks':['t1','t1'],'decisions':[],'results':[]}):
            with self.assertRaises(ValueError):self.review(context_selection=selected)

    def test_selected_snapshot_backup_rejects_scope_tampering_even_with_new_hash(self):
        self.selected_records();agent,room=self.review(context_selection={'tasks':['t1'],'decisions':[],'results':[]})
        with self.connect() as c:
            snapshot=project_backup.envelope(c);project_backup.validate(snapshot['state'],snapshot['gateway'],c,portable=True)
            tampered=copy.deepcopy(snapshot['gateway']);row=next(r for r in tampered['ecosystem_items'] if r['id']==room['id']);body=json.loads(row['body'])
            body['context']['selection']['tasks']=[];body['context']['context_hash']=ecosystem.digest({k:v for k,v in body['context'].items() if k!='context_hash'});row['body']=json.dumps(body)
            with self.assertRaisesRegex(ValueError,'记录范围'):project_backup.validate(snapshot['state'],tampered,c,portable=True)

    def test_legacy_review_retains_full_context_and_broad_guard(self):
        self.selected_records();agent,room=self.review()
        self.assertNotIn('selection',room['context']);self.assertEqual(len(room['context']['tasks']),2)
        with self.connect() as c:
            state=self.gateway.state(c);state['tasks'][1]['title']='旧客户端仍发送此任务';c.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(state),))
        with self.assertRaisesRegex(ValueError,'上下文已变化'):self.start(room)

    def test_explicit_result_selection_includes_old_result_without_recent_window_truncation(self):
        with self.connect() as c:
            for i in range(25):
                c.execute('INSERT INTO action_results(id,action_id,project_id,outcome,summary,source_ref,actor,created_at,source_version,verification_status) VALUES(?,?,?,?,?,?,?,?,?,?)',
                          ('r'+str(i),'fixture-action','p1','failure','结果 '+str(i),'synthetic://result','fixture',str(i).zfill(3),'version-'+str(i),'UNVERIFIED'))
        agent,room=self.review(context_selection={'tasks':[],'decisions':[],'results':['r0']})
        self.assertEqual([r['id'] for r in room['context']['results']],['r0'])
        self.assertEqual(room['context']['results'][0]['source_version'],'version-0')
        room=self.start(room);request=self.eco.agent_get(agent)['requests'][0]
        with self.connect() as c:
            c.execute("UPDATE action_results SET summary='未选结果更新' WHERE id='r24'")
        self.assertFalse(self.eco.view('p1')['rooms'][0]['context_stale'])
        with self.connect() as c:
            c.execute("UPDATE action_results SET source_version='changed-version' WHERE id='r0'")
        with self.assertRaisesRegex(ValueError,'项目记录已变化'):self.eco.agent_reply(agent,dict(request,output=output()))

    def test_review_restore_preserves_brief_and_rejects_material_tamper(self):
        room = self.completed()
        with self.connect() as c:
            snapshot = project_backup.envelope(c)
            project_backup.validate(snapshot['state'], snapshot['gateway'], c, portable=True)
            tampered = copy.deepcopy(snapshot['gateway'])
            row = next(r for r in tampered['ecosystem_items'] if r['id'] == room['id'])
            body = json.loads(row['body']);body['materials'][0]['content'] = '替换的材料';row['body'] = json.dumps(body)
            with self.assertRaisesRegex(ValueError, '材料'):
                project_backup.validate(snapshot['state'], tampered, c, portable=True)
            project_backup.restore(c, snapshot['state'], snapshot['gateway'], portable=True)
        self.assertEqual(self.get(room, 'room')['brief'], room['brief'])

    def test_review_dry_preserves_state_and_rejects_cross_space_judgment(self):
        agent, room = self.review()
        body = dict(operation='review.brief.save', project_id='p2', id=room['id'], expected_rev=room['object_rev'], brief_revision=1, content=output(), reason='cross')
        with self.assertRaises(agent_gateway.GatewayError):
            self.eco.post(body)
        self.assertEqual(self.eco.view('p2')['rooms'], [])
        with self.assertRaisesRegex(ValueError, '已登记判断'):
            self.review(review_of='outside-decision')
        with self.assertRaisesRegex(ValueError, '一个执行器'):
            self.review(max_calls=2)

    def test_change_marks_linked_decision_for_review_without_mutation(self):
        room = self.completed()
        self.post('room.adopt', id=room['id'], target='decision', title='成本判断', rationale='材料范围内暂定', brief_revision=1)
        decision = self.eco.view('p1')['context']['decisions'][0]
        watch = self.post('watch.save', name='成本公开来源', question='成本假设是否改变？', url='https://example.com/cost', keywords=[], decision_ids=[decision['id']], interval_minutes=60)
        def fetched(text):
            return dict(url=watch['url'], text=text, hash=hashlib.sha256(text.encode()).hexdigest())
        self.eco.fetcher = lambda _: fetched('价格 100')
        self.eco.check_watch('p1',watch['id'])
        self.eco.fetcher = lambda _: fetched('价格 200')
        self.eco.check_watch('p1',watch['id'])
        view = self.eco.view('p1')
        self.assertEqual(view['context']['decisions'][0], decision)
        self.assertEqual(view['impacts'][0]['status'], 'needs_review')
        self.assertEqual(view['alerts'][0]['brief']['question'], '成本假设是否改变？')
        self.post('alert.review', id=view['alerts'][0]['id'], status='dismissed')
        self.assertEqual(self.eco.view('p1')['impacts'], [])
        self.assertEqual(self.eco.view('p1')['observations'][0]['changes'], [])

    def test_old_backup_cannot_reset_consumed_budget_or_reuse_identity(self):
        agent, room = self.review()
        with self.connect() as c:
            old = project_backup.envelope(c)
        self.start(room)
        request = self.eco.agent_get(agent)['requests'][0]
        self.eco.agent_reply(agent, dict(request, output=output()))
        completed = self.get(room, 'room')
        with self.connect() as c:
            project_backup.restore(c, old['state'], old['gateway'], portable=True)
        restored = self.get(room, 'room')
        self.assertEqual(restored['used_calls'], 1)
        self.assertEqual(restored['status'], 'interrupted')
        self.assertGreater(restored['object_rev'], completed['object_rev'])
        with self.assertRaises(ValueError):self.start(restored)
        with self.connect() as c:
            self.assertEqual(c.execute('SELECT state FROM ecosystem_attempts WHERE room_id=?',(room['id'],)).fetchone()[0],'reply_accepted')
            corrupt=copy.deepcopy(old['gateway'])
            row=next(r for r in corrupt['ecosystem_items'] if r['id']==room['id'])
            value=json.loads(row['body']);value['question']='复用旧 ID 进行新评审';row['body']=json.dumps(value)
            with self.assertRaisesRegex(ValueError,'原执行契约'):
                project_backup.restore(c,old['state'],corrupt,portable=True)

    def test_send_intent_releases_database_before_executor_wait(self):
        profile=self.profile()
        room=self.post('review.create',title='单执行器',question='选择方案？',constraints='',materials=[{'title':'材料','content':'A\nB'}],profile_ids=[profile['id']],max_rounds=1,max_calls=1)
        room=self.start(room)
        with self.eco.send_guard('p1',room,room['participants'][0]):
            other=sqlite3.connect(self.path,timeout=.1)
            try:
                other.execute('BEGIN IMMEDIATE')
                other.execute("UPDATE meta SET v=v WHERE k='rev'")
                other.commit()
            finally:other.close()
        with self.connect() as c:
            self.assertEqual(c.execute('SELECT state FROM ecosystem_attempts WHERE room_id=?',(room['id'],)).fetchone()[0],'dispatched')


class CoverageCase(unittest.TestCase):
    def test_failure_baseline_staleness_and_paused_are_distinct(self):
        now=time.time(); timestamp=ecosystem.stamp()
        base=dict(id='w',name='官方价格',question='价格是否改变？',url='https://example.com',enabled=False,interval_minutes=60,
                  last_checked=timestamp,snapshot=dict(captured_at=timestamp),last_result='unchanged')
        covered=observation_service.coverage([base],[],now)[0]
        self.assertEqual(covered['covered'],1)
        self.assertFalse(covered['sources'][0]['automatic'])
        failed=dict(base,id='f',error='网络失败')
        partial=observation_service.coverage([base,failed],[],now)[0]
        self.assertEqual(partial['covered'],1)
        self.assertFalse(partial['complete'])
        self.assertIn('未覆盖',partial['summary'])
        stale=observation_service.coverage([base],[],now+7201)[0]
        self.assertEqual(stale['sources'][0]['status'],'stale')
        never=observation_service.coverage([dict(base,snapshot=None)],[],now)[0]
        self.assertEqual(never['sources'][0]['status'],'not_checked')


if __name__ == '__main__':unittest.main()
