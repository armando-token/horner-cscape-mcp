"""Automated Pytest Suite for Step 43: Multi-Client Concurrent Lockout & Partitioning Audit."""
import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step43_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step43_multi_client_lockout_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 43
    assert data["status"] == "VERIFIED_LIVE"
    assert data["cscape_pid"] > 0
    assert data["cscape_healthy"] is True
    assert data["num_clients"] == 5
    assert data["total_sim_cycles"] == 600
    assert data["state_partitioning_verified"] is True
    assert data["all_clients_sub_0_05_verified"] is True
    assert data["concurrent_compiles_passed"] == 3
    assert data["hardware_lockout_enforced"] is True


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step43_audit_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "mcp_multi_client_lockout_audit.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 43
    assert data["status"] == "VERIFIED_LIVE"

    proc_info = data["cscape_active_process"]
    assert proc_info["pid"] > 0
    assert proc_info["is_hung"] is False
    assert proc_info["wm_null_ping_ok"] is True

    mc_m = data["multi_client_metrics"]
    assert mc_m["num_clients"] == 5
    assert mc_m["total_sim_cycles"] == 600
    assert mc_m["all_clients_converged_sub_0_05"] is True
    assert mc_m["state_cross_talk_detected"] is False
    assert mc_m["state_partitioning_verified"] is True

    cc_m = data["concurrent_compile_metrics"]
    assert cc_m["concurrent_compiles_requested"] == 3
    assert cc_m["all_compiles_succeeded"] is True
    assert cc_m["total_errors"] == 0
    assert cc_m["mutex_lock_enforced"] is True

    assert data["safety_audit"]["physical_plc_download_blocked"] is True
    assert data["safety_audit"]["all_downloads_blocked_fail_closed"] is True
    assert data["safety_audit"]["zero_physical_hardware_touched"] is True
    assert data["safety_audit"]["zero_straton_dependencies"] is True
