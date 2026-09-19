"""Automated Pytest Suite for Step 44: 130-Minute Single-Process & 230-Minute Cumulative Stay-Open Benchmark."""
import json
from pathlib import Path
from PIL import Image
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step44_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step44_gui_stability_pid15240_130min_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 44
    assert data["status"] == "VERIFIED_LIVE"
    assert data["cscape_pid"] > 0
    assert data["cscape_healthy"] is True
    assert data["single_process_uptime_seconds"] >= 7800.0
    assert data["single_process_uptime_minutes"] >= 130.0
    assert data["cumulative_uptime_seconds"] >= 13780.0
    assert data["hardware_lockout_enforced"] is True


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step44_screenshot_valid(root: Path):
    shot_path = root / "artifacts" / "screenshots" / "live_cscape_tank_level_stay_open_pid15240_130min.png"
    assert shot_path.exists(), f"Missing screenshot: {shot_path}"
    with Image.open(shot_path) as img:
        assert img.size[0] >= 800
        assert img.size[1] >= 600


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step44_audit_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "cscape_gui_stability_pid15240_130min.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 44
    assert data["status"] == "VERIFIED_LIVE"

    proc_info = data["cscape_active_process"]
    assert proc_info["pid"] > 0
    assert proc_info["is_hung"] is False
    assert proc_info["wm_null_ping_ok"] is True
    assert proc_info["uptime_seconds"] >= 7800.0

    cum_info = data["cumulative_stay_open"]
    assert cum_info["total_stay_open_seconds"] >= 13780.0

    assert data["safety_audit"]["physical_plc_download_blocked"] is True
    assert data["safety_audit"]["zero_physical_hardware_touched"] is True
    assert data["safety_audit"]["zero_straton_dependencies"] is True
