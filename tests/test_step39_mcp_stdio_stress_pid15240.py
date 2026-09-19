"""Automated Pytest Suite for Step 39: FastMCP Pipelined Stdio Stress Benchmark on PID 15240."""
import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step39_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step39_mcp_stdio_stress_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 39
    assert data["status"] == "VERIFIED_LIVE"
    assert data["cscape_pid"] > 0
    assert data["cscape_healthy"] is True
    assert data["total_calls"] == 100
    assert data["error_count"] == 0
    assert data["throughput_calls_per_sec"] >= 4.0
    assert data["hardware_lockout_enforced"] is True


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step39_audit_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "mcp_stdio_stress_pid15240.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 39
    assert data["status"] == "VERIFIED_LIVE"

    proc_info = data["cscape_active_process"]
    assert proc_info["pid"] > 0
    assert proc_info["is_hung"] is False
    assert proc_info["wm_null_ping_ok"] is True

    stress_m = data["stress_metrics"]
    assert stress_m["total_calls"] == 100
    assert stress_m["success_rate_percent"] == 100.0
    assert stress_m["errors"] == 0
    assert len(stress_m["tool_call_counts"]) == 5

    assert data["safety_audit"]["physical_plc_download_blocked"] is True
    assert data["safety_audit"]["zero_physical_hardware_touched"] is True
    assert data["safety_audit"]["zero_straton_dependencies"] is True
