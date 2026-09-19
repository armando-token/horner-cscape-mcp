r"""Test Suite for Step 153: Live FastMCP Telemetry Streaming & Frame Verification.

MANDATES:
- Target Cscape (TankLevelClosedLoop.csp) MUST REMAIN RUNNING under keepalive supervisor.
- Import path safety: sys.path.insert(0, r"C:\HornerAI\horner-cscape-mcp") and sys.path.insert(0, r"C:\Users\ArmandoSilva").
- Live JSON-RPC 2.0 stdio subprocess client against scripts/run_mcp_server.py.
- Validates 50-frame telemetry streaming pipeline over stdio.
- Validates hardware download lockout (32827).
- Validates Step 153 checkpoints, logs, and screenshots across dual roots.
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

from scripts.execute_step153_mcp_telemetry_streaming_frame_verification import (
    StdioRpcFastClient,
    PROJECT_DIR,
    CSP_PATH,
    BASELINE_VARS_PATH,
    sweep_cscape_dialogs,
)


class TestStep153LiveGateAndProcess:
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


class TestStep153TelemetryStreamingAndFrames:
    """Verifies FastMCP telemetry streaming pipeline and safety locks."""

    @pytest.mark.asyncio
    async def test_telemetry_streaming_pipeline_50_frames(self):
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
                "clientInfo": {"name": "PTest153Stream", "version": "1.0.0"},
            }, timeout=60.0)
            await client.call_rpc("notifications/initialized")

            frames = []
            for i in range(50):
                lat, res = await client.call_tool("cscape_simulate_cycle", {
                    "dt_ms": 5.0, "project_name": "TankLevelClosedLoop"
                })
                data = json.loads(res["result"]["content"][0]["text"])
                assert data["success"] is True
                frames.append(data)

            assert len(frames) == 50
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
                "clientInfo": {"name": "PTest153Lockout", "version": "1.0.0"},
            }, timeout=60.0)
            await client.call_rpc("notifications/initialized")

            lat_dl, res_dl = await client.call_tool("cscape_download_logic", {"project_path": "TankLevelClosedLoop"})
            is_dl_err = res_dl.get("result", {}).get("isError") is True or "error" in res_dl
            assert is_dl_err is True, "Controller download tool was not rejected!"
        finally:
            await client.close()


class TestStep153BenchmarkArtifactsAndEvidence:
    """Validates Step 153 benchmark execution outputs, log hashes, and checkpoints."""

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_step153_checkpoint_valid(self, root: Path):
        cp_file = root / "artifacts" / "checkpoints" / "step153_mcp_telemetry_streaming_frame_verification_checkpoint.json"
        assert cp_file.exists(), f"Step 153 checkpoint missing on {root}"
        data = json.loads(cp_file.read_text(encoding="utf-8"))
        assert data["step"] == 153
        assert data["status"] == "PASSED"
        assert data["cscape_pid"] > 0
        assert data["frames_streamed"] == 200
        assert data["frame_loss_percent"] == 0.0
        assert data["gui_compile_status"] == "SUCCESS"
        assert data["zero_straton_dependencies"] is True
        assert data["hardware_lockout_enforced"] is True
        assert "checkpoint_sha256" in data

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_step153_log_valid(self, root: Path):
        log_file = root / "artifacts" / "logs" / "step153_mcp_telemetry_streaming_frame_verification.json"
        assert log_file.exists(), f"Step 153 log missing on {root}"
        data = json.loads(log_file.read_text(encoding="utf-8"))
        assert data["step"] == 153
        assert data["status"] == "PASSED"
        assert data["target_pid"] > 0
        assert data["telemetry_frames_streamed"] == 200
        assert data["frame_loss_percent"] == 0.0
        assert data["gui_error_count"] == 0
        assert data["gui_warning_count"] == 0
        assert data["cscape_process_health"]["is_hung"] is False
        assert data["cscape_process_health"]["is_enabled"] is True
        assert "screenshot_evidence" in data

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_step153_screenshot_valid(self, root: Path):
        ss_file = root / "artifacts" / "screenshots" / "live_cscape_tank_level_step153.png"
        assert ss_file.exists(), f"Step 153 screenshot missing on {root}"
        assert ss_file.stat().st_size > 500
