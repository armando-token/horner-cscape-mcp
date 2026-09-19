"""Automated Pytest Suite for Step 29: Dynamic Setpoint Trajectory Tracking & Rate-Limiting Audit."""
import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step29_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step29_trajectory_rate_limit_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 29
    assert data["status"] == "VERIFIED_LIVE"
    assert data["total_cycles"] == 500
    assert data["max_rate_observed_pct"] <= 0.5001
    assert data["high_hold_error_pct"] <= 0.05
    assert data["final_error_pct"] <= 0.05
    assert data["hardware_lockout_enforced"] is True
    assert data["cscape_healthy"] is True
    assert data["cscape_pid"] > 0


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step29_audit_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "mcp_trajectory_rate_limit_audit.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 29
    assert data["status"] == "VERIFIED_LIVE"
    assert data["cscape_process"]["healthy"] is True
    assert data["cscape_process"]["pid"] > 0
    assert data["cscape_process"]["is_hung"] is False
    sim = data["simulation_summary"]
    assert sim["total_cycles"] == 500
    assert sim["throughput_cycles_per_sec"] > 500.0
    metrics = data["trajectory_metrics"]
    assert metrics["rate_limit_strictly_enforced"] is True
    assert metrics["max_rate_observed_pct_per_scan"] <= 0.5001
    assert metrics["high_hold_error_pct"] <= 0.05
    assert metrics["final_hold_error_pct"] <= 0.05
    assert metrics["trajectory_tracking_verified"] is True
    assert data["safety_audit"]["physical_plc_download_blocked"] is True
    assert data["safety_audit"]["zero_physical_hardware_touched"] is True
    assert data["safety_audit"]["hardware_lockout_enforced"] is True
