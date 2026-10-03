import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from source_bridge import Bridge
from agent_manager import Manager


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=pathlib.Path(self.temp.name).resolve()
        self.data=self.root/'desk';self.data.mkdir()
        self.files=self.root/'files';self.files.mkdir()
        self.bridge=Bridge(self.data,self.root/'codex')
        self.bridge.configure('p',dict(enabled=True,send_content=True,folders=[str(self.files)],threads=[],
            if_revision=0,consent='selected-local-sources-v1',content_consent='selected-source-text-to-codex-v1'))

    def poll(self):
        self.bridge.last_poll.clear();self.bridge.poll()
        return self.bridge.model_snapshot('p')

    def test_all_140_files_indexed_and_batches_survive_restart(self):
        for i in range(140): (self.files/f'{i:03}.md').write_text('负结果保留 '+str(i))
        first=self.poll()
        self.assertEqual(self.bridge.status('p')['coverage']['indexed'],140)
        self.assertEqual(len(first['items']),128)
        self.assertEqual(self.poll(),first)
        self.bridge.accept_batch('p',first)
        self.bridge=Bridge(self.data,self.root/'codex')
        second=self.poll()
        self.assertEqual(len(second['items']),12)
        self.assertFalse({r['id'] for r in first['items']} & {r['id'] for r in second['items']})
        self.bridge.accept_batch('p',second)
        self.assertEqual(self.bridge.status('p')['coverage']['processed'],140)
        self.assertEqual(self.poll(),second)  # No endless empty-batch inference.
        self.assertEqual(self.bridge.index_page('p',100)['total'],140)

    def test_large_utf8_file_chunked_losslessly(self):
        original='资料待核验🙂\n'*16000
        (self.files/'large.md').write_text(original)
        parts=[]
        for _ in range(20):
            batch=self.poll()
            self.assertLessEqual(sum(len(r.get('content','').encode()) for r in batch['items']),65536)
            parts.extend(r['content'] for r in batch['items'] if 'content' in r)
            self.bridge.accept_batch('p',batch)
            if self.bridge.status('p')['coverage']['pending']==0: break
        self.assertEqual(''.join(parts),original)
        self.assertEqual(self.bridge.status('p')['coverage']['processed'],1)

    def test_failed_model_keeps_batch_pending_and_does_not_retry(self):
        (self.files/'a.md').write_text('not processed')
        self.poll();calls=[]
        def runner(payload):
            calls.append(payload);raise RuntimeError('synthetic failure')
        manager=Manager(self.data,lambda p:{'project':{'id':'p'}},lambda *a:None,runner=runner,debounce=0)
        manager.bridge=self.bridge
        manager.configure('p',dict(enabled=True,max_calls_per_day=4,consent='codex-project-records-v1'))
        manager.tick();manager.tick()
        self.assertEqual(len(calls),1)
        self.assertEqual(self.bridge.status('p')['coverage']['processed'],0)

    def test_saved_success_recovers_read_cursor_without_model_replay(self):
        (self.files/'a.md').write_text('recovered reading receipt')
        self.poll();calls=[]
        manager=Manager(self.data,lambda p:{'project':{'id':'p'}},lambda *a:None,
            runner=lambda value:(calls.append(value) or {k:'未核验' for k in ('summary','changes','risks','next_step','human_decision')}),debounce=0)
        manager.bridge=self.bridge
        manager.configure('p',dict(enabled=True,max_calls_per_day=4,consent='codex-project-records-v1'))
        with patch.object(self.bridge,'accept_batch'):
            manager.tick()  # Simulate process loss between result commit and ledger acknowledgment.
        self.assertEqual(self.bridge.status('p')['coverage']['processed'],0)
        manager.tick()
        self.assertEqual(len(calls),1)
        self.assertEqual(self.bridge.status('p')['coverage']['processed'],1)

    def test_change_before_result_cannot_be_accepted(self):
        f=self.files/'a.md';f.write_text('old')
        first=self.poll();f.write_text('new')
        self.assertEqual(self.bridge.model_snapshot('p')['items'],[])
        second=self.poll()
        self.bridge.accept_batch('p',first)
        self.assertEqual(self.bridge.status('p')['coverage']['processed'],0)
        self.bridge.accept_batch('p',second)
        self.assertEqual(self.bridge.status('p')['coverage']['processed'],1)

    def test_incomplete_inventory_never_claims_complete_or_removes_existing(self):
        (self.files/'a.md').write_text('kept')
        self.poll()
        with patch('source_bridge.walk',side_effect=ValueError('synthetic unavailable')):
            self.poll()
        status=self.bridge.status('p')['coverage']
        self.assertFalse(status['inventory_complete'])
        self.assertEqual(status['removed'],0)
        self.assertEqual(status['indexed'],1)


if __name__=='__main__': unittest.main()
