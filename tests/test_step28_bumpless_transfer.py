"""Automated Pytest Suite for Step 28: Bumpless Manual/Auto Transfer Dynamic Audit."""
import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step28_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step28_bumpless_transfer_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 28
    assert data["status"] == "VERIFIED_LIVE"
    assert data["total_cycles"] == 500
    assert data["bumpless_transfer_verified"] is True
    assert data["transfer_delta_pct"] <= 0.50
    assert data["final_recovery_error_pct"] <= 0.10
    assert data["hardware_lockout_enforced"] is True
    assert data["cscape_healthy"] is True
    assert data["cscape_pid"] > 0


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step28_audit_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "mcp_bumpless_transfer_audit.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 28
    assert data["status"] == "VERIFIED_LIVE"
    assert data["cscape_process"]["healthy"] is True
    assert data["cscape_process"]["pid"] > 0
    assert data["cscape_process"]["is_hung"] is False
    sim = data["simulation_summary"]
    assert sim["total_cycles"] == 500
    assert sim["throughput_cycles_per_sec"] > 500.0
    metrics = data["transfer_metrics"]
    assert metrics["manual_mode_tracking_verified"] is True
    assert metrics["anti_windup_integrator_tracking_verified"] is True
    assert metrics["bumpless_transfer_verified"] is True
    assert metrics["transfer_step_delta_pct"] <= 0.50
    assert metrics["derivative_kick_suppression_verified"] is True
    assert abs(metrics["transfer_derivative_term"]) < 0.10
    assert metrics["final_recovery_error_pct"] <= 0.10
    assert data["safety_audit"]["physical_plc_download_blocked"] is True
    assert data["safety_audit"]["zero_physical_hardware_touched"] is True
    assert data["safety_audit"]["hardware_lockout_enforced"] is True
