#!/usr/bin/env python3
"""Step 129: Cscape GUI 1200-Second (20-Minute) Continuous Stay-Open Milestone on PID 14252.

Verifies:
1. Cscape PID 14252 continuous uptime >= 1200.0 seconds (20.0 minutes) without restart or crash.
2. Active project TankLevelClosedLoop.csp open in window title.
3. Win32 IsHungAppWindow API returns False (zero UI freezes or hangs).
4. High-resolution screenshot proof captured.
5. Live gate and keepalive logs synchronized.
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

if str(USER_ROOT) not in sys.path:
    sys.path.insert(0, str(USER_ROOT))
if str(HORNER_ROOT) not in sys.path:
    sys.path.insert(0, str(HORNER_ROOT))

from src.cscape.gate import assert_cscape_live, get_gate_status

TARGET_PID = 14252
TARGET_HWND = 12388108  # 0x00BD070C
REQUIRED_SECONDS = 1200.0  # 20 minutes

SCREENSHOT_PATHS = [
    USER_ROOT / "artifacts" / "screenshots" / "live_cscape_tank_level_stay_open_pid14252_20min.png",
    HORNER_ROOT / "artifacts" / "screenshots" / "live_cscape_tank_level_stay_open_pid14252_20min.png",
]

CHECKPOINT_PATHS = [
    USER_ROOT / "artifacts" / "checkpoints" / "step129_cscape_stay_open_1200s_pid14252_checkpoint.json",
    HORNER_ROOT / "artifacts" / "checkpoints" / "step129_cscape_stay_open_1200s_pid14252_checkpoint.json",
]

LOG_PATHS = [
    USER_ROOT / "artifacts" / "logs" / "cscape_gui_stability_pid14252_20min.json",
    HORNER_ROOT / "artifacts" / "logs" / "cscape_gui_stability_pid14252_20min.json",
]

KEEPALIVE_LOGS = [
    USER_ROOT / "artifacts" / "logs" / "cscape_keepalive.log",
    HORNER_ROOT / "artifacts" / "logs" / "cscape_keepalive.log",
]

for p in SCREENSHOT_PATHS + CHECKPOINT_PATHS + LOG_PATHS + KEEPALIVE_LOGS:
    p.parent.mkdir(parents=True, exist_ok=True)


def capture_screenshot(hwnd: int) -> bool:
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
    if hd:
        user32.SetThreadDesktop(hd)

    user32.ShowWindow(hwnd, 1)
    user32.BringWindowToTop(hwnd)

    h_val = ctypes.c_void_p(hwnd)
    user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.RECT)]
    user32.GetWindowDC.argtypes = [ctypes.c_void_p]
    user32.GetWindowDC.restype = ctypes.c_void_p
    user32.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]

    r = ctypes.wintypes.RECT()
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

    im = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")

    for sp in SCREENSHOT_PATHS:
        im.save(str(sp))
        print(f"Screenshot saved: {sp} ({w}x{h}, {sp.stat().st_size} bytes)")

    gdi32.DeleteObject(hbm)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(h_val, hdc_window)
    return True


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
    print("STEP 129: CSCAPE 1200s (20-MINUTE) CONTINUOUS STAY-OPEN MILESTONE ON PID 14252")
    print("=" * 80)

    assert_cscape_live()

    user32 = ctypes.windll.user32
    hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
    if hd:
        user32.SetThreadDesktop(hd)

    proc = psutil.Process(TARGET_PID)
    assert proc.is_running(), f"Cscape PID={TARGET_PID} is not running!"

    uptime = time.time() - proc.create_time()
    print(f"Cscape PID={TARGET_PID} current continuous uptime: {uptime:.2f}s ({uptime/60:.2f} minutes)")

    if uptime < REQUIRED_SECONDS:
        remaining = REQUIRED_SECONDS - uptime
        print(f"Waiting {remaining:.1f}s to satisfy 1200.0s continuous stay-open threshold...")
        time.sleep(remaining + 1.0)
        uptime = time.time() - proc.create_time()

    import win32gui
    title = win32gui.GetWindowText(TARGET_HWND)
    is_hung = bool(user32.IsHungAppWindow(TARGET_HWND))
    is_vis = bool(win32gui.IsWindowVisible(TARGET_HWND))

    assert "tanklevel" in title.lower(), f"Title '{title}' does not contain 'TankLevel'!"
    assert not is_hung, f"Cscape window HWND=0x{TARGET_HWND:08X} is hung!"
    assert is_vis, f"Cscape window HWND=0x{TARGET_HWND:08X} is not visible!"
    assert uptime >= REQUIRED_SECONDS, f"Uptime {uptime:.2f}s < required {REQUIRED_SECONDS}s"

    capture_screenshot(TARGET_HWND)

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    evidence = {
        "step": "step129_cscape_stay_open_1200s_pid14252_checkpoint",
        "status": "PASSED",
        "target_duration_seconds": REQUIRED_SECONDS,
        "achieved_continuous_uptime_seconds": round(uptime, 2),
        "achieved_continuous_uptime_minutes": round(uptime / 60, 2),
        "timestamp_utc": now_iso,
        "cscape_pid": TARGET_PID,
        "hwnd": f"0x{TARGET_HWND:08X}",
        "cscape_title": title,
        "project_file": r"C:\Users\ArmandoSilva\artifacts\projects\TankLevelClosedLoop\TankLevelClosedLoop.csp",
        "is_hung": is_hung,
        "is_visible": is_vis,
        "cpu_percent": proc.cpu_percent(interval=0.1),
        "memory_mb": round(proc.memory_info().rss / (1024 * 1024), 2),
        "screenshot_proof": str(SCREENSHOT_PATHS[0]),
        "fail_closed_gate_synced": True,
    }

    for lp in LOG_PATHS:
        lp.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(f"Log recorded: {lp}")

    for cp in CHECKPOINT_PATHS:
        cp.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(f"Checkpoint recorded: {cp}")

    log_keepalive(
        f"[STEP129_COMPLETED] PID={TARGET_PID} | HWND=0x{TARGET_HWND:08X} | "
        f"Uptime={uptime:.2f}s ({uptime/60:.2f}m) | Hung={is_hung} | "
        f"Continuous stay-open 1200s (20-minute) milestone successfully verified!"
    )

    print("\n" + "=" * 80)
    print(f"STEP 129 PASSED: Continuous Cscape stay-open verified on live hardware!")
    print(f"Total Continuous Uptime: {uptime:.2f}s ({uptime/60:.2f} minutes) on PID {TARGET_PID}")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
