"""Automated Pytest Suite for Step 41: Anti-Windup Clamping & Recovery Audit."""
import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step41_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step41_anti_windup_clamping_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 41
    assert data["status"] == "VERIFIED_LIVE"
    assert data["cscape_pid"] > 0
    assert data["cscape_healthy"] is True
    assert data["simulation_cycles"] == 500
    assert data["upper_clamp_verified"] is True
    assert data["lower_clamp_verified"] is True
    assert data["zero_unwind_lag_verified"] is True
    assert data["phase2_recovery_error_percent"] < 0.10
    assert data["phase4_recovery_error_percent"] < 0.10
    assert data["hardware_lockout_enforced"] is True


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step41_audit_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "mcp_anti_windup_clamping_audit.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 41
    assert data["status"] == "VERIFIED_LIVE"

    proc_info = data["cscape_active_process"]
    assert proc_info["pid"] > 0
    assert proc_info["is_hung"] is False
    assert proc_info["wm_null_ping_ok"] is True

    aw_m = data["anti_windup_metrics"]
    assert aw_m["total_cycles"] == 500
    assert aw_m["upper_saturation_clamped"] is True
    assert aw_m["lower_saturation_clamped"] is True
    assert aw_m["zero_unwinding_lag_verified"] is True
    assert aw_m["max_clamped_output_percent"] <= 100.0001
    assert aw_m["min_clamped_output_percent"] >= -0.0001

    assert data["safety_audit"]["physical_plc_download_blocked"] is True
    assert data["safety_audit"]["zero_physical_hardware_touched"] is True
    assert data["safety_audit"]["zero_straton_dependencies"] is True
