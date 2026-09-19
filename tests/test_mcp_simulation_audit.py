"""Comprehensive Audit & Verification Test Suite for MCP Simulation Tools.

Subagent 13: MCP Simulation Tool Auditor
Audits:
1. cscape_simulate_cycle
2. cscape_run_simulation
3. cscape_read_register
4. cscape_write_register

Verification Domains:
1. Simulated register manipulation in software-only memory (%R, %AI, %AQ, %I, %Q, %M, %T, %S, %SR, REAL, DINT)
2. Strict isolation from physical hardware ports (COM1..COM256, CAN, USB, JTAG, download command lockout)
3. Integration with TankLevel closed-loop simulation state (artifacts/projects/TankLevelClosedLoop)
4. FastMCP async server dispatch (server.call_tool)
"""

import json
import math
import pytest
from pathlib import Path

from src.mcp.server import server, create_mcp_server
from src.mcp.tools import (
    cscape_simulate_cycle,
    cscape_run_simulation,
    cscape_read_register,
    cscape_write_register,
    get_active_simulator,
)
from src.cscape.simulation import (
    CscapeSimulator,
    HornerRegisterTable,
    RegisterType,
    parse_register_address,
    enforce_software_isolation,
)
from src.security.exceptions import (
    HardwareLockoutError,
    UnauthorizedDownloadError,
    SecurityError,
)


class TestSoftwareRegisterManipulation:
    """Verifies software-only register memory operations across all Horner OCS types."""

    def setup_method(self):
        get_active_simulator(project_name="UnitTestingMemory", reset=True)

    def test_word_register_read_write(self):
        """Verify 16-bit word registers (%R, %AI, %AQ, %SR)."""
        proj = "UnitTestingMemory"

        # %R holding register
        w_res = cscape_write_register(address="%R100", value=12345, project_name=proj)
        assert w_res["success"] is True
        assert w_res["address"] == "%R100"
        assert w_res["isolation_enforced"] is True

        r_res = cscape_read_register(address="%R100", project_name=proj)
        assert r_res["success"] is True
        assert r_res["value"] == 12345
        assert r_res["data_type"] == "INT"

        # Negative 16-bit signed integer
        cscape_write_register(address="%R101", value=-1234, project_name=proj)
        r_neg = cscape_read_register(address="%R101", project_name=proj)
        assert r_neg["value"] == -1234

        # %AI analog input register
        cscape_write_register(address="%AI1", value=24000, project_name=proj)
        assert cscape_read_register(address="%AI1", project_name=proj)["value"] == 24000

        # %AQ analog output register
        cscape_write_register(address="%AQ1", value=16000, project_name=proj)
        assert cscape_read_register(address="%AQ1", project_name=proj)["value"] == 16000

    def test_discrete_bit_register_read_write(self):
        """Verify discrete boolean bit registers (%I, %Q, %M, %T, %S)."""
        proj = "UnitTestingMemory"

        # %I discrete input
        cscape_write_register(address="%I1", value=True, project_name=proj)
        assert cscape_read_register(address="%I1", project_name=proj)["value"] is True
        cscape_write_register(address="%I1", value=False, project_name=proj)
        assert cscape_read_register(address="%I1", project_name=proj)["value"] is False

        # %Q discrete output
        cscape_write_register(address="%Q5", value=True, project_name=proj)
        assert cscape_read_register(address="%Q5", project_name=proj)["value"] is True

        # %M internal marker bit
        cscape_write_register(address="%M10", value=True, project_name=proj)
        assert cscape_read_register(address="%M10", project_name=proj)["value"] is True

        # %T temporary bit
        cscape_write_register(address="%T20", value=True, project_name=proj)
        assert cscape_read_register(address="%T20", project_name=proj)["value"] is True

    def test_bit_of_word_read_write(self):
        """Verify bit-of-word indexing (%R100.0 .. %R100.15)."""
        proj = "UnitTestingMemory"

        cscape_write_register(address="%R100", value=0, project_name=proj)
        cscape_write_register(address="%R100.0", value=True, project_name=proj)
        cscape_write_register(address="%R100.3", value=True, project_name=proj)

        assert cscape_read_register(address="%R100.0", project_name=proj)["value"] is True
        assert cscape_read_register(address="%R100.1", project_name=proj)["value"] is False
        assert cscape_read_register(address="%R100.3", project_name=proj)["value"] is True
        assert cscape_read_register(address="%R100", project_name=proj)["value"] == 9

    def test_real_32bit_float_read_write(self):
        """Verify 32-bit IEEE 754 REAL floating-point values across two registers."""
        proj = "UnitTestingMemory"

        test_val = 78.625
        w_res = cscape_write_register(address="%R50", value=test_val, data_type="REAL", project_name=proj)
        assert w_res["success"] is True
        assert w_res["data_type"] == "REAL"

        r_res = cscape_read_register(address="%R50", data_type="REAL", project_name=proj)
        assert r_res["success"] is True
        assert math.isclose(r_res["value"], test_val, rel_tol=1e-5)

    def test_dint_32bit_signed_integer_read_write(self):
        """Verify 32-bit signed DINT integer values across two registers."""
        proj = "UnitTestingMemory"

        test_dint = 123456789
        w_res = cscape_write_register(address="%R60", value=test_dint, data_type="DINT", project_name=proj)
        assert w_res["success"] is True
        assert w_res["data_type"] == "DINT"

        r_res = cscape_read_register(address="%R60", data_type="DINT", project_name=proj)
        assert r_res["success"] is True
        assert r_res["value"] == test_dint

    def test_system_bits_and_registers_in_simulation_cycle(self):
        """Verify %S system clock bits and %SR system registers are updated accurately."""
        proj = "UnitTestingMemory"
        sim = get_active_simulator(project_name=proj, reset=True)

        res0 = cscape_simulate_cycle(dt_ms=10.0, project_name=proj)
        assert res0["success"] is True
        assert res0["cycle"] == 0
        assert res0["system_bits"]["%S1"] is True

        res1 = cscape_simulate_cycle(dt_ms=10.0, project_name=proj)
        assert res1["success"] is True
        assert res1["cycle"] == 1
        assert res1["system_bits"]["%S1"] is False
        assert res1["system_bits"]["%S7"] is True


class TestPhysicalHardwareIsolation:
    """Verifies fail-closed lockout of all physical communication interfaces."""

    def test_com_port_hardware_lockout(self):
        """Verify attempts to target COM serial ports fail closed."""
        for bad_port in ["COM1", "COM3", "com24", r"\\.\COM4"]:
            res_r = cscape_read_register(address=bad_port)
            assert res_r["success"] is False
            assert "blocked" in res_r["message"].lower() or "invalid" in res_r["message"].lower()
            assert res_r["isolation_enforced"] is True

            res_w = cscape_write_register(address=bad_port, value=1)
            assert res_w["success"] is False
            assert "blocked" in res_w["message"].lower() or "invalid" in res_w["message"].lower()
            assert res_w["isolation_enforced"] is True

    def test_can_and_usb_hardware_lockout(self):
        """Verify CAN and USB bus interfaces fail closed."""
        for hw in ["CAN0", "PCAN0", "USB0", "/dev/ttyUSB0"]:
            res = cscape_read_register(address=hw)
            assert res["success"] is False
            assert res["isolation_enforced"] is True

    def test_prohibited_download_commands_locked_out(self):
        """Verify controller download commands are strictly blocked."""
        with pytest.raises(UnauthorizedDownloadError):
            enforce_software_isolation("download")

        with pytest.raises(UnauthorizedDownloadError):
            enforce_software_isolation("--download")

        with pytest.raises(UnauthorizedDownloadError):
            enforce_software_isolation("/flash")

    def test_out_of_bounds_registers_rejected(self):
        """Horner OCS register boundary limits are strictly enforced."""
        proj = "UnitTestingMemory"
        res1 = cscape_read_register(address="%R10000", project_name=proj)
        assert res1["success"] is False
        assert "out of bounds" in res1["message"]

        res2 = cscape_read_register(address="%AI513", project_name=proj)
        assert res2["success"] is False
        assert "out of bounds" in res2["message"]

        res3 = cscape_read_register(address="%I2049", project_name=proj)
        assert res3["success"] is False
        assert "out of bounds" in res3["message"]

        # 32-bit multi-register boundary limits (R9999 requires R9999 + R10000)
        res_real_w = cscape_write_register(address="%R9999", value=12.34, data_type="REAL", project_name=proj)
        assert res_real_w["success"] is False
        assert "out of bounds" in res_real_w["message"]

        res_real_r = cscape_read_register(address="%R9999", data_type="REAL", project_name=proj)
        assert res_real_r["success"] is False
        assert "out of bounds" in res_real_r["message"]

        res_dint_w = cscape_write_register(address="%R9999", value=999999, data_type="DINT", project_name=proj)
        assert res_dint_w["success"] is False
        assert "out of bounds" in res_dint_w["message"]

        res_dint_r = cscape_read_register(address="%R9999", data_type="DINT", project_name=proj)
        assert res_dint_r["success"] is False
        assert "out of bounds" in res_dint_r["message"]

        # Bit offset out of bounds (> 15)
        res_bit_err = cscape_read_register(address="%R100.16", project_name=proj)
        assert res_bit_err["success"] is False
        assert "out of bounds" in res_bit_err["message"]

        # Bit offset on discrete bit register prohibited
        res_disc_bit = cscape_read_register(address="%I1.0", project_name=proj)
        assert res_disc_bit["success"] is False
        assert "bit offset" in res_disc_bit["message"].lower()


class TestTankLevelClosedLoopIntegration:
    """Verifies integration with artifacts/projects/TankLevelClosedLoop."""

    def setup_method(self):
        self.sim = get_active_simulator(project_name="TankLevelClosedLoop", reset=True)

    def test_tank_level_variables_bound_to_ocs_registers(self):
        """Verify all TankLevel variables from variables.csv are bound to registers."""
        mapping = self.sim.mapping
        assert mapping.get_var_for_register("%AI1") == "RawLevelInput"
        assert mapping.get_var_for_register("%AQ1") == "RawPumpOutput"
        assert mapping.get_var_for_register("%AQ2") == "RawValveOutput"
        assert mapping.get_var_for_register("%I1") == "DI_System_Start_PB"
        assert mapping.get_var_for_register("%Q1") == "PumpRunCmd"
        assert mapping.get_var_for_register("%Q2") == "InflowValveCmd"
        assert mapping.get_var_for_register("%M7") == "AlarmHighHigh"
        assert mapping.get_var_for_register("%M8") == "AlarmHigh"
        assert mapping.get_var_for_register("%M9") == "AlarmLow"
        assert mapping.get_var_for_register("%M10") == "AlarmLowLow"
        assert mapping.get_var_for_register("%R1") == "TankLevelPV"
        assert mapping.get_var_for_register("%R3") == "Setpoint"
        assert mapping.get_var_for_register("%R7") == "ControlOutput"
        assert mapping.get_var_for_register("%R21") == "CycleCounter"

    def test_overfill_trip_high_high_alarm(self):
        """High-High level trip test: %AI1 = 32000 (100% full) trips %M7 and cuts inflow %Q2."""
        proj = "TankLevelClosedLoop"

        # 1. Write RawLevelInput = 32000 (20mA full level)
        cscape_write_register(address="%AI1", value=32000, project_name=proj)

        # 2. Simulate 1 scan cycle
        step_res = cscape_simulate_cycle(dt_ms=10.0, project_name=proj)
        assert step_res["success"] is True

        # 3. Read TankLevelPV (%R1) - must scale to 100.0%
        pv_res = cscape_read_register(address="%R1", project_name=proj)
        assert pv_res["success"] is True
        assert math.isclose(pv_res["value"], 100.0, abs_tol=0.1)

        # 4. Read AlarmHighHigh (%M7) - must trip to True (>= 90%)
        hh_res = cscape_read_register(address="%M7", project_name=proj)
        assert hh_res["success"] is True
        assert hh_res["value"] is True

        # 5. InflowValveCmd (%Q2) - must interlock and shut off (False)
        q2_res = cscape_read_register(address="%Q2", project_name=proj)
        assert q2_res["success"] is True
        assert q2_res["value"] is False

    def test_dry_run_pump_protection_low_low_alarm(self):
        """Low-Low level dry-run protection test: %AI1 = 0 (0% empty) trips %M10 and halts pump %Q1."""
        proj = "TankLevelClosedLoop"

        # 1. Write RawLevelInput = 0 (4mA empty tank)
        cscape_write_register(address="%AI1", value=0, project_name=proj)

        # 2. Simulate scan cycle
        cscape_simulate_cycle(dt_ms=10.0, project_name=proj)

        # 3. Read TankLevelPV (%R1) - must scale to 0.0%
        pv_res = cscape_read_register(address="%R1", project_name=proj)
        assert math.isclose(pv_res["value"], 0.0, abs_tol=0.1)

        # 4. Read AlarmLowLow (%M10) - must trip to True (<= 10%)
        ll_res = cscape_read_register(address="%M10", project_name=proj)
        assert ll_res["value"] is True

        # 5. Read PumpRunCmd (%Q1) - must trip False to protect against dry run
        pump_res = cscape_read_register(address="%Q1", project_name=proj)
        assert pump_res["value"] is False

    def test_cycle_counter_dint_increment(self):
        """Verify CycleCounter (%R21) increments monotonically across scan cycles."""
        proj = "TankLevelClosedLoop"

        c0 = cscape_read_register(address="%R21", project_name=proj)["value"]

        for _ in range(5):
            cscape_simulate_cycle(dt_ms=10.0, project_name=proj)

        c5 = cscape_read_register(address="%R21", project_name=proj)["value"]
        assert c5 == c0 + 5


class TestRunSimulationEngine:
    """Verifies multi-step simulation execution via cscape_run_simulation."""

    def test_run_simulation_step_validation(self):
        """Input validation rejects invalid step counts fail closed."""
        res_neg = cscape_run_simulation(steps=-1)
        assert res_neg["success"] is False
        assert "Simulation error" in res_neg["message"]

        res_zero = cscape_run_simulation(steps=0)
        assert res_zero["success"] is False

        res_huge = cscape_run_simulation(steps=1000000)
        assert res_huge["success"] is False

    def test_run_simulation_clock_and_trace(self):
        """Verify cycle counts, elapsed time, and trace generation."""
        res = cscape_run_simulation(steps=4, dt_ms=10.0)
        assert res["success"] is True
        assert res["total_cycles"] == 4
        assert res["elapsed_time_ms"] == 40.0
        assert len(res["trace"]) == 4
        assert res["isolation_enforced"] is True
        # Cycle 0 has first scan bit %S1 True
        assert res["trace"][0]["system_bits"]["%S1"] is True
        # Cycle 1 has %S1 False
        assert res["trace"][1]["system_bits"]["%S1"] is False

    def test_run_simulation_with_st_code(self):
        """Verify execution with inline Structured Text code."""
        st_code = """
        PROGRAM TestProg
        VAR
            Counter : INT := 0;
        END_VAR
        Counter := Counter + 1;
        END_PROGRAM
        """
        res = cscape_run_simulation(steps=3, st_code=st_code, dt_ms=10.0)
        assert res["success"] is True
        assert res["total_cycles"] == 3


class TestFastMCPSimulationToolDispatch:
    """Verifies async tool execution through MCPServer interface."""

    @pytest.mark.asyncio
    async def test_tools_registered_on_server(self):
        """Verify simulation tools are registered on the FastMCP server instance."""
        tools = await server.list_tools()
        tool_names = [t.name for t in tools]
        assert "cscape_simulate_cycle" in tool_names
        assert "cscape_run_simulation" in tool_names
        assert "cscape_read_register" in tool_names
        assert "cscape_write_register" in tool_names

    @pytest.mark.asyncio
    async def test_async_call_tool_run_simulation(self):
        """Verify async execution of cscape_run_simulation through server.call_tool."""
        res = await server.call_tool("cscape_run_simulation", {"steps": 3, "dt_ms": 10.0})
        assert not res.is_error
        data = json.loads(res.content[0].text)
        assert data["success"] is True
        assert data["total_cycles"] == 3
        assert data["isolation_enforced"] is True

    @pytest.mark.asyncio
    async def test_async_call_tool_write_simulate_read_pipeline(self):
        """Verify complete pipeline through server.call_tool."""
        res_w = await server.call_tool("cscape_write_register", {
            "address": "%AI1",
            "value": 16000,
            "project_name": "TankLevelClosedLoop",
        })
        assert not res_w.is_error
        data_w = json.loads(res_w.content[0].text)
        assert data_w["success"] is True
        assert data_w["address"] == "%AI1"
        assert data_w["value"] == 16000

        res_sim = await server.call_tool("cscape_simulate_cycle", {
            "dt_ms": 10.0,
            "project_name": "TankLevelClosedLoop",
        })
        assert not res_sim.is_error
        data_sim = json.loads(res_sim.content[0].text)
        assert data_sim["success"] is True
        assert data_sim["isolation_enforced"] is True

        res_r = await server.call_tool("cscape_read_register", {
            "address": "%R1",
            "project_name": "TankLevelClosedLoop",
        })
        assert not res_r.is_error
        data_r = json.loads(res_r.content[0].text)
        assert data_r["success"] is True
        assert math.isclose(data_r["value"], 50.0, abs_tol=0.5)
        assert data_r["bound_variable"] == "TankLevelPV"
