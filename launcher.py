#!/usr/bin/env python3
"""Start or reuse the local desk; no project data is modified by the launcher."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser
import platform_support

ROOT = Path(__file__).resolve().parent

def health(url):
    try:
        with urllib.request.urlopen(url + 'healthz', timeout=1) as response:
            value = json.load(response)
            return value if value.get('app') == 'research-desk' else None
    except (OSError, ValueError):
        return None

def healthy(url, identity=None):
    value = health(url)
    return bool(value and (identity is None or value.get('launch_id') == identity))

@contextmanager
def exclusive_lock(path):
    with path.open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0, 2)
            if lock.tell() == 0:
                lock.write(b'0'); lock.flush()
            deadline = time.monotonic() + 20
            while True:
                try:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError('另一次启动尚未完成，请稍后重试')
                    time.sleep(.1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            yield

def start(port=8765, open_browser=True):
    if not 1024 <= port <= 65535:
        raise ValueError('端口必须在1024–65535之间')
    os.umask(0o077)
    data = Path(os.environ.get('RESEARCH_DESK_DATA_DIR') or platform_support.default_data()).resolve()
    data.mkdir(parents=True, exist_ok=True)
    url = 'http://127.0.0.1:' + str(port) + '/'
    identity = hashlib.sha256((str(data) + '\n' + str(ROOT)).encode()).hexdigest()
    with exclusive_lock(data / 'launcher.lock'):
        existing = health(url)
        if existing and existing.get('launch_id') != identity:
            raise RuntimeError('端口正由另一份研序占用，请先退出旧版本；不会连接或停止其他实例。')
        if not healthy(url, identity):
            env = os.environ.copy()
            env.update(PORT=str(port), OPEN_BROWSER='0', RESEARCH_DESK_DATA_DIR=str(data), RESEARCH_DESK_LAUNCH_ID=identity)
            python = Path(sys.executable)
            if os.name == 'nt' and python.name.lower() == 'pythonw.exe':
                python = python.with_name('python.exe')
            with (data / 'server.log').open('a', encoding='utf-8') as log:
                child = subprocess.Popen([str(python), '-X', 'utf8', str(ROOT / 'server.py')], cwd=ROOT, env=env,
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True,
                    start_new_session=os.name != 'nt',
                    creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == 'nt' else 0)
            deadline = time.monotonic() + 15
            while not healthy(url, identity):
                if child.poll() is not None or time.monotonic() >= deadline:
                    if child.poll() is None:
                        child.terminate()
                    raise RuntimeError('研序启动失败；日志位于 ' + str(data / 'server.log') + '。请检查端口占用。')
                time.sleep(.15)
    if open_browser and not webbrowser.open(url):
        raise RuntimeError('服务已启动，请手动打开 ' + url)
    print('研序可用：' + url)
    return 0

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-open', action='store_true')
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', '8765')))
    args = parser.parse_args()
    try:
        raise SystemExit(start(args.port, not args.no_open))
    except (OSError, RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
