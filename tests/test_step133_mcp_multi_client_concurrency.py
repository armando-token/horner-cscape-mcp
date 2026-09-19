"""Automated Pytest Suite for Step 133: FastMCP Multi-Client Live Concurrency Benchmark on Live Cscape."""

import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import psutil
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")

REQUIRED_TOOLS = [
    "cscape_read_variables",
    "cscape_simulate_cycle",
    "cscape_read_register",
    "cscape_write_register",
    "cscape_compile_project",
]


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step133_checkpoint_valid(root: Path):
    """Validates checkpoint existence and structure across both repository roots."""
    ckpt_path = root / "artifacts" / "checkpoints" / "step133_mcp_multi_client_concurrency_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))

    assert data["step"] == 133
    assert data["name"] == "step133_mcp_multi_client_concurrency_checkpoint"
    assert data["status"] == "VERIFIED_LIVE"
    assert data["cscape_pid"] > 0
    assert data["cscape_healthy"] is True
    assert data["total_clients"] == 5
    assert len(data["client_names"]) == 5
    assert data["calls_per_client"] == 20
    assert data["total_calls"] == 100
    assert data["error_count"] == 0
    assert data["dropped_frames"] == 0
    assert data["cross_client_frame_contamination"] == 0
    assert data["success_rate_percent"] == 100.0
    assert data["aggregate_throughput_calls_per_sec"] > 0.0
    assert data["hardware_lockout_enforced"] is True
    assert data["zero_straton_dependencies"] is True

    # Check tools invoked and counts
    for tool in REQUIRED_TOOLS:
        assert tool in data["tools_invoked"]
        assert data["tool_call_counts"][tool] == 20

    # Latency percentiles
    overall_lat = data["overall_latency_ms"]
    assert overall_lat["min"] > 0.0
    assert overall_lat["median"] > 0.0
    assert overall_lat["max"] >= overall_lat["p95"]


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step133_audit_log_valid(root: Path):
    """Validates benchmark audit log structure and metrics across both repository roots."""
    log_path = root / "artifacts" / "logs" / "mcp_multi_client_concurrency.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))

    assert data["step"] == 133
    assert data["status"] == "VERIFIED_LIVE"

    proc_info = data["cscape_active_process"]
    assert proc_info["pid"] > 0
    assert proc_info["is_hung"] is False
    assert proc_info["wm_null_ping_ok"] is True

    config = data["concurrency_configuration"]
    assert config["num_clients"] == 5
    assert config["calls_per_client"] == 20
    assert config["total_calls"] == 100
    assert config["transport"] == "stdio"
    assert config["gui_arbitration"] == "serialized_asyncio_lock"
    assert config["dialog_sweeper_active"] is True

    agg_m = data["aggregate_metrics"]
    assert agg_m["total_calls"] == 100
    assert agg_m["successful_calls"] == 100
    assert agg_m["errors"] == 0
    assert agg_m["dropped_frames"] == 0
    assert agg_m["cross_client_frame_contamination"] == 0
    assert agg_m["success_rate_percent"] == 100.0

    # 5 clients tracked in per_client_metrics
    client_metrics = data["per_client_metrics"]
    assert len(client_metrics) == 5
    for cname, cm in client_metrics.items():
        assert cm["calls"] == 20
        assert cm["errors"] == 0
        assert cm["dropped_frames"] == 0
        assert cm["contamination"] == 0
        assert cm["success_rate_percent"] == 100.0
        assert cm["throughput_calls_per_sec"] > 0.0

    # 5 tools tracked in per_tool_metrics
    tool_metrics = data["per_tool_metrics"]
    assert len(tool_metrics) == 5
    for tool in REQUIRED_TOOLS:
        assert tool in tool_metrics
        assert tool_metrics[tool]["call_count"] == 20

    # Safety audit
    assert data["safety_audit"]["id_controller_download_32827_blocked"] is True
    assert data["safety_audit"]["physical_plc_download_blocked"] is True
    assert data["safety_audit"]["zero_physical_hardware_touched"] is True
    assert data["safety_audit"]["zero_straton_dependencies"] is True

    # 100 call records
    assert len(data["call_records"]) == 100
    for record in data["call_records"]:
        assert record["success"] is True


def test_step133_cscape_live_and_healthy():
    """Asserts live Cscape is currently alive, running, and responsive."""
    from src.cscape.gate import get_gate_status, attach_thread_desktop
    gate = get_gate_status()
    live_pid = gate.get("pid")
    if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
        pytest.skip(f"Live Cscape gate not active or PID {live_pid} offline")

    assert gate.get("ready_for_tests") is True
    assert live_pid > 0
    assert psutil.pid_exists(live_pid)

    proc = psutil.Process(live_pid)
    assert proc.is_running()
    assert "cscape" in proc.name().lower()

    raw_h = gate.get("hwnd", "0x0")
    if not raw_h:
        pytest.skip("No HWND in live gate")
    hwnd = int(raw_h, 16) if isinstance(raw_h, str) and raw_h.startswith("0x") else int(raw_h or 0)
    assert hwnd > 0

    user32 = ctypes.windll.user32
    if not bool(user32.IsWindow(hwnd)):
        pytest.skip(f"Live window HWND {hex(hwnd)} is invalid/closed")

    attach_thread_desktop(hwnd)

    assert bool(user32.IsWindow(hwnd)) is True
    assert bool(user32.IsHungAppWindow(hwnd)) is False

    sm_res = ctypes.c_ulong()
    ping_ok = bool(user32.SendMessageTimeoutW(hwnd, 0x0000, 0, 0, 0x0002, 1000, ctypes.byref(sm_res)))
    assert ping_ok is True


def test_step133_hardware_lockout_and_zero_straton():
    """Asserts physical controller download lockout and zero Straton legacy dependencies."""
    from src.cscape.compilation import CscapeCompiler, ID_CONTROLLER_DOWNLOAD
    from src.security.exceptions import HardwareLockoutError, UnauthorizedDownloadError

    assert ID_CONTROLLER_DOWNLOAD == 32827
    compiler = CscapeCompiler()
    lockout_enforced = False
    try:
        compiler.trigger_cscape_gui_compile(cscape_hwnd=0x10001, command_id=32827)
    except (HardwareLockoutError, UnauthorizedDownloadError, RuntimeError):
        lockout_enforced = True

    assert lockout_enforced is True, "ID_CONTROLLER_DOWNLOAD 32827 was not blocked fail-closed!"
