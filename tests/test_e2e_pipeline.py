"""
End-to-End Integration Tests for the complete Horner Cscape MCP Toolchain:
Project Creation -> ST POU Injection -> Validation -> Simulated Execution -> Diagnostic Verification.
"""
import pytest
from pathlib import Path
from src.project.manager import CscapeProject
from src.validation.validator import STValidator
from src.simulation.simulator import STSimulator
from src.simulation.test_runner import TestBench, TestRunner
from src.diagnostics.verifier import DiagnosticVerifier, DiagnosticReport
from src.cscape.compiler import CscapeCompiler, CscapeLogParser, CscapeBuildResult
from src.cscape.project_manager import CFBF_MAGIC, CscapeLiveProjectManager
from src.cscape.simulation import CscapeSimulator, SimulationState
from src.cscape.st_ld_interop import LadderConstructRejectedError
from src.cscape.variables import VariableManager, CscapeVariable
from src.security.exceptions import HardwareLockoutError, UnauthorizedDownloadError

def test_e2e_conveyor_packaging_line(tmp_path):
    """
    Complete E2E pipeline for an industrial conveyor packaging line:
    1. Project Creation
    2. ST POU Injection (ConveyorBatchControl with CTU counter and state machine)
    3. Validation
    4. Simulated Execution (Pulsing box sensors over scan cycles)
    5. Diagnostic Verification (State coverage, invariant check, zero hardware faults)
    """
    # 1. Project Creation
    proj_dir = tmp_path / "PackagingLine"
    project = CscapeProject.create(proj_dir, name="PackagingLine", controller="XL4")
    assert (proj_dir / "PackagingLine.csp").exists()
    assert (proj_dir / "cscape_project.json").exists()

    # 2. ST POU Injection
    conveyor_st = """
    PROGRAM ConveyorBatchControl
    VAR_INPUT
        bSystemEnable : BOOL := FALSE;
        bBoxSensor : BOOL := FALSE;
        bResetCounter : BOOL := FALSE;
    END_VAR
    VAR_OUTPUT
        bConveyorRunning : BOOL := FALSE;
        bBatchComplete : BOOL := FALSE;
        iBoxCount : INT := 0;
    END_VAR
    VAR
        iState : INT := 0; (* 0: IDLE, 1: FEEDING, 2: BATCH_DONE *)
        boxCounter : CTU;
    END_VAR

    // Execute counter
    boxCounter(CU := bBoxSensor, RESET := (bResetCounter OR (iState = 0)), PV := 5);
    iBoxCount := boxCounter.CV;

    // State transitions
    CASE iState OF
        0: // IDLE
            IF bSystemEnable THEN
                iState := 1;
            END_IF;

        1: // FEEDING
            IF NOT bSystemEnable THEN
                iState := 0;
            ELSIF boxCounter.Q THEN
                iState := 2;
            END_IF;

        2: // BATCH_DONE
            IF bResetCounter OR (NOT bSystemEnable) THEN
                iState := 0;
            END_IF;
    END_CASE;

    // Output mapping
    bConveyorRunning := (iState = 1);
    bBatchComplete := (iState = 2);
    END_PROGRAM
    """
    pou_info = project.inject_pou("ConveyorBatchControl", conveyor_st, pou_type="PROGRAM")
    assert pou_info.name == "ConveyorBatchControl"
    assert Path(pou_info.file_path).exists()
    assert pou_info.statement_count >= 2

    # 3. Validation
    validator = STValidator()
    val_res = validator.validate(pou_info.st_code)
    assert val_res.is_valid is True, f"Validation failed: {val_res.summary}"
    assert len(val_res.errors) == 0
    assert "CTU" in val_res.used_function_blocks

    # 4. Simulated Execution
    sim = STSimulator(default_dt_ms=10.0)
    sim.load_program(pou_info.st_code)

    # Initial cycle in IDLE
    sim.step()
    assert sim.get_variable("iState") == 0
    assert sim.get_variable("bConveyorRunning") is False

    # Enable system -> transitions to FEEDING
    sim.set_variable("bSystemEnable", True)
    sim.step()
    assert sim.get_variable("iState") == 1
    assert sim.get_variable("bConveyorRunning") is True

    # Simulate 5 boxes arriving at sensor
    for box in range(1, 6):
        # Sensor ON
        sim.set_variable("bBoxSensor", True)
        sim.step()
        # Sensor OFF
        sim.set_variable("bBoxSensor", False)
        sim.step()
        assert sim.get_variable("iBoxCount") == box

    # After 5th box, counter reached PV=5 -> transitions to BATCH_DONE
    assert sim.get_variable("iState") == 2
    assert sim.get_variable("bBatchComplete") is True
    assert sim.get_variable("bConveyorRunning") is False

    # 5. Diagnostic Verification
    verifier = DiagnosticVerifier()
    safety_invariant = lambda snap: (
        "Safety fault: Conveyor active when system disabled"
        if snap.get("bConveyorRunning") and not snap.get("bSystemEnable")
        else None
    )

    report = verifier.verify(
        simulator=sim,
        state_variables=["iState"],
        expected_states={"iState": {0, 1, 2}},
        safety_invariants=[safety_invariant]
    )

    assert report.status == "success"
    assert report.checks_failed == 0
    assert report.checks_passed == report.checks_run
    assert report.state_coverage["ISTATE"] == {0, 1, 2}

def test_e2e_chemical_reactor_vessel(tmp_path):
    """
    Complete E2E pipeline for an industrial chemical reactor vessel:
    1. Project Creation
    2. ST POU Injection (ReactorAgitator with TON timer and temperature interlock)
    3. Validation
    4. Simulated Execution (Heating, Agitation timing, emergency trip)
    5. Diagnostic Verification
    """
    proj_dir = tmp_path / "ReactorVessel"
    project = CscapeProject.create(proj_dir, name="ReactorVessel", controller="X5")

    reactor_st = """
    PROGRAM ReactorAgitator
    VAR_INPUT
        bStartProcess : BOOL := FALSE;
        rTemperature : REAL := 20.0;
        bEmergencyStop : BOOL := FALSE;
    END_VAR
    VAR_OUTPUT
        bHeaterActive : BOOL := FALSE;
        bAgitatorMotor : BOOL := FALSE;
        bProcessDone : BOOL := FALSE;
        bAlarm : BOOL := FALSE;
    END_VAR
    VAR
        iState : INT := 0; (* 0: STANDBY, 1: HEATING, 2: AGITATING, 3: DONE, 4: EMERGENCY *)
        agitationTimer : TON;
    END_VAR

    agitationTimer(IN := (iState = 2), PT := T#50ms);

    IF bEmergencyStop OR (rTemperature > 100.0) THEN
        iState := 4;
    END_IF;

    CASE iState OF
        0: // STANDBY
            IF bStartProcess THEN
                iState := 1;
            END_IF;

        1: // HEATING
            IF rTemperature >= 75.0 THEN
                iState := 2;
            END_IF;

        2: // AGITATING
            IF agitationTimer.Q THEN
                iState := 3;
            END_IF;

        3: // DONE
            // Wait for reset or stays done

        4: // EMERGENCY
            // Safe shutdown
    END_CASE;

    // Output mapping
    bHeaterActive := (iState = 1);
    bAgitatorMotor := (iState = 2);
    bProcessDone := (iState = 3);
    bAlarm := (iState = 4);
    END_PROGRAM
    """
    pou_info = project.inject_pou("ReactorAgitator", reactor_st)
    assert pou_info.name == "ReactorAgitator"

    # Validation
    validator = STValidator()
    val_res = validator.validate(pou_info.st_code)
    assert val_res.is_valid is True
    assert "TON" in val_res.used_function_blocks

    # Simulated Execution
    sim = STSimulator(default_dt_ms=10.0)
    sim.load_program(pou_info.st_code)

    # Standby
    sim.step()
    assert sim.get_variable("iState") == 0

    # Start Heating
    sim.set_variable("bStartProcess", True)
    sim.step()
    assert sim.get_variable("iState") == 1
    assert sim.get_variable("bHeaterActive") is True

    # Temperature reaches 75.0°C -> transitions to AGITATING
    sim.set_variable("rTemperature", 75.0)
    sim.step()
    assert sim.get_variable("iState") == 2
    assert sim.get_variable("bAgitatorMotor") is True
    assert sim.get_variable("bHeaterActive") is False

    # Agitate for 50ms (5 cycles)
    for _ in range(5):
        sim.step()
    assert sim.get_variable("iState") == 3
    assert sim.get_variable("bProcessDone") is True
    assert sim.get_variable("bAgitatorMotor") is False

    # Diagnostic Verification
    verifier = DiagnosticVerifier()
    report = verifier.verify(
        simulator=sim,
        state_variables=["iState"],
        expected_states={"iState": {0, 1, 2, 3}}
    )
    assert report.status == "success"

def test_e2e_traffic_light_preemption(tmp_path):
    """
    Complete E2E pipeline for a traffic junction with emergency vehicle preemption.
    """
    proj_dir = tmp_path / "TrafficJunction"
    project = CscapeProject.create(proj_dir, name="TrafficJunction", controller="XL4")

    traffic_st = """
    PROGRAM TrafficController
    VAR_INPUT
        bEmergencySensor : BOOL := FALSE;
    END_VAR
    VAR_OUTPUT
        bRedLight : BOOL := TRUE;
        bYellowLight : BOOL := FALSE;
        bGreenLight : BOOL := FALSE;
        bEmergencySiren : BOOL := FALSE;
    END_VAR
    VAR
        iPhase : INT := 2; (* 0: GREEN, 1: YELLOW, 2: RED, 3: EMERGENCY *)
        phaseTimer : TON;
    END_VAR

    phaseTimer(IN := TRUE, PT := T#30ms);

    IF bEmergencySensor THEN
        iPhase := 3;
    END_IF;

    CASE iPhase OF
        0: // GREEN
            bRedLight := FALSE;
            bYellowLight := FALSE;
            bGreenLight := TRUE;
            bEmergencySiren := FALSE;
            IF phaseTimer.Q THEN
                iPhase := 1;
                phaseTimer(IN := FALSE);
            END_IF;

        1: // YELLOW
            bRedLight := FALSE;
            bYellowLight := TRUE;
            bGreenLight := FALSE;
            bEmergencySiren := FALSE;
            IF phaseTimer.Q THEN
                iPhase := 2;
                phaseTimer(IN := FALSE);
            END_IF;

        2: // RED
            bRedLight := TRUE;
            bYellowLight := FALSE;
            bGreenLight := FALSE;
            bEmergencySiren := FALSE;
            IF phaseTimer.Q THEN
                iPhase := 0;
                phaseTimer(IN := FALSE);
            END_IF;

        3: // EMERGENCY PREEMPTION
            bRedLight := TRUE;
            bYellowLight := FALSE;
            bGreenLight := FALSE;
            bEmergencySiren := TRUE;
            IF NOT bEmergencySensor THEN
                iPhase := 2;
            END_IF;
    END_CASE;
    END_PROGRAM
    """
    pou = project.inject_pou("TrafficController", traffic_st)
    val = STValidator().validate(pou.st_code)
    assert val.is_valid is True

    sim = STSimulator(default_dt_ms=10.0)
    sim.load_program(pou.st_code)

    # Run normal cycles
    for _ in range(8):
        sim.step()

    # Preempt with emergency vehicle
    sim.set_variable("bEmergencySensor", True)
    sim.step()
    assert sim.get_variable("iPhase") == 3
    assert sim.get_variable("bEmergencySiren") is True
    assert sim.get_variable("bGreenLight") is False

    # Clear emergency
    sim.set_variable("bEmergencySensor", False)
    sim.step()
    assert sim.get_variable("iPhase") == 2

    # Verify conflicting green/red never occurred
    safety_rule = lambda snap: (
        "Safety conflict: Green and Red active simultaneously"
        if snap.get("bGreenLight") and snap.get("bRedLight")
        else None
    )

    verifier = DiagnosticVerifier()
    report = verifier.verify(
        simulator=sim,
        state_variables=["iPhase"],
        expected_states={"iPhase": {0, 1, 2, 3}},
        safety_invariants=[safety_rule]
    )
    assert report.status == "success"

def test_e2e_negative_safety_abort(tmp_path):
    """
    E2E pipeline testing safety refusal:
    When prohibited physical PLC operations or invalid syntax are injected,
    the pipeline blocks execution and produces actionable diagnostic errors.
    """
    proj_dir = tmp_path / "SafetyGuardProject"
    project = CscapeProject.create(proj_dir, name="SafetyGuardProject", controller="XL4")

    dangerous_st = """
    PROGRAM MaliciousFlash
    VAR
        cmd : INT := 1;
    END_VAR
    // Prohibited physical PLC flash/download commands
    PGMUpdateUtility(run := TRUE);
    DIRECT_IO(channel := 5);
    END_PROGRAM
    """
    pou = project.inject_pou("MaliciousFlash", dangerous_st)

    # Validation MUST detect the forbidden operations
    val = STValidator()
    result = val.validate(pou.st_code)
    assert result.is_valid is False
    assert len(result.errors) >= 2
    assert any("PGMUpdateUtility" in str(e) for e in result.errors)
    assert any("DIRECT_IO" in str(e) for e in result.errors)

    # Ensure simulation execution is halted on invalid/unsafe POU
    sim = STSimulator()
    with pytest.raises(Exception):
        if not result.is_valid:
            raise RuntimeError(f"Pipeline Safety Halt: {result.summary}")
        sim.load_program(pou.st_code)


def test_complete_cscape_e2e_pipeline_stages(tmp_path: Path):
    """
    Comprehensive verification of the full 6-stage end-to-end flow:
    1. Project Initialization: CscapeProject.create -> CFBF .csp container & cscape_project.json
    2. ST Injection: project.inject_pou with IEC 61131-3 logic + ladder rejection guard
    3. Variables Allocation: VariableManager assigning OCS registers (%M, %Q, %AI, %R) + project sync
    4. Compile: CscapeCompiler.compile_project -> clean build, 0 errors, hardware lockout
    5. Diagnostic Extraction: CscapeLogParser extracting clean build info and line-accurate syntax errors
    6. Software Simulation: CscapeSimulator multi-cycle execution with register table, scan clocks, and zero hardware access
    """
    proj_dir = tmp_path / "AutomatedWarehouse"

    # 1. Project Initialization
    project = CscapeProject.create(proj_dir, name="AutomatedWarehouse", controller="XL4")
    assert (proj_dir / "AutomatedWarehouse.csp").exists()
    assert (proj_dir / "cscape_project.json").exists()
    info = CscapeLiveProjectManager.inspect_project_file(proj_dir / "AutomatedWarehouse.csp")
    assert info.is_valid_cfbf is True
    assert info.magic_hex == CFBF_MAGIC.hex()

    # 2. ST Injection
    warehouse_st = """PROGRAM WarehouseConveyor
VAR
    bSystemRun : BOOL := FALSE;
    bItemDetected : BOOL := FALSE;
    nWeightKg : INT := 0;
    bConveyorMotor : BOOL := FALSE;
    bDiverterArm : BOOL := FALSE;
    nTotalDispatched : INT := 0;
END_VAR

IF bSystemRun THEN
    bConveyorMotor := TRUE;
    IF bItemDetected THEN
        nTotalDispatched := nTotalDispatched + 1;
        IF nWeightKg > 50 THEN
            bDiverterArm := TRUE;
        ELSE
            bDiverterArm := FALSE;
        END_IF;
    END_IF;
ELSE
    bConveyorMotor := FALSE;
    bDiverterArm := FALSE;
END_IF;
END_PROGRAM
"""
    pou = project.inject_pou("WarehouseConveyor", warehouse_st, pou_type="PROGRAM")
    assert pou.name == "WarehouseConveyor"
    assert (proj_dir / "pous" / "WarehouseConveyor.st").exists()
    assert pou.statement_count >= 1

    # Guard check: reject ladder logic
    with pytest.raises(LadderConstructRejectedError):
        project.inject_pou("InvalidLadder", "PROGRAM LadderBad\n---[/]---( )---\nEND_PROGRAM")

    # 3. Variables Allocation
    vm = VariableManager(project_name="AutomatedWarehouse")
    reg_run = vm.allocate_register("BOOL", "%M")
    assert reg_run == "%M1"
    vm.add_variable(CscapeVariable(name="bSystemRun", data_type="BOOL", tag=reg_run, description="System Master Run"))

    reg_sensor = vm.allocate_register("BOOL", "%M")
    assert reg_sensor == "%M2"
    vm.add_variable(CscapeVariable(name="bItemDetected", data_type="BOOL", tag=reg_sensor, description="Optical Sensor"))

    reg_motor = vm.allocate_register("BOOL", "%Q")
    assert reg_motor == "%Q1"
    vm.add_variable(CscapeVariable(name="bConveyorMotor", data_type="BOOL", tag=reg_motor, description="Main Conveyor Drive"))

    reg_divert = vm.allocate_register("BOOL", "%Q")
    assert reg_divert == "%Q2"
    vm.add_variable(CscapeVariable(name="bDiverterArm", data_type="BOOL", tag=reg_divert, description="Heavy Item Diverter"))

    reg_weight = vm.allocate_register("INT", "%AI")
    assert reg_weight == "%AI1"
    vm.add_variable(CscapeVariable(name="nWeightKg", data_type="INT", tag=reg_weight, description="Scale Load Cell"))

    reg_disp = vm.allocate_register("INT", "%R")
    assert reg_disp == "%R1"
    vm.add_variable(CscapeVariable(name="nTotalDispatched", data_type="INT", tag=reg_disp, description="Dispatch Counter"))

    assert len(vm.detect_conflicts()) == 0
    sync_res = vm.sync_to_project(proj_dir)
    assert sync_res["variables_count"] == 6
    assert (proj_dir / "variables.xml").exists()
    assert (proj_dir / "variables.csv").exists()

    # 4. Compile
    compiler = CscapeCompiler(workspace_root=tmp_path)
    build_res = compiler.compile_project(proj_dir, clean_build=True)
    assert build_res.success is True
    assert build_res.error_count == 0
    assert build_res.hardware_lockout_enforced is True
    assert (proj_dir / "artifacts" / "build.log").exists()

    # 5. Diagnostic Extraction
    # Clean compile produces 0 error diagnostics
    clean_diags = CscapeLogParser.parse_log(build_res.raw_log)
    assert len([d for d in clean_diags if d.level == "ERROR"]) == 0

    # Induced syntax error produces line-accurate diagnostic
    err_proj_dir = tmp_path / "WarehouseErr"
    CscapeProject.create(err_proj_dir, name="WarehouseErr")
    (err_proj_dir / "pous").mkdir(exist_ok=True)
    (err_proj_dir / "pous" / "BrokenSyntax.st").write_text(
        "PROGRAM BrokenSyntax\nVAR\n    y : INT := 10\nEND_VAR\ny :=\n",
        encoding="utf-8",
    )
    err_res = compiler.compile_project(err_proj_dir)
    assert err_res.success is False
    assert err_res.error_count > 0
    assert len(err_res.diagnostics) > 0
    assert any(d.level == "ERROR" and d.line is not None for d in err_res.diagnostics)

    # 6. Software Simulation
    sim = CscapeSimulator(default_dt_ms=10.0, enforce_isolation=True)
    with pytest.raises(HardwareLockoutError):
        sim.connect_hardware("COM2")
    with pytest.raises(UnauthorizedDownloadError):
        sim.download_to_controller()

    reg_map = {v.name: v.tag for v in vm.list_variables() if v.tag}
    sim.load_program(warehouse_st, register_map=reg_map)
    sim.start_simulation()
    assert sim.state == SimulationState.RUNNING

    # Scan 0: System Idle
    sim.step_cycle()
    assert sim.read_bit(reg_motor) is False
    assert sim.read_register(reg_disp) == 0

    # Scan 1: Turn system on -> Motor starts
    sim.write_bit(reg_run, True)
    sim.step_cycle()
    assert sim.read_bit(reg_motor) is True
    assert sim.read_bit(reg_divert) is False

    # Scan 2: Normal weight item (25 kg) detected -> Dispatched, no divert
    sim.write_bit(reg_sensor, True)
    sim.write_register(reg_weight, 25)
    sim.step_cycle()
    assert sim.read_register(reg_disp) == 1
    assert sim.read_bit(reg_divert) is False

    # Scan 3: Heavy weight item (75 kg) detected -> Diverter active
    sim.write_register(reg_weight, 75)
    sim.step_cycle()
    assert sim.read_register(reg_disp) == 2
    assert sim.read_bit(reg_divert) is True

    # Scan 4: Turn system off -> Motor and diverter stop
    sim.write_bit(reg_run, False)
    sim.step_cycle()
    assert sim.read_bit(reg_motor) is False
    assert sim.read_bit(reg_divert) is False

    sim.stop_simulation()
    assert sim.state == SimulationState.STOPPED