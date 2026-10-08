"""Historical material use and target-object gates, isolated records and external replies only."""
import copy
import json
import unittest

import ecosystem
import project_backup
import review_history
import review_service
import test_review_observation as review_support

output = review_support.output


class HistoryCase(unittest.TestCase):
    setUp = review_support.ReviewCase.setUp
    tearDown = review_support.ReviewCase.tearDown
    connect = review_support.ReviewCase.connect
    rev = review_support.ReviewCase.rev
    bump = review_support.ReviewCase.bump
    post = review_support.ReviewCase.post
    profile = review_support.ReviewCase.profile
    get = review_support.ReviewCase.get
    start = review_support.ReviewCase.start
    external = review_support.ReviewCase.external
    review = review_support.ReviewCase.review
    completed = review_support.ReviewCase.completed
    selected_records = review_support.ReviewCase.selected_records

    def request(self, source, **updates):
        result = {'room_id': source['id'], 'expected_rev': source['object_rev'], 'context_hash': source['context']['context_hash'],
                  'reason': '仍需对比原条件，历史结果未核验', 'selection': {'materials': ['M1'], 'tasks': [], 'decisions': [], 'results': []}}
        result.update(updates)
        return result

    def historical(self, source, **updates):
        values = {'title': '明确历史材料评审', 'question': '原条件是否仍成立？', 'constraints': '历史信息不能冒充当前信息',
                  'profile_ids': [], 'max_rounds': 1, 'max_calls': 1, 'context_selection': {'tasks': [], 'decisions': [], 'results': []},
                  'history_source': self.request(source)}
        values.update(updates)
        return self.post('review.create', **values)

    def change(self, mutate):
        with self.connect() as c:
            state = self.gateway.state(c); mutate(state)
            c.execute('UPDATE state SET body=? WHERE id=1', (json.dumps(state),)); self.bump(c)

    def test_old_snapshot_becomes_material_with_current_project_and_original_consumption(self):
        self.selected_records()
        agent, source = self.review(context_selection={'tasks': ['t1'], 'decisions': [], 'results': []})
        self.start(source); self.eco.agent_reply(agent, dict(self.eco.agent_get(agent)['requests'][0], output=output()))
        source = self.get(source, 'room')
        self.change(lambda state: (state['tasks'][0].update(title='当前任务已变化'), state['projects'][0].update(goal='当前目标')))
        request = self.request(source, selection={'materials': ['M1'], 'tasks': ['t1'], 'decisions': [], 'results': []})
        created = self.historical(source, history_source=request)
        self.assertEqual(created['context']['project']['goal'], '当前目标')
        self.assertEqual(created['context']['tasks'], [])
        self.assertEqual(created['materials'][0]['content'], source['materials'][0]['content'])
        self.assertEqual(created['materials'][0]['version'], source['materials'][0]['version'])
        self.assertEqual(json.loads(created['materials'][1]['content'])['title'], '选定任务')
        self.assertEqual(created['history_source']['source_used_calls'], 1)
        self.assertEqual(self.get(source, 'room'), source)
        self.assertEqual(created['used_calls'], 0)
        self.change(lambda state: state['tasks'][0].update(title='再次变化'))
        self.assertFalse(next(r for r in self.eco.view('p1')['rooms'] if r['id'] == created['id'])['context_stale'])

    def test_history_wire_reason_and_current_goal_guard(self):
        source = self.completed(); agent = self.external('new-history-executor'); profile = self.profile(agent=agent['id'])
        created = self.historical(source, profile_ids=[profile['id']])
        started = self.start(created)
        request = self.eco.agent_get(agent)['requests'][0]
        self.assertEqual(request['history_source'], created['history_source'])
        prompt = review_service.prompt(created, created['participants'][0])
        self.assertIn('历史结果未核验', prompt); self.assertIn('不代表当前记录', prompt)
        self.change(lambda state: state['projects'][0].update(goal='执行中变化'))
        with self.assertRaisesRegex(ValueError, '项目记录已变化'):
            self.eco.agent_reply(agent, dict(request, output=output()))
        with self.assertRaisesRegex(RuntimeError, '记录变化'):
            with self.eco.send_guard('p1', started, started['participants'][0]): pass
        self.assertEqual(self.get(created, 'room')['used_calls'], 0)

    def test_current_selected_record_is_still_dependency(self):
        self.selected_records(); _, source = self.review(context_selection={'tasks': [], 'decisions': [], 'results': []})
        agent = self.external('live-dependency'); profile = self.profile(agent=agent['id'])
        created = self.historical(source, profile_ids=[profile['id']], context_selection={'tasks': ['t1'], 'decisions': [], 'results': []})
        self.change(lambda state: state['tasks'][0].update(title='变化'))
        with self.assertRaisesRegex(ValueError, '上下文已变化'): self.start(created)

    def test_negative_result_keeps_original_source_version_and_does_not_become_current_record(self):
        with self.connect() as c:
            c.execute('INSERT INTO action_results(id,action_id,project_id,outcome,summary,source_ref,actor,created_at,source_version,verification_status) VALUES(?,?,?,?,?,?,?,?,?,?)',
                      ('r0','fixture','p1','failure','原负结果','synthetic://result','fixture','now','original-sha','UNVERIFIED'))
        _, source = self.review(context_selection={'tasks': [], 'decisions': [], 'results': ['r0']})
        with self.connect() as c: c.execute("UPDATE action_results SET source_version='later-sha',summary='新登记' WHERE id='r0'")
        created = self.historical(source, history_source=self.request(source, selection={'materials': [], 'tasks': [], 'decisions': [], 'results': ['r0']}))
        row = json.loads(created['materials'][0]['content'])
        self.assertEqual(row['outcome'], 'failure'); self.assertEqual(row['source_version'], 'original-sha'); self.assertEqual(row['summary'], '原负结果')
        self.assertEqual(created['context']['results'], []); self.assertEqual(row['verification_status'], 'UNVERIFIED')

    def test_history_total_limit_and_large_record_reject_without_truncation(self):
        source = self.completed()
        with self.assertRaises(ValueError): review_history.selection({'materials': [str(i) for i in range(13)], 'tasks': [], 'decisions': [], 'results': []})
        self.change(lambda state: state['tasks'].append({'id': 'big', 'project': 'p1', 'title': '大快照', 'note': 'X'*17000}))
        _, source = self.review(context_selection={'tasks': ['big'], 'decisions': [], 'results': []})
        with self.assertRaisesRegex(ValueError, '16000'):
            self.historical(source, history_source=self.request(source, selection={'materials': [], 'tasks': ['big'], 'decisions': [], 'results': []}))

    def test_bad_history_selection_reason_versions_scope_and_active_reject_without_draft(self):
        source = self.completed(); before = len(self.eco.view('p1')['rooms'])
        bad = [self.request(source, reason=' '), self.request(source, expected_rev=True), self.request(source, expected_rev=0),
               self.request(source, context_hash='0'*64), self.request(source, selection={k: [] for k in review_history.KEYS}),
               self.request(source, selection={'materials': ['M1', 'M1'], 'tasks': [], 'decisions': [], 'results': []}),
               self.request(source, selection={'materials': [], 'tasks': ['not-in-source'], 'decisions': [], 'results': []})]
        for request in bad:
            with self.assertRaises(ValueError): self.historical(source, history_source=request)
        with self.assertRaises(ValueError): self.historical(source, materials=[])
        with self.assertRaises(Exception): self.post('review.create', project='p2', title='越项目', question='Q', constraints='', profile_ids=[], max_rounds=1, max_calls=1, history_source=self.request(source))
        self.assertEqual(len(self.eco.view('p1')['rooms']), before)
        agent, running = self.review(); running = self.start(running)
        with self.assertRaisesRegex(ValueError, '仍在运行'): self.historical(running)

    def test_dry_does_not_copy_and_source_change_between_dry_apply_rejects(self):
        _, source = self.review(); body = dict(operation='review.create', project_id='p1', ifRev=self.eco.view('p1')['rev'], title='H', question='Q',
            constraints='', profile_ids=[], max_rounds=1, max_calls=1, history_source=self.request(source))
        before = self.eco.view('p1'); self.eco.post(dict(body, dry=True)); self.assertEqual(self.eco.view('p1'), before)
        self.post('room.message', id=source['id'], content='原对象有新增记录')
        body['ifRev'] = self.eco.view('p1')['rev']
        with self.assertRaisesRegex(ValueError, '历史来源对象或版本'): self.eco.post(body)

    def test_portable_snapshot_without_original_and_tamper_rejection(self):
        source = self.completed(); created = self.historical(source)
        with self.connect() as c:
            snapshot = project_backup.envelope(c)
            snapshot['gateway']['ecosystem_items'] = [r for r in snapshot['gateway']['ecosystem_items'] if r['id'] != source['id']]
            project_backup.validate(snapshot['state'], snapshot['gateway'], c, portable=True)
            for field, value in [('reason', ''), ('project_id', 'p2'), ('source_used_calls', -1), ('context_hash', 'bad')]:
                bad = copy.deepcopy(snapshot['gateway']); row = next(r for r in bad['ecosystem_items'] if r['id'] == created['id']); room = json.loads(row['body'])
                room['history_source'][field] = value; row['body'] = json.dumps(room)
                with self.assertRaises(ValueError): project_backup.validate(snapshot['state'], bad, c, portable=True)
            bad = copy.deepcopy(snapshot['gateway']); row = next(r for r in bad['ecosystem_items'] if r['id'] == created['id']); room = json.loads(row['body'])
            room['history_source']['bindings'][0]['version'] = '0'*64; row['body'] = json.dumps(room)
            with self.assertRaises(ValueError): project_backup.validate(snapshot['state'], bad, c, portable=True)
            project_backup.restore(c, snapshot['state'], snapshot['gateway'], portable=True)
        self.assertEqual(self.get(created, 'room')['materials'], created['materials'])

    def test_old_contract_hash_unchanged_and_consumed_history_reason_cannot_change(self):
        source = self.completed()
        keys = ('id', 'project_id', 'question', 'context', 'participants', 'max_rounds', 'max_calls', 'mode', 'materials', 'constraints', 'source_change', 'review_of')
        self.assertEqual(ecosystem.room_contract(source), ecosystem.digest({k: source.get(k) for k in keys}))
        agent = self.external('history-reply'); profile = self.profile(agent=agent['id'])
        created = self.historical(source, profile_ids=[profile['id']]); self.start(created)
        self.eco.agent_reply(agent, dict(self.eco.agent_get(agent)['requests'][0], output=output()))
        created = self.get(created, 'room'); md = review_service.markdown(created)
        self.assertIn('历史快照使用理由', md); self.assertIn('原已耗 / 配额：1 / 1', md)
        with self.connect() as c:
            bad = copy.deepcopy(created); bad['history_source']['reason'] = '改变原执行理由'
            with self.assertRaisesRegex(ValueError, '原执行契约'): ecosystem.usage_floor(c, bad)
        self.assertEqual(self.get(source, 'room')['used_calls'], 1)

    def adoption(self, room, **updates):
        body = dict(operation='room.adopt', project_id='p1', id=room['id'], expected_rev=room['object_rev'], ifRev=self.eco.view('p1')['rev'],
                    brief_revision=1, target='task', title='跨项目任务', rationale='保留未核验来源', target_project_id='p2')
        body.update(updates); return body

    def test_target_object_allows_unrelated_records_with_stale_global_revision(self):
        room = self.completed(); target = self.eco.view('p2'); body = self.adoption(room, target_project_version=target['project_version'])
        self.change(lambda state: state['tasks'].append({'id': 'unrelated', 'project': 'p2', 'title': '无关任务'}))
        self.assertNotEqual(self.eco.view('p2')['context']['context_hash'], target['context']['context_hash'])
        result = self.eco.post(body)['item']
        self.assertEqual(result['adoptions'][0]['target_gate'], {'kind': 'project_object', 'version': target['project_version']})
        self.assertEqual(self.eco.view('p2')['context']['tasks'][-1]['title'], '跨项目任务')

    def test_target_goal_invalid_version_ambiguous_gate_and_legacy_changes_reject(self):
        room = self.completed(); target = self.eco.view('p2')
        for body in [self.adoption(room, target_project_version='bad'), self.adoption(room, target_project_version=target['project_version'], target_context_hash=target['context']['context_hash'])]:
            with self.assertRaises(ValueError): self.eco.post(body)
        legacy = self.adoption(room, target_context_hash=target['context']['context_hash'])
        self.change(lambda state: state['tasks'].append({'id': 'unrelated', 'project': 'p2', 'title': '无关任务'}))
        with self.assertRaisesRegex(ValueError, '回写项目记录'): self.eco.post(legacy)
        body = self.adoption(room, target_project_version=target['project_version'])
        self.change(lambda state: state['projects'][1].update(goal='目标已改变'))
        with self.assertRaisesRegex(ValueError, '回写项目对象'): self.eco.post(body)
        self.assertEqual(self.get(room, 'room')['adoptions'], [])


if __name__ == '__main__': unittest.main()
