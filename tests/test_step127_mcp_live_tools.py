"""Test suite validating Step 127 live FastMCP multi-tool verification evidence."""

import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step127_checkpoint_valid(root):
    cp = root / "artifacts" / "checkpoints" / "step127_mcp_live_tools_evidence_checkpoint.json"
    assert cp.exists(), f"Checkpoint {cp} does not exist"
    data = json.loads(cp.read_text(encoding="utf-8"))
    assert data["status"] == "PASSED"
    assert data["cscape_pid"] > 0
    assert "TankLevelClosedLoop" in data["cscape_title"]
    assert data["is_hung"] is False
    assert data["tools_verified_count"] >= 9
    assert data["fail_closed_enforced"] is True
    assert data["zero_plc_download_enforced"] is True


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step127_audit_log_valid(root):
    lp = root / "artifacts" / "logs" / "mcp_live_tools_evidence_audit.json"
    assert lp.exists(), f"Log {lp} does not exist"
    data = json.loads(lp.read_text(encoding="utf-8"))
    assert data["status"] == "PASSED"
    assert data["cscape_pid"] > 0
    assert "cscape_compile_project" in data["tools_proven"]
    assert "cscape_read_variables" in data["tools_proven"]
    assert "cscape_export_variables" in data["tools_proven"]
    assert "cscape_register_tools" in data["tools_proven"]
    assert "cscape_simulate_cycle" in data["tools_proven"]
    assert "cscape_run_simulation" in data["tools_proven"]
    assert "cscape_validate_st" in data["tools_proven"]
    assert "st_ladder_interop_guard" in data["tools_proven"]
    assert "hardware_safety_lockout" in data["tools_proven"]
