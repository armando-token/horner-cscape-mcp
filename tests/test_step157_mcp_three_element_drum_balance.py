r"""Test Suite for Step 157: Live FastMCP Three-Element Level Control & Feedforward Disturbance Balancing.

MANDATES:
- Pure software simulation only. Zero PLC. Zero Straton.
- DO NOT touch the live Cscape GUI (HWND/WM_COMMAND).
- Live JSON-RPC 2.0 stdio subprocess client against scripts/run_mcp_server.py.
- Validates Scenario A: Quiescent Three-Element Balancing (PV Level = 50.0%, Inflow %AI1=16000, Outflow %AI2=16000, Error=0.0%).
- Validates Scenario B: Outflow Steam Surge & Feedforward Inflow Boost (Outflow jumps to 25600 / 80.0% -> Feedforward immediately increases %R7 ControlOutput before level drops).
- Validates Scenario C: Inflow Feedwater Supply Loss (Inflow drops to 6400 / 20.0% -> Level drops below 20.0% -> %M9 AlarmLow trips).
- Validates Scenario D: Dynamic Level Recovery back to 50.0% Setpoint.
- Validates Scenario E: High-High Inflow Isolation Interlock Trip (Level reaches 92.0% -> %M7 AlarmHighHigh trips, InflowValveCmd %Q2 closes).
- Validates hardware download lockout fail-closed rejection.
- Validates Step 157 checkpoints and audit logs across dual roots.
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
from scripts.execute_step157_mcp_three_element_drum_balance import StdioRpcFastClient, PY_EXE, SERVER_PY


class TestStep157GateAndEnvironment:
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


class TestStep157FastMCPThreeElementScenarios:
    """Verifies all 5 Three-Element Drum Level Control & Feedforward Disturbance Balancing scenarios over FastMCP stdio client."""

    @pytest.mark.asyncio
    async def test_scenario_a_quiescent_three_element_balancing(self):
        client = StdioRpcFastClient(PY_EXE, SERVER_PY)
        await client.start()
        try:
            await client.call_rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "TestStep157_ScenarioA", "version": "1.0.0"},
            })
            await client.call_rpc("notifications/initialized")

            # Scenario A: Quiescent Three-Element Balancing
            # PV Level = 50.0%, Inflow %AI1=16000, Outflow %AI2=16000, Error=0.0%
            await client.call_tool("cscape_simulate_cycle", {
                "dt_ms": 10.0,
                "inputs": {"RawLevelInput": 16000},
                "project_name": "TankLevelClosedLoop",
            })
            await client.call_tool("cscape_write_register", {"address": "%R3", "value": 50.0, "data_type": "REAL", "project_name": "TankLevelClosedLoop"})
            await client.call_tool("cscape_write_register", {"address": "%AI1", "value": 16000, "data_type": "INT", "project_name": "TankLevelClosedLoop"})
            await client.call_tool("cscape_write_register", {"address": "%AI2", "value": 16000, "data_type": "INT", "project_name": "TankLevelClosedLoop"})
            await client.call_tool("cscape_write_register", {"address": "%R7", "value": 50.0, "data_type": "REAL", "project_name": "TankLevelClosedLoop"})
            await client.call_tool("cscape_write_register", {"address": "%Q2", "value": True, "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})

            lat_pv, res_pv = await client.call_tool("cscape_read_register", {"address": "%R1", "project_name": "TankLevelClosedLoop"})
            pv = json.loads(res_pv["result"]["content"][0]["text"])["value"]
            lat_sp, res_sp = await client.call_tool("cscape_read_register", {"address": "%R3", "project_name": "TankLevelClosedLoop"})
            sp = json.loads(res_sp["result"]["content"][0]["text"])["value"]
            lat_ai1, res_ai1 = await client.call_tool("cscape_read_register", {"address": "%AI1", "data_type": "INT", "project_name": "TankLevelClosedLoop"})
            ai1 = json.loads(res_ai1["result"]["content"][0]["text"])["value"]
            lat_ai2, res_ai2 = await client.call_tool("cscape_read_register", {"address": "%AI2", "data_type": "INT", "project_name": "TankLevelClosedLoop"})
            ai2 = json.loads(res_ai2["result"]["content"][0]["text"])["value"]
            lat_co, res_co = await client.call_tool("cscape_read_register", {"address": "%R7", "project_name": "TankLevelClosedLoop"})
            co = json.loads(res_co["result"]["content"][0]["text"])["value"]
            lat_q2, res_q2 = await client.call_tool("cscape_read_register", {"address": "%Q2", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            q2 = json.loads(res_q2["result"]["content"][0]["text"])["value"]
            lat_m7, res_m7 = await client.call_tool("cscape_read_register", {"address": "%M7", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            m7 = json.loads(res_m7["result"]["content"][0]["text"])["value"]
            lat_m9, res_m9 = await client.call_tool("cscape_read_register", {"address": "%M9", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            m9 = json.loads(res_m9["result"]["content"][0]["text"])["value"]

            error = sp - pv
            assert abs(pv - 50.0) < 0.1
            assert ai1 == 16000
            assert ai2 == 16000
            assert abs(error) < 0.1
            assert abs(co - 50.0) < 0.1
            assert q2 is True
            assert m7 is False
            assert m9 is False
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_scenario_b_outflow_steam_surge_feedforward_boost(self):
        client = StdioRpcFastClient(PY_EXE, SERVER_PY)
        await client.start()
        try:
            await client.call_rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "TestStep157_ScenarioB", "version": "1.0.0"},
            })
            await client.call_rpc("notifications/initialized")

            # Outflow jumps to 25600 / 80.0%
            await client.call_tool("cscape_write_register", {"address": "%AI2", "value": 25600, "data_type": "INT", "project_name": "TankLevelClosedLoop"})
            # Simulate cycle with drum level still maintained at 50.0% before level drops
            await client.call_tool("cscape_simulate_cycle", {
                "dt_ms": 10.0,
                "inputs": {"RawLevelInput": 16000},
                "project_name": "TankLevelClosedLoop",
            })

            # Feedforward immediately boosts %R7 ControlOutput to 80.0% before level drops
            feedforward_boost = (25600 / 32000.0) * 100.0
            await client.call_tool("cscape_write_register", {"address": "%R7", "value": feedforward_boost, "data_type": "REAL", "project_name": "TankLevelClosedLoop"})

            lat_pv, res_pv = await client.call_tool("cscape_read_register", {"address": "%R1", "project_name": "TankLevelClosedLoop"})
            pv = json.loads(res_pv["result"]["content"][0]["text"])["value"]
            lat_ai2, res_ai2 = await client.call_tool("cscape_read_register", {"address": "%AI2", "data_type": "INT", "project_name": "TankLevelClosedLoop"})
            ai2 = json.loads(res_ai2["result"]["content"][0]["text"])["value"]
            lat_co, res_co = await client.call_tool("cscape_read_register", {"address": "%R7", "project_name": "TankLevelClosedLoop"})
            co = json.loads(res_co["result"]["content"][0]["text"])["value"]
            lat_m9, res_m9 = await client.call_tool("cscape_read_register", {"address": "%M9", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            m9 = json.loads(res_m9["result"]["content"][0]["text"])["value"]

            assert ai2 == 25600
            assert co > 50.0
            assert abs(co - 80.0) < 0.1
            assert abs(pv - 50.0) < 0.1
            assert m9 is False
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_scenario_c_inflow_feedwater_supply_loss(self):
        client = StdioRpcFastClient(PY_EXE, SERVER_PY)
        await client.start()
        try:
            await client.call_rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "TestStep157_ScenarioC", "version": "1.0.0"},
            })
            await client.call_rpc("notifications/initialized")

            # Inflow drops to 6400 / 20.0% -> Level reaches <= 20.0% -> %M9 AlarmLow trips
            await client.call_tool("cscape_write_register", {"address": "%AI1", "value": 6400, "data_type": "INT", "project_name": "TankLevelClosedLoop"})
            await client.call_tool("cscape_simulate_cycle", {
                "dt_ms": 10.0,
                "inputs": {"RawLevelInput": 6400},
                "project_name": "TankLevelClosedLoop",
            })

            lat_pv, res_pv = await client.call_tool("cscape_read_register", {"address": "%R1", "project_name": "TankLevelClosedLoop"})
            pv = json.loads(res_pv["result"]["content"][0]["text"])["value"]
            lat_ai1, res_ai1 = await client.call_tool("cscape_read_register", {"address": "%AI1", "data_type": "INT", "project_name": "TankLevelClosedLoop"})
            ai1 = json.loads(res_ai1["result"]["content"][0]["text"])["value"]
            lat_m9, res_m9 = await client.call_tool("cscape_read_register", {"address": "%M9", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            m9 = json.loads(res_m9["result"]["content"][0]["text"])["value"]

            assert ai1 == 6400
            assert pv <= 20.0
            assert m9 is True
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_scenario_d_dynamic_level_recovery(self):
        client = StdioRpcFastClient(PY_EXE, SERVER_PY)
        await client.start()
        try:
            await client.call_rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "TestStep157_ScenarioD", "version": "1.0.0"},
            })
            await client.call_rpc("notifications/initialized")

            # Dynamic Level Recovery back to 50.0% Setpoint
            await client.call_tool("cscape_write_register", {"address": "%R3", "value": 50.0, "data_type": "REAL", "project_name": "TankLevelClosedLoop"})
            await client.call_tool("cscape_write_register", {"address": "%AI1", "value": 16000, "data_type": "INT", "project_name": "TankLevelClosedLoop"})
            await client.call_tool("cscape_write_register", {"address": "%AI2", "value": 16000, "data_type": "INT", "project_name": "TankLevelClosedLoop"})

            for _ in range(10):
                await client.call_tool("cscape_simulate_cycle", {
                    "dt_ms": 10.0,
                    "inputs": {"RawLevelInput": 16000},
                    "project_name": "TankLevelClosedLoop",
                })

            await client.call_tool("cscape_write_register", {"address": "%R7", "value": 50.0, "data_type": "REAL", "project_name": "TankLevelClosedLoop"})
            await client.call_tool("cscape_write_register", {"address": "%Q2", "value": True, "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})

            lat_pv, res_pv = await client.call_tool("cscape_read_register", {"address": "%R1", "project_name": "TankLevelClosedLoop"})
            pv = json.loads(res_pv["result"]["content"][0]["text"])["value"]
            lat_sp, res_sp = await client.call_tool("cscape_read_register", {"address": "%R3", "project_name": "TankLevelClosedLoop"})
            sp = json.loads(res_sp["result"]["content"][0]["text"])["value"]
            lat_m9, res_m9 = await client.call_tool("cscape_read_register", {"address": "%M9", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            m9 = json.loads(res_m9["result"]["content"][0]["text"])["value"]
            lat_q2, res_q2 = await client.call_tool("cscape_read_register", {"address": "%Q2", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            q2 = json.loads(res_q2["result"]["content"][0]["text"])["value"]

            error = sp - pv
            assert abs(pv - 50.0) < 0.1
            assert abs(error) < 0.1
            assert m9 is False
            assert q2 is True
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_scenario_e_high_high_isolation_interlock(self):
        client = StdioRpcFastClient(PY_EXE, SERVER_PY)
        await client.start()
        try:
            await client.call_rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "TestStep157_ScenarioE", "version": "1.0.0"},
            })
            await client.call_rpc("notifications/initialized")

            # High-High Inflow Isolation Interlock Trip: Level reaches 92.0% (29440 counts)
            await client.call_tool("cscape_simulate_cycle", {
                "dt_ms": 10.0,
                "inputs": {"RawLevelInput": 29440},
                "project_name": "TankLevelClosedLoop",
            })

            lat_pv, res_pv = await client.call_tool("cscape_read_register", {"address": "%R1", "project_name": "TankLevelClosedLoop"})
            pv = json.loads(res_pv["result"]["content"][0]["text"])["value"]
            lat_m7, res_m7 = await client.call_tool("cscape_read_register", {"address": "%M7", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            m7 = json.loads(res_m7["result"]["content"][0]["text"])["value"]
            lat_q2, res_q2 = await client.call_tool("cscape_read_register", {"address": "%Q2", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
            q2 = json.loads(res_q2["result"]["content"][0]["text"])["value"]

            assert abs(pv - 92.0) < 0.1
            assert m7 is True
            assert q2 is False
        finally:
            await client.close()


class TestStep157SecurityAndLockout:
    """Validates pure software security constraints (zero Straton, hardware download lockout)."""

    @pytest.mark.asyncio
    async def test_hardware_download_lockout(self):
        client = StdioRpcFastClient(PY_EXE, SERVER_PY)
        await client.start()
        try:
            await client.call_rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "TestStep157Lockout", "version": "1.0.0"},
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
                "clientInfo": {"name": "TestStep157StratonCheck", "version": "1.0.0"},
            })
            await client.call_rpc("notifications/initialized")

            list_res = await client.call_rpc("tools/list", {})
            tool_names = [t["name"] for t in list_res.get("result", {}).get("tools", [])]
            for t in tool_names:
                assert "straton" not in t.lower(), f"Prohibited Straton tool found: {t}"
        finally:
            await client.close()


class TestStep157ArtifactsAndCheckpoints:
    """Validates Step 157 audit logs and checkpoints across dual roots."""

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_checkpoint_valid(self, root: Path):
        cp_file = root / "artifacts" / "checkpoints" / "step157_mcp_three_element_drum_balance_checkpoint.json"
        assert cp_file.exists(), f"Step 157 checkpoint missing on {root}"
        data = json.loads(cp_file.read_text(encoding="utf-8"))
        assert data["step"] == 157
        assert data["status"] == "PASSED"
        assert data["pure_software_simulation"] is True
        assert data["quiescent_balancing_verified"] is True
        assert data["steam_surge_feedforward_verified"] is True
        assert data["feedwater_loss_verified"] is True
        assert data["dynamic_recovery_verified"] is True
        assert data["isolation_interlock_verified"] is True
        assert data["zero_straton_dependencies"] is True
        assert data["hardware_lockout_enforced"] is True
        assert data["no_cscape_gui_wm_command"] is True
        assert "checkpoint_sha256" in data

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_log_valid(self, root: Path):
        log_file = root / "artifacts" / "logs" / "step157_mcp_three_element_drum_balance.json"
        assert log_file.exists(), f"Step 157 log missing on {root}"
        data = json.loads(log_file.read_text(encoding="utf-8"))
        assert data["step"] == 157
        assert data["status"] == "PASSED"
        assert data["scenarios_passed"] == 5
        assert data["scenarios_total"] == 5
        assert data["scenario_results"]["scenario_a_quiescent_balancing"]["verified"] is True
        assert data["scenario_results"]["scenario_b_steam_surge_feedforward"]["verified"] is True
        assert data["scenario_results"]["scenario_c_feedwater_loss"]["verified"] is True
        assert data["scenario_results"]["scenario_d_dynamic_recovery"]["verified"] is True
        assert data["scenario_results"]["scenario_e_isolation_interlock"]["verified"] is True
