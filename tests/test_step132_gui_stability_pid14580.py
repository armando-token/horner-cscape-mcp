"""Test suite validating Step 132 Cscape keepalive evidence."""

import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step132_checkpoint_valid(root):
    cp = root / "artifacts" / "checkpoints" / "step132_cscape_stay_open_pid14580_checkpoint.json"
    assert cp.exists(), f"Checkpoint {cp} does not exist"
    data = json.loads(cp.read_text(encoding="utf-8"))
    assert data["status"] == "PASSED"
    assert data["cscape_pid"] > 0
    assert data["achieved_continuous_uptime_seconds"] > 60.0
    assert "TankLevelClosedLoop" in data["cscape_title"]
    assert data["is_hung"] is False
    assert data["fail_closed_gate_synced"] is True


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step132_screenshot_valid(root):
    sp = root / "artifacts" / "screenshots" / "live_cscape_tank_level_stay_open_pid14580_milestone.png"
    assert sp.exists(), f"Screenshot {sp} does not exist"
    assert sp.stat().st_size > 200, f"Screenshot {sp} is too small"


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step132_audit_log_valid(root):
    lp = root / "artifacts" / "logs" / "cscape_gui_stability_pid14580_milestone.json"
    assert lp.exists(), f"Log {lp} does not exist"
    data = json.loads(lp.read_text(encoding="utf-8"))
    assert data["status"] == "PASSED"
    assert data["cscape_pid"] > 0
    assert data["achieved_continuous_uptime_seconds"] > 60.0
