import ctypes
import ctypes.wintypes
import time
import winreg
from pathlib import Path

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

CSCAPE_EXE = Path(r"C:\Program Files (x86)\Cscape 10.2\Cscape.exe")
CSP_PATH = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\projects\TankLevel_P4_REDO\TankLevel_P4_REDO.csp")

def ensure_desktop():
    hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
    if hd:
        user32.SetThreadDesktop(hd)

def configure_registry():
    print("Configuring registry keys for clean visible startup...")
    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Horner_Electric\Cscape\Editor")
    winreg.SetValueEx(k, "AllowUserToChooseProgram", 0, winreg.REG_DWORD, 0)
    winreg.SetValueEx(k, "OpenLast", 0, winreg.REG_DWORD, 1)
    winreg.SetValueEx(k, "CreateBlankProgram", 0, winreg.REG_DWORD, 0)
    winreg.CloseKey(k)

    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Horner_Electric\Cscape\Setup")
    winreg.SetValueEx(k, "CscapeExitedCorrectly", 0, winreg.REG_DWORD, 1)
    winreg.CloseKey(k)

    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Horner_Electric\Cscape\Recent File List")
    winreg.SetValueEx(k, "File1", 0, winreg.REG_SZ, str(CSP_PATH))
    winreg.CloseKey(k)

    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Horner_Electric\Cscape\IECEditor")
    winreg.SetValueEx(k, "EnableDragDrop", 0, winreg.REG_DWORD, 1)
    winreg.SetValueEx(k, "UndoRedoStackSize", 0, winreg.REG_DWORD, 16)
    winreg.SetValueEx(k, "TabSize", 0, winreg.REG_DWORD, 4)
    winreg.CloseKey(k)

    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Horner_Electric\Cscape\HornerIDReg")
    winreg.SetValueEx(k, "HornerKeepMeLoggedIn", 0, winreg.REG_DWORD, 1)
    winreg.CloseKey(k)
    print("Registry keys set.")

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

ensure_desktop()
configure_registry()

si = STARTUPINFO()
si.cb = ctypes.sizeof(STARTUPINFO)
si.lpDesktop = r"winsta0\Default"
si.dwFlags = 0x00000001
si.wShowWindow = 1

pi = PROCESS_INFORMATION()
cmd = f'"{CSCAPE_EXE}" "{CSP_PATH}"'
cwd = str(CSCAPE_EXE.parent)
flags = 0x01000000 | 0x00000200 | 0x00000008
success = kernel32.CreateProcessW(None, cmd, None, None, False, flags, None, cwd, ctypes.byref(si), ctypes.byref(pi))
if not success:
    flags = 0x00000200
    success = kernel32.CreateProcessW(None, cmd, None, None, False, flags, None, cwd, ctypes.byref(si), ctypes.byref(pi))

pid = pi.dwProcessId
kernel32.CloseHandle(pi.hThread)
kernel32.CloseHandle(pi.hProcess)
print(f"Spawned Cscape PID={pid}")

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

main_hwnd = 0
main_title = ""
for sec in range(25):
    time.sleep(1.0)
    def cb(h, _):
        global main_hwnd, main_title
        p = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(h):
            cls_b = ctypes.create_unicode_buffer(256)
            txt_b = ctypes.create_unicode_buffer(512)
            user32.GetClassNameW(h, cls_b, 256)
            user32.GetWindowTextW(h, txt_b, 512)
            if "cscape" in txt_b.value.lower() and not txt_b.value.startswith("GDI+"):
                main_hwnd = h
                main_title = txt_b.value
            elif cls_b.value == "#32770":
                print(f"  Dismissing startup modal {hex(h)}: {txt_b.value}")
                user32.PostMessageW(h, 0x0111, 1, 0)
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    if main_hwnd and "tanklevel_p4_redo" in main_title.lower():
        print(f"Sec {sec}: Main window found: HWND={hex(main_hwnd)} Title='{main_title}'")
        break

print(f"Final: Cscape main HWND={hex(main_hwnd)} Title='{main_title}'")
if main_hwnd:
    user32.ShowWindow(main_hwnd, 9)
    user32.BringWindowToTop(main_hwnd)
    user32.SetForegroundWindow(main_hwnd)
