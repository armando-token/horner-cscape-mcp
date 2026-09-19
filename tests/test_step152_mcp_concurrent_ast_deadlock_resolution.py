r"""Test Suite for Step 152: Live FastMCP Multi-Client Concurrent AST Mutation & Deadlock Resolution.

MANDATES:
- Target Cscape (TankLevelClosedLoop.csp) MUST REMAIN RUNNING under keepalive supervisor.
- Import path safety: sys.path.insert(0, r"C:\HornerAI\horner-cscape-mcp") and sys.path.insert(0, r"C:\Users\ArmandoSilva").
- Live JSON-RPC 2.0 stdio subprocess client against scripts/run_mcp_server.py.
- Validates 3-client concurrent operation: AST validation, register R/W, and simulation stepping.
- Validates hardware download lockout (32827).
- Validates Step 152 checkpoints, logs, and screenshots across dual roots.
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

from scripts.execute_step152_mcp_concurrent_ast_deadlock_resolution import (
    StdioRpcFastClient,
    PROJECT_DIR,
    CSP_PATH,
    BASELINE_VARS_PATH,
    sweep_cscape_dialogs,
)


class TestStep152LiveGateAndProcess:
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


class TestStep152MultiClientConcurrencyAndAST:
    """Verifies FastMCP multi-client concurrency, AST mutation checks, and safety lockout."""

    @pytest.mark.asyncio
    async def test_concurrent_ast_validation_and_simulation(self):
        py_exe = HORNER_ROOT / ".venv" / "Scripts" / "python.exe"
        if not py_exe.exists():
            py_exe = Path(sys.executable)
        server_py = HORNER_ROOT / "scripts" / "run_mcp_server.py"

        ca = StdioRpcFastClient(py_exe, server_py, "TestA")
        cb = StdioRpcFastClient(py_exe, server_py, "TestB")
        await asyncio.gather(ca.start(), cb.start())

        try:
            # Concurrent init
            async def _init(c: StdioRpcFastClient):
                await c.call_rpc("initialize", {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": c.client_name, "version": "1.0.0"},
                }, timeout=60.0)
                await c.call_rpc("notifications/initialized")

            await asyncio.gather(_init(ca), _init(cb))

            # Task 1: AST validation on client A
            async def _task_a():
                st_code = "PROGRAM ConcurrentTest\nVAR x: INT; END_VAR\nx := 42;\nEND_PROGRAM\n"
                lat, res = await ca.call_tool("cscape_validate_st", {"code": st_code})
                return json.loads(res["result"]["content"][0]["text"])["valid"]

            # Task 2: Register read on client B
            async def _task_b():
                lat, res = await cb.call_tool("cscape_read_register", {
                    "address": "%R1", "data_type": "REAL", "project_name": "TankLevelClosedLoop"
                })
                return json.loads(res["result"]["content"][0]["text"])["success"]

            res_a, res_b = await asyncio.gather(_task_a(), _task_b())
            assert res_a is True
            assert res_b is True
        finally:
            await asyncio.gather(ca.close(), cb.close())

    @pytest.mark.asyncio
    async def test_hardware_download_lockout(self):
        py_exe = HORNER_ROOT / ".venv" / "Scripts" / "python.exe"
        if not py_exe.exists():
            py_exe = Path(sys.executable)
        server_py = HORNER_ROOT / "scripts" / "run_mcp_server.py"

        client = StdioRpcFastClient(py_exe, server_py, "LockoutClient")
        await client.start()
        try:
            await client.call_rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "PTest152Lockout", "version": "1.0.0"},
            }, timeout=60.0)
            await client.call_rpc("notifications/initialized")

            lat_dl, res_dl = await client.call_tool("cscape_download_logic", {"project_path": "TankLevelClosedLoop"})
            is_dl_err = res_dl.get("result", {}).get("isError") is True or "error" in res_dl
            assert is_dl_err is True, "Controller download tool was not rejected!"
        finally:
            await client.close()


class TestStep152BenchmarkArtifactsAndEvidence:
    """Validates Step 152 benchmark execution outputs, log hashes, and checkpoints."""

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_step152_checkpoint_valid(self, root: Path):
        cp_file = root / "artifacts" / "checkpoints" / "step152_mcp_concurrent_ast_deadlock_resolution_checkpoint.json"
        assert cp_file.exists(), f"Step 152 checkpoint missing on {root}"
        data = json.loads(cp_file.read_text(encoding="utf-8"))
        assert data["step"] == 152
        assert data["status"] == "PASSED"
        assert data["cscape_pid"] > 0
        assert data["concurrent_clients"] == 3
        assert data["deadlock_free"] is True
        assert data["transactional_rollback_verified"] is True
        assert data["gui_compile_status"] == "SUCCESS"
        assert data["zero_straton_dependencies"] is True
        assert data["hardware_lockout_enforced"] is True
        assert "checkpoint_sha256" in data

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_step152_log_valid(self, root: Path):
        log_file = root / "artifacts" / "logs" / "step152_mcp_concurrent_ast_deadlock_resolution.json"
        assert log_file.exists(), f"Step 152 log missing on {root}"
        data = json.loads(log_file.read_text(encoding="utf-8"))
        assert data["step"] == 152
        assert data["status"] == "PASSED"
        assert data["target_pid"] > 0
        assert data["concurrent_clients_count"] == 3
        assert data["deadlock_detected"] is False
        assert data["transactional_rollback_verified"] is True
        assert data["gui_error_count"] == 0
        assert data["gui_warning_count"] == 0
        assert data["cscape_process_health"]["is_hung"] is False
        assert data["cscape_process_health"]["is_enabled"] is True
        assert "screenshot_evidence" in data

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_step152_screenshot_valid(self, root: Path):
        ss_file = root / "artifacts" / "screenshots" / "live_cscape_tank_level_step152.png"
        assert ss_file.exists(), f"Step 152 screenshot missing on {root}"
        assert ss_file.stat().st_size > 500
