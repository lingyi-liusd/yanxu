"""Packaging safety tests; Windows API tests only run on a real Windows host."""
import hashlib
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile
import launcher
import platform_support
import source_bridge

ROOT = Path(__file__).resolve().parents[1]


def packaging_module(name):
    spec = importlib.util.spec_from_file_location('test_beta_' + name, ROOT / 'packaging' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_sources(root, builder):
    """Deliberately synthetic integration stubs, never a document-parser PASS."""
    for name in builder.ALLOWLIST:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'# synthetic packaging fixture\n')
    for name, contents in {
            'packaging/beta_boot.py': "RESEARCH_DESK_RELEASE='2026.10.02-beta.1'\n",
            'packaging/self_check.py': '# synthetic packaging fixture\n',
            'packaging/windows_install.py': "VERSION = '2026.10.02-beta.1'\n",
            'packaging/TESTER-README.md': 'fixture guide ' + builder.VERSION,
            'vendor/README.md': 'Synthetic dependency provenance, not publisher verification',
            'document_text.py': '# synthetic document import stub\n',
            'document_worker.py': '# synthetic document import stub\n'}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding='utf-8')
    for name in builder.DOCUMENT_WHEELS:
        with zipfile.ZipFile(root / name, 'w') as stream:
            module = 'pypdf/__init__.py' if 'pypdf-' in name else 'typing_extensions.py'
            stream.writestr(module, "__version__='6.19.0'\n" if 'pypdf-' in name else '# synthetic stub\n')


def offline_receipt(builder, root):
    return {'status': 'PASS', 'kind': 'offline-installation-test', 'model_calls': 0,
            'user_sources_read': False, 'package': builder.package_identity(root)}


class PortableCase(unittest.TestCase):
    def test_windows_data_never_uses_mac_path(self):
        value = platform_support.default_data('nt', {'LOCALAPPDATA':'C:/Users/Tester/AppData/Local'}, '/not-real')
        self.assertEqual(str(value), 'C:/Users/Tester/AppData/Local/ResearchDesk')
        self.assertNotIn('Library', str(value))
        self.assertTrue(str(platform_support.default_data('nt', {}, '/fake', True)).endswith('ResearchDeskBeta'))

    def test_windows_reader_has_no_unsafe_fallback(self):
        if os.name != 'nt':
            with self.assertRaises(OSError):
                platform_support.windows_read('/etc/hosts','/',1000)

    def test_launcher_refuses_other_installation_without_spawning(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {'RESEARCH_DESK_DATA_DIR':directory}), \
             mock.patch.object(launcher,'health',return_value={'app':'research-desk','launch_id':'other'}), \
             mock.patch.object(launcher.subprocess,'Popen') as child:
            with self.assertRaisesRegex(RuntimeError,'另一份'):
                launcher.start(18765,False)
            child.assert_not_called()

    def test_source_bundle_explicit_allowlist_does_not_collect_local_state(self):
        builder = packaging_module('build_beta')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            fixture_sources(source, builder)
            (source / 'auth.json').write_text('synthetic forbidden marker')
            destination = root / 'bundle'
            with mock.patch.object(builder, 'SOURCE', source), mock.patch.object(builder, 'DOCUMENT_SHA256',
                    {name:builder.sha256(source/name) for name in builder.DOCUMENT_WHEELS}):
                builder.copy_code(destination)
            names={p.relative_to(destination).as_posix() for p in destination.rglob('*') if p.is_file()}
            self.assertEqual(names,set('app/'+name for name in builder.ALLOWLIST)|
                             {'app/vendor/README.md','beta_boot.py','self_check.py','app/AGENTS.md','README.md'})
            for name in names:
                self.assertFalse(name.endswith(('.sqlite3','.log','.bak','.jsonl')))
                self.assertNotIn('auth.json',name)
            self.assertNotIn('/Users/Developer', (destination/'app/AGENTS.md').read_text())
            self.assertIn(builder.VERSION, (destination/'beta_boot.py').read_text())
            self.assertIn('2026.10.02-beta.1', (source/'packaging/beta_boot.py').read_text())

    @unittest.skipUnless(os.name=='nt','Requires real Windows API')
    def test_windows_secure_normal_read_and_junction_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            actual=root/'actual';actual.mkdir()
            file=actual/'sample.md';file.write_bytes(b'synthetic')
            self.assertEqual(source_bridge.secure_read(file,root,1024),b'synthetic')
            junction=root/'junction'
            subprocess.run(['cmd.exe','/c','mklink','/J',str(junction),str(actual)],check=True,capture_output=True)
            with self.assertRaises(OSError):
                source_bridge.secure_read(junction/'sample.md',root,1024)

    def test_tester_readme_is_bundled_and_version_bound(self):
        spec=importlib.util.spec_from_file_location('beta_readme_builder',ROOT/'packaging/build_beta.py')
        builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        guide=(ROOT/'packaging/TESTER-README.md').read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            builder.manifest(root,'windows-x64',[])
            self.assertEqual((root/'README.md').read_bytes(),guide)
            receipt=json.loads((root/'manifest.json').read_text())
            self.assertEqual(receipt['files']['README.md'],hashlib.sha256(guide).hexdigest())
            self.assertEqual(receipt['native_execution'],'NOT_RUN')
            self.assertIn(builder.VERSION.encode(), guide)

    @unittest.skipUnless(Path('/usr/bin/ditto').exists(),'Requires macOS archive utility')
    def test_mac_archive_preserves_unicode_names_symlinks_and_guide(self):
        spec=importlib.util.spec_from_file_location('beta_mac_archive',ROOT/'packaging/build_beta.py')
        builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            bundle=root/'研序测试版.app'
            resources=bundle/'Contents/Resources';resources.mkdir(parents=True)
            (resources/'登录Codex.command').write_bytes(b'synthetic; never executed')
            (resources/'link').symlink_to('登录Codex.command')
            builder.manifest(resources, 'macos-arm64', [])
            archive=root/'test.zip'
            builder.archive_mac(bundle,archive)
            finalizer = packaging_module('finalize_beta')
            finalizer.verify_zip(archive, '研序测试版.app/Contents/Resources/',
                                 json.loads((resources/'manifest.json').read_text()))
            extracted=root/'unpacked'
            subprocess.run(['/usr/bin/ditto','-x','-k',str(archive),str(extracted)],check=True)
            self.assertEqual((extracted/'README.md').read_bytes(),(ROOT/'packaging/TESTER-README.md').read_bytes())
            installed=extracted/'研序测试版.app/Contents/Resources'
            self.assertEqual((installed/'登录Codex.command').read_bytes(),b'synthetic; never executed')
            self.assertTrue((installed/'link').is_symlink())
            self.assertEqual((installed/'link').read_bytes(),b'synthetic; never executed')


class BetaConfigurationCase(unittest.TestCase):
    """Configure against synthetic homes only; never launch or read user data."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='yanxu-beta-config-fixture-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.boot = packaging_module('beta_boot')
        self.default = self.root / 'default-beta'
        self.production = self.root / 'synthetic-production'
        self.production.mkdir()
        self.home = self.root / 'synthetic-home'
        (self.home / '.codex').mkdir(parents=True)
        for path in (self.production/'desk.sqlite3', self.production/'api-token',
                     self.home/'.codex/config.toml', self.home/'.codex/auth.json'):
            path.write_bytes(b'synthetic marker; must remain untouched')

    @contextmanager
    def configuration(self, override):
        values = {'RESEARCH_DESK_DATA_DIR':str(self.production),
                  'CODEX_HOME':str(self.home/'.codex'), 'PATH':'synthetic-original-path'}
        if override is not None:
            values['RESEARCH_DESK_BETA_DATA_DIR'] = str(override)
        with mock.patch.dict(os.environ, values, clear=True), \
             mock.patch.object(self.boot, 'ROOT', self.root/'synthetic-bundle'), \
             mock.patch.object(self.boot.Path, 'home', return_value=self.home), \
             mock.patch.object(self.boot.platform_support, 'default_data', return_value=self.default) as default, \
             mock.patch.object(self.boot.subprocess, 'Popen') as child:
            if override is None:
                os.environ.pop('RESEARCH_DESK_BETA_DATA_DIR', None)
            yield default
            child.assert_not_called()

    def assert_isolated(self, data):
        self.assertEqual(os.environ['RESEARCH_DESK_DATA_DIR'], str(data))
        self.assertEqual(os.environ['CODEX_HOME'], str(data/'codex'))
        self.assertTrue((data/'codex').is_dir())
        self.assertEqual(list((data/'codex').iterdir()), [])
        self.assertEqual(os.environ['RESEARCH_DESK_SOURCE_CODEX_HOME'], str(self.home/'.codex'))
        suffix = '.exe' if os.name == 'nt' else ''
        self.assertEqual(os.environ['RESEARCH_DESK_CODEX_BIN'],
                         str(self.root/'synthetic-bundle/runtime/codex/bin'/('codex'+suffix)))
        self.assertEqual(os.environ['RESEARCH_DESK_NODE_BIN'],
                         str(self.root/'synthetic-bundle/runtime/node'/('node'+suffix)))
        self.assertEqual(os.environ['OPEN_BROWSER'], '0')
        self.assertEqual(set(self.production.iterdir()), {self.production/'desk.sqlite3',self.production/'api-token'})
        if os.name != 'nt':
            self.assertEqual(data.stat().st_mode & 0o777, 0o700)
            self.assertEqual((data/'codex').stat().st_mode & 0o777, 0o700)

    def test_default_and_empty_override_preserve_default_beta_location(self):
        for override in (None, ''):
            with self.subTest(override=override), self.configuration(override) as default, \
                 mock.patch.object(self.boot.Path, 'read_text') as read_text, \
                 mock.patch.object(self.boot.Path, 'read_bytes') as read_bytes:
                data = self.boot.configure()
                self.assertEqual(data, self.default)
                default.assert_called_once_with(beta=True)
                self.assert_isolated(data)
                read_text.assert_not_called()
                read_bytes.assert_not_called()

    def test_explicit_override_isolates_data_codex_and_leaves_production_untouched(self):
        before = {p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        custom = self.root/'diagnostic-beta'
        with self.configuration(custom) as default, \
             mock.patch.object(self.boot.Path, 'read_text') as read_text, \
             mock.patch.object(self.boot.Path, 'read_bytes') as read_bytes:
            data = self.boot.configure()
            self.assertEqual(data, custom)
            default.assert_not_called()
            self.assert_isolated(data)
            self.assertFalse(self.default.exists())
            read_text.assert_not_called()
            read_bytes.assert_not_called()
        self.assertEqual(before, {p:p.read_bytes() for p in before})

    def test_different_diagnostic_directories_have_distinct_service_identities(self):
        identities = []
        for name in ('diagnostic-one','diagnostic-two'):
            with self.configuration(self.root/name):
                identities.append(self.boot.identity(self.boot.configure()))
        self.assertNotEqual(*identities)

    def assert_rejected(self, override):
        before = {p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with self.configuration(override) as default:
            environment = dict(os.environ)
            with self.assertRaisesRegex(ValueError, '真实绝对路径'):
                self.boot.configure()
            self.assertEqual(dict(os.environ), environment)
            default.assert_not_called()
        self.assertFalse(self.default.exists())
        self.assertEqual(before, {p:p.read_bytes() for p in before})

    def test_relative_override_is_rejected_without_creating_data(self):
        self.assert_rejected('relative-diagnostic-beta')

    def test_symlink_leaf_override_is_rejected_without_following_target(self):
        link = self.root/'linked-beta'
        link.symlink_to(self.production, target_is_directory=True)
        self.assert_rejected(link)
        self.assertFalse((self.production/'codex').exists())

    def test_symlink_parent_override_is_rejected(self):
        link = self.root/'linked-parent'
        link.symlink_to(self.production, target_is_directory=True)
        self.assert_rejected(link/'new-beta')
        self.assertFalse((self.production/'new-beta').exists())

    def test_noncanonical_dotdot_override_is_rejected(self):
        self.assert_rejected(str(self.root/'branch') + '/../new-beta')
        self.assertFalse((self.root/'new-beta').exists())

    @contextmanager
    def rejected_configuration(self, data):
        """A rejected synthetic path must not publish config or change permissions."""
        with self.configuration(data), \
             mock.patch.object(self.boot.Path, 'chmod') as chmod, \
             mock.patch.object(self.boot.os, 'fchmod', create=True) as fchmod, \
             mock.patch.object(self.boot.Path, 'read_text') as read_text, \
             mock.patch.object(self.boot.Path, 'read_bytes') as read_bytes:
            environment = dict(os.environ)
            with self.assertRaises((ValueError, OSError)):
                yield
            self.assertEqual(dict(os.environ), environment)
            chmod.assert_not_called()
            fchmod.assert_not_called()
            read_text.assert_not_called()
            read_bytes.assert_not_called()

    def test_codex_symlinks_are_rejected_before_chmod(self):
        for name in ('outside-directory', 'inside-directory', 'dangling'):
            with self.subTest(target=name):
                data = self.root / ('beta-' + name)
                data.mkdir()
                target = data/'other-login' if name == 'inside-directory' else self.root/name
                if name != 'dangling':
                    target.mkdir()
                    marker = target/'auth.json'
                    marker.write_bytes(b'synthetic auth; never adopt or modify')
                    target_mode = target.stat().st_mode
                (data/'codex').symlink_to(target, target_is_directory=True)
                data_mode = data.stat().st_mode
                with self.rejected_configuration(data):
                    self.boot.configure()
                self.assertTrue((data/'codex').is_symlink())
                self.assertEqual(data.stat().st_mode, data_mode)
                if name != 'dangling':
                    self.assertEqual(target.stat().st_mode, target_mode)
                    self.assertEqual(marker.read_bytes(), b'synthetic auth; never adopt or modify')
                else:
                    self.assertFalse(target.exists())

    def test_non_directory_codex_is_rejected_before_chmod(self):
        data = self.root/'beta-file-login'
        data.mkdir()
        login = data/'codex'
        login.write_bytes(b'synthetic non-directory')
        data_mode, login_mode = data.stat().st_mode, login.stat().st_mode
        with self.rejected_configuration(data):
            self.boot.configure()
        self.assertEqual(login.read_bytes(), b'synthetic non-directory')
        self.assertEqual(data.stat().st_mode, data_mode)
        self.assertEqual(login.stat().st_mode, login_mode)

    def test_non_directory_data_is_rejected_before_creation(self):
        data = self.root/'beta-file-root'
        data.write_bytes(b'synthetic non-directory data')
        mode = data.stat().st_mode
        with self.rejected_configuration(data):
            self.boot.configure()
        self.assertEqual(data.read_bytes(), b'synthetic non-directory data')
        self.assertEqual(data.stat().st_mode, mode)

    def test_existing_real_codex_keeps_its_synthetic_login(self):
        data = self.root/'existing-real-beta'
        login = data/'codex'
        login.mkdir(parents=True)
        marker = login/'auth.json'
        marker.write_bytes(b'synthetic existing beta login; preserve')
        with self.configuration(data), \
             mock.patch.object(self.boot.Path, 'read_text') as read_text, \
             mock.patch.object(self.boot.Path, 'read_bytes') as read_bytes:
            self.assertEqual(self.boot.configure(), data)
            self.assertEqual(os.environ['CODEX_HOME'], str(login))
            self.assertEqual(login.resolve(), login)
            read_text.assert_not_called()
            read_bytes.assert_not_called()
        self.assertEqual(marker.read_bytes(), b'synthetic existing beta login; preserve')
        if os.name != 'nt':
            self.assertEqual(data.stat().st_mode & 0o777, 0o700)
            self.assertEqual(login.stat().st_mode & 0o777, 0o700)

    def test_directory_swap_during_creation_is_rejected_before_chmod(self):
        mkdir = Path.mkdir
        for swapped in ('data', 'codex'):
            with self.subTest(swapped=swapped):
                data = self.root/('beta-create-swap-' + swapped)
                outside = self.root/('outside-create-swap-' + swapped)
                (outside/'codex').mkdir(parents=True)
                marker = outside/'auth.json'
                marker.write_bytes(b'synthetic outside marker')
                outside_modes = (outside.stat().st_mode, (outside/'codex').stat().st_mode)
                def swapping_mkdir(path, *args, **kwargs):
                    result = mkdir(path, *args, **kwargs)
                    if path == data/'codex':
                        selected = data if swapped == 'data' else data/'codex'
                        selected.rename(self.root/('saved-create-swap-' + swapped))
                        selected.symlink_to(outside, target_is_directory=True)
                    return result
                with self.rejected_configuration(data), \
                     mock.patch.object(self.boot.Path, 'mkdir', autospec=True, side_effect=swapping_mkdir):
                    self.boot.configure()
                self.assertEqual(marker.read_bytes(), b'synthetic outside marker')
                self.assertEqual(outside_modes, (outside.stat().st_mode, (outside/'codex').stat().st_mode))

    @unittest.skipIf(os.name == 'nt', 'POSIX directory-handle permission check')
    def test_codex_swap_at_permission_open_cannot_chmod_external_directory(self):
        data = self.root/'beta-open-swap'
        outside = self.root/'outside-open-swap'
        outside.mkdir()
        marker = outside/'auth.json'
        marker.write_bytes(b'synthetic outside marker')
        outside_mode = outside.stat().st_mode
        directory_open = os.open
        swapped = False
        def swapping_open(path, flags, *args, **kwargs):
            nonlocal swapped
            if path == 'codex' and not swapped:
                swapped = True
                (data/'codex').rename(self.root/'saved-open-login')
                (data/'codex').symlink_to(outside, target_is_directory=True)
            return directory_open(path, flags, *args, **kwargs)
        with self.rejected_configuration(data), \
             mock.patch.object(self.boot.os, 'open', side_effect=swapping_open):
            self.boot.configure()
        self.assertTrue(swapped)
        self.assertEqual(outside.stat().st_mode, outside_mode)
        self.assertEqual(marker.read_bytes(), b'synthetic outside marker')


class PackagingFixture:
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='yanxu-packaging-fixture-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.builder = packaging_module('build_beta')
        self.source = self.root / 'source'
        fixture_sources(self.source, self.builder)
        patch = mock.patch.object(self.builder, 'SOURCE', self.source)
        patch.start()
        self.addCleanup(patch.stop)
        pins = mock.patch.object(self.builder, 'DOCUMENT_SHA256',
                                 {name:self.builder.sha256(self.source/name) for name in self.builder.DOCUMENT_WHEELS})
        pins.start()
        self.addCleanup(pins.stop)

    def payload(self):
        root = self.root / 'payload'
        self.builder.copy_code(root)
        self.builder.manifest(root, 'macos-arm64', [])
        return root


class PackagingIntegrityCase(PackagingFixture, unittest.TestCase):
    def test_existing_build_output_rejected_before_network_or_download(self):
        output = self.root / 'old-output'
        output.mkdir()
        with mock.patch.object(sys, 'argv', ['build_beta.py','--output',str(output),'--cache',str(self.root/'cache')]), \
             mock.patch.object(self.builder, 'dependencies') as download:
            with self.assertRaisesRegex(RuntimeError, '拒绝覆盖'):
                self.builder.main()
            download.assert_not_called()

    def test_altered_wheel_fails_pinned_digest_gate(self):
        (self.source / self.builder.DOCUMENT_WHEELS[0]).write_bytes(b'changed wheel')
        with self.assertRaisesRegex(RuntimeError, 'Pinned document dependency SHA256 mismatch'):
            self.builder.copy_code(self.root / 'not-created')
        self.assertFalse((self.root / 'not-created').exists())

    def test_missing_document_integration_fails_before_any_copy(self):
        for name in ('document_text.py', 'document_worker.py') + self.builder.DOCUMENT_WHEELS:
            with self.subTest(name=name):
                path = self.source / name
                original = path.read_bytes()
                path.unlink()
                destination = self.root / 'not-created'
                with self.assertRaisesRegex(RuntimeError, 'Missing/unsafe source'):
                    self.builder.copy_code(destination)
                self.assertFalse(destination.exists())
                path.write_bytes(original)

    def test_source_change_during_copy_fails(self):
        copy = shutil.copy2
        changed = False
        def changing_copy(source, target):
            nonlocal changed
            result = copy(source, target)
            if not changed:
                changed = True
                (self.source / 'document_text.py').write_text('# source changed concurrently\n')
            return result
        with mock.patch.object(self.builder.shutil, 'copy2', side_effect=changing_copy):
            with self.assertRaisesRegex(RuntimeError, 'Source changed'):
                self.builder.copy_code(self.root / 'payload')

    def test_symlinked_vendor_parent_is_not_allowed(self):
        vendor = self.source / 'vendor'
        outside = self.root / 'outside'
        vendor.rename(outside)
        vendor.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'Missing/unsafe source'):
            self.builder.copy_code(self.root / 'payload')

    def test_stale_unlisted_code_cannot_survive_sync(self):
        root = self.root / 'payload'
        (root / 'app').mkdir(parents=True)
        (root / 'app/old_private_module.py').write_text('# stale\n')
        with self.assertRaisesRegex(RuntimeError, 'Unexpected existing app payload'):
            self.builder.copy_code(root)

    def test_package_identity_detects_post_copy_changes(self):
        root = self.payload()
        original = self.builder.package_identity(root)
        (root / 'app/document_worker.py').write_text('# changed after test\n')
        with self.assertRaisesRegex(RuntimeError, 'Manifest mismatch'):
            self.builder.package_identity(root)
        self.builder.manifest(root, 'macos-arm64', [])
        self.assertNotEqual(original, self.builder.package_identity(root))

    def test_self_check_uses_same_exact_package_identity(self):
        self_check = packaging_module('self_check')
        root = self.payload()
        self.assertEqual(self.builder.package_identity(root), self_check.package_identity(root))
        (root / 'app/document_text.py').write_text('# altered\n')
        with self.assertRaisesRegex(RuntimeError, '安装测试文件已改变'):
            self_check.package_identity(root)

    def test_document_import_probe_uses_only_packaged_fixture_stubs(self):
        self_check = packaging_module('self_check')
        root = self.payload()
        with mock.patch.object(self_check, 'ROOT', root):
            value = self_check.document_probe(sys.executable, dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), {}, False)
        self.assertEqual(value['pypdf'], '6.19.0')
        self.assertEqual(set(value['modules']), {'pypdf','typing_extensions','document_text','document_worker'})
        self.assertEqual(value['extraction'], 'NOT_RUN_FIXTURE')

    def test_missing_wheel_cannot_fall_back_to_host_dependency(self):
        self_check = packaging_module('self_check')
        root = self.payload()
        (root / 'app' / self.builder.DOCUMENT_WHEELS[0]).unlink()
        with mock.patch.object(self_check, 'ROOT', root):
            with self.assertRaises(subprocess.CalledProcessError):
                self_check.document_probe(sys.executable, dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), {}, False)

    def test_current_packaged_document_integration_extracts_only_synthetic_inputs(self):
        builder = packaging_module('build_beta')
        self_check = packaging_module('self_check')
        root = self.root / 'real-code-synthetic-documents'
        builder.copy_code(root)
        with mock.patch.object(self_check, 'ROOT', root):
            value = self_check.document_probe(sys.executable, dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), {})
        self.assertEqual(value['extraction'], 'SYNTHETIC_PDF_DOCX_AND_INVALID_PDF_PASS')
        self.assertEqual(value['pypdf'], '6.19.0')

    def test_archive_helpers_refuse_existing_outputs(self):
        destination = self.root / 'archive.zip'
        destination.write_bytes(b'keep old artifact')
        with self.assertRaises(FileExistsError):
            self.builder.archive(self.root / 'payload', destination)
        with mock.patch.object(self.builder.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, '拒绝覆盖'):
                self.builder.archive_mac(self.root / 'old.app', destination)
            run.assert_not_called()
        self.assertEqual(destination.read_bytes(), b'keep old artifact')

    def test_windows_copied_installer_gets_new_version_without_source_edit(self):
        root = self.payload()
        def sips_fixture(command, **kwargs):
            Path(command[-1]).write_bytes(b'synthetic icon')
        original = (self.source / 'packaging/windows_install.py').read_bytes()
        with mock.patch.object(self.builder.subprocess, 'run', side_effect=sips_fixture):
            self.builder.windows_files(root)
        self.assertIn(self.builder.VERSION, (root / 'windows_install.py').read_text())
        self.assertEqual((self.source / 'packaging/windows_install.py').read_bytes(), original)


class FinalizeCase(PackagingFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.finalizer = packaging_module('finalize_beta')
        self.finalizer.build = self.builder
        self.input = self.root / 'old-owned-build'
        self.mac = self.input / '研序测试版.app/Contents/Resources'
        self.windows = self.input / '研序测试版-Windows-x64'
        for root, platform in ((self.mac, 'macos-arm64'), (self.windows, 'windows-x64')):
            (root / 'app').mkdir(parents=True)
            (root / 'app/server.py').write_text('# old code\n')
            self.builder.manifest(root, platform, [])
            value = json.loads((root / 'manifest.json').read_text())
            value['release'] = self.builder.PREVIOUS_VERSION
            (root / 'manifest.json').write_text(json.dumps(value))
        info = self.input / '研序测试版.app/Contents/Info.plist'
        info.write_bytes(plistlib.dumps({'CFBundleVersion': self.builder.PREVIOUS_VERSION}))
        self.output = self.root / '研序测试版-2026.10.03-beta.2'

    def test_clone_excludes_only_app_caches_without_mutating_input(self):
        cache=self.mac/'app/__pycache__/server.cpython-313.pyc'
        cache.parent.mkdir();cache.write_bytes(b'old interpreter cache')
        secret=self.mac/'app/auth.json';secret.write_text('forbidden fixture')
        target=self.root/'cloned.app'
        self.finalizer.clone_owned_build(self.input/'研序测试版.app',target)
        copied=target/'Contents/Resources'
        self.assertTrue(cache.is_file())
        self.assertFalse((copied/'app/__pycache__').exists())
        self.assertTrue((copied/'app/auth.json').exists())
        with self.assertRaisesRegex(RuntimeError,'Unexpected existing app payload'):
            self.builder.copy_code(copied)

    def test_existing_release_output_is_never_overwritten(self):
        self.output.mkdir()
        marker = self.output / 'old.zip'
        marker.write_bytes(b'keep')
        with mock.patch.object(self.builder, 'copy_code') as copy:
            with self.assertRaisesRegex(RuntimeError, '拒绝覆盖'):
                self.finalizer.finalize(self.output, self.input, [])
            copy.assert_not_called()
        self.assertEqual(marker.read_bytes(), b'keep')

    def test_pre_copy_pass_receipt_is_rejected(self):
        report = self.root / 'old-pass.json'
        report.write_text(json.dumps(offline_receipt(self.builder, self.mac)))
        with mock.patch.object(self.finalizer.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, '旧回执不能复用'):
                self.finalizer.finalize(self.output, self.input, [], report)
            run.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_unbound_and_old_code_receipts_cannot_prove_new_copy(self):
        old = offline_receipt(self.builder, self.mac)
        self.builder.copy_code(self.mac)
        self.builder.manifest(self.mac, 'macos-arm64', [])
        for report in (old, {'status':'PASS','model_calls':0}):
            with self.subTest(report=report):
                with self.assertRaisesRegex(RuntimeError, 'does not prove'):
                    self.finalizer.check_report(self.mac, report)
        self.finalizer.check_report(self.mac, offline_receipt(self.builder, self.mac))

    def test_tampered_input_rejected_before_output_creation(self):
        (self.windows / 'app/server.py').write_text('# input altered\n')
        with self.assertRaisesRegex(RuntimeError, 'Manifest mismatch'):
            self.finalizer.finalize(self.output, self.input, [])
        self.assertFalse(self.output.exists())

    def test_exact_post_copy_probe_precedes_final_signing_and_preserves_input(self):
        snapshots = {p.relative_to(self.input).as_posix():p.read_bytes()
                     for p in self.input.rglob('*') if p.is_file()}
        calls = []
        def execute_fixture(command, **kwargs):
            if '--report' in command:
                root = Path(command[3]).parent
                self.assertEqual((root / 'app/document_worker.py').read_bytes(),
                                 (self.source / 'document_worker.py').read_bytes())
                self.assertIn(self.builder.VERSION, (root / 'beta_boot.py').read_text())
                Path(command[-1]).write_text(json.dumps(offline_receipt(self.builder, root)))
                calls.append('post-copy-offline-check')
            elif command[0]=='/usr/bin/swiftc':
                Path(command[-1]).write_bytes(b'synthetic native picker executable')
                calls.append('compile-host' if command[1].endswith('MacApp.swift') else 'compile-picker')
            else:
                self.assertEqual(command[0], '/usr/bin/codesign')
                calls.append('codesign')
        def windows_fixture(root):
            (root / 'windows_install.py').write_text('VERSION=' + repr(self.builder.VERSION))
            pe = bytearray(72); pe[:2] = b'MZ'; struct.pack_into('<I',pe,60,64)
            pe[64:68] = b'PE\0\0';struct.pack_into('<H',pe,68,0x8664)
            for name in ('runtime/python/python.exe','runtime/python/pythonw.exe','runtime/python/python313.dll',
                         'runtime/node/node.exe','runtime/codex/bin/codex.exe'):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(pe)
        def mac_archive_fixture(bundle, destination):
            self.builder.archive(bundle, destination)
        with mock.patch.object(self.finalizer.subprocess, 'run', side_effect=execute_fixture), \
             mock.patch.object(self.builder, 'windows_files', side_effect=windows_fixture), \
             mock.patch.object(self.builder, 'archive_mac', side_effect=mac_archive_fixture):
            receipt = self.finalizer.finalize(self.output, self.input, [])
        self.assertEqual(calls, ['compile-picker','compile-host','codesign','post-copy-offline-check','codesign','codesign'])
        self.assertEqual(receipt['windows_native_execution'], 'NOT_RUN')
        self.assertEqual(receipt['macos_gui'], 'NOT_RUN_FOR_THIS_RELEASE')
        self.assertEqual(receipt['tested_package']['release'], self.builder.VERSION)
        self.assertEqual(snapshots, {p.relative_to(self.input).as_posix():p.read_bytes()
                                    for p in self.input.rglob('*') if p.is_file()})

    def test_stale_report_returned_by_probe_never_reaches_signing(self):
        old = offline_receipt(self.builder, self.mac)
        def execute_fixture(command, **kwargs):
            if '--report' in command:
                Path(command[-1]).write_text(json.dumps(old))
            elif command[0]=='/usr/bin/swiftc':
                Path(command[-1]).write_bytes(b'synthetic native picker executable')
            else:
                self.assertIn('--deep', command)
        with mock.patch.object(self.finalizer.subprocess, 'run', side_effect=execute_fixture) as run, \
             mock.patch.object(self.builder, 'windows_files'):
            with self.assertRaisesRegex(RuntimeError, 'does not prove'):
                self.finalizer.finalize(self.output, self.input, [])
        self.assertEqual(run.call_count, 4)  # picker + host compile, nested sign, rejected offline report
        self.assertFalse((self.output / '打包验收.json').exists())
        self.assertFalse(list(self.output.glob('*.zip')))

    def test_report_cannot_write_into_original_build(self):
        report = self.input / 'new-report.json'
        with self.assertRaisesRegex(RuntimeError, '受测应用目录之外'):
            self.finalizer.finalize(self.output, self.input, [], report)
        self.assertFalse(report.exists())
        self.assertFalse(self.output.exists())

    def test_zip_is_compared_to_tested_manifest_not_its_own_claim(self):
        root = self.payload()
        expected = json.loads((root / 'manifest.json').read_text())
        (root / 'app/document_worker.py').write_text('# alternate code\n')
        self.builder.manifest(root, 'macos-arm64', [])
        destination = self.root / 'alternate.zip'
        self.builder.archive(root, destination)
        with self.assertRaisesRegex(RuntimeError, 'differs from tested package'):
            self.finalizer.verify_zip(destination, root.name + '/', expected)

    def test_mac_zip_symlink_escape_cannot_borrow_external_file(self):
        expected = {'files':{'link':hashlib.sha256(b'outside').hexdigest()}}
        destination = self.root / 'unsafe.zip'
        with zipfile.ZipFile(destination, 'w') as stream:
            stream.writestr('payload/manifest.json', json.dumps(expected))
            link=zipfile.ZipInfo('payload/link');link.create_system=3;link.external_attr=0o120777 << 16
            stream.writestr(link, '../outside')
            stream.writestr('outside', b'outside')
        with self.assertRaisesRegex(RuntimeError, 'Unsafe ZIP symlink'):
            self.finalizer.verify_zip(destination, 'payload/', expected)


if __name__=='__main__':
    unittest.main()
