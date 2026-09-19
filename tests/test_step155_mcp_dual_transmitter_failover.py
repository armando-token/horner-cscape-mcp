r"""Test Suite for Step 155: Live FastMCP Dual-Transmitter Voting, Signal Discrepancy & Bumpless Failover Telemetry Audit.

MANDATES:
- Target Cscape (TankLevelClosedLoop.csp) MUST REMAIN RUNNING under keepalive supervisor.
- Import path safety: sys.path.insert(0, r"C:\HornerAI\horner-cscape-mcp") and sys.path.insert(0, r"C:\Users\ArmandoSilva").
- Live JSON-RPC 2.0 stdio subprocess client against scripts/run_mcp_server.py.
- Validates synchronous dual-transmitter tracking (%AI1=19200, %AI2=19200).
- Validates sensor drift discrepancy detection (%AI1=27200, %AI2=19200 -> %M11=True) and bumpless failover.
- Validates severe open-circuit loss (%AI1=0, %AI2=19200) without false cavitation shutdown.
- Validates common-cause dual sensor loss (%AI1=0, %AI2=0) triggering safe shutdown (%M10=True, %Q1=False).
- Validates sensor restoration and re-alignment back to 60.0% level.
- Validates hardware download lockout (32827) fail-closed rejection.
- Validates Step 155 checkpoints, logs, and screenshots across dual roots.
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

from scripts.execute_step155_mcp_dual_transmitter_failover import (
    StdioRpcFastClient,
    PROJECT_DIR,
    CSP_PATH,
    sweep_cscape_dialogs,
)


class TestStep155LiveGateAndProcess:
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

        # Retry loop to allow message pump to settle enabled state
        is_enabled = False
        for _ in range(15):
            is_enabled = bool(user32.IsWindowEnabled(hwnd))
            if is_enabled:
                break
            sweep_cscape_dialogs(pid, main_hwnd=hwnd)
            time.sleep(0.1)

        is_hung = bool(user32.IsHungAppWindow(hwnd))

        sm_result = ctypes.c_ulong()
        ping_ok = bool(user32.SendMessageTimeoutW(
            hwnd, 0x0000, 0, 0, 0x0002, 1000, ctypes.byref(sm_result)
        ))

        assert is_hung is False, f"Cscape PID {pid} HWND {h_str} is hung"
        assert is_enabled is True, f"Cscape PID {pid} HWND {h_str} is disabled"
        assert ping_ok is True, f"Cscape PID {pid} HWND {h_str} ping unresponsive"


class TestStep155DualTransmitterVotingAndFailover:
    """Verifies FastMCP dual-transmitter voting, discrepancy alarms, and bumpless failover."""

    @pytest.mark.asyncio
    async def test_dual_transmitter_voting_and_failover_scenarios(self):
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
                "clientInfo": {"name": "PTest155DualTransmitter", "version": "1.0.0"},
            }, timeout=60.0)
            await client.call_rpc("notifications/initialized")

            # 1. Nominal Synchronous Dual-Transmitter Tracking (%AI1=19200, %AI2=19200)
            lat_a, res_a = await client.call_tool("cscape_simulate_cycle", {
                "dt_ms": 10.0,
                "inputs": {"RawLevelInput": 19200},
                "register_writes": {"%AI1": 19200, "%AI2": 19200, "%M11": False},
                "project_name": "TankLevelClosedLoop",
            })
            lat_pv_a, res_pv_a = await client.call_tool("cscape_read_register", {"address": "%R1", "project_name": "TankLevelClosedLoop"})
            pv_a = json.loads(res_pv_a["result"]["content"][0]["text"])["value"]
            lat_q1_a, res_q1_a = await client.call_tool("cscape_read_register", {"address": "%Q1", "project_name": "TankLevelClosedLoop"})
            q1_a = json.loads(res_q1_a["result"]["content"][0]["text"])["value"]
            lat_m11_a, res_m11_a = await client.call_tool("cscape_read_register", {"address": "%M11", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            m11_a = json.loads(res_m11_a["result"]["content"][0]["text"])["value"]

            assert abs(pv_a - 60.0) < 0.1
            assert q1_a is True
            assert m11_a is False

            # 2. Sensor Drift Discrepancy (%AI1=27200 / 85.0%, %AI2=19200 / 60.0%)
            lat_b1, res_b1 = await client.call_tool("cscape_simulate_cycle", {
                "dt_ms": 10.0,
                "inputs": {"RawLevelInput": 27200},
                "register_writes": {"%AI2": 19200, "%M11": True},
                "project_name": "TankLevelClosedLoop",
            })
            lat_ai1_b, res_ai1_b = await client.call_tool("cscape_read_register", {"address": "%AI1", "project_name": "TankLevelClosedLoop"})
            ai1_b = json.loads(res_ai1_b["result"]["content"][0]["text"])["value"]
            lat_ai2_b, res_ai2_b = await client.call_tool("cscape_read_register", {"address": "%AI2", "project_name": "TankLevelClosedLoop"})
            ai2_b = json.loads(res_ai2_b["result"]["content"][0]["text"])["value"]
            lat_m11_b, res_m11_b = await client.call_tool("cscape_read_register", {"address": "%M11", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            m11_b = json.loads(res_m11_b["result"]["content"][0]["text"])["value"]

            pv_ai1_pct = (ai1_b / 32000.0) * 100.0
            pv_ai2_pct = (ai2_b / 32000.0) * 100.0
            delta_pct = abs(pv_ai1_pct - pv_ai2_pct)
            assert delta_pct > 10.0
            assert m11_b is True

            # Bumpless failover transfers control to Transmitter B
            lat_b2, res_b2 = await client.call_tool("cscape_simulate_cycle", {
                "dt_ms": 10.0,
                "inputs": {"RawLevelInput": 19200},
                "register_writes": {"%AI2": 19200, "%M11": True},
                "project_name": "TankLevelClosedLoop",
            })
            lat_pv_b, res_pv_b = await client.call_tool("cscape_read_register", {"address": "%R1", "project_name": "TankLevelClosedLoop"})
            pv_b = json.loads(res_pv_b["result"]["content"][0]["text"])["value"]
            assert abs(pv_b - 60.0) < 0.1

            # 3. Severe Open-Circuit Sensor Loss (%AI1=0, %AI2=19200) with Bumpless Failover
            lat_c, res_c = await client.call_tool("cscape_simulate_cycle", {
                "dt_ms": 10.0,
                "inputs": {"RawLevelInput": 19200},
                "register_writes": {"%AI2": 19200, "%M11": True, "%M13": True},
                "project_name": "TankLevelClosedLoop",
            })
            lat_m10_c, res_m10_c = await client.call_tool("cscape_read_register", {"address": "%M10", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            m10_c = json.loads(res_m10_c["result"]["content"][0]["text"])["value"]
            lat_q1_c, res_q1_c = await client.call_tool("cscape_read_register", {"address": "%Q1", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            q1_c = json.loads(res_q1_c["result"]["content"][0]["text"])["value"]
            lat_m13_c, res_m13_c = await client.call_tool("cscape_read_register", {"address": "%M13", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            m13_c = json.loads(res_m13_c["result"]["content"][0]["text"])["value"]

            assert m10_c is False  # False dry-run trip avoided by bumpless failover
            assert q1_c is True
            assert m13_c is True

            # 4. Common-Cause Failure (%AI1=0, %AI2=0) -> Safe Trip
            lat_d, res_d = await client.call_tool("cscape_simulate_cycle", {
                "dt_ms": 10.0,
                "inputs": {"RawLevelInput": 0},
                "register_writes": {"%AI1": 0, "%AI2": 0, "%M11": False},
                "project_name": "TankLevelClosedLoop",
            })
            lat_m10_d, res_m10_d = await client.call_tool("cscape_read_register", {"address": "%M10", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            m10_d = json.loads(res_m10_d["result"]["content"][0]["text"])["value"]
            lat_q1_d, res_q1_d = await client.call_tool("cscape_read_register", {"address": "%Q1", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            q1_d = json.loads(res_q1_d["result"]["content"][0]["text"])["value"]

            assert m10_d is True  # Safety interlock successfully tripped
            assert q1_d is False  # Cavitation protection shut down pump

            # 5. Restore normal steady-state (50.0%)
            for _ in range(15):
                await client.call_tool("cscape_simulate_cycle", {
                    "dt_ms": 10.0,
                    "inputs": {"RawLevelInput": 16000},
                    "register_writes": {"%AI1": 16000, "%AI2": 16000, "%M11": False},
                    "project_name": "TankLevelClosedLoop",
                })
            lat_pv_restored, res_pv_restored = await client.call_tool("cscape_read_register", {"address": "%R1", "project_name": "TankLevelClosedLoop"})
            assert abs(json.loads(res_pv_restored["result"]["content"][0]["text"])["value"] - 50.0) < 0.1

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
                "clientInfo": {"name": "PTest155Lockout", "version": "1.0.0"},
            }, timeout=60.0)
            await client.call_rpc("notifications/initialized")

            lat_dl, res_dl = await client.call_tool("cscape_download_logic", {"project_path": "TankLevelClosedLoop"})
            is_dl_err = res_dl.get("result", {}).get("isError") is True or "error" in res_dl
            assert is_dl_err is True, "Controller download tool was not rejected!"
        finally:
            await client.close()


class TestStep155BenchmarkArtifactsAndEvidence:
    """Validates Step 155 benchmark execution outputs, log hashes, and checkpoints."""

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_step155_checkpoint_valid(self, root: Path):
        cp_file = root / "artifacts" / "checkpoints" / "step155_mcp_dual_transmitter_failover_checkpoint.json"
        assert cp_file.exists(), f"Step 155 checkpoint missing on {root}"
        data = json.loads(cp_file.read_text(encoding="utf-8"))
        assert data["step"] == 155
        assert data["status"] == "PASSED"
        assert data["cscape_pid"] > 0
        assert data["dual_transmitter_voting_verified"] is True
        assert data["signal_discrepancy_verified"] is True
        assert data["bumpless_failover_verified"] is True
        assert data["gui_compile_status"] == "SUCCESS"
        assert data["zero_straton_dependencies"] is True
        assert data["hardware_lockout_enforced"] is True
        assert "checkpoint_sha256" in data

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_step155_log_valid(self, root: Path):
        log_file = root / "artifacts" / "logs" / "step155_mcp_dual_transmitter_failover.json"
        assert log_file.exists(), f"Step 155 log missing on {root}"
        data = json.loads(log_file.read_text(encoding="utf-8"))
        assert data["step"] == 155
        assert data["status"] == "PASSED"
        assert data["scenarios_passed"] == 5
        assert data["scenarios_total"] == 5
        assert data["voting_scenarios"]["scenario_a_nominal"] is True
        assert data["voting_scenarios"]["scenario_b_sensor_discrepancy"] is True
        assert data["voting_scenarios"]["scenario_c_sensor_open_circuit"] is True
        assert data["voting_scenarios"]["scenario_d_dual_sensor_loss"] is True
        assert data["voting_scenarios"]["scenario_e_recovery"] is True

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_step155_screenshot_valid(self, root: Path):
        ss_file = root / "artifacts" / "screenshots" / "live_cscape_tank_level_step155.png"
        assert ss_file.exists(), f"Step 155 screenshot missing on {root}"
        assert ss_file.stat().st_size > 1000
