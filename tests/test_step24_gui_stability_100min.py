"""Automated Pytest Suite for Step 24: 100-Minute Continuous Stay-Open Milestone."""
import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step24_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step24_gui_stability_100min_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 24
    assert data["status"] == "VERIFIED_LIVE"
    assert data["pid"] > 0
    assert data["uptime_seconds"] >= 6000.0
    assert data["uptime_minutes"] >= 100.0
    assert data["is_hung"] is False
    assert data["memory_mb"] > 10.0


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step24_screenshot_valid(root: Path):
    ss_path = root / "artifacts" / "screenshots" / "live_cscape_tank_level_stay_open_100min.png"
    assert ss_path.exists(), f"Missing screenshot: {ss_path}"
    assert ss_path.stat().st_size > 10000, f"Screenshot file too small: {ss_path.stat().st_size} bytes"


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step24_audit_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "cscape_gui_stability_100min.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 24
    assert data["status"] == "VERIFIED_LIVE"
    metrics = data["metrics"]
    assert metrics["pid"] > 0
    assert metrics["cumulative_uptime_seconds"] >= 6000.0
    assert metrics["stay_open_100min_exceeded"] is True
    assert metrics["is_hung_app_window"] is False
    assert metrics["send_message_timeout_wm_null_responsive"] is True
    assert metrics["frame_45011_present"] is True
    assert metrics["listbox_372_present"] is True
    assert data["safety_audit"]["physical_plc_download_blocked"] is True
    assert data["safety_audit"]["straton_processes_running"] == 0
