"""Automated Pytest Suite for Step 33: Multi-Boundary Anti-Chatter & Flapping Prevention Audit."""
import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step33_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step33_anti_chatter_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 33
    assert data["status"] == "VERIFIED_LIVE"
    assert data["total_cycles"] == 500
    assert data["phase2_flapping_flips"] == 0
    assert data["phase3_flapping_flips"] == 0
    assert data["zero_relay_flapping_verified"] is True
    assert data["final_error_pct"] <= 0.05
    assert data["hardware_lockout_enforced"] is True
    assert data["cscape_healthy"] is True
    assert data["cscape_pid"] > 0


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step33_audit_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "mcp_anti_chatter_audit.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 33
    assert data["status"] == "VERIFIED_LIVE"
    assert data["cscape_process"]["healthy"] is True
    assert data["cscape_process"]["pid"] > 0
    assert data["cscape_process"]["is_hung"] is False
    sim = data["simulation_summary"]
    assert sim["total_cycles"] == 500
    assert sim["throughput_cycles_per_sec"] > 500.0
    metrics = data["chatter_metrics"]
    assert metrics["phase2_high_boundary_oscillation_cycles"] == 150
    assert metrics["phase2_flapping_flips"] == 0
    assert metrics["phase2_anti_chatter_verified"] is True
    assert metrics["phase3_low_boundary_oscillation_cycles"] == 100
    assert metrics["phase3_flapping_flips"] == 0
    assert metrics["phase3_anti_chatter_verified"] is True
    assert metrics["zero_relay_contact_burnout_verified"] is True
    assert metrics["final_recovery_error_pct"] <= 0.05
    assert data["safety_audit"]["physical_plc_download_blocked"] is True
    assert data["safety_audit"]["zero_physical_hardware_touched"] is True
    assert data["safety_audit"]["hardware_lockout_enforced"] is True
