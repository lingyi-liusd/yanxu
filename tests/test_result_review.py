"""Standalone receipt checks: synthetic SQLite only, no server/production data."""
import copy
import hashlib
import json
import pathlib
import sqlite3
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import result_review as review


VERSION = 'sha256:' + 'a' * 64
OTHER_VERSION = 'sha256:' + 'b' * 64


class ResultReviewTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.addCleanup(self.c.close)
        # Match the canonical result/evidence columns without importing server.
        self.c.executescript('''
          CREATE TABLE action_results (
            id TEXT PRIMARY KEY, action_id TEXT NOT NULL, project_id TEXT NOT NULL,
            outcome TEXT NOT NULL, summary TEXT NOT NULL, source_ref TEXT NOT NULL,
            actor TEXT NOT NULL, created_at TEXT NOT NULL,
            verification_status TEXT NOT NULL DEFAULT 'UNVERIFIED', source_version TEXT NOT NULL);
          CREATE TABLE evidence (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, action_id TEXT, task_id TEXT,
            status TEXT NOT NULL, title TEXT NOT NULL, summary TEXT NOT NULL,
            source_ref TEXT NOT NULL, source_version TEXT, artifact_path TEXT,
            provenance TEXT, actor TEXT NOT NULL, created_at TEXT NOT NULL,
            supersedes_id TEXT, invalidated_at TEXT,
            verification_status TEXT NOT NULL DEFAULT 'UNVERIFIED');
        ''')
        review.schema(self.c)
        self.c.execute('''INSERT INTO action_results
          (id,action_id,project_id,outcome,summary,source_ref,actor,created_at,source_version)
          VALUES ('r','a','p','FAIL','保留负结果与未解条件','/synthetic/nonexistent.md',
                  'synthetic-agent','2026-10-03T00:00:00+08:00',?)''', (VERSION,))
        self.evidence('e')
        self.c.commit()

    def evidence(self, eid, **changes):
        row = dict(id=eid, project_id='p', action_id='a', status='FAIL',
                   title='与Result标题不同', summary='负结果仍未核验',
                   source_ref='/synthetic/nonexistent.md', source_version=VERSION,
                   actor='synthetic-agent', created_at='2026-10-03T00:00:00+08:00')
        row.update(changes)
        self.c.execute('INSERT INTO evidence (' + ','.join(row) + ') VALUES ('
                       + ','.join('?' for _ in row) + ')', list(row.values()))

    def body(self, **changes):
        target = review.target(self.c, {'id': 'p'}, 'r')
        body = dict(project_id='p', result_id='r', target_hash=target['target_hash'],
                    source_version=target['result']['source_version'],
                    checked_source_version=VERSION, source_assessment='matched',
                    review_kind='source', criteria='人工比较登记版本与所查来源字节摘要',
                    reviewer='合成人工审查者', conclusion='needs_more',
                    notes='仅记录人工报告；未开展科学核验', consent=review.CONSENT)
        body.update(changes)
        return body

    def originals(self):
        return {table: self.c.execute('SELECT * FROM ' + table + ' ORDER BY id').fetchall()
                for table in ('action_results', 'evidence')}

    def count(self):
        return self.c.execute('SELECT count(*) FROM result_reviews').fetchone()[0]

    def assert_rejected(self, body, status=400):
        before, count, total = self.originals(), self.count(), self.c.total_changes
        with self.assertRaises(review.ReviewError) as caught:
            review.prepare(self.c, {'id': 'p'}, body)
        self.assertEqual(caught.exception.status, status)
        self.assertEqual((self.originals(), self.count(), self.c.total_changes), (before, count, total))

    def test_schema_is_idempotent_and_has_only_requested_columns(self):
        review.schema(self.c)
        self.assertEqual(tuple(row[1] for row in self.c.execute('PRAGMA table_info(result_reviews)')),
                         review.COLUMNS)

    def test_schema_does_not_commit_callers_transaction(self):
        self.c.execute("UPDATE action_results SET summary='事务内修改' WHERE id='r'")
        review.schema(self.c)
        self.c.rollback()
        self.assertEqual(review.target(self.c, 'p', 'r')['result']['summary'], '保留负结果与未解条件')

    def test_target_exact_identity_and_canonical_hash_no_title_guess(self):
        for eid, changes in [('other-project', {'project_id': 'q'}),
                             ('other-action', {'action_id': 'different'}),
                             ('other-ref', {'source_ref': '/other/nonexistent.md'}),
                             ('substring', {'source_ref': '/synthetic/nonexistent.md.bak'}),
                             ('other-version', {'source_version': OTHER_VERSION})]:
            self.evidence(eid, title='保留负结果与未解条件', **changes)
        target = review.target(self.c, 'p', 'r')
        self.assertEqual([row['id'] for row in target['evidence_candidates']], ['e'])
        self.assertEqual(target['evidence'], target['evidence_candidates'][0])
        self.assertEqual((target['evidence_association'], target['evidence_id']), ('unique', 'e'))
        payload = {'project_id': target['project_id'], 'result': target['result'],
                   'evidence': target['evidence_candidates']}
        expected = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
            separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
        self.assertEqual(target['target_hash'], expected)
        self.assertEqual(review.target(self.c, 'p', 'r'), target)

    def test_ui_top_level_fields_history_and_revision_readback(self):
        self.c.execute('CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)')
        self.c.execute("INSERT INTO meta VALUES ('rev','17')")
        target = review.target(self.c, 'p', 'r')
        self.assertTrue({'result', 'evidence', 'evidence_candidates', 'target_hash',
                         'source_ref', 'source_version', 'reviews', 'rev'} <= set(target))
        self.assertEqual(target['source_ref'], target['result']['source_ref'])
        self.assertEqual(target['source_version'], target['result']['source_version'])
        self.assertEqual(target['rev'], 17)
        self.assertEqual(target['reviews'], [])
        receipt = review.prepare(self.c, 'p', self.body())
        review.save(self.c, receipt)
        self.c.execute("UPDATE meta SET v='18' WHERE k='rev'")
        after = review.target(self.c, 'p', 'r')
        self.assertEqual(after['rev'], 18)
        self.assertEqual(after['target_hash'], target['target_hash'])
        self.assertEqual(after['reviews'][0]['id'], receipt['id'])
        self.assertEqual(after['reviews'][0]['project_id'], 'p')
        self.assertEqual(after['reviews'][0]['scientific_status'], 'NOT_ASSESSED')

    def test_target_missing_or_cross_project_result_is_not_exposed(self):
        for project, rid in [('q', 'r'), ('p', 'unknown')]:
            with self.subTest(project=project, rid=rid), self.assertRaises(review.ReviewError) as caught:
                review.target(self.c, project, rid)
            self.assertEqual(caught.exception.status, 404)

    def test_zero_matches_can_review_result_without_inventing_evidence(self):
        self.c.execute("DELETE FROM evidence WHERE id='e'")
        self.evidence('same-title', source_version=OTHER_VERSION)
        target = review.target(self.c, 'p', 'r')
        self.assertEqual(target['evidence_association'], 'missing')
        self.assertIsNone(target['evidence'])
        self.assertIn('无法唯一关联', target['association_note'])
        receipt = review.prepare(self.c, 'p', self.body())
        self.assertIsNone(receipt['evidence_id'])
        review.save(self.c, receipt)
        self.assertIsNone(self.c.execute('SELECT evidence_id FROM result_reviews').fetchone()[0])

    def test_multiple_matches_mark_ambiguity_and_allow_explicit_selection(self):
        self.evidence('z', title='任意标题')
        self.evidence('b', title='另一标题')
        target = review.target(self.c, 'p', 'r')
        self.assertEqual([row['id'] for row in target['evidence_candidates']], ['b', 'e', 'z'])
        self.assertEqual(target['evidence_association'], 'ambiguous')
        self.assertIsNone(target['evidence'])
        self.assertIsNone(target['evidence_id'])
        self.assertIn('无法唯一关联', target['association_note'])
        receipt = review.prepare(self.c, 'p', self.body())
        self.assertIsNone(receipt['evidence_id'])
        review.save(self.c, receipt)
        selected = review.prepare(self.c, 'p', self.body(evidence_id='z'))
        self.assertEqual(review.save(self.c, selected)['evidence_id'], 'z')

    def test_explicit_evidence_must_match_all_identity_fields(self):
        cases = [{'project_id': 'q'}, {'action_id': 'other'},
                 {'source_ref': '/other'}, {'source_version': OTHER_VERSION}]
        for index, changes in enumerate(cases):
            eid = 'wrong-' + str(index)
            self.evidence(eid, **changes)
            with self.subTest(changes=changes):
                self.assert_rejected(self.body(evidence_id=eid))
        self.assert_rejected(self.body(evidence_id='unknown'))

    def test_prepare_is_read_only_and_does_not_mutate_body(self):
        body = self.body(ifRev=7, dry=True)
        original = copy.deepcopy(body)
        before, total = self.originals(), self.c.total_changes
        receipt = review.prepare(self.c, {'id': 'p'}, body)
        self.assertEqual(body, original)
        self.assertEqual(self.originals(), before)
        self.assertEqual(self.c.total_changes, total)
        self.assertEqual(self.count(), 0)
        self.assertEqual(receipt['evidence_id'], 'e')
        self.assertEqual(receipt['scientific_status'], 'NOT_ASSESSED')
        self.assertNotIn('ifRev', receipt)

    def test_required_human_consent_and_project_identity(self):
        for changes in ({'consent': None}, {'consent': 'other'}, {'project_id': 'q'},
                        {'result_id': None}, {'evidence_id': ''}):
            with self.subTest(changes=changes):
                self.assert_rejected(self.body(**changes))
        body = self.body()
        del body['consent']
        self.assert_rejected(body)

    def test_source_version_and_target_hash_must_be_explicit_and_current(self):
        for field in ('target_hash', 'source_version'):
            body = self.body()
            del body[field]
            self.assert_rejected(body)
        for changes in ({'target_hash': '0' * 64}, {'source_version': OTHER_VERSION},
                        {'source_ref': '/different'}):
            self.assert_rejected(self.body(**changes), 409)

    def test_stale_result_or_evidence_page_rejected(self):
        for table, field, value in [('action_results', 'summary', '新内容'),
                                    ('action_results', 'outcome', 'PASS'),
                                    ('action_results', 'source_version', OTHER_VERSION),
                                    ('evidence', 'summary', '新依据'),
                                    ('evidence', 'verification_status', 'VERIFIED'),
                                    ('evidence', 'source_version', OTHER_VERSION)]:
            with self.subTest(table=table, field=field):
                old = self.body()
                self.c.execute('UPDATE ' + table + ' SET ' + field + '=?', (value,))
                self.assert_rejected(old, 409)
                self.c.rollback()
        old = self.body()
        self.evidence('new-match')
        self.assert_rejected(old, 409)

    def test_matched_rejects_symbolic_bare_malformed_and_different_hashes(self):
        for version in ('v1', 'a' * 64, 'sha256:' + 'g' * 64,
                        'sha256:' + 'a' * 63, 'sha256:' + 'a' * 65, ''):
            with self.subTest(version=version):
                self.c.execute('UPDATE action_results SET source_version=?', (version,))
                self.assert_rejected(self.body(checked_source_version=version))
        self.c.rollback()
        for checked in (OTHER_VERSION, 'v1', 'a' * 64, '', VERSION + '\n'):
            self.assert_rejected(self.body(checked_source_version=checked))

    def test_checked_version_is_human_supplied_not_copied_or_coerced(self):
        body = self.body()
        del body['checked_source_version']
        self.assert_rejected(body)
        for checked in (None, 123, True, ['v1'], 'x' * 4001):
            self.assert_rejected(self.body(checked_source_version=checked, source_assessment='unavailable'))
        for assessment in ('missing', 'unavailable'):
            receipt = review.prepare(self.c, 'p', self.body(
                source_assessment=assessment, checked_source_version=''))
            self.assertEqual(receipt['checked_source_version'], '')

    def test_nonmatching_source_assessments_can_preserve_negative_receipts(self):
        for assessment, checked, conclusion in [('missing', '', 'rejected'),
                                               ('mismatch', OTHER_VERSION, 'rejected'),
                                               ('unavailable', '', 'needs_more'),
                                               ('symbolic', 'v-observed', 'needs_more')]:
            receipt = review.prepare(self.c, 'p', self.body(source_assessment=assessment,
                checked_source_version=checked, conclusion=conclusion))
            review.save(self.c, receipt)
        self.assertEqual(self.count(), 4)
        self.assertEqual(review.target(self.c, 'p', 'r')['result']['outcome'], 'FAIL')

    def test_legacy_blank_version_is_unknown_not_unique_or_matched(self):
        self.c.execute("UPDATE action_results SET source_version='' WHERE id='r'")
        self.c.execute("UPDATE evidence SET source_version='' WHERE id='e'")
        self.assertEqual(review.target(self.c, 'p', 'r')['evidence_association'], 'missing')
        receipt = review.prepare(self.c, 'p', self.body(
            source_assessment='unavailable', checked_source_version=''))
        self.assertEqual(receipt['source_version'], '')
        review.save(self.c, receipt)
        self.assert_rejected(self.body(checked_source_version=''))

    def test_text_limits_no_silent_truncation_and_exact_manual_text(self):
        for field in ('criteria', 'reviewer', 'notes'):
            for value in ('', ' \n\t ', None, 42, '字' * 4001):
                with self.subTest(field=field, value=repr(value)[:30]):
                    self.assert_rejected(self.body(**{field: value}))
            text = '字' * 4000
            receipt = review.prepare(self.c, 'p', self.body(**{field: text}))
            self.assertEqual(receipt[field], text)
        text = '  原文条件\n失败不改写  '
        receipt = review.prepare(self.c, 'p', self.body(notes=text))
        review.save(self.c, receipt)
        self.assertEqual(self.c.execute('SELECT notes FROM result_reviews').fetchone()[0], text)

    def test_enums_and_scientific_upgrade_rejected(self):
        for changes in ({'source_assessment': 'PASS'}, {'review_kind': 'other'},
                        {'conclusion': 'VERIFIED'}, {'scientific_status': 'VERIFIED'},
                        {'scientific_status': 'PASS'}):
            self.assert_rejected(self.body(**changes))

    def test_accepted_software_pass_never_upgrades_result_or_evidence(self):
        self.c.execute("UPDATE action_results SET outcome='PASS' WHERE id='r'")
        before = self.originals()
        for kind in review.REVIEW_KINDS:
            receipt = review.prepare(self.c, 'p', self.body(review_kind=kind,
                conclusion='accepted', notes='软件PASS，字节一致；科学核验未开展'))
            review.save(self.c, receipt)
        self.assertEqual(self.originals(), before)
        self.assertEqual(self.c.execute('SELECT DISTINCT scientific_status FROM result_reviews').fetchall(),
                         [('NOT_ASSESSED',)])

    def test_receipts_excluded_from_target_hash_and_other_drafts_stay_valid(self):
        before = review.target(self.c, 'p', 'r')
        first = review.prepare(self.c, 'p', self.body())
        second = review.prepare(self.c, 'p', self.body(notes='第二次独立人工意见'))
        review.save(self.c, first)
        after = review.target(self.c, 'p', 'r')
        self.assertEqual({k: v for k, v in after.items() if k != 'reviews'},
                         {k: v for k, v in before.items() if k != 'reviews'})
        self.assertEqual(len(after['reviews']), 1)
        review.save(self.c, second)
        self.assertEqual(self.count(), 2)

    def test_save_revalidates_stale_receipt_before_insert(self):
        receipt = review.prepare(self.c, 'p', self.body())
        self.c.execute("UPDATE evidence SET summary='变更发生在prepare之后' WHERE id='e'")
        with self.assertRaises(review.ReviewError) as caught:
            review.save(self.c, receipt)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.count(), 0)

    def test_save_revalidates_forged_receipt_and_consent(self):
        receipt = review.prepare(self.c, 'p', self.body())
        for changes in ({'consent': ''}, {'project_id': 'q'}, {'source_version': OTHER_VERSION},
                        {'source_ref': '/other'}, {'evidence_id': 'other'},
                        {'checked_source_version': OTHER_VERSION}, {'scientific_status': 'VERIFIED'},
                        {'criteria': ''}, {'review_kind': 'bad'}, {'created_at': 'invalid'},
                        {'created_at': '2026-10-03T00:00:00'}, {'id': ''}):
            with self.subTest(changes=changes), self.assertRaises(review.ReviewError):
                review.save(self.c, dict(receipt, **changes))
            self.assertEqual(self.count(), 0)
        for changed in (dict(receipt, unexpected=True), {k: v for k, v in receipt.items() if k != 'consent'}):
            with self.assertRaises(review.ReviewError):
                review.save(self.c, changed)

    def test_duplicate_content_rejected_even_with_new_id_and_time(self):
        first = review.prepare(self.c, 'p', self.body())
        review.save(self.c, first)
        second = review.prepare(self.c, 'p', self.body())
        self.assertNotEqual(first['id'], second['id'])
        for duplicate in (first, second):
            with self.assertRaises(review.ReviewError) as caught:
                review.save(self.c, duplicate)
            self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.count(), 1)
        changed = review.prepare(self.c, 'p', self.body(conclusion='rejected', notes='后续人工反对意见'))
        review.save(self.c, changed)
        self.assertEqual(self.count(), 2)
        self.assertEqual(self.c.execute('SELECT conclusion FROM result_reviews WHERE id=?',
                         (first['id'],)).fetchone()[0], 'needs_more')

    def test_null_evidence_duplicates_also_rejected(self):
        self.c.execute("DELETE FROM evidence WHERE id='e'")
        review.save(self.c, review.prepare(self.c, 'p', self.body()))
        with self.assertRaises(review.ReviewError):
            review.save(self.c, review.prepare(self.c, 'p', self.body()))
        self.assertEqual(self.count(), 1)

    def test_save_only_appends_and_leaves_commit_to_outer_transaction(self):
        receipt = review.prepare(self.c, 'p', self.body())
        statements = []
        self.c.set_trace_callback(statements.append)
        saved = review.save(self.c, receipt)
        self.c.set_trace_callback(None)
        writes = [sql for sql in statements if sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))]
        self.assertEqual(len(writes), 1)
        self.assertTrue(writes[0].startswith('INSERT INTO result_reviews'))
        self.assertEqual(saved, receipt)
        self.assertTrue(self.c.in_transaction)
        self.c.rollback()
        self.assertEqual(self.count(), 0)

    def test_no_source_file_network_or_model_access(self):
        # These targets need not exist or be reachable: only their registered
        # strings are reviewed. No live services or file fixtures are needed.
        for source in ('/synthetic/nonexistent.md', 'https://invalid.example/source'):
            self.c.execute('UPDATE action_results SET source_ref=?', (source,))
            self.c.execute('UPDATE evidence SET source_ref=?', (source,))
            with mock.patch('builtins.open', side_effect=AssertionError('file access')), \
                 mock.patch('pathlib.Path.open', side_effect=AssertionError('file access')), \
                 mock.patch('os.open', side_effect=AssertionError('file descriptor access')), \
                 mock.patch('os.scandir', side_effect=AssertionError('directory scan')), \
                 mock.patch('urllib.request.urlopen', side_effect=AssertionError('URL access')), \
                 mock.patch('socket.socket', side_effect=AssertionError('network access')), \
                 mock.patch('subprocess.Popen', side_effect=AssertionError('model/process access')):
                for assessment, checked in (('unavailable', ''), ('matched', VERSION)):
                    body = self.body(source_assessment=assessment, checked_source_version=checked)
                    review.save(self.c, review.prepare(self.c, 'p', body))
        self.assertEqual(self.count(), 4)

    def test_matched_exposed_as_human_declaration_without_source_inspection_claim(self):
        before = self.originals()
        receipt = review.prepare(self.c, 'p', self.body(conclusion='accepted'))
        review.save(self.c, receipt)
        target = review.target(self.c, 'p', 'r')
        self.assertEqual(target['reviews'][0]['source_assessment'], 'matched')
        self.assertEqual(target['reviews'][0]['reviewer'], '合成人工审查者')
        self.assertEqual(target['reviews'][0]['checked_source_version'], VERSION)
        self.assertIn('人工声明', target['boundary'])
        self.assertIn('格式和字符串相等性', target['boundary'])
        self.assertIn('未读取来源文件或URL', target['boundary'])
        self.assertIn('不证明服务取得或检查过来源字节', target['boundary'])
        self.assertIn('不代表科学核验', target['boundary'])
        self.assertEqual(target['reviews'][0]['scientific_status'], 'NOT_ASSESSED')
        self.assertEqual(target['scientific_status'], 'NOT_ASSESSED')
        self.assertEqual(self.originals(), before)


if __name__ == '__main__':
    unittest.main()
