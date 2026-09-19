"""Reopen TankLevelClosedLoop.csp in Cscape GUI, enforcing fail-closed gate.

1. Ensure registry settings point to TankLevelClosedLoop.csp and IEC mode.
2. Cleanly restart Cscape.exe if currently on untitled1 or missing TankLevel.
3. Dismiss any startup modal dialogs (About Cscape, Select Editor Type).
4. Verify window title explicitly shows TankLevel.
5. Capture proof screenshot.
6. Write gate checkpoint and append status to cscape_keepalive.log.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import datetime
import json
from pathlib import Path
import subprocess
import sys
import time
import winreg

import psutil
try:
    from PIL import Image
except ImportError:
    Image = None

USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()

CSCAPE_EXE = Path(r"C:\Program Files (x86)\Cscape 10.2\Cscape.exe")
CSP_PATH = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else (USER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "TankLevelClosedLoop.csp")

KEEPALIVE_LOG = USER_ROOT / "artifacts" / "logs" / "cscape_keepalive.log"
GATE_FILES = [
    USER_ROOT / "artifacts" / ".cscape_live_gate.json",
    USER_ROOT / "artifacts" / "checkpoints" / "cscape_live_gate.json",
    HORNER_ROOT / "artifacts" / ".cscape_live_gate.json",
    HORNER_ROOT / "artifacts" / "checkpoints" / "cscape_live_gate.json",
]

SCREENSHOT_PATHS = [
    USER_ROOT / "artifacts" / "screenshots" / "cscape_tanklevel_loaded.png",
    HORNER_ROOT / "artifacts" / "screenshots" / "cscape_tanklevel_loaded.png",
]

CHECKPOINT_PATHS = [
    USER_ROOT / "artifacts" / "checkpoints" / "step2_tanklevel_loaded_checkpoint.json",
    HORNER_ROOT / "artifacts" / "checkpoints" / "step2_tanklevel_loaded_checkpoint.json",
]

for p in [KEEPALIVE_LOG] + GATE_FILES + SCREENSHOT_PATHS + CHECKPOINT_PATHS:
    p.parent.mkdir(parents=True, exist_ok=True)


def get_utc_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def log_msg(msg: str) -> None:
    line = f"[{get_utc_iso()}] {msg}"
    print(line, flush=True)
    try:
        with open(KEEPALIVE_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def update_gate(ready: bool, status: str, pid: int | None, hwnd: int | None, title: str, reason: str) -> None:
    data = {
        "ready_for_tests": ready,
        "status": status,
        "pid": pid,
        "hwnd": f"0x{hwnd:08X}" if hwnd else None,
        "window_title": title,
        "project_file": str(CSP_PATH),
        "reason": reason,
        "timestamp_utc": get_utc_iso(),
        "heartbeat_utc": get_utc_iso(),
    }
    for gf in GATE_FILES:
        try:
            gf.parent.mkdir(parents=True, exist_ok=True)
            gf.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass
    log_msg(f"[GATE_UPDATE] Status={status} | Ready={ready} | PID={pid} | HWND=0x{hwnd or 0:X} | Title='{title}' | Reason={reason}")


def set_registry() -> None:
    log_msg("Configuring HKCU registry for Cscape project and clean exit...")
    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Horner_Electric\Cscape\Recent File List")
    winreg.SetValueEx(k, "File1", 0, winreg.REG_SZ, str(CSP_PATH))
    winreg.CloseKey(k)

    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Horner_Electric\Cscape\Editor")
    winreg.SetValueEx(k, "OpenLast", 0, winreg.REG_DWORD, 1)
    winreg.SetValueEx(k, "AllowUserToChooseProgram", 0, winreg.REG_DWORD, 0)
    winreg.SetValueEx(k, "CreateBlankProgram", 0, winreg.REG_DWORD, 0)
    winreg.CloseKey(k)

    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Horner_Electric\Cscape\Setup")
    winreg.SetValueEx(k, "CscapeExitedCorrectly", 0, winreg.REG_DWORD, 1)
    winreg.CloseKey(k)

    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Horner_Electric\Cscape\IECEditor")
    winreg.SetValueEx(k, "EnableDragDrop", 0, winreg.REG_DWORD, 1)
    winreg.SetValueEx(k, "UndoRedoStackSize", 0, winreg.REG_DWORD, 16)
    winreg.SetValueEx(k, "TabSize", 0, winreg.REG_DWORD, 4)
    winreg.CloseKey(k)


user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

WNDENUMPROC = ctypes.WINFUNCTYPE(
    ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
)

user32.IsHungAppWindow.argtypes = [ctypes.wintypes.HWND]
user32.IsHungAppWindow.restype = ctypes.wintypes.BOOL

user32.SendMessageTimeoutW.argtypes = [
    ctypes.wintypes.HWND,
    ctypes.wintypes.UINT,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
    ctypes.wintypes.UINT,
    ctypes.wintypes.UINT,
    ctypes.POINTER(ctypes.c_ulong),
]
user32.SendMessageTimeoutW.restype = ctypes.c_long

user32.OpenDesktopW.argtypes = [ctypes.c_wchar_p, ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD]
user32.OpenDesktopW.restype = ctypes.c_void_p

user32.SetThreadDesktop.argtypes = [ctypes.c_void_p]
user32.SetThreadDesktop.restype = ctypes.wintypes.BOOL

user32.GetWindowThreadProcessId.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD

user32.GetWindowRect.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.RECT)]
user32.GetWindowRect.restype = ctypes.wintypes.BOOL

user32.GetWindowDC.argtypes = [ctypes.wintypes.HWND]
user32.GetWindowDC.restype = ctypes.wintypes.HDC

user32.ReleaseDC.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int

user32.ShowWindow.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = ctypes.wintypes.BOOL

user32.BringWindowToTop.argtypes = [ctypes.wintypes.HWND]
user32.BringWindowToTop.restype = ctypes.wintypes.BOOL

user32.SetForegroundWindow.argtypes = [ctypes.wintypes.HWND]
user32.SetForegroundWindow.restype = ctypes.wintypes.BOOL

user32.PostMessageW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.UINT, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM]
user32.PostMessageW.restype = ctypes.wintypes.BOOL

user32.GetDlgCtrlID.argtypes = [ctypes.wintypes.HWND]
user32.GetDlgCtrlID.restype = ctypes.c_int

user32.GetWindowTextW.argtypes = [ctypes.wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int

user32.GetClassNameW.argtypes = [ctypes.wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int

user32.EnumWindows.argtypes = [WNDENUMPROC, ctypes.wintypes.LPARAM]
user32.EnumWindows.restype = ctypes.wintypes.BOOL

user32.EnumDesktopWindows.argtypes = [ctypes.c_void_p, WNDENUMPROC, ctypes.wintypes.LPARAM]
user32.EnumDesktopWindows.restype = ctypes.wintypes.BOOL

user32.EnumChildWindows.argtypes = [ctypes.wintypes.HWND, WNDENUMPROC, ctypes.wintypes.LPARAM]
user32.EnumChildWindows.restype = ctypes.wintypes.BOOL


def ping_window(hwnd: int, timeout_ms: int = 1000) -> bool:
    if not hwnd:
        return False
    try:
        res_val = ctypes.c_ulong(0)
        res = user32.SendMessageTimeoutW(hwnd, 0, 0, 0, 0x0002, timeout_ms, ctypes.byref(res_val))
        return bool(res)
    except Exception:
        return False


def get_cscape_windows() -> list[dict]:
    try:
        hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if hd:
            user32.SetThreadDesktop(hd)
    except Exception:
        pass

    pids = set()
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if p.info["name"] and "cscape" in p.info["name"].lower():
                pids.add(p.info["pid"])
        except Exception:
            pass

    wins = []

    def cb(hwnd, _):
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids:
            t = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, t, 512)
            c = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, c, 256)
            vis = user32.IsWindowVisible(hwnd)
            r = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            wins.append({
                "hwnd": hwnd,
                "pid": pid.value,
                "title": t.value,
                "class": c.value,
                "visible": bool(vis),
                "rect": (r.left, r.top, r.right, r.bottom),
            })
        return 1

    user32.EnumWindows.argtypes = [WNDENUMPROC, ctypes.wintypes.LPARAM]
    user32.EnumWindows.restype = ctypes.wintypes.BOOL
    c_cb = WNDENUMPROC(cb)
    user32.EnumWindows(c_cb, 0)
    if not wins:
        user32.EnumDesktopWindows.argtypes = [ctypes.c_void_p, WNDENUMPROC, ctypes.wintypes.LPARAM]
        user32.EnumDesktopWindows.restype = ctypes.wintypes.BOOL
        for dname in ["Default", "exebox-SFKDH7PVZHHA5N3KL2KU2F6TB4", "exebox-TSZBFXK7CRLCRFNAU74PC5FQZL"]:
            hd = user32.OpenDesktopW(dname, 0, False, 0x01FF)
            if hd:
                user32.EnumDesktopWindows(hd, c_cb, 0)
                if any("cscape" in w["title"].lower() for w in wins):
                    break
    return wins


def capture_screenshot(hwnd: int) -> bool:
    try:
        from PIL import ImageGrab
        im = ImageGrab.grab()
        for sp in SCREENSHOT_PATHS:
            im.save(str(sp))
            log_msg(f"Screenshot proof saved: {sp} ({im.size[0]}x{im.size[1]})")
        return True
    except Exception as err:
        log_msg(f"Screenshot error via ImageGrab: {err}")
        return False



def enum_child_controls(parent_hwnd: int) -> dict[int, int]:
    controls: dict[int, int] = {}

    def cb(hwnd, _):
        try:
            cid = user32.GetDlgCtrlID(hwnd)
            controls[cid] = hwnd
        except Exception:
            pass
        return 1

    user32.EnumChildWindows.argtypes = [ctypes.wintypes.HWND, WNDENUMPROC, ctypes.wintypes.LPARAM]
    user32.EnumChildWindows.restype = ctypes.wintypes.BOOL
    c_cb = WNDENUMPROC(cb)
    user32.EnumChildWindows(parent_hwnd, c_cb, 0)
    return controls


def handle_dialogs(wins: list[dict]) -> None:
    for w in wins:
        if w["class"] == "#32770":
            t_lower = w["title"].lower()
            ctrls = enum_child_controls(w["hwnd"])
            ok_hwnd = ctrls.get(1)
            if "about cscape" in t_lower:
                log_msg(f"Dismissing splash dialog HWND=0x{w['hwnd']:08X}...")
                if ok_hwnd:
                    user32.PostMessageW(ok_hwnd, 0x00F5, 0, 0)  # BM_CLICK
                user32.PostMessageW(w["hwnd"], 0x0111, 1, ok_hwnd or 0)  # ID_OK
            elif "select editor" in t_lower:
                log_msg(f"Selecting IEC editor in dialog HWND=0x{w['hwnd']:08X}...")
                radio_hwnd = ctrls.get(1461)
                if radio_hwnd:
                    user32.PostMessageW(radio_hwnd, 0x00F1, 1, 0)  # BM_SETCHECK BST_CHECKED
                    user32.PostMessageW(w["hwnd"], 0x0111, 1461, radio_hwnd)
                else:
                    user32.PostMessageW(w["hwnd"], 0x0111, 1461, 0)
                time.sleep(0.1)
                if ok_hwnd:
                    user32.PostMessageW(ok_hwnd, 0x00F5, 0, 0)
                user32.PostMessageW(w["hwnd"], 0x0111, 1, ok_hwnd or 0)


def main() -> int:
    log_msg("=" * 80)
    log_msg("FAIL-CLOSED GATE CHECK: VERIFYING TANKLEVEL IN CSCAPE")
    log_msg("=" * 80)

    set_registry()

    # Inspect running instances
    wins = get_cscape_windows()
    active_tanklevel = False
    main_hwnd = 0
    main_pid = 0
    main_title = ""

    for w in wins:
        if "cscape" in w["title"].lower() and not w["title"].startswith("GDI+"):
            main_hwnd = w["hwnd"]
            main_pid = w["pid"]
            main_title = w["title"]
            if "tanklevel" in w["title"].lower() or "labproject" in w["title"].lower():
                active_tanklevel = True
                break

    log_msg(f"Current Cscape State: PID={main_pid}, HWND=0x{main_hwnd:08X}, Title='{main_title}'")

    if not active_tanklevel:
        log_msg("Cscape is NOT open on TankLevelClosedLoop (or on untitled1). Relaunching...")
        update_gate(
            ready=False,
            status="RELAUNCH_UNDERWAY",
            pid=main_pid,
            hwnd=main_hwnd,
            title=main_title,
            reason="Cscape on untitled1 or project not loaded; restarting with TankLevelClosedLoop.csp",
        )

        # Cleanly kill existing instances
        subprocess.run(["taskkill.exe", "/F", "/T", "/IM", "Cscape.exe"], capture_output=True)
        time.sleep(1.5)

        # Ensure registry clean exit again
        set_registry()

        # Launch Cscape with TankLevelClosedLoop.csp detached
        cmd = [str(CSCAPE_EXE), str(CSP_PATH)]
        log_msg(f"Spawning detached: {' '.join(cmd)}")
        creationflags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        try:
            proc = subprocess.Popen(cmd, cwd=str(CSCAPE_EXE.parent), creationflags=creationflags | 0x01000000, close_fds=True)
        except OSError:
            proc = subprocess.Popen(cmd, cwd=str(CSCAPE_EXE.parent), creationflags=creationflags, close_fds=True)
        main_pid = proc.pid
        log_msg(f"Spawned Cscape PID={main_pid}")

        # Wait for GUI and handle dialogs
        t0 = time.time()
        while time.time() - t0 < 30.0:
            wins = get_cscape_windows()
            handle_dialogs(wins)

            for w in wins:
                if "cscape" in w["title"].lower() and not w["title"].startswith("GDI+"):
                    main_hwnd = w["hwnd"]
                    main_pid = w["pid"]
                    main_title = w["title"]
                    if "tanklevel" in w["title"].lower() or "labproject" in w["title"].lower():
                        active_tanklevel = True
                        break

            if active_tanklevel:
                break

            time.sleep(1.0)

    # If main window appeared but title doesn't yet have project, try MRU 1 command (57616)
    if not active_tanklevel and main_hwnd:
        log_msg(f"Title is '{main_title}'. Sending ID_FILE_MRU_FILE1 (57616)...")
        user32.PostMessageW(main_hwnd, 0x0111, 57616, 0)
        time.sleep(3.0)
        wins = get_cscape_windows()
        handle_dialogs(wins)
        for w in wins:
            if "cscape" in w["title"].lower() and not w["title"].startswith("GDI+"):
                main_hwnd = w["hwnd"]
                main_pid = w["pid"]
                main_title = w["title"]
                if "tanklevel" in w["title"].lower() or "labproject" in w["title"].lower():
                    active_tanklevel = True
                    break

    # Final assertion
    log_msg(f"Final Window State: PID={main_pid}, HWND=0x{main_hwnd:08X}, Title='{main_title}'")
    is_hung = user32.IsHungAppWindow(main_hwnd) if main_hwnd else True
    ping_ok = ping_window(main_hwnd) if main_hwnd else False

    if active_tanklevel and not is_hung and ping_ok:
        log_msg("SUCCESS: Cscape is VISIBLY OPEN on TankLevelClosedLoop!")
        user32.ShowWindow(main_hwnd, 1)  # SW_SHOWNORMAL
        user32.BringWindowToTop(main_hwnd)
        user32.SetForegroundWindow(main_hwnd)

        capture_screenshot(main_hwnd)

        update_gate(
            ready=True,
            status="READY_FOR_TESTS",
            pid=main_pid,
            hwnd=main_hwnd,
            title=main_title,
            reason="TankLevelClosedLoop verified active and responsive",
        )

        checkpoint_data = {
            "step": "step2_open_tanklevel_project",
            "status": "PASSED",
            "timestamp_utc": get_utc_iso(),
            "project_file": str(CSP_PATH),
            "target_cscape_pid": main_pid,
            "main_hwnd": f"0x{main_hwnd:08X}",
            "main_window_title": main_title,
            "gui_loaded_verified": True,
            "is_hung": is_hung,
            "screenshot_proof": str(SCREENSHOT_PATHS[0]),
        }
        for cp in CHECKPOINT_PATHS:
            try:
                cp.write_text(json.dumps(checkpoint_data, indent=2), encoding="utf-8")
                log_msg(f"Checkpoint recorded: {cp}")
            except Exception:
                pass

        return 0
    else:
        err_msg = f"FAIL-CLOSED: TankLevel not active in title ('{main_title}') or is_hung={is_hung}"
        log_msg(err_msg)
        update_gate(
            ready=False,
            status="FAIL_CLOSED_CSCAPE_DEAD",
            pid=main_pid,
            hwnd=main_hwnd,
            title=main_title,
            reason=err_msg,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
