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
project = r"C:\HornerAI\horner-cscape-mcp\artifacts\projects\LabProject_W01\LabProject_W01.csp"
cmd = f'"{cscape_exe}" "{project}"'
cwd = r"C:\Program Files (x86)\Cscape 10.2"

flags = 0x01000000 | 0x00000200
res = kernel32.CreateProcessW(None, cmd, None, None, False, flags, None, cwd, ctypes.byref(si), ctypes.byref(pi))
err = kernel32.GetLastError()
print("CreateProcess with breakaway res:", res, "LastError:", err)

if not res:
    flags2 = 0x00000008 | 0x00000200
    res2 = kernel32.CreateProcessW(None, cmd, None, None, False, flags2, None, cwd, ctypes.byref(si), ctypes.byref(pi))
    err2 = kernel32.GetLastError()
    print("CreateProcess with DETACHED res:", res2, "LastError:", err2)

pid = pi.dwProcessId
print("PID:", pid)
kernel32.CloseHandle(pi.hThread)
kernel32.CloseHandle(pi.hProcess)
