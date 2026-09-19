"""Automated Pytest Suite for Step 21: Live Compile-to-Simulation Toolchain Chain."""
import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step21_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step21_live_gui_compile_chain_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 21
    assert data["status"] == "VERIFIED_LIVE"
    assert data["compile_success"] is True
    assert data["simulation_converged"] is True
    assert data["final_error_pct"] < 0.05
    assert data["download_lockout_enforced"] is True
    assert data["cscape_healthy"] is True
    assert data["cscape_pid"] > 0


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step21_audit_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "mcp_live_gui_compile_chain_audit.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 21
    assert data["compilation_result"]["success"] is True
    assert data["compilation_result"]["error_count"] == 0
    assert data["compilation_result"]["hardware_lockout_enforced"] is True
    assert data["chained_simulation_result"]["converged"] is True
    assert data["safety_audit"]["controller_download_32827_blocked"] is True
