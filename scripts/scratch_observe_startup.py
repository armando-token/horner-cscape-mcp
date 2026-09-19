import ctypes
import ctypes.wintypes
import time
from pathlib import Path

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

CSCAPE_EXE = Path(r"C:\Program Files (x86)\Cscape 10.2\Cscape.exe")
CSP_FILE = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\projects\TankLevel_P4_REDO\TankLevel_P4_REDO.csp")

hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
if hd:
    user32.SetThreadDesktop(hd)

class STARTUPINFO(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.wintypes.DWORD),
        ("lpReserved", ctypes.c_wchar_p),
        ("lpDesktop", ctypes.c_wchar_p),
        ("lpTitle", ctypes.c_wchar_p),
        ("dwX", ctypes.wintypes.DWORD),
        ("dwY", ctypes.wintypes.DWORD),
        ("dwXSize", ctypes.wintypes.DWORD),
        ("dwYSize", ctypes.wintypes.DWORD),
        ("dwXCountChars", ctypes.wintypes.DWORD),
        ("dwYCountChars", ctypes.wintypes.DWORD),
        ("dwFillAttribute", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("wShowWindow", ctypes.wintypes.WORD),
        ("cbReserved2", ctypes.wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", ctypes.wintypes.HANDLE),
        ("hStdOutput", ctypes.wintypes.HANDLE),
        ("hStdError", ctypes.wintypes.HANDLE),
    ]

class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", ctypes.wintypes.HANDLE),
        ("hThread", ctypes.wintypes.HANDLE),
        ("dwProcessId", ctypes.wintypes.DWORD),
        ("dwThreadId", ctypes.wintypes.DWORD),
    ]

si = STARTUPINFO()
si.cb = ctypes.sizeof(STARTUPINFO)
si.lpDesktop = r"winsta0\Default"
si.dwFlags = 0x00000001
si.wShowWindow = 1

pi = PROCESS_INFORMATION()
cmd = f'"{CSCAPE_EXE}" "{CSP_FILE}"'
cwd = str(CSCAPE_EXE.parent)
flags = 0x01000000 | 0x00000200 | 0x00000008
kernel32.CreateProcessW(None, cmd, None, None, False, flags, None, cwd, ctypes.byref(si), ctypes.byref(pi))
pid = pi.dwProcessId
kernel32.CloseHandle(pi.hThread)
kernel32.CloseHandle(pi.hProcess)
print(f"Spawned PID={pid}")

# Wait and observe windows without dismissing
for sec in range(10):
    time.sleep(1.0)
    windows = []
    def cb(h, _):
        p = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(h):
            cls_b = ctypes.create_unicode_buffer(256)
            txt_b = ctypes.create_unicode_buffer(512)
            user32.GetClassNameW(h, cls_b, 256)
            user32.GetWindowTextW(h, txt_b, 512)
            windows.append((hex(h), cls_b.value, txt_b.value))
        return True
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    print(f"Sec {sec}: {windows}")
