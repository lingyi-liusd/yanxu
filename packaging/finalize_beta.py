"""Clone an owned beta, synchronize code, test that exact copy, then publish.

The input builds and previous desktop outputs are never modified. A fresh output
is required; failed staging remains available for diagnosis, not a PASS receipt.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import posixpath
import shutil
import subprocess
import zipfile

spec = importlib.util.spec_from_file_location('beta_builder', Path(__file__).with_name('build_beta.py'))
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def validate_input(build_root):
    bundle = build_root / '研序测试版.app'
    windows = build_root / '研序测试版-Windows-x64'
    roots = [(bundle / 'Contents/Resources', 'macos-arm64'), (windows, 'windows-x64')]
    for root, platform in roots:
        if not root.is_dir() or root.is_symlink():
            raise RuntimeError('Expected an existing unpacked beta: ' + str(root))
        value = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        if (value.get('release') not in (build.PREVIOUS_VERSION, build.VERSION)
                or value.get('platform') != platform or value.get('private_beta') is not True):
            raise RuntimeError('Not an owned private beta build: ' + str(root))
        build.package_identity(root)
    return bundle, windows


def clone_owned_build(source, destination):
    # Previously exercised app-code caches are not source or dependencies.
    # Ignore only these caches; other unexpected files still fail the allowlist.
    def ignore(directory, names):
        parts = Path(directory).relative_to(source).parts
        in_app = parts[:3] == ('Contents', 'Resources', 'app') or parts[:1] == ('app',)
        return [name for name in names if name == '__pycache__' or name.endswith('.pyc')] if in_app else []
    shutil.copytree(source, destination, symlinks=True, ignore=ignore)


def check_report(root, report):
    if (report.get('status') != 'PASS' or report.get('model_calls') != 0
            or report.get('user_sources_read') is not False
            or report.get('kind') != 'offline-installation-test'
            or report.get('package') != build.package_identity(root)):
        raise RuntimeError('Offline receipt does not prove this synchronized package')


def run_offline_check(root, destination):
    if destination.exists() or destination.is_symlink():
        raise RuntimeError('拒绝覆盖已有自检回执：' + str(destination))
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
    subprocess.run([str(root / 'runtime/python/bin/python3'), '-X', 'utf8',
                    str(root / 'self_check.py'), '--report', str(destination)],
                   env=env, check=True, timeout=180)
    report = json.loads(destination.read_text(encoding='utf-8'))
    check_report(root, report)
    return report


def verify_zip(path, prefix, expected, windows=False):
    # Compare the archive to the finalized folder, not just to its own manifest.
    with zipfile.ZipFile(path) as stream:
        def archive_name(item):
            # ditto writes UTF-8 name bytes without always setting ZIP's UTF-8
            # flag. Python then presents those bytes as CP437; keep the archive
            # intact and use the original ZipInfo object to read its contents.
            if not windows and not item.flag_bits & 0x800:
                try:
                    return item.filename.encode('cp437').decode('utf-8')
                except UnicodeError:
                    pass
            return item.filename
        names = [archive_name(item) for item in stream.infolist()]
        if len(names) != len(set(names)):
            raise RuntimeError('Duplicate ZIP entries: ' + str(path))
        entries = {archive_name(item):item for item in stream.infolist()}
        def file_bytes(name, visited=()):
            if name in visited or len(visited) >= 64 or not name.startswith(prefix):
                raise RuntimeError('Unsafe ZIP symlink: ' + name)
            item = entries[name]
            data = stream.read(item)
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                if windows:
                    raise RuntimeError('Unexpected Windows ZIP symlink: ' + name)
                target = data.decode('utf-8')
                if target.startswith('/') or '\\' in target:
                    raise RuntimeError('Unsafe ZIP symlink: ' + name)
                return file_bytes(posixpath.normpath(posixpath.join(posixpath.dirname(name), target)), visited + (name,))
            return data
        value = json.loads(file_bytes(prefix + 'manifest.json'))
        if value != expected:
            raise RuntimeError('ZIP manifest differs from tested package: ' + str(path))
        for name, digest in value['files'].items():
            if hashlib.sha256(file_bytes(prefix + name)).hexdigest() != digest:
                raise RuntimeError('ZIP checksum mismatch: ' + name)
        if windows:
            import struct
            required = ['runtime/python/python.exe', 'runtime/python/pythonw.exe', 'runtime/python/python313.dll',
                        'runtime/node/node.exe', 'runtime/codex/bin/codex.exe']
            for name in required:
                data = file_bytes(prefix + name)
                if len(data) < 64 or data[:2] != b'MZ':
                    raise RuntimeError('Not a Windows x64 executable: ' + name)
                offset = struct.unpack_from('<I', data, 60)[0]
                if (offset + 6 > len(data) or data[offset:offset+4] != b'PE\0\0'
                        or struct.unpack_from('<H', data, offset+4)[0] != 0x8664):
                    raise RuntimeError('Not a Windows x64 executable: ' + name)
        forbidden = [name for name in names if Path(name).name in
                     ('auth.json', 'api-token', 'manager.sqlite3', 'agent-connection.sqlite3', 'desk.sqlite3',
                      'source-bridge.sqlite3', 'private-ui-overrides.json', 'config.toml')
                     or name.endswith(('.jsonl', '.bak', '.log'))]
        if forbidden:
            raise RuntimeError('Private state found in archive: ' + repr(forbidden))


def finalize(output, build_root, archives, mac_report=None):
    output = output.absolute()
    build_root = build_root.resolve()
    if output.exists() or output.is_symlink():
        raise RuntimeError('拒绝覆盖现有发布目录：' + str(output))
    if output.resolve().is_relative_to(build_root) or build_root.is_relative_to(output.resolve()):
        raise RuntimeError('发布目录必须与输入构建分开')
    destination = mac_report or output / 'Mac离线安装自检.json'
    if destination.exists() or destination.is_symlink():
        raise RuntimeError('需要新的同步后自检回执，旧回执不能复用：' + str(destination))
    if (destination.resolve().is_relative_to(build_root)
            or destination.resolve().is_relative_to(output / '研序测试版.app')
            or destination.resolve().is_relative_to(output / '研序测试版-Windows-x64')):
        raise RuntimeError('自检回执必须放在输入构建和受测应用目录之外')
    original_bundle, original_windows = validate_input(build_root)
    build.source_files()
    output.mkdir(parents=True)
    bundle = output / original_bundle.name
    windows = output / original_windows.name
    clone_owned_build(original_bundle, bundle)
    clone_owned_build(original_windows, windows)
    resources = bundle / 'Contents/Resources'
    roots = [(resources, 'macos-arm64'), (windows, 'windows-x64')]
    synchronized = []
    for root, platform in roots:
        synchronized.append(build.copy_code(root))
        if platform == 'windows-x64':
            build.windows_files(root)
        else:
            build.build_folder_picker(root)
    if synchronized[0] != synchronized[1] or build.source_files() != synchronized[0]:
        raise RuntimeError('Sources changed between platform copies; no release accepted')
    # Recompile the native host: copying web/Python code cannot update menu or
    # lifecycle behavior. Keep GUI acceptance separate from compile success.
    (bundle/'Contents/MacOS').mkdir(exist_ok=True)
    subprocess.run(['/usr/bin/swiftc',str(build.SOURCE/'packaging/MacApp.swift'),'-O',
                    '-o',str(bundle/'Contents/MacOS/YanxuBeta')],check=True)
    info_path = bundle / 'Contents/Info.plist'
    with info_path.open('rb') as stream:
        info = plistlib.load(stream)
    info['CFBundleVersion'] = build.VERSION
    if build.BUNDLE_IDENTIFIER:
        info['CFBundleIdentifier'] = build.BUNDLE_IDENTIFIER
    with info_path.open('wb') as stream:
        plistlib.dump(info, stream)
    # Deep signing may rewrite nested runtime executables; their final bytes
    # must be hashed and tested after that rewrite, not before it.
    subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(bundle)], check=True)
    for root, platform in roots:
        build.manifest(root, platform, archives)
        build.package_identity(root)
    report = run_offline_check(resources, destination)
    value = json.loads((resources / 'manifest.json').read_text(encoding='utf-8'))
    value['native_execution'] = 'OFFLINE_RUNTIME_PASS; GUI_NOT_RUN_FOR_THIS_RELEASE'
    value['offline_runtime_receipt'] = report
    (resources / 'manifest.json').write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(bundle)], check=True)
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(bundle)], check=True)
    # A changed file at any later stage invalidates the exact-copy receipt.
    check_report(resources, report)
    build.archive_mac(bundle, output / '研序测试版-macOS-Apple芯片.zip')
    build.archive(windows, output / '研序测试版-Windows-x64.zip')
    for root, platform in roots:
        value = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        build.package_identity(root)
        prefix = '研序测试版.app/Contents/Resources/' if platform == 'macos-arm64' else '研序测试版-Windows-x64/'
        name = '研序测试版-macOS-Apple芯片.zip' if platform == 'macos-arm64' else '研序测试版-Windows-x64.zip'
        verify_zip(output / name, prefix, value, platform == 'windows-x64')
    if build.source_files() != synchronized[0]:
        raise RuntimeError('Sources changed during finalization; no release accepted')
    shutil.copy2(resources / 'README.md', output / 'README.md')
    sums = [build.sha256(p) + '  ' + p.name for p in sorted(output.glob('*.zip'))]
    (output / 'SHA256SUMS.txt').write_text('\n'.join(sums) + '\n', encoding='utf-8')
    receipt = {'release': build.VERSION, 'mac_offline_runtime': 'PASS', 'model_calls': 0,
               'tested_package': report['package'], 'source_sha256': synchronized[0],
               'mac_zip_checksums': 'PASS', 'windows_zip_checksums': 'PASS',
               'windows_x64_binary_headers': 'PASS', 'private_state_exclusion': 'PASS',
               'windows_native_execution': 'NOT_RUN', 'macos_gui': 'NOT_RUN_FOR_THIS_RELEASE'}
    (output / '打包验收.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print('新发布目录已生成；同步后离线自检与实际 ZIP 校验完成：' + str(output), flush=True)
    return receipt


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--build-root',type=Path,required=True,help='Existing owned unpacked betas; cloned, never updated in place')
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--mac-report',type=Path,help='New report destination; never a pre-copy PASS input')
    args=parser.parse_args()
    archives=json.loads((args.cache/'dependency-lock.json').read_text())
    finalize(args.output, args.build_root, archives, args.mac_report)


if __name__=='__main__':
    main()
