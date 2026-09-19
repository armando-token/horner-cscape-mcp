r"""Test Suite for Step 149: Live FastMCP Variable Schema Evolution, Range Bound Invariant & Multi-Format Tag Mutation Audit.

MANDATES:
- Target Cscape (TankLevelClosedLoop.csp) MUST REMAIN RUNNING under keepalive supervisor.
- Import path safety: sys.path.insert(0, r"C:\HornerAI\horner-cscape-mcp") and sys.path.insert(0, r"C:\Users\ArmandoSilva").
- Live JSON-RPC 2.0 stdio subprocess client against scripts/run_mcp_server.py.
- Validates multi-POU variable inspection via cscape_inspect_variables.
- Validates bidirectional CSV to XML variable schema conversion and dynamic tag augmentation.
- Validates fail-closed register collision detection on word-span overlap.
- Validates hardware download lockout (32827).
- Validates Step 149 checkpoints, logs, and screenshots across dual roots.
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

from scripts.execute_step149_mcp_variable_schema_evolution import (
    StdioRpcFastClient,
    PROJECT_DIR,
    CSP_PATH,
    BASELINE_VARS_PATH,
    EVOLVED_XML_PATH,
    sweep_cscape_dialogs,
)


class TestStep149LiveGateAndProcess:
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


class TestStep149VariableSchemaEvolution:
    """Verifies FastMCP variable inspection, XML schema evolution, and collision invariants."""

    @pytest.mark.asyncio
    async def test_variable_inspection_across_pous(self):
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
                "clientInfo": {"name": "PTest149Inspect", "version": "1.0.0"},
            }, timeout=60.0)
            await client.call_rpc("notifications/initialized")

            lat_insp, res_insp = await client.call_tool("cscape_inspect_variables", {
                "project_name": "TankLevelClosedLoop"
            })
            data_insp = json.loads(res_insp["result"]["content"][0]["text"])
            assert data_insp["status"] == "success"
            assert len(data_insp["pous"]) >= 4
            assert data_insp["total_variables"] > 0
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_xml_schema_evolution_and_augmentation(self):
        py_exe = HORNER_ROOT / ".venv" / "Scripts" / "python.exe"
        if not py_exe.exists():
            py_exe = Path(sys.executable)
        server_py = HORNER_ROOT / "scripts" / "run_mcp_server.py"

        client = StdioRpcFastClient(py_exe, server_py)
        await client.start()
        test_xml_path = PROJECT_DIR / "test_evolved_vars.xml"
        try:
            await client.call_rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "PTest149XML", "version": "1.0.0"},
            }, timeout=60.0)
            await client.call_rpc("notifications/initialized")

            # 1. Read baseline
            lat_v, res_v = await client.call_tool("cscape_read_variables", {
                "file_path": str(BASELINE_VARS_PATH)
            })
            data_v = json.loads(res_v["result"]["content"][0]["text"])
            base_count = data_v["count"]
            vars_list = list(data_v["variables"])

            # 2. Add telemetry tags
            vars_list.append({
                "name": "VibrationIndexTest",
                "data_type": "REAL",
                "tag": "%R260",
                "address": "%R260",
                "scope": "GLOBAL",
            })
            vars_list.append({
                "name": "BearingTempTest",
                "data_type": "REAL",
                "tag": "%R262",
                "address": "%R262",
                "scope": "GLOBAL",
            })

            # 3. Write XML
            lat_w, res_w = await client.call_tool("cscape_write_variables", {
                "output_path": str(test_xml_path),
                "variables": vars_list,
                "format_type": "XML",
            })
            data_w = json.loads(res_w["result"]["content"][0]["text"])
            assert data_w["success"] is True

            # 4. Read XML back
            lat_r, res_r = await client.call_tool("cscape_read_variables", {
                "file_path": str(test_xml_path)
            })
            data_r = json.loads(res_r["result"]["content"][0]["text"])
            assert data_r["success"] is True
            assert data_r["count"] == base_count + 2
            assert data_r["conflicts_detected"] == 0
            assert data_r["validation_status"] == "VALID"
        finally:
            if test_xml_path.exists():
                test_xml_path.unlink()
            await client.close()

    @pytest.mark.asyncio
    async def test_register_collision_invariant_rejection(self):
        py_exe = HORNER_ROOT / ".venv" / "Scripts" / "python.exe"
        if not py_exe.exists():
            py_exe = Path(sys.executable)
        server_py = HORNER_ROOT / "scripts" / "run_mcp_server.py"

        client = StdioRpcFastClient(py_exe, server_py)
        await client.start()
        test_col_path = PROJECT_DIR / "test_collision_vars.csv"
        try:
            await client.call_rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "PTest149Collision", "version": "1.0.0"},
            }, timeout=60.0)
            await client.call_rpc("notifications/initialized")

            colliding_vars = [
                {"name": "RealVarA", "data_type": "REAL", "tag": "%R300", "address": "%R300", "scope": "GLOBAL"},
                {"name": "RealVarB", "data_type": "REAL", "tag": "%R301", "address": "%R301", "scope": "GLOBAL"}, # Overlaps %R300-%R301
            ]

            lat_w, res_w = await client.call_tool("cscape_write_variables", {
                "output_path": str(test_col_path),
                "variables": colliding_vars,
                "format_type": "CSV",
            })
            data_w = json.loads(res_w["result"]["content"][0]["text"])
            assert data_w.get("conflicts_detected") >= 1
            assert data_w.get("validation_status") == "INVALID"
        finally:
            if test_col_path.exists():
                test_col_path.unlink()
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
                "clientInfo": {"name": "PTest149Lockout", "version": "1.0.0"},
            }, timeout=60.0)
            await client.call_rpc("notifications/initialized")

            lat_dl, res_dl = await client.call_tool("cscape_download_logic", {"project_path": "TankLevelClosedLoop"})
            is_dl_err = res_dl.get("result", {}).get("isError") is True or "error" in res_dl
            assert is_dl_err is True, "Controller download tool was not rejected!"
        finally:
            await client.close()


class TestStep149BenchmarkArtifactsAndEvidence:
    """Validates Step 149 benchmark execution outputs, log hashes, and checkpoints."""

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_step149_checkpoint_valid(self, root: Path):
        cp_file = root / "artifacts" / "checkpoints" / "step149_mcp_variable_schema_evolution_checkpoint.json"
        assert cp_file.exists(), f"Step 149 checkpoint missing on {root}"
        data = json.loads(cp_file.read_text(encoding="utf-8"))
        assert data["step"] == 149
        assert data["status"] == "PASSED"
        assert data["cscape_pid"] > 0
        assert data["augmented_tags"] > data["baseline_tags"]
        assert data["xml_roundtrip"] == "SUCCESS"
        assert data["collision_rejection"] == "SUCCESS"
        assert data["gui_compile_status"] == "SUCCESS"
        assert data["zero_straton_dependencies"] is True
        assert data["hardware_lockout_enforced"] is True
        assert "checkpoint_sha256" in data

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_step149_log_valid(self, root: Path):
        log_file = root / "artifacts" / "logs" / "step149_mcp_variable_schema_evolution.json"
        assert log_file.exists(), f"Step 149 log missing on {root}"
        data = json.loads(log_file.read_text(encoding="utf-8"))
        assert data["step"] == 149
        assert data["status"] == "PASSED"
        assert data["target_pid"] > 0
        assert data["xml_conversion_verified"] is True
        assert data["collision_rejection_verified"] is True
        assert data["self_healing_cleanup_verified"] is True
        assert data["gui_error_count"] == 0
        assert data["gui_warning_count"] == 0
        assert data["cscape_process_health"]["is_hung"] is False
        assert data["cscape_process_health"]["is_enabled"] is True
        assert "screenshot_evidence" in data

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_step149_screenshot_valid(self, root: Path):
        ss_file = root / "artifacts" / "screenshots" / "live_cscape_tank_level_step149.png"
        assert ss_file.exists(), f"Step 149 screenshot missing on {root}"
        assert ss_file.stat().st_size > 500
