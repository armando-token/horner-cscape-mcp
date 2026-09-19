import ctypes
import ctypes.wintypes
import psutil

user32 = ctypes.windll.user32
h_default = user32.OpenDesktopW("Default", 0, False, 0x01FF)
if h_default:
    user32.SetThreadDesktop(h_default)

for p in psutil.process_iter(["pid", "name"]):
    if "cscape" in p.info["name"].lower():
        print(f"Cscape Process: PID {p.info['pid']}")

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
found = []
def cb(hwnd, _):
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    title = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, title, 512)
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    vis = user32.IsWindowVisible(hwnd)
    if "cscape" in title.value.lower() or "about" in title.value.lower() or "editor" in title.value.lower():
        print(f"PID={pid.value}, HWND=0x{hwnd:08X}, Vis={vis}, Class={cls.value}, Title='{title.value}'")
        found.append((pid.value, hwnd, vis, cls.value, title.value))
    return True

user32.EnumWindows(WNDENUMPROC(cb), 0)
if not found:
    print("No Cscape/About/Editor windows found.")
