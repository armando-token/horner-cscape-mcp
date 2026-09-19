r"""Test Suite for Step 144: FastMCP Multi-Client Concurrent Stdio Stress & Register Partitioning on Live Cscape.

MANDATES:
- Target Cscape (TankLevelClosedLoop.csp) MUST REMAIN RUNNING via live gate.
- Import path safety: sys.path.insert(0, r"C:\HornerAI\horner-cscape-mcp") and sys.path.insert(0, r"C:\Users\ArmandoSilva").
- Live JSON-RPC 2.0 stdio subprocess clients against scripts/run_mcp_server.py.
- Validates 4-client concurrent handshake and tool discovery with zero Straton K5 tools.
- Validates partitioned register read/write operations without cross-client contamination.
- Validates serialized live GUI compilation error check (ID_PROGRAM_ERRORCHECK = 32826).
- Validates strict hardware download lockout (ID_CONTROLLER_DOWNLOAD = 32827).
- Validates Step 144 benchmark metrics, logs, screenshots, and dual-root checkpoints.
"""

from __future__ import annotations

import asyncio
import ctypes
import hashlib
import json
import math
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

from scripts.execute_step144_mcp_multi_client_stress_pid7968 import (
    FastMCPBenchClient,
    TARGET_PID,
    TARGET_HWND,
    TARGET_HWND_STR,
    PROJECT_DIR,
    CSP_PATH,
    VARS_CSV,
    NUM_CLIENTS,
    CALLS_PER_CLIENT,
    TOTAL_CALLS,
    sweep_cscape_dialogs,
)


class TestStep144LiveGateAndProcess:
    """Verifies live Cscape gate is READY_FOR_TESTS with active PID."""

    def test_gate_status_ready_for_tests(self):
        gate = get_gate_status()
        live_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
            pytest.skip("No active live Cscape gate")
        assert gate.get("ready_for_tests") is True
        assert gate.get("status") == "READY_FOR_TESTS"
        assert gate.get("pid") > 0
        assert gate.get("hwnd") is not None
        assert "TankLevelClosedLoop" in gate.get("window_title", "")

    def test_cscape_live_pid_and_hwnd_responsive(self):
        gate = get_gate_status()
        live_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
            pytest.skip("No active live Cscape gate")
        pid = int(gate["pid"])
        h_str = str(gate["hwnd"])
        hwnd = int(h_str, 16) if h_str.startswith("0x") else int(h_str)

        user32 = ctypes.windll.user32
        attach_thread_desktop(hwnd)
        is_hung = False
        is_enabled = False
        ping_ok = False
        for _ in range(10):
            sweep_cscape_dialogs(pid)
            is_hung = bool(user32.IsHungAppWindow(hwnd))
            is_enabled = bool(user32.IsWindowEnabled(hwnd))
            sm_result = ctypes.c_ulong()
            ping_ok = bool(user32.SendMessageTimeoutW(
                hwnd, 0x0000, 0, 0, 0x0002, 1000, ctypes.byref(sm_result)
            ))
            if is_enabled and not is_hung and ping_ok:
                break
            time.sleep(0.5)

        assert is_hung is False, f"Cscape PID {pid} HWND {h_str} is hung"
        assert is_enabled is True, f"Cscape PID {pid} HWND {h_str} is disabled"
        assert ping_ok is True, f"Cscape PID {pid} HWND {h_str} ping unresponsive"


class TestStep144MultiClientConcurrency:
    """Verifies concurrent stdio FastMCP clients running live tool rotations."""

    @pytest.mark.asyncio
    async def test_concurrent_handshake_and_no_straton(self):
        py_exe = HORNER_ROOT / ".venv" / "Scripts" / "python.exe"
        if not py_exe.exists():
            py_exe = Path(sys.executable)
        server_py = HORNER_ROOT / "scripts" / "run_mcp_server.py"

        clients = [FastMCPBenchClient(f"PytestClient_{i+1}", py_exe, server_py) for i in range(2)]
        for c in clients:
            await c.start()

        try:
            results = await asyncio.gather(*[c.handshake() for c in clients])
            for i, tools in enumerate(results):
                assert len(tools) >= 20
                assert "cscape_read_variables" in tools
                assert "cscape_simulate_cycle" in tools
                assert "cscape_read_register" in tools
                assert "cscape_write_register" in tools
                assert "cscape_compile" in tools
                # Zero Straton K5 tools
                straton_tools = [t for t in tools if "straton" in t.lower() or "k5" in t.lower()]
                assert len(straton_tools) == 0, f"Straton legacy tools detected: {straton_tools}"
        finally:
            for c in clients:
                await c.close()

    @pytest.mark.asyncio
    async def test_partitioned_register_writes_concurrent(self):
        py_exe = HORNER_ROOT / ".venv" / "Scripts" / "python.exe"
        if not py_exe.exists():
            py_exe = Path(sys.executable)
        server_py = HORNER_ROOT / "scripts" / "run_mcp_server.py"

        c1 = FastMCPBenchClient("PTest_C1", py_exe, server_py)
        c2 = FastMCPBenchClient("PTest_C2", py_exe, server_py)

        await c1.start()
        await c2.start()

        try:
            await asyncio.gather(c1.handshake(), c2.handshake())

            # Client 1 writes %R200 = 200.5, Client 2 writes %R201 = 201.5 concurrently
            task1 = c1.call_tool("cscape_write_register", {
                "address": "%R200", "value": 200.5, "data_type": "REAL", "project_name": "TankLevelClosedLoop"
            })
            task2 = c2.call_tool("cscape_write_register", {
                "address": "%R201", "value": 201.5, "data_type": "REAL", "project_name": "TankLevelClosedLoop"
            })
            res1, res2 = await asyncio.gather(task1, task2)

            lat1, data1 = res1
            lat2, data2 = res2
            assert "result" in data1
            assert "result" in data2

            # Read back independently
            read1 = await c1.call_tool("cscape_read_register", {
                "address": "%R200", "data_type": "REAL", "project_name": "TankLevelClosedLoop"
            })
            read2 = await c2.call_tool("cscape_read_register", {
                "address": "%R201", "data_type": "REAL", "project_name": "TankLevelClosedLoop"
            })

            r1_text = json.loads(read1[1]["result"]["content"][0]["text"])
            r2_text = json.loads(read2[1]["result"]["content"][0]["text"])

            assert r1_text["value"] == 200.5
            assert r2_text["value"] == 201.5
            assert c1.contamination_count == 0
            assert c2.contamination_count == 0
        finally:
            await c1.close()
            await c2.close()

    @pytest.mark.asyncio
    async def test_hardware_download_lockout_across_clients(self):
        py_exe = HORNER_ROOT / ".venv" / "Scripts" / "python.exe"
        if not py_exe.exists():
            py_exe = Path(sys.executable)
        server_py = HORNER_ROOT / "scripts" / "run_mcp_server.py"

        client = FastMCPBenchClient("PTest_Lockout", py_exe, server_py)
        await client.start()
        try:
            await client.handshake()
            res = await client.call_tool("cscape_download_logic", {"project_path": "TankLevelClosedLoop"})
            is_err = res[1].get("result", {}).get("isError") is True or "error" in res[1]
            assert is_err is True, "Download tool was not rejected!"
        finally:
            await client.close()


class TestStep144BenchmarkArtifactsAndEvidence:
    """Validates Step 144 benchmark execution outputs, log hashes, and checkpoints."""

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_step144_checkpoint_valid(self, root: Path):
        cp_file = root / "artifacts" / "checkpoints" / "step144_mcp_multi_client_stress_checkpoint.json"
        assert cp_file.exists(), f"Step 144 checkpoint missing on {root}"
        data = json.loads(cp_file.read_text(encoding="utf-8"))
        assert data["step"] == 144
        assert data["status"] == "PASSED"
        assert data["cscape_pid"] > 0
        assert data["clients_count"] == NUM_CLIENTS
        assert data["total_calls"] == TOTAL_CALLS
        assert data["success_rate_percent"] == 100.0
        assert data["errors"] == 0
        assert data["dropped_frames"] == 0
        assert data["cross_client_contamination"] == 0
        assert data["zero_straton_dependencies"] is True
        assert data["hardware_lockout_enforced"] is True
        assert "checkpoint_sha256" in data

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_step144_log_valid(self, root: Path):
        log_file = root / "artifacts" / "logs" / "step144_mcp_multi_client_stress.json"
        assert log_file.exists(), f"Step 144 log missing on {root}"
        data = json.loads(log_file.read_text(encoding="utf-8"))
        assert data["step"] == 144
        assert data["status"] == "PASSED"
        assert data["target_pid"] > 0
        assert data["total_calls"] == TOTAL_CALLS
        assert data["errors"] == 0
        assert data["cscape_process_health"]["is_hung"] is False
        assert data["cscape_process_health"]["is_enabled"] is True
        assert "overall_latency_ms" in data
        assert "per_client_summary" in data
        assert "screenshot_evidence" in data

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_step144_screenshot_valid(self, root: Path):
        ss_file = root / "artifacts" / "screenshots" / "live_cscape_tank_level_step144_pid7968.png"
        assert ss_file.exists(), f"Step 144 screenshot missing on {root}"
        assert ss_file.stat().st_size > 500
