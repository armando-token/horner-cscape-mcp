"""Automated Pytest Suite for Step 46: Redundant Dual-Transmitter Voting Closed-Loop Audit."""
import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step46_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step46_dual_transmitter_voting_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 46
    assert data["status"] == "VERIFIED_LIVE"
    assert data["cscape_pid"] > 0
    assert data["cscape_healthy"] is True
    assert data["total_cycles"] == 350
    assert data["phase1_final_error_percent"] < 0.05
    assert data["phase2_drift_quarantine_error_percent"] < 0.10
    assert data["phase3_primary_a_error_percent"] < 0.05
    assert data["phase4_max_clamped_output"] == 0.0
    assert data["phase5_recovery_error_percent"] < 0.05
    assert data["voting_redundancy_verified"] is True
    assert data["hardware_lockout_enforced"] is True


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step46_audit_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "mcp_dual_transmitter_voting_audit.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 46
    assert data["status"] == "VERIFIED_LIVE"

    proc_info = data["cscape_active_process"]
    assert proc_info["pid"] > 0
    assert proc_info["is_hung"] is False
    assert proc_info["wm_null_ping_ok"] is True

    rm = data["redundancy_metrics"]
    assert rm["total_cycles"] == 350
    assert rm["discrepancy_threshold_pct"] == 3.0
    assert rm["critical_2oo2_threshold_pct"] == 10.0
    assert rm["phase1_final_error_percent"] < 0.05
    assert rm["phase2_quarantine_verified"] is True
    assert rm["phase3_primary_a_retention_verified"] is True
    assert rm["phase4_failsafe_2oo2_clamp_verified"] is True
    assert rm["phase5_bumpless_recovery_verified"] is True
    assert rm["phase5_recovery_final_error_percent"] < 0.05

    assert data["safety_audit"]["physical_plc_download_blocked"] is True
    assert data["safety_audit"]["zero_physical_hardware_touched"] is True
    assert data["safety_audit"]["zero_straton_dependencies"] is True
