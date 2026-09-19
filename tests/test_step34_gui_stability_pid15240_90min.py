"""Automated Pytest Suite for Step 34: 90-Minute Single-Process Continuous Stay-Open Milestone (PID 15240)."""
import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step34_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step34_gui_stability_pid15240_90min_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 34
    assert data["status"] == "VERIFIED_LIVE"
    assert data["cscape_pid"] > 0
    assert data["active_uptime_seconds"] >= 5400.0
    assert data["active_uptime_minutes"] >= 90.0
    assert data["single_process_90min_verified"] is True
    assert data["zero_crashes_verified"] is True
    assert data["hardware_lockout_enforced"] is True


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step34_screenshot_valid(root: Path):
    ss_path = root / "artifacts" / "screenshots" / "live_cscape_tank_level_stay_open_pid15240_90min.png"
    assert ss_path.exists(), f"Missing screenshot: {ss_path}"
    assert ss_path.stat().st_size > 10000, f"Screenshot file too small: {ss_path.stat().st_size} bytes"


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step34_audit_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "cscape_gui_stability_pid15240_90min.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 34
    assert data["status"] == "VERIFIED_LIVE"
    proc_info = data["cscape_active_process"]
    assert proc_info["pid"] > 0
    assert proc_info["active_uptime_seconds"] >= 5400.0
    assert proc_info["single_process_90min_exceeded"] is True
    assert data["live_window"]["is_hung"] is False
    assert data["live_window"]["wm_null_ping_ok"] is True
    assert data["safety_audit"]["physical_plc_download_blocked"] is True
