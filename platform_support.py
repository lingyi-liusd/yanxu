"""Portable paths and fail-closed Windows file reads. No global configuration writes."""
import os
import pathlib


def default_data(platform=None, environ=None, home=None, beta=False):
    platform = platform or os.name
    environ = os.environ if environ is None else environ
    home = pathlib.Path.home() if home is None else pathlib.Path(home)
    name = 'ResearchDeskBeta' if beta else 'ResearchDesk'
    if platform == 'nt':
        return pathlib.Path(environ.get('LOCALAPPDATA') or home / 'AppData' / 'Local') / name
    import sys
    if sys.platform == 'darwin':
        return home / 'Library' / 'Application Support' / name
    return pathlib.Path(environ.get('XDG_DATA_HOME') or home / '.local' / 'share') / name


def windows_read(path, root, limit):
    """Pin all directories against rename/delete and reject junctions/reparse points."""
    if os.name != 'nt':
        raise OSError('Windows secure reader is not available on this platform')
    import ctypes
    from ctypes import wintypes
    import msvcrt
    import stat
    root = pathlib.Path(os.path.abspath(root))
    path = pathlib.Path(os.path.abspath(path))
    path.relative_to(root)
    if path == root:
        raise ValueError('Expected a file below the selected directory')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    class Info(ctypes.Structure):
        _fields_ = [('attributes', wintypes.DWORD), ('created', wintypes.FILETIME),
                    ('accessed', wintypes.FILETIME), ('written', wintypes.FILETIME),
                    ('volume', wintypes.DWORD), ('high', wintypes.DWORD), ('low', wintypes.DWORD),
                    ('links', wintypes.DWORD), ('index_high', wintypes.DWORD), ('index_low', wintypes.DWORD)]
    get_info = kernel.GetFileInformationByHandle
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Info)]
    get_info.restype = wintypes.BOOL
    handles = []
    fd = None
    try:
        directories = list(reversed(path.parent.parents)) + [path.parent]
        for directory in directories:
            handle = create(str(directory), 0x80, 3, None, 3, 0x02200000, None)
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            handles.append(handle)
            info = Info()
            if not get_info(handle, ctypes.byref(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            if info.attributes & 0x400 or not info.attributes & 0x10:
                raise OSError('拒绝符号链接或目录联接；请选择真实文件夹')
        handle = create(str(path), 0x80000000, 3, None, 3, 0x00200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        handles.append(handle)
        info = Info()
        if not get_info(handle, ctypes.byref(info)) or info.attributes & (0x400 | 0x10):
            raise OSError('拒绝重解析点或非普通文件')
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        handles.pop()
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise ValueError('文件不是普通文件或超过大小限制')
        chunks, size = [], 0
        while size <= limit:
            chunk = os.read(fd, min(65536, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        after = os.fstat(fd)
        if size > limit or (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError('文件读取期间发生变化，等待下一次观察')
        return b''.join(chunks)
    finally:
        if fd is not None:
            os.close(fd)
        for handle in reversed(handles):
            close(handle)
