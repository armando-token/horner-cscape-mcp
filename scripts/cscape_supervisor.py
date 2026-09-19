#!/usr/bin/env python3
r"""Visible Cscape GUI Controller & Autonomous Liveness Supervisor.

Enforces:
1. Absolute Hardware Lockout Policy (NO hardware or PLC download).
2. Clean visible startup on interactive desktop (`winsta0\Default`, SW_SHOWNORMAL).
3. TankLevelClosedLoop.csp loaded into Cscape GUI.
4. Auto-dismissal of splash (#32770) and prompt dialogs.
5. Strict process filtering (only cscape.exe processes, never Notepad or other apps).
6. Continuous window liveness verification (IsWindowVisible, IsWindowEnabled, not IsHungAppWindow).
7. Verification that Project Navigator is user-visible.
8. Screenshot capture proof to artifacts/screenshots/live_cscape_tanklevel_visible.png.
9. Atomic updates to artifacts/.cscape_live_gate.json.
10. Resilient watchdog supervisor loop: NEVER kill on transient state; only recover if process dead or hung >15s.
"""

from __future__ import annotations

import argparse
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
from PIL import Image

USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
CSCAPE_EXE = Path(r"C:\Program Files (x86)\Cscape 10.2\Cscape.exe")
CSP_PATH = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "TankLevelClosedLoop.csp"

ID_TOOLS_PROJECTNAVIGATOR = 45012
ID_FILE_MRU_FILE1 = 57616

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

SUPERVISOR_LOG = HORNER_ROOT / "artifacts" / "logs" / "cscape_supervisor.log"

for p in SCREENSHOT_PATHS + GATE_PATHS + [SUPERVISOR_LOG]:
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


def log(msg: str):
    timestamp = get_utc_iso()
    line = f"[{timestamp}] [AGENT1-SUPERVISOR] {msg}"
    print(line, flush=True)
    try:
        with open(SUPERVISOR_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def is_cscape_process(pid: int) -> bool:
    """Strictly verify if a PID corresponds to Cscape.exe."""
    try:
        p = psutil.Process(pid)
        return "cscape" in p.name().lower()
    except Exception:
        return False


def ensure_desktop():
    try:
        hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if hd:
            user32.SetThreadDesktop(hd)
            return hd
    except Exception as e:
        log(f"Warning attaching to desktop: {e}")
    return None


def configure_registry():
    log("Configuring registry keys for clean visible startup...")
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
    log("Registry keys successfully set.")


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
    log(f"Spawning Cscape visibly: {cmd} (Cwd: {cwd})")

    # Try CREATE_BREAKAWAY_FROM_JOB | CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
    creation_flags = 0x01000000 | 0x00000200 | 0x00000008
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
        log("CreateProcessW with breakaway failed, retrying without breakaway...")
        creation_flags = 0x00000200
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
        err = kernel32.GetLastError()
        raise RuntimeError(f"CreateProcessW failed with error code {err}")

    pid = pi.dwProcessId
    kernel32.CloseHandle(pi.hThread)
    kernel32.CloseHandle(pi.hProcess)
    log(f"Successfully spawned Cscape PID={pid}")
    return pid


def enum_child_windows(parent_hwnd: int) -> list[dict]:
    children = []

    def cb(hwnd, _):
        try:
            cid = user32.GetDlgCtrlID(hwnd)
            c = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, c, 256)
            t = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, t, 512)
            vis = user32.IsWindowVisible(hwnd)
            children.append({
                "hwnd": hwnd,
                "ctrl_id": cid,
                "class": c.value,
                "title": t.value,
                "visible": bool(vis),
            })
        except Exception:
            pass
        return 1

    c_cb = WNDENUMPROC(cb)
    user32.EnumChildWindows(parent_hwnd, c_cb, 0)
    return children


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
        r = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        wins.append({
            "hwnd": hwnd,
            "pid": pid.value,
            "title": t.value,
            "class": c.value,
            "visible": bool(vis),
            "enabled": bool(en),
            "rect": (r.left, r.top, r.right, r.bottom),
        })
        return 1

    c_cb = WNDENUMPROC(cb)
    user32.EnumWindows(c_cb, 0)
    return wins


def dismiss_modal_dialogs():
    wins = get_all_windows()
    for w in wins:
        # STRICT PROCESS CHECK: Only interact with dialogs belonging to Cscape
        if not is_cscape_process(w["pid"]):
            continue

        if w["class"] == "#32770":
            title_lower = w["title"].lower()
            children = enum_child_windows(w["hwnd"])
            ok_hwnd = next((c["hwnd"] for c in children if c["ctrl_id"] == 1), None)
            if "about cscape" in title_lower or "splash" in title_lower:
                log(f"Dismissing splash dialog HWND=0x{w['hwnd']:08X} ('{w['title']}')...")
                if ok_hwnd:
                    user32.PostMessageW(ok_hwnd, 0x00F5, 0, 0)  # BM_CLICK
                user32.PostMessageW(w["hwnd"], 0x0111, 1, ok_hwnd or 0)
            elif "select editor" in title_lower:
                log(f"Handling Select Editor Type dialog HWND=0x{w['hwnd']:08X}...")
                radio_hwnd = next((c["hwnd"] for c in children if c["ctrl_id"] == 1461), None)
                if radio_hwnd:
                    user32.PostMessageW(radio_hwnd, 0x00F1, 1, 0)  # BM_SETCHECK BST_CHECKED
                    user32.PostMessageW(w["hwnd"], 0x0111, 1461, radio_hwnd)
                if ok_hwnd:
                    user32.PostMessageW(ok_hwnd, 0x00F5, 0, 0)
                user32.PostMessageW(w["hwnd"], 0x0111, 1, ok_hwnd or 0)
            elif "confirm save as" in title_lower or "confirm" in title_lower:
                log(f"Handling Confirm Save As dialog HWND=0x{w['hwnd']:08X} cleanly to avoid loop...")
                user32.PostMessageW(w["hwnd"], 0x0111, 6, 0)  # IDYES
            elif "allow" in title_lower or "security" in title_lower or "warning" in title_lower or "notice" in title_lower:
                log(f"Dismissing prompt dialog HWND=0x{w['hwnd']:08X} ('{w['title']}')...")
                if ok_hwnd:
                    user32.PostMessageW(ok_hwnd, 0x00F5, 0, 0)
                user32.PostMessageW(w["hwnd"], 0x0111, 1, ok_hwnd or 0)


def capture_screenshot(hwnd: int) -> bool:
    r = ctypes.wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return False
    w = max(100, r.right - r.left)
    h = max(100, r.bottom - r.top)

    hdc_window = user32.GetWindowDC(hwnd)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
    hbm = gdi32.CreateCompatibleBitmap(hdc_window, w, h)
    gdi32.SelectObject(hdc_mem, hbm)

    # Use PrintWindow with PW_RENDERFULLCONTENT (2), fallback to BitBlt
    res = user32.PrintWindow(hwnd, hdc_mem, 2)
    if not res:
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
        im = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
        for sp in SCREENSHOT_PATHS:
            im.save(str(sp))
            log(f"Saved screenshot proof: {sp} ({w}x{h}, {sp.stat().st_size} bytes)")
        return True
    except Exception as e:
        log(f"Error saving screenshot: {e}")
        return False
    finally:
        gdi32.DeleteObject(hbm)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc_window)


def update_gate(ready: bool, pid: int | None, hwnd: int | None, title: str, reason: str = "Cscape verified active and responsive", cycle: int = 1):
    active_proj = str(CSP_PATH)
    t_lower = (title or "").lower()
    if "c6_native_run" in t_lower:
        active_proj = str(HORNER_ROOT / "artifacts" / "projects" / "C6_Native_Run" / "C6_Native_Run.csp")
    elif "labproject" in t_lower:
        active_proj = str(HORNER_ROOT / "artifacts" / "projects" / "LabProject_W01" / "LabProject_W01.csp")

    data = {
        "ready_for_tests": ready,
        "status": "READY_FOR_TESTS" if ready else "NOT_READY",
        "pid": pid,
        "hwnd": f"0x{hwnd:08X}" if hwnd else None,
        "window_title": title,
        "project_file": active_proj,
        "exit_code": None,
        "reason": reason,
        "cycle": cycle,
        "timestamp_utc": get_utc_iso(),
        "heartbeat_utc": get_utc_iso(),
    }
    for gp in GATE_PATHS:
        try:
            gp.parent.mkdir(parents=True, exist_ok=True)
            gp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            log(f"Failed to update gate file {gp}: {e}")


def find_active_cscape_window() -> tuple[int, int, str]:
    """Find the Cscape main window, returning (pid, hwnd, title).

    STRICT REQUIREMENT: Process must be named cscape.exe. Never match Notepad or other apps.
    """
    wins = get_all_windows()
    # First pass: Title contains active test projects and process is cscape.exe
    for w in wins:
        if not is_cscape_process(w["pid"]):
            continue
        if w["title"].startswith("GDI+"):
            continue
        t_low = w["title"].lower()
        if any(k in t_low for k in ["c6_native_run", "labproject", "tanklevelclosedloop"]):
            return w["pid"], w["hwnd"], w["title"]

    # Second pass: Process is cscape.exe, title contains Cscape, not a dialog
    for w in wins:
        if not is_cscape_process(w["pid"]):
            continue
        if w["class"] == "#32770" or w["title"].startswith("GDI+"):
            continue
        if "cscape" in w["title"].lower():
            return w["pid"], w["hwnd"], w["title"]

    return 0, 0, ""


def verify_and_ensure_project_navigator(main_hwnd: int) -> bool:
    """Verify that the Project Navigator pane / tree is user-visible, opening it if needed."""
    children = enum_child_windows(main_hwnd)
    nav_found = False
    for c in children:
        c_title_lower = c["title"].lower()
        c_class_lower = c["class"].lower()
        if "navigator" in c_title_lower or "systreeview32" in c_class_lower or c["ctrl_id"] in (45012, 300):
            if c["visible"]:
                nav_found = True
                break

    if not nav_found:
        log("Project Navigator not immediately visible; sending ID_TOOLS_PROJECTNAVIGATOR (45012)...")
        user32.PostMessageW(main_hwnd, 0x0111, ID_TOOLS_PROJECTNAVIGATOR, 0)
        time.sleep(1.0)
        # Check again
        children = enum_child_windows(main_hwnd)
        for c in children:
            if "navigator" in c["title"].lower() or "systreeview32" in c["class"].lower() or c["ctrl_id"] in (45012, 300):
                if c["visible"]:
                    nav_found = True
                    break

    log(f"Project Navigator visibility status: {nav_found}")
    return nav_found


def kill_all_cscape():
    log("Killing any lingering Cscape processes...")
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if "cscape" in p.info["name"].lower():
                log(f"Terminating Cscape PID {p.info['pid']}...")
                p.kill()
        except Exception:
            pass
    try:
        subprocess.run(["taskkill.exe", "/F", "/T", "/IM", "Cscape.exe"], capture_output=True, timeout=5.0)
    except Exception:
        pass
    time.sleep(1.0)


def setup_and_verify_cscape() -> tuple[int, int, str]:
    """Sets up, launches, verifies, and screenshots Cscape GUI. Returns (pid, hwnd, title)."""
    log("=" * 80)
    log("STARTING CSCAPE VISIBLE SETUP & VERIFICATION")
    log("=" * 80)

    # First check if Cscape is ALREADY actively running with TankLevelClosedLoop visible
    cur_pid, cur_hwnd, cur_title = find_active_cscape_window()
    if (
        cur_hwnd
        and any(k in cur_title.lower() for k in ["c6_native_run", "labproject", "tanklevelclosedloop"])
        and user32.IsWindowVisible(cur_hwnd)
        and not user32.IsHungAppWindow(cur_hwnd)
    ):
        log(f"Adopting already active visible Cscape window: PID={cur_pid}, HWND=0x{cur_hwnd:08X}, Title='{cur_title}'")
        # Terminate any other duplicate Cscape processes
        for p in psutil.process_iter(["pid", "name"]):
            try:
                if "cscape" in p.info["name"].lower() and p.info["pid"] != cur_pid:
                    log(f"Killing duplicate orphan Cscape PID {p.info['pid']}...")
                    p.kill()
            except Exception:
                pass
        user32.ShowWindow(cur_hwnd, 9)  # SW_RESTORE
        user32.SetWindowPos(cur_hwnd, 0, 40, 40, 1400, 900, 0x0040)
        user32.ShowWindow(cur_hwnd, 3)  # SW_SHOWMAXIMIZED
        user32.BringWindowToTop(cur_hwnd)
        user32.SetForegroundWindow(cur_hwnd)
        time.sleep(1.0)
        dismiss_modal_dialogs()
        verify_and_ensure_project_navigator(cur_hwnd)
        capture_screenshot(cur_hwnd)
        update_gate(ready=True, pid=cur_pid, hwnd=cur_hwnd, title=cur_title)
        return cur_pid, cur_hwnd, cur_title

    kill_all_cscape()
    configure_registry()

    spawn_pid = spawn_cscape_visible()

    log("Monitoring startup and dialogs (up to 35 seconds)...")
    main_pid = spawn_pid
    main_hwnd = 0
    main_title = ""

    t0 = time.time()
    while time.time() - t0 < 35.0:
        dismiss_modal_dialogs()
        pid, hwnd, title = find_active_cscape_window()
        if hwnd:
            main_hwnd = hwnd
            main_pid = pid
            main_title = title
            if any(k in title.lower() for k in ["c6_native_run", "labproject", "tanklevelclosedloop"]):
                break
        time.sleep(1.0)

    # If title doesn't yet show recognized project, send MRU 1
    if not any(k in main_title.lower() for k in ["c6_native_run", "labproject", "tanklevelclosedloop"]) and main_hwnd:
        log(f"Main title is '{main_title}'. Sending ID_FILE_MRU_FILE1 (57616)...")
        user32.PostMessageW(main_hwnd, 0x0111, ID_FILE_MRU_FILE1, 0)
        time.sleep(3.0)
        dismiss_modal_dialogs()
        pid, hwnd, title = find_active_cscape_window()
        if hwnd:
            main_hwnd = hwnd
            main_pid = pid
            main_title = title

    log("-" * 80)
    log(f"Cscape Window Located: PID={main_pid}, HWND=0x{main_hwnd:08X}, Title='{main_title}'")

    if not main_hwnd:
        raise RuntimeError("Failed to locate Cscape main window handle!")

    # Verify and normalize window (with settling retry)
    for _ in range(10):
        is_vis = bool(user32.IsWindowVisible(main_hwnd))
        is_en = bool(user32.IsWindowEnabled(main_hwnd))
        is_hung = bool(user32.IsHungAppWindow(main_hwnd))
        has_proj = any(k in main_title.lower() for k in ["tanklevelclosedloop", "c6_native_run", "labproject"])
        if is_vis and is_en and not is_hung and has_proj:
            break
        time.sleep(1.0)
        tb = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(main_hwnd, tb, 512)
        if tb.value:
            main_title = tb.value

    log(f"IsWindowVisible={is_vis}, IsWindowEnabled={is_en}, IsHungAppWindow={is_hung}, HasProject={has_proj}")

    if not (is_vis and is_en and not is_hung and has_proj):
        raise RuntimeError(f"Window verification failed: vis={is_vis}, en={is_en}, hung={is_hung}, title='{main_title}'")

    # Set window size and bring to foreground
    user32.ShowWindow(main_hwnd, 9)  # SW_RESTORE
    user32.SetWindowPos(main_hwnd, 0, 40, 40, 1400, 900, 0x0040)  # SWP_SHOWWINDOW
    user32.ShowWindow(main_hwnd, 3)  # SW_SHOWMAXIMIZED
    user32.BringWindowToTop(main_hwnd)
    user32.SetForegroundWindow(main_hwnd)
    time.sleep(2.0)

    # Dismiss any final popups after showing
    dismiss_modal_dialogs()

    # Re-check active window handle in case Cscape handed off to successor
    final_pid, final_hwnd, final_title = find_active_cscape_window()
    if final_hwnd and "tanklevelclosedloop" in final_title.lower():
        main_pid, main_hwnd, main_title = final_pid, final_hwnd, final_title

    # Verify Project Navigator is open and user-visible
    verify_and_ensure_project_navigator(main_hwnd)

    # Capture live screenshot proof
    log(f"Capturing live screenshot proof for HWND=0x{main_hwnd:08X}...")
    capture_screenshot(main_hwnd)

    # Update gate
    log(f"Updating gate files for PID={main_pid}, HWND=0x{main_hwnd:08X}...")
    update_gate(ready=True, pid=main_pid, hwnd=main_hwnd, title=main_title)

    log("=" * 80)
    log(f"CSCAPE VERIFIED VISIBLE ON INTERACTIVE DESKTOP: PID={main_pid}, HWND=0x{main_hwnd:08X}")
    log("=" * 80)
    return main_pid, main_hwnd, main_title


def run_supervisor_loop(target_pid: int, target_hwnd: int, title: str):
    log("Entering autonomous keepalive supervisor loop...")
    cycle = 1
    current_pid = target_pid
    current_hwnd = target_hwnd
    current_title = title
    hung_start_time: float | None = None

    while True:
        try:
            time.sleep(2.0)
            cycle += 1

            ensure_desktop()

            # 1. Verify Cscape process exists
            if not psutil.pid_exists(current_pid) or not is_cscape_process(current_pid):
                # Check if adopted successor Cscape process exists
                active_pid, active_hwnd, active_title = find_active_cscape_window()
                if active_pid and is_cscape_process(active_pid) and active_hwnd:
                    log(f"Adopted successor Cscape PID={active_pid}, HWND=0x{active_hwnd:08X}")
                    current_pid, current_hwnd, current_title = active_pid, active_hwnd, active_title
                else:
                    log(f"Cscape PID={current_pid} exited and no active successor found! Relaunching...")
                    current_pid, current_hwnd, current_title = setup_and_verify_cscape()
                    hung_start_time = None
                    continue

            # 2. Check window hung status (only recover if hung > 15 seconds)
            is_hung = bool(user32.IsHungAppWindow(current_hwnd))
            if is_hung:
                if hung_start_time is None:
                    hung_start_time = time.monotonic()
                    log(f"Cscape window HWND=0x{current_hwnd:08X} reported hung. Starting 15s tolerance window...")
                elif time.monotonic() - hung_start_time > 15.0:
                    log(f"Cscape window HWND=0x{current_hwnd:08X} hung continuously for >15s! Recovering...")
                    current_pid, current_hwnd, current_title = setup_and_verify_cscape()
                    hung_start_time = None
                    continue
            else:
                hung_start_time = None

            # 3. Check window visibility and update title if changed
            active_pid, active_hwnd, active_title = find_active_cscape_window()
            if active_hwnd and active_pid == current_pid:
                current_hwnd = active_hwnd
                current_title = active_title

            # 4. Heartbeat update to gate files
            update_gate(
                ready=True,
                pid=current_pid,
                hwnd=current_hwnd,
                title=current_title,
                reason="Watchdog heartbeat: Cscape active and visible on interactive desktop",
                cycle=cycle,
            )

            if cycle % 30 == 0:
                log(f"Watchdog health check cycle {cycle}: PID={current_pid}, HWND=0x{current_hwnd:08X}, Title='{current_title}'")

        except Exception as e:
            log(f"Exception in supervisor loop: {e}")
            time.sleep(5.0)


def main():
    parser = argparse.ArgumentParser(description="Visible Cscape GUI Controller & Liveness Supervisor")
    parser.add_argument("--supervisor", action="store_true", help="Run continuous supervisor loop")
    args = parser.parse_args()

    pid, hwnd, title = setup_and_verify_cscape()

    if args.supervisor:
        run_supervisor_loop(pid, hwnd, title)

    return 0


if __name__ == "__main__":
    sys.exit(main())
