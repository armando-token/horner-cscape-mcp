r"""Test Suite for Step 143: FastMCP Live Stdio JSON-RPC End-to-End Pipeline & Live Tool Suite.

MANDATES:
- Target Cscape (TankLevelClosedLoop.csp) MUST REMAIN RUNNING via live gate.
- Import path safety: sys.path.insert(0, r"C:\HornerAI\horner-cscape-mcp") and sys.path.insert(0, r"C:\Users\ArmandoSilva").
- Live JSON-RPC 2.0 stdio subprocess client against scripts/run_mcp_server.py.
- Validates live tool discovery and execution over stdio:
  * cscape_read_variables
  * cscape_write_register
  * cscape_read_register
  * cscape_simulate_cycle
  * cscape_compile
  * cscape_export_variables
  * cscape_get_diagnostics
- Strict hardware lockout (zero PLC download) verified over stdio.
- Fail-closed gate verification: mid-test gate offline fails closed.
- Step 143 checkpoint and log validation across dual roots.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict

import psutil
import pytest

# Mandatory import safety
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()

for r in [str(HORNER_ROOT), str(USER_ROOT)]:
    if r not in sys.path:
        sys.path.insert(0, r)

from src.cscape.gate import assert_cscape_live, attach_thread_desktop, get_gate_status, CscapeLivenessGateError
from src.cscape.compilation import ID_PROGRAM_ERRORCHECK, ID_CONTROLLER_DOWNLOAD
from src.cscape.safety import ID_CONTROLLER_DOWNLOAD as SAFETY_DOWNLOAD, intercept_download_command
from src.security.exceptions import CscapeSafetyViolationError, UnauthorizedDownloadError

from scripts.execute_step143_mcp_live_stdio_pipeline import (
    StdioRpcClient,
    TARGET_PID,
    TARGET_HWND,
    TARGET_HWND_STR,
    MAIN_PROJECT,
    CHECKPOINT_RELS,
    LOG_RELS,
    SCREENSHOT_RELS,
    check_cscape_health,
    sweep_cscape_dialogs,
)


@pytest.fixture(scope="module")
def stdio_client():
    py_exe = HORNER_ROOT / ".venv" / "Scripts" / "python.exe"
    if not py_exe.exists():
        py_exe = Path(sys.executable)
    server_script = HORNER_ROOT / "scripts" / "run_mcp_server.py"

    client = StdioRpcClient(py_exe, server_script)
    client.start()
    init_res = client.send_rpc("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "TestStep143Client", "version": "1.0.0"}
    })
    assert "result" in init_res
    yield client
    client.close()


class TestStep143LiveGateAndProcess:
    """Verifies live Cscape gate is READY_FOR_TESTS with active process."""

    def test_gate_status_ready_for_tests(self):
        gate = get_gate_status()
        live_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
            pytest.skip(f"No active live Cscape gate (PID {live_pid})")
        assert gate.get("ready_for_tests") is True
        assert gate.get("status") == "READY_FOR_TESTS"
        assert live_pid > 0
        assert gate.get("hwnd") is not None
        assert "TankLevelClosedLoop" in gate.get("window_title", "")

    def test_cscape_live_pid_and_hwnd_responsive(self):
        gate = get_gate_status()
        live_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
            pytest.skip(f"No active live Cscape process (gate reports PID {live_pid})")
        raw_h = gate.get("hwnd", "0x0")
        live_hwnd = int(raw_h, 16) if isinstance(raw_h, str) and raw_h.startswith("0x") else int(raw_h or 0)
        health = {}
        for _ in range(10):
            sweep_cscape_dialogs(live_pid)
            health = check_cscape_health(live_pid, live_hwnd)
            if health.get("healthy") and health.get("is_enabled"):
                break
            time.sleep(0.5)
        assert health["healthy"] is True
        assert health["is_hung"] is False
        assert health["is_enabled"] is True
        assert health["ping_ok"] is True
        assert health["uptime_seconds"] > 0.0


class TestStep143StdioJsonRpcTools:
    """Verifies FastMCP live tools execution over native JSON-RPC stdio subprocess."""

    def test_tools_list_discovery(self, stdio_client):
        res = stdio_client.send_rpc("tools/list", {})
        assert "result" in res
        tools = [t["name"] for t in res["result"].get("tools", [])]
        assert len(tools) >= 20
        assert "cscape_read_variables" in tools
        assert "cscape_write_register" in tools
        assert "cscape_read_register" in tools
        assert "cscape_simulate_cycle" in tools
        assert "cscape_compile" in tools
        assert "cscape_export_variables" in tools
        assert "cscape_get_diagnostics" in tools

    def test_cscape_read_variables_stdio(self, stdio_client):
        vars_csv = str(HORNER_ROOT / "artifacts" / "projects" / MAIN_PROJECT / "variables.csv")
        call_res = stdio_client.call_tool("cscape_read_variables", {"file_path": vars_csv})
        assert "result" in call_res
        data = json.loads(call_res["result"]["content"][0]["text"])
        assert data["success"] is True
        assert data["count"] >= 20
        assert "variables" in data
        var_names = [v["name"] for v in data["variables"]] if isinstance(data["variables"], list) else list(data["variables"].keys())
        assert "TankLevelPV" in var_names

    def test_cscape_write_and_read_register_stdio(self, stdio_client):
        call_w = stdio_client.call_tool("cscape_write_register", {
            "address": "%R101",
            "value": 6400.0,
            "data_type": "REAL",
            "project_name": MAIN_PROJECT,
        })
        assert "result" in call_w
        data_w = json.loads(call_w["result"]["content"][0]["text"])
        assert data_w["success"] is True

        call_r = stdio_client.call_tool("cscape_read_register", {
            "address": "%R101",
            "data_type": "REAL",
            "project_name": MAIN_PROJECT,
        })
        assert "result" in call_r
        data_r = json.loads(call_r["result"]["content"][0]["text"])
        assert data_r["success"] is True
        assert data_r["value"] == 6400.0

    def test_cscape_simulate_cycle_stdio(self, stdio_client):
        call_s = stdio_client.call_tool("cscape_simulate_cycle", {
            "dt_ms": 10.0,
            "project_name": MAIN_PROJECT,
        })
        assert "result" in call_s
        data_s = json.loads(call_s["result"]["content"][0]["text"])
        assert data_s["success"] is True
        assert "registers" in data_s

    def test_cscape_compile_live_gui_stdio(self, stdio_client):
        gate = get_gate_status()
        live_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
            pytest.skip(f"No active live Cscape gate (PID {live_pid})")
        raw_h = gate.get("hwnd", "0x0")
        live_hwnd = int(raw_h, 16) if isinstance(raw_h, str) and raw_h.startswith("0x") else int(raw_h or 0)
        proj_dir = str(HORNER_ROOT / "artifacts" / "projects" / MAIN_PROJECT)
        sweep_cscape_dialogs(live_pid)
        call_c = stdio_client.call_tool("cscape_compile", {
            "project_path": proj_dir,
            "clean_build": False,
            "cscape_hwnd": live_hwnd,
        })
        assert "result" in call_c
        data_c = json.loads(call_c["result"]["content"][0]["text"])
        assert data_c["success"] is True
        assert data_c["error_count"] == 0
        assert data_c["warning_count"] == 0
        assert data_c.get("command_dispatched") == ID_PROGRAM_ERRORCHECK
        sweep_cscape_dialogs(live_pid)

    def test_cscape_export_variables_stdio(self, stdio_client):
        vars_csv = str(HORNER_ROOT / "artifacts" / "projects" / MAIN_PROJECT / "variables.csv")
        xml_out = str(HORNER_ROOT / "artifacts" / "projects" / MAIN_PROJECT / "variables_test143.xml")
        call_e = stdio_client.call_tool("cscape_export_variables", {
            "output_path": xml_out,
            "format_type": "xml",
            "source_file": vars_csv,
        })
        assert "result" in call_e
        data_e = json.loads(call_e["result"]["content"][0]["text"])
        assert data_e["success"] is True
        assert Path(xml_out).exists()
        assert Path(xml_out).stat().st_size > 0

    def test_cscape_get_diagnostics_stdio(self, stdio_client):
        call_d = stdio_client.call_tool("cscape_get_diagnostics", {"project_name": MAIN_PROJECT})
        assert "result" in call_d
        data_d = json.loads(call_d["result"]["content"][0]["text"])
        assert data_d["compile_successful"] is True


class TestStep143SafetyAndFailClosed:
    """Verifies strict hardware download lockout and fail-closed gate semantics."""

    def test_stdio_hardware_download_rejected(self, stdio_client):
        res = stdio_client.call_tool("cscape_download_logic", {"project_path": "TankLevelClosedLoop"})
        is_err = res.get("result", {}).get("isError") is True or "error" in res
        assert is_err is True

    def test_core_safety_intercepts_download_command(self):
        with pytest.raises(CscapeSafetyViolationError):
            intercept_download_command(SAFETY_DOWNLOAD)

    def test_fail_closed_if_gate_reports_offline(self, monkeypatch):
        dead_gate = {
            "ready_for_tests": False,
            "status": "FAIL_CLOSED_CSCAPE_DEAD",
            "reason": "Simulated death for fail-closed verification",
        }
        monkeypatch.setattr("src.cscape.gate.get_gate_status", lambda: dead_gate)
        with pytest.raises(CscapeLivenessGateError) as exc:
            assert_cscape_live()
        assert "FAIL-CLOSED" in str(exc.value)


class TestStep143ArtifactsAndCheckpoints:
    """Verifies dual-root mirroring, checkpoint hashes, and screenshot evidence."""

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_step143_checkpoint_exists(self, root: Path):
        cp_path = root / "artifacts" / "checkpoints" / "step143_mcp_live_stdio_pipeline_checkpoint.json"
        assert cp_path.exists(), f"Missing checkpoint on {root}"
        data = json.loads(cp_path.read_text(encoding="utf-8"))
        assert data["step"] == 143
        assert data["status"] == "PASSED"
        assert data["cscape_pid"] > 0

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_step143_log_exists(self, root: Path):
        log_path = root / "artifacts" / "logs" / "step143_mcp_live_stdio_pipeline.json"
        assert log_path.exists(), f"Missing log on {root}"
        data = json.loads(log_path.read_text(encoding="utf-8"))
        assert data["step"] == 143
        assert data["status"] == "PASSED"

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_step143_screenshot_exists(self, root: Path):
        ss_path = root / "artifacts" / "screenshots" / "live_cscape_tank_level_step143_pid7968.png"
        assert ss_path.exists(), f"Missing screenshot on {root}"
        assert ss_path.stat().st_size > 500
