"""Automated Pytest Suite for Step 42: Cyclic Scan Jitter & Discretization Invariance Audit."""
import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step42_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step42_discretization_invariance_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 42
    assert data["status"] == "VERIFIED_LIVE"
    assert data["cscape_pid"] > 0
    assert data["cscape_healthy"] is True
    assert data["total_cycles"] == 2725
    assert data["scan_rates_count"] == 6
    assert data["all_rates_sub_0_05_verified"] is True
    assert data["dt1ms_final_error_percent"] < 0.05
    assert data["dt10ms_final_error_percent"] < 0.05
    assert data["dt50ms_final_error_percent"] < 0.05
    assert data["hardware_lockout_enforced"] is True


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step42_audit_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "mcp_discretization_invariance_audit.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 42
    assert data["status"] == "VERIFIED_LIVE"

    proc_info = data["cscape_active_process"]
    assert proc_info["pid"] > 0
    assert proc_info["is_hung"] is False
    assert proc_info["wm_null_ping_ok"] is True

    disc_m = data["discretization_metrics"]
    assert disc_m["total_cycles"] == 2725
    assert disc_m["scan_rates_tested"] == 6
    assert disc_m["all_rates_converged_sub_0_05"] is True
    assert len(disc_m["rate_results"]) == 6

    for rate_key, res in disc_m["rate_results"].items():
        assert res["converged_sub_0_05"] is True
        assert res["final_error_percent"] < 0.05

    assert data["safety_audit"]["physical_plc_download_blocked"] is True
    assert data["safety_audit"]["zero_physical_hardware_touched"] is True
    assert data["safety_audit"]["zero_straton_dependencies"] is True
