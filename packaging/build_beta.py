"""Reproducible private beta bundle: explicit source allowlist, pinned runtimes.

Use on macOS arm64. Windows archives are assembled, not claimed native-tested.
Downloads are verified against publisher checksums/npm integrity, not executed
until verification. The build never reads ResearchDesk data or ~/.codex auth.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile

SOURCE = Path(__file__).resolve().parents[1]
VERSION = '2026.10.03-beta.16'
PREVIOUS_VERSION = '2026.10.03-beta.15'
GUIDE_PATH = 'packaging/TESTER-README.md'
PREVIEW_DATA_NAME = None
BUNDLE_IDENTIFIER = None
DOCUMENT_WHEELS = ('vendor/pypdf-6.19.0-py3-none-any.whl',
                   'vendor/typing_extensions-4.15.0-py3-none-any.whl')
DOCUMENT_SHA256 = {
    DOCUMENT_WHEELS[0]: '7e5d6e730e7dae87d560a2cee218b852f6498c8be61966f3cd02ead971e48d14',
    DOCUMENT_WHEELS[1]: 'f0fa19c6845758ab08074a0cfa8b7aecb71c999ca73d62883bc25cc018c4e548'}
OPTIONAL_SOURCES = ('vendor/README.md', 'vendor/THIRD-PARTY-NOTICES.md')
ALLOWLIST = ('index.html', 'apps/shell.html', 'apps/shell.js', 'apps/shell.css', 'apps/links.js', 'app_launcher.py', 'discussion_app.py', 'radar_app.py', 'ecosystem.js','ecosystem_state.js','ecosystem_client.js', 'review_ui.js','chat_ui.js', 'ecosystem.css', 'ecosystem.py','group_chat.py', 'ecosystem_contracts.py', 'review_service.py','review_context.py','review_history.py', 'observation_service.py','result_observation.py', 'source_extractors.py', 'lineage_service.py', 'extension_contracts.py', 'source-packs/public-updates.v1.json', 'review-templates/solution-tradeoff.v1.json', 'radar_fetch.py', 'server.py', 'agent_gateway.py', 'project_backup.py',
             'agent_manager.py', 'agent_connection.py', 'registered_batches.py', 'management_runtime.py', 'project_continuity.py', 'action_contracts.py','result_review.py',
             'source_bridge.py', 'source_intake.py', 'source_index.py', 'workspace_registry.py', 'platform_support.py', 'launcher.py', 'mcp-server.js',
             'assets/yanxu-logo.png', 'assets/fonts/ChillRoundGothic-Bold.woff',
             'assets/fonts/OFL.txt', 'assets/fonts/README.txt', 'BETA-ACCEPTANCE.md',
             'document_text.py', 'document_worker.py', 'folder_picker.py', 'packaging/FolderPicker.swift', 'packaging/MacApp.swift') + DOCUMENT_WHEELS
PYTHON_MAC = 'https://github.com/astral-sh/python-build-standalone/releases/download/20261001/cpython-3.13.16+20261001-aarch64-apple-darwin-install_only_stripped.tar.gz'
PYTHON_MAC_SHA = 'd00669acb53c1b014f1fcf5eaea740d8e45c3aff4b1e0244dc0f8697fb211a82'
PYTHON_WIN = 'https://www.python.org/ftp/python/3.13.16/python-3.13.16-embed-amd64.zip'
NODE_VERSION = 'v22.23.3'
CODEX_VERSION = '0.160.0'


def fetch(url):
    with urllib.request.urlopen(url, timeout=90) as response:
        return response.read()


def download(cache, name, url, expected=None, integrity=None):
    destination = cache / name
    if not destination.exists():
        print('下载 ' + name, flush=True)
        raw = fetch(url)
    else:
        raw = destination.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if expected and digest != expected:
        raise RuntimeError('SHA256 mismatch: ' + name)
    if integrity:
        algorithm, value = integrity.split('-', 1)
        if base64.b64encode(hashlib.new(algorithm, raw).digest()).decode() != value:
            raise RuntimeError('npm integrity mismatch: ' + name)
    if not destination.exists():
        destination.write_bytes(raw)
    return {'name': name, 'url': url, 'sha256': digest, 'publisher_sha256': expected,
            'publisher_integrity': integrity, 'path': str(destination)}


def unpack(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    def check(name):
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise RuntimeError('Archive path escape: ' + name)
    if archive.suffix == '.zip':
        with zipfile.ZipFile(archive) as stream:
            for member in stream.infolist():
                check(member.filename)
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise RuntimeError('Unexpected ZIP symlink')
            stream.extractall(root)
    else:
        with tarfile.open(archive) as stream:
            for member in stream.getmembers():
                check(member.name)
                if member.issym():
                    check(str(Path(member.name).parent / member.linkname))
                elif member.islnk():
                    check(member.linkname)
                elif not (member.isfile() or member.isdir()):
                    raise RuntimeError('Unexpected archive special file')
            stream.extractall(root)


def dependencies(cache):
    checksums = fetch('https://nodejs.org/dist/' + NODE_VERSION + '/SHASUMS256.txt').decode()
    hashes = dict((name, sha) for sha, name in (line.split() for line in checksums.splitlines()))
    # Compare Python's digest to its official Sigstore bundle digest (not a full signature verification).
    python_attestation = json.loads(fetch(PYTHON_WIN + '.sigstore'))
    python_digest = base64.b64decode(python_attestation['messageSignature']['messageDigest']['digest']).hex()
    requests = [('python-mac.tar.gz', PYTHON_MAC, PYTHON_MAC_SHA, None),
                ('python-win.zip', PYTHON_WIN, python_digest, None)]
    for platform, archive in [('mac', 'darwin-arm64.tar.gz'), ('win', 'win-x64.zip')]:
        name = 'node-' + NODE_VERSION + '-' + archive
        requests.append(('node-' + platform + ('.tar.gz' if platform == 'mac' else '.zip'),
                         'https://nodejs.org/dist/' + NODE_VERSION + '/' + name, hashes[name], None))
        tag = CODEX_VERSION + ('-darwin-arm64' if platform == 'mac' else '-win32-x64')
        metadata = json.loads(fetch('https://registry.npmjs.org/@openai/codex/' + tag))
        requests.append(('codex-' + platform + '.tgz', metadata['dist']['tarball'], None, metadata['dist']['integrity']))
    with ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(lambda request: download(cache, *request), requests))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def map_sha256(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def source_files():
    names = list(ALLOWLIST) + [name for name in OPTIONAL_SOURCES if (SOURCE / name).exists()]
    names += ['packaging/beta_boot.py', 'packaging/self_check.py', GUIDE_PATH,
              'packaging/windows_install.py']
    for name in names:
        source = SOURCE / name
        if not source.is_file() or source.is_symlink() or not source.resolve().is_relative_to(SOURCE.resolve()):
            raise RuntimeError('Missing/unsafe source: ' + name)
    sources = {name: sha256(SOURCE / name) for name in names}
    for name, expected in DOCUMENT_SHA256.items():
        if sources[name] != expected:
            raise RuntimeError('Pinned document dependency SHA256 mismatch: ' + name)
    return sources


def release_text(text, pattern):
    text, count = re.subn(pattern, lambda match: match[1] + repr(VERSION), text)
    if count != 1:
        raise RuntimeError('Expected one explicit beta release field')
    return text


def copy_code(root):
    # Validate the complete allowlist before copying anything, including pending
    # document integration. Recheck it afterwards to catch concurrent source edits.
    sources = source_files()
    allowed = {'app/' + name for name in list(ALLOWLIST) + [name for name in OPTIONAL_SOURCES if name in sources]}
    allowed.add('app/AGENTS.md')
    for path in (root / 'app').rglob('*'):
        if path.is_symlink() or (path.is_file() and path.relative_to(root).as_posix() not in allowed):
            raise RuntimeError('Unexpected existing app payload: ' + str(path))
    for name in ('app', 'beta_boot.py', 'self_check.py', 'README.md'):
        if (root / name).is_symlink():
            raise RuntimeError('Unsafe synchronization target: ' + name)
    for name in list(ALLOWLIST) + [name for name in OPTIONAL_SOURCES if name in sources]:
        source = SOURCE / name
        target = root / 'app' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    (root / 'beta_boot.py').write_text(release_text(
        (SOURCE / 'packaging/beta_boot.py').read_text(encoding='utf-8'),
        r"(RESEARCH_DESK_RELEASE\s*=\s*)['\"][^'\"]+['\"]"), encoding='utf-8')
    if PREVIEW_DATA_NAME:
        boot = root / 'beta_boot.py'
        boot.write_text(boot.read_text(encoding='utf-8').replace('platform_support.default_data(beta=True)', 'platform_support.default_data(beta=True).with_name('+repr(PREVIEW_DATA_NAME)+')'), encoding='utf-8')
    shutil.copy2(SOURCE / 'packaging/self_check.py', root / 'self_check.py')
    shutil.copy2(SOURCE / GUIDE_PATH, root / 'README.md')
    (root / 'app/AGENTS.md').write_text('# 研序测试版 · Agent 规则\n\n'
        '先读取当前项目目标、最新有效状态、交接和来源版本。AI摘要是建议，不是已确认事实或用户授权。\n'
        '在页面生成项目级 MCP 配置，服务地址使用18765端口，Node使用包内绝对路径。不要手工覆盖全局Codex配置。\n'
        '工作前调用 project.get_context；只认领明确授权的Action，保留负结果、未知、适用条件、预算和未解决问题。\n'
        '分别登记交付状态、科学结果与证据等级，不因完成任务就把结论升级为通过。\n'
        '文件和对话读取默认关闭，指定范围读取与向模型发送正文须分别经人授权。\n'
        '自主管理默认关闭，按项目确认范围和总结频率后启用；有变化才总结，不限研序每日次数，Codex账户额度仍适用。失败不自动重试。\n'
        '常驻管理连接另行启用，心跳不调用模型，断线不重放工作；暂停不换执行器，项目/来源授权和预算不重置。\n'
        '工作区路径策略不是操作系统沙箱，不提供跨Agent文件写入锁。\n'
        '正文格式授权与读取、发送授权分别核对；阅读回执记录来源版本和片段处理状态，不代表理解或科学核验。\n'
        '不要自行派发其他聊天、执行实验、覆盖科学记录、改目标或读取授权范围外的文件。\n',encoding='utf-8')
    if source_files() != sources:
        raise RuntimeError('Source changed during synchronization; discard this new staging build')
    for name in list(ALLOWLIST) + [name for name in OPTIONAL_SOURCES if name in sources]:
        if sha256(root / 'app' / name) != sources[name]:
            raise RuntimeError('Synchronized source mismatch: ' + name)
    return sources


def build_folder_picker(root):
    subprocess.run(['/usr/bin/swiftc', str(SOURCE / 'packaging/FolderPicker.swift'), '-O',
                    '-target', 'arm64-apple-macos12.0', '-framework', 'AppKit',
                    '-o', str(root / 'folder-picker')], check=True)


def package_identity(root):
    """Bind offline receipts to the exact manifest file bytes, not a prior PASS."""
    value = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    for name, expected in value['files'].items():
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()) or not path.is_file() or sha256(path) != expected:
            raise RuntimeError('Manifest mismatch: ' + name)
    return {'release': value['release'], 'platform': value['platform'],
            'files_sha256': map_sha256(value['files'])}


def runtime(root, platform, archives, staging):
    extracted = staging / platform
    for dependency in archives:
        if '-' + platform + '.' in dependency['name']:
            unpack(Path(dependency['path']), extracted / dependency['name'].split('-')[0])
    target = root / 'runtime'
    target.mkdir()
    shutil.copytree(extracted / 'python' / 'python' if platform == 'mac' else extracted / 'python', target / 'python', symlinks=True)
    node_root = next((extracted / 'node').iterdir())
    (target / 'node').mkdir()
    shutil.copy2(node_root / ('bin/node' if platform == 'mac' else 'node.exe'), target / 'node' / ('node' if platform == 'mac' else 'node.exe'))
    shutil.copy2(node_root / 'LICENSE', target / 'node/LICENSE')
    package = extracted / 'codex/package'
    triplet = 'aarch64-apple-darwin' if platform == 'mac' else 'x86_64-pc-windows-msvc'
    vendor = package / 'vendor' / triplet
    shutil.copytree(vendor, target / 'codex', symlinks=True)
    # Apache license for the CLI; retained alongside bundled third-party notices.
    (target / 'codex/LICENSE').write_bytes(fetch('https://raw.githubusercontent.com/openai/codex/rust-v'+CODEX_VERSION+'/LICENSE'))
    for name in ('LICENSE', 'NOTICE', 'README.md', 'package.json'):
        if (package / name).exists():
            shutil.copy2(package / name, target / 'codex' / name)
    if platform == 'win':
        (target / 'python/python313._pth').write_text('python313.zip\n.\n../..\n../../app\nimport site\n', encoding='utf-8')
    else:
        for name in ('python/bin/python3', 'node/node', 'codex/bin/codex'):
            (target / name).chmod(0o755)


def manifest(root, platform, dependencies):
    # The tester guide belongs beside launchers and is covered by the manifest.
    shutil.copy2(SOURCE / GUIDE_PATH, root / 'README.md')
    files = {}
    for path in sorted(root.rglob('*')):
        if path.is_file() and path != root / 'manifest.json' and '__pycache__' not in path.parts:
            files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    value = {'release': VERSION, 'platform': platform, 'private_beta': True,
             'contains_user_data': False, 'sources_opt_in': True, 'ai_opt_in': True,
             'native_execution': 'NOT_RUN' if platform == 'windows-x64' else 'PENDING_TEST',
             'document_dependencies': [{'file':'app/' + name, 'sha256':digest,
                 'license_provenance':'license texts retained inside wheel dist-info/licenses; see app/vendor/README.md if present'}
                 for name,digest in DOCUMENT_SHA256.items()],
             'dependencies': [{k:v for k,v in d.items() if k != 'path'} for d in dependencies], 'files': files}
    (root / 'manifest.json').write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def windows_files(root):
    # Keep the source installer unchanged; bind its copied installation directory
    # to this release so an older beta remains recoverable.
    (root / 'windows_install.py').write_text(release_text(
        (SOURCE / 'packaging/windows_install.py').read_text(encoding='utf-8'),
        r"(?m)^(VERSION\s*=\s*)['\"][^'\"]+['\"]"), encoding='utf-8')
    for name, script, args in [('一键安装.cmd', 'windows_install.py', ''), ('打开研序.cmd', 'beta_boot.py', ''),
                               ('退出研序.cmd', 'beta_boot.py', '--stop'), ('登录AI.cmd', 'beta_boot.py', '--login')]:
        exe = 'python.exe' if name == '登录AI.cmd' else 'pythonw.exe'
        text = '@echo off\r\nset "PYTHONUTF8=1"\r\nset "PYTHONDONTWRITEBYTECODE=1"\r\n"%~dp0runtime\\python\\'+exe+'" -X utf8 "%~dp0'+script+'" '+args+'\r\n'
        (root / name).write_bytes(text.encode('ascii'))
    # ICO can contain PNG frames, supported by all target Windows releases.
    subprocess.run(['/usr/bin/sips','-z','256','256',str(SOURCE/'assets/yanxu-logo.png'),
                    '--out',str(root/'icon256.png')],check=True,stdout=subprocess.DEVNULL)
    png = (root/'icon256.png').read_bytes()
    import struct
    (root / 'yanxu.ico').write_bytes(struct.pack('<HHHBBBBHHII', 0,1,1,0,0,0,0,1,32,len(png),22) + png)
    (root/'icon256.png').unlink()
    (root / '先读我.txt').write_text('研序测试版 '+VERSION+'\nWindows 10/11 x64\n\n'
        '1. 完整解压 ZIP，不要在压缩包预览内运行。\n2. 双击“一键安装.cmd”，安装完成后自动打开，之后用桌面“研序测试版”。\n'
        '3. 无需管理员权限或另装 Python/Node。安装位置：%LOCALAPPDATA%\\ResearchDeskBeta\\Apps。\n'
        '4. 可直接双击“打开研序.cmd”免安装试用；Edge 未安装时使用默认浏览器。\n'
        '5. 浏览器关窗不会停止后台，请双击“退出研序.cmd”或桌面“退出研序测试版”，停止后才会停止后台分析。\n'
        '6. AI 默认关闭。双击“登录AI.cmd”，使用自己的账号登录，再在项目中确认 AI 发送范围和预算。\n'
        '7. 不复制账号/令牌/研究资料，不改全局 Codex 配置，不自动读取电脑或对话。\n'
        '8. 数据保存在 %LOCALAPPDATA%\\ResearchDeskBeta；删除软件文件不会自动删除数据。\n'
        '9. 此包未签名，Windows 原生运行尚未实机验证；企业策略可能阻止脚本/程序，请勿关闭安全软件。\n'
        '10. 本包用于私有内测，不含自动更新/遥测；模型调用需要网络和可用账户额度。\n', encoding='utf-8-sig')


def mac_files(bundle):
    contents = bundle / 'Contents'
    (contents / 'MacOS').mkdir()
    resources = contents / 'Resources'
    info = {'CFBundleIdentifier':'local.yanxu.researchdesk.beta', 'CFBundleName':'研序测试版',
            'CFBundleDisplayName':'研序测试版', 'CFBundleExecutable':'YanxuBeta',
            'CFBundleVersion':VERSION, 'CFBundleShortVersionString':'0.1.0',
            'CFBundlePackageType':'APPL', 'LSMinimumSystemVersion':'12.0',
            'NSHighResolutionCapable':True, 'CFBundleIconFile':'Yanxu.icns',
            'NSAppTransportSecurity':{'NSAllowsLocalNetworking':True}}
    with (contents / 'Info.plist').open('wb') as stream:
        plistlib.dump(info, stream)
    subprocess.run(['/usr/bin/swiftc', str(SOURCE / 'packaging/MacApp.swift'), '-O',
                    '-target', 'arm64-apple-macos12.0', '-framework', 'AppKit', '-framework', 'WebKit',
                    '-o', str(contents / 'MacOS/YanxuBeta')], check=True)
    build_folder_picker(resources)
    command = '#!/bin/zsh\nTASK_ROOT="${0:A:h}"\nexport PYTHONDONTWRITEBYTECODE=1\n"$TASK_ROOT/runtime/python/bin/python3" "$TASK_ROOT/beta_boot.py" --login\n'
    (resources / '登录Codex.command').write_text(command, encoding='utf-8')
    (resources / '登录Codex.command').chmod(0o755)
    iconset = contents.parent.parent / 'Yanxu.iconset'
    iconset.mkdir()
    for size in (16,32,128,256,512):
        for scale in (1,2):
            name = 'icon_'+str(size)+'x'+str(size)+('@2x' if scale==2 else '')+'.png'
            subprocess.run(['/usr/bin/sips', '-z', str(size*scale), str(size*scale),
                            str(SOURCE / 'assets/yanxu-logo.png'), '--out', str(iconset / name)], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(['/usr/bin/iconutil','-c','icns',str(iconset),'-o',str(resources/'Yanxu.icns')],check=True)
    shutil.rmtree(iconset)
    subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(bundle)],check=True)


def archive(root, path):
    with zipfile.ZipFile(path,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as stream:
        for item in sorted(root.rglob('*')):
            if item.is_file():
                stream.write(item, str(Path(root.name) / item.relative_to(root)))


def archive_mac(bundle, path):
    # Keep Apple's archive writer for the entire ZIP. Appending with Python's
    # zipfile rewrites ditto's Unicode central-directory names incorrectly.
    if path.exists() or path.is_symlink():
        raise RuntimeError('拒绝覆盖现有压缩包：' + str(path))
    with tempfile.TemporaryDirectory(prefix='yanxu-mac-package-') as directory:
        staging=Path(directory)
        shutil.copytree(bundle,staging/bundle.name,symlinks=True)
        guide = bundle / 'Contents/Resources/README.md'
        shutil.copy2(guide if guide.is_file() else SOURCE/GUIDE_PATH,staging/'README.md')
        subprocess.run(['/usr/bin/ditto','-c','-k','--sequesterRsrc',str(staging),str(path)],check=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--download-only',action='store_true')
    args=parser.parse_args()
    if not args.download_only and (args.output.exists() or args.output.is_symlink()):
        raise RuntimeError('拒绝覆盖现有发布目录：'+str(args.output))
    if not args.download_only:
        source_files()  # fail before downloading runtimes if integration is incomplete
    args.cache.mkdir(parents=True,exist_ok=True)
    archives=dependencies(args.cache)
    (args.cache/'dependency-lock.json').write_text(json.dumps(archives,indent=2),encoding='utf-8')
    if args.download_only:
        print('依赖已校验并缓存',flush=True);return
    args.output.mkdir(parents=True)
    staging=args.output/'build-staging'
    bundle=args.output/'研序测试版.app'
    resources=bundle/'Contents/Resources'
    resources.mkdir(parents=True)
    mac_sources=copy_code(resources)
    runtime(resources,'mac',archives,staging);mac_files(bundle)
    # Nested signatures can change executable bytes. Freeze those before taking
    # file hashes; the final outer signature updates only bundle CodeResources.
    subprocess.run(['/usr/bin/codesign','--force','--deep','--sign','-',str(bundle)],check=True)
    manifest(resources,'macos-arm64',archives)
    subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(bundle)],check=True)
    package_identity(resources)
    windows=args.output/'研序测试版-Windows-x64'
    windows.mkdir()
    windows_sources=copy_code(windows)
    runtime(windows,'win',archives,staging);windows_files(windows)
    manifest(windows,'windows-x64',archives)
    if mac_sources != windows_sources or source_files() != mac_sources:
        raise RuntimeError('Sources changed between platform copies; no release accepted')
    archive_mac(bundle,args.output/'研序测试版-macOS-Apple芯片.zip')
    archive(windows,args.output/'研序测试版-Windows-x64.zip')
    shutil.copy2(SOURCE/GUIDE_PATH,args.output/'README.md')
    shutil.rmtree(staging)
    (args.output/'使用说明.txt').write_text('研序 '+VERSION+' · 私有内测\n\n'
        'Mac：Apple 芯片 macOS 12+，双击“研序测试版.app”；可拖入“应用程序”。退出应用会停止该版本后台。\n'
        'Windows：Win10/11 x64，解压 Windows ZIP 后双击“一键安装.cmd”，之后从桌面打开。\n'
        '所有运行依赖已包含；正常启动离线可用。AI 需联网、本人登录，并按项目明确授权。\n'
        '只带应用代码，不带现有研究项目、账户凭证、资料或自动管理授权。\n'
        '测试版使用独立 ResearchDeskBeta 数据目录和18765端口，不修改正式研序数据或全局Codex配置。\n'
        '登录入口：Mac顶部菜单“登录 Codex（仅测试版）”；Win桌面“登录研序测试版AI”。\n'
        'macOS 为本地 ad-hoc 签名，未公证；其他Mac首次打开可能需在系统隐私与安全中确认来源。\n'
        'Windows 包已适配并检查结构，但未在真实 Windows 机器上运行验收；不是正式发行版。\n'
        '不要用关键项目作为首次测试。功能/隐私限制及验收方法见包内 app/BETA-ACCEPTANCE.md。\n',encoding='utf-8-sig')
    sums=[]
    for file in args.output.glob('*.zip'):
        sums.append(hashlib.sha256(file.read_bytes()).hexdigest()+'  '+file.name)
    (args.output/'SHA256SUMS.txt').write_text('\n'.join(sums)+'\n',encoding='utf-8')
    print('构建完成：'+str(args.output),flush=True)


if __name__=='__main__':
    main()
