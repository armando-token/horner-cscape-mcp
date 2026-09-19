"""Automated Pytest Suite for Step 25: Actuator Saturation & Valve Stiction Non-Linearity Audit."""
import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step25_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step25_actuator_stiction_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 25
    assert data["status"] == "VERIFIED_LIVE"
    assert data["total_cycles"] == 500
    assert data["phase_2_saturated_error_pct"] <= 0.05
    assert data["phase_3_saturated_error_pct"] <= 0.05
    assert data["phase_4_stiction_error_pct"] <= 0.20
    assert data["cv_range_pct"][0] <= 0.0
    assert data["cv_range_pct"][1] >= 100.0
    assert data["hardware_lockout_enforced"] is True
    assert data["cscape_healthy"] is True
    assert data["cscape_pid"] > 0


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step25_audit_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "mcp_actuator_saturation_stiction_audit.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 25
    assert data["status"] == "VERIFIED_LIVE"
    assert data["cscape_process"]["healthy"] is True
    assert data["cscape_process"]["pid"] > 0
    assert data["cscape_process"]["is_hung"] is False
    assert data["simulation_summary"]["total_cycles"] == 500
    assert data["simulation_summary"]["throughput_cycles_per_sec"] > 500
    metrics = data["non_linearity_metrics"]
    assert metrics["stiction_deadband_pct"] == 1.0
    assert metrics["cv_min_pct"] <= 0.0
    assert metrics["cv_max_pct"] >= 100.0
    assert metrics["phase_2_saturated_up_error_pct"] <= 0.05
    assert metrics["phase_3_saturated_down_error_pct"] <= 0.05
    assert metrics["phase_4_stiction_error_pct"] <= 0.20
    assert metrics["anti_windup_verified"] is True
    assert metrics["saturation_recovery_verified"] is True
    assert metrics["stiction_regulation_verified"] is True
    assert data["safety_audit"]["physical_plc_download_blocked"] is True
    assert data["safety_audit"]["zero_physical_hardware_touched"] is True
    assert data["safety_audit"]["hardware_lockout_enforced"] is True
