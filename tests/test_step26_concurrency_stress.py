"""Automated Pytest Suite for Step 26: Multi-Worker Concurrent Closed-Loop Stress & Client Isolation Audit."""
import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step26_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step26_concurrency_stress_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 26
    assert data["status"] == "VERIFIED_LIVE"
    assert data["num_workers"] == 8
    assert data["total_cycles"] == 800
    assert data["aggregate_throughput_cycles_per_sec"] > 500.0
    assert data["hardware_lockout_enforced"] is True
    assert data["cscape_healthy"] is True
    assert data["cscape_pid"] > 0


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step26_audit_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "mcp_concurrent_simulation_stress_audit.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 26
    assert data["status"] == "VERIFIED_LIVE"
    assert data["cscape_process"]["healthy"] is True
    assert data["cscape_process"]["pid"] > 0
    assert data["cscape_process"]["is_hung"] is False
    metrics = data["concurrency_metrics"]
    assert metrics["num_workers"] == 8
    assert metrics["cycles_per_worker"] == 100
    assert metrics["total_cycles"] == 800
    assert metrics["aggregate_throughput_cycles_per_sec"] > 500.0
    assert metrics["all_workers_succeeded"] is True
    assert len(data["worker_results"]) == 8
    for w in data["worker_results"]:
        assert w["final_error_pct"] <= 0.10
    assert data["safety_audit"]["physical_plc_download_blocked"] is True
    assert data["safety_audit"]["zero_physical_hardware_touched"] is True
    assert data["safety_audit"]["hardware_lockout_enforced"] is True
