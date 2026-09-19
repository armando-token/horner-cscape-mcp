"""Automated Pytest Suite for Step 37: Multi-Variable Bidirectional CSV/XML Tag Sync Audit."""
import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step37_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step37_variable_sync_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 37
    assert data["status"] == "VERIFIED_LIVE"
    assert data["cscape_pid"] > 0
    assert data["cscape_healthy"] is True
    assert data["total_variables"] == 21
    assert data["tag_match_rate_percent"] == 100.0
    assert data["data_type_match_rate_percent"] == 100.0
    assert data["conflicts_detected"] == 0
    assert data["simulation_cycles"] == 100
    assert data["hardware_lockout_enforced"] is True


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step37_xml_file_valid(root: Path):
    xml_path = root / "artifacts" / "projects" / "TankLevelClosedLoop" / "variables.xml"
    assert xml_path.exists(), f"Missing variables.xml: {xml_path}"
    content = xml_path.read_text(encoding="utf-8")
    assert "<ProjectVariables" in content or "<var " in content
    assert "TankLevelPV" in content
    assert "%R1" in content
    assert "%AI1" in content
    assert "%AQ1" in content


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step37_audit_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "mcp_variable_sync_audit.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 37
    assert data["status"] == "VERIFIED_LIVE"
    proc_info = data["cscape_active_process"]
    assert proc_info["pid"] > 0
    assert proc_info["is_hung"] is False
    assert proc_info["wm_null_ping_ok"] is True

    sync_m = data["variable_sync_metrics"]
    assert sync_m["total_variables"] == 21
    assert sync_m["tag_match_rate_percent"] == 100.0
    assert sync_m["data_type_match_rate_percent"] == 100.0
    assert sync_m["scope_match_rate_percent"] == 100.0
    assert sync_m["conflicts_detected"] == 0
    assert sync_m["memory_collision_free"] is True

    sim_m = data["simulation_metrics"]
    assert sim_m["cycles_run"] == 100
    assert sim_m["cycles_per_sec"] > 500.0
    assert sim_m["runtime_register_consistency_verified"] is True

    assert data["safety_audit"]["physical_plc_download_blocked"] is True
    assert data["safety_audit"]["zero_physical_hardware_touched"] is True
    assert data["safety_audit"]["zero_straton_dependencies"] is True
