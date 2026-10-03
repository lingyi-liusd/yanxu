"""Per-user offline install. No admin, PATH changes, or Codex global writes."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
VERSION = '2026.10.02-beta.1'


def verify(root, manifest):
    for name, expected in manifest['files'].items():
        path = root / name
        if not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError('安装包文件缺失或已改变：' + name)


def main():
    if os.name != 'nt':
        raise RuntimeError('此安装入口仅用于 Windows 10/11 x64')
    if os.environ.get('PROCESSOR_ARCHITECTURE', '').upper() not in ('AMD64', 'ARM64') and not os.environ.get('PROCESSOR_ARCHITEW6432'):
        raise RuntimeError('不支持32位 Windows，请使用64位系统')
    manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    verify(ROOT, manifest)
    # Test native Windows runtimes and an isolated empty app before installing.
    report = Path(os.environ['LOCALAPPDATA']) / 'ResearchDeskBeta/install-selftest.json'
    result = subprocess.run([str(ROOT/'runtime/python/python.exe'), '-X', 'utf8', str(ROOT/'self_check.py'),
                             '--report',str(report)],creationflags=subprocess.CREATE_NO_WINDOW,timeout=150)
    if result.returncode:
        raise RuntimeError('安装自检未通过，未覆盖现有应用。请查看 '+str(report))
    parent = Path(os.environ['LOCALAPPDATA']) / 'ResearchDeskBeta' / 'Apps'
    target = parent / VERSION
    if target.exists():
        verify(target, manifest)  # do not silently overwrite another installation
    else:
        parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ROOT, target)
        verify(target, manifest)
    env = os.environ.copy()
    env['YANXU_INSTALL_DIR'] = str(target)
    # Ask Windows for Desktop (supports redirected/OneDrive desktops).
    script = '''$ErrorActionPreference = 'Stop'
$root = $env:YANXU_INSTALL_DIR
$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$names = @('研序测试版', '退出研序测试版', '登录研序测试版AI')
$flags = @('', '--stop', '--login')
for ($i=0; $i -lt $names.Count; $i++) {
  $file = Join-Path $desktop ($names[$i]+'.lnk')
  $python = Join-Path $root 'runtime\\python\\pythonw.exe'
  if ($i -eq 2) { $python = Join-Path $root 'runtime\\python\\python.exe' }
  if (Test-Path -LiteralPath $file) {
    $old = $shell.CreateShortcut($file)
    if ($old.TargetPath -ne $python) { throw '桌面已有同名快捷方式，未覆盖；请先重命名旧快捷方式' }
  }
  $link = $shell.CreateShortcut($file)
  $link.TargetPath = $python
  $link.Arguments = '-X utf8 "'+(Join-Path $root 'beta_boot.py')+'" '+$flags[$i]
  $link.WorkingDirectory = $root
  $link.IconLocation = (Join-Path $root 'yanxu.ico')+',0'
  $link.Description = '研序独立测试版，不修改正式数据或 Codex 配置'
  $link.Save()
}
'''
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            env=env, capture_output=True, text=True, encoding='utf-8', errors='replace',
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError('文件已安装，但快捷方式创建失败：' + result.stderr + '\n可双击安装目录的打开研序.cmd')
    ctypes.windll.user32.MessageBoxW(None,
        '安装完成。桌面已生成“研序测试版”。\nPython、Node、Codex CLI 已包含，无需另装。\nAI 需本人登录并按项目授权，默认关闭。',
        '研序测试版', 0x40)
    subprocess.Popen([str(target / 'runtime/python/pythonw.exe'), '-X', 'utf8', str(target / 'beta_boot.py')],
                     cwd=target, creationflags=subprocess.CREATE_NO_WINDOW)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        if os.name == 'nt':
            ctypes.windll.user32.MessageBoxW(None, str(error), '研序安装未完成', 0x10)
        else:
            print(str(error), file=sys.stderr)
        sys.exit(1)
