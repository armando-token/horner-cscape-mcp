"""Automated Pytest Suite for Step 38: Three-Zone Dynamic Gain Scheduling & Live Compile Audit."""
import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step38_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step38_gain_scheduling_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 38
    assert data["status"] == "VERIFIED_LIVE"
    assert data["cscape_pid"] > 0
    assert data["cscape_healthy"] is True
    assert data["live_compile_success"] is True
    assert data["compile_error_count"] == 0
    assert data["gain_scheduling_zones"] == 3
    assert data["simulation_cycles"] == 500
    assert data["zone1_final_error_percent"] < 0.25
    assert data["zone2_final_error_percent"] < 0.25
    assert data["zone3_final_error_percent"] < 0.25
    assert data["hardware_lockout_enforced"] is True


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step38_audit_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "mcp_gain_scheduling_audit.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 38
    assert data["status"] == "VERIFIED_LIVE"

    proc_info = data["cscape_active_process"]
    assert proc_info["pid"] > 0
    assert proc_info["is_hung"] is False
    assert proc_info["wm_null_ping_ok"] is True

    comp_info = data["live_compile_metrics"]
    assert comp_info["success"] is True
    assert comp_info["error_count"] == 0
    assert comp_info["project_name"] == "TankLevelClosedLoop"

    gs_info = data["gain_scheduling_metrics"]
    assert gs_info["total_cycles"] == 500
    assert gs_info["zones_evaluated"] == 3
    assert gs_info["all_zones_settled_successfully"] is True

    assert data["safety_audit"]["physical_plc_download_blocked"] is True
    assert data["safety_audit"]["zero_physical_hardware_touched"] is True
    assert data["safety_audit"]["zero_straton_dependencies"] is True
