#!/usr/bin/env python3
"""Step 135: Cscape Keepalive Long-Uptime Milestone (5,000+ Seconds / 80+ Minutes) on Active PID 14580.

Verifies:
1. Continuous uptime of active Cscape PID 14580 reaching >= 5000.0s (83.3+ minutes) without interruption.
2. Responsiveness polling during wait: assert process running, IsHungAppWindow = False, SendMessageTimeoutW ping = True.
3. High-resolution screenshot proof captured and verified (>50KB) across both workspace roots.
4. Process health metrics: memory rss, thread count, cpu percent, window rect, window title.
5. Strict PLC download lockout (ID_CONTROLLER_DOWNLOAD = 32827 blocked, zero physical PLC flashing).
6. Zero Straton K5 legacy dependencies.
7. Keepalive log appended, detailed log saved, and step 135 checkpoint recorded across both roots.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import datetime
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict

import psutil
from PIL import Image

USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()

for r in [USER_ROOT, HORNER_ROOT]:
    if str(r) not in sys.path:
        sys.path.insert(0, str(r))

from src.cscape.gate import assert_cscape_live, attach_thread_desktop, get_gate_status
from src.cscape.safety import (
    ID_CONTROLLER_DOWNLOAD,
    ID_PLC_DOWNLOAD,
    CscapeSafetyViolationError,
    intercept_download_command,
)

TARGET_PID = 14580
TARGET_UPTIME_SECONDS = 5000.0

SCREENSHOT_PATHS = [
    USER_ROOT / "artifacts" / "screenshots" / "live_cscape_tank_level_stay_open_pid14580_5000s.png",
    HORNER_ROOT / "artifacts" / "screenshots" / "live_cscape_tank_level_stay_open_pid14580_5000s.png",
]

CHECKPOINT_PATHS = [
    USER_ROOT / "artifacts" / "checkpoints" / "step135_cscape_stay_open_5000s_checkpoint.json",
    HORNER_ROOT / "artifacts" / "checkpoints" / "step135_cscape_stay_open_5000s_checkpoint.json",
]

LOG_PATHS = [
    USER_ROOT / "artifacts" / "logs" / "cscape_gui_stability_pid14580_5000s.json",
    HORNER_ROOT / "artifacts" / "logs" / "cscape_gui_stability_pid14580_5000s.json",
]

KEEPALIVE_LOGS = [
    USER_ROOT / "artifacts" / "logs" / "cscape_keepalive.log",
    HORNER_ROOT / "artifacts" / "logs" / "cscape_keepalive.log",
]

for p in SCREENSHOT_PATHS + CHECKPOINT_PATHS + LOG_PATHS + KEEPALIVE_LOGS:
    p.parent.mkdir(parents=True, exist_ok=True)


def init_win32_apis():
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowDC.argtypes = [ctypes.c_void_p]
    user32.GetWindowDC.restype = ctypes.c_void_p
    user32.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.IsHungAppWindow.argtypes = [wintypes.HWND]
    user32.IsHungAppWindow.restype = wintypes.BOOL
    user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_ulong)
    ]
    user32.SendMessageTimeoutW.restype = ctypes.c_long

    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.GetDIBits.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint
    ]
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]

    return user32, gdi32


def ping_cscape_window(user32, hwnd: int) -> bool:
    attach_thread_desktop(hwnd)
    res_val = ctypes.c_ulong(0)
    # SMTO_ABORTIFHUNG = 0x0002, timeout = 1000ms, WM_NULL = 0x0000
    res = user32.SendMessageTimeoutW(hwnd, 0, 0, 0, 0x0002, 1000, ctypes.byref(res_val))
    return bool(res != 0)


def capture_screenshot(user32, gdi32, hwnd: int) -> int:
    attach_thread_desktop(hwnd)
    user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE = 3
    user32.BringWindowToTop(hwnd)
    time.sleep(0.5)

    h_val = ctypes.c_void_p(hwnd)
    r = wintypes.RECT()
    user32.GetWindowRect(h_val, ctypes.byref(r))
    w = max(10, r.right - r.left)
    h = max(10, r.bottom - r.top)

    hdc_window = user32.GetWindowDC(h_val)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
    hbm = gdi32.CreateCompatibleBitmap(hdc_window, w, h)
    gdi32.SelectObject(hdc_mem, hbm)

    user32.PrintWindow(h_val, hdc_mem, 2)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
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

    im = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")

    saved_size = 0
    for sp in SCREENSHOT_PATHS:
        im.save(str(sp))
        saved_size = sp.stat().st_size
        print(f"Screenshot saved: {sp} ({w}x{h}, {saved_size} bytes)")

    gdi32.DeleteObject(hbm)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(h_val, hdc_window)

    assert saved_size > 50000, f"Screenshot size ({saved_size} bytes) is not > 50KB!"
    return saved_size


def log_keepalive(msg: str) -> None:
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    line = f"[{now_iso}] {msg}"
    print(line, flush=True)
    for kl in KEEPALIVE_LOGS:
        try:
            with open(kl, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


def main() -> int:
    print("=" * 80)
    print("STEP 135: CSCAPE KEEPALIVE LONG-UPTIME MILESTONE (5,000+s / 80+m)")
    print(f"Target PID: {TARGET_PID} | Target Continuous Uptime: {TARGET_UPTIME_SECONDS}s")
    print("=" * 80)

    user32, gdi32 = init_win32_apis()

    gate = assert_cscape_live()
    cur_pid = gate["pid"]
    assert cur_pid == TARGET_PID, f"Expected PID {TARGET_PID}, but gate returned {cur_pid}"

    raw_h = gate.get("hwnd", "0x0")
    cur_hwnd = int(raw_h, 16) if isinstance(raw_h, str) and raw_h.startswith("0x") else int(raw_h or 0)
    attach_thread_desktop(cur_hwnd)

    proc = psutil.Process(cur_pid)
    assert proc.is_running(), f"Cscape PID={cur_pid} is not running!"
    assert "cscape" in proc.name().lower(), f"Process {cur_pid} name '{proc.name()}' is not Cscape.exe!"

    # Polling loop until >= 5000.0s continuous uptime
    start_poll = time.time()
    while True:
        uptime = time.time() - proc.create_time()
        assert proc.is_running(), f"Cscape PID={cur_pid} died during keepalive polling!"

        is_hung = bool(user32.IsHungAppWindow(cur_hwnd))
        assert not is_hung, f"Cscape window HWND=0x{cur_hwnd:08X} became hung!"

        ping_ok = ping_cscape_window(user32, cur_hwnd)
        assert ping_ok, f"Cscape window HWND=0x{cur_hwnd:08X} failed SendMessageTimeoutW ping!"

        if uptime >= TARGET_UPTIME_SECONDS:
            print(f"\n>>> REACHED 5,000s MILESTONE! Uptime = {uptime:.2f}s ({uptime/60:.2f} minutes) <<<")
            break

        remaining = TARGET_UPTIME_SECONDS - uptime
        print(
            f"[POLLING] Uptime={uptime:.2f}s ({uptime/60:.2f}m) | "
            f"Remaining={remaining:.2f}s | Hung={is_hung} | Ping={ping_ok}"
        )
        sleep_dur = min(10.0, max(1.0, remaining))
        time.sleep(sleep_dur)

    # 5,000s milestone reached!
    final_uptime = time.time() - proc.create_time()
    uptime_minutes = final_uptime / 60.0

    # Ensure window is visible, active, and maximized for evidence
    import win32gui
    title = win32gui.GetWindowText(cur_hwnd)
    is_hung = bool(user32.IsHungAppWindow(cur_hwnd))
    is_vis = bool(win32gui.IsWindowVisible(cur_hwnd))
    ping_ok = ping_cscape_window(user32, cur_hwnd)

    assert "tanklevel" in title.lower(), f"Title '{title}' does not contain 'TankLevel'!"
    assert not is_hung, f"Cscape window HWND=0x{cur_hwnd:08X} is hung!"
    assert is_vis, f"Cscape window HWND=0x{cur_hwnd:08X} is not visible!"
    assert ping_ok, "SendMessageTimeoutW ping failed at milestone!"

    ss_size = capture_screenshot(user32, gdi32, cur_hwnd)

    # Gather full process and window metrics
    mem_info = proc.memory_info()
    memory_mb = round(mem_info.rss / (1024 * 1024), 2)
    thread_count = proc.num_threads()
    cpu_pct = proc.cpu_percent(interval=0.2)

    r = wintypes.RECT()
    user32.GetWindowRect(ctypes.c_void_p(cur_hwnd), ctypes.byref(r))
    window_rect = {
        "left": r.left,
        "top": r.top,
        "right": r.right,
        "bottom": r.bottom,
        "width": r.right - r.left,
        "height": r.bottom - r.top,
    }

    # Mandate: Strict PLC Lockout Enforcement Verification
    print("\n[SAFETY] Enforcing physical PLC lockout (ID_CONTROLLER_DOWNLOAD = 32827)...")
    assert ID_CONTROLLER_DOWNLOAD == 32827, "ID_CONTROLLER_DOWNLOAD is not 32827!"
    plc_lockout_enforced = False
    try:
        intercept_download_command(ID_CONTROLLER_DOWNLOAD)
    except CscapeSafetyViolationError:
        plc_lockout_enforced = True
    assert plc_lockout_enforced, "Physical controller download lockout failed to intercept!"

    # Mandate: Zero Straton K5 legacy dependencies
    straton_binaries = ["k5bus.exe", "k5edit.exe", "k5run.exe", "k5vm.exe", "k5cmd.exe", "t5.exe"]
    active_straton = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            pname = p.info["name"].lower()
            if any(sb in pname for sb in straton_binaries):
                active_straton.append(p.info)
        except Exception:
            pass
    assert len(active_straton) == 0, f"Found active Straton K5 processes: {active_straton}"

    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    evidence = {
        "step": 135,
        "name": "step135_cscape_stay_open_5000s_checkpoint",
        "status": "PASSED",
        "target_milestone_seconds": TARGET_UPTIME_SECONDS,
        "achieved_continuous_uptime_seconds": round(final_uptime, 2),
        "achieved_continuous_uptime_minutes": round(uptime_minutes, 2),
        "timestamp_utc": now_iso,
        "cscape_pid": cur_pid,
        "hwnd": f"0x{cur_hwnd:08X}",
        "cscape_title": title,
        "project_file": r"C:\Users\ArmandoSilva\artifacts\projects\TankLevelClosedLoop\TankLevelClosedLoop.csp",
        "is_hung": is_hung,
        "is_visible": is_vis,
        "ping_responsive": ping_ok,
        "cpu_percent": cpu_pct,
        "memory_mb": memory_mb,
        "thread_count": thread_count,
        "window_rect": window_rect,
        "screenshot_proof": str(SCREENSHOT_PATHS[0]),
        "screenshot_size_bytes": ss_size,
        "plc_lockout_enforced": plc_lockout_enforced,
        "zero_straton_dependencies": True,
        "fail_closed_gate_synced": True,
    }

    for lp in LOG_PATHS:
        lp.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(f"Log recorded: {lp}")

    for cp in CHECKPOINT_PATHS:
        cp.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(f"Checkpoint recorded: {cp}")

    log_keepalive(
        f"[STEP135_COMPLETED] PID={cur_pid} | HWND=0x{cur_hwnd:08X} | "
        f"Uptime={final_uptime:.2f}s ({uptime_minutes:.2f}m) | Hung={is_hung} | "
        f"Ping={ping_ok} | ScreenshotSize={ss_size}B | "
        f"Cscape Keepalive Long-Uptime Milestone (5,000+ Seconds / 80+ Minutes) verified!"
    )

    print("\n" + "=" * 80)
    print("STEP 135 PASSED: Continuous Cscape keepalive milestone 5,000+ seconds reached!")
    print(f"Achieved Uptime: {final_uptime:.2f}s ({uptime_minutes:.2f} minutes) on PID {cur_pid}")
    print(f"Screenshot verified: {ss_size} bytes (>50KB)")
    print(f"PLC Lockout Enforced: {plc_lockout_enforced}")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
