# Foreground-window + idle detection (Win32 via ctypes) - same approach as dashboard.py.
import ctypes
import os
import re
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.GetTickCount64.restype = ctypes.c_ulonglong

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
user32.GetLastInputInfo.restype = wintypes.BOOL


def get_idle_seconds():
    try:
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not user32.GetLastInputInfo(ctypes.byref(lii)):
            return 0.0
        return max(0.0, (kernel32.GetTickCount64() - lii.dwTime) / 1000.0)
    except Exception:
        return 0.0


def get_active_window_info():
    """{"path", "name", "title"} for the focused window's program, or None."""
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None

        length = user32.GetWindowTextLengthW(hwnd)
        title_buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buf, length + 1)

        hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not hproc:
            return None
        try:
            size = wintypes.DWORD(1024)
            path_buf = ctypes.create_unicode_buffer(size.value)
            ok = kernel32.QueryFullProcessImageNameW(hproc, 0, path_buf, ctypes.byref(size))
            if not ok:
                return None
            path = path_buf.value
        finally:
            kernel32.CloseHandle(hproc)

        return {"path": path, "name": os.path.basename(path), "title": title_buf.value}
    except Exception:
        return None


def friendly_name(exe_name):
    stem = exe_name[:-4] if exe_name.lower().endswith(".exe") else exe_name
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", stem).replace("_", " ").replace("-", " ").strip()
    return spaced.title() if spaced.islower() else spaced
