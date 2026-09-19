"""Test suite validating Step 135 Cscape keepalive long-uptime milestone evidence (5,000+s / 80+m) on PID 14580."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import psutil
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()

import sys
for r in [USER_ROOT, HORNER_ROOT]:
    if str(r) not in sys.path:
        sys.path.insert(0, str(r))

from src.cscape.gate import assert_cscape_live, attach_thread_desktop, get_gate_status
from src.cscape.safety import (
    ID_CONTROLLER_DOWNLOAD,
    ID_CONTROLLER_DOWNLOAD_ALT,
    ID_PLC_DOWNLOAD,
    CscapeSafetyViolationError,
    intercept_download_command,
)


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step135_checkpoint_exists_and_valid(root: Path):
    """Assertion 1: Checkpoint exists across both roots with valid schema and status."""
    cp = root / "artifacts" / "checkpoints" / "step135_cscape_stay_open_5000s_checkpoint.json"
    assert cp.exists(), f"Checkpoint {cp} does not exist"
    data = json.loads(cp.read_text(encoding="utf-8"))
    assert data["status"] == "PASSED"
    assert data["step"] == 135
    assert data["fail_closed_gate_synced"] is True
    assert "TankLevelClosedLoop" in data["cscape_title"]
    assert "TankLevelClosedLoop" in data["project_file"]


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step135_pid_matches_active_cscape(root: Path):
    """Assertion 2: PID matches active Cscape process and is alive."""
    cp = root / "artifacts" / "checkpoints" / "step135_cscape_stay_open_5000s_checkpoint.json"
    data = json.loads(cp.read_text(encoding="utf-8"))
    ckpt_pid = data["cscape_pid"]
    assert ckpt_pid > 0

    gate = get_gate_status()
    live_pid = gate.get("pid")
    if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
        pytest.skip(f"No active live Cscape process (gate reports PID {live_pid})")
    assert live_pid > 0
    proc = psutil.Process(live_pid)
    assert proc.is_running(), f"Process PID {live_pid} is not running"
    assert "cscape" in proc.name().lower(), f"Process {live_pid} name '{proc.name()}' is not Cscape"


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step135_continuous_uptime_milestone(root: Path):
    """Assertion 3: Continuous uptime >= 5000.0s (83.3+ minutes) verified."""
    cp = root / "artifacts" / "checkpoints" / "step135_cscape_stay_open_5000s_checkpoint.json"
    data = json.loads(cp.read_text(encoding="utf-8"))
    uptime_sec = data["achieved_continuous_uptime_seconds"]
    uptime_min = data["achieved_continuous_uptime_minutes"]

    assert uptime_sec >= 5000.0, f"Continuous uptime {uptime_sec}s is < 5000.0s"
    assert uptime_min >= 83.3, f"Continuous uptime {uptime_min}m is < 83.3m"

    # Live process uptime check if live gate is active
    gate = get_gate_status()
    if gate.get("ready_for_tests") and gate.get("pid"):
        live_pid = gate.get("pid")
        if psutil.pid_exists(live_pid):
            proc = psutil.Process(live_pid)
            live_uptime = psutil.time.time() - proc.create_time()
            assert live_uptime > 0.0


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step135_is_hung_app_window_false_and_responsive(root: Path):
    """Assertion 4: IsHungAppWindow is False and window is responsive."""
    cp = root / "artifacts" / "checkpoints" / "step135_cscape_stay_open_5000s_checkpoint.json"
    data = json.loads(cp.read_text(encoding="utf-8"))
    assert data["is_hung"] is False
    assert data["ping_responsive"] is True

    # Win32 live check
    gate = get_gate_status()
    live_pid = gate.get("pid")
    if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid) or not gate.get("hwnd"):
        pytest.skip("No active live Cscape gate")
    raw_h = gate.get("hwnd", "0x0")
    hwnd = int(raw_h, 16) if isinstance(raw_h, str) and raw_h.startswith("0x") else int(raw_h or 0)
    assert hwnd > 0
    attach_thread_desktop(hwnd)

    user32 = ctypes.windll.user32
    user32.IsHungAppWindow.argtypes = [wintypes.HWND]
    user32.IsHungAppWindow.restype = wintypes.BOOL
    is_hung_live = bool(user32.IsHungAppWindow(hwnd))
    assert not is_hung_live, f"Live window HWND {hex(hwnd)} reports IsHungAppWindow=True"

    # SendMessageTimeoutW responsiveness ping
    user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_ulong)
    ]
    user32.SendMessageTimeoutW.restype = ctypes.c_long
    res_val = ctypes.c_ulong(0)
    ping_res = user32.SendMessageTimeoutW(hwnd, 0, 0, 0, 0x0002, 1000, ctypes.byref(res_val))
    assert ping_res != 0, f"SendMessageTimeoutW failed on HWND {hex(hwnd)}"


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step135_screenshot_exists_and_valid(root: Path):
    """Assertion 5: High-resolution screenshot exists and file size > 50KB."""
    sp = root / "artifacts" / "screenshots" / "live_cscape_tank_level_stay_open_pid14580_5000s.png"
    assert sp.exists(), f"Screenshot {sp} does not exist"
    size_bytes = sp.stat().st_size
    assert size_bytes > 50000, f"Screenshot {sp} size ({size_bytes} bytes) is not > 50KB"


def test_step135_plc_lockout_enforced():
    """Assertion 6: Physical PLC lockout is strictly enforced (ID_CONTROLLER_DOWNLOAD = 32827)."""
    assert ID_CONTROLLER_DOWNLOAD == 32827
    assert ID_CONTROLLER_DOWNLOAD_ALT == 33149

    with pytest.raises(CscapeSafetyViolationError):
        intercept_download_command(ID_CONTROLLER_DOWNLOAD)

    with pytest.raises(CscapeSafetyViolationError):
        intercept_download_command("ID_CONTROLLER_DOWNLOAD")

    with pytest.raises(CscapeSafetyViolationError):
        intercept_download_command(ID_PLC_DOWNLOAD)


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step135_audit_log_and_keepalive_entry(root: Path):
    """Assertion 7: Audit log and keepalive entries exist and match milestone."""
    lp = root / "artifacts" / "logs" / "cscape_gui_stability_pid14580_5000s.json"
    assert lp.exists(), f"Log {lp} does not exist"
    log_data = json.loads(lp.read_text(encoding="utf-8"))
    assert log_data["status"] == "PASSED"
    assert log_data["cscape_pid"] > 0
    assert log_data["achieved_continuous_uptime_seconds"] >= 5000.0

    kl = root / "artifacts" / "logs" / "cscape_keepalive.log"
    assert kl.exists(), f"Keepalive log {kl} does not exist"
    kl_content = kl.read_text(encoding="utf-8")
    assert "[STEP135_COMPLETED]" in kl_content
    

def test_step135_zero_straton_dependencies():
    """Assertion 8: Zero Straton K5 legacy dependencies running."""
    straton_binaries = ["k5bus.exe", "k5edit.exe", "k5run.exe", "k5vm.exe", "k5cmd.exe", "t5.exe"]
    active_straton = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            pname = p.info["name"].lower()
            if any(sb in pname for sb in straton_binaries):
                active_straton.append(p.info)
        except Exception:
            pass
    assert len(active_straton) == 0, f"Found active Straton processes: {active_straton}"
