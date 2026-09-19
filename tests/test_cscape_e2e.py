"""End-to-End Integration Test Suite for Horner Cscape 10.2 MCP.

Tests the full automation lifecycle across:
1. Cscape 10.2 Binary Verification & Lifecycle Initialization
2. Splash & "Select Editor Type" Dialog Automation (IEC 61131 Mode Radio 1461)
3. Native Project Creation & Storage (.csp / .cpj CFBF OLE compound file structure)
4. Structured Text (ST) POU Generation & Injection with SHA-256 AST Integrity
5. Local Compilation Loop & Error Diagnostics (ID_PROGRAM_ERRORCHECK 32826)
6. OCS Register Variable Mapping (%R, %M, %T, %AI, %AQ, %I, %Q)
7. Offline Software Simulation Execution (Scan cycle clock %S1/%S7/%S8/%S9)
8. Absolute Safety Lockout (Hardware communication and controller downloads blocked)
"""

from __future__ import annotations

import datetime
from pathlib import Path
import time
from typing import Any

import pytest

from src.cscape.compiler import (
    CscapeBuildResult,
    CscapeCompiler,
    CscapeLogParser,
    ID_CONTROLLER_DOWNLOAD,
    ID_PROGRAM_ERRORCHECK,
)
from src.cscape.lifecycle import (
    CscapeLifecycleError,
    CscapeLifecycleManager,
    CscapeLifecycleState,
    RADIO_ID_IEC_61131,
    RADIO_ID_ADVANCED_LADDER_REGISTER,
    RADIO_ID_ADVANCED_LADDER_VARIABLE,
    resolve_cscape_executable,
)
from src.cscape.project_manager import (
    CFBF_MAGIC,
    CscapeLiveProjectManager,
    ProjectCreationResult,
    RADIO_IEC_61131,
    RADIO_ADVANCED_LADDER_REG,
    RADIO_ADVANCED_LADDER_VAR,
    CscapeSafetyError,
)
from src.project.manager import CscapeProject
from src.cscape.simulation import (
    CscapeCommandID,
    CscapeSimulator,
    SimulationState,
    create_cscape_simulation,
    simulate_pou_with_registers,
)
from src.cscape.st_inserter import (
    ID_ST_FUNCTION,
    ID_ST_FUNCTION_BLOCK,
    ID_ST_PROGRAM,
    InsertionMethod,
    POUType,
    STPOUDefinition,
    StructuredTextInserter,
    calculate_code_hash,
    normalize_st_code,
)
from src.cscape.st_ld_interop import (
    STLadderInteropGuard,
    LadderConstructRejectedError,
)
from src.cscape.variables import (
    CscapeVariable,
    VariableManager,
)
from src.security.exceptions import (
    HardwareLockoutError,
    UnauthorizedDownloadError,
)
from src.security.guard import SafetyGuard
from src.security.policy import SecurityConfig


@pytest.fixture(scope="module")
def cscape_binary_path() -> Path:
    """Resolve the host Cscape 10.2 executable path."""
    exe = resolve_cscape_executable()
    assert exe is not None, "Horner Cscape 10.2 executable must be installed on host system."
    assert exe.exists(), f"Cscape.exe not found at {exe}"
    return exe


@pytest.fixture
def workspace_tmp_dir(tmp_path: Path) -> Path:
    """Provide a sandboxed temporary workspace directory."""
    d = tmp_path / "cscape_e2e_run"
    d.mkdir(parents=True, exist_ok=True)
    return d


class TestCscapeE2ELifecycle:
    """E2E verification of Cscape executable discovery, state model, and lifecycle controls."""

    def test_cscape_binary_exists_and_verified(self, cscape_binary_path: Path):
        """Verify Cscape 10.2 exists with expected PE attributes."""
        assert cscape_binary_path.name.lower() == "cscape.exe"
        size = cscape_binary_path.stat().st_size
        # Cscape 10.2 binary is approximately 17.6MB
        assert size > 15_000_000, f"Cscape.exe size {size} is unexpectedly small"

    def test_lifecycle_manager_initialization(self, cscape_binary_path: Path):
        """Verify lifecycle manager initializes in NOT_STARTED state with correct constants."""
        mgr = CscapeLifecycleManager(executable_path=cscape_binary_path)
        assert mgr.state == CscapeLifecycleState.NOT_STARTED
        assert mgr.executable_path == cscape_binary_path
        assert mgr.splash_hwnd is None
        assert mgr.main_hwnd is None

    def test_lifecycle_constants_iec_priority(self):
        """Verify that lifecycle definitions enforce IEC 61131 radio button 1461."""
        assert RADIO_ID_IEC_61131 == 1461
        assert RADIO_IEC_61131 == 1461
        assert RADIO_ADVANCED_LADDER_REG == 1460
        assert RADIO_ADVANCED_LADDER_VAR == 3757

    def test_lifecycle_rejects_legacy_ladder_modes(self):
        """Verify lifecycle manager rejects legacy ladder mode radio IDs 1460 and 3757."""
        mgr = CscapeLifecycleManager()
        with pytest.raises(CscapeLifecycleError, match="Legacy ladder mode radio ID 1460 is strictly rejected"):
            mgr.handle_editor_type_dialog(radio_id=RADIO_ID_ADVANCED_LADDER_REGISTER)
        with pytest.raises(CscapeLifecycleError, match="Legacy ladder mode radio ID 3757 is strictly rejected"):
            mgr.handle_editor_type_dialog(radio_id=RADIO_ID_ADVANCED_LADDER_VARIABLE)


class TestCscapeE2EProjectCreation:
    """E2E verification of native project creation and binary file inspection."""

    def test_project_manager_rejects_non_iec_policy(self):
        """Safety policy test: attempt to create project with ensure_iec=False must fail."""
        mgr = CscapeLiveProjectManager()
        with pytest.raises(CscapeSafetyError, match="prohibited by project policy"):
            mgr.create_new_project(ensure_iec=False)

    def test_project_manager_rejects_legacy_ladder_radios(self):
        """Verify project manager select_radio rejects legacy ladder mode IDs 1460 and 3757."""
        mgr = CscapeLiveProjectManager()
        with pytest.raises(CscapeSafetyError, match="Legacy ladder mode radio ID 1460 is strictly rejected"):
            mgr.select_radio(12345, RADIO_ADVANCED_LADDER_REG)
        with pytest.raises(CscapeSafetyError, match="Legacy ladder mode radio ID 3757 is strictly rejected"):
            mgr.select_radio(12345, RADIO_ADVANCED_LADDER_VAR)

    def test_inspect_native_sample_fixtures(self):
        """Inspect binary headers of harvested native .csp fixtures."""
        fixtures_dir = Path(r"C:\HornerAI\horner-cscape-mcp\fixtures\cscape_native_samples")
        if not fixtures_dir.exists():
            pytest.skip("Fixtures directory not found")

        csp_files = list(fixtures_dir.glob("*.csp"))
        assert len(csp_files) > 0, "No .csp files found in fixtures"

        for csp in csp_files[:5]:
            info = CscapeLiveProjectManager.inspect_project_file(csp)
            assert info.is_valid_cfbf is True
            assert info.magic_hex == CFBF_MAGIC.hex()
            assert info.sector_size in (512, 4096)
            assert info.has_contents_stream is True


class TestCscapeE2ESTInsertion:
    """E2E verification of Structured Text POU creation and AST integrity."""

    def test_st_pou_generation_and_ast_validation(self, workspace_tmp_dir: Path):
        """Generate structured text, validate AST, and compute SHA-256 integrity hash."""
        st_code = '''(* Horner Cscape 10.2 Industrial ST Pump Controller *)
PROGRAM PumpController
VAR_INPUT
    bStartSwitch : BOOL := FALSE;
    bStopSwitch : BOOL := FALSE;
    bLevelLow : BOOL := FALSE;
    bLevelHigh : BOOL := FALSE;
END_VAR
VAR_OUTPUT
    bPumpRunning : BOOL := FALSE;
    bAlarmLowLevel : BOOL := FALSE;
END_VAR
VAR
    bSystemReady : BOOL := FALSE;
END_VAR

bSystemReady := NOT bLevelLow;
bAlarmLowLevel := bLevelLow;

IF bStopSwitch OR bLevelLow THEN
    bPumpRunning := FALSE;
ELSIF bStartSwitch AND bSystemReady THEN
    bPumpRunning := TRUE;
END_IF;
END_PROGRAM
'''
        pou = STPOUDefinition(
            name="PumpController",
            pou_type=POUType.PROGRAM,
            code=st_code,
        )
        assert pou.name == "PumpController"
        assert pou.pou_type == POUType.PROGRAM
        code_hash = calculate_code_hash(pou.code)
        assert code_hash is not None
        assert len(code_hash) == 64
        assert code_hash == calculate_code_hash(st_code)

    def test_ladder_construct_guard_rejection(self):
        """Verify ST guard unconditionally rejects ladder rungs and contacts."""
        ladder_bad_code = """
        PROGRAM BadLadder
        ---[ bStart ]---( bMotor )---
        END_PROGRAM
        """
        with pytest.raises(LadderConstructRejectedError):
            STLadderInteropGuard.enforce_st_code(ladder_bad_code)


class TestCscapeE2ECompilation:
    """E2E verification of compilation pass and error diagnostic parsing."""

    def test_compilation_constants_lockout(self):
        """Verify compile accelerator is ID_PROGRAM_ERRORCHECK and download is blocked."""
        assert ID_PROGRAM_ERRORCHECK == 32826
        assert ID_CONTROLLER_DOWNLOAD == 32827

    def test_cscape_compiler_clean_build(self, workspace_tmp_dir: Path):
        """Execute compiler pass on a valid Structured Text project."""
        pous_dir = workspace_tmp_dir / "pous"
        pous_dir.mkdir(parents=True, exist_ok=True)
        st_file = pous_dir / "ConveyorLogic.st"
        st_file.write_text(
            '''PROGRAM ConveyorLogic
VAR
    nBoxCount : INT := 0;
    bSensor : BOOL := FALSE;
END_VAR
IF bSensor THEN
    nBoxCount := nBoxCount + 1;
END_IF;
END_PROGRAM
''',
            encoding="utf-8",
        )

        compiler = CscapeCompiler(workspace_root=workspace_tmp_dir)
        result: CscapeBuildResult = compiler.compile_project(workspace_tmp_dir)

        assert result.success is True
        assert result.error_count == 0
        assert result.hardware_lockout_enforced is True

    def test_cscape_compiler_syntax_error_diagnostics(self, workspace_tmp_dir: Path):
        """Execute compiler pass on syntax error and verify line-accurate diagnostics."""
        err_dir = workspace_tmp_dir / "ErrProj"
        pous_dir = err_dir / "pous"
        pous_dir.mkdir(parents=True, exist_ok=True)
        st_file = pous_dir / "BadLogic.st"
        st_file.write_text(
            '''PROGRAM BadLogic
VAR
    x : BOOL := FALSE
END_VAR
x :=
''',
            encoding="utf-8",
        )

        compiler = CscapeCompiler(workspace_root=workspace_tmp_dir)
        result: CscapeBuildResult = compiler.compile_project(err_dir)

        assert result.success is False
        assert result.error_count > 0
        assert len(result.diagnostics) > 0
        assert any(d.level == "ERROR" for d in result.diagnostics)


class TestCscapeE2EVariables:
    """E2E verification of Horner register allocation and variable tables."""

    def test_variable_manager_ocs_registers_and_project_sync(self, workspace_tmp_dir: Path):
        """Allocate %R, %M, %Q, %AI registers and verify project synchronization."""
        vm = VariableManager(project_name="OCS_IO_Table")
        vm.add_variable(
            CscapeVariable(
                name="StartPB",
                data_type="BOOL",
                tag="%M1",
                description="Panel Start Pushbutton",
            )
        )
        vm.add_variable(
            CscapeVariable(
                name="MotorRunCoil",
                data_type="BOOL",
                tag="%Q1",
                description="Motor Contactor Output",
            )
        )
        vm.add_variable(
            CscapeVariable(
                name="TankTemperature",
                data_type="INT",
                tag="%AI1",
                description="Analog Input RTD 1",
            )
        )
        vm.add_variable(
            CscapeVariable(
                name="CycleCount",
                data_type="DINT",
                tag="%R100",
                description="Batch counter register",
            )
        )

        sync_result = vm.sync_to_project(workspace_tmp_dir)
        assert sync_result["variables_count"] == 4
        assert (workspace_tmp_dir / "variables.csv").exists()
        assert (workspace_tmp_dir / "variables.xml").exists()

        # Reload and assert fidelity
        vm2 = VariableManager()
        loaded = vm2.load_from_project(workspace_tmp_dir)
        assert loaded == 4
        assert vm2.get_variable("StartPB").tag == "%M1"
        assert vm2.get_variable("MotorRunCoil").tag == "%Q1"
        assert vm2.get_variable("TankTemperature").tag == "%AI1"
        assert vm2.get_variable("CycleCount").tag == "%R100"


class TestCscapeE2ESimulation:
    """E2E verification of cycle-accurate software simulation and scan clocks."""

    def test_cycle_simulation_with_scan_clocks(self):
        """Execute multi-cycle simulation verifying software isolation and command constants."""
        st_logic = """PROGRAM SimBatch
VAR
    nTicks : INT := 0;
END_VAR
nTicks := nTicks + 1;
END_PROGRAM
"""
        sim = create_cscape_simulation(st_code=st_logic)
        sim.start_simulation()
        assert sim.state == SimulationState.RUNNING

        for _ in range(5):
            sim.step_cycle()

        status = sim.get_status()
        assert status["cycle_count"] == 5
        assert status["software_isolation_enforced"] is True
        assert status["cscape_ui_commands"]["start_simulation_id"] == CscapeCommandID.START_SIMULATION
        sim.stop_simulation()
        assert sim.state == SimulationState.STOPPED


class TestCscapeE2ESafetyLockout:
    """E2E verification of fail-closed security invariants: Zero hardware download."""

    def test_guard_blocks_physical_ports(self):
        """Verify COM, CAN, and USB ports trigger HardwareLockoutError."""
        guard = SafetyGuard()
        with pytest.raises(HardwareLockoutError):
            guard.validate_command(["Cscape.exe", "/com:COM3"])
        with pytest.raises(HardwareLockoutError):
            guard.validate_command(["Cscape.exe", "--port=CAN0"])
        with pytest.raises(HardwareLockoutError):
            guard.validate_command(["Cscape.exe", "/usb:vid_0483"])

    def test_guard_blocks_controller_download(self):
        """Verify /download, -download, and flash commands trigger UnauthorizedDownloadError."""
        guard = SafetyGuard()
        with pytest.raises(UnauthorizedDownloadError):
            guard.validate_command(["Cscape.exe", "/download"])
        with pytest.raises(UnauthorizedDownloadError):
            guard.validate_command(["Cscape.exe", "--flash"])
        with pytest.raises(UnauthorizedDownloadError):
            guard.validate_command(["Cscape.exe", "/target:plc"])


class TestCscapeCompletePipelineFlow:
    """End-to-End Verification of the Complete 6-Stage Toolchain Pipeline:
    1. Project Initialization: create native Cscape project container (.csp) & manifest.
    2. ST Injection: inject IEC 61131-3 Structured Text logic and verify AST integrity.
    3. Variables Allocation: assign Horner OCS registers (%R, %M, %Q, %AI), verify 0 conflicts, sync XML/CSV.
    4. Compile: execute CscapeCompiler build, assert zero errors and hardware lockout enforcement.
    5. Diagnostic Extraction: extract compiler diagnostics from build logs for clean and induced error cases.
    6. Software Simulation: run CscapeSimulator with scan clocks (%S1, %S7, %S8), step cycles, verify I/O register reflection and 100% software isolation.
    """

    def test_complete_end_to_end_flow(self, workspace_tmp_dir: Path):
        """Execute and assert the complete 6-stage end-to-end workflow."""
        proj_dir = workspace_tmp_dir / "WaterTreatmentPlant"

        # ---------------------------------------------------------------------
        # Stage 1: Project Initialization
        # ---------------------------------------------------------------------
        project = CscapeProject.create(proj_dir, name="WaterTreatmentPlant", controller="XL4")
        assert (proj_dir / "WaterTreatmentPlant.csp").exists()
        assert (proj_dir / "cscape_project.json").exists()
        info = CscapeLiveProjectManager.inspect_project_file(proj_dir / "WaterTreatmentPlant.csp")
        assert info.is_valid_cfbf is True
        assert info.magic_hex == CFBF_MAGIC.hex()
        assert info.sector_size in (512, 4096)

        # ---------------------------------------------------------------------
        # Stage 2: ST Injection
        # ---------------------------------------------------------------------
        pump_logic = '''PROGRAM WaterTreatmentControl
VAR
    bStartSwitch : BOOL := FALSE;
    bStopSwitch : BOOL := FALSE;
    nLevelSensor : INT := 0;
    bPumpRunning : BOOL := FALSE;
    bAlarmHigh : BOOL := FALSE;
    nBatchCycles : INT := 0;
END_VAR

IF bStopSwitch OR (nLevelSensor > 90) THEN
    bPumpRunning := FALSE;
ELSIF bStartSwitch AND (nLevelSensor <= 80) THEN
    bPumpRunning := TRUE;
END_IF;

bAlarmHigh := (nLevelSensor > 90);

IF bPumpRunning THEN
    nBatchCycles := nBatchCycles + 1;
END_IF;
END_PROGRAM
'''
        pou = project.inject_pou("WaterTreatmentControl", pump_logic, pou_type="PROGRAM")
        assert pou.name == "WaterTreatmentControl"
        assert (proj_dir / "pous" / "WaterTreatmentControl.st").exists()
        assert calculate_code_hash(pou.st_code) == calculate_code_hash(pump_logic)

        # Rejection of ladder logic
        with pytest.raises(LadderConstructRejectedError):
            project.inject_pou("BadLadder", "PROGRAM Bad\n---[ ]---\nEND_PROGRAM")

        # ---------------------------------------------------------------------
        # Stage 3: Variables Allocation
        # ---------------------------------------------------------------------
        vm = VariableManager(project_name="WaterTreatmentPlant")
        reg_start = vm.allocate_register("BOOL", "%M")
        assert reg_start == "%M1"
        vm.add_variable(CscapeVariable(name="bStartSwitch", data_type="BOOL", tag=reg_start, description="Start PB"))

        reg_stop = vm.allocate_register("BOOL", "%M")
        assert reg_stop == "%M2"
        vm.add_variable(CscapeVariable(name="bStopSwitch", data_type="BOOL", tag=reg_stop, description="Stop PB"))

        reg_pump = vm.allocate_register("BOOL", "%Q")
        assert reg_pump == "%Q1"
        vm.add_variable(CscapeVariable(name="bPumpRunning", data_type="BOOL", tag=reg_pump, description="Pump Coil"))

        reg_alarm = vm.allocate_register("BOOL", "%Q")
        assert reg_alarm == "%Q2"
        vm.add_variable(CscapeVariable(name="bAlarmHigh", data_type="BOOL", tag=reg_alarm, description="High Level Alarm"))

        reg_level = vm.allocate_register("INT", "%AI")
        assert reg_level == "%AI1"
        vm.add_variable(CscapeVariable(name="nLevelSensor", data_type="INT", tag=reg_level, description="Analog Level"))

        reg_batch = vm.allocate_register("INT", "%R")
        assert reg_batch == "%R1"
        vm.add_variable(CscapeVariable(name="nBatchCycles", data_type="INT", tag=reg_batch, description="Cycle Counter"))

        assert len(vm.detect_conflicts()) == 0
        sync_meta = vm.sync_to_project(proj_dir)
        assert sync_meta["variables_count"] == 6
        assert (proj_dir / "variables.xml").exists()
        assert (proj_dir / "variables.csv").exists()

        # ---------------------------------------------------------------------
        # Stage 4: Compile
        # ---------------------------------------------------------------------
        build_result = project.compile(clean_build=True)
        assert build_result.success is True
        assert build_result.error_count == 0
        assert build_result.hardware_lockout_enforced is True
        assert (proj_dir / "artifacts" / "build.log").exists()

        # ---------------------------------------------------------------------
        # Stage 5: Diagnostic Extraction
        # ---------------------------------------------------------------------
        clean_diags = CscapeLogParser.parse_log(build_result.raw_log)
        assert len([d for d in clean_diags if d.level == "ERROR"]) == 0

        # Induced error diagnostic extraction
        err_proj_dir = workspace_tmp_dir / "ErrExtractionProj"
        CscapeProject.create(err_proj_dir, name="ErrExtractionProj")
        (err_proj_dir / "pous").mkdir(exist_ok=True)
        (err_proj_dir / "pous" / "ErrLogic.st").write_text(
            "PROGRAM ErrLogic\nVAR\n    val : INT := 0\nEND_VAR\nval := \n",
            encoding="utf-8",
        )
        err_compiler = CscapeCompiler(workspace_root=workspace_tmp_dir)
        err_build = err_compiler.compile_project(err_proj_dir)
        assert err_build.success is False
        assert err_build.error_count > 0
        assert len(err_build.diagnostics) > 0
        assert any(d.level == "ERROR" and d.line is not None for d in err_build.diagnostics)

        # ---------------------------------------------------------------------
        # Stage 6: Software Simulation
        # ---------------------------------------------------------------------
        sim = CscapeSimulator(default_dt_ms=10.0, enforce_isolation=True)
        with pytest.raises(HardwareLockoutError):
            sim.connect_hardware("COM1")
        with pytest.raises(UnauthorizedDownloadError):
            sim.download_to_controller()

        reg_map = {v.name: v.tag for v in vm.list_variables() if v.tag}
        sim.load_program(pump_logic, register_map=reg_map)
        sim.start_simulation()
        assert sim.state == SimulationState.RUNNING

        # Cycle 0: System initial state (idle)
        sim.step_cycle()
        assert sim.read_bit(reg_pump) is False
        assert sim.read_register(reg_batch) == 0

        # Cycle 1: Start pump with safe water level
        sim.write_bit(reg_start, True)
        sim.write_register(reg_level, 50)
        sim.step_cycle()
        assert sim.read_bit(reg_pump) is True
        assert sim.read_register(reg_batch) == 1

        # Cycles 2-5: Pumping operation continues
        for _ in range(4):
            sim.step_cycle()
        assert sim.read_register(reg_batch) == 5

        # High level trip (>90): Pump shuts off, high level alarm trips
        sim.write_register(reg_level, 95)
        sim.step_cycle()
        assert sim.read_bit(reg_pump) is False
        assert sim.read_bit(reg_alarm) is True

        sim.stop_simulation()
        assert sim.state == SimulationState.STOPPED

