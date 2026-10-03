"""Entry point for the bundled beta; never adopts production tokens or settings."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import shlex
import tempfile
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'app'))
import launcher
import platform_support


def _beta_directory(path, must_exist=False):
    """Validate both the selected root and the private login directory."""
    message = '测试版数据目录及独立Codex目录必须是真实绝对路径的目录，不允许符号链接或非目录'
    if not path.is_absolute() or path.is_symlink() or path.resolve() != path:
        raise ValueError(message)
    try:
        info = path.lstat()
    except FileNotFoundError:
        if must_exist:
            raise ValueError(message) from None
        return None
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError(message)
    return info


def _private_beta_permissions(data, codex_home):
    # Revalidate after creation and before changing permissions. On POSIX, pin
    # both directories without following links so a swapped path cannot chmod
    # an outside login directory. This is not an OS sandbox.
    expected = (_beta_directory(data, True), _beta_directory(codex_home, True))
    if os.name == 'nt':
        return
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    data_fd = os.open(data, flags)
    try:
        codex_fd = os.open('codex', flags, dir_fd=data_fd)
        try:
            for path, before, handle in zip((data, codex_home), expected, (data_fd, codex_fd)):
                current = _beta_directory(path, True)
                pinned = os.fstat(handle)
                identity = (before.st_dev, before.st_ino)
                if identity != (current.st_dev, current.st_ino) or identity != (pinned.st_dev, pinned.st_ino):
                    raise ValueError('测试版数据目录或独立Codex目录在配置期间发生变化')
            os.fchmod(data_fd, 0o700)
            os.fchmod(codex_fd, 0o700)
        finally:
            os.close(codex_fd)
    finally:
        os.close(data_fd)


def configure():
    override=os.environ.get('RESEARCH_DESK_BETA_DATA_DIR')
    data = Path(override) if override else platform_support.default_data(beta=True)
    codex_home = data / 'codex'
    _beta_directory(data)
    _beta_directory(codex_home)
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    _beta_directory(data, True)
    codex_home.mkdir(mode=0o700, exist_ok=True)
    _private_beta_permissions(data, codex_home)
    runtime = ROOT / 'runtime'
    suffix = '.exe' if os.name == 'nt' else ''
    # Always separate the login used for beta AI from the user's desktop Codex config.
    os.environ.update(RESEARCH_DESK_DATA_DIR=str(data), CODEX_HOME=str(codex_home),
                      RESEARCH_DESK_SOURCE_CODEX_HOME=str(Path.home() / '.codex'),
                      RESEARCH_DESK_CODEX_BIN=str(runtime / 'codex/bin' / ('codex' + suffix)),
                      RESEARCH_DESK_NODE_BIN=str(runtime / 'node' / ('node' + suffix)),
                      RESEARCH_DESK_RELEASE='2026.10.02-beta.1', OPEN_BROWSER='0',
                      PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    os.environ['PATH'] = os.pathsep.join([str(runtime / 'node'), str(runtime / 'codex/bin'),
                                         str(runtime / 'codex/codex-path'), os.environ.get('PATH', '')])
    # This setting affects only the isolated beta login, not ~/.codex/config.toml.
    return data


def identity(data):
    return hashlib.sha256((str(data.resolve()) + '\n' + str((ROOT / 'app').resolve())).encode()).hexdigest()


def login_window(data):
    """Terminal does not inherit a running native app's selected profile."""
    if sys.platform != 'darwin':
        raise RuntimeError('原生登录窗口仅适用于 macOS')
    folder = Path(tempfile.mkdtemp(prefix='yanxu-beta-login-'))
    command = folder / '登录当前研序测试空间.command'
    args = ['env', 'RESEARCH_DESK_BETA_DATA_DIR='+str(data),
            'PYTHONDONTWRITEBYTECODE=1',sys.executable,str(ROOT/'beta_boot.py'),'--login']
    command.write_text('#!/bin/zsh\nexec '+shlex.join(args)+'\n',encoding='utf-8')
    command.chmod(0o700)
    subprocess.run(['/usr/bin/open', str(command)],check=True)
    return 0


def background_setting(data, enabled=None):
    """Own-profile preference only; never starts a service or authorizes AI."""
    target = data / 'native-lifecycle.json'
    if target.is_symlink():
        raise RuntimeError('后台设置不能是符号链接')
    current = False
    if target.exists():
        if not target.is_file() or target.stat().st_size > 4096:
            raise RuntimeError('后台设置文件无效')
        value = json.loads(target.read_text(encoding='utf-8'))
        if not isinstance(value,dict) or set(value) != {'keep_running_after_window_close'} or type(value['keep_running_after_window_close']) is not bool:
            raise RuntimeError('后台设置无效，请检查当前测试空间')
        current = value['keep_running_after_window_close']
    if enabled is not None:
        if type(enabled) is not bool:
            raise ValueError('后台设置必须为布尔值')
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=data,
                                         prefix='.native-lifecycle-',delete=False) as stream:
            temp = Path(stream.name)
            json.dump({'keep_running_after_window_close':enabled},stream)
        try:
            temp.chmod(0o600)
            os.replace(temp,target)
        finally:
            if temp.exists():temp.unlink()
        current = enabled
    return {'keep_running_after_window_close':current}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-open', action='store_true')
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--login', action='store_true')
    parser.add_argument('--login-window', action='store_true')
    parser.add_argument('--show-data', action='store_true')
    lifecycle = parser.add_mutually_exclusive_group()
    lifecycle.add_argument('--background-state', action='store_true')
    lifecycle.add_argument('--background-on', action='store_true')
    lifecycle.add_argument('--background-off', action='store_true')
    parser.add_argument('--port', type=int, default=18765)
    args = parser.parse_args()
    data = configure()
    if args.background_state or args.background_on or args.background_off:
        setting = background_setting(data,None if args.background_state else args.background_on)
        print(json.dumps(setting))
        return 0
    if args.login_window:
        return login_window(data)
    if args.show_data:
        if sys.platform != 'darwin':
            raise RuntimeError('原生数据目录入口仅适用于 macOS')
        subprocess.run(['/usr/bin/open',str(data)],check=True)
        return 0
    if args.login:
        return subprocess.call([os.environ['RESEARCH_DESK_CODEX_BIN'], '-c',
                                'cli_auth_credentials_store="file"', 'login'])
    url = 'http://127.0.0.1:' + str(args.port) + '/'
    if args.stop:
        current = launcher.health(url)
        if not current:
            return 0
        if current.get('launch_id') != identity(data):
            raise RuntimeError('不是当前测试版的服务，不会停止它')
        if os.name == 'nt':
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel.OpenProcess(1, False, current['pid'])
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if not kernel.TerminateProcess(handle, 0):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                kernel.CloseHandle(handle)
        else:
            os.kill(current['pid'], signal.SIGTERM)
        return 0
    if os.name == 'nt' and not args.no_open:
        result = launcher.start(args.port, False)
        candidates = [Path(os.environ.get(key,'')) / 'Microsoft/Edge/Application/msedge.exe'
                      for key in ('PROGRAMFILES(X86)', 'PROGRAMFILES', 'LOCALAPPDATA') if os.environ.get(key)]
        edge = next((path for path in candidates if path.is_file()), None)
        if edge:
            subprocess.Popen([str(edge), '--app='+url, '--user-data-dir='+str(data/'edge-profile'), '--no-first-run'],
                             creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            import webbrowser
            if not webbrowser.open(url):
                raise RuntimeError('请手动打开 '+url)
        return result
    return launcher.start(args.port, not args.no_open)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        if os.name == 'nt':
            ctypes.windll.user32.MessageBoxW(None, str(error), '研序测试版 · 未能启动', 0x10)
        else:
            print(str(error), file=sys.stderr)
        raise SystemExit(1)
