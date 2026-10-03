"""G3 regression contract: lossless approval, strict claims, and inherited budgets.

Run from the canonical repository:
    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests \
        -p 'test_contract_integrity.py' -v

The HTTP/MCP cases reuse test_agent_gateway's temporary-data/random-port
fixture, never the production service. Model executables and CODEX_HOME are
redirected to disposable locations. Management calls are synthetic SQL fixtures
with the daily allowance already spent; runtime execution is never enabled.
Missing implementation is a failure, not an expected failure or a skip. Only
MCP cases may skip when Node is unavailable. This file does not test scientific
results, G4 ownership reconciliation, or actual model execution.
"""

import copy
import hashlib
import importlib
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import test_agent_gateway as support


TEXT_FIELDS = ('goal', 'reason', 'expected_output', 'success_condition',
               'failure_condition', 'stop_condition')
CONDITION_FIELDS = TEXT_FIELDS[1:]


def contract_fixture(management=False):
    value = {
        'scope': 'read_only_review' if management else 'project_action',
        'goal': '核对合成契约的原文与版本',
        'reason': '来源已登记，需要一次有界核对',
        'expected_output': '一份保留未知与负结果的合成核对报告',
        'success_condition': '所有原文、版本、预算与尾部停止条件一致',
        'failure_condition': '任一字段缺失或改写即失败，不推测成功',
        'stop_condition': '报告一次后停止；资料不足则记录 UNKNOWN 并停止',
        'budget': {'max_progress_reports': 2},
    }
    if not management:
        value.update(dependencies=['t1'], dependency_policy='recorded')
    return value


def boundary_text(length, field):
    # Includes whitespace, CRLF, combining characters, emoji, and a meaningful
    # tail. Character limits are not UTF-8 byte limits or strip/normalize limits.
    prefix = ' \t原文 ' + field + ' e\u0301🧪\r\n'
    tail = '\n尾部停止条件：来源改变或预算耗尽立即停止。 \t'
    return prefix + '测' * (length - len(prefix) - len(tail)) + tail


def json_value(value):
    return json.loads(value) if isinstance(value, str) else value


class ContractValidationTests(unittest.TestCase):
    def contracts(self):
        try:
            return importlib.import_module('action_contracts')
        except ModuleNotFoundError as exc:
            if exc.name != 'action_contracts':
                raise
            self.fail('Missing required action_contracts.validate/digest implementation')

    def test_all_condition_boundaries_are_lossless(self):
        module = self.contracts()
        for management in (False, True):
            for field in CONDITION_FIELDS:
                for length in (1999, 2000, 2001, 4000):
                    with self.subTest(management=management, field=field, length=length):
                        value = contract_fixture(management)
                        value[field] = boundary_text(length, field)
                        before = copy.deepcopy(value)
                        validated = module.validate(value, management=management)
                        self.assertEqual(value, before, 'Validation mutated the input')
                        self.assertEqual(validated, before, 'Validation changed approved characters')

    def test_goal_400_is_lossless_and_401_is_rejected(self):
        module = self.contracts()
        for management in (False, True):
            with self.subTest(management=management):
                value = contract_fixture(management)
                value['goal'] = boundary_text(400, 'goal')
                self.assertEqual(module.validate(value, management=management), value)
                value['goal'] += '末'
                with self.assertRaises(ValueError):
                    module.validate(value, management=management)

    def test_4001_conditions_are_rejected_without_mutation(self):
        module = self.contracts()
        for management in (False, True):
            for field in CONDITION_FIELDS:
                with self.subTest(management=management, field=field):
                    value = contract_fixture(management)
                    value[field] = boundary_text(4001, field)
                    before = copy.deepcopy(value)
                    with self.assertRaises(ValueError):
                        module.validate(value, management=management)
                    self.assertEqual(value, before)

    def test_missing_blank_and_nontext_conditions_are_rejected(self):
        module = self.contracts()
        for management in (False, True):
            for field in TEXT_FIELDS:
                for invalid in (None, '', ' \t\r\n\u3000', 7, [], {}):
                    with self.subTest(management=management, field=field, invalid=invalid):
                        value = contract_fixture(management)
                        value[field] = invalid
                        with self.assertRaises(ValueError):
                            module.validate(value, management=management)
                with self.subTest(management=management, field=field, missing=True):
                    value = contract_fixture(management)
                    del value[field]
                    with self.assertRaises(ValueError):
                        module.validate(value, management=management)

    def test_budget_must_be_explicit_positive_integer(self):
        module = self.contracts()
        for management in (False, True):
            for invalid in (None, {}, {'max_progress_reports': 0},
                            {'max_progress_reports': True}, {'max_progress_reports': '2'}):
                with self.subTest(management=management, budget=invalid):
                    value = contract_fixture(management)
                    value['budget'] = invalid
                    with self.assertRaises(ValueError):
                        module.validate(value, management=management)
            value = contract_fixture(management)
            del value['budget']
            with self.assertRaises(ValueError):
                module.validate(value, management=management)

    def test_management_dependencies_and_policy_are_independent_fields(self):
        module = self.contracts()
        for policy in ('recorded', 'all_completed'):
            with self.subTest(policy=policy):
                value = contract_fixture(True)
                value.update(dependencies=['t1'], dependency_policy=policy)
                self.assertEqual(module.validate(value, management=True), value)

    def test_dependency_types_and_unknown_policy_are_rejected(self):
        module = self.contracts()
        for deps in ('t1', [None], [1]):
            with self.subTest(dependencies=deps):
                value = contract_fixture()
                value['dependencies'] = deps
                with self.assertRaises(ValueError):
                    module.validate(value)
        value = contract_fixture()
        value['dependency_policy'] = 'guess_completed'
        with self.assertRaises(ValueError):
            module.validate(value)

    def test_management_scope_cannot_be_changed_to_execution(self):
        module = self.contracts()
        for scope in ('project_action', 'experiment', ''):
            with self.subTest(scope=scope):
                value = contract_fixture(True)
                value['scope'] = scope
                with self.assertRaises(ValueError):
                    module.validate(value, management=True)

    def test_digest_is_deterministic_and_covers_every_contract_field(self):
        module = self.contracts()
        value = contract_fixture()
        value['stop_condition'] = boundary_text(4000, 'stop_condition')
        before = copy.deepcopy(value)
        original = module.digest(value)
        self.assertIsInstance(original, str)
        self.assertTrue(original)
        self.assertEqual(original, module.digest(copy.deepcopy(value)))
        self.assertEqual(original, module.digest(dict(reversed(list(value.items())))))
        self.assertEqual(value, before)
        changes = {field: value[field] + '异' for field in TEXT_FIELDS}
        changes.update(scope='read_only_review', dependencies=['t1', 't2'],
                       dependency_policy='all_completed', budget={'max_progress_reports': 3})
        # Replacing only the final character detects hashes over a truncated prefix.
        changes['stop_condition'] = value['stop_condition'][:-1] + '异'
        for field, changed in changes.items():
            with self.subTest(field=field):
                self.assertNotEqual(original, module.digest(dict(value, **{field: changed})))


class ContractHTTPTests(unittest.TestCase):
    request = support.AgentGatewayCase.request
    agent = support.AgentGatewayCase.agent
    seed_management_handoff = support.AgentGatewayCase.seed_management_handoff
    maxDiff = 800

    def setUp(self):
        guard = tempfile.TemporaryDirectory(prefix='yanxu-contract-no-model-')
        self.addCleanup(guard.cleanup)
        guard_path = pathlib.Path(guard.name)
        # Even an unintended inference attempt cannot resolve a real model CLI.
        patcher = patch.dict(os.environ, {
            'PYTHONDONTWRITEBYTECODE': '1',
            'CODEX_HOME': str(guard_path / 'synthetic-codex-home'),
            'RESEARCH_DESK_CODEX_BIN': str(guard_path / 'codex'),
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.stop_fixture)
        support.AgentGatewayCase.setUp(self)

    def stop_fixture(self):
        process = getattr(self, 'proc', None)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        if getattr(self, 'tmp', None):
            self.tmp.cleanup()

    def context(self, token=None):
        code, _, value = self.request('/api/agent/context', token=token or self.agent_token)
        self.assertEqual(code, 200, value)
        return value

    def strict_agent(self):
        code, _, connection = self.request('/api/agents/connect', {
            'project_id': 'p1', 'name': 'Synthetic strict agent',
            'permission': 'EXECUTE', 'contract_mode': 'strict_v2',
        })
        self.assertEqual(code, 200, connection)
        return connection['token']

    def claim_body(self, context=None, **changes):
        value = contract_fixture()
        if context is not None:
            value['context_hash'] = context['management']['resume_brief']['source_hash']
        value.update(changes)
        return dict(value, phase='claim')

    def main_snapshot(self):
        # Table-level fingerprints include history/revision, ownership, events,
        # and any newly added contract tables, while avoiding huge failure diffs.
        result = {}
        with sqlite3.connect(self.dir / 'desk.sqlite3') as connection:
            names = [row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            for name in names:
                quoted = '"' + name.replace('"', '""') + '"'
                rows = connection.execute('SELECT * FROM ' + quoted).fetchall()
                raw = json.dumps(sorted(rows, key=repr), ensure_ascii=False, default=repr)
                result[name] = hashlib.sha256(raw.encode()).hexdigest()
        return result

    def handoff_snapshot(self):
        with sqlite3.connect(self.dir / 'manager.sqlite3') as connection:
            return connection.execute('SELECT * FROM handoffs ORDER BY id').fetchall()

    def used_budget(self):
        with sqlite3.connect(self.dir / 'manager.sqlite3') as connection:
            return connection.execute(
                "SELECT project,day,count(*) FROM jobs WHERE day IS NOT NULL GROUP BY project,day ORDER BY project,day"
            ).fetchall()

    def rejected_claim(self, body, token, expected=None):
        before = self.main_snapshot()
        budget = self.used_budget()
        code, _, reply = self.request('/api/agent/activity', body, token=token)
        self.assertEqual(self.main_snapshot(), before, 'Rejected claim wrote records/history/revision')
        self.assertEqual(self.used_budget(), budget, 'Rejected claim changed consumed model budget')
        self.assertIn(code, (400, 403, 409), reply)
        if expected is not None:
            self.assertEqual(code, expected, reply)
        self.assertNotIn('action_id', reply)

    def assert_action_contract(self, claim, approved):
        context = self.context()
        action = next(row for row in context['actions'] if row['id'] == claim['action_id'])
        for field in TEXT_FIELDS:
            target = 'why_now' if field == 'reason' else field
            self.assertEqual(action[target], approved[field], target + ' changed approved characters')
        self.assertEqual(json_value(action['budget']), approved['budget'])
        self.assertEqual(json_value(action['dependencies']), approved.get('dependencies', []))
        self.assertEqual(action['approved_contract'], approved)
        self.assertEqual(action['approved_contract']['scope'], approved['scope'])
        self.assertEqual(action['approved_contract'].get('dependency_policy', 'recorded'),
                         approved.get('dependency_policy', 'recorded'))
        expected_hash = importlib.import_module('action_contracts').digest(approved)
        self.assertEqual(claim['contract_hash'], expected_hash)
        self.assertEqual(action['contract_hash'], expected_hash)
        self.assertIsInstance(action['authority_note'], str)
        self.assertTrue(action['authority_note'].strip())
        self.assertEqual(action['why_now'], approved['reason'], 'Authority note was appended to why_now')
        with sqlite3.connect(self.dir / 'desk.sqlite3') as connection:
            raw = connection.execute('SELECT why_now,stop_condition,budget,dependencies FROM actions WHERE id=?',
                                     (claim['action_id'],)).fetchone()
        self.assertEqual(raw[0], approved['reason'])
        self.assertEqual(raw[1], approved['stop_condition'])
        self.assertEqual(json_value(raw[2]), approved['budget'])
        self.assertEqual(json_value(raw[3]), approved.get('dependencies', []))
        return action

    def approve(self, contract):
        body = self.seed_management_handoff()
        body['contract'] = copy.deepcopy(contract)
        before, handoffs, budget = self.main_snapshot(), self.handoff_snapshot(), self.used_budget()
        code, _, preview = self.request('/api/project/manager/handoff', dict(body, dry=True))
        self.assertEqual(code, 200, preview)
        self.assertEqual(self.main_snapshot(), before, 'Dry approval wrote project records')
        self.assertEqual(self.handoff_snapshot(), handoffs, 'Dry approval froze a handoff')
        self.assertEqual(self.used_budget(), budget)
        code, _, approved = self.request('/api/project/manager/handoff', body)
        self.assertEqual(code, 200, approved)
        self.assertEqual(approved['contract'], contract)
        self.assertEqual(approved['contract_hash'], importlib.import_module('action_contracts').digest(contract))
        with sqlite3.connect(self.dir / 'manager.sqlite3') as connection:
            stored = connection.execute('SELECT contract FROM handoffs WHERE id=?',
                                        (body['handoff_id'],)).fetchone()[0]
        self.assertEqual(json.loads(stored), contract)
        return body

    def management_roundtrip(self, length):
        contract = contract_fixture(True)
        contract['goal'] = boundary_text(400, 'goal')
        for field in CONDITION_FIELDS:
            contract[field] = boundary_text(length, field)
        body = self.approve(contract)
        self.context()
        budget = self.used_budget()
        code, _, claim = self.agent('management/claim', {'handoff_id': body['handoff_id']})
        self.assertEqual(code, 200, claim)
        self.assertEqual(self.used_budget(), budget)
        self.assertEqual(claim['approved_contract'], contract)
        self.assert_action_contract(claim, contract)

    def test_management_roundtrip_1999(self):
        self.management_roundtrip(1999)

    def test_management_roundtrip_2000(self):
        self.management_roundtrip(2000)

    def test_management_roundtrip_2001(self):
        self.management_roundtrip(2001)

    def test_management_roundtrip_4000_and_tail_stop(self):
        self.management_roundtrip(4000)

    def test_management_scope_dependencies_policy_budget_remain_separate(self):
        contract = contract_fixture(True)
        contract.update(dependencies=['t1'], dependency_policy='recorded')
        body = self.approve(contract)
        self.context()
        code, _, claim = self.agent('management/claim', {'handoff_id': body['handoff_id']})
        self.assertEqual(code, 200, claim)
        self.assert_action_contract(claim, contract)

    def test_approval_rejects_4001_and_401_goal_atomically(self):
        body = self.seed_management_handoff()
        for field in TEXT_FIELDS:
            with self.subTest(field=field):
                contract = copy.deepcopy(body['contract'])
                contract[field] = boundary_text(401 if field == 'goal' else 4001, field)
                before, handoffs, budget = self.main_snapshot(), self.handoff_snapshot(), self.used_budget()
                code, _, reply = self.request('/api/project/manager/handoff', dict(body, contract=contract))
                self.assertEqual(self.main_snapshot(), before)
                self.assertEqual(self.handoff_snapshot(), handoffs)
                self.assertEqual(self.used_budget(), budget)
                self.assertEqual(code, 400, reply)

    def test_approval_rejects_empty_criteria_atomically(self):
        body = self.seed_management_handoff()
        for field in ('success_condition', 'failure_condition', 'stop_condition'):
            for blank in ('', ' \t\n\u3000'):
                with self.subTest(field=field, blank=repr(blank)):
                    before, handoffs = self.main_snapshot(), self.handoff_snapshot()
                    contract = dict(body['contract'], **{field: blank})
                    code, _, reply = self.request('/api/project/manager/handoff', dict(body, contract=contract))
                    self.assertEqual(self.main_snapshot(), before)
                    self.assertEqual(self.handoff_snapshot(), handoffs)
                    self.assertEqual(code, 400, reply)

    def test_approved_contract_cannot_be_silently_reapproved_with_new_tail(self):
        contract = contract_fixture(True)
        contract['stop_condition'] = boundary_text(4000, 'stop_condition')
        body = self.approve(contract)
        _, revision, _ = self.request('/api/state')
        changed = dict(contract, stop_condition=contract['stop_condition'][:-1] + '异')
        before, handoffs = self.main_snapshot(), self.handoff_snapshot()
        code, _, reply = self.request('/api/project/manager/handoff',
                                      dict(body, ifRev=revision, contract=changed))
        self.assertEqual(self.main_snapshot(), before)
        self.assertEqual(self.handoff_snapshot(), handoffs)
        self.assertEqual(code, 400, reply)

    def test_management_retry_and_context_reads_inherit_spent_budget(self):
        contract = contract_fixture(True)
        body = self.approve(contract)
        self.context()
        budget = self.used_budget()
        code, _, claim = self.agent('management/claim', {'handoff_id': body['handoff_id']})
        self.assertEqual(code, 200, claim)
        for number in (1, 2):
            code, _, reply = self.agent('activity', {
                'phase': 'progress', 'action_id': claim['action_id'], 'summary': '合成进度 ' + str(number),
            })
            self.assertEqual(code, 200, reply)
        before = self.main_snapshot()
        code, _, retry = self.agent('management/claim', {
            'handoff_id': body['handoff_id'], 'budget': {'max_progress_reports': 20},
            'reason': '重试不得改预算或批准原文',
        })
        self.assertEqual(code, 200, retry)
        self.assertTrue(retry['already_claimed'])
        self.assertEqual(retry['action_id'], claim['action_id'])
        self.assertEqual(self.main_snapshot(), before, 'Idempotent retry wrote another action/event')
        for _ in range(2):
            context = self.context()
            active = next(row for row in context['management']['resume_brief']['handoff']['active_actions']
                          if row['id'] == claim['action_id'])
            self.assertEqual(active['progress_reports_used'], 2)
            self.assertEqual(json_value(active['budget']), contract['budget'])
            self.assertEqual(active['stop_condition'], contract['stop_condition'])
            self.assertEqual(context['management']['resume_brief']['handoff']['management_budget']['used_today'], 1)
        self.rejected_claim({'phase': 'progress', 'action_id': claim['action_id'],
                             'summary': '预算用尽后额外报告'}, self.agent_token, expected=409)
        self.assertEqual(self.used_budget(), budget)
        self.assert_action_contract(claim, contract)

    def test_management_retry_returns_original_contract_hash(self):
        contract = contract_fixture(True)
        body = self.approve(contract)
        self.context()
        code, _, claim = self.agent('management/claim', {'handoff_id': body['handoff_id']})
        self.assertEqual(code, 200, claim)
        before, budget = self.main_snapshot(), self.used_budget()
        code, _, retry = self.agent('management/claim', {'handoff_id': body['handoff_id']})
        self.assertEqual(code, 200, retry)
        self.assertEqual(self.main_snapshot(), before)
        self.assertEqual(self.used_budget(), budget)
        self.assertTrue(retry['already_claimed'])
        self.assertEqual(retry['action_id'], claim['action_id'])
        self.assertIn('contract_hash', retry, 'Idempotent claim must return the original contract identity')
        self.assertEqual(retry['contract_hash'], claim['contract_hash'])

    def strict_roundtrip(self, length):
        token = self.strict_agent()
        context = self.context(token)
        contract = contract_fixture()
        contract['goal'] = boundary_text(400, 'goal')
        for field in CONDITION_FIELDS:
            contract[field] = boundary_text(length, field)
        body = dict(contract, phase='claim', context_hash=context['management']['resume_brief']['source_hash'])
        code, _, claim = self.request('/api/agent/activity', body, token=token)
        self.assertEqual(code, 200, claim)
        self.assert_action_contract(claim, contract)

    def test_strict_roundtrip_1999(self):
        self.strict_roundtrip(1999)

    def test_strict_roundtrip_2000(self):
        self.strict_roundtrip(2000)

    def test_strict_roundtrip_2001(self):
        self.strict_roundtrip(2001)

    def test_strict_roundtrip_4000_and_tail_stop(self):
        self.strict_roundtrip(4000)

    def test_legacy_http_connection_keeps_minimal_claim_compatible(self):
        # The fixture connection omits contract_mode and has not handshaken.
        code, _, claim = self.agent('activity', {
            'phase': 'claim', 'goal': '旧 HTTP 合成认领', 'reason': '兼容调用', 'expected_output': '记录',
        })
        self.assertEqual(code, 200, claim)
        self.assertTrue(claim['action_id'])

    def test_strict_unhandshaken_even_with_current_hash_is_rejected(self):
        token = self.strict_agent()
        code, _, context = self.request('/api/project/context?project_id=p1')
        self.assertEqual(code, 200, context)
        self.rejected_claim(self.claim_body(context), token, expected=409)

    def test_noncontext_read_is_not_a_strict_handshake(self):
        token = self.strict_agent()
        self.assertEqual(self.request('/api/agent/actions', token=token)[0], 200)
        _, _, context = self.request('/api/project/context?project_id=p1')
        self.rejected_claim(self.claim_body(context), token, expected=409)

    def test_strict_handshake_is_bound_to_the_claiming_agent(self):
        token = self.strict_agent()
        context = self.context()  # Another agent's handshake cannot authorize this one.
        self.rejected_claim(self.claim_body(context), token, expected=409)

    def test_strict_missing_context_hash_is_rejected(self):
        token = self.strict_agent()
        self.context(token)
        self.rejected_claim(self.claim_body(), token, expected=409)

    def test_strict_stale_context_hash_is_rejected(self):
        token = self.strict_agent()
        old = self.context(token)
        code, _, reply = self.request('/api/action', {
            'collection': 'tasks', 'item': {'id': 'changed', 'project': 'p1', 'title': '合成来源版本改变'},
        })
        self.assertEqual(code, 200, reply)
        self.rejected_claim(self.claim_body(old), token, expected=409)

    def test_strict_empty_or_missing_criteria_are_rejected(self):
        token = self.strict_agent()
        context = self.context(token)
        for field in ('success_condition', 'failure_condition', 'stop_condition'):
            for invalid in ('', ' \t\n\u3000', None):
                with self.subTest(field=field, invalid=repr(invalid)):
                    self.rejected_claim(self.claim_body(context, **{field: invalid}), token, expected=400)
            with self.subTest(field=field, missing=True):
                body = self.claim_body(context)
                del body[field]
                self.rejected_claim(body, token, expected=400)

    def test_strict_4001_conditions_and_401_goal_are_rejected(self):
        token = self.strict_agent()
        context = self.context(token)
        for field in TEXT_FIELDS:
            with self.subTest(field=field):
                text = boundary_text(401 if field == 'goal' else 4001, field)
                self.rejected_claim(self.claim_body(context, **{field: text}), token, expected=400)

    def test_strict_budget_must_be_explicit_and_valid(self):
        token = self.strict_agent()
        context = self.context(token)
        for invalid in (None, {}, {'max_progress_reports': 0}, {'max_progress_reports': True}):
            with self.subTest(budget=invalid):
                self.rejected_claim(self.claim_body(context, budget=invalid), token, expected=400)
        body = self.claim_body(context)
        del body['budget']
        self.rejected_claim(body, token, expected=400)

    def test_strict_unknown_dependency_is_rejected(self):
        token = self.strict_agent()
        self.rejected_claim(self.claim_body(self.context(token), dependencies=['synthetic-missing']),
                             token, expected=409)

    def test_strict_cross_project_dependency_is_rejected(self):
        for collection, item in (
            ('projects', {'id': 'p2', 'name': '其他合成项目', 'stages': []}),
            ('tasks', {'id': 'foreign-task', 'project': 'p2', 'title': '其他项目的合成依赖', 'status': '已完成'}),
        ):
            code, _, reply = self.request('/api/action', {'collection': collection, 'item': item})
            self.assertEqual(code, 200, reply)
        token = self.strict_agent()
        self.rejected_claim(self.claim_body(self.context(token), dependencies=['foreign-task']), token, expected=409)

    def test_strict_default_recorded_allows_unfinished_registered_dependency(self):
        token = self.strict_agent()
        context = self.context(token)
        self.assertNotEqual(next(row for row in context['active_tasks'] if row['id'] == 't1')['status'], '已完成')
        body = self.claim_body(context)
        del body['dependency_policy']
        code, _, claim = self.request('/api/agent/activity', body, token=token)
        self.assertEqual(code, 200, claim)
        self.assert_action_contract(claim, contract_fixture())

    def test_strict_all_completed_rejects_unfinished_dependency(self):
        token = self.strict_agent()
        self.rejected_claim(self.claim_body(self.context(token), dependency_policy='all_completed'),
                             token, expected=409)

    def test_strict_all_completed_accepts_completed_dependency(self):
        code, _, reply = self.request('/api/action', {
            'collection': 'tasks', 'item': {'id': 't1', 'project': 'p1', 'title': '合成已完成依赖', 'status': '已完成'},
        })
        self.assertEqual(code, 200, reply)
        token = self.strict_agent()
        body = self.claim_body(self.context(token), dependency_policy='all_completed')
        code, _, claim = self.request('/api/agent/activity', body, token=token)
        self.assertEqual(code, 200, claim)
        self.assert_action_contract(claim, dict(contract_fixture(), dependency_policy='all_completed'))

    def test_strict_connection_cannot_downgrade_via_claim_payload(self):
        token = self.strict_agent()
        context = self.context(token)
        self.rejected_claim(self.claim_body(context, contract_mode='legacy', success_condition=''),
                             token, expected=400)

    def test_strict_context_reconnect_does_not_reset_progress_budget(self):
        token = self.strict_agent()
        body = self.claim_body(self.context(token))
        code, _, claim = self.request('/api/agent/activity', body, token=token)
        self.assertEqual(code, 200, claim)
        budget = self.used_budget()
        for count in (1, 2):
            code, _, reply = self.request('/api/agent/activity', {
                'phase': 'progress', 'action_id': claim['action_id'], 'summary': '合成严格行动进度 ' + str(count),
            }, token=token)
            self.assertEqual(code, 200, reply)
            context = self.context(token)
            active = next(row for row in context['management']['resume_brief']['handoff']['active_actions']
                          if row['id'] == claim['action_id'])
            self.assertEqual(active['progress_reports_used'], count)
            self.assertEqual(json_value(active['budget']), {'max_progress_reports': 2})
        self.rejected_claim({'phase': 'progress', 'action_id': claim['action_id'],
                             'summary': '第三次报告必须拒绝'}, token, expected=409)
        self.assertEqual(self.used_budget(), budget)
        self.assert_action_contract(claim, contract_fixture())

    def mcp_reply(self, name, arguments=None, token=None):
        if not support.NODE:
            self.skipTest('Node is required for real MCP transport')
        environment = os.environ.copy()
        environment.update(RESEARCH_DESK_BASE_URL=self.base,
                           RESEARCH_DESK_AGENT_TOKEN=token or self.agent_token,
                           RESEARCH_DESK_PROJECT_ID='p1', RESEARCH_DESK_DATA_DIR=str(self.dir))
        messages = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                'protocolVersion': '2024-11-05', 'capabilities': {},
                'clientInfo': {'name': 'synthetic-contract-test', 'version': '1'},
            }},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
             'params': {'name': name, 'arguments': arguments or {}}},
        ]
        run = subprocess.run([support.NODE, str(ROOT / 'mcp-server.js')], cwd=str(ROOT),
                             env=environment, input=''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in messages),
                             text=True, capture_output=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        rows = [json.loads(line) for line in run.stdout.splitlines()]
        initialized = next(row for row in rows if row.get('id') == 1)
        self.assertEqual(initialized['result']['protocolVersion'], '2024-11-05')
        reply = next(row for row in rows if row.get('id') == 2)
        self.assertNotIn('error', reply, reply)
        return reply['result']

    def mcp_value(self, name, arguments=None):
        reply = self.mcp_reply(name, arguments)
        self.assertFalse(reply.get('isError'), reply)
        return json.loads(reply['content'][0]['text'])

    def rejected_mcp(self, body):
        before, budget = self.main_snapshot(), self.used_budget()
        reply = self.mcp_reply('project.claim_action', body)
        self.assertEqual(self.main_snapshot(), before, 'Rejected MCP claim wrote project state')
        self.assertEqual(self.used_budget(), budget)
        self.assertTrue(reply.get('isError'), reply)

    def test_mcp_project_claim_is_strict_on_legacy_http_connection(self):
        _, _, context = self.request('/api/project/context?project_id=p1')
        self.rejected_mcp(self.claim_body(context))

    def test_mcp_strict_missing_hash_and_empty_criteria_are_rejected(self):
        context = self.mcp_value('project.get_context')
        self.rejected_mcp(self.claim_body())
        for field in ('success_condition', 'failure_condition', 'stop_condition'):
            with self.subTest(field=field):
                self.rejected_mcp(self.claim_body(context, **{field: ''}))
        body = self.claim_body(context)
        del body['budget']
        self.rejected_mcp(body)

    def test_mcp_strict_stale_hash_and_bad_dependencies_are_rejected(self):
        old = self.mcp_value('project.get_context')
        code, _, reply = self.request('/api/action', {
            'collection': 'tasks', 'item': {'id': 'new-version', 'project': 'p1', 'title': '合成版本变化'},
        })
        self.assertEqual(code, 200, reply)
        self.rejected_mcp(self.claim_body(old))
        current = self.mcp_value('project.get_context')
        self.rejected_mcp(self.claim_body(current, dependencies=['unknown']))

    def test_mcp_strict_current_hash_and_complete_contract_roundtrip(self):
        context = self.mcp_value('project.get_context')
        contract = contract_fixture()
        contract['reason'] = boundary_text(2001, 'reason')
        contract['stop_condition'] = boundary_text(4000, 'stop_condition')
        body = dict(contract, context_hash=context['management']['resume_brief']['source_hash'])
        claim = self.mcp_value('project.claim_action', body)
        self.assert_action_contract(claim, contract)


if __name__ == '__main__':
    unittest.main()
