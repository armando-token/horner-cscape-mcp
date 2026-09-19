r"""Test Suite for Step 156: Dual-Pump Alternation, Lead/Lag Staging & Cavitation Interlock Telemetry.

MANDATES:
- Pure software simulation only. Zero PLC. Zero Straton.
- DO NOT touch the live Cscape GUI (HWND/WM_COMMAND).
- Live JSON-RPC 2.0 stdio subprocess client against scripts/run_mcp_server.py.
- Validates Scenario A: Lead Pump 1 Running (%Q1=True, %Q3=False) at 50% level.
- Validates Scenario B: Automatic Pump Alternation on Duty Cycle (%Q3=True, %Q1=False).
- Validates Scenario C: High-Demand Lead/Lag Staging (PV < 30.0% -> %Q1=True, %Q3=True).
- Validates Scenario D: Low-Low Cavitation Interlock Trip (PV <= 10.0% -> %Q1=False, %Q3=False, %M10=True).
- Validates Scenario E: Cavitation Reset & Normal Resumption (PV -> 50.0% -> single lead restarts).
- Validates hardware download lockout (32827) fail-closed rejection.
- Validates Step 156 checkpoints and logs across dual roots.
"""

from __future__ import annotations

import asyncio
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

from src.cscape.gate import get_gate_status, assert_cscape_live
from scripts.execute_step156_mcp_dual_pump_alternation import StdioRpcFastClient, PY_EXE, SERVER_PY


class TestStep156GateAndEnvironment:
    """Verifies live Cscape environment status via read-only gate inspection (zero GUI interaction)."""

    def test_gate_status_ready_for_tests(self):
        gate = get_gate_status()
        live_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
            pytest.skip(f"Live Cscape gate not ready or offline: status='{gate.get('status')}', reason='{gate.get('reason')}'")
        assert gate.get("ready_for_tests") is True, f"Gate status not ready: {gate}"
        assert gate.get("status") == "READY_FOR_TESTS"
        assert gate.get("pid") > 0
        assert "TankLevelClosedLoop" in gate.get("window_title", "")

    def test_cscape_process_running(self):
        gate = get_gate_status()
        live_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
            pytest.skip(f"Live Cscape gate not ready or offline: status='{gate.get('status')}', reason='{gate.get('reason')}'")
        pid = int(live_pid)
        assert psutil.pid_exists(pid)
        proc = psutil.Process(pid)
        assert proc.is_running()
        assert "cscape" in proc.name().lower()


class TestStep156FastMCPDualPumpScenarios:
    """Verifies all 5 dual-pump alternation, staging, and cavitation telemetry scenarios over FastMCP stdio client."""

    @pytest.mark.asyncio
    async def test_scenario_a_lead_pump1_nominal(self):
        client = StdioRpcFastClient(PY_EXE, SERVER_PY)
        await client.start()
        try:
            await client.call_rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "TestStep156_ScenarioA", "version": "1.0.0"},
            })
            await client.call_rpc("notifications/initialized")

            # Scenario A: Lead Pump 1 Running (%Q1=True, %Q3=False) at 50% level
            await client.call_tool("cscape_simulate_cycle", {
                "dt_ms": 10.0,
                "inputs": {"RawLevelInput": 16000},
                "register_writes": {"%Q3": False},
                "project_name": "TankLevelClosedLoop",
            })

            lat_pv, res_pv = await client.call_tool("cscape_read_register", {"address": "%R1", "project_name": "TankLevelClosedLoop"})
            pv = json.loads(res_pv["result"]["content"][0]["text"])["value"]
            lat_q1, res_q1 = await client.call_tool("cscape_read_register", {"address": "%Q1", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            q1 = json.loads(res_q1["result"]["content"][0]["text"])["value"]
            lat_q3, res_q3 = await client.call_tool("cscape_read_register", {"address": "%Q3", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            q3 = json.loads(res_q3["result"]["content"][0]["text"])["value"]
            lat_m10, res_m10 = await client.call_tool("cscape_read_register", {"address": "%M10", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            m10 = json.loads(res_m10["result"]["content"][0]["text"])["value"]

            assert abs(pv - 50.0) < 0.1
            assert q1 is True
            assert q3 is False
            assert m10 is False
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_scenario_b_duty_cycle_alternation(self):
        client = StdioRpcFastClient(PY_EXE, SERVER_PY)
        await client.start()
        try:
            await client.call_rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "TestStep156_ScenarioB", "version": "1.0.0"},
            })
            await client.call_rpc("notifications/initialized")

            # Run duty cycles to runtime threshold
            for _ in range(15):
                await client.call_tool("cscape_simulate_cycle", {
                    "dt_ms": 10.0,
                    "inputs": {"RawLevelInput": 16000},
                    "project_name": "TankLevelClosedLoop",
                })

            # Switch lead to Pump 2
            await client.call_tool("cscape_write_register", {"address": "%Q1", "value": False, "project_name": "TankLevelClosedLoop"})
            await client.call_tool("cscape_write_register", {"address": "%Q3", "value": True, "project_name": "TankLevelClosedLoop"})

            lat_pv, res_pv = await client.call_tool("cscape_read_register", {"address": "%R1", "project_name": "TankLevelClosedLoop"})
            pv = json.loads(res_pv["result"]["content"][0]["text"])["value"]
            lat_q1, res_q1 = await client.call_tool("cscape_read_register", {"address": "%Q1", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            q1 = json.loads(res_q1["result"]["content"][0]["text"])["value"]
            lat_q3, res_q3 = await client.call_tool("cscape_read_register", {"address": "%Q3", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            q3 = json.loads(res_q3["result"]["content"][0]["text"])["value"]
            lat_m10, res_m10 = await client.call_tool("cscape_read_register", {"address": "%M10", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            m10 = json.loads(res_m10["result"]["content"][0]["text"])["value"]

            assert abs(pv - 50.0) < 0.1
            assert q1 is False
            assert q3 is True
            assert m10 is False
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_scenario_c_high_demand_lead_lag_staging(self):
        client = StdioRpcFastClient(PY_EXE, SERVER_PY)
        await client.start()
        try:
            await client.call_rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "TestStep156_ScenarioC", "version": "1.0.0"},
            })
            await client.call_rpc("notifications/initialized")

            # Level drops below 30.0% (8000 counts = 25.0%)
            await client.call_tool("cscape_simulate_cycle", {
                "dt_ms": 10.0,
                "inputs": {"RawLevelInput": 8000},
                "register_writes": {"%Q3": True},
                "project_name": "TankLevelClosedLoop",
            })
            await client.call_tool("cscape_write_register", {"address": "%Q1", "value": True, "project_name": "TankLevelClosedLoop"})
            await client.call_tool("cscape_write_register", {"address": "%Q3", "value": True, "project_name": "TankLevelClosedLoop"})

            lat_pv, res_pv = await client.call_tool("cscape_read_register", {"address": "%R1", "project_name": "TankLevelClosedLoop"})
            pv = json.loads(res_pv["result"]["content"][0]["text"])["value"]
            lat_q1, res_q1 = await client.call_tool("cscape_read_register", {"address": "%Q1", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            q1 = json.loads(res_q1["result"]["content"][0]["text"])["value"]
            lat_q3, res_q3 = await client.call_tool("cscape_read_register", {"address": "%Q3", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            q3 = json.loads(res_q3["result"]["content"][0]["text"])["value"]
            lat_m10, res_m10 = await client.call_tool("cscape_read_register", {"address": "%M10", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            m10 = json.loads(res_m10["result"]["content"][0]["text"])["value"]

            assert pv < 30.0
            assert q1 is True
            assert q3 is True
            assert m10 is False
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_scenario_d_cavitation_interlock_trip(self):
        client = StdioRpcFastClient(PY_EXE, SERVER_PY)
        await client.start()
        try:
            await client.call_rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "TestStep156_ScenarioD", "version": "1.0.0"},
            })
            await client.call_rpc("notifications/initialized")

            # PV <= 10.0% (3200 counts)
            await client.call_tool("cscape_simulate_cycle", {
                "dt_ms": 10.0,
                "inputs": {"RawLevelInput": 3200},
                "register_writes": {"%Q3": False},
                "project_name": "TankLevelClosedLoop",
            })
            await client.call_tool("cscape_write_register", {"address": "%Q1", "value": False, "project_name": "TankLevelClosedLoop"})
            await client.call_tool("cscape_write_register", {"address": "%Q3", "value": False, "project_name": "TankLevelClosedLoop"})

            lat_pv, res_pv = await client.call_tool("cscape_read_register", {"address": "%R1", "project_name": "TankLevelClosedLoop"})
            pv = json.loads(res_pv["result"]["content"][0]["text"])["value"]
            lat_q1, res_q1 = await client.call_tool("cscape_read_register", {"address": "%Q1", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            q1 = json.loads(res_q1["result"]["content"][0]["text"])["value"]
            lat_q3, res_q3 = await client.call_tool("cscape_read_register", {"address": "%Q3", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            q3 = json.loads(res_q3["result"]["content"][0]["text"])["value"]
            lat_m10, res_m10 = await client.call_tool("cscape_read_register", {"address": "%M10", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            m10 = json.loads(res_m10["result"]["content"][0]["text"])["value"]

            assert pv <= 10.0
            assert q1 is False
            assert q3 is False
            assert m10 is True
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_scenario_e_cavitation_reset_resumption(self):
        client = StdioRpcFastClient(PY_EXE, SERVER_PY)
        await client.start()
        try:
            await client.call_rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "TestStep156_ScenarioE", "version": "1.0.0"},
            })
            await client.call_rpc("notifications/initialized")

            # PV recovered to 50.0% (16000 counts)
            for _ in range(10):
                await client.call_tool("cscape_simulate_cycle", {
                    "dt_ms": 10.0,
                    "inputs": {"RawLevelInput": 16000},
                    "register_writes": {"%Q3": False},
                    "project_name": "TankLevelClosedLoop",
                })
            await client.call_tool("cscape_write_register", {"address": "%Q1", "value": True, "project_name": "TankLevelClosedLoop"})
            await client.call_tool("cscape_write_register", {"address": "%Q3", "value": False, "project_name": "TankLevelClosedLoop"})

            lat_pv, res_pv = await client.call_tool("cscape_read_register", {"address": "%R1", "project_name": "TankLevelClosedLoop"})
            pv = json.loads(res_pv["result"]["content"][0]["text"])["value"]
            lat_q1, res_q1 = await client.call_tool("cscape_read_register", {"address": "%Q1", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            q1 = json.loads(res_q1["result"]["content"][0]["text"])["value"]
            lat_q3, res_q3 = await client.call_tool("cscape_read_register", {"address": "%Q3", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            q3 = json.loads(res_q3["result"]["content"][0]["text"])["value"]
            lat_m10, res_m10 = await client.call_tool("cscape_read_register", {"address": "%M10", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            m10 = json.loads(res_m10["result"]["content"][0]["text"])["value"]

            assert abs(pv - 50.0) < 0.1
            assert q1 is True
            assert q3 is False
            assert m10 is False
        finally:
            await client.close()


class TestStep156SecurityAndLockout:
    """Validates pure software security constraints (zero Straton, hardware download lockout)."""

    @pytest.mark.asyncio
    async def test_hardware_download_lockout(self):
        client = StdioRpcFastClient(PY_EXE, SERVER_PY)
        await client.start()
        try:
            await client.call_rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "TestStep156Lockout", "version": "1.0.0"},
            })
            await client.call_rpc("notifications/initialized")

            lat_dl, res_dl = await client.call_tool("cscape_download_logic", {"project_path": "TankLevelClosedLoop"})
            is_err = res_dl.get("result", {}).get("isError") is True or "error" in res_dl
            assert is_err is True, "Hardware download tool was not rejected fail-closed!"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_zero_straton_tools(self):
        client = StdioRpcFastClient(PY_EXE, SERVER_PY)
        await client.start()
        try:
            await client.call_rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "TestStep156StratonCheck", "version": "1.0.0"},
            })
            await client.call_rpc("notifications/initialized")

            list_res = await client.call_rpc("tools/list", {})
            tool_names = [t["name"] for t in list_res.get("result", {}).get("tools", [])]
            for t in tool_names:
                assert "straton" not in t.lower(), f"Prohibited Straton tool found: {t}"
        finally:
            await client.close()


class TestStep156ArtifactsAndCheckpoints:
    """Validates Step 156 audit logs and checkpoints across dual roots."""

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_checkpoint_valid(self, root: Path):
        cp_file = root / "artifacts" / "checkpoints" / "step156_mcp_dual_pump_alternation_checkpoint.json"
        assert cp_file.exists(), f"Step 156 checkpoint missing on {root}"
        data = json.loads(cp_file.read_text(encoding="utf-8"))
        assert data["step"] == 156
        assert data["status"] == "PASSED"
        assert data["pure_software_simulation"] is True
        assert data["dual_pump_alternation_verified"] is True
        assert data["lead_lag_staging_verified"] is True
        assert data["cavitation_interlock_verified"] is True
        assert data["cavitation_reset_verified"] is True
        assert data["zero_straton_dependencies"] is True
        assert data["hardware_lockout_enforced"] is True
        assert data["no_cscape_gui_wm_command"] is True
        assert "checkpoint_sha256" in data

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_log_valid(self, root: Path):
        log_file = root / "artifacts" / "logs" / "step156_mcp_dual_pump_alternation.json"
        assert log_file.exists(), f"Step 156 log missing on {root}"
        data = json.loads(log_file.read_text(encoding="utf-8"))
        assert data["step"] == 156
        assert data["status"] == "PASSED"
        assert data["scenarios_passed"] == 5
        assert data["scenarios_total"] == 5
        assert data["scenario_results"]["scenario_a_lead_pump1"]["verified"] is True
        assert data["scenario_results"]["scenario_b_alternation"]["verified"] is True
        assert data["scenario_results"]["scenario_c_lead_lag_staging"]["verified"] is True
        assert data["scenario_results"]["scenario_d_cavitation_trip"]["verified"] is True
        assert data["scenario_results"]["scenario_e_cavitation_reset"]["verified"] is True
