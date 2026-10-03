import concurrent.futures
import copy
import hashlib
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import source_intake
from source_bridge import Bridge
import test_server as support


class DraftTests(unittest.TestCase):
    def test_metadata_only_deterministic_and_project_bound(self):
        observed = [{'id':'file:/a.md', 'kind':'file', 'reference':'/a.md', 'version':'sha256:'+'a'*64,
                     'state':'read', 'content':'PRIVATE BODY'},
                    {'id':'file:/b.md', 'kind':'file', 'reference':'/b.md', 'version':'sha256:'+'b'*64, 'state':'read'}]
        scope = {'revision':1, 'enabled':True, 'observed':observed}
        before = copy.deepcopy(scope)
        files = [{'project':'other', 'path':'/a.md'}, {'project':'p', 'path':'/b.md'}]
        draft = source_intake.build('p', files, scope)
        self.assertEqual([i['path'] for i in draft['items']], ['/a.md'])
        self.assertNotIn('PRIVATE BODY', json.dumps(draft))
        self.assertEqual(draft['items'][0]['verification_status'], 'UNVERIFIED')
        scope['observed'].reverse()
        self.assertEqual(draft, source_intake.build('p', files, scope))
        scope['observed'].reverse()
        self.assertEqual(scope, before)
        self.assertNotEqual(draft['draft_hash'], source_intake.build('other', files, scope)['draft_hash'])

    def test_disabled_skipped_conversations_and_duplicates_not_promoted(self):
        good = {'id':'file:/a.md', 'kind':'file', 'reference':'/a.md', 'version':'sha256:'+'a'*64, 'state':'read'}
        rows = [good, dict(good), dict(good, id='thread:t', kind='conversation'),
                dict(good, id='file:/c', reference='/c', state='skipped_or_unreadable'),
                dict(good, id='file:/d', reference='/d', version='v1')]
        scope = {'enabled':True, 'observed':rows}
        self.assertEqual(len(source_intake.build('p', [], scope)['items']), 1)
        scope['enabled'] = False
        self.assertEqual(source_intake.build('p', [], scope)['items'], [])


class IntakeHTTPTests(unittest.TestCase):
    api = support.ServerCase.api
    _wait_ready = support.ServerCase._wait_ready
    create_project = support.ServerCase.create_project
    tearDown = support.ServerCase.tearDown

    def setUp(self):
        support.ServerCase.setUp(self)
        self.source_tmp = tempfile.TemporaryDirectory(prefix='intake-selected-')
        self.addCleanup(self.source_tmp.cleanup)
        self.folder = pathlib.Path(self.source_tmp.name).resolve()
        self.file = self.folder / '研究记录.md'
        self.file.write_text('负结果保留；真实测试 NOT_RUN', encoding='utf-8')
        self.create_project('p', '隔离内测')
        code, _, workspace = self.api('/api/project/workspace', {'project_id':'p','root':str(self.folder),
            'relative_path':'.','if_revision':0,'consent':'project-workspace-binding-v1'})
        self.assertEqual(code,200,workspace)
        self.workspace_revision=workspace['revision']
        self.bridge = Bridge(self.data_dir, self.folder / 'no-codex-sessions')

    def authorize(self):
        rev = self.bridge.status('p')['revision']
        code, _, _ = self.api('/api/project/manager/sources', {'project_id':'p', 'enabled':True,
            'send_content':False, 'folders':[str(self.folder)], 'threads':[],
            'if_revision':rev, 'workspace_revision':self.workspace_revision,'consent':'selected-local-sources-v1'})
        self.assertEqual(code, 200)
        self.bridge.last_poll.clear()
        self.bridge.poll()

    def preview(self):
        code, rev, state = self.api('/api/state')
        self.assertEqual(code, 200)
        code, _, manager = self.api('/api/project/manager?project_id=p')
        self.assertEqual(code, 200)
        draft = manager['source_intake']
        body = {'project_id':'p', 'ifRev':rev, 'draft_hash':draft['draft_hash'],
                'source_ids':[i['id'] for i in draft['items']], 'confirm_indexing':True}
        return body, state, manager

    def test_confirm_only_indexes_with_version_no_model_or_evidence(self):
        _, before, manager = self.preview()
        self.assertEqual(manager['source_intake']['items'], [])
        self.authorize()
        body, before, manager = self.preview()
        self.assertEqual(len(manager['source_intake']['items']), 1)
        code, rev, dry = self.api('/api/project/manager/intake', dict(body, dry=True))
        self.assertEqual(code, 200)
        self.assertEqual(dry['added'], 1)
        self.assertEqual(self.api('/api/state')[2], before)
        code, rev, result = self.api('/api/project/manager/intake', body)
        self.assertEqual(code, 200, result)
        self.assertEqual(result['added'], 1)
        _, _, after = self.api('/api/state')
        self.assertEqual({k:v for k,v in after.items() if k != 'files'}, {k:v for k,v in before.items() if k != 'files'})
        index = after['files'][0]
        self.assertEqual(index['path'], str(self.file))
        self.assertEqual(index['content_hash'], 'sha256:'+hashlib.sha256(self.file.read_bytes()).hexdigest())
        self.assertEqual(index['verification_status'], 'UNVERIFIED')
        self.assertNotIn('真实测试', json.dumps(after, ensure_ascii=False))
        _, _, manager = self.api('/api/project/manager?project_id=p')
        self.assertEqual(manager['source_intake']['items'], [])
        self.assertEqual(manager['used_today'], 0)
        self.assertFalse(manager['source_bridge']['send_content'])
        self.assertEqual(self.api('/api/project/results?project_id=p')[2]['results'], [])
        code, _, failed = self.api('/api/project/manager/intake', dict(body, ifRev=rev))
        self.assertEqual(code, 400)
        self.assertEqual(len(self.api('/api/state')[2]['files']), 1)

    def test_live_file_changed_after_preview_rejected_without_poll(self):
        self.authorize()
        body, before, _ = self.preview()
        self.file.write_text('新版本；仍未核验', encoding='utf-8')
        code, _, result = self.api('/api/project/manager/intake', body)
        self.assertEqual(code, 400)
        self.assertIn('版本已变化', result['error'])
        self.assertEqual(self.api('/api/state')[2], before)

    def authorize_documents(self):
        self.authorize()
        rev=self.bridge.status('p')['revision']
        code,_,body=self.api('/api/project/manager/sources',{'project_id':'p','enabled':True,
            'send_content':False,'folders':[str(self.folder)],'threads':[],
            'if_revision':rev,'workspace_revision':self.workspace_revision,
            'consent':'selected-local-sources-v1','document_text_enabled':True,
            'document_consent':'selected-document-text-v1'})
        self.assertEqual(code,200,body)
        self.bridge.last_poll.clear();self.bridge.poll()

    def test_actual_binary_documents_register_metadata_without_reparse_or_science(self):
        from document_fixtures import docx_bytes,pdf_bytes
        from unittest import mock
        documents={'report.docx':docx_bytes(extra={'word/media/unread.png':b'x'}),
                   'report.pdf':pdf_bytes(('UNKNOWN',None))}
        for name,raw in documents.items():(self.folder/name).write_bytes(raw)
        self.authorize_documents();body,before,manager=self.preview()
        self.assertEqual(len(body['source_ids']),3)
        with mock.patch('document_text.extract',side_effect=AssertionError('No locked reparse')):
            code,_,result=self.api('/api/project/manager/intake',body)
        self.assertEqual(code,200,result)
        after=self.api('/api/state')[2]
        self.assertEqual(len(after['files']),3)
        for row in after['files']:
            self.assertEqual(row['verification_status'],'UNVERIFIED')
            self.assertEqual(row['content_hash'],'sha256:'+hashlib.sha256(pathlib.Path(row['path']).read_bytes()).hexdigest())
        self.assertEqual(self.api('/api/project/results?project_id=p')[2]['results'],[])
        self.assertEqual(self.api('/api/project/manager?project_id=p')[2]['used_today'],0)

    def test_old_document_parser_receipt_cannot_register(self):
        from document_fixtures import docx_bytes
        (self.folder/'report.docx').write_bytes(docx_bytes());self.authorize_documents()
        body,before,_=self.preview()
        with self.bridge.db() as c:
            c.execute("UPDATE source_index SET reading_details='{}' WHERE reference LIKE '%.docx'")
        code,_,result=self.api('/api/project/manager/intake',body)
        self.assertEqual(code,400,result);self.assertIn('解析版本',result['error'])
        self.assertEqual(self.api('/api/state')[2],before)

    def test_large_text_intake_uses_same_two_megabyte_read_boundary(self):
        self.file.write_text('Known UNKNOWN source. '*5000,encoding='utf-8')
        self.authorize();body,_,_=self.preview()
        self.assertGreater(self.file.stat().st_size,65536)
        code,_,result=self.api('/api/project/manager/intake',body)
        self.assertEqual(code,200,result)
        self.assertEqual(len(self.api('/api/state')[2]['files']),1)

    def test_revoked_and_reconsented_scope_reject_old_draft(self):
        self.authorize()
        body, before, _ = self.preview()
        scope = self.bridge.status('p')
        self.bridge.configure('p', {'enabled':False, 'send_content':False, 'folders':[], 'threads':[], 'if_revision':scope['revision']})
        self.assertEqual(self.api('/api/project/manager/intake', body)[0], 400)
        self.authorize()
        self.assertEqual(self.api('/api/project/manager/intake', body)[0], 400)
        self.assertEqual(self.api('/api/state')[2], before)

    def test_replaced_symlink_unreadable_or_sensitive_file_not_registered(self):
        self.authorize()
        body, before, _ = self.preview()
        self.file.unlink()
        self.assertEqual(self.api('/api/project/manager/intake', body)[0], 400)
        target = self.folder / 'other.md'
        target.write_text('same bytes are not a reason to follow a symlink')
        self.file.symlink_to(target)
        self.assertEqual(self.api('/api/project/manager/intake', body)[0], 400)
        self.file.unlink()
        self.file.write_text('api_key = sk-'+'x'*30)
        self.assertEqual(self.api('/api/project/manager/intake', body)[0], 400)
        self.assertEqual(self.api('/api/state')[2], before)

    def test_invalid_selection_stale_revision_and_missing_confirmation_no_partial_write(self):
        self.authorize()
        body, before, _ = self.preview()
        for extra in ({'source_ids':body['source_ids']+['file:/unselected.md']},
                      {'source_ids':body['source_ids']*2}, {'source_ids':[]},
                      {'confirm_indexing':False}, {'ifRev':body['ifRev']-1}, {'project_id':'other'}):
            self.assertEqual(self.api('/api/project/manager/intake', dict(body, **extra))[0], 400)
            self.assertEqual(self.api('/api/state')[2], before)

    def test_concurrent_confirmation_only_one_write(self):
        self.authorize()
        body, _, _ = self.preview()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            codes = list(pool.map(lambda _:self.api('/api/project/manager/intake', body)[0], range(2)))
        self.assertEqual(sorted(codes), [200, 400])
        self.assertEqual(len(self.api('/api/state')[2]['files']), 1)


if __name__ == '__main__':
    unittest.main()
