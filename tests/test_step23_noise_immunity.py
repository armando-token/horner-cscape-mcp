"""Automated Pytest Suite for Step 23: Closed-Loop Dynamic Noise Immunity & Wave Rejection Audit."""
import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step23_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step23_noise_immunity_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 23
    assert data["status"] == "VERIFIED_LIVE"
    assert data["total_cycles"] == 500
    assert data["mean_noise_phase_error_pct"] <= 0.35
    assert data["post_noise_settled_error_pct"] <= 0.05
    assert data["peak_derivative_pct"] <= 15.0
    assert data["hardware_lockout_enforced"] is True
    assert data["cscape_healthy"] is True
    assert data["cscape_pid"] > 0


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step23_audit_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "mcp_closed_loop_noise_immunity_audit.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 23
    assert data["status"] == "VERIFIED_LIVE"
    assert data["cscape_process"]["healthy"] is True
    assert data["cscape_process"]["pid"] > 0
    assert data["cscape_process"]["is_hung"] is False
    assert data["simulation_summary"]["total_cycles"] == 500
    assert data["simulation_summary"]["throughput_cycles_per_sec"] > 500
    metrics = data["noise_rejection_metrics"]
    assert metrics["noise_amplitude_pct"] == 3.0
    assert metrics["mean_true_pv_error_pct"] <= 0.35
    assert metrics["peak_derivative_term_pct"] <= 15.0
    assert metrics["noise_immunity_verified"] is True
    assert metrics["derivative_bounded_verified"] is True
    assert metrics["recovery_settling_verified"] is True
    assert data["safety_audit"]["physical_plc_download_blocked"] is True
    assert data["safety_audit"]["zero_physical_hardware_touched"] is True
    assert data["safety_audit"]["hardware_lockout_enforced"] is True
