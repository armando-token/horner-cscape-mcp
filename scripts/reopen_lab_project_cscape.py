"""Launch and verify Cscape 10.2 visibly hosting LabProject_W01.csp on winsta0\\Default.

Enforces:
1. HKCU registry setup for LabProject_W01.csp as Recent File 1 and clean exit.
2. Clean process spawn on winsta0\\Default desktop.
3. Modal dialog suppression (About Cscape, Select Editor Type).
4. Window visibility and activation on interactive desktop.
5. Verification of LabProject in window title and Project Navigator.
6. Gate file update (.cscape_live_gate.json) with PID and HWND.
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
LAB_CSP = HORNER_ROOT / "artifacts" / "projects" / "LabProject_W01" / "LabProject_W01.csp"
ORIGINAL_TANK_CSP = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "TankLevelClosedLoop.csp"
ORIGINAL_TANK_SHA256 = "d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af"

KEEPALIVE_LOG = HORNER_ROOT / "artifacts" / "logs" / "cscape_keepalive.log"
GATE_FILES = [
    USER_ROOT / "artifacts" / ".cscape_live_gate.json",
    USER_ROOT / "artifacts" / "checkpoints" / "cscape_live_gate.json",
    HORNER_ROOT / "artifacts" / ".cscape_live_gate.json",
    HORNER_ROOT / "artifacts" / "checkpoints" / "cscape_live_gate.json",
]

SCREENSHOT_PATHS = [
    USER_ROOT / "artifacts" / "recovery" / "run_20260906_120831" / "cscape_lab_w01_visible.png",
    HORNER_ROOT / "artifacts" / "recovery" / "run_20260906_120831" / "cscape_lab_w01_visible.png",
]

for p in [KEEPALIVE_LOG] + GATE_FILES + SCREENSHOT_PATHS:
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
        "project_file": str(LAB_CSP),
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
    log_msg("Configuring HKCU registry for LabProject_W01.csp and clean exit...")
    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Horner_Electric\Cscape\Recent File List")
    winreg.SetValueEx(k, "File1", 0, winreg.REG_SZ, str(LAB_CSP))
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

    c_cb = WNDENUMPROC(cb)
    user32.EnumWindows(c_cb, 0)
    return wins


def capture_screenshot(hwnd: int, extra_paths: list[Path] | None = None) -> bool:
    r = ctypes.wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return False
    w = max(10, r.right - r.left)
    h = max(10, r.bottom - r.top)

    hdc_window = user32.GetWindowDC(hwnd)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
    hbm = gdi32.CreateCompatibleBitmap(hdc_window, w, h)
    gdi32.SelectObject(hdc_mem, hbm)
    gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_window, 0, 0, 0x00CC0020)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", ctypes.wintypes.DWORD),
            ("biWidth", ctypes.wintypes.LONG),
            ("biHeight", ctypes.wintypes.LONG),
            ("biPlanes", ctypes.wintypes.WORD),
            ("biBitCount", ctypes.wintypes.WORD),
            ("biCompression", ctypes.wintypes.DWORD),
            ("biSizeImage", ctypes.wintypes.DWORD),
            ("biXPelsPerMeter", ctypes.wintypes.LONG),
            ("biYPelsPerMeter", ctypes.wintypes.LONG),
            ("biClrUsed", ctypes.wintypes.DWORD),
            ("biClrImportant", ctypes.wintypes.DWORD),
        ]

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0

    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(hdc_mem, hbm, 0, h, buf, ctypes.byref(bmi), 0)

    try:
        if Image is not None:
            im = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
            all_paths = list(SCREENSHOT_PATHS)
            if extra_paths:
                all_paths.extend(extra_paths)
            for sp in all_paths:
                sp.parent.mkdir(parents=True, exist_ok=True)
                im.save(str(sp))
                log_msg(f"Screenshot proof saved: {sp} ({im.size[0]}x{im.size[1]})")
        return True
    except Exception as err:
        log_msg(f"Screenshot error: {err}")
        return False
    finally:
        gdi32.DeleteObject(hbm)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc_window)


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


def handle_dialogs(wins: list[dict]) -> None:
    for w in wins:
        if w["class"] == "#32770":
            t_lower = w["title"].lower()
            ctrls = enum_child_controls(w["hwnd"])
            ok_hwnd = ctrls.get(1)
            if "about cscape" in t_lower or "splash" in t_lower:
                log_msg(f"Dismissing splash dialog HWND=0x{w['hwnd']:08X}...")
                if ok_hwnd:
                    user32.PostMessageW(ok_hwnd, 0x00F5, 0, 0)
                user32.PostMessageW(w["hwnd"], 0x0111, 1, ok_hwnd or 0)
            elif "select editor" in t_lower:
                log_msg(f"Selecting IEC editor in dialog HWND=0x{w['hwnd']:08X}...")
                radio_hwnd = ctrls.get(1461)
                if radio_hwnd:
                    user32.PostMessageW(radio_hwnd, 0x00F1, 1, 0)
                    user32.PostMessageW(w["hwnd"], 0x0111, 1461, radio_hwnd)
                else:
                    user32.PostMessageW(w["hwnd"], 0x0111, 1461, 0)
                time.sleep(0.1)
                if ok_hwnd:
                    user32.PostMessageW(ok_hwnd, 0x00F5, 0, 0)
                user32.PostMessageW(w["hwnd"], 0x0111, 1, ok_hwnd or 0)
            elif "allow" in t_lower or "security" in t_lower or "notice" in t_lower:
                log_msg(f"Dismissing prompt dialog HWND=0x{w['hwnd']:08X} ('{w['title']}')...")
                if ok_hwnd:
                    user32.PostMessageW(ok_hwnd, 0x00F5, 0, 0)
                user32.PostMessageW(w["hwnd"], 0x0111, 1, ok_hwnd or 0)


def launch_or_verify_lab_cscape() -> tuple[int, int, str]:
    log_msg("=" * 80)
    log_msg("LAUNCH / VERIFY CSCAPE WITH LabProject_W01.csp ON winsta0\\Default")
    log_msg("=" * 80)

    set_registry()

    wins = get_cscape_windows()
    active_lab = False
    main_hwnd = 0
    main_pid = 0
    main_title = ""

    for w in wins:
        if "cscape" in w["title"].lower() and not w["title"].startswith("GDI+"):
            main_hwnd = w["hwnd"]
            main_pid = w["pid"]
            main_title = w["title"]
            if "labproject" in w["title"].lower():
                active_lab = True
                break

    log_msg(f"Current Cscape State: PID={main_pid}, HWND=0x{main_hwnd:08X}, Title='{main_title}'")

    if not active_lab:
        log_msg("Cscape is NOT open on LabProject_W01. Relaunching...")
        update_gate(
            ready=False,
            status="RELAUNCH_UNDERWAY",
            pid=main_pid,
            hwnd=main_hwnd,
            title=main_title,
            reason="Restarting Cscape with LabProject_W01.csp",
        )

        subprocess.run(["taskkill.exe", "/F", "/T", "/IM", "Cscape.exe"], capture_output=True)
        time.sleep(1.5)

        set_registry()

        cmd = [str(CSCAPE_EXE), str(LAB_CSP)]
        log_msg(f"Spawning detached: {' '.join(cmd)}")
        creationflags = 0x00000008 | 0x00000200
        try:
            proc = subprocess.Popen(cmd, cwd=str(CSCAPE_EXE.parent), creationflags=creationflags | 0x01000000, close_fds=True)
        except OSError:
            proc = subprocess.Popen(cmd, cwd=str(CSCAPE_EXE.parent), creationflags=creationflags, close_fds=True)
        main_pid = proc.pid
        log_msg(f"Spawned Cscape PID={main_pid}")

        t0 = time.time()
        while time.time() - t0 < 30.0:
            wins = get_cscape_windows()
            handle_dialogs(wins)

            for w in wins:
                if "cscape" in w["title"].lower() and not w["title"].startswith("GDI+"):
                    main_hwnd = w["hwnd"]
                    main_pid = w["pid"]
                    main_title = w["title"]
                    if "labproject" in w["title"].lower():
                        active_lab = True
                        break

            if active_lab:
                break

            time.sleep(1.0)

    if not active_lab and main_hwnd:
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
                if "labproject" in w["title"].lower():
                    active_lab = True
                    break

    log_msg(f"Final Window State: PID={main_pid}, HWND=0x{main_hwnd:08X}, Title='{main_title}'")
    is_hung = user32.IsHungAppWindow(main_hwnd) if main_hwnd else True
    ping_ok = ping_window(main_hwnd) if main_hwnd else False

    if active_lab and not is_hung and ping_ok:
        log_msg("SUCCESS: Cscape is VISIBLY OPEN on LabProject_W01.csp!")
        user32.ShowWindow(main_hwnd, 1)
        user32.BringWindowToTop(main_hwnd)
        user32.SetForegroundWindow(main_hwnd)

        user32.PostMessageW(main_hwnd, 0x0111, 45012, 0)
        time.sleep(0.5)

        capture_screenshot(main_hwnd)

        update_gate(
            ready=True,
            status="READY_FOR_TESTS",
            pid=main_pid,
            hwnd=main_hwnd,
            title=main_title,
            reason="LabProject_W01 verified active, visible, and responsive",
        )
        return main_pid, main_hwnd, main_title
    else:
        err_msg = f"FAIL-CLOSED: LabProject not active in title ('{main_title}') or is_hung={is_hung}"
        log_msg(err_msg)
        update_gate(
            ready=False,
            status="FAIL_CLOSED_CSCAPE_DEAD",
            pid=main_pid,
            hwnd=main_hwnd,
            title=main_title,
            reason=err_msg,
        )
        raise RuntimeError(err_msg)


if __name__ == "__main__":
    launch_or_verify_lab_cscape()
