"""Comprehensive Unit Tests for Horner Cscape 10.2 Simulation Interface.

Tests:
1. Cscape Win32 / MFC Command IDs & Menu Architecture
2. Horner OCS Register Address Parsing & Validation
3. HornerRegisterTable (Word, Bit, DINT, REAL, Range, System Bits/Registers)
4. VariableRegisterMapping & ST AST Preprocessing
5. CscapeSimulator Execution (Cycles, Step, Breakpoints, Timers, Trace)
6. 100% Software Isolation & Hardware Lockout Enforcement
7. Pure-Software Execution, Horner %S System Clocks & Timer/Counter Verification
8. CscapeUIAutomationController Command Auditing
9. High-Level Facade APIs (create_cscape_simulation, simulate_pou_with_registers)
"""

import math
import sys
from pathlib import Path
import pytest

from src.cscape.simulation import (
    CLASSIFICATION,
    VERIFICATION_CLASSIFICATION,
    CscapeCommandID,
    CscapeSimulator,
    CscapeUIAutomationController,
    HornerRegisterTable,
    RegisterAddress,
    RegisterType,
    SimulationBackend,
    SimulationSnapshot,
    SimulationState,
    VariableRegisterMapping,
    create_cscape_simulation,
    enforce_software_isolation,
    parse_register_address,
    simulate_pou_with_registers,
)
from src.security.exceptions import (
    HardwareLockoutError,
    SecurityError,
    UnauthorizedDownloadError,
)
from src.security.policy import DEFAULT_BLOCKED_UI_COMMANDS


# ============================================================================
# 1. Cscape Win32 Command IDs & Menu Architecture Tests
# ============================================================================

class TestCscapeCommandIDs:
    """Tests for Cscape 10.2 Win32 / MFC command constants."""

    def test_command_id_values(self):
        """Verify command IDs match reverse-engineered Cscape.exe menu resource 550."""
        assert CscapeCommandID.START_SIMULATION == 38367
        assert CscapeCommandID.STOP_DEBUG_SIMULATION == 38037
        assert CscapeCommandID.EXECUTE_SINGLE_CYCLE == 38357
        assert CscapeCommandID.RESUME_CYCLE_MODE == 38365
        assert CscapeCommandID.STEP_IN == 38358
        assert CscapeCommandID.STEP_OVER == 38359
        assert CscapeCommandID.STEP_OUT == 38360
        assert CscapeCommandID.PROFILER == 38362
        assert CscapeCommandID.ENHANCED_IEC_DEBUG == 38411
        assert CscapeCommandID.SIMULATE_LOCAL == 32812
        assert CscapeCommandID.DEBUG_MONITOR == 32838
        assert CscapeCommandID.OFFLINE_MODE == 62660

    def test_simulation_commands_not_blocked(self):
        """Ensure simulation and debug command IDs are NOT in DEFAULT_BLOCKED_UI_COMMANDS."""
        simulation_ids = [
            CscapeCommandID.START_SIMULATION,
            CscapeCommandID.STOP_DEBUG_SIMULATION,
            CscapeCommandID.EXECUTE_SINGLE_CYCLE,
            CscapeCommandID.RESUME_CYCLE_MODE,
            CscapeCommandID.STEP_IN,
            CscapeCommandID.STEP_OVER,
            CscapeCommandID.STEP_OUT,
            CscapeCommandID.PROFILER,
        ]
        for cid in simulation_ids:
            assert cid not in DEFAULT_BLOCKED_UI_COMMANDS
            assert int(cid) not in DEFAULT_BLOCKED_UI_COMMANDS

    def test_download_commands_are_blocked(self):
        """Verify standard download command IDs are strictly included in DEFAULT_BLOCKED_UI_COMMANDS."""
        # 32827: ID_PLC_DOWNLOAD, 32828: ID_PLC_UPLOAD
        assert 32827 in DEFAULT_BLOCKED_UI_COMMANDS
        assert 32828 in DEFAULT_BLOCKED_UI_COMMANDS


# ============================================================================
# 2. Horner OCS Register Address Parsing Tests
# ============================================================================

class TestRegisterAddressParsing:
    """Tests parsing and validation of register strings."""

    def test_parse_valid_word_registers(self):
        """Parse valid %R, %AI, %AQ, %SR registers."""
        addr_r = parse_register_address("%R100")
        assert addr_r.reg_type == RegisterType.R
        assert addr_r.index == 100
        assert addr_r.canonical == "%R100"
        assert addr_r.is_word is True
        assert addr_r.is_bit is False

        addr_ai = parse_register_address("ai5")
        assert addr_ai.reg_type == RegisterType.AI
        assert addr_ai.index == 5
        assert addr_ai.canonical == "%AI5"

        addr_aq = parse_register_address("%AQ512")
        assert addr_aq.reg_type == RegisterType.AQ
        assert addr_aq.index == 512

        addr_sr = parse_register_address("%SR1")
        assert addr_sr.reg_type == RegisterType.SR
        assert addr_sr.index == 1

    def test_parse_valid_bit_registers(self):
        """Parse valid %I, %Q, %M, %T, %S discrete registers."""
        addr_i = parse_register_address("%I1")
        assert addr_i.reg_type == RegisterType.I
        assert addr_i.index == 1
        assert addr_i.canonical == "%I1"
        assert addr_i.is_bit is True
        assert addr_i.is_word is False

        addr_q = parse_register_address("%q2048")
        assert addr_q.reg_type == RegisterType.Q
        assert addr_q.index == 2048

        addr_m = parse_register_address("%M50")
        assert addr_m.reg_type == RegisterType.M
        assert addr_m.index == 50

        addr_s = parse_register_address("%S1")
        assert addr_s.reg_type == RegisterType.S
        assert addr_s.index == 1

        addr_d = parse_register_address("%D1")
        assert addr_d.reg_type == RegisterType.D
        assert addr_d.index == 1
        assert addr_d.canonical == "%D1"

        addr_k = parse_register_address("%K1024")
        assert addr_k.reg_type == RegisterType.K
        assert addr_k.index == 1024
        assert addr_k.canonical == "%K1024"

    def test_parse_bit_of_word(self):
        """Parse bit-of-word notation like %R100.0 or %R50.15."""
        addr = parse_register_address("%R100.3")
        assert addr.reg_type == RegisterType.R
        assert addr.index == 100
        assert addr.bit_offset == 3
        assert addr.canonical == "%R100.3"
        assert addr.is_bit is True
        assert addr.is_word is False

    def test_parse_invalid_registers(self):
        """Invalid register formats and out-of-bound indices must raise ValueError."""
        with pytest.raises(ValueError, match="Invalid Horner register format"):
            parse_register_address("INVALID")

        with pytest.raises(ValueError, match="Unknown Horner register type"):
            parse_register_address("%Z100")

        # Bounds checks
        with pytest.raises(ValueError, match="out of bounds"):
            parse_register_address("%R0")  # Index is 1-based

        with pytest.raises(ValueError, match="out of bounds"):
            parse_register_address("%R10000")  # Max is 9999

        with pytest.raises(ValueError, match="out of bounds"):
            parse_register_address("%I2049")  # Max is 2048

        with pytest.raises(ValueError, match="out of bounds"):
            parse_register_address("%S17")  # Max is 16

        with pytest.raises(ValueError, match="Bit offset .* out of bounds"):
            parse_register_address("%R1.16")  # 0 to 15 allowed

        with pytest.raises(ValueError, match="Cannot specify bit offset on discrete"):
            parse_register_address("%I1.2")


# ============================================================================
# 3. HornerRegisterTable Tests
# ============================================================================

class TestHornerRegisterTable:
    """Tests for HornerRegisterTable data operations."""

    def test_word_read_write_signed_and_unsigned(self):
        """Test reading and writing 16-bit word registers."""
        table = HornerRegisterTable()

        # Positive value
        table.write_word(RegisterType.R, 1, 1234)
        assert table.read_word(RegisterType.R, 1, signed=True) == 1234
        assert table.read_word(RegisterType.R, 1, signed=False) == 1234

        # Negative signed value (-500)
        table.write_word(RegisterType.R, 2, -500)
        assert table.read_word(RegisterType.R, 2, signed=True) == -500
        assert table.read_word(RegisterType.R, 2, signed=False) == 65536 - 500

        # Boundary values
        table.write_word(RegisterType.R, 3, 32767)
        assert table.read_word(RegisterType.R, 3, signed=True) == 32767

        table.write_word(RegisterType.R, 4, -32768)
        assert table.read_word(RegisterType.R, 4, signed=True) == -32768

    def test_discrete_bit_read_write(self):
        """Test reading and writing discrete boolean bits."""
        table = HornerRegisterTable()

        assert table.read_bit(RegisterType.I, 1) is False
        table.write_bit(RegisterType.I, 1, True)
        assert table.read_bit(RegisterType.I, 1) is True

        table.write_bit(RegisterType.Q, 10, True)
        assert table.read_bit(RegisterType.Q, 10) is True
        table.write_bit(RegisterType.Q, 10, False)
        assert table.read_bit(RegisterType.Q, 10) is False

        # Display and Keypad bits (%D, %K)
        table.write_bit(RegisterType.D, 1, True)
        assert table.read_bit(RegisterType.D, 1) is True
        table.write("%K5", True)
        assert table.read("%K5") is True
        assert table.read("%K6") is False

    def test_bit_of_word_read_write(self):
        """Test reading and writing individual bits of a 16-bit word register."""
        table = HornerRegisterTable()

        # Set word to 0x0005 (bits 0 and 2 set)
        table.write_word(RegisterType.R, 10, 0x0005)
        assert table.read_bit(RegisterType.R, 10, bit_offset=0) is True
        assert table.read_bit(RegisterType.R, 10, bit_offset=1) is False
        assert table.read_bit(RegisterType.R, 10, bit_offset=2) is True

        # Modify bit 1 to True via address string
        table.write("%R10.1", True)
        assert table.read("%R10.1") is True
        assert table.read_word(RegisterType.R, 10) == 0x0007

    def test_dint_32bit_read_write(self):
        """Test 32-bit signed DINT integer across two registers."""
        table = HornerRegisterTable()

        # Positive 32-bit integer
        table.write_dint("%R1", 1000000)
        assert table.read_dint("%R1") == 1000000

        # Negative 32-bit integer
        table.write_dint("%R10", -12345678)
        assert table.read_dint("%R10") == -12345678

    def test_real_float_read_write(self):
        """Test 32-bit IEEE 754 REAL floating-point across two registers."""
        table = HornerRegisterTable()

        table.write_real("%R1", 123.456)
        val = table.read_real("%R1")
        assert math.isclose(val, 123.456, rel_tol=1e-5)

        table.write_real("%R10", -0.0078125)
        val2 = table.read_real("%R10")
        assert math.isclose(val2, -0.0078125, rel_tol=1e-6)

    def test_range_operations(self):
        """Test reading and writing ranges of registers."""
        table = HornerRegisterTable()

        data = [10, 20, 30, 40, 50]
        table.write_range(RegisterType.R, start_idx=1, values=data)
        read_back = table.read_range(RegisterType.R, start_idx=1, count=5)
        assert read_back == data

    def test_system_registers_and_clock_bits(self):
        """Verify %S1 first scan pulse and clock wave generators."""
        table = HornerRegisterTable()

        # Cycle 0 (elapsed = 0ms)
        table.update_system_registers(cycle_index=0, dt_ms=10.0, elapsed_time_ms=0.0)
        assert table.read_bit(RegisterType.S, 1) is True  # %S1 first scan
        assert table.read_word(RegisterType.SR, 1) == 10  # %SR1 dt_ms
        assert table.read_word(RegisterType.SR, 2) == 1   # %SR2 mode
        assert table.read_word(RegisterType.SR, 3) == 0   # %SR3 scan low

        # Cycle 1 (elapsed = 10ms)
        table.update_system_registers(cycle_index=1, dt_ms=10.0, elapsed_time_ms=10.0)
        assert table.read_bit(RegisterType.S, 1) is False # %S1 cleared!
        assert table.read_bit(RegisterType.S, 7) is True  # %S7 10ms clock pulse active

        # Cycle 10 (elapsed = 100ms)
        table.update_system_registers(cycle_index=10, dt_ms=10.0, elapsed_time_ms=100.0)
        assert table.read_bit(RegisterType.S, 8) is True  # %S8 100ms clock pulse active

    def test_snapshot_and_restore(self):
        """Test serializing and restoring register snapshots."""
        table = HornerRegisterTable()
        table.write("%R1", 42)
        table.write("%I1", True)
        table.write("%Q5", True)

        snap = table.snapshot()
        assert snap["%R1"] == 42
        assert snap["%I1"] is True
        assert snap["%Q5"] is True

        table2 = HornerRegisterTable()
        table2.load_snapshot(snap)
        assert table2.read("%R1") == 42
        assert table2.read("%I1") is True
        assert table2.read("%Q5") is True


# ============================================================================
# 4. VariableRegisterMapping & AST Preprocessing Tests
# ============================================================================

class TestVariableRegisterMapping:
    """Tests for variable-to-register mapping and code sanitization."""

    def test_extract_and_sanitize_st(self):
        """Test extraction of AT %... directives and sanitization of ST code."""
        st_code = """
        PROGRAM ConveyorTest
        VAR
            bStart AT %I1 : BOOL := FALSE;
            bStop AT %I2 : BOOL := FALSE;
            bMotor AT %Q1 : BOOL := FALSE;
            nSpeed AT %R100 : INT := 1200;
        END_VAR
        IF bStart THEN
            bMotor := TRUE;
        END_IF;
        END_PROGRAM
        """
        mapping = VariableRegisterMapping()
        sanitized, bindings = mapping.extract_from_st(st_code)

        assert len(bindings) == 4
        assert mapping.get_binding("bStart").register_address.canonical == "%I1"
        assert mapping.get_binding("nSpeed").register_address.canonical == "%R100"

        # AT %... removed from sanitized code
        assert "AT %" not in sanitized
        assert "bStart : BOOL" in sanitized
        assert "nSpeed : INT" in sanitized

    def test_sync_bidirectional(self):
        """Test register <-> variable synchronization."""
        table = HornerRegisterTable()
        mapping = VariableRegisterMapping()

        mapping.bind("bStart", "%I1", "BOOL")
        mapping.bind("nSpeed", "%R100", "INT")
        mapping.bind("bRunning", "%Q1", "BOOL")

        # 1. Inputs: Register -> Variables
        table.write("%I1", True)
        table.write("%R100", 1500)
        var_ctx: dict = {}
        mapping.sync_registers_to_variables(table, var_ctx)
        assert var_ctx["bStart"] is True
        assert var_ctx["nSpeed"] == 1500

        # 2. Outputs: Variables -> Registers
        var_ctx["bRunning"] = True
        mapping.sync_variables_to_registers(table, var_ctx)
        assert table.read("%Q1") is True


# ============================================================================
# 5. CscapeSimulator Execution Tests
# ============================================================================

class TestCscapeSimulatorExecution:
    """Tests full cyclic simulation execution."""

    def test_conveyor_station_cycle_execution(self):
        """Simulate conveyor logic with latching start/stop buttons."""
        st_code = """
        PROGRAM ConveyorStation
        VAR
            bStart AT %I1 : BOOL := FALSE;
            bStop  AT %I2 : BOOL := FALSE;
            bMotor AT %Q1 : BOOL := FALSE;
            nSpeed AT %R100 : INT := 0;
        END_VAR

        IF bStart AND NOT bStop THEN
            bMotor := TRUE;
            nSpeed := 1750;
        ELSIF bStop THEN
            bMotor := FALSE;
            nSpeed := 0;
        END_IF;
        END_PROGRAM
        """
        sim = create_cscape_simulation(st_code=st_code)
        sim.start_simulation()

        # Cycle 0: initial state
        snap0 = sim.step_cycle()
        assert sim.read_bit("%Q1") is False
        assert sim.read_register("%R100") == 0
        assert snap0.system_bits["%S1"] is True  # %S1 is TRUE on scan 0

        # Cycle 1: Press Start
        sim.write_bit("%I1", True)
        snap1 = sim.step_cycle()
        assert sim.read_bit("%Q1") is True
        assert sim.read_register("%R100") == 1750
        assert snap1.system_bits["%S1"] is False # %S1 cleared

        # Cycle 2: Release Start (verify latching)
        sim.write_bit("%I1", False)
        sim.step_cycle()
        assert sim.read_bit("%Q1") is True
        assert sim.read_register("%R100") == 1750

        # Cycle 3: Press Stop
        sim.write_bit("%I2", True)
        sim.step_cycle()
        assert sim.read_bit("%Q1") is False
        assert sim.read_register("%R100") == 0

    def test_timer_and_analog_real_execution(self):
        """Simulate IEC TON timer and IEEE 754 REAL analog registers."""
        st_code = """
        PROGRAM AnalogTimerStation
        VAR
            bTrigger AT %I1 : BOOL := FALSE;
            fTemp    AT %R101 : REAL := 25.0;
            tDelay   : TON;
            bDone    AT %Q1 : BOOL := FALSE;
        END_VAR

        fTemp := fTemp + 1.0;
        tDelay(IN := bTrigger, PT := T#40ms);
        bDone := tDelay.Q;
        END_PROGRAM
        """
        sim = create_cscape_simulation(st_code=st_code, default_dt_ms=10.0)
        sim.start_simulation()

        sim.write_real("%R101", 20.0)
        sim.write_bit("%I1", True)

        # Run 5 cycles (50ms)
        snaps = sim.run_cycles(cycles=5, dt_ms=10.0)
        assert len(snaps) == 5

        # Timer should have expired (>= 40ms)
        assert sim.read_bit("%Q1") is True
        # Temperature incremented by 1.0 each cycle: 20 + 5 = 25.0
        assert math.isclose(sim.read_real("%R101"), 25.0, rel_tol=1e-4)

    def test_run_until_condition(self):
        """Test run_until terminates when specified condition is met."""
        st_code = """
        PROGRAM LoopCounter
        VAR
            nCount AT %R1 : INT := 0;
        END_VAR
        nCount := nCount + 2;
        END_PROGRAM
        """
        sim = create_cscape_simulation(st_code=st_code)
        sim.start_simulation()

        sim.run_until(lambda s: s.read_register("%R1") >= 20, max_cycles=50)
        assert sim.read_register("%R1") == 20
        assert sim.cycle_count == 10

    def test_breakpoint_pauses_simulation(self):
        """Test breakpoints pause cycle execution."""
        st_code = """
        PROGRAM BPTest
        VAR
            nVal AT %R5 : INT := 0;
        END_VAR
        nVal := nVal + 1;
        END_PROGRAM
        """
        sim = create_cscape_simulation(st_code=st_code)
        sim.start_simulation()

        # Pause when nVal == 3
        sim.add_breakpoint(lambda s: s.read_register("%R5") == 3)
        sim.run_cycles(cycles=10)

        assert sim.state == SimulationState.PAUSED
        assert sim.read_register("%R5") == 3
        assert sim.cycle_count == 3

    def test_pure_register_mode(self):
        """Test simulation operates in pure register mode without ST program."""
        sim = CscapeSimulator()
        sim.start_simulation()

        sim.write_register("%R1", 99)
        sim.write_bit("%I1", True)
        snap = sim.step_cycle()

        assert sim.read_register("%R1") == 99
        assert sim.read_bit("%I1") is True
        assert snap.system_bits["%S1"] is True

    def test_status_telemetry(self):
        """Test status dictionary output."""
        sim = CscapeSimulator()
        status = sim.get_status()

        assert status["state"] == "IDLE"
        assert status["software_isolation_enforced"] is True
        assert status["pure_software_execution"] is True
        assert "system_clocks" in status
        assert "cscape_ui_commands" in status


# ============================================================================
# 6. 100% Software Isolation & Hardware Lockout Tests
# ============================================================================

class TestSoftwareIsolation:
    """Tests enforcing zero-hardware, zero-download, simulation-only constraints."""

    def test_hardware_port_connection_blocked(self):
        """Attempting to connect to COM/CAN/USB ports must raise HardwareLockoutError."""
        sim = CscapeSimulator()

        with pytest.raises(HardwareLockoutError, match="Hardware communication port 'COM1' is strictly blocked"):
            sim.connect_hardware("COM1")

        with pytest.raises(HardwareLockoutError, match="Hardware communication port 'CAN0' is strictly blocked"):
            sim.connect_hardware("CAN0")

        with pytest.raises(HardwareLockoutError, match="Hardware communication port 'USB0' is strictly blocked"):
            sim.connect_hardware("USB0")

    def test_download_to_controller_blocked(self):
        """Attempting to download logic or flash hardware must raise UnauthorizedDownloadError."""
        sim = CscapeSimulator()

        with pytest.raises(UnauthorizedDownloadError, match="prohibited"):
            sim.download_to_controller()

    def test_enforce_software_isolation_helper(self):
        """Direct tests of enforce_software_isolation() validation."""
        # Allowed simulation targets
        enforce_software_isolation("T5SIMUL")
        enforce_software_isolation()

        # Blocked physical ports
        with pytest.raises(HardwareLockoutError):
            enforce_software_isolation("COM3")

        with pytest.raises(HardwareLockoutError):
            enforce_software_isolation("/dev/ttyS0")

        # Blocked commands & flags
        with pytest.raises(UnauthorizedDownloadError):
            enforce_software_isolation("download")

        with pytest.raises(UnauthorizedDownloadError):
            enforce_software_isolation("--download")

        with pytest.raises(UnauthorizedDownloadError):
            enforce_software_isolation("/flash")


# ============================================================================
# 7. Pure-Software Execution, Horner %S Clocks & Timer/Counter Tests
# ============================================================================

class TestPureSoftwareExecutionAndSystemClocks:
    """Tests for pure-software scan cycle execution, Horner %S clocks, and purged bridge."""

    def test_k5netsim_bridge_purged(self):
        """Verify dead K5NETSim.dll bridge references have been purged."""
        import src.cscape.simulation as csim
        assert not hasattr(csim, "K5NETSimBridge")
        assert not hasattr(csim, "K5NETSimInfo")
        assert not hasattr(csim, "DEFAULT_K5NETSIM_PATH")
        assert "K5NETSIM" not in [b.value for b in SimulationBackend]

        # Simulator backend defaults to EMULATED
        sim = CscapeSimulator()
        assert sim.backend == SimulationBackend.EMULATED
        assert not hasattr(sim, "k5_bridge")

    def test_horner_s1_first_scan_pulse_in_st_logic(self):
        """Verify Horner %S1 first-scan pulse activates exclusively on cycle 0 in ST logic."""
        st_code = """
        PROGRAM FirstScanTest
        VAR
            bInitPulse AT %S1 : BOOL;
            bInitialized : BOOL := FALSE;
            nScanCounter : INT := 0;
        END_VAR

        IF bInitPulse THEN
            bInitialized := TRUE;
        END_IF;
        nScanCounter := nScanCounter + 1;
        END_PROGRAM
        """
        sim = create_cscape_simulation(st_code=st_code)
        sim.start_simulation()

        # Cycle 0 (first scan): %S1 is True, bInitPulse is True
        snap0 = sim.step_cycle()
        assert snap0.system_bits["%S1"] is True
        assert sim.read_variable("bInitialized") is True
        assert sim.read_variable("nScanCounter") == 1

        # Cycle 1 (second scan): %S1 is False, bInitPulse is False
        snap1 = sim.step_cycle()
        assert snap1.system_bits["%S1"] is False
        assert sim.read_variable("bInitPulse") is False
        assert sim.read_variable("bInitialized") is True
        assert sim.read_variable("nScanCounter") == 2

        # Cycle 2: %S1 remains False
        snap2 = sim.step_cycle()
        assert snap2.system_bits["%S1"] is False
        assert sim.read_variable("nScanCounter") == 3

    def test_horner_direct_s1_reference_in_st(self):
        """Verify direct %S1 register reference in ST logic executes correctly on scan 0."""
        st_code = """
        PROGRAM DirectS1Test
        VAR
            nInitialValue AT %R50 : INT := 0;
        END_VAR

        IF %S1 THEN
            nInitialValue := 999;
        END_IF;
        END_PROGRAM
        """
        sim = create_cscape_simulation(st_code=st_code)
        sim.start_simulation()

        # Cycle 0
        sim.step_cycle()
        assert sim.read_register("%R50") == 999

        # Cycle 1: %S1 is False, value remains 999
        sim.step_cycle()
        assert sim.read_register("%R50") == 999

    def test_horner_s7_10ms_clock_square_wave(self):
        """Verify %S7 10ms system clock square wave (period 20ms: 10ms high, 10ms low)."""
        sim = CscapeSimulator(default_dt_ms=10.0)
        sim.start_simulation()

        # Cycle 0 (0ms): False
        snap0 = sim.step_cycle(dt_ms=10.0)
        assert snap0.system_bits["%S7"] is False
        assert sim.read_bit("%S7") is False

        # Cycle 1 (10ms): True
        snap1 = sim.step_cycle(dt_ms=10.0)
        assert snap1.system_bits["%S7"] is True
        assert sim.read_bit("%S7") is True

        # Cycle 2 (20ms): False
        snap2 = sim.step_cycle(dt_ms=10.0)
        assert snap2.system_bits["%S7"] is False
        assert sim.read_bit("%S7") is False

        # Cycle 3 (30ms): True
        snap3 = sim.step_cycle(dt_ms=10.0)
        assert snap3.system_bits["%S7"] is True
        assert sim.read_bit("%S7") is True

    def test_horner_s8_100ms_clock_square_wave(self):
        """Verify %S8 100ms system clock square wave (period 200ms: 100ms high, 100ms low)."""
        sim = CscapeSimulator(default_dt_ms=50.0)
        sim.start_simulation()

        # 0ms: False
        snap0 = sim.step_cycle(dt_ms=50.0)
        assert snap0.system_bits["%S8"] is False

        # 50ms: False
        snap1 = sim.step_cycle(dt_ms=50.0)
        assert snap1.system_bits["%S8"] is False

        # 100ms: True
        snap2 = sim.step_cycle(dt_ms=50.0)
        assert snap2.system_bits["%S8"] is True

        # 150ms: True
        snap3 = sim.step_cycle(dt_ms=50.0)
        assert snap3.system_bits["%S8"] is True

        # 200ms: False
        snap4 = sim.step_cycle(dt_ms=50.0)
        assert snap4.system_bits["%S8"] is False

    def test_horner_s9_1s_clock_square_wave(self):
        """Verify %S9 1000ms system clock square wave (period 2000ms: 1s high, 1s low)."""
        sim = CscapeSimulator(default_dt_ms=500.0)
        sim.start_simulation()

        # 0ms: False
        snap0 = sim.step_cycle(dt_ms=500.0)
        assert snap0.system_bits["%S9"] is False

        # 500ms: False
        snap1 = sim.step_cycle(dt_ms=500.0)
        assert snap1.system_bits["%S9"] is False

        # 1000ms: True
        snap2 = sim.step_cycle(dt_ms=500.0)
        assert snap2.system_bits["%S9"] is True

        # 1500ms: True
        snap3 = sim.step_cycle(dt_ms=500.0)
        assert snap3.system_bits["%S9"] is True

        # 2000ms: False
        snap4 = sim.step_cycle(dt_ms=500.0)
        assert snap4.system_bits["%S9"] is False

    def test_horner_system_registers_sr1_to_sr4(self):
        """Verify Horner OCS system registers %SR1 (dt), %SR2 (mode), %SR3/4 (scan counter)."""
        table = HornerRegisterTable()

        # Cycle 0 with dt = 25ms
        table.update_system_registers(cycle_index=0, dt_ms=25.0, elapsed_time_ms=0.0)
        assert table.read_word(RegisterType.SR, 1) == 25   # %SR1 scan duration
        assert table.read_word(RegisterType.SR, 2) == 1    # %SR2 operating mode (1 = RUN)
        assert table.read_word(RegisterType.SR, 3) == 0    # %SR3 scan low word
        assert table.read_word(RegisterType.SR, 4) == 0    # %SR4 scan high word

        # Cycle 70000 with dt = 15ms (overflows 16 bits into high word)
        table.update_system_registers(cycle_index=70000, dt_ms=15.0, elapsed_time_ms=1050000.0)
        assert table.read_word(RegisterType.SR, 1) == 15
        assert table.read_word(RegisterType.SR, 3) == 70000 & 0xFFFF
        assert table.read_word(RegisterType.SR, 4) == (70000 >> 16) & 0xFFFF

    def test_horner_system_clocks_read_only_protection(self):
        """Verify user program logic cannot overwrite system clocks %S or %SR."""
        st_code = """
        PROGRAM ProtectClocks
        VAR
            bFirst AT %S1 : BOOL;
        END_VAR

        // Attempt to maliciously or accidentally clear %S1
        bFirst := FALSE;
        END_PROGRAM
        """
        sim = create_cscape_simulation(st_code=st_code)
        sim.start_simulation()

        # On cycle 0, %S1 must remain True despite assignment
        snap = sim.step_cycle()
        assert snap.system_bits["%S1"] is True
        assert sim.read_bit("%S1") is True

    def test_timers_and_counters_scan_integration(self):
        """Verify pure-software execution of TON timer and CTU counter with Horner registers."""
        st_code = """
        PROGRAM BatchProcess
        VAR
            bRun AT %I1 : BOOL := FALSE;
            bCountPulse AT %I2 : BOOL := FALSE;
            bResetCounter AT %I3 : BOOL := FALSE;
            bBatchDone AT %Q1 : BOOL := FALSE;
            nBatchCount AT %R10 : INT := 0;
            delayTimer : TON;
            batchCounter : CTU;
        END_VAR

        delayTimer(IN := bRun, PT := T#30ms);
        batchCounter(CU := bCountPulse, RESET := bResetCounter, PV := 2);
        nBatchCount := batchCounter.CV;
        bBatchDone := delayTimer.Q AND batchCounter.Q;
        END_PROGRAM
        """
        sim = create_cscape_simulation(st_code=st_code, default_dt_ms=10.0)
        sim.start_simulation()

        # Step 1 (10ms): Turn on bRun, pulse bCountPulse
        sim.write_bit("%I1", True)
        sim.write_bit("%I2", True)
        sim.step_cycle()
        assert sim.read_register("%R10") == 1
        assert sim.read_bit("%Q1") is False

        # Step 2 (20ms): bCountPulse drops
        sim.write_bit("%I2", False)
        sim.step_cycle()
        assert sim.read_register("%R10") == 1
        assert sim.read_bit("%Q1") is False

        # Step 3 (30ms): bCountPulse rising edge 2 -> reaches PV=2, delayTimer reaches 30ms -> Q1 TRUE
        sim.write_bit("%I2", True)
        sim.step_cycle()
        assert sim.read_register("%R10") == 2
        assert sim.read_bit("%Q1") is True


# ============================================================================
# 8. CscapeUIAutomationController Tests
# ============================================================================

class TestCscapeUIAutomationController:
    """Tests for UI command dispatch and safety auditing."""

    def test_simulation_ui_commands_allowed(self):
        """Simulation commands pass safety audit."""
        ctrl = CscapeUIAutomationController()
        assert ctrl.start_simulation() is True
        assert ctrl.execute_single_cycle() is True
        assert ctrl.resume_cycle_mode() is True
        assert ctrl.stop_simulation() is True

    def test_download_ui_command_raises(self):
        """Download UI command IDs raise UnauthorizedDownloadError."""
        ctrl = CscapeUIAutomationController()
        with pytest.raises(UnauthorizedDownloadError):
            ctrl.trigger_command(32827)  # ID_PLC_DOWNLOAD


# ============================================================================
# 9. High-Level Facade Function Tests
# ============================================================================

class TestHighLevelFacade:
    """Tests for top-level helper functions."""

    def test_simulate_pou_with_registers(self):
        """Test simulate_pou_with_registers helper function."""
        st_code = """
        PROGRAM PumpStation
        VAR
            bRun AT %I1 : BOOL := FALSE;
            bPump AT %Q1 : BOOL := FALSE;
        END_VAR
        bPump := bRun;
        END_PROGRAM
        """
        res = simulate_pou_with_registers(
            st_code=st_code,
            inputs={"bRun": [False, True, True]},
            steps=3,
        )

        assert res["success"] is True
        assert res["total_cycles"] == 3
        assert res["isolation_enforced"] is True
        assert len(res["trace"]) == 3
        assert res["trace"][0]["registers"].get("%Q1", False) is False
        assert res["trace"][1]["registers"].get("%Q1") is True


class TestCscapeSimulationNegativeAndMockContracts:
    """Negative and mock rigor contract tests for pure-software simulation."""

    def test_simulation_taxonomy_declarations(self):
        """Mandate: Cscape simulation module explicitly declares TESTED_MOCK [offline/DEV only]."""
        expected = "TESTED_MOCK [offline/DEV only]"
        assert CLASSIFICATION == expected
        assert VERIFICATION_CLASSIFICATION == expected

    def test_verified_live_mode_prohibited_fail_closed(self):
        """Mandate: Requesting mode='VERIFIED_LIVE' on simulation fails closed."""
        code = "PROGRAM Simple\nVAR x:INT; END_VAR\nx := 1;\nEND_PROGRAM"
        for bad_mode in ["VERIFIED_LIVE", "LIVE", "verified_live"]:
            with pytest.raises(ValueError) as exc:
                simulate_pou_with_registers(st_code=code, inputs={}, mode=bad_mode)
            assert "ERR_VERIFIED_LIVE_PROHIBITED_ON_SIMULATION" in str(exc.value)

            with pytest.raises(ValueError) as exc_sim:
                CscapeSimulator(mode=bad_mode)
            assert "ERR_VERIFIED_LIVE_PROHIBITED_ON_SIMULATION" in str(exc_sim.value)

    def test_simulate_pou_ladder_rejection_fail_closed(self):
        """Mandate: Ladder logic in simulate_pou_with_registers fails closed with ERR_LADDER_FORBIDDEN."""
        ladder_code = "PROGRAM Bad\nVAR x:BOOL; END_VAR\n---( )---\nEND_PROGRAM"
        with pytest.raises(ValueError) as exc:
            simulate_pou_with_registers(st_code=ladder_code, inputs={})
        assert "ERR_LADDER_FORBIDDEN" in str(exc.value)

    def test_load_program_ladder_rejection_fail_closed(self):
        """Mandate: Ladder logic in CscapeSimulator.load_program fails closed with ERR_LADDER_FORBIDDEN."""
        sim = CscapeSimulator()
        ladder_code = "PROGRAM Bad\nVAR x:BOOL; END_VAR\n---[ ]---\nEND_PROGRAM"
        with pytest.raises(ValueError) as exc:
            sim.load_program(ladder_code)
        assert "ERR_LADDER_FORBIDDEN" in str(exc.value)

    def test_simulate_pou_syntax_error_fail_closed(self):
        """Mandate: Syntax error in simulate_pou_with_registers fails closed with ST_SYNTAX_ERROR."""
        broken_code = "PROGRAM Broken\nVAR x:INT; END_VAR\nIF THEN END_PROGRAM"
        with pytest.raises(ValueError) as exc:
            simulate_pou_with_registers(st_code=broken_code, inputs={})
        assert "ST_SYNTAX_ERROR" in str(exc.value)

    def test_load_program_syntax_error_fail_closed(self):
        """Mandate: Syntax error in CscapeSimulator.load_program fails closed with ST_SYNTAX_ERROR."""
        sim = CscapeSimulator()
        broken_code = "PROGRAM Broken\nVAR x:INT; END_VAR\nx := ;;\nEND_PROGRAM"
        with pytest.raises(ValueError) as exc:
            sim.load_program(broken_code)
        assert "ST_SYNTAX_ERROR" in str(exc.value)

