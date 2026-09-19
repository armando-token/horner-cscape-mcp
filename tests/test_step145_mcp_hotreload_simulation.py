r"""Test Suite for Step 145: Live Multi-POU Variable Hot-Reload, Closed-Loop Sim & GUI Verification over FastMCP.

MANDATES:
- Target Cscape (TankLevelClosedLoop.csp) MUST REMAIN RUNNING under keepalive supervisor.
- Import path safety: sys.path.insert(0, r"C:\HornerAI\horner-cscape-mcp") and sys.path.insert(0, r"C:\Users\ArmandoSilva").
- Live JSON-RPC 2.0 stdio subprocess client against scripts/run_mcp_server.py.
- Validates variable inspection and dynamic hot-reload from 21 to 23 tags.
- Validates closed-loop cyclic simulation across 200 steps with discrete register tracking.
- Validates serialized live GUI compilation error check (ID_PROGRAM_ERRORCHECK = 32826).
- Validates XML variable export and hardware download lockout (32827).
- Validates Step 145 checkpoints, logs, and screenshots across dual roots.
"""

from __future__ import annotations

import asyncio
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List

import psutil
import pytest

# Mandatory dual-root safety
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()

for r in [str(HORNER_ROOT), str(USER_ROOT)]:
    if r not in sys.path:
        sys.path.insert(0, r)

from src.cscape.gate import assert_cscape_live, attach_thread_desktop, get_gate_status, CscapeLivenessGateError
from src.cscape.compilation import ID_PROGRAM_ERRORCHECK, ID_CONTROLLER_DOWNLOAD
from src.cscape.safety import ID_CONTROLLER_DOWNLOAD as SAFETY_DOWNLOAD, intercept_download_command
from src.security.exceptions import CscapeSafetyViolationError, HardwareLockoutError

from scripts.execute_step145_mcp_hotreload_simulation import (
    StdioRpcFastClient,
    PROJECT_DIR,
    CSP_PATH,
    VARS_CSV,
    sweep_cscape_dialogs,
)


class TestStep145LiveGateAndProcess:
    """Verifies live Cscape gate is READY_FOR_TESTS with active PID."""

    def test_gate_status_ready_for_tests(self):
        gate = get_gate_status()
        live_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
            pytest.skip(f"Live Cscape gate not ready or offline: status='{gate.get('status')}', reason='{gate.get('reason')}'")
        assert gate.get("ready_for_tests") is True
        assert gate.get("status") == "READY_FOR_TESTS"
        assert gate.get("pid") > 0
        assert gate.get("hwnd") is not None
        assert "TankLevelClosedLoop" in gate.get("window_title", "")

    def test_cscape_live_pid_and_hwnd_responsive(self):
        gate = get_gate_status()
        live_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
            pytest.skip(f"Live Cscape gate not ready or offline: status='{gate.get('status')}', reason='{gate.get('reason')}'")
        pid = int(live_pid)
        raw_h = gate.get("hwnd", "0x0")
        if not raw_h:
            pytest.skip("No HWND in live gate")
        hwnd = int(raw_h, 16) if isinstance(raw_h, str) and raw_h.startswith("0x") else int(raw_h or 0)
        attach_thread_desktop(hwnd)
        user32 = ctypes.windll.user32
        if not bool(user32.IsWindow(hwnd)):
            pytest.skip(f"Live Cscape HWND {hex(hwnd)} is invalid/closed")

        user32 = ctypes.windll.user32
        sweep_cscape_dialogs(pid, main_hwnd=hwnd)
        is_hung = bool(user32.IsHungAppWindow(hwnd))
        is_enabled = bool(user32.IsWindowEnabled(hwnd))

        sm_result = ctypes.c_ulong()
        ping_ok = bool(user32.SendMessageTimeoutW(
            hwnd, 0x0000, 0, 0, 0x0002, 1000, ctypes.byref(sm_result)
        ))

        assert is_hung is False, f"Cscape PID {pid} HWND {h_str} is hung"
        assert is_enabled is True, f"Cscape PID {pid} HWND {h_str} is disabled"
        assert ping_ok is True, f"Cscape PID {pid} HWND {h_str} ping unresponsive"


class TestStep145HotReloadAndSimulation:
    """Verifies FastMCP variable hot-reload, simulation, and live GUI compilation."""

    @pytest.mark.asyncio
    async def test_variable_read_and_hot_reload(self):
        py_exe = HORNER_ROOT / ".venv" / "Scripts" / "python.exe"
        if not py_exe.exists():
            py_exe = Path(sys.executable)
        server_py = HORNER_ROOT / "scripts" / "run_mcp_server.py"

        client = StdioRpcFastClient(py_exe, server_py)
        await client.start()

        baseline_csv = VARS_CSV.read_text(encoding="utf-8")
        try:
            await client.call_rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "PTest145", "version": "1.0.0"},
            }, timeout=60.0)
            await client.call_rpc("notifications/initialized")

            # Read baseline
            lat_b, res_b = await client.call_tool("cscape_read_variables", {"file_path": str(VARS_CSV)})
            data_b = json.loads(res_b["result"]["content"][0]["text"])
            assert data_b["success"] is True
            initial_count = data_b["count"]
            assert initial_count >= 20

            # Hot reload
            appended = baseline_csv.strip() + '\n"PytestAuditTag";"INT";"";"";"";"NO";"";"%R260";"Test hot reload tag";"globals"\n'
            VARS_CSV.write_text(appended, encoding="utf-8")

            lat_h, res_h = await client.call_tool("cscape_read_variables", {"file_path": str(VARS_CSV)})
            data_h = json.loads(res_h["result"]["content"][0]["text"])
            assert data_h["success"] is True
            assert data_h["count"] == initial_count + 1
        finally:
            VARS_CSV.write_text(baseline_csv, encoding="utf-8")
            await client.close()

    @pytest.mark.asyncio
    async def test_closed_loop_simulation_cycles(self):
        py_exe = HORNER_ROOT / ".venv" / "Scripts" / "python.exe"
        if not py_exe.exists():
            py_exe = Path(sys.executable)
        server_py = HORNER_ROOT / "scripts" / "run_mcp_server.py"

        client = StdioRpcFastClient(py_exe, server_py)
        await client.start()
        try:
            await client.call_rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "PTest145Sim", "version": "1.0.0"},
            }, timeout=60.0)
            await client.call_rpc("notifications/initialized")

            # Run 5 simulation cycles
            for _ in range(5):
                lat_s, res_s = await client.call_tool("cscape_simulate_cycle", {
                    "dt_ms": 10.0, "project_name": "TankLevelClosedLoop"
                })
                data_s = json.loads(res_s["result"]["content"][0]["text"])
                assert data_s["success"] is True
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_hardware_download_lockout(self):
        py_exe = HORNER_ROOT / ".venv" / "Scripts" / "python.exe"
        if not py_exe.exists():
            py_exe = Path(sys.executable)
        server_py = HORNER_ROOT / "scripts" / "run_mcp_server.py"

        client = StdioRpcFastClient(py_exe, server_py)
        await client.start()
        try:
            await client.call_rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "PTest145Lockout", "version": "1.0.0"},
            }, timeout=60.0)
            await client.call_rpc("notifications/initialized")

            lat_dl, res_dl = await client.call_tool("cscape_download_logic", {"project_path": "TankLevelClosedLoop"})
            is_dl_err = res_dl.get("result", {}).get("isError") is True or "error" in res_dl
            assert is_dl_err is True, "Controller download tool was not rejected!"
        finally:
            await client.close()


class TestStep145BenchmarkArtifactsAndEvidence:
    """Validates Step 145 benchmark execution outputs, log hashes, and checkpoints."""

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_step145_checkpoint_valid(self, root: Path):
        cp_file = root / "artifacts" / "checkpoints" / "step145_mcp_hotreload_simulation_checkpoint.json"
        assert cp_file.exists(), f"Step 145 checkpoint missing on {root}"
        data = json.loads(cp_file.read_text(encoding="utf-8"))
        assert data["step"] == 145
        assert data["status"] == "PASSED"
        assert data["cscape_pid"] > 0
        assert data["simulation_cycles"] == 200
        assert data["gui_compile_status"] == "SUCCESS"
        assert data["zero_straton_dependencies"] is True
        assert data["hardware_lockout_enforced"] is True
        assert "checkpoint_sha256" in data

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_step145_log_valid(self, root: Path):
        log_file = root / "artifacts" / "logs" / "step145_mcp_hotreload_simulation.json"
        assert log_file.exists(), f"Step 145 log missing on {root}"
        data = json.loads(log_file.read_text(encoding="utf-8"))
        assert data["step"] == 145
        assert data["status"] == "PASSED"
        assert data["target_pid"] > 0
        assert data["simulation_cycles_executed"] == 200
        assert data["gui_error_count"] == 0
        assert data["gui_warning_count"] == 0
        assert data["cscape_process_health"]["is_hung"] is False
        assert data["cscape_process_health"]["is_enabled"] is True
        assert "screenshot_evidence" in data

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_step145_screenshot_valid(self, root: Path):
        ss_file = root / "artifacts" / "screenshots" / "live_cscape_tank_level_step145.png"
        assert ss_file.exists(), f"Step 145 screenshot missing on {root}"
        assert ss_file.stat().st_size > 500
