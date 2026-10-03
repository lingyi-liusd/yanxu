"""Human-only folder dialog. No traversal, persistence, or source authorization."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

_LOCK = threading.Lock()


def choose():
    if not _LOCK.acquire(blocking=False):
        raise ValueError('文件夹选择器已打开，请先完成或取消')
    try:
        if sys.platform == 'darwin':
            # The executable is built by us, never supplied in a request body.
            helper = Path(os.environ.get('RESEARCH_DESK_FOLDER_PICKER',
                          str(Path(__file__).resolve().parent.parent / 'folder-picker')))
            if not helper.is_file() or helper.is_symlink():
                raise ValueError('本机选择器不可用，请在高级设置粘贴目录路径')
            command = [str(helper)]
        elif sys.platform == 'win32':
            command = [sys.executable, str(Path(__file__).resolve()), '--windows-dialog']
        else:
            raise ValueError('此环境不支持本机选择器，请在高级设置粘贴目录路径')
        try:
            reply = subprocess.run(command, capture_output=True, text=True,
                                   encoding='utf-8', timeout=180, check=True)
        except subprocess.TimeoutExpired:
            raise ValueError('选择器已超时关闭；未改变目录或授权') from None
        except (OSError, subprocess.CalledProcessError):
            raise ValueError('无法打开本机选择器，请在高级设置粘贴目录路径') from None
        value = json.loads(reply.stdout)
        if value.get('cancelled') is True:
            return {'cancelled': True}
        path = value.get('path')
        if not isinstance(path, str) or not path or len(path) > 4096 or '\x00' in path or '\n' in path or '\r' in path or not Path(path).is_absolute():
            raise ValueError('选择器没有返回有效目录；未改变授权')
        return {'cancelled': False, 'path': path}
    finally:
        _LOCK.release()


def windows_dialog():
    # A separate process owns the native dialog and COM apartment; timeout kills
    # only this helper. Shell32 returns a path, not file contents or permissions.
    import ctypes
    from ctypes import wintypes
    ole = ctypes.OleDLL('ole32')
    shell = ctypes.WinDLL('shell32')
    class BrowseInfo(ctypes.Structure):
        _fields_ = [('hwndOwner', wintypes.HWND), ('pidlRoot', ctypes.c_void_p),
                    ('pszDisplayName', wintypes.LPWSTR), ('lpszTitle', wintypes.LPCWSTR),
                    ('ulFlags', wintypes.UINT), ('lpfn', ctypes.c_void_p),
                    ('lParam', ctypes.c_ssize_t), ('iImage', ctypes.c_int)]
    shell.SHBrowseForFolderW.argtypes = [ctypes.POINTER(BrowseInfo)]
    shell.SHBrowseForFolderW.restype = ctypes.c_void_p
    shell.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
    shell.SHGetPathFromIDListW.restype = wintypes.BOOL
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.OleInitialize.argtypes = [ctypes.c_void_p]
    initialized = ole.OleInitialize(None)
    if initialized not in (0, 1):
        raise RuntimeError('COM initialization failed')
    try:
        display = ctypes.create_unicode_buffer(260)
        info = BrowseInfo(None, None, display, '研序 · 选择项目资料目录 / Choose project folder',
                          0x0001 | 0x0040 | 0x0200, None, 0, 0)
        pidl = shell.SHBrowseForFolderW(ctypes.byref(info))
        if not pidl:
            return {'cancelled': True}
        try:
            path = ctypes.create_unicode_buffer(260)
            if not shell.SHGetPathFromIDListW(pidl, path):
                raise RuntimeError('Not a file-system folder')
            return {'path': path.value, 'cancelled': False}
        finally:
            ole.CoTaskMemFree(pidl)
    finally:
        ole.OleUninitialize()


if __name__ == '__main__':
    if sys.platform != 'win32' or sys.argv[1:] != ['--windows-dialog']:
        raise SystemExit('Native Windows helper only')
    print(json.dumps(windows_dialog(), ensure_ascii=True))
