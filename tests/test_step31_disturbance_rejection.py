"""Automated Pytest Suite for Step 31: Dual-Timeconstant Load Disturbance Rejection Audit."""
import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step31_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step31_disturbance_rejection_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 31
    assert data["status"] == "VERIFIED_LIVE"
    assert data["total_cycles"] == 500
    assert data["phase2_settled_error_pct"] <= 1.0
    assert data["phase3_settled_error_pct"] <= 1.0
    assert data["final_recovery_error_pct"] <= 1.0
    assert data["hardware_lockout_enforced"] is True
    assert data["cscape_healthy"] is True
    assert data["cscape_pid"] > 0


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step31_audit_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "mcp_disturbance_rejection_audit.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 31
    assert data["status"] == "VERIFIED_LIVE"
    assert data["cscape_process"]["healthy"] is True
    assert data["cscape_process"]["pid"] > 0
    assert data["cscape_process"]["is_hung"] is False
    sim = data["simulation_summary"]
    assert sim["total_cycles"] == 500
    assert sim["throughput_cycles_per_sec"] > 500.0
    metrics = data["disturbance_metrics"]
    assert metrics["dual_timeconstant_dynamics_verified"] is True
    assert metrics["load_disturbance_rejection_verified"] is True
    assert metrics["phase2_75pct_load_settled_error_pct"] <= 1.0
    assert metrics["phase3_25pct_load_settled_error_pct"] <= 1.0
    assert metrics["final_50pct_load_recovery_error_pct"] <= 1.0
    assert data["safety_audit"]["physical_plc_download_blocked"] is True
    assert data["safety_audit"]["zero_physical_hardware_touched"] is True
    assert data["safety_audit"]["hardware_lockout_enforced"] is True
