"""Automated Pytest Suite for Step 45: Scan Cycle Overrun & Watchdog Interlock Recovery Audit."""
import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step45_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step45_scan_overrun_watchdog_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 45
    assert data["status"] == "VERIFIED_LIVE"
    assert data["cscape_pid"] > 0
    assert data["cscape_healthy"] is True
    assert data["total_cycles"] == 300
    assert data["phase1_final_error_percent"] < 0.05
    assert data["phase2_max_clamped_output"] == 0.0
    assert data["phase3_latch_retained"] is True
    assert data["phase4_recovery_error_percent"] < 0.05
    assert data["watchdog_fail_safe_verified"] is True
    assert data["hardware_lockout_enforced"] is True


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step45_audit_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "mcp_scan_overrun_watchdog_audit.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 45
    assert data["status"] == "VERIFIED_LIVE"

    proc_info = data["cscape_active_process"]
    assert proc_info["pid"] > 0
    assert proc_info["is_hung"] is False
    assert proc_info["wm_null_ping_ok"] is True

    wm = data["watchdog_metrics"]
    assert wm["total_cycles"] == 300
    assert wm["watchdog_limit_ms"] == 50.0
    assert wm["overrun_scan_dt_ms"] == 65.0
    assert wm["phase2_immediate_actuator_trip_verified"] is True
    assert wm["phase3_fail_safe_latch_verified"] is True
    assert wm["phase4_sub_0_05_verified"] is True
    assert wm["phase4_recovery_final_error_percent"] < 0.05

    assert data["safety_audit"]["physical_plc_download_blocked"] is True
    assert data["safety_audit"]["zero_physical_hardware_touched"] is True
    assert data["safety_audit"]["zero_straton_dependencies"] is True
