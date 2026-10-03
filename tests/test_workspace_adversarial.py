"""Isolated workspace/source attacks; failing safety assertions are intentional.

Run from the repository root:
    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests \
        -p 'test_workspace_adversarial.py' -v

All bytes, sessions, databases and replacement directories are synthetic and
created beneath TemporaryDirectory. Permission failures are injected, never
implemented with chmod. No server, model runner or real research store is used.
Registry is a path policy, not a process sandbox. Source consent and content
consent remain separate from a workspace binding. Index/batch/ack tests use
Bridge.workspace, index_page, model_snapshot and accept_batch from the source.
"""

import copy
import errno
import hashlib
import json
import os
import pathlib
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import source_bridge
from source_bridge import Bridge, conversation, secure_read, walk
from workspace_registry import Registry


THREAD = '01234567-1234-1234-1234-123456789abc'
LOCAL_CONSENT = 'selected-local-sources-v1'
CONTENT_CONSENT = 'selected-source-text-to-codex-v1'
BINDING_CONSENT = 'project-workspace-binding-v1'


class IsolatedCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='yanxu-adversarial-')
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name).resolve()
        self.data = self.root / 'desk'
        self.workspace = self.root / 'workspace'
        self.home = self.root / 'codex'
        self.fake_user = self.root / 'user-home'
        self.first = self.workspace / 'alpha'
        self.second = self.workspace / 'beta'
        for directory in (self.data, self.home, self.fake_user, self.first, self.second):
            directory.mkdir(parents=True)
        # Protected-home checks stay entirely on synthetic directories.
        for patcher in (patch('pathlib.Path.home', return_value=self.fake_user),
                        patch.dict(os.environ, {'CODEX_HOME': str(self.home)})):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.projects = {
            'alpha': {'project': {'id': 'alpha', 'workspace': str(self.first),
                                  'goal': 'synthetic isolation check'}},
            'beta': {'project': {'id': 'beta', 'workspace': str(self.second)}},
        }
        self.registry = Registry(self.data, lambda p: copy.deepcopy(self.projects[p]))
        self.bridge = Bridge(self.data, self.home)

    def bind(self, project='alpha', **changes):
        body = dict(root=str(self.workspace), relative_path=project, exclusions=[],
                    if_revision=self.registry.status(project)['revision'],
                    consent=BINDING_CONSENT)
        body.update(changes)
        return self.registry.configure(project, body)

    def scope(self, project='alpha', **changes):
        body = dict(enabled=True, send_content=True,
                    folders=[str(self.first if project == 'alpha' else self.second)],
                    threads=[], consent=LOCAL_CONSENT, content_consent=CONTENT_CONSENT,
                    if_revision=self.bridge.status(project)['revision'])
        if self.bridge.workspace is not None:
            body['workspace_revision'] = self.registry.status(project)['revision']
        body.update(changes)
        return self.bridge.configure(project, body)

    def poll(self):
        self.bridge.last_poll.clear()
        return self.bridge.poll()

    def text(self, path, content='SYNTHETIC ordinary source'):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def seed_thread(self, messages, identity=THREAD, folder='sessions'):
        path = self.home / folder / ('rollout-' + THREAD + '.jsonl')
        rows = [{'type': 'session_meta', 'payload': {'id': identity}}]
        rows.extend({'type': 'response_item', 'payload': {
            'type': 'message', 'role': role,
            'content': [{'type': 'input_text' if role == 'user' else 'output_text',
                         'text': content}]}} for role, content in messages)
        return self.text(path, ''.join(json.dumps(r) + '\n' for r in rows))

    def assertNoContent(self, marker, project='alpha'):
        self.assertNotIn(marker, json.dumps(self.bridge.status(project)))
        self.assertNotIn(marker, json.dumps(self.bridge.model_snapshot(project)))


class RegistryAdversarialTests(IsolatedCase):
    def test_legacy_workspace_suggestion_grants_neither_binding_nor_source_read(self):
        path = self.text(self.first / 'a.md', 'BINDING_IS_NOT_CONSENT')
        before = copy.deepcopy(self.projects)
        status = self.registry.status('alpha')
        self.assertFalse(status['configured'])
        self.assertEqual(status['suggested_path'], str(self.first))
        self.assertFalse(self.registry.allows('alpha', path))
        self.bind()
        with patch('source_bridge.secure_read', side_effect=AssertionError('unconsented read')):
            self.poll()
        self.assertFalse(self.bridge.status('alpha')['enabled'])
        self.assertIsNone(self.bridge.model_snapshot('alpha'))
        self.assertEqual(self.projects, before)

    def test_binding_consent_revision_and_dry_are_atomic(self):
        for changes in ({'consent': ''}, {'consent': LOCAL_CONSENT}, {'if_revision': 99}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.bind(**changes)
        result = self.bind(dry=True)
        self.assertTrue(result['dry'])
        self.assertEqual(self.registry.status('alpha')['revision'], 0)
        with self.registry.db() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM workspaces').fetchone()[0], 0)
        self.bind()
        before = self.registry.status('alpha')
        with self.assertRaises(ValueError):
            self.bind(if_revision=0, exclusions=['a.md'])
        self.assertEqual(self.registry.status('alpha'), before)

    def test_path_traversal_absolute_and_missing_target_are_rejected(self):
        for relative in ('../beta', 'alpha/../../beta', str(self.second), 'missing'):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                self.bind(relative_path=relative)
        self.assertFalse((self.workspace / 'missing').exists())
        self.assertFalse(self.registry.status('alpha')['configured'])

    def test_protected_roots_and_their_ancestors_or_private_children_are_rejected(self):
        private_child = self.home / 'sessions'
        private_child.mkdir()
        data_child = self.data / 'cache'
        data_child.mkdir()
        for root in (self.fake_user, self.home, private_child, self.data, data_child, self.root,
                     pathlib.Path(source_bridge.__file__).resolve().parent):
            with self.subTest(root=str(root)), self.assertRaises(ValueError):
                self.bind(root=str(root), relative_path='.')

    def test_symlink_root_and_target_are_rejected(self):
        alias = self.root / 'workspace-alias'
        alias.symlink_to(self.workspace, target_is_directory=True)
        child_alias = self.workspace / 'alpha-alias'
        child_alias.symlink_to(self.first, target_is_directory=True)
        for changes in ({'root': str(alias)}, {'relative_path': child_alias.name}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.bind(**changes)

    def test_same_nested_and_cross_root_overlaps_are_rejected(self):
        nested = self.first / 'nested'
        nested.mkdir()
        self.bind()
        attacks = [dict(relative_path='alpha'), dict(relative_path='alpha/nested'),
                   dict(root=str(self.first), relative_path='.'), dict(relative_path='.')]
        for attack in attacks:
            with self.subTest(attack=attack), self.assertRaises(ValueError):
                self.bind('beta', **attack)
        self.assertFalse(self.registry.status('beta')['configured'])

    def test_reversed_overlap_and_nonoverlapping_prefix_sibling(self):
        nested = self.first / 'nested'
        nested.mkdir()
        self.bind(relative_path='alpha/nested')
        with self.assertRaises(ValueError):
            self.bind('beta', relative_path='alpha')
        sibling = self.workspace / 'alpha-extra'
        sibling.mkdir()
        self.bind('beta', relative_path=sibling.name)
        self.assertFalse(self.registry.allows('alpha', sibling / 'a.md'))

    def test_concurrent_overlapping_bindings_only_commit_once(self):
        peer = Registry(self.data, lambda p: copy.deepcopy(self.projects[p]))
        barrier = threading.Barrier(2)

        def claim(registry, project):
            barrier.wait(timeout=5)
            try:
                registry.configure(project, dict(root=str(self.workspace), relative_path='alpha',
                    exclusions=[], if_revision=0, consent=BINDING_CONSENT))
                return 'committed'
            except ValueError:
                return 'rejected'

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(claim, r, p) for r, p in
                       ((self.registry, 'alpha'), (peer, 'beta'))]
            self.assertCountEqual([f.result(timeout=10) for f in futures], ['committed', 'rejected'])

    def test_exclusions_cover_descendants_without_prefix_overblocking(self):
        self.bind(exclusions=['draft', 'a.md', 'draft'])
        self.assertEqual(self.registry.status('alpha')['exclusions'], ['a.md', 'draft'])
        for name in ('draft', 'draft/sub/a.md', 'a.md'):
            with self.subTest(name=name):
                self.assertFalse(self.registry.allows('alpha', self.first / name))
        self.assertTrue(self.registry.allows('alpha', self.text(self.first / 'draft-extra/a.md')))
        self.assertTrue(self.registry.allows('alpha', self.text(self.first / 'a.md.extra')))

    def test_invalid_exclusions_do_not_mutate_binding(self):
        self.bind()
        before = self.registry.status('alpha')
        for exclusions in ('a.md', [None], [''], ['.'], ['../beta'], [str(self.second)],
                           ['x'] * 33):
            with self.subTest(exclusions=exclusions), self.assertRaises(ValueError):
                self.bind(exclusions=exclusions)
        self.assertEqual(self.registry.status('alpha'), before)

    def test_allow_rejects_traversal_symlinks_and_stale_revision(self):
        path = self.text(self.first / 'a.md')
        self.bind()
        alias = self.first / 'alias.md'
        alias.symlink_to(path)
        for attack in (alias, self.first / '../beta/a.md', self.second / 'a.md', pathlib.Path('a.md')):
            with self.subTest(path=str(attack)):
                self.assertFalse(self.registry.allows('alpha', attack))
        self.assertTrue(self.registry.allows('alpha', path, revision=1))
        self.bind(exclusions=['a.md'])
        self.assertFalse(self.registry.allows('alpha', path, revision=1))
        self.assertFalse(self.registry.allows('alpha', path, revision=2))

    def test_missing_bound_directory_fails_closed(self):
        self.bind()
        self.first.rename(self.workspace / 'retired-alpha')
        self.assertEqual(self.registry.status('alpha')['state'], 'unavailable')
        self.assertFalse(self.registry.allows('alpha', self.first / 'a.md'))

    def test_parent_symlink_replacement_invalidates_existing_binding(self):
        self.bind()
        retired = self.root / 'retired-workspace'
        self.workspace.rename(retired)
        self.workspace.symlink_to(retired, target_is_directory=True)
        self.assertEqual(self.registry.status('alpha')['state'], 'unavailable')
        self.assertFalse(self.registry.allows('alpha', self.first / 'a.md'))


@unittest.skipIf(os.name == 'nt', 'POSIX descriptor race tests; Windows needs native execution')
class SecureReaderAdversarialTests(IsolatedCase):
    def test_dotdot_cannot_escape_selected_root(self):
        self.text(self.second / 'outside.md', 'OUTSIDE_SELECTED_ROOT')
        traversal = self.first / '..' / 'beta' / 'outside.md'
        with self.assertRaises((OSError, ValueError), msg='.. traversal returned bytes outside selected root'):
            secure_read(traversal, self.first, 65536)

    def test_absolute_outside_path_is_rejected(self):
        path = self.text(self.second / 'outside.md')
        with self.assertRaises((OSError, ValueError)):
            secure_read(path, self.first, 65536)

    def test_leaf_and_parent_symlinks_cannot_be_read(self):
        outside = self.text(self.second / 'outside.md', 'SYMLINK_OUTSIDE')
        alias = self.first / 'alias.md'
        alias.symlink_to(outside)
        parent = self.first / 'linked-parent'
        parent.symlink_to(self.second, target_is_directory=True)
        for path in (alias, parent / outside.name):
            with self.subTest(path=str(path)), self.assertRaises((OSError, ValueError)):
                secure_read(path, self.first, 65536)

    def test_parent_swap_after_descriptor_open_stays_on_original_directory(self):
        path = self.text(self.first / 'nested/a.md', 'ORIGINAL_DESCRIPTOR_BYTES')
        self.text(self.second / 'nested/a.md', 'REPLACEMENT_BYTES')
        original_open = os.open
        swapped = []

        def racing_open(name, flags, *args, **kwargs):
            descriptor = original_open(name, flags, *args, **kwargs)
            if str(name) == 'alpha' and not swapped:
                self.first.rename(self.workspace / 'retired-alpha')
                self.first.symlink_to(self.second, target_is_directory=True)
                swapped.append(True)
            return descriptor

        with patch('source_bridge.os.open', side_effect=racing_open):
            self.assertEqual(secure_read(path, self.first, 65536), b'ORIGINAL_DESCRIPTOR_BYTES')
        self.assertEqual(swapped, [True])

    def test_file_growth_during_read_is_rejected(self):
        path = self.text(self.first / 'a.md', 'before')
        original_read = os.read
        mutated = []

        def racing_read(fd, size):
            if not mutated:
                self.text(path, 'changed-and-larger')
                mutated.append(True)
            return original_read(fd, size)

        with patch('source_bridge.os.read', side_effect=racing_read), self.assertRaises(ValueError):
            secure_read(path, self.first, 65536)
        self.assertEqual(mutated, [True])

    def test_permission_error_closes_every_opened_descriptor(self):
        path = self.text(self.first / 'denied.md')
        original_open, original_close = os.open, os.close
        opened, closed = [], []

        def denying_open(name, flags, *args, **kwargs):
            if str(name) == path.name:
                raise PermissionError(errno.EACCES, 'synthetic permission denial')
            descriptor = original_open(name, flags, *args, **kwargs)
            opened.append(descriptor)
            return descriptor

        def closing(fd):
            closed.append(fd)
            return original_close(fd)

        with patch('source_bridge.os.open', side_effect=denying_open), \
                patch('source_bridge.os.close', side_effect=closing), self.assertRaises(PermissionError):
            secure_read(path, self.first, 65536)
        self.assertEqual(closed, list(reversed(opened)))

    def test_fifo_and_oversize_are_rejected_without_blocking(self):
        pipe = self.first / 'pipe.txt'
        os.mkfifo(pipe)
        large = self.text(self.first / 'large.md', 'x' * 65537)
        for path in (pipe, large):
            with self.subTest(path=str(path)), self.assertRaises(ValueError):
                secure_read(path, self.first, 65536)


class BridgeAdversarialTests(IsolatedCase):
    def test_content_consent_is_independent_and_metadata_has_no_body(self):
        marker = 'LOCAL_BODY_REQUIRES_SEND_CONSENT'
        self.text(self.first / 'a.md', marker)
        self.bind()
        with self.assertRaises(ValueError):
            self.scope(content_consent='')
        self.scope(send_content=False, content_consent='')
        self.poll()
        self.assertEqual(self.bridge.model_snapshot('alpha')['items'], [])
        self.assertNotIn(marker, json.dumps(self.bridge.status('alpha')))
        self.assertEqual(len(self.bridge.status('alpha')['observed']), 1)

    def test_two_projects_never_mix_cached_content(self):
        self.text(self.first / 'a.md', 'ALPHA_ONLY_BYTES')
        self.text(self.second / 'b.md', 'BETA_ONLY_BYTES')
        self.scope()
        self.scope('beta')
        self.poll()
        self.assertNotIn('BETA_ONLY_BYTES', json.dumps(self.bridge.model_snapshot('alpha')))
        self.assertNotIn('ALPHA_ONLY_BYTES', json.dumps(self.bridge.model_snapshot('beta')))
        self.assertIsNone(self.bridge.model_snapshot('unconfigured-project'))

    def test_pause_immediately_clears_cache_and_prevents_future_open(self):
        self.text(self.first / 'a.md', 'OLD_CACHE_BODY')
        self.scope()
        self.poll()
        self.scope(enabled=False)
        self.assertNoContent('OLD_CACHE_BODY')
        with patch('source_bridge.secure_read', side_effect=AssertionError('read after pause')):
            self.poll()
        self.assertEqual(self.bridge.status('alpha')['observed'], [])

    def test_revoke_during_read_drops_observation_and_receipt(self):
        self.text(self.first / 'a.md', 'REVOKED_IN_FLIGHT_BODY')
        self.scope()
        original = secure_read

        def revoking(*args):
            result = original(*args)
            self.scope(enabled=False)
            return result

        with patch('source_bridge.secure_read', side_effect=revoking):
            self.assertEqual(self.poll(), [])
        self.assertEqual(self.bridge.status('alpha')['observed'], [])
        self.assertNoContent('REVOKED_IN_FLIGHT_BODY')
        self.assertFalse(any(r['operation'] == '来源观察'
                             for r in self.bridge.status('alpha')['receipts']))

    def test_revocation_stops_opening_remaining_files(self):
        first = self.text(self.first / 'a.md', 'FIRST_ALLOWED_READ')
        second = self.text(self.first / 'b.md', 'AFTER_REVOCATION_BODY')
        self.bind()
        self.bridge.workspace = self.registry
        self.scope()
        original = secure_read
        reads = []

        def revoking(path, root, limit):
            reads.append(path)
            raw = original(path, root, limit)
            if len(reads) == 1:
                self.scope(enabled=False)
            return raw

        with patch('source_bridge.secure_read', side_effect=revoking):
            self.poll()
        self.assertNotIn(second, reads, 'remaining file opened after consent was revoked')
        self.assertEqual(reads, [first])

    def test_inflight_scope_change_does_not_retain_old_or_inject_new_project_body(self):
        self.text(self.first / 'a.md', 'OLD_SELECTION_BODY')
        self.text(self.second / 'b.md', 'NEW_SELECTION_BODY')
        self.scope()
        original = secure_read

        def rebinding(*args):
            result = original(*args)
            self.scope(folders=[str(self.second)])
            return result

        with patch('source_bridge.secure_read', side_effect=rebinding):
            self.poll()
        self.assertNoContent('OLD_SELECTION_BODY')
        self.assertEqual(self.bridge.status('alpha')['observed'], [])
        self.poll()
        self.assertNotIn('OLD_SELECTION_BODY', json.dumps(self.bridge.model_snapshot('alpha')))
        self.assertIn('NEW_SELECTION_BODY', json.dumps(self.bridge.model_snapshot('alpha')))

    def test_symlink_parent_replacement_after_discovery_never_opens_target_bytes(self):
        path = self.text(self.first / 'nested/a.md', 'OLD_NESTED_BODY')
        self.text(self.second / 'a.md', 'ESCAPED_PARENT_BODY')
        self.scope()
        original = secure_read

        def replacing(*args):
            path.parent.rename(self.first / 'retired-nested')
            path.parent.symlink_to(self.second, target_is_directory=True)
            return original(*args)

        with patch('source_bridge.secure_read', side_effect=replacing):
            self.poll()
        self.assertNoContent('ESCAPED_PARENT_BODY')
        self.assertTrue(all('content' not in item
                            for item in self.bridge.model_snapshot('alpha')['items']))

    def test_regular_directory_replacement_requires_reconsent(self):
        self.text(self.first / 'a.md', 'ORIGINAL_SELECTED_TREE')
        self.bind()
        self.bridge.workspace = self.registry
        self.scope()
        self.poll()
        self.first.rename(self.workspace / 'retired-alpha')
        self.first.mkdir()
        self.text(self.first / 'a.md', 'SAME_PATH_DIFFERENT_DIRECTORY')
        self.poll()
        self.assertNoContent('SAME_PATH_DIFFERENT_DIRECTORY')

    def test_missing_folder_blocks_previous_body_and_reports_unavailability(self):
        self.text(self.first / 'a.md', 'MISSING_FOLDER_OLD_BODY')
        self.scope()
        self.poll()
        self.first.rename(self.workspace / 'retired-alpha')
        self.poll()
        self.assertNoContent('MISSING_FOLDER_OLD_BODY')
        snapshot = self.bridge.model_snapshot('alpha')
        self.assertEqual(snapshot['items'], [])
        self.assertTrue(snapshot.get('blocked'))

    def test_permission_failure_does_not_preserve_old_body_or_poison_next_project(self):
        denied = self.text(self.first / 'a.md', 'DENIED_FILE_OLD_BODY')
        self.text(self.second / 'b.md', 'OTHER_PROJECT_STILL_READABLE')
        self.scope()
        self.scope('beta')
        self.poll()
        original = secure_read

        def denying(path, *args):
            if path == denied:
                raise PermissionError(errno.EACCES, 'synthetic permission denial')
            return original(path, *args)

        with patch('source_bridge.secure_read', side_effect=denying):
            self.poll()
        self.assertNoContent('DENIED_FILE_OLD_BODY')
        self.assertIn('OTHER_PROJECT_STILL_READABLE', json.dumps(self.bridge.model_snapshot('beta')))

    def test_secret_names_hidden_directories_and_symlinks_never_return_body(self):
        forbidden = [self.text(self.first / name, 'NEVER_READ_NAMED_SECRET')
                     for name in ('api-token.txt', '.hidden/a.md', 'secrets/a.md', 'node_modules/a.md')]
        self.text(self.second / 'outside.md', 'SYMLINK_EXTERNAL_BODY')
        (self.first / 'link.md').symlink_to(self.second / 'outside.md')
        self.scope()
        with patch('source_bridge.secure_read', wraps=secure_read) as reader:
            self.poll()
        opened = [call.args[0] for call in reader.call_args_list]
        self.assertTrue(all(path not in opened for path in forbidden))
        self.assertNoContent('NEVER_READ_NAMED_SECRET')
        self.assertNoContent('SYMLINK_EXTERNAL_BODY')

    def test_sensitive_text_and_invalid_utf8_are_never_cached_as_body(self):
        samples = ['-----BEGIN PRIVATE KEY-----\nSYNTHETIC', 'Bearer ' + 'X' * 24,
                   'password = synthetic-password', 'api_key = sk-' + 'z' * 24]
        for i, text in enumerate(samples):
            self.text(self.first / ('a%d.md' % i), text)
        (self.first / 'bad.txt').write_bytes(b'\xff\xfe\x00')
        self.scope()
        self.poll()
        source = self.bridge.model_snapshot('alpha')
        self.assertEqual(len(source['items']), 5)
        self.assertTrue(all('content' not in item for item in source['items']))
        for text in samples:
            self.assertNoContent(text)
        with self.bridge.db() as connection:
            persisted = '\n'.join(r[0] for r in connection.execute('SELECT snapshot FROM observations'))
        self.assertNotIn('sk-', persisted)
        self.assertNotIn('synthetic-password', persisted)

    def test_directory_bound_fails_before_open_and_other_project_still_polls(self):
        for i in range(6):
            self.text(self.first / ('a%d.md' % i))
        good = self.text(self.second / 'b.md', 'SMALL_PROJECT_BODY')
        self.scope()
        self.scope('beta')
        original = walk

        def bounded(root, max_entries=4096, allowed=None):
            return original(root, max_entries=4, allowed=allowed)

        with patch('source_bridge.walk', side_effect=bounded), \
                patch('source_bridge.secure_read', wraps=secure_read) as reader:
            self.poll()
        coverage = self.bridge.status('alpha')['coverage']
        self.assertFalse(coverage['inventory_complete'])
        self.assertTrue(coverage['errors'])
        self.assertEqual([call.args[0] for call in reader.call_args_list], [good])
        self.assertIn('SMALL_PROJECT_BODY', json.dumps(self.bridge.model_snapshot('beta')))

    def test_item_limit_and_multibyte_total_content_limit(self):
        for i in range(130):
            self.text(self.first / ('a%03d.md' % i), '中' * 400)
        self.scope()
        self.poll()
        items = self.bridge.model_snapshot('alpha')['items']
        self.assertLessEqual(len(items), 128)
        self.assertLessEqual(sum(len(item.get('content', '').encode('utf-8')) for item in items),
                             source_bridge.TOTAL_LIMIT)
        coverage = self.bridge.status('alpha')['coverage']
        self.assertEqual(coverage['indexed'], 130)
        self.assertGreater(coverage['pending'], 0)

    def test_poll_is_deduplicated_without_body_receipts(self):
        marker = 'CONTENT_MUST_NOT_ENTER_RECEIPTS'
        raw = self.text(self.first / 'a.md', marker).read_bytes()
        self.scope()
        self.assertEqual(self.poll(), ['alpha'])
        before = self.bridge.status('alpha')['receipts']
        self.assertEqual(self.poll(), [])
        self.assertEqual(self.bridge.status('alpha')['receipts'], before)
        self.assertNotIn(marker, json.dumps(self.bridge.status('alpha')))
        item = self.bridge.model_snapshot('alpha')['items'][0]
        self.assertEqual(item['version'], 'sha256:' + hashlib.sha256(raw).hexdigest())
        self.assertEqual(item['verification_status'], 'UNVERIFIED')

    def test_thread_identity_duplicates_sensitive_messages_and_window_limits(self):
        self.seed_thread([('user', 'ordinary-%d' % i) for i in range(22)] +
                         [('assistant', 'password = synthetic-password')])
        row = conversation(self.home, THREAD)
        self.assertEqual(len(row['content']), 20)
        self.assertTrue(row['truncated'])
        self.assertEqual(row['filtered_sensitive_messages'], 1)
        self.assertNotIn('synthetic-password', json.dumps(row))
        self.seed_thread([('user', 'duplicate session')], folder='archived_sessions')
        with self.assertRaises(ValueError):
            conversation(self.home, THREAD)

    def test_invalid_session_payload_cannot_abort_poll_for_other_project(self):
        self.seed_thread([])
        malformed = {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                                                       'content': None}}
        log = self.home / 'sessions' / ('rollout-' + THREAD + '.jsonl')
        self.text(log, log.read_text(encoding='utf-8') + json.dumps(malformed) + '\n')
        self.text(self.second / 'b.md', 'OTHER_PROJECT_BODY')
        self.scope(folders=[], threads=[THREAD])
        self.scope('beta')
        self.poll()
        self.assertTrue(self.bridge.status('alpha')['errors'])
        self.assertIn('OTHER_PROJECT_BODY', json.dumps(self.bridge.model_snapshot('beta')))


class WorkspaceBridgeAdversarialTests(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.bind()
        self.bind('beta')
        self.bridge.workspace = self.registry

    def test_unbound_project_and_stale_binding_revision_cannot_authorize_sources(self):
        self.projects['unbound'] = {'project': {'id': 'unbound', 'workspace': str(self.first)}}
        with self.assertRaises(ValueError):
            self.scope('unbound', folders=[str(self.first)])
        with self.assertRaises(ValueError):
            self.scope(workspace_revision=0)
        self.assertFalse(self.bridge.status('alpha')['enabled'])

    def test_other_project_and_workspace_parent_cannot_be_selected(self):
        for folder in (self.second, self.workspace, self.root):
            with self.subTest(folder=str(folder)), self.assertRaises(ValueError):
                self.scope(folders=[str(folder)])
        self.assertEqual(self.bridge.index_page('alpha')['items'], [])

    def test_excluded_descendants_are_never_opened_or_indexed(self):
        forbidden = self.text(self.first / 'draft/a.md', 'EXCLUDED_BODY')
        allowed = self.text(self.first / 'draft-extra/a.md', 'ALLOWED_BODY')
        self.bind(exclusions=['draft'])
        self.scope()
        with patch('source_bridge.secure_read', wraps=secure_read) as reader:
            self.poll()
        self.assertNotIn(forbidden, [call.args[0] for call in reader.call_args_list])
        indexed = [row['reference'] for row in self.bridge.index_page('alpha')['items']]
        self.assertEqual(indexed, [str(allowed)])
        self.assertNoContent('EXCLUDED_BODY')

    def test_binding_revision_change_blocks_cached_body_and_further_reads(self):
        self.text(self.first / 'a.md', 'STALE_WORKSPACE_BODY')
        self.scope()
        self.poll()
        self.bind(exclusions=['a.md'])
        with patch('source_bridge.secure_read', side_effect=AssertionError('read on stale binding')):
            self.poll()
            self.assertNoContent('STALE_WORKSPACE_BODY')
        self.assertTrue(self.bridge.status('alpha')['workspace_blocked'])

    def test_legacy_source_scope_requires_reconsent_after_registry_attachment(self):
        self.bridge.workspace = None
        self.text(self.first / 'a.md', 'LEGACY_SCOPE_BODY')
        self.scope()
        self.poll()
        self.bridge.workspace = self.registry
        with patch('source_bridge.secure_read', side_effect=AssertionError('legacy scope read')):
            self.poll()
            self.assertNoContent('LEGACY_SCOPE_BODY')
        self.assertTrue(self.bridge.status('alpha')['workspace_blocked'])

    def test_rebind_during_read_stops_subsequent_files_and_discards_batch(self):
        self.text(self.first / 'a.md', 'BEFORE_BINDING_CHANGE')
        second = self.text(self.first / 'b.md', 'AFTER_BINDING_CHANGE')
        self.scope()
        original = secure_read
        reads = []

        def rebinding(path, *args):
            reads.append(path)
            raw = original(path, *args)
            self.bind(exclusions=['b.md'])
            return raw

        with patch('source_bridge.secure_read', side_effect=rebinding):
            self.poll()
        self.assertNotIn(second, reads)
        self.assertEqual(self.bridge.status('alpha')['observed'], [])
        self.assertEqual(self.bridge.model_snapshot('alpha')['items'], [])

    def test_revoke_during_model_snapshot_cannot_return_stale_body(self):
        self.text(self.first / 'a.md', 'SNAPSHOT_REVOKED_BODY')
        self.scope()
        self.poll()
        original = secure_read

        def revoking(*args):
            raw = original(*args)
            self.scope(enabled=False)
            return raw

        with patch('source_bridge.secure_read', side_effect=revoking):
            snapshot = self.bridge.model_snapshot('alpha')
        self.assertEqual(snapshot['items'], [], 'snapshot returned body after its authorization was revoked')

    def test_binding_change_during_model_snapshot_cannot_return_stale_body(self):
        self.text(self.first / 'a.md', 'SNAPSHOT_REBOUND_BODY')
        self.scope()
        self.poll()
        original = secure_read

        def rebinding(*args):
            raw = original(*args)
            self.bind(exclusions=['a.md'])
            return raw

        with patch('source_bridge.secure_read', side_effect=rebinding):
            snapshot = self.bridge.model_snapshot('alpha')
        self.assertEqual(snapshot['items'], [], 'snapshot returned body after workspace revision changed')


class IndexBatchAdversarialTests(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.bind()
        self.bind('beta')
        self.bridge.workspace = self.registry

    def prepare_batch(self, content='BATCH_BODY', filename='a.md'):
        path = self.text(self.first / filename, content)
        self.scope()
        self.poll()
        snapshot = self.bridge.model_snapshot('alpha')
        self.assertTrue(snapshot['batch_id'])
        return path, snapshot

    def accepted(self):
        return self.bridge.status('alpha')['coverage']['accepted_chunks']

    def test_without_ack_identical_batch_repeats_without_progress(self):
        _, snapshot = self.prepare_batch('x' * 70000)
        self.assertEqual(self.accepted(), 0)
        self.poll()
        retry = self.bridge.model_snapshot('alpha')
        self.assertEqual(retry['batch_id'], snapshot['batch_id'])
        self.assertEqual(retry['items'], snapshot['items'])
        self.assertEqual(self.bridge.index_page('alpha')['items'][0]['offset'], 0)

    def test_failed_manager_result_holds_batch_and_does_not_auto_retry(self):
        from agent_manager import Manager

        _, snapshot = self.prepare_batch('x' * 70000)
        before = copy.deepcopy(self.projects)
        calls = []

        def failing_runner(payload):
            calls.append(payload)
            raise RuntimeError('synthetic runner failure; no model was invoked')

        manager = Manager(self.data, lambda p: copy.deepcopy(self.projects[p]),
                          lambda *args: None, runner=failing_runner, debounce=0)
        manager.bridge = self.bridge
        manager.configure('alpha', dict(enabled=True, max_calls_per_day=2,
                                        consent='codex-project-records-v1'))
        manager.tick()
        self.assertEqual(len(calls), 1)
        self.assertEqual(manager.status('alpha')['jobs'][0]['state'], 'failed')
        self.assertEqual(self.accepted(), 0)
        self.poll()
        self.assertEqual(self.bridge.model_snapshot('alpha')['batch_id'], snapshot['batch_id'])
        manager.tick()
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.projects, before)

    def test_source_changed_during_successful_stub_result_holds_batch(self):
        from agent_manager import Manager

        path, _ = self.prepare_batch('OLD_INFLIGHT_BODY')
        calls = []

        def stale_runner(payload):
            calls.append(payload)
            self.text(path, 'NEW_INFLIGHT_BODY')
            return {key: 'synthetic unverified output' for key in
                    ('summary', 'changes', 'risks', 'next_step', 'human_decision')}

        manager = Manager(self.data, lambda p: copy.deepcopy(self.projects[p]),
                          lambda *args: None, runner=stale_runner, debounce=0)
        manager.bridge = self.bridge
        manager.configure('alpha', dict(enabled=True, max_calls_per_day=1,
                                        consent='codex-project-records-v1'))
        manager.tick()
        self.assertEqual(len(calls), 1)
        self.assertNotEqual(manager.status('alpha')['jobs'][0]['state'], 'succeeded')
        self.assertEqual(self.accepted(), 0)

    def test_multibyte_file_chunks_reconstruct_once_and_survive_restart(self):
        content = '中' * 23000
        _, snapshot = self.prepare_batch(content)
        chunks = []
        for _ in range(4):
            item = snapshot['items'][0]
            self.assertLessEqual(len(item['content'].encode('utf-8')), source_bridge.TOTAL_LIMIT)
            chunks.append(item['content'])
            self.bridge.accept_batch('alpha', snapshot)
            if self.bridge.status('alpha')['coverage']['pending'] == 0:
                break
            self.bridge = Bridge(self.data, self.home)
            self.bridge.workspace = self.registry
            self.poll()
            snapshot = self.bridge.model_snapshot('alpha')
        self.assertEqual(''.join(chunks), content)
        self.assertEqual(self.bridge.status('alpha')['coverage']['processed'], 1)
        self.assertEqual(self.accepted(), 2)

    def test_more_than_128_files_are_indexed_and_processed_across_batches(self):
        for i in range(130):
            self.text(self.first / ('a%03d.md' % i), 'x')
        self.scope()
        self.poll()
        first = self.bridge.model_snapshot('alpha')
        self.assertEqual(len(first['items']), 128)
        self.assertEqual(self.bridge.index_page('alpha')['total'], 130)
        self.bridge.accept_batch('alpha', first)
        self.poll()
        second = self.bridge.model_snapshot('alpha')
        self.assertEqual(len(second['items']), 2)
        self.assertTrue(set(i['id'] for i in first['items']).isdisjoint(i['id'] for i in second['items']))
        self.bridge.accept_batch('alpha', second)
        coverage = self.bridge.status('alpha')['coverage']
        self.assertEqual((coverage['processed'], coverage['pending'], coverage['accepted_chunks']), (130, 0, 130))

    def test_index_pagination_is_metadata_only_and_has_no_cross_project_rows(self):
        for i in range(5):
            self.text(self.first / ('a%d.md' % i), 'INDEX_BODY_NEVER_EXPORTED')
        self.text(self.second / 'b.md', 'BETA_INDEX_BODY')
        self.scope()
        self.scope('beta')
        self.poll()
        pages = [self.bridge.index_page('alpha', offset=offset, limit=2) for offset in (0, 2, 4)]
        rows = [row for page in pages for row in page['items']]
        self.assertEqual([page['next_offset'] for page in pages], [2, 4, None])
        self.assertEqual(len({row['reference'] for row in rows}), 5)
        self.assertTrue(all(self.first in pathlib.Path(row['reference']).parents for row in rows))
        self.assertNotIn('INDEX_BODY_NEVER_EXPORTED', json.dumps(pages))
        self.assertEqual(self.bridge.index_page('unknown')['items'], [])

    def test_pdf_oversize_and_sensitive_tail_have_explicit_unprocessed_states(self):
        self.text(self.first / 'paper.pdf', 'SYNTHETIC_NOT_A_PDF')
        oversized = self.text(self.first / 'large.md', 'x' * (2 * 1024 * 1024 + 1))
        self.text(self.first / 'tail.md', 'x' * 70000 + '\npassword = synthetic-password')
        self.scope()
        with patch('source_bridge.secure_read', wraps=secure_read) as reader:
            self.poll()
        self.assertNotIn(oversized, [call.args[0] for call in reader.call_args_list])
        states = {pathlib.Path(row['reference']).name: row['state']
                  for row in self.bridge.index_page('alpha')['items']}
        self.assertEqual(states, {'large.md': 'oversize', 'paper.pdf': 'unsupported', 'tail.md': 'blocked'})
        coverage = self.bridge.status('alpha')['coverage']
        self.assertEqual((coverage['processed'], coverage['blocked'], coverage['unsupported']), (0, 2, 1))
        self.assertNoContent('synthetic-password')

    def test_stale_revision_wrong_batch_and_cross_project_ack_do_not_advance(self):
        _, snapshot = self.prepare_batch()
        for changes in ({'batch_id': 'wrong'}, {'revision': snapshot['revision'] + 1}):
            invalid = dict(snapshot, **changes)
            self.bridge.accept_batch('alpha', invalid)
            self.assertEqual(self.accepted(), 0)
        self.bridge.accept_batch('beta', snapshot)
        self.assertEqual(self.accepted(), 0)
        self.scope(enabled=False)
        self.bridge.accept_batch('alpha', snapshot)
        self.assertEqual(self.accepted(), 0)

    def test_ack_of_nonempty_chunk_is_idempotent(self):
        _, snapshot = self.prepare_batch()
        self.bridge.accept_batch('alpha', snapshot)
        self.bridge.accept_batch('alpha', snapshot)
        self.assertEqual(self.accepted(), 1)

    def test_ack_of_empty_file_is_idempotent(self):
        _, snapshot = self.prepare_batch('')
        self.bridge.accept_batch('alpha', snapshot)
        self.bridge.accept_batch('alpha', snapshot)
        self.assertEqual(self.accepted(), 1, 'empty chunk replay incremented accepted count')

    def test_tampered_ack_cannot_skip_unread_bytes(self):
        _, snapshot = self.prepare_batch('x' * 70000)
        forged = copy.deepcopy(snapshot)
        forged['items'][0]['chunk_end'] = forged['items'][0]['file_bytes']
        forged['items'][0]['content'] = 'forged acknowledgement body'
        self.bridge.accept_batch('alpha', forged)
        self.assertEqual(self.accepted(), 0, 'batch_id did not bind the acknowledged items')
        self.assertEqual(self.bridge.index_page('alpha')['items'][0]['offset'], 0)

    def test_file_change_between_snapshot_and_ack_cannot_advance_old_version(self):
        path, snapshot = self.prepare_batch('OLD_ACK_BODY')
        self.text(path, 'NEW_ACK_BODY')
        self.bridge.accept_batch('alpha', snapshot)
        self.assertEqual(self.accepted(), 0, 'changed file acknowledged using cached index version')

    def test_workspace_change_between_snapshot_and_ack_cannot_advance(self):
        _, snapshot = self.prepare_batch()
        self.bind(exclusions=['a.md'])
        self.bridge.accept_batch('alpha', snapshot)
        self.assertEqual(self.accepted(), 0, 'old workspace revision was acknowledged')

    def test_workspace_rebind_after_canonical_validation_cannot_commit_ack(self):
        """A completed rebind in the canonical-to-commit window must invalidate ack."""
        _, snapshot = self.prepare_batch('x' * 70000)
        before = self.bridge.index_page('alpha')['items']
        original_snapshot = self.bridge.model_snapshot
        injected = []

        def rebinding_after_validation(project):
            canonical = original_snapshot(project)
            if not injected:
                self.assertEqual(canonical['batch_id'], snapshot['batch_id'])
                self.assertEqual(canonical['items'], snapshot['items'])
                # Return an authentic snapshot, but first let a separate binding
                # transaction commit. The source scope revision stays unchanged.
                injected.append(self.bind(exclusions=['a.md'])['revision'])
            return canonical

        with patch.object(self.bridge, 'model_snapshot', side_effect=rebinding_after_validation):
            self.bridge.accept_batch('alpha', snapshot)
        self.assertEqual(len(injected), 1, 'canonical-to-commit race hook did not execute')
        self.assertEqual(original_snapshot('alpha')['items'], [])
        self.assertEqual(self.accepted(), 0, 'ack committed after canonical validation was invalidated by rebind')
        self.assertEqual(self.bridge.index_page('alpha')['items'], before)
        coverage = self.bridge.status('alpha')['coverage']
        self.assertEqual((coverage['processed'], coverage['pending']), (0, 1))

    def test_file_change_after_canonical_validation_cannot_commit_ack(self):
        """A file changed after authentic canonical validation must retain its batch."""
        path, snapshot = self.prepare_batch('x' * 70000)
        before = self.bridge.index_page('alpha')['items']
        original_snapshot = self.bridge.model_snapshot
        injected = []

        def changing_after_validation(project):
            canonical = original_snapshot(project)
            if not injected:
                self.assertEqual(canonical['batch_id'], snapshot['batch_id'])
                self.assertEqual(canonical['items'], snapshot['items'])
                # Same byte count, different hash: mutate after validation and
                # before returning its authentic result to accept_batch.
                self.text(path, 'y' * 70000)
                injected.append(True)
            return canonical

        with patch.object(self.bridge, 'model_snapshot', side_effect=changing_after_validation):
            self.bridge.accept_batch('alpha', snapshot)
        self.assertEqual(injected, [True], 'canonical-to-commit race hook did not execute')
        self.assertEqual(original_snapshot('alpha')['items'], [])
        self.assertEqual(self.accepted(), 0, 'ack committed after file hash changed following canonical validation')
        self.assertEqual(self.bridge.index_page('alpha')['items'], before)
        coverage = self.bridge.status('alpha')['coverage']
        self.assertEqual((coverage['processed'], coverage['pending']), (0, 1))

    def test_registry_writer_waits_for_ack_transaction_before_rebinding(self):
        """A separate Registry writer waits while ack holds the attached DB lock."""
        _, snapshot = self.prepare_batch()
        revision = self.registry.status('alpha')['revision']
        writer_registry = Registry(self.data, lambda p: copy.deepcopy(self.projects[p]))
        original_writer_db = writer_registry.db
        original_validation = self.bridge._ack_sources_valid
        writer_attempted = threading.Event()
        writer_finished = threading.Event()
        futures = []
        checked = []

        @contextmanager
        def traced_writer_db():
            with original_writer_db() as connection:
                def trace(statement):
                    if statement.strip().upper() == 'BEGIN IMMEDIATE':
                        writer_attempted.set()
                connection.set_trace_callback(trace)
                yield connection

        def rebind_in_other_thread():
            try:
                return writer_registry.configure('alpha', dict(
                    root=str(self.workspace), relative_path='alpha', exclusions=['a.md'],
                    if_revision=revision, consent=BINDING_CONSENT))
            finally:
                writer_finished.set()

        with ThreadPoolExecutor(max_workers=1) as pool, \
                patch.object(writer_registry, 'db', side_effect=traced_writer_db):
            def validate_while_writer_waits(*args):
                if not checked:
                    checked.append(True)
                    # This hook executes after accept_batch acquires its lock.
                    # Never call configure in this thread while that lock is held.
                    futures.append(pool.submit(rebind_in_other_thread))
                    self.assertTrue(writer_attempted.wait(timeout=3), 'writer did not attempt BEGIN IMMEDIATE')
                    self.assertFalse(writer_finished.wait(timeout=0.15), 'binding writer passed the ack lock')
                    self.assertEqual(writer_registry.status('alpha')['revision'], revision)
                return original_validation(*args)

            with patch.object(self.bridge, '_ack_sources_valid', side_effect=validate_while_writer_waits):
                self.bridge.accept_batch('alpha', snapshot)
            self.assertEqual(checked, [True])
            result = futures[0].result(timeout=5)
        self.assertTrue(writer_finished.is_set())
        self.assertEqual(result['revision'], revision + 1)
        self.assertEqual(self.accepted(), 1, 'valid ack did not finish before the waiting rebind')
        self.assertEqual(self.bridge.model_snapshot('alpha')['items'], [])

    def test_file_change_after_index_advance_rolls_back_ack_transaction(self):
        """Mutation after the real ledger UPDATE is detected and rolled back."""
        path, snapshot = self.prepare_batch('x' * 70000)
        before = self.bridge.index_page('alpha')['items']
        original_accept = source_bridge.source_index.accept
        advanced_in_transaction = []

        def changing_after_update(connection, project, items):
            advanced = original_accept(connection, project, items)
            self.assertGreater(advanced, 0, 'ledger UPDATE was not reached')
            advanced_in_transaction.append(advanced)
            self.text(path, 'y' * 70000)
            return advanced

        with patch('source_bridge.source_index.accept', side_effect=changing_after_update):
            self.bridge.accept_batch('alpha', snapshot)
        self.assertEqual(advanced_in_transaction, [1])
        self.assertEqual(self.accepted(), 0, 'post-update file mutation did not roll back ack')
        self.assertEqual(self.bridge.index_page('alpha')['items'], before)
        coverage = self.bridge.status('alpha')['coverage']
        self.assertEqual((coverage['processed'], coverage['pending']), (0, 1))
        self.assertEqual(self.bridge.model_snapshot('alpha')['items'], [])

    def test_removal_after_ack_does_not_replay_last_accepted_body(self):
        path, snapshot = self.prepare_batch('REMOVED_ACCEPTED_BODY')
        self.bridge.accept_batch('alpha', snapshot)
        path.unlink()  # Only this explicitly known synthetic file is removed.
        self.poll()
        self.assertNoContent('REMOVED_ACCEPTED_BODY')
        self.assertEqual(self.bridge.status('alpha')['coverage']['removed'], 1)


if __name__ == '__main__':
    unittest.main()
