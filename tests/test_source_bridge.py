import copy
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from source_bridge import Bridge, conversation, secure_read, walk
from agent_manager import Manager

THREAD = '01234567-1234-1234-1234-123456789abc'


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name).resolve()
        self.data = self.root / 'desk'
        self.files = self.root / 'selected'
        self.home = self.root / 'codex'
        for directory in (self.data, self.files, self.home): directory.mkdir()
        self.b = Bridge(self.data, self.home)

    def tearDown(self): self.temp.cleanup()

    def configure(self, **changes):
        body = dict(enabled=True, send_content=False, folders=[str(self.files)], threads=[],
            consent='selected-local-sources-v1', if_revision=self.b.status('p')['revision'])
        body.update(changes)
        return self.b.configure('p', body)

    def poll(self):
        self.b.last_poll.clear()
        self.b.poll()

    def seed_thread(self, identity=THREAD):
        directory = self.home / 'sessions' / '2026'
        directory.mkdir(parents=True, exist_ok=True)
        self.log = directory / ('rollout-' + THREAD + '.jsonl')
        rows = [{'type':'session_meta','payload':{'id':identity}},
                {'type':'response_item','payload':{'type':'message','role':'system','content':[{'type':'input_text','text':'DO NOT IMPORT SYSTEM'}]}},
                {'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':'核查指定文件'}]}},
                {'type':'response_item','payload':{'type':'message','role':'assistant','content':[{'type':'output_text','text':'PARTIAL 未验证；负结果保留'}]}},
                {'type':'response_item','payload':{'type':'message','role':'assistant','channel':'analysis','content':[{'type':'output_text','text':'DO NOT IMPORT INTERNAL ANALYSIS'}]}},
                {'type':'response_item','payload':{'type':'function_call_output','output':'DO NOT IMPORT TOOL'}}]
        self.log.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))

    def test_default_and_separate_consent(self):
        (self.files / 'note.md').write_text('private notes')
        self.poll()
        self.assertEqual(self.b.status('p')['observed'], [])
        self.assertIsNone(self.b.model_snapshot('p'))
        with self.assertRaises(ValueError): self.configure(consent='')
        with self.assertRaises(ValueError): self.configure(send_content=True)
        self.configure()
        self.poll()
        self.assertEqual(len(self.b.status('p')['observed']),1)
        self.assertNotIn('private notes',json.dumps(self.b.status('p')))
        self.assertEqual(self.b.model_snapshot('p')['items'], [])

    def test_discovery_versions_pause_and_remove(self):
        (self.files / 'a.md').write_text('未验证')
        self.configure(send_content=True, content_consent='selected-source-text-to-codex-v1')
        self.poll()
        old = self.b.model_snapshot('p')
        (self.files / 'new.txt').write_text('new discovery')
        self.poll()
        self.assertEqual(len(self.b.model_snapshot('p')['items']),2)
        (self.files / 'a.md').write_text('updated but UNVERIFIED')
        self.poll()
        self.assertNotEqual(old['items'][0]['version'],self.b.model_snapshot('p')['items'][0]['version'])
        self.configure(enabled=False)
        self.poll()
        self.assertEqual(self.b.model_snapshot('p')['items'], [])
        self.assertEqual(self.b.status('p')['observed'], [])
        self.assertTrue(self.b.status('p')['receipts'])

    def test_exclusions_symlinks_binary_oversize_and_secrets(self):
        (self.files / '.hidden.md').write_text('hidden')
        (self.files / 'api-token.txt').write_text('token')
        (self.files / 'large.md').write_text('x'*65537)
        (self.files / 'notes.txt').write_text('api_key = sk-' + 'x'*30)
        (self.files / 'binary.txt').write_bytes(b'a\x00b')
        (self.files / 'unsupported.pdf').write_bytes(b'pdf')
        (self.files / 'link.md').symlink_to(self.files / 'notes.txt')
        self.configure(send_content=True, content_consent='selected-source-text-to-codex-v1')
        self.poll()
        source = self.b.model_snapshot('p')
        self.assertTrue(source['items'])
        self.assertTrue(all('content' not in r for r in source['items'] if not r['reference'].endswith('large.md')))
        large=next(r for r in source['items'] if r['reference'].endswith('large.md'))
        self.assertTrue(large['truncated'])  # >64KB is now chunked, not silently omitted.
        self.assertNotIn('api-token',json.dumps(source))
        self.assertNotIn('sk-',json.dumps(source))
        with self.assertRaises(OSError): secure_read(self.files/'link.md',self.files,65536)

    def test_root_guards_revision_and_dry(self):
        for root in (self.root, self.home, self.data, pathlib.Path.home()):
            with self.assertRaises(ValueError): self.configure(folders=[str(root)])
        with self.assertRaises(ValueError): self.configure(threads=['../../auth'])
        self.configure(dry=True)
        self.assertEqual(self.b.status('p')['revision'],0)
        self.configure()
        with self.assertRaises(ValueError): self.configure(if_revision=0)

    def test_only_selected_messages_and_identity(self):
        self.seed_thread()
        self.configure(folders=[],threads=[THREAD],send_content=True,content_consent='selected-source-text-to-codex-v1')
        self.poll()
        row = self.b.model_snapshot('p')['items'][0]
        self.assertEqual(len(row['content']),2)
        self.assertEqual(row['verification_status'],'UNVERIFIED')
        self.assertNotIn('DO NOT IMPORT',json.dumps(row))
        self.log.write_text(self.log.read_text()+'{"type":')
        self.assertEqual(len(conversation(self.home,THREAD)['content']),2)
        self.seed_thread(identity='wrong')
        with self.assertRaises(ValueError): conversation(self.home,THREAD)

    def test_directory_bounds_missing_and_app_subdirectory(self):
        for i in range(4): (self.files / str(i)).mkdir()
        with self.assertRaises(ValueError): list(walk(self.files, 3))
        with self.assertRaises(ValueError): list(walk(self.files / 'missing'))
        with self.assertRaises(ValueError): self.configure(folders=[str(pathlib.Path(__file__).parent)])

    def test_revoke_during_read_drops_output(self):
        (self.files / 'a.md').write_text('not retained after revoke')
        self.configure()
        original = secure_read
        def revoking(*args):
            self.configure(enabled=False)
            return original(*args)
        with patch('source_bridge.secure_read',side_effect=revoking): self.poll()
        self.assertEqual(self.b.status('p')['observed'],[])

    def test_manager_budget_dedupe_revocation_and_no_scientific_write(self):
        source = {'project':{'id':'p','goal':'unchanged'},'tasks':[]}
        before = copy.deepcopy(source)
        calls = []
        manager = Manager(self.data,lambda p:copy.deepcopy(source),lambda *a:None,
            runner=lambda value:(calls.append(value) or {k:'待核验' for k in ('summary','changes','risks','next_step','human_decision')}),debounce=0)
        manager.bridge = self.b
        self.configure(send_content=True, content_consent='selected-source-text-to-codex-v1')
        (self.files / 'a.md').write_text('source version one')
        self.poll()
        manager.configure('p',dict(enabled=True,max_calls_per_day=1,consent='codex-project-records-v1'))
        manager.tick()
        self.assertEqual(len(calls),1)
        self.assertIn('source version one',json.dumps(calls))
        manager.tick()
        self.assertEqual(len(calls),1)
        (self.files / 'a.md').write_text('changed')
        self.poll()
        manager.tick()
        self.assertEqual(len(calls),1)  # shared budget, not a new budget
        self.configure(enabled=False)
        self.assertEqual(manager.source('p')[0]['source_bridge']['items'],[])
        self.assertEqual(source,before)

    def test_reconsent_does_not_reintroduce_previous_analysis(self):
        calls=[]
        manager=Manager(self.data,lambda p:{'project':{'id':'p'}},lambda *a:None,
            runner=lambda v:(calls.append(v) or {k:'OLD SOURCE BODY' for k in ('summary','changes','risks','next_step','human_decision')}),debounce=0)
        manager.bridge=self.b
        (self.files/'a.md').write_text('old')
        self.configure(send_content=True,content_consent='selected-source-text-to-codex-v1');self.poll()
        manager.configure('p',dict(enabled=True,max_calls_per_day=4,consent='codex-project-records-v1'))
        manager.tick()
        self.configure(enabled=False)
        manager.tick()
        self.assertNotIn('previous_analysis',calls[-1])
        self.assertNotIn('old',json.dumps(calls[-1]['current']['source_bridge']))

    def test_local_drafts_refresh_without_model_or_scientific_change(self):
        source = {'project':{'id':'p','goal':'原目标'}, 'files':[]}
        events, calls = [], []
        manager = Manager(self.data, lambda p:copy.deepcopy(source), lambda *args:events.append(args),
            runner=lambda payload:(calls.append(payload) or {k:'未核验' for k in ('summary','changes','risks','next_step','human_decision')}), debounce=0)
        manager.bridge = self.b
        self.configure()
        manager.configure('p', dict(enabled=True, max_calls_per_day=1, consent='codex-project-records-v1'))
        manager.tick()
        before = manager.status('p')
        self.assertEqual(len(calls), 1)
        (self.files/'new.md').write_text('本地资料，不发送正文')
        self.b.last_poll.clear()
        manager.tick()
        after = manager.status('p')
        self.assertEqual(len(calls), 1)
        self.assertEqual(after['source_hash'], before['source_hash'])
        self.assertEqual(after['jobs'], before['jobs'])
        self.assertEqual(after['used_today'], before['used_today'])
        self.assertEqual(len(after['source_intake']['items']), 1)
        self.assertTrue(any(ev[1].get('reason') == 'sources.observed' for ev in events))
        self.assertNotIn('本地资料', json.dumps(after['source_intake'], ensure_ascii=False))
        self.assertEqual(source, {'project':{'id':'p','goal':'原目标'}, 'files':[]})


if __name__ == '__main__': unittest.main()
