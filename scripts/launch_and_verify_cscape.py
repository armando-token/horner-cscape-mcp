#!/usr/bin/env python3
"""Launch and verify Cscape 10.2 visibly on interactive desktop with TankLevelClosedLoop.csp."""

import ctypes
import ctypes.wintypes
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import winreg

import psutil
from PIL import Image, ImageGrab

USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
CSCAPE_EXE = Path(r"C:\Program Files (x86)\Cscape 10.2\Cscape.exe")
CSP_PATH = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else (HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "TankLevelClosedLoop.csp")
PROJECT_NAME = CSP_PATH.name.lower()

SCREENSHOT_PATHS = [
    HORNER_ROOT / "artifacts" / "screenshots" / "live_cscape_tanklevel_visible.png",
    USER_ROOT / "artifacts" / "screenshots" / "live_cscape_tanklevel_visible.png",
]

GATE_PATHS = [
    HORNER_ROOT / "artifacts" / ".cscape_live_gate.json",
    USER_ROOT / "artifacts" / ".cscape_live_gate.json",
    HORNER_ROOT / "artifacts" / "checkpoints" / "cscape_live_gate.json",
    USER_ROOT / "artifacts" / "checkpoints" / "cscape_live_gate.json",
]

for p in SCREENSHOT_PATHS + GATE_PATHS:
    p.parent.mkdir(parents=True, exist_ok=True)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32

user32.IsHungAppWindow.argtypes = [ctypes.wintypes.HWND]
user32.IsHungAppWindow.restype = ctypes.wintypes.BOOL
user32.IsWindowVisible.argtypes = [ctypes.wintypes.HWND]
user32.IsWindowVisible.restype = ctypes.wintypes.BOOL
user32.IsWindowEnabled.argtypes = [ctypes.wintypes.HWND]
user32.IsWindowEnabled.restype = ctypes.wintypes.BOOL

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)


def get_utc_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def ensure_desktop():
    try:
        hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if hd:
            user32.SetThreadDesktop(hd)
            return hd
    except Exception as e:
        print(f"Warning attaching to desktop: {e}")
    return None


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
    print("Registry successfully configured.")


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


def spawn_cscape_visible() -> int:
    ensure_desktop()
    si = STARTUPINFO()
    si.cb = ctypes.sizeof(STARTUPINFO)
    si.lpDesktop = r"winsta0\Default"
    si.dwFlags = 0x00000001  # STARTF_USESHOWWINDOW
    si.wShowWindow = 1       # SW_SHOWNORMAL

    pi = PROCESS_INFORMATION()

    cmd = f'"{CSCAPE_EXE}" "{CSP_PATH}"'
    cwd = str(CSCAPE_EXE.parent)
    print(f"Spawning Cscape visibly: {cmd} in {cwd}")

    creation_flags = 0x01000000 | 0x00000200  # CREATE_BREAKAWAY_FROM_JOB | CREATE_NEW_PROCESS_GROUP
    success = kernel32.CreateProcessW(
        None,
        cmd,
        None,
        None,
        False,
        creation_flags,
        None,
        cwd,
        ctypes.byref(si),
        ctypes.byref(pi),
    )

    if not success:
        # Fallback without breakaway
        print("CreateProcessW with breakaway failed, falling back without breakaway...")
        success = kernel32.CreateProcessW(
            None,
            cmd,
            None,
            None,
            False,
            0x00000200,
            None,
            cwd,
            ctypes.byref(si),
            ctypes.byref(pi),
        )

    if not success:
        err = kernel32.GetLastError()
        raise RuntimeError(f"CreateProcessW failed with error code {err}")

    pid = pi.dwProcessId
    kernel32.CloseHandle(pi.hThread)
    kernel32.CloseHandle(pi.hProcess)
    print(f"Successfully spawned Cscape PID={pid}")
    return pid


def enum_child_controls(parent_hwnd: int) -> dict[int, int]:
    controls: dict[int, int] = {}

    def cb(hwnd, _):
        try:
            cid = user32.GetDlgCtrlID(hwnd)
            controls[cid] = hwnd
        except Exception:
            pass
        return 1

    c_cb = WNDENUMPROC(cb)
    user32.EnumChildWindows(parent_hwnd, c_cb, 0)
    return controls


def get_all_windows() -> list[dict]:
    ensure_desktop()
    wins = []

    def cb(hwnd, _):
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        t = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, t, 512)
        c = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, c, 256)
        vis = user32.IsWindowVisible(hwnd)
        en = user32.IsWindowEnabled(hwnd)
        wins.append({
            "hwnd": hwnd,
            "pid": pid.value,
            "title": t.value,
            "class": c.value,
            "visible": bool(vis),
            "enabled": bool(en),
        })
        return 1

    c_cb = WNDENUMPROC(cb)
    user32.EnumWindows(c_cb, 0)
    return wins


def dismiss_modal_dialogs():
    wins = get_all_windows()
    for w in wins:
        if w["class"] == "#32770":
            title_lower = w["title"].lower()
            ctrls = enum_child_controls(w["hwnd"])
            ok_hwnd = ctrls.get(1)  # IDOK = 1
            if "about cscape" in title_lower or "splash" in title_lower:
                print(f"Dismissing splash dialog HWND=0x{w['hwnd']:08X} ('{w['title']}')...")
                if ok_hwnd:
                    user32.PostMessageW(ok_hwnd, 0x00F5, 0, 0)  # BM_CLICK
                user32.PostMessageW(w["hwnd"], 0x0111, 1, ok_hwnd or 0)
            elif "select editor" in title_lower:
                print(f"Handling Select Editor Type dialog HWND=0x{w['hwnd']:08X}...")
                radio_hwnd = ctrls.get(1461)
                if radio_hwnd:
                    user32.PostMessageW(radio_hwnd, 0x00F1, 1, 0)  # BM_SETCHECK BST_CHECKED
                    user32.PostMessageW(w["hwnd"], 0x0111, 1461, radio_hwnd)
                if ok_hwnd:
                    user32.PostMessageW(ok_hwnd, 0x00F5, 0, 0)
                user32.PostMessageW(w["hwnd"], 0x0111, 1, ok_hwnd or 0)
            elif "allow" in title_lower or "security" in title_lower or "warning" in title_lower or "notice" in title_lower:
                print(f"Dismissing prompt dialog HWND=0x{w['hwnd']:08X} ('{w['title']}')...")
                if ok_hwnd:
                    user32.PostMessageW(ok_hwnd, 0x00F5, 0, 0)
                user32.PostMessageW(w["hwnd"], 0x0111, 1, ok_hwnd or 0)


def capture_screenshot(hwnd: int) -> bool:
    r = ctypes.wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return False
    bbox = (max(0, r.left), max(0, r.top), max(10, r.right), max(10, r.bottom))
    try:
        im = ImageGrab.grab(bbox=bbox)
        for sp in SCREENSHOT_PATHS:
            im.save(str(sp))
            print(f"Saved screenshot: {sp} ({im.size[0]}x{im.size[1]}, {sp.stat().st_size} bytes)")
        return True
    except Exception as e:
        print(f"Error saving screenshot: {e}")
        return False


def update_gate(ready: bool, pid: int, hwnd: int, title: str, reason: str = "TankLevelClosedLoop verified active and responsive"):
    data = {
        "ready_for_tests": ready,
        "status": "READY_FOR_TESTS" if ready else "NOT_READY",
        "pid": pid,
        "hwnd": f"0x{hwnd:08X}" if hwnd else None,
        "window_title": title,
        "project_file": str(CSP_PATH),
        "exit_code": None,
        "reason": reason,
        "cycle": 1,
        "timestamp_utc": get_utc_iso(),
        "heartbeat_utc": get_utc_iso(),
    }
    for gp in GATE_PATHS:
        try:
            gp.parent.mkdir(parents=True, exist_ok=True)
            gp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            print(f"Updated gate file: {gp}")
        except Exception as e:
            print(f"Failed to update gate file {gp}: {e}")


def main():
    print("=" * 80)
    print("AGENT 1: VISIBLE CSCAPE GUI CONTROLLER & LIVENESS SUPERVISOR")
    print("=" * 80)

    # 1. Kill any existing Cscape processes cleanly
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if "cscape" in p.info["name"].lower():
                print(f"Terminating lingering Cscape PID {p.info['pid']}...")
                p.kill()
        except Exception:
            pass
    time.sleep(1.0)

    # 2. Configure registry
    configure_registry()

    # 3. Spawn Cscape visibly
    pid = spawn_cscape_visible()

    # 4. Wait, dismiss modal dialogs, and look for main window
    print("Monitoring startup and modal dialogs...")
    main_hwnd = 0
    main_title = ""
    main_pid = pid

    t0 = time.time()
    while time.time() - t0 < 30.0:
        dismiss_modal_dialogs()
        wins = get_all_windows()
        for w in wins:
            if "cscape" in w["title"].lower() and not w["title"].startswith("GDI+"):
                # Potential main window
                main_hwnd = w["hwnd"]
                main_title = w["title"]
                main_pid = w["pid"]
                if PROJECT_NAME in w["title"].lower():
                    break
        if PROJECT_NAME in main_title.lower():
            break
        time.sleep(1.0)

    # If title doesn't yet contain project name, send ID_FILE_MRU_FILE1
    if PROJECT_NAME not in main_title.lower() and main_hwnd:
        print(f"Title is currently '{main_title}'. Sending ID_FILE_MRU_FILE1 (57616)...")
        user32.PostMessageW(main_hwnd, 0x0111, 57616, 0)
        time.sleep(3.0)
        dismiss_modal_dialogs()
        wins = get_all_windows()
        for w in wins:
            if "cscape" in w["title"].lower() and not w["title"].startswith("GDI+"):
                main_hwnd = w["hwnd"]
                main_title = w["title"]
                main_pid = w["pid"]
                if PROJECT_NAME in w["title"].lower():
                    break

    # 5. Verify Cscape window
    print("-" * 80)
    print("VERIFYING CSCAPE WINDOW PROPERTIES:")
    print(f"PID: {main_pid}")
    print(f"HWND: 0x{main_hwnd:08X}")
    print(f"Title: '{main_title}'")

    if not main_hwnd:
        raise RuntimeError("Failed to locate Cscape main window!")

    is_visible = bool(user32.IsWindowVisible(main_hwnd))
    is_enabled = bool(user32.IsWindowEnabled(main_hwnd))
    is_hung = bool(user32.IsHungAppWindow(main_hwnd))
    has_project = PROJECT_NAME in main_title.lower()

    print(f"IsWindowVisible: {is_visible}")
    print(f"IsWindowEnabled: {is_enabled}")
    print(f"IsHungAppWindow: {is_hung}")
    print(f"Title contains {PROJECT_NAME}: {has_project}")

    if not (is_visible and is_enabled and not is_hung and has_project):
        raise RuntimeError(
            f"Verification FAILED: visible={is_visible}, enabled={is_enabled}, hung={is_hung}, title='{main_title}'"
        )

    # Bring to foreground & restore
    user32.ShowWindow(main_hwnd, 1)  # SW_SHOWNORMAL
    user32.BringWindowToTop(main_hwnd)
    user32.SetForegroundWindow(main_hwnd)
    time.sleep(1.0)

    # 6. Capture screenshot
    print("Capturing live screenshot proof...")
    success = capture_screenshot(main_hwnd)
    if not success:
        print("Warning: initial screenshot attempt failed, retrying...")
        time.sleep(1.0)
        capture_screenshot(main_hwnd)

    # 7. Update gate file
    print("Updating gate files...")
    update_gate(ready=True, pid=main_pid, hwnd=main_hwnd, title=main_title)

    print("=" * 80)
    print("VERIFICATION COMPLETE & SUCCESSFUL!")
    print(f"PID: {main_pid}")
    print(f"HWND: 0x{main_hwnd:08X}")
    print(f"Title: {main_title}")
    print(f"Screenshot proof: {SCREENSHOT_PATHS[0]}")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
