import ctypes
import ctypes.wintypes
import psutil

user32 = ctypes.windll.user32
user32.OpenDesktopW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
user32.OpenDesktopW.restype = ctypes.c_void_p
user32.SetThreadDesktop.argtypes = [ctypes.c_void_p]
user32.SetThreadDesktop.restype = ctypes.c_int
h_default = user32.OpenDesktopW("Default", 0, False, 0x01FF)
user32.SetThreadDesktop(h_default)
count = 0
found = 0

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
DESKTOPS = ["exebox-4UYOMYCLSY7IRCSVX4UOYYRGR2", "exebox-4HQH2O3BWDBLEAPYCRHZZOBYPF", "Default"]
user32.OpenDesktopW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
user32.OpenDesktopW.restype = ctypes.c_void_p
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
user32.EnumDesktopWindows.argtypes = [ctypes.c_void_p, WNDENUMPROC, ctypes.c_void_p]
user32.EnumDesktopWindows.restype = ctypes.c_int

cscape_pids = set()
for p in psutil.process_iter(["pid", "name"]):
    if p.info["name"] and "cscape" in p.info["name"].lower():
        cscape_pids.add(p.info["pid"])
print("Found Cscape PIDs:", cscape_pids)

for dname in DESKTOPS:
    hd = user32.OpenDesktopW(dname, 0, False, 0x01FF)
    if not hd:
        print(f"Could not open desktop {dname}")
        continue
    matches = []
    def make_cb(desk_matches):
        def cb(hwnd, _):
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in cscape_pids:
                title = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, title, 512)
                cls = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls, 256)
                vis = user32.IsWindowVisible(hwnd)
                desk_matches.append((pid.value, hwnd, vis, cls.value, title.value))
            return 1
        return WNDENUMPROC(cb)
    
    cb_func = make_cb(matches)
    user32.EnumDesktopWindows(hd, cb_func, 0)
    print(f"Desktop {dname}: found {len(matches)} windows")
    for pid, hwnd, vis, cls, title in matches:
        print(f"  PID={pid} HWND=0x{hwnd:08X} Vis={vis} Class={cls} Title='{title}'")
