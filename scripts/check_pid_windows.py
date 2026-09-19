import ctypes
import ctypes.wintypes
import psutil

user32 = ctypes.windll.user32
h_default = user32.OpenDesktopW("Default", 0, False, 0x01FF)
if h_default:
    user32.SetThreadDesktop(h_default)

import sys
target_pid = int(sys.argv[1]) if len(sys.argv) > 1 else None
cscape_pids = set()
if target_pid:
    cscape_pids.add(target_pid)
else:
    for p in psutil.process_iter(["pid", "name"]):
        if p.info["name"] and "cscape" in p.info["name"].lower():
            cscape_pids.add(p.info["pid"])

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
def cb(hwnd, _):
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value in cscape_pids:
        title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, 512)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        vis = user32.IsWindowVisible(hwnd)
        print(f"PID: {pid.value}, HWND: 0x{hwnd:08X} ({hwnd}), Vis: {vis}, Class: {cls.value}, Title: '{title.value}'")
    return True

user32.EnumWindows(WNDENUMPROC(cb), 0)

