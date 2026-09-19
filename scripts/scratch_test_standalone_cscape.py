import ctypes, ctypes.wintypes, time
from pathlib import Path

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

CSCAPE_EXE = Path(r"C:\Program Files (x86)\Cscape 10.2\Cscape.exe")

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

# Suppress crash recovery in registry
try:
    import winreg
    reg_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Horner_Electric\Cscape\Setup")
    winreg.SetValueEx(reg_key, "CscapeExitedCorrectly", 0, winreg.REG_DWORD, 1)
    winreg.CloseKey(reg_key)
except Exception as e:
    print("Registry error:", e)

si = STARTUPINFO()
si.cb = ctypes.sizeof(STARTUPINFO)
si.lpDesktop = r"winsta0\Default"
si.dwFlags = 0x00000001
si.wShowWindow = 1

pi = PROCESS_INFORMATION()
cmd = f'"{CSCAPE_EXE}"'
res = kernel32.CreateProcessW(None, cmd, None, None, False, 0x00000200, None, str(CSCAPE_EXE.parent), ctypes.byref(si), ctypes.byref(pi))
err = kernel32.GetLastError()
pid = pi.dwProcessId
print(f"Launched standalone Cscape result={res}, err={err}, pid={pid}")

for i in range(10):
    time.sleep(1.0)
    exit_code = ctypes.wintypes.DWORD()
    kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(exit_code))
    print(f"Sec {i}: exit_code={exit_code.value}")
    if exit_code.value != 259: # 259 is STILL_ACTIVE
        break
