import ctypes
from ctypes import wintypes
import os, sys, time

kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

class STARTUPINFO(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", ctypes.c_wchar_p),
        ("lpDesktop", ctypes.c_wchar_p),
        ("lpTitle", ctypes.c_wchar_p),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]

class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]

si = STARTUPINFO()
si.cb = ctypes.sizeof(STARTUPINFO)
si.lpDesktop = r"winsta0\Default"
si.dwFlags = 0x00000001
si.wShowWindow = 1

pi = PROCESS_INFORMATION()

cscape_exe = r"C:\Program Files (x86)\Cscape 10.2\Cscape.exe"
project = r"C:\HornerAI\horner-cscape-mcp\artifacts\projects\TankLevelClosedLoop\TankLevelClosedLoop.csp"
cmd = f'"{cscape_exe}" "{project}"'
cwd = r"C:\Program Files (x86)\Cscape 10.2"

flags2 = 0x00000008 | 0x00000200
res2 = kernel32.CreateProcessW(None, cmd, None, None, False, flags2, None, cwd, ctypes.byref(si), ctypes.byref(pi))
print("CreateProcess with TankLevel res:", res2, "PID:", pi.dwProcessId)

time.sleep(3.0)

# Check windows on winsta0\Default
hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
if hd:
    user32.SetThreadDesktop(hd)

def cb(h, _):
    p = wintypes.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(p))
    if p.value == pi.dwProcessId:
        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, cls_buf, 256)
        t_buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(h, t_buf, 512)
        vis = bool(user32.IsWindowVisible(h))
        print(f"TankLevel Cscape Window: {hex(h)}, {cls_buf.value}, '{t_buf.value}', visible={vis}")
    return True

user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(cb), 0)
