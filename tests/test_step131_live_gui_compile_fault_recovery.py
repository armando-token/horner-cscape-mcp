"""Automated Pytest Suite for Step 131: Live GUI Compile Fault-Injection & Recovery Roundtrip."""
import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step131_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step131_live_gui_compile_fault_injection_recovery_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 131
    assert data["status"] == "VERIFIED_LIVE"
    assert data["cscape_pid"] > 0
    assert data["cscape_healthy"] is True
    assert data["baseline_compile_success"] is True
    assert data["fault_rejected"] is True
    assert data["recovery_compile_success"] is True
    assert data["hardware_lockout_enforced"] is True


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step131_audit_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "mcp_live_gui_compile_fault_recovery_audit.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 131
    assert data["status"] == "VERIFIED_LIVE"

    proc_info = data["cscape_active_process"]
    assert proc_info["pid"] > 0
    assert proc_info["is_hung"] is False
    assert proc_info["ping_ok"] is True

    roundtrip = data["fault_injection_roundtrip"]
    assert roundtrip["baseline_compile_success"] is True
    assert roundtrip["fault_compile_rejected"] is True
    assert roundtrip["fault_error_count"] >= 1
    assert roundtrip["gui_survived_fault_unhung"] is True
    assert roundtrip["recovery_compile_success"] is True
    assert roundtrip["recovery_errors"] == 0

    assert data["safety_audit"]["physical_plc_download_blocked"] is True
    assert data["safety_audit"]["zero_physical_hardware_touched"] is True
    assert data["safety_audit"]["zero_straton_dependencies"] is True
