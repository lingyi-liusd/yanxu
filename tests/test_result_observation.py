"""Result-driven watch proposals, synthetic persisted fixtures; no model/network/scientific runs."""
import copy
import json
import unittest

import ecosystem
import project_backup
import result_observation
import test_review_observation as review_support


class ResultObservationCase(unittest.TestCase):
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

    def fixture(self):
        with self.connect() as c:
            state = self.gateway.state(c); state['decisions'].append({'id': 'd1', 'project': 'p1', 'title': '原判断', 'answer': '保持范围', 'status': '已决'})
            c.execute('UPDATE state SET body=? WHERE id=1', (json.dumps(state),))
        agent, room = self.review(review_of='d1', context_selection={'tasks': [], 'decisions': [], 'results': []})
        self.start(room); self.eco.agent_reply(agent, dict(self.eco.agent_get(agent)['requests'][0], output=review_support.output()))
        room = self.get(room, 'room')
        adopted = self.post('room.adopt', id=room['id'], expected_rev=room['object_rev'], brief_revision=1, target='task', title='核查原条件', rationale='合成流程，保留未知')
        task_id = adopted['adopted_id']; execution = self.external('fixture-execution', permission='EXECUTE')
        # Persisted ledger fixture only; true strict HTTP/MCP execution covered separately.
        with self.connect() as c:
            c.execute('INSERT INTO actions(id,project_id,task_id,goal,why_now,expected_output,success_condition,failure_condition,dependencies,agent_id,status,budget,stop_condition,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                      ('a1','p1',task_id,'核查原条件','合成回归','版本记录','证据完整','证据缺失','[]',execution['id'],'finished','{"max_progress_reports":1}','结果后停止','now','now'))
            c.execute('INSERT INTO action_results(id,action_id,project_id,outcome,summary,source_ref,actor,created_at,source_version,verification_status) VALUES(?,?,?,?,?,?,?,?,?,?)',
                      ('r1','a1','p1','failure','缺少外部证据；收益未知','synthetic://result',execution['id'],'now','source-v1','UNVERIFIED'))
        watch = self.post('watch.save', name='原关联来源', url='https://example.org/feed', question='原条件是否变化？', decision_ids=['d1'], keywords=['成本'], interval_minutes=60, enabled=False, auto_push=False)
        return watch, adopted, task_id

    def candidate(self):
        return self.eco.view('p1')['result_observation']['candidates'][0]

    def body(self, candidate, choice='keep', **updates):
        values = dict(operation='watch.result.resolve', project_id='p1', id=candidate['watch_id'], expected_rev=candidate['target']['object_rev'],
                      proposal_id=candidate['id'], basis_hash=candidate['basis_hash'], resolution=choice,
                      rule=candidate['target']['rule'] if choice == 'keep' else candidate['proposed'], reason='人工合成处理，尚未科学核验', consent='result-observation-adjustment-v1')
        values.update(updates); return values

    def test_read_is_pure_exact_link_and_negative_result_kept(self):
        watch, room, _ = self.fixture(); before = self.get(watch, 'watch'); rev = self.eco.view('p1')['rev']
        candidate = self.candidate(); self.assertEqual(self.eco.view('p1')['rev'], rev); self.assertEqual(self.get(watch, 'watch'), before)
        self.assertEqual(candidate['source']['result']['outcome'], 'failure'); self.assertEqual(candidate['source']['result']['source_version'], 'source-v1')
        self.assertEqual(candidate['source']['result']['verification_status'], 'UNVERIFIED')
        self.assertEqual(candidate['source']['relation']['decision_ids'], ['d1'])
        self.assertIn('缺少外部证据；收益未知', candidate['proposed']['question']); self.assertEqual(candidate['proposed']['keywords'], ['成本'])
        self.assertEqual(candidate['proposed']['interval_minutes'], 60); self.assertFalse(candidate['target']['enabled'])
        self.assertEqual(self.executor.calls, []); self.assertEqual(self.get(room, 'room')['used_calls'], 1)
        self.post('watch.save', name='无关来源', url='https://example.org/other', question='另一个问题', decision_ids=[], keywords=[], interval_minutes=60, enabled=False)
        self.assertEqual(len(self.eco.view('p1')['result_observation']['candidates']), 1)

    def test_keep_history_suppression_restart_and_portable_restore(self):
        watch, room, _ = self.fixture(); candidate = self.candidate(); before = self.get(watch, 'watch')
        body = self.body(candidate); snapshot = self.eco.view('p1'); self.eco.post(dict(body, dry=True)); self.assertEqual(self.eco.view('p1'), snapshot)
        saved = self.eco.post(body)['item']; self.assertEqual(saved['question'], before['question']); self.assertEqual(saved['config_version'], before['config_version'])
        self.assertEqual(saved['result_adjustments'][0]['resolution'], 'keep'); self.assertEqual(saved['result_adjustments'][0]['source']['result']['outcome'], 'failure')
        self.assertEqual(self.eco.view('p1')['result_observation']['total'], 0)
        with self.assertRaises(ValueError): self.eco.post(dict(body, expected_rev=saved['object_rev']))
        with self.connect() as c:
            snapshot = project_backup.envelope(c); project_backup.validate(snapshot['state'], snapshot['gateway'], c, portable=True)
            project_backup.restore(c, snapshot['state'], snapshot['gateway'], portable=True)
        self.assertEqual(self.get(watch, 'watch')['result_adjustments'], saved['result_adjustments'])
        self.assertEqual(self.eco.view('p1')['result_observation']['total'], 0); self.assertEqual(self.get(room, 'room')['used_calls'], 1)

    def test_modify_only_selected_rule_preserves_authority_and_source(self):
        watch, _, _ = self.fixture(); candidate = self.candidate(); before = self.get(watch, 'watch')
        after = dict(candidate['proposed'], keywords=['证据', '成本'], interval_minutes=120)
        saved = self.eco.post(self.body(candidate, 'modify', rule=after, enabled=True, auto_push=True, url='https://example.org/new'))['item']
        for key in ('enabled', 'auto_push', 'push_target', 'url', 'name', 'decision_ids'): self.assertEqual(saved[key], before[key])
        self.assertEqual(saved['config_version'], before['config_version'] + 1); self.assertEqual(saved['keywords'], after['keywords']); self.assertEqual(saved['interval_minutes'], 120)
        receipt = saved['result_adjustments'][0]; self.assertEqual(receipt['before'], candidate['target']['rule']); self.assertEqual(receipt['after'], after)
        self.assertEqual(receipt['scientific_result'], 'NOT_ASSESSED'); self.assertEqual(self.eco.view('p1')['result_observation']['total'], 0)

    def test_source_versions_goal_decision_and_target_races_reject_without_effect(self):
        watch, _, task_id = self.fixture()
        for change in ('result', 'action', 'goal', 'decision', 'task', 'watch'):
            candidate = self.candidate(); body = self.body(candidate)
            with self.connect() as c:
                if change == 'result': c.execute("UPDATE action_results SET source_version='source-v2' WHERE id='r1'")
                elif change == 'action': c.execute("UPDATE actions SET version=version+1 WHERE id='a1'")
                elif change == 'watch':
                    value = self.eco.item(c, 'p1', watch['id'], 'watch'); value['keywords'] = ['更新']; self.eco.save(c, value, 'watch'); body['expected_rev'] = value['object_rev']
                else:
                    state = self.gateway.state(c)
                    if change == 'goal': state['projects'][0]['goal'] = '当前新目标'
                    elif change == 'decision': state['decisions'][0]['answer'] = '新判断版本'
                    else: next(t for t in state['tasks'] if t['id'] == task_id)['note'] = '采纳条件已更新'
                    c.execute('UPDATE state SET body=? WHERE id=1', (json.dumps(state),))
                self.bump(c)
            with self.assertRaisesRegex(ValueError, '来源或目标版本'): self.eco.post(body)
            self.assertNotIn('result_adjustments', self.get(watch, 'watch'))

    def test_unrelated_record_drift_does_not_invalidate_selected_source(self):
        watch, _, _ = self.fixture(); body = self.body(self.candidate()); body['ifRev'] = self.eco.view('p1')['rev']
        with self.connect() as c:
            state = self.gateway.state(c); state['tasks'].append({'id': 'unrelated', 'project': 'p1', 'title': '无关任务'})
            c.execute('UPDATE state SET body=? WHERE id=1', (json.dumps(state),)); self.bump(c)
        self.eco.post(body); self.assertEqual(self.eco.view('p1')['result_observation']['total'], 0)

    def test_bad_consent_rule_reason_scope_and_keep_modify_mismatch_reject(self):
        watch, _, _ = self.fixture(); candidate = self.candidate()
        for updates in ({'consent': ''}, {'reason': ' '}, {'resolution': 'automatic'}, {'resolution': 'modify'}, {'rule': candidate['proposed']},
                        {'rule': dict(candidate['target']['rule'], enabled=True)}, {'rule': dict(candidate['target']['rule'], keywords=['X']*13)},
                        {'rule': dict(candidate['target']['rule'], interval_minutes=1)}, {'project_id': 'p2'}):
            with self.assertRaises(Exception): self.eco.post(self.body(candidate, **updates))
        self.assertNotIn('result_adjustments', self.get(watch, 'watch'))

    def test_missing_origin_or_binding_and_cross_project_rows_do_not_match(self):
        watch, room, _ = self.fixture()
        with self.connect() as c:
            pack = self.eco.context(c, 'p1'); rooms = self.eco.items(c, 'p1', 'room'); actions = ecosystem.ledger.all_rows(c, 'SELECT * FROM actions'); results = ecosystem.ledger.all_rows(c, 'SELECT * FROM action_results')
        builder = lambda rs, ws, ac=actions, res=results: result_observation.proposals(pack['project'], pack['tasks'], pack['decisions'], rs, ac, res, ws)
        self.assertEqual(builder([], [watch]), [])
        unrelated = copy.deepcopy(watch); unrelated['decision_ids'] = []; self.assertEqual(builder(rooms, [unrelated]), [])
        other = copy.deepcopy(results); other[0]['project_id'] = 'p2'; self.assertEqual(builder(rooms, [watch], res=other), [])
        # Explicit originating source also works without a decision binding.
        direct = copy.deepcopy(rooms); direct[0].pop('review_of', None); direct[0]['source_change'] = {'project_id': 'p1', 'watch_id': watch['id']}
        self.assertEqual(builder(direct, [unrelated])[0]['source']['relation']['source_watch_id'], watch['id'])

    def test_receipt_tamper_duplicate_and_malformed_snapshots_reject(self):
        watch, _, _ = self.fixture(); saved = self.eco.post(self.body(self.candidate()))['item']
        for change in ('hash', 'scope', 'bad-task', 'duplicate', 'after'):
            bad = copy.deepcopy(saved); receipt = bad['result_adjustments'][0]
            if change == 'hash': receipt['source']['result']['outcome'] = 'success'
            elif change == 'scope': receipt['source']['result']['project_id'] = 'p2'; receipt['source_hash'] = result_observation.digest(receipt['source'])
            elif change == 'bad-task': receipt['source']['task'] = None
            elif change == 'duplicate': bad['result_adjustments'].append(copy.deepcopy(receipt))
            else: receipt['after']['question'] = '维持时偷偷改规则'
            with self.assertRaises(ValueError): result_observation.validate_receipts(bad)

    def test_oversize_question_is_visible_not_truncated_and_outcomes_not_promoted(self):
        self.fixture()
        with self.connect() as c: c.execute("UPDATE action_results SET summary=? WHERE id='r1'", ('X'*1100,))
        candidate = self.candidate(); self.assertEqual(candidate['proposed'], candidate['target']['rule']); self.assertIn('未自动截断', candidate['notice'])
        self.assertEqual(len(candidate['source']['result']['summary']), 1100)
        for outcome in ('success', 'partial', 'inconclusive', 'unknown', 'FAIL'):
            with self.connect() as c: c.execute("UPDATE action_results SET outcome=? WHERE id='r1'", (outcome,))
            self.assertEqual(self.candidate()['source']['result']['outcome'], outcome)

    def test_candidate_display_limit_is_explicit_without_dropping_processing_paths(self):
        self.fixture()
        for i in range(50):
            self.post('watch.save', name='关联来源 '+str(i), url='https://example.org/feed-'+str(i), question='原问题', decision_ids=['d1'], keywords=[], interval_minutes=60, enabled=False)
        group = self.eco.view('p1')['result_observation']; self.assertEqual(group['total'], 51); self.assertEqual(group['shown'], 50); self.assertEqual(len(group['candidates']), 50)
        self.eco.post(self.body(group['candidates'][0])); self.assertEqual(self.eco.view('p1')['result_observation']['total'], 50)

    def test_history_cap_keeps_existing_receipts_and_refuses_further_append(self):
        watch, _, _ = self.fixture(); candidate = self.candidate(); value = self.get(watch, 'watch'); receipts = []
        for i in range(50):
            previous = copy.deepcopy(candidate); previous['source']['result']['source_version'] = 'older-'+str(i)
            previous['source_hash'] = result_observation.digest(previous['source']); previous['basis_hash'] = result_observation.digest({'source_hash': previous['source_hash'], 'target': previous['target']})
            receipts.append(result_observation.resolution(previous, 'keep', previous['target']['rule'], '历史合成处理', 'now'))
        value['result_adjustments'] = receipts; result_observation.validate_receipts(value)
        with self.connect() as c: self.eco.save(c, value, 'watch')
        current = self.candidate(); self.assertFalse(current['can_resolve'])
        with self.assertRaisesRegex(ValueError, '50 条'): self.eco.post(self.body(current))
        self.assertEqual(self.get(watch, 'watch')['result_adjustments'], receipts)


if __name__ == '__main__': unittest.main()
