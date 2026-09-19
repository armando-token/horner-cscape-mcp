"""Synchronizes live Cscape gate status across all target gate files."""
from __future__ import annotations
import datetime
import json
import sys
from pathlib import Path
import psutil

WORKSPACE_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
for p in [str(WORKSPACE_ROOT), str(HORNER_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from src.cscape.gate import GATE_PATHS, attach_thread_desktop
from scripts.watchdog_cscape_10min import Win32Helper

def sync_gate() -> dict:
    whelper = Win32Helper()
    cscape_pids = set()
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if p.info["name"] and "cscape" in p.info["name"].lower():
                cscape_pids.add(p.info["pid"])
        except Exception:
            pass

    if not cscape_pids:
        data = {
            "ready_for_tests": False,
            "status": "FAIL_CLOSED_CSCAPE_DEAD",
            "pid": None,
            "hwnd": None,
            "window_title": None,
            "reason": "No Cscape process found running on Windows",
            "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "heartbeat_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
    else:
        wins = whelper.enum_windows_for_pids(cscape_pids)
        target_win = None
        for w in wins:
            if "cscape" in w.title.lower() and "tanklevel" in w.title.lower():
                target_win = w
                break

        if target_win and not whelper.is_hung_app_window(target_win.hwnd):
            data = {
                "ready_for_tests": True,
                "status": "READY_FOR_TESTS",
                "pid": target_win.pid,
                "hwnd": f"0x{target_win.hwnd:08X}",
                "window_title": target_win.title,
                "project_file": r"C:\Users\ArmandoSilva\artifacts\projects\TankLevelClosedLoop\TankLevelClosedLoop.csp",
                "exit_code": None,
                "reason": "TankLevelClosedLoop verified active and responsive",
                "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "heartbeat_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        else:
            w_title = target_win.title if target_win else "Unknown"
            w_hwnd = f"0x{target_win.hwnd:08X}" if target_win else None
            w_pid = target_win.pid if target_win else (list(cscape_pids)[0] if cscape_pids else None)
            data = {
                "ready_for_tests": False,
                "status": "FAIL_CLOSED_TANKLEVEL_NOT_OPEN",
                "pid": w_pid,
                "hwnd": w_hwnd,
                "window_title": w_title,
                "reason": f"TankLevelClosedLoop not active (Title: '{w_title}')",
                "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "heartbeat_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }

    for p in GATE_PATHS:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    print("Gate Synced:", json.dumps(data, indent=2))
    return data

if __name__ == "__main__":
    sync_gate()
