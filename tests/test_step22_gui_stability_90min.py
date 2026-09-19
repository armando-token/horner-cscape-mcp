"""Automated Pytest Suite for Step 22: Cscape 90-Minute Continuous Stay-Open."""
import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step22_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step22_gui_stability_90min_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 22
    assert data["status"] == "VERIFIED_LIVE"
    assert data["pid"] > 0
    assert data["uptime_seconds"] >= 5400.0
    assert data["uptime_minutes"] >= 90.0
    assert data["is_hung"] is False
    assert Path(data["screenshot_path"]).exists()
    assert Path(data["evidence_log"]).exists()


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step22_screenshot_exists(root: Path):
    ss_path = root / "artifacts" / "screenshots" / "live_cscape_tank_level_stay_open_90min.png"
    assert ss_path.exists(), f"Missing screenshot: {ss_path}"
    assert ss_path.stat().st_size > 10000, f"Screenshot file too small: {ss_path.stat().st_size} bytes"


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step22_evidence_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "cscape_gui_stability_90min.json"
    assert log_path.exists(), f"Missing evidence log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 22
    assert data["status"] == "VERIFIED_LIVE"
    assert data["metrics"]["stay_open_90min_exceeded"] is True
    assert data["metrics"]["is_hung_app_window"] is False
    assert data["metrics"]["send_message_timeout_wm_null_responsive"] is True
    assert data["metrics"]["frame_45011_present"] is True
    assert data["metrics"]["listbox_372_present"] is True
    assert data["safety_audit"]["physical_plc_download_blocked"] is True
    assert data["safety_audit"]["straton_k5_tools_quarantined"] is True
