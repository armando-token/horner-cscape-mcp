"""Automated Pytest Suite for Step 35: Multi-Setpoint Sequence & Settling Time Benchmark."""
import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step35_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step35_multistep_settling_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 35
    assert data["status"] == "VERIFIED_LIVE"
    assert data["total_cycles"] == 500
    assert data["all_stages_settled_verified"] is True
    assert data["max_settling_cycles"] <= 45
    for s_name, s_info in data["stage_metrics"].items():
        assert s_info["settling_verified"] is True
        assert s_info["final_error_pct"] <= 0.15
    assert data["hardware_lockout_enforced"] is True
    assert data["cscape_healthy"] is True
    assert data["cscape_pid"] > 0


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step35_audit_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "mcp_multistep_settling_audit.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 35
    assert data["status"] == "VERIFIED_LIVE"
    assert data["cscape_process"]["healthy"] is True
    assert data["cscape_process"]["pid"] > 0
    assert data["cscape_process"]["is_hung"] is False
    sim = data["simulation_summary"]
    assert sim["total_cycles"] == 500
    assert sim["throughput_cycles_per_sec"] > 500.0
    metrics = data["stage_metrics"]
    assert len(metrics) == 5
    for s_name, s_info in metrics.items():
        assert s_info["settling_verified"] is True
        assert s_info["settling_cycles"] <= 45
        assert s_info["final_error_pct"] <= 0.15
    assert data["safety_audit"]["physical_plc_download_blocked"] is True
    assert data["safety_audit"]["zero_physical_hardware_touched"] is True
    assert data["safety_audit"]["hardware_lockout_enforced"] is True
