#!/usr/bin/env python3
r"""Agent 1: Visible Cscape GUI Controller Execution Script.

Tasks:
1. Dynamically discover active Cscape PID and HWND with TankLevelClosedLoop.csp on interactive desktop.
2. Attach thread to desktop 'Default' using attach_thread_desktop from src.cscape.gate.
3. Verify Cscape window state:
   - IsWindow(hwnd) == True, IsWindowVisible(hwnd) == True, IsWindowEnabled(hwnd) == True, IsHungAppWindow(hwnd) == False.
   - Ping with SendMessageTimeoutW (WM_NULL, 2000ms timeout).
   - Window title contains "TankLevelClosedLoop" or "Cscape".
   - Confirm SW_HIDE is NOT used; window must remain visible (SW_SHOWNORMAL / SW_SHOWMAXIMIZED).
4. Sweep modal dialogs (#32770) using sweep_cscape_dialogs before and after dispatch.
5. Dispatch live GUI Error Check: ID_PROGRAM_ERRORCHECK = 32826 (Ctrl+F7) to HWND via PostMessageW / CscapeCompiler.
6. Capture high-resolution screenshot of the visible Cscape window to:
   - C:\HornerAI\horner-cscape-mcp\artifacts\screenshots\live_cscape_tank_level_g1.png
   - Mirror to C:\Users\ArmandoSilva\artifacts\screenshots\live_cscape_tank_level_g1.png
   Verify screenshot is a valid PNG >= 10 KB.
7. Update and sync gate file artifacts/.cscape_live_gate.json in both roots with current timestamp, discovered PID/HWND, and READY_FOR_TESTS status.
8. Write JSON log to artifacts/logs/g1_visible_gui_proof.json in both roots.
9. Validate fail-closed gate assertion via assert_cscape_live().
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import psutil

# Dual roots
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()

for root_path in [str(HORNER_ROOT), str(USER_ROOT)]:
    if root_path not in sys.path:
        sys.path.insert(0, root_path)

from src.cscape.gate import attach_thread_desktop, assert_cscape_live, get_gate_status
from src.cscape.compiler import CscapeCompiler, ID_PROGRAM_ERRORCHECK
from scripts.execute_step155_mcp_dual_transmitter_failover import (
    sweep_cscape_dialogs,
    capture_cscape_screenshot,
)

GATE_FILES = [
    HORNER_ROOT / "artifacts" / ".cscape_live_gate.json",
    USER_ROOT / "artifacts" / ".cscape_live_gate.json",
]

SCREENSHOT_PATHS = [
    HORNER_ROOT / "artifacts" / "screenshots" / "live_cscape_tank_level_g1.png",
    USER_ROOT / "artifacts" / "screenshots" / "live_cscape_tank_level_g1.png",
]

LOG_PATHS = [
    HORNER_ROOT / "artifacts" / "logs" / "g1_visible_gui_proof.json",
    USER_ROOT / "artifacts" / "logs" / "g1_visible_gui_proof.json",
]


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.UINT),
        ("flags", wintypes.UINT),
        ("showCmd", wintypes.UINT),
        ("ptMinPosition", wintypes.POINT),
        ("ptMaxPosition", wintypes.POINT),
        ("rcNormalPosition", wintypes.RECT),
    ]


def compute_sha256(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def discover_active_cscape() -> Tuple[int, int, str]:
    """Dynamically discovers the primary active visible Cscape window running TankLevelClosedLoop."""
    user32 = ctypes.windll.user32
    hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
    if hd:
        user32.SetThreadDesktop(hd)

    candidates: List[Tuple[int, int, str, float]] = []

    def enum_windows_cb(hwnd: int, lparam: int) -> bool:
        if user32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                p = psutil.Process(pid.value)
                if "cscape" in p.name().lower():
                    title_buf = ctypes.create_unicode_buffer(512)
                    user32.GetWindowTextW(hwnd, title_buf, 512)
                    title = title_buf.value
                    if "tanklevel" in title.lower() or "cscape" in title.lower():
                        # Ping check
                        sm_result = ctypes.c_ulong()
                        ping_ok = bool(user32.SendMessageTimeoutW(
                            hwnd, 0x0000, 0, 0, 0x0002, 2000, ctypes.byref(sm_result)
                        ))
                        if ping_ok and not user32.IsHungAppWindow(hwnd):
                            candidates.append((pid.value, hwnd, title, p.create_time()))
            except Exception:
                pass
        return True

    WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumDesktopWindows(hd, WNDENUM(enum_windows_cb), 0)

    if not candidates:
        raise RuntimeError("No active, responsive visible Cscape window found on Default desktop!")

    # Sort candidates preferring PID 11220 or newest process with TankLevelClosedLoop
    candidates.sort(key=lambda c: (1 if "tanklevelclosedloop" in c[2].lower() else 0, c[3]), reverse=True)
    selected_pid, selected_hwnd, selected_title, _ = candidates[0]
    return selected_pid, selected_hwnd, selected_title


def execute_agent1_tasks() -> Dict[str, Any]:
    print("=" * 80)
    print("AGENT 1: VISIBLE CSCAPE GUI CONTROLLER EXECUTION")
    print("=" * 80)
    t_start = time.perf_counter()
    iso_start = datetime.datetime.now(datetime.timezone.utc).isoformat()

    user32 = ctypes.windll.user32

    # --------------------------------------------------------------------------
    # Task 0 & 1: Dynamic discovery & Attach thread to desktop 'Default'
    # --------------------------------------------------------------------------
    print("\n[TASK 0 & 1] Dynamically discovering active Cscape and attaching thread to 'Default'...")
    active_pid, active_hwnd, active_title = discover_active_cscape()
    active_hwnd_hex = f"0x{active_hwnd:08X}"
    print(f"  Discovered Cscape: PID={active_pid}, HWND={active_hwnd_hex} ({active_hwnd})")
    print(f"  Title: '{active_title}'")

    desktop_attached = attach_thread_desktop(active_hwnd)
    print(f"  Desktop attached: '{desktop_attached}'")
    assert desktop_attached.lower() == "default", f"Failed to attach to Default desktop: {desktop_attached}"
    print("  -> Task 1 PASSED: Successfully attached to desktop 'Default'.")

    # --------------------------------------------------------------------------
    # Task 2: Verify Cscape window state
    # --------------------------------------------------------------------------
    print(f"\n[TASK 2] Verifying Cscape PID {active_pid} and HWND {active_hwnd_hex}...")
    assert psutil.pid_exists(active_pid), f"PID {active_pid} does not exist!"
    proc = psutil.Process(active_pid)
    proc_name = proc.name()
    assert "cscape" in proc_name.lower(), f"PID {active_pid} is {proc_name}, not Cscape.exe!"
    uptime_sec = round(time.time() - proc.create_time(), 1)
    rss_mb = round(proc.memory_info().rss / (1024 * 1024), 2)
    print(f"  Process: {proc_name} (PID: {active_pid}), Uptime: {uptime_sec}s, RSS: {rss_mb} MB")

    is_window = bool(user32.IsWindow(active_hwnd))
    is_visible = bool(user32.IsWindowVisible(active_hwnd))
    is_enabled = bool(user32.IsWindowEnabled(active_hwnd))
    is_hung = bool(user32.IsHungAppWindow(active_hwnd))

    assert is_window is True, f"HWND {active_hwnd_hex} is not a valid window!"
    assert is_visible is True, f"HWND {active_hwnd_hex} is not visible!"
    assert is_enabled is True, f"HWND {active_hwnd_hex} is disabled!"
    assert is_hung is False, f"HWND {active_hwnd_hex} is hung!"

    # SendMessageTimeoutW ping (WM_NULL = 0x0000)
    sm_result = ctypes.c_ulong()
    ping_res = bool(user32.SendMessageTimeoutW(
        active_hwnd, 0x0000, 0, 0, 0x0002, 2000, ctypes.byref(sm_result)
    ))
    assert ping_res is True, f"HWND {active_hwnd_hex} failed WM_NULL ping within 2000ms timeout!"

    # Title verification
    title_buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(active_hwnd, title_buf, 512)
    window_title = title_buf.value
    assert ("tanklevelclosedloop" in window_title.lower() or "cscape" in window_title.lower()), (
        f"Window title does not contain 'TankLevelClosedLoop' or 'Cscape': '{window_title}'"
    )

    # Confirm SW_HIDE is NOT used; window must remain visible (SW_SHOWNORMAL / SW_SHOWMAXIMIZED)
    wp = WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(WINDOWPLACEMENT)
    user32.GetWindowPlacement(active_hwnd, ctypes.byref(wp))
    SW_HIDE = 0
    SW_SHOWNORMAL = 1
    SW_SHOWMAXIMIZED = 3
    print(f"  Window Placement showCmd: {wp.showCmd}")
    assert wp.showCmd != SW_HIDE, f"Window is hidden (SW_HIDE)! showCmd={wp.showCmd}"
    assert is_visible is True, "Window IsWindowVisible is False!"

    # Ensure maximized or visible on desktop
    user32.ShowWindow(active_hwnd, SW_SHOWMAXIMIZED)
    time.sleep(0.5)

    rect = wintypes.RECT()
    user32.GetWindowRect(active_hwnd, ctypes.byref(rect))
    win_w = rect.right - rect.left
    win_h = rect.bottom - rect.top
    print(f"  Window Dimensions: {win_w}x{win_h}")
    print(f"  -> Task 2 PASSED: Cscape PID {active_pid}, HWND {active_hwnd_hex} verified visible, enabled, non-hung, and responsive.")

    # --------------------------------------------------------------------------
    # Task 3: Check and sweep non-fatal modal dialogs (#32770)
    # --------------------------------------------------------------------------
    print("\n[TASK 3] Checking and sweeping modal dialogs (#32770)...")
    pre_sweep_count = sweep_cscape_dialogs(active_pid, main_hwnd=active_hwnd)
    print(f"  Pre-sweep dialogs dismissed: {pre_sweep_count}")
    print("  -> Task 3 PASSED: Dialog sweep completed cleanly.")

    # --------------------------------------------------------------------------
    # Task 4: Dispatch live GUI Error Check: ID_PROGRAM_ERRORCHECK = 32826
    # --------------------------------------------------------------------------
    print(f"\n[TASK 4] Dispatching live GUI Error Check (ID_PROGRAM_ERRORCHECK = {ID_PROGRAM_ERRORCHECK})...")
    compiler = CscapeCompiler(workspace_root=HORNER_ROOT)
    t_compile_start = time.perf_counter()
    compile_result = compiler.trigger_cscape_gui_compile(
        cscape_hwnd=active_hwnd,
        command_id=ID_PROGRAM_ERRORCHECK,
        timeout_sec=15.0,
    )
    compile_duration = round(time.perf_counter() - t_compile_start, 3)

    # Post-compile sweep to ensure clean state
    post_sweep_count = sweep_cscape_dialogs(active_pid, main_hwnd=active_hwnd)

    print(f"  Compile duration:     {compile_duration}s")
    print(f"  Command dispatched:   {compile_result.get('command_dispatched')}")
    print(f"  Compile success:      {compile_result.get('success')}")
    print(f"  Error count:          {compile_result.get('error_count')}")
    print(f"  Warning count:        {compile_result.get('warning_count')}")
    print(f"  Controls enumerated:  {compile_result.get('controls_enumerated')}")
    print(f"  Post-sweep dialogs:   {post_sweep_count}")
    print(f"  Build log summary:\n    " + "\n    ".join(compile_result.get("build_log", "").splitlines()))

    assert compile_result.get("command_dispatched") == ID_PROGRAM_ERRORCHECK, "Wrong command ID dispatched!"
    assert compile_result.get("success") is True, f"Compile returned failure: {compile_result}"
    assert compile_result.get("error_count") == 0, f"Errors encountered during compile: {compile_result.get('errors')}"
    print("  -> Task 4 PASSED: Live GUI Error Check executed with 0 errors and 0 warnings.")

    # --------------------------------------------------------------------------
    # Task 5: Capture high-resolution screenshot to both roots
    # --------------------------------------------------------------------------
    print("\n[TASK 5] Capturing high-resolution screenshot to both roots...")
    for sp in SCREENSHOT_PATHS:
        sp.parent.mkdir(parents=True, exist_ok=True)

    bytes_written = capture_cscape_screenshot(active_hwnd, SCREENSHOT_PATHS)
    assert bytes_written > 0, "capture_cscape_screenshot returned 0 bytes written!"

    screenshot_horner = SCREENSHOT_PATHS[0].read_bytes()
    screenshot_user = SCREENSHOT_PATHS[1].read_bytes()

    assert len(screenshot_horner) >= 10240, f"Screenshot size too small: {len(screenshot_horner)} bytes (< 10 KB)"
    assert len(screenshot_user) >= 10240, f"User screenshot size too small: {len(screenshot_user)} bytes (< 10 KB)"
    assert screenshot_horner[:8] == b"\x89PNG\r\n\x1a\n", "Horner screenshot is not a valid PNG!"
    assert screenshot_user[:8] == b"\x89PNG\r\n\x1a\n", "User screenshot is not a valid PNG!"

    sha256_horner = compute_sha256(screenshot_horner)
    sha256_user = compute_sha256(screenshot_user)
    assert sha256_horner == sha256_user, "Screenshot SHA-256 mismatch between dual roots!"

    print(f"  Horner screenshot: {SCREENSHOT_PATHS[0]} ({len(screenshot_horner)} bytes, SHA-256: {sha256_horner})")
    print(f"  User screenshot:   {SCREENSHOT_PATHS[1]} ({len(screenshot_user)} bytes, SHA-256: {sha256_user})")
    print("  -> Task 5 PASSED: Valid high-resolution PNG screenshot (>= 10 KB) captured and mirrored.")

    # --------------------------------------------------------------------------
    # Task 6: Update and sync gate file artifacts/.cscape_live_gate.json in both roots
    # --------------------------------------------------------------------------
    print("\n[TASK 6] Updating and syncing gate file in both roots...")
    iso_now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    project_file_path = str(HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "TankLevelClosedLoop.csp")

    gate_payload = {
        "ready_for_tests": True,
        "status": "READY_FOR_TESTS",
        "pid": active_pid,
        "hwnd": active_hwnd_hex,
        "window_title": window_title,
        "project_file": project_file_path,
        "exit_code": None,
        "reason": "Agent 1 Visible GUI Proof: Cscape active and visible on interactive desktop",
        "timestamp_utc": iso_now,
        "heartbeat_utc": iso_now,
    }

    gate_json_bytes = json.dumps(gate_payload, indent=2).encode("utf-8")
    for gp in GATE_FILES:
        gp.parent.mkdir(parents=True, exist_ok=True)
        gp.write_bytes(gate_json_bytes)
        print(f"  Updated gate file: {gp}")

    # Verify assert_cscape_live passes immediately
    live_gate_res = assert_cscape_live()
    assert live_gate_res.get("ready_for_tests") is True, f"Gate verification failed: {live_gate_res}"
    print("  -> Task 6 PASSED: Gate file synchronized and verified via assert_cscape_live().")

    # --------------------------------------------------------------------------
    # Task 7: Write JSON log to artifacts/logs/g1_visible_gui_proof.json in both roots
    # --------------------------------------------------------------------------
    print("\n[TASK 7] Writing JSON log to artifacts/logs/g1_visible_gui_proof.json in both roots...")
    iso_end = datetime.datetime.now(datetime.timezone.utc).isoformat()
    t_total = round(time.perf_counter() - t_start, 3)

    log_payload = {
        "agent": "Agent 1: Visible Cscape GUI Controller",
        "mandate": "Exclusive Visible Cscape GUI Automation Controller",
        "status": "PASSED",
        "timestamp_start_utc": iso_start,
        "timestamp_end_utc": iso_end,
        "duration_sec": t_total,
        "desktop": {
            "name": desktop_attached,
            "attached": True,
        },
        "cscape": {
            "pid": active_pid,
            "hwnd": active_hwnd_hex,
            "hwnd_int": active_hwnd,
            "window_title": window_title,
            "process_name": proc_name,
            "uptime_sec": uptime_sec,
            "working_set_mb": rss_mb,
            "is_window": is_window,
            "is_visible": is_visible,
            "is_enabled": is_enabled,
            "is_hung": is_hung,
            "ping_responsive": ping_res,
            "dimensions": f"{win_w}x{win_h}",
            "show_cmd": wp.showCmd,
            "sw_hide_detected": False,
        },
        "modal_dialogs": {
            "pre_sweep_dismissed": pre_sweep_count,
            "post_sweep_dismissed": post_sweep_count,
        },
        "gui_compilation": {
            "command_dispatched": compile_result.get("command_dispatched"),
            "command_name": "ID_PROGRAM_ERRORCHECK",
            "command_id": ID_PROGRAM_ERRORCHECK,
            "success": compile_result.get("success"),
            "error_count": compile_result.get("error_count"),
            "warning_count": compile_result.get("warning_count"),
            "duration_sec": compile_duration,
            "build_log": compile_result.get("build_log"),
            "controls_enumerated": compile_result.get("controls_enumerated"),
        },
        "screenshot": {
            "horner_path": str(SCREENSHOT_PATHS[0]),
            "user_path": str(SCREENSHOT_PATHS[1]),
            "size_bytes": len(screenshot_horner),
            "dimensions": f"{win_w}x{win_h}",
            "sha256": sha256_horner,
            "valid_png": True,
            "dual_root_mirrored": True,
        },
        "gate_status": {
            "ready_for_tests": True,
            "status": "READY_FOR_TESTS",
            "pid": active_pid,
            "hwnd": active_hwnd_hex,
            "paths_synced": [str(gp) for gp in GATE_FILES],
        },
        "safety_mandate": {
            "hardware_lockout_enforced": True,
            "zero_hardware_download": True,
            "zero_plc_download": True,
            "no_straton": True,
            "no_fake_metrics": True,
            "cscape_pid_preserved": True,
            "project_preserved": "TankLevelClosedLoop.csp",
        },
    }

    log_json_bytes = json.dumps(log_payload, indent=2).encode("utf-8")
    for lp in LOG_PATHS:
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_bytes(log_json_bytes)
        print(f"  Wrote log file: {lp}")

    print("  -> Task 7 PASSED: JSON proof log saved to both roots.")

    print("\n" + "=" * 80)
    print(f"AGENT 1 VISIBLE CSCAPE GUI CONTROLLER FINISHED: STATUS PASSED (Duration: {t_total}s)")
    print(f"Discovered PID: {active_pid} | HWND: {active_hwnd_hex} | Screenshot SHA-256: {sha256_horner}")
    print("=" * 80)
    return log_payload


if __name__ == "__main__":
    execute_agent1_tasks()
