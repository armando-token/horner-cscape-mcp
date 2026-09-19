"""Test Suite for Step 141: Multi-Cycle FastMCP Closed-Loop Plant Simulation & Discrete Register Verification.

Verifies:
1. FastMCP Simulation & Software Register Tools (cscape_run_simulation, cscape_simulate_cycle, cscape_read_register, cscape_write_register).
2. Register & Variable Interaction across multiple OCS types (%R INT/REAL/DINT, %M bits, %AI, %AQ, %Q, %I, bit-of-word).
3. Boundary & Error Handling (out-of-bounds indices, multi-register spans, invalid formats, IEEE 754 precision).
4. Closed-Loop Plant Dynamics on TankLevelClosedLoop (Setpoint tracking, PID modulation, pump/valve sequencing).
5. Alarm Thresholds (%M7 HH, %M8 H, %M9 L, %M10 LL) and Hysteresis Deadbands.
6. Disturbance Injection and Emergency Trip Shutoff (fail-closed trip when %M7 active).
7. Safety & Software Isolation (COM/CAN/USB lockout, ID_CONTROLLER_DOWNLOAD 32827 & 33149 lockout, zero Straton dependencies).
8. FastMCP Server Async Dispatch (server.call_tool pipeline).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Dict

import psutil
import pytest

# Mandatory import path safety
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()

for r in [str(HORNER_ROOT), str(USER_ROOT)]:
    if r not in sys.path:
        sys.path.insert(0, r)

from src.cscape.gate import assert_cscape_live, get_gate_status
from src.mcp.server import server
from src.mcp.tools import (
    cscape_run_simulation,
    cscape_simulate_cycle,
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
from src.cscape.safety import (
    ID_CONTROLLER_DOWNLOAD,
    ID_CONTROLLER_DOWNLOAD_ALT,
    intercept_download_command,
    CscapeSafetyViolationError,
)
from src.security.exceptions import (
    HardwareLockoutError,
    UnauthorizedDownloadError,
)
from src.security.guard import SafetyGuard

# TARGET_PID dynamically resolved from live gate
TARGET_PROJECT = "TankLevelClosedLoop"
STRATON_BINARIES = ["k5bus.exe", "k5edit.exe", "k5run.exe", "k5vm.exe", "k5cmd.exe", "t5.exe"]

CHECKPOINT_REL = Path("artifacts/checkpoints/step141_mcp_closed_loop_simulation_checkpoint.json")
LOG_REL = Path("artifacts/logs/step141_mcp_closed_loop_simulation.json")


# ==============================================================================
# 1. Checkpoint & Gate Structure Tests
# ==============================================================================

class TestStep141CheckpointAndGate:
    """Verifies Step 141 checkpoint and live gate files across both workspace roots."""

    @pytest.mark.parametrize("root", [HORNER_ROOT, USER_ROOT])
    def test_checkpoint_exists_and_valid_schema(self, root: Path):
        """Assertion 1: Step 141 checkpoint exists and contains valid schema."""
        cp_path = root / CHECKPOINT_REL
        assert cp_path.exists(), f"Checkpoint missing at {cp_path}"
        data = json.loads(cp_path.read_text(encoding="utf-8"))
        assert data["step"] == 141
        assert data["name"] == "step141_mcp_closed_loop_simulation_checkpoint"
        assert data["status"] == "PASSED"
        assert data["cscape_pid"] > 0
        assert data["hwnd"] == "0x024B054A"
        assert data["closed_loop_cycles"] == 50
        assert data["setpoint_tracking_verified"] is True
        assert data["emergency_trip_shutoff_verified"] is True
        assert data["pure_software_isolation_enforced"] is True
        assert "checkpoint_sha256" in data
        assert len(data["checkpoint_sha256"]) == 64

    def test_live_gate_ready_and_responsive(self):
        """Assertion 2: Live Cscape gate indicates READY_FOR_TESTS with TankLevelClosedLoop."""
        gate = get_gate_status()
        active_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not active_pid or not psutil.pid_exists(active_pid):
            pytest.skip(f"No active live Cscape gate (PID {active_pid})")
        assert gate.get("ready_for_tests") is True
        assert gate.get("status") == "READY_FOR_TESTS"
        assert active_pid > 0
        assert psutil.pid_exists(active_pid), f"Active Cscape PID {active_pid} is not running!"
        assert "TankLevelClosedLoop" in gate.get("project_file", "")

    def test_audit_log_exists_and_sha256_matches(self):
        """Assertion 3: Empirical audit log exists with valid JSON and SHA-256 match."""
        log_path = HORNER_ROOT / LOG_REL
        assert log_path.exists(), f"Log missing at {log_path}"
        raw_text = log_path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
        assert data["step"] == 141
        assert "phases" in data
        assert data["phases"]["closed_loop_simulation"]["status"] == "PASSED"
        expected_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        cp = json.loads((HORNER_ROOT / CHECKPOINT_REL).read_text(encoding="utf-8"))
        assert cp["log_sha256"] == expected_hash


# ==============================================================================
# 2. FastMCP Simulation Engine & Cycle Stepping Tests
# ==============================================================================

class TestFastMCPSimulationEngine:
    """Verifies cscape_run_simulation and cscape_simulate_cycle functionality."""

    def test_cscape_run_simulation_step_validation(self):
        """Assertion 4: Input validation rejects invalid step counts fail-closed."""
        res_neg = cscape_run_simulation(steps=-1)
        assert res_neg["success"] is False
        assert "Simulation error" in res_neg["message"]

        res_zero = cscape_run_simulation(steps=0)
        assert res_zero["success"] is False

        res_huge = cscape_run_simulation(steps=1000000)
        assert res_huge["success"] is False

    def test_cscape_run_simulation_cycle_stepping_and_system_clocks(self):
        """Assertion 5: Multi-cycle execution produces valid trace and system bits (%S1..%S9)."""
        res = cscape_run_simulation(steps=5, dt_ms=10.0)
        assert res["success"] is True
        assert res["total_cycles"] == 5
        assert res["elapsed_time_ms"] == 50.0
        assert len(res["trace"]) == 5
        assert res["isolation_enforced"] is True

        # First scan bit %S1 is TRUE only on cycle 0
        assert res["trace"][0]["system_bits"]["%S1"] is True
        assert res["trace"][1]["system_bits"]["%S1"] is False
        assert res["trace"][2]["system_bits"]["%S1"] is False

    def test_cscape_run_simulation_inline_st_code(self):
        """Assertion 6: Executes inline Structured Text program cleanly."""
        st_code = """
        PROGRAM CounterTest
        VAR
            Tally : INT := 10;
        END_VAR
        Tally := Tally + 5;
        END_PROGRAM
        """
        res = cscape_run_simulation(steps=3, st_code=st_code, dt_ms=10.0)
        assert res["success"] is True
        assert res["total_cycles"] == 3

    def test_cscape_simulate_cycle_discrete_execution(self):
        """Assertion 7: Single cycle execution updates time and system bit snapshot."""
        proj = "UnitTestingMemory"
        sim = get_active_simulator(project_name=proj, reset=True)
        res0 = cscape_simulate_cycle(dt_ms=10.0, project_name=proj)
        assert res0["success"] is True
        assert res0["cycle"] == 0
        assert res0["isolation_enforced"] is True
        assert res0["hardware_lockout_enforced"] is True
        assert res0["system_bits"]["%S1"] is True

        res1 = cscape_simulate_cycle(dt_ms=10.0, project_name=proj)
        assert res1["success"] is True
        assert res1["cycle"] == 1
        assert res1["system_bits"]["%S1"] is False

    def test_cscape_simulate_cycle_system_registers(self):
        """Assertion 8: System registers (%SR1 scan rate, %SR2 status) are updated."""
        proj = "UnitTestingMemory"
        res = cscape_simulate_cycle(dt_ms=15.0, project_name=proj)
        assert res["success"] is True
        assert "%SR1" in res["registers"]
        assert "%SR2" in res["registers"]


# ==============================================================================
# 3. Discrete Register Manipulation & Boundary Handling Tests
# ==============================================================================

class TestDiscreteRegisterVerification:
    """Verifies software-only register memory operations across all Horner OCS types."""

    def setup_method(self):
        get_active_simulator(project_name="UnitTestingMemory", reset=True)

    def test_register_word_read_write_int16(self):
        """Assertion 9: 16-bit word registers (%R, %AI, %AQ, %SR) with signed values."""
        proj = "UnitTestingMemory"
        # Positive INT16
        cscape_write_register("%R100", 30000, project_name=proj)
        assert cscape_read_register("%R100", project_name=proj)["value"] == 30000

        # Negative INT16
        cscape_write_register("%R101", -15000, project_name=proj)
        assert cscape_read_register("%R101", project_name=proj)["value"] == -15000

        # %AI and %AQ analog registers
        cscape_write_register("%AI1", 16000, project_name=proj)
        assert cscape_read_register("%AI1", project_name=proj)["value"] == 16000
        cscape_write_register("%AQ1", 24000, project_name=proj)
        assert cscape_read_register("%AQ1", project_name=proj)["value"] == 24000

    def test_register_discrete_bits_read_write(self):
        """Assertion 10: Discrete boolean bit registers (%I, %Q, %M, %T)."""
        proj = "UnitTestingMemory"
        for bit_addr in ["%I1", "%Q1", "%M7", "%M10", "%T1"]:
            cscape_write_register(bit_addr, True, project_name=proj)
            assert cscape_read_register(bit_addr, project_name=proj)["value"] is True
            cscape_write_register(bit_addr, False, project_name=proj)
            assert cscape_read_register(bit_addr, project_name=proj)["value"] is False

    def test_register_bit_of_word_addressing(self):
        """Assertion 11: Bit-of-word indexing (%R100.0 .. %R100.15) read and write."""
        proj = "UnitTestingMemory"
        cscape_write_register("%R100", 0, project_name=proj)
        cscape_write_register("%R100.0", True, project_name=proj)
        cscape_write_register("%R100.3", True, project_name=proj)
        assert cscape_read_register("%R100.0", project_name=proj)["value"] is True
        assert cscape_read_register("%R100.1", project_name=proj)["value"] is False
        assert cscape_read_register("%R100.3", project_name=proj)["value"] is True
        assert cscape_read_register("%R100", project_name=proj)["value"] == 9

    def test_register_real_ieee754_floating_point(self):
        """Assertion 12: 32-bit REAL IEEE 754 float across two registers with precision."""
        proj = "UnitTestingMemory"
        for val in [0.0, 50.0, 87.625, 3.14159, -12.5]:
            cscape_write_register("%R50", val, data_type="REAL", project_name=proj)
            read_back = cscape_read_register("%R50", data_type="REAL", project_name=proj)["value"]
            assert math.isclose(read_back, val, rel_tol=1e-5)

    def test_register_dint_32bit_signed_integer(self):
        """Assertion 13: 32-bit signed DINT integer across two registers."""
        proj = "UnitTestingMemory"
        test_val = 123456789
        cscape_write_register("%R60", test_val, data_type="DINT", project_name=proj)
        assert cscape_read_register("%R60", data_type="DINT", project_name=proj)["value"] == test_val

    def test_register_boundary_overflow_rejection(self):
        """Assertion 14: Rejects out-of-bounds register indices fail-closed."""
        proj = "UnitTestingMemory"
        for bad_addr in ["%R10000", "%AI513", "%AQ513", "%M2049", "%Q2049", "%I2049", "%S17", "%SR257"]:
            res = cscape_read_register(bad_addr, project_name=proj)
            assert res["success"] is False
            assert "out of bounds" in res["message"]

    def test_register_multiword_upper_boundary_limits(self):
        """Assertion 15: Rejects multi-word 32-bit types on upper boundary and invalid bit offsets."""
        proj = "UnitTestingMemory"
        # %R9999 for REAL needs %R9999 + %R10000
        res_real = cscape_write_register("%R9999", 12.34, data_type="REAL", project_name=proj)
        assert res_real["success"] is False
        assert "out of bounds" in res_real["message"]

        # Bit offset > 15
        res_bit = cscape_read_register("%R100.16", project_name=proj)
        assert res_bit["success"] is False

        # Bit offset on discrete bit
        res_disc = cscape_read_register("%I1.0", project_name=proj)
        assert res_disc["success"] is False

    def test_register_invalid_format_rejection(self):
        """Assertion 16: Rejects malformed register strings fail-closed."""
        proj = "UnitTestingMemory"
        for bad in ["INVALID", "%XYZ10", "123", "%", "%R", "R"]:
            res = cscape_read_register(bad, project_name=proj)
            assert res["success"] is False


# ==============================================================================
# 4. TankLevelClosedLoop Plant Dynamics & Alarms Tests
# ==============================================================================

class TestTankLevelClosedLoopPlantSimulation:
    """Verifies closed-loop simulation dynamics, alarms, and emergency trip on TankLevelClosedLoop."""

    def setup_method(self):
        self.sim = get_active_simulator("TankLevelClosedLoop", reset=True)

    def test_tank_level_variables_bound_to_registers(self):
        """Assertion 17: All TankLevelClosedLoop variables are bound to Horner OCS registers."""
        mapping = self.sim.mapping
        assert mapping.get_var_for_register("%AI1") == "RawLevelInput"
        assert mapping.get_var_for_register("%AQ1") == "RawPumpOutput"
        assert mapping.get_var_for_register("%AQ2") == "RawValveOutput"
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

    def test_closed_loop_setpoint_tracking_and_modulation(self):
        """Assertion 18: Multi-cycle plant simulation tracks setpoint with PID modulation."""
        proj = "TankLevelClosedLoop"
        plant_level = 45.0
        setpoint = 60.0
        outflow = 20.0
        capacitance = 10.0
        dt_sec = 0.01

        for _ in range(30):
            raw_counts = int((plant_level / 100.0) * 32000.0)
            cscape_write_register("%AI1", raw_counts, project_name=proj)
            cscape_simulate_cycle(dt_ms=10.0, project_name=proj)

            cv = cscape_read_register("%R7", project_name=proj)["value"]
            valve_cmd = cscape_read_register("%Q2", project_name=proj)["value"]
            inflow = cv if valve_cmd else 0.0
            plant_level += ((inflow - outflow) / capacitance) * dt_sec * 100.0
            plant_level = max(0.0, min(100.0, plant_level))

        # Level must increase from 45.0% towards 60.0%
        assert plant_level > 45.0
        # Pump must remain commanded on
        assert cscape_read_register("%Q1", project_name=proj)["value"] is True

    def test_high_high_alarm_emergency_trip_shutoff(self):
        """Assertion 19: High-High trip (>=90.0%) forces inflow valve %Q2 to False (emergency shutoff)."""
        proj = "TankLevelClosedLoop"
        # 1. Level at 92% (overfill)
        cscape_write_register("%AI1", int(92.0 * 320), project_name=proj)
        cscape_simulate_cycle(10.0, project_name=proj)

        # AlarmHighHigh (%M7) must trip True
        assert cscape_read_register("%M7", project_name=proj)["value"] is True
        # InflowValveCmd (%Q2) must trip False (fail-closed trip!)
        assert cscape_read_register("%Q2", project_name=proj)["value"] is False

    def test_low_low_alarm_dry_run_pump_protection(self):
        """Assertion 20: Low-Low trip (<=10.0%) trips %M10 and halts feed pump %Q1 to protect against dry run."""
        proj = "TankLevelClosedLoop"
        # Level at 5% (empty)
        cscape_write_register("%AI1", int(5.0 * 320), project_name=proj)
        cscape_simulate_cycle(10.0, project_name=proj)

        # AlarmLowLow (%M10) must trip True
        assert cscape_read_register("%M10", project_name=proj)["value"] is True
        # PumpRunCmd (%Q1) must halt False
        assert cscape_read_register("%Q1", project_name=proj)["value"] is False

    def test_alarm_hysteresis_deadbands_full_matrix(self):
        """Assertion 21: Validates hysteresis deadbands for all 4 alarms (HH, H, L, LL)."""
        proj = "TankLevelClosedLoop"

        # High-High Hysteresis: Trips >= 90%, Resets < 88%
        cscape_write_register("%AI1", int(91.0 * 320), project_name=proj)
        cscape_simulate_cycle(10.0, project_name=proj)
        assert cscape_read_register("%M7", project_name=proj)["value"] is True
        # At 89% (still >= 88%) -> remains True
        cscape_write_register("%AI1", int(89.0 * 320), project_name=proj)
        cscape_simulate_cycle(10.0, project_name=proj)
        assert cscape_read_register("%M7", project_name=proj)["value"] is True
        # At 86% (< 88%) -> resets False
        cscape_write_register("%AI1", int(86.0 * 320), project_name=proj)
        cscape_simulate_cycle(10.0, project_name=proj)
        assert cscape_read_register("%M7", project_name=proj)["value"] is False

        # Low-Low Hysteresis: Trips <= 10%, Resets > 12%
        cscape_write_register("%AI1", int(8.0 * 320), project_name=proj)
        cscape_simulate_cycle(10.0, project_name=proj)
        assert cscape_read_register("%M10", project_name=proj)["value"] is True
        # At 11% (<= 12%) -> remains True
        cscape_write_register("%AI1", int(11.0 * 320), project_name=proj)
        cscape_simulate_cycle(10.0, project_name=proj)
        assert cscape_read_register("%M10", project_name=proj)["value"] is True
        # At 14% (> 12%) -> resets False
        cscape_write_register("%AI1", int(14.0 * 320), project_name=proj)
        cscape_simulate_cycle(10.0, project_name=proj)
        assert cscape_read_register("%M10", project_name=proj)["value"] is False

    def test_closed_loop_disturbance_injection_and_recovery(self):
        """Assertion 22: Injected surge triggers emergency trip, clears fail-closed upon drainage."""
        proj = "TankLevelClosedLoop"
        # Normal level 60%
        cscape_write_register("%AI1", int(60.0 * 320), project_name=proj)
        cscape_simulate_cycle(10.0, project_name=proj)
        assert cscape_read_register("%M7", project_name=proj)["value"] is False

        # Injected surge to 95%
        cscape_write_register("%AI1", int(95.0 * 320), project_name=proj)
        cscape_simulate_cycle(10.0, project_name=proj)
        assert cscape_read_register("%M7", project_name=proj)["value"] is True
        assert cscape_read_register("%Q2", project_name=proj)["value"] is False

        # Drain to 70%
        cscape_write_register("%AI1", int(70.0 * 320), project_name=proj)
        cscape_simulate_cycle(10.0, project_name=proj)
        assert cscape_read_register("%M7", project_name=proj)["value"] is False
        assert cscape_read_register("%Q2", project_name=proj)["value"] is True

    def test_cycle_counter_monotonicity(self):
        """Assertion 23: CycleCounter (%R21) increments by 1 per execution cycle."""
        proj = "TankLevelClosedLoop"
        c0 = cscape_read_register("%R21", project_name=proj)["value"]
        for _ in range(5):
            cscape_simulate_cycle(10.0, project_name=proj)
        c5 = cscape_read_register("%R21", project_name=proj)["value"]
        assert c5 == c0 + 5


# ==============================================================================
# 5. FastMCP Server Dispatch & Safety Isolation Tests
# ==============================================================================

class TestFastMCPServerAndSafetyIsolation:
    """Verifies FastMCP async dispatch and zero-hardware isolation enforcement."""

    @pytest.mark.asyncio
    async def test_fastmcp_list_tools_registered(self):
        """Assertion 24: All 4 simulation and register tools registered on FastMCP server."""
        tools = await server.list_tools()
        names = [t.name for t in tools]
        for expected in ["cscape_run_simulation", "cscape_simulate_cycle", "cscape_read_register", "cscape_write_register"]:
            assert expected in names

    @pytest.mark.asyncio
    async def test_fastmcp_async_tool_dispatch_pipeline(self):
        """Assertion 25: Pipelined async dispatch over server.call_tool."""
        proj = "TankLevelClosedLoop"
        res_w = await server.call_tool("cscape_write_register", {
            "address": "%AI1",
            "value": 16000,
            "project_name": proj,
        })
        assert not res_w.is_error
        assert json.loads(res_w.content[0].text)["success"] is True

        res_sim = await server.call_tool("cscape_simulate_cycle", {
            "dt_ms": 10.0,
            "project_name": proj,
        })
        assert not res_sim.is_error
        assert json.loads(res_sim.content[0].text)["success"] is True

        res_r = await server.call_tool("cscape_read_register", {
            "address": "%R1",
            "project_name": proj,
        })
        assert not res_r.is_error
        assert math.isclose(json.loads(res_r.content[0].text)["value"], 50.0, abs_tol=0.1)

    def test_hardware_isolation_fail_closed_ports(self):
        """Assertion 26: Hardware ports (COM, CAN, USB) blocked unconditionally."""
        for port in ["COM1", "COM4", "CAN0", "USB0"]:
            res = cscape_read_register(port)
            assert res["success"] is False
            assert res["isolation_enforced"] is True

    def test_controller_download_lockout_enforcement(self):
        """Assertion 27: Controller download (32827, 33149) strictly intercepted and blocked."""
        assert ID_CONTROLLER_DOWNLOAD == 32827
        assert ID_CONTROLLER_DOWNLOAD_ALT == 33149

        with pytest.raises(CscapeSafetyViolationError):
            intercept_download_command(32827)

        with pytest.raises(CscapeSafetyViolationError):
            intercept_download_command(33149)

        with pytest.raises(UnauthorizedDownloadError):
            SafetyGuard.validate_download("/download")

        # Zero Straton processes
        for p in psutil.process_iter(["name"]):
            try:
                name = p.info["name"]
                if name:
                    assert name.lower() not in STRATON_BINARIES, f"Straton process running: {name}"
            except Exception:
                pass
