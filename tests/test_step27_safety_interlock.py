"""Automated Pytest Suite for Step 27: Multi-Tier Safety Interlock & Alarm Hysteresis Closed-Loop Audit."""
import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step27_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step27_safety_interlock_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 27
    assert data["status"] == "VERIFIED_LIVE"
    assert data["total_cycles"] == 500
    assert data["spill_protection_verified"] is True
    assert data["cavitation_cutoff_verified"] is True
    assert data["final_recovery_error_pct"] <= 0.10
    assert data["hardware_lockout_enforced"] is True
    assert data["cscape_healthy"] is True
    assert data["cscape_pid"] > 0


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step27_audit_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "mcp_safety_interlock_hysteresis_audit.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 27
    assert data["status"] == "VERIFIED_LIVE"
    assert data["cscape_process"]["healthy"] is True
    assert data["cscape_process"]["pid"] > 0
    assert data["cscape_process"]["is_hung"] is False
    sim = data["simulation_summary"]
    assert sim["total_cycles"] == 500
    assert sim["throughput_cycles_per_sec"] > 500.0
    metrics = data["safety_interlock_metrics"]
    assert metrics["high_high_spill_protection_verified"] is True
    assert metrics["low_low_cavitation_protection_verified"] is True
    assert metrics["high_hysteresis_deadband_verified"] is True
    assert metrics["low_hysteresis_deadband_verified"] is True
    assert metrics["bumpless_nominal_recovery_verified"] is True
    assert metrics["final_recovery_error_pct"] <= 0.10
    assert data["safety_audit"]["physical_plc_download_blocked"] is True
    assert data["safety_audit"]["zero_physical_hardware_touched"] is True
    assert data["safety_audit"]["hardware_lockout_enforced"] is True
