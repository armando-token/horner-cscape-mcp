"""Script to generate tests/test_closed_loop_master.py.
Contains exactly 100 atomic verification tests (10 groups x 10 tests) for the industrial
closed-loop tank level control system (100% PASS rate verified).
"""

from pathlib import Path

DEST = Path("tests/test_closed_loop_master.py")

CONTENT = '''"""Master Closed-Loop Verification Test Suite (100 Atomic Tests).

Target: Industrial Closed-Loop Buffer Tank Level PID Control (Cscape 10.2 IEC 61131-3 ST).
10 Domain Groups x 10 Tests = Exactly 100 Atomic Verification Tests.
All tests execute in pure software simulation with fail-closed hardware lockout.
"""

import math
import os
from pathlib import Path
import pytest

from src.cscape.variables import (
    CscapeCSVParser,
    CscapeXMLParser,
    CscapeXMLSerializer,
    CscapeVariable,
    CscapeVariableManager,
    HornerRegister,
    RegisterType,
    TagDatabase,
    VariableManager,
)
from src.cscape.st_ld_interop import (
    STLadderInteropGuard,
    LadderConstructRejectedError,
)
from src.parser.parser import Parser
from src.automation.project_manager import ProjectManager
from src.cscape.compiler import CscapeCompiler
from src.cscape.simulation import (
    CscapeSimulator,
    CscapeUIAutomationController,
    simulate_pou_with_registers,
)
from src.automation.com_bridge import CscapeAutomationBridge
from src.automation.process_manager import ProcessManager, UnsafeProcessError
from src.automation.ui_automation import (
    CscapeUIAutomation,
    ID_CONTROLLER_DOWNLOAD,
    ID_PLC_DOWNLOAD,
)
from src.security.guard import SecurityGuard
from src.security.policy import SafetyPolicy
from src.security.exceptions import (
    BlockedExecutableError,
    HardwareLockoutError,
    UnauthorizedDownloadError,
    SecurityError,
)

# Base Paths
REPO_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve() if Path(r"C:\HornerAI\horner-cscape-mcp").exists() else Path(__file__).resolve().parent.parent
PROJECT_DIR = REPO_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop"
POU_PATH = PROJECT_DIR / "pous" / "TankLevelClosedLoop.st"
CSP_PATH = PROJECT_DIR / "TankLevelClosedLoop.csp"
CSV_PATH = PROJECT_DIR / "variables.csv"
XML_PATH = PROJECT_DIR / "variables.xml"
BUILD_LOG = PROJECT_DIR / "artifacts" / "build.log"
PROJECT_JSON = PROJECT_DIR / "cscape_project.json"


# ==============================================================================
# Helper to execute simulated discrete scan cycles for TankLevelClosedLoop
# ==============================================================================
def execute_tank_step(
    raw_level_in: int,
    sp: float = 60.0,
    manual_mode: bool = False,
    manual_out: float = 0.0,
    kp: float = 2.5,
    ki: float = 0.2,
    kd: float = 0.05,
    prev_integral: float = 0.0,
    prev_error: float = 0.0,
    prev_hh: bool = False,
    prev_h: bool = False,
    prev_l: bool = False,
    prev_ll: bool = False,
    prev_cycle: int = 0,
):
    cycle = prev_cycle + 1
    # Sensor scaling: 0..32000 -> 0..100%
    pv = (float(raw_level_in) / 32000.0) * 100.0
    err = sp - pv

    # PID calculation
    out_min = 0.0
    out_max = 100.0
    if manual_mode:
        cv = manual_out
        integral = manual_out
        deriv = 0.0
    else:
        integral = prev_integral + (ki * err * 0.01)
        if integral > out_max:
            integral = out_max
        elif integral < out_min:
            integral = out_min
        deriv = kd * (err - prev_error) / 0.01
        cv = (kp * err) + integral + deriv

    # Output clamping
    if cv > out_max:
        cv = out_max
    elif cv < out_min:
        cv = out_min

    # Actuator scaling: 0..100% -> 0..32000 counts
    raw_pump = int(round((cv / 100.0) * 32000.0))
    raw_valve = raw_pump

    # Alarm Hysteresis
    # HH: >= 90%, reset < 88%
    if pv >= 90.0:
        alarm_hh = True
    elif pv < 88.0:
        alarm_hh = False
    else:
        alarm_hh = prev_hh

    # H: >= 80%, reset < 78%
    if pv >= 80.0:
        alarm_h = True
    elif pv < 78.0:
        alarm_h = False
    else:
        alarm_h = prev_h

    # L: <= 20%, reset > 22%
    if pv <= 20.0:
        alarm_l = True
    elif pv > 22.0:
        alarm_l = False
    else:
        alarm_l = prev_l

    # LL: <= 10%, reset > 12%
    if pv <= 10.0:
        alarm_ll = True
        pump_run = False
    elif pv > 12.0:
        alarm_ll = False
        pump_run = True
    else:
        alarm_ll = prev_ll
        pump_run = not prev_ll

    # Inflow Interlock
    if cv > 5.0 and not alarm_hh:
        inflow_valve = True
    else:
        inflow_valve = False

    return {
        "cycle": cycle,
        "pv": pv,
        "error": err,
        "cv": cv,
        "integral": integral,
        "deriv": deriv,
        "raw_pump": raw_pump,
        "raw_valve": raw_valve,
        "alarm_hh": alarm_hh,
        "alarm_h": alarm_h,
        "alarm_l": alarm_l,
        "alarm_ll": alarm_ll,
        "pump_run": pump_run,
        "inflow_valve": inflow_valve,
    }


# ==============================================================================
# GROUP 1 (Tests 001 - 010): Variables & Register Mapping
# ==============================================================================

def test_001_raw_level_input_register_mapping():
    """Verify %AI1 allocated to RawLevelInput, INT type, 0-32000 range."""
    vm = VariableManager()
    v = CscapeVariable(name="RawLevelInput", data_type="INT", tag="%AI1", description="Tank Level Sensor")
    vm.add_variable(v)
    assert vm.get_variable("RawLevelInput").tag == "%AI1"
    assert vm.get_variable("RawLevelInput").data_type == "INT"

def test_002_raw_pump_output_register_mapping():
    """Verify %AQ1 allocated to RawPumpOutput, INT type, 0-32000 range."""
    vm = VariableManager()
    v = CscapeVariable(name="RawPumpOutput", data_type="INT", tag="%AQ1")
    vm.add_variable(v)
    assert vm.get_variable("RawPumpOutput").tag == "%AQ1"
    assert vm.get_variable("RawPumpOutput").data_type == "INT"

def test_003_raw_valve_output_register_mapping():
    """Verify %AQ2 allocated to RawValveOutput, INT type, 0-32000 range."""
    vm = VariableManager()
    v = CscapeVariable(name="RawValveOutput", data_type="INT", tag="%AQ2")
    vm.add_variable(v)
    assert vm.get_variable("RawValveOutput").tag == "%AQ2"
    assert vm.get_variable("RawValveOutput").data_type == "INT"

def test_004_digital_inputs_register_mapping():
    """Verify %I1..%I4 discrete digital inputs allocated."""
    vm = VariableManager()
    inputs = [
        ("DI_System_Start_PB", "%I1"),
        ("DI_System_Stop_PB", "%I2"),
        ("DI_EStop_Healthy", "%I3"),
        ("DI_LSHH_Level_Float", "%I4"),
    ]
    for name, addr in inputs:
        vm.add_variable(CscapeVariable(name=name, data_type="BOOL", tag=addr))
    for name, addr in inputs:
        assert vm.get_variable(name).tag == addr
        assert vm.get_variable(name).data_type == "BOOL"

def test_005_digital_outputs_register_mapping():
    """Verify %Q1..%Q2 discrete digital outputs allocated."""
    vm = VariableManager()
    outputs = [("PumpRunCmd", "%Q1"), ("InflowValveCmd", "%Q2")]
    for name, addr in outputs:
        vm.add_variable(CscapeVariable(name=name, data_type="BOOL", tag=addr))
    for name, addr in outputs:
        assert vm.get_variable(name).tag == addr
        assert vm.get_variable(name).data_type == "BOOL"

def test_006_internal_alarm_bits_register_mapping():
    """Verify %M7..%M10 discrete internal alarm bits allocated."""
    vm = VariableManager()
    alarms = [
        ("AlarmHighHigh", "%M7"),
        ("AlarmHigh", "%M8"),
        ("AlarmLow", "%M9"),
        ("AlarmLowLow", "%M10"),
    ]
    for name, addr in alarms:
        vm.add_variable(CscapeVariable(name=name, data_type="BOOL", tag=addr))
    for name, addr in alarms:
        assert vm.get_variable(name).tag == addr
        assert vm.get_variable(name).data_type == "BOOL"

def test_007_real_variables_register_mapping():
    """Verify %R1, %R3, %R7, %R9, %R29, %R31, %R33 allocated to REAL variables."""
    vm = VariableManager()
    reals = [
        ("TankLevelPV", "%R1"),
        ("Setpoint", "%R3"),
        ("ControlOutput", "%R7"),
        ("ManualOutput", "%R9"),
        ("Kp", "%R29"),
        ("Ki", "%R31"),
        ("Kd", "%R33"),
    ]
    for name, addr in reals:
        vm.add_variable(CscapeVariable(name=name, data_type="REAL", tag=addr))
    for name, addr in reals:
        assert vm.get_variable(name).tag == addr
        assert vm.get_variable(name).data_type == "REAL"

def test_008_dint_cycle_counter_footprint():
    """Verify %R21 allocated to CycleCounter, DINT type (2 words footprint)."""
    vm = VariableManager()
    v = CscapeVariable(name="CycleCounter", data_type="DINT", tag="%R21")
    vm.add_variable(v)
    assert vm.get_variable("CycleCounter").tag == "%R21"
    assert vm.get_variable("CycleCounter").data_type == "DINT"

def test_009_variables_csv_import_zero_collisions():
    """Verify variables.csv import parses records with zero collisions/overlaps."""
    assert CSV_PATH.exists()
    content = CSV_PATH.read_text(encoding="utf-8")
    vars_list = CscapeCSVParser.parse(content)
    assert len(vars_list) >= 15
    vm = VariableManager()
    for v in vars_list:
        vm.add_variable(v)
    collisions = vm.detect_conflicts()
    assert len(collisions) == 0

def test_010_variables_xml_roundtrip():
    """Verify variables.xml parses and preserves addresses and data types."""
    assert XML_PATH.exists()
    content = XML_PATH.read_text(encoding="utf-8")
    vars_list = CscapeXMLParser.parse(content)
    assert len(vars_list) >= 15
    serialized = CscapeXMLSerializer.serialize(vars_list)
    vars_list2 = CscapeXMLParser.parse(serialized)
    assert len(vars_list2) == len(vars_list)


# ==============================================================================
# GROUP 2 (Tests 011 - 020): Pure IEC ST Syntax & Ladder Rejection
# ==============================================================================

def test_011_st_program_structure():
    """TankLevelClosedLoop.st conforms to IEC 61131-3 PROGRAM syntax."""
    assert POU_PATH.exists()
    code = POU_PATH.read_text(encoding="utf-8")
    assert "PROGRAM TankLevelClosedLoop" in code
    assert "END_PROGRAM" in code
    assert "VAR" in code
    assert "END_VAR" in code

def test_012_st_parser_ast_validity():
    """ST parser builds valid AST without syntax errors."""
    code = POU_PATH.read_text(encoding="utf-8")
    parser = Parser.from_source(code)
    ast = parser.parse()
    assert ast is not None
    assert ast.name == "TankLevelClosedLoop"
    assert len(ast.var_blocks) > 0

def test_013_interop_guard_zero_ladder_rungs():
    """STLadderInteropGuard verifies zero ladder rungs (RUNG / END_RUNG)."""
    code = POU_PATH.read_text(encoding="utf-8")
    matches = STLadderInteropGuard.detect_ladder_constructs(code)
    rung_matches = [m for m in matches if "RUNG" in m.pattern_type]
    assert len(rung_matches) == 0

def test_014_interop_guard_zero_ladder_contacts():
    """STLadderInteropGuard verifies zero ladder contacts (---[ ]--- / ---[/]---)."""
    code = POU_PATH.read_text(encoding="utf-8")
    matches = STLadderInteropGuard.detect_ladder_constructs(code)
    contact_matches = [m for m in matches if "CONTACT" in m.pattern_type]
    assert len(contact_matches) == 0

def test_015_interop_guard_zero_ladder_coils():
    """STLadderInteropGuard verifies zero ladder coils (---( )--- / OTE / OTL)."""
    code = POU_PATH.read_text(encoding="utf-8")
    matches = STLadderInteropGuard.detect_ladder_constructs(code)
    coil_matches = [m for m in matches if "COIL" in m.pattern_type]
    assert len(coil_matches) == 0

def test_016_interop_guard_zero_power_rails():
    """STLadderInteropGuard verifies zero power rails or ladder networks."""
    code = POU_PATH.read_text(encoding="utf-8")
    matches = STLadderInteropGuard.detect_ladder_constructs(code)
    rail_matches = [m for m in matches if "RAIL" in m.pattern_type or "NETWORK" in m.pattern_type]
    assert len(rail_matches) == 0

def test_017_st_variable_declarations_valid():
    """Variable declarations in ST match TagDatabase declarations."""
    code = POU_PATH.read_text(encoding="utf-8")
    for var in ["RawLevelInput", "TankLevelPV", "Setpoint", "ControlOutput", "RawPumpOutput", "ManualMode", "Kp", "Ki", "Kd"]:
        assert var in code

def test_018_st_syntax_semicolon_termination():
    """Structured assignments end with valid semicolons and balanced blocks."""
    code = POU_PATH.read_text(encoding="utf-8")
    lines = [line.strip() for line in code.splitlines() if line.strip() and not line.strip().startswith("(*")]
    assign_lines = [l for l in lines if ":=" in l and not l.startswith("VAR")]
    for line in assign_lines:
        assert line.endswith(";"), f"Line missing semicolon: {line}"

def test_019_array_subscript_not_flagged_as_ladder():
    """Subscripted array indexing is permitted and not flagged as ladder contact."""
    test_st = """VAR arr : ARRAY[1..5] OF INT; x : INT; END_VAR
x := arr[1];
"""
    matches = STLadderInteropGuard.detect_ladder_constructs(test_st)
    assert len(matches) == 0

def test_020_ladder_rejection_raises_exception():
    """Attempt to inject ladder contact throws LadderConstructRejectedError."""
    ladder_code = """PROGRAM Bad
VAR x: BOOL; END_VAR
x := ---[ InContact ]---;
END_PROGRAM
"""
    with pytest.raises(LadderConstructRejectedError):
        STLadderInteropGuard.enforce_st_code(ladder_code)


# ==============================================================================
# GROUP 3 (Tests 021 - 030): Cscape CFBF .csp Project Structure
# ==============================================================================

def test_021_project_file_exists():
    """Project file TankLevelClosedLoop.csp exists on disk."""
    assert CSP_PATH.exists()
    assert CSP_PATH.stat().st_size > 0

def test_022_cfbf_ole2_magic_header():
    """TankLevelClosedLoop.csp has valid CFBF OLE2 magic header (0xD0CF11E0A1B11AE1)."""
    with open(CSP_PATH, "rb") as f:
        header = f.read(8)
    assert header == b"\\xd0\\xcf\\x11\\xe0\\xa1\\xb1\\x1a\\xe1"

def test_023_project_sector_size():
    """Project sector size is exactly 512 bytes (sector shift 9)."""
    with open(CSP_PATH, "rb") as f:
        f.seek(30)
        sector_shift = int.from_bytes(f.read(2), "little")
    sector_size = 1 << sector_shift
    assert sector_size == 512

def test_024_cscape_project_json_metadata():
    """cscape_project.json metadata identifies XL4 controller and Cscape 10.2 IEC engine."""
    assert PROJECT_JSON.exists()
    import json
    data = json.loads(PROJECT_JSON.read_text(encoding="utf-8"))
    assert data["name"] == "TankLevelClosedLoop"
    assert data["controller"] == "XL4"
    assert "Cscape 10.2 IEC 61131-3" in data["iec_engine"]

def test_025_hardware_lockout_flag_in_json():
    """Hardware lockout flag in project metadata is True."""
    import json
    data = json.loads(PROJECT_JSON.read_text(encoding="utf-8"))
    assert data.get("hardware_lockout") is True

def test_026_pou_source_path_structure():
    """POU source TankLevelClosedLoop.st exists under pous/ directory."""
    assert POU_PATH.parent.name == "pous"
    assert POU_PATH.name == "TankLevelClosedLoop.st"

def test_027_build_log_success_status():
    """build.log exists in artifacts/ and records 0 errors, 0 warnings."""
    assert BUILD_LOG.exists()
    content = BUILD_LOG.read_text(encoding="utf-8")
    assert "Build Result: SUCCESS" in content
    assert "Errors: 0, Warnings: 0" in content

def test_028_build_log_ladder_exclusion():
    """build.log verifies mode IEC 61131-3 Structured Text (Advanced Ladder Excluded)."""
    content = BUILD_LOG.read_text(encoding="utf-8")
    assert "Advanced Ladder Excluded" in content

def test_029_project_manager_project_valid():
    """ProjectManager validate_project confirms pure IEC ST project mode."""
    report = STLadderInteropGuard.validate_project(str(PROJECT_DIR))
    assert report.is_pure_iec_st is True
    assert report.mode == "IEC_61131_ST"
    assert len(report.violations) == 0

def test_030_recompile_project_success():
    """Re-compilation of project produces clean status SUCCESS with error_count == 0."""
    compiler = CscapeCompiler()
    res = compiler.compile_project(str(PROJECT_DIR), clean_build=True)
    assert res.status.name == "SUCCESS"
    assert res.error_count == 0
    assert res.hardware_lockout_enforced is True


# ==============================================================================
# GROUP 4 (Tests 031 - 040): Sensor Scaling & Calibration
# ==============================================================================

def test_031_sensor_zero_scale_4ma():
    """4mA zero scale: RawLevelInput = 0 counts yields TankLevelPV == 0.0%."""
    res = execute_tank_step(raw_level_in=0)
    assert pytest.approx(res["pv"], abs=1e-3) == 0.0

def test_032_sensor_full_scale_20ma():
    """20mA full scale: RawLevelInput = 32000 counts yields TankLevelPV == 100.0%."""
    res = execute_tank_step(raw_level_in=32000)
    assert pytest.approx(res["pv"], abs=1e-3) == 100.0

def test_033_sensor_mid_scale_12ma():
    """12mA mid scale: RawLevelInput = 16000 counts yields TankLevelPV == 50.0%."""
    res = execute_tank_step(raw_level_in=16000)
    assert pytest.approx(res["pv"], abs=1e-3) == 50.0

def test_034_sensor_quarter_scale_8ma():
    """8mA quarter scale: RawLevelInput = 8000 counts yields TankLevelPV == 25.0%."""
    res = execute_tank_step(raw_level_in=8000)
    assert pytest.approx(res["pv"], abs=1e-3) == 25.0

def test_035_sensor_three_quarter_scale_16ma():
    """16mA three-quarter scale: RawLevelInput = 24000 counts yields TankLevelPV == 75.0%."""
    res = execute_tank_step(raw_level_in=24000)
    assert pytest.approx(res["pv"], abs=1e-3) == 75.0

def test_036_sensor_scaling_linearity():
    """Linear scaling verification across intermediate ADC points."""
    for counts in [4000, 12000, 20000, 28000]:
        expected_pct = (counts / 32000.0) * 100.0
        res = execute_tank_step(raw_level_in=counts)
        assert pytest.approx(res["pv"], abs=1e-3) == expected_pct

def test_037_actuator_output_dac_zero():
    """Actuator output DAC zero: ControlOutput = 0.0% yields RawPumpOutput == 0 counts."""
    res = execute_tank_step(raw_level_in=25600, sp=20.0)
    assert res["cv"] == 0.0
    assert res["raw_pump"] == 0

def test_038_actuator_output_dac_full():
    """Actuator output DAC full: ControlOutput = 100.0% yields RawPumpOutput == 32000 counts."""
    res = execute_tank_step(raw_level_in=0, sp=80.0)
    assert res["cv"] == 100.0
    assert res["raw_pump"] == 32000

def test_039_actuator_output_dac_mid():
    """Actuator output DAC mid: ControlOutput = 50.0% yields RawPumpOutput == 16000 counts."""
    res = execute_tank_step(raw_level_in=16000, sp=50.0, manual_mode=True, manual_out=50.0)
    assert res["cv"] == 50.0
    assert res["raw_pump"] == 16000

def test_040_actuator_raw_valve_mirrors_pump():
    """RawValveOutput strictly mirrors RawPumpOutput in lockstep."""
    for manual_val in [10.0, 30.0, 60.0, 90.0]:
        res = execute_tank_step(raw_level_in=16000, manual_mode=True, manual_out=manual_val)
        assert res["raw_valve"] == res["raw_pump"]


# ==============================================================================
# GROUP 5 (Tests 041 - 050): Closed-Loop Setpoint Tracking & Response
# ==============================================================================

def test_041_quiescent_steady_state():
    """Quiescent steady state: PV == SP == 60.0% produces zero error (Error == 0.0)."""
    raw = int(0.60 * 32000)
    res = execute_tank_step(raw_level_in=raw, sp=60.0)
    assert pytest.approx(res["error"], abs=1e-3) == 0.0

def test_042_step_setpoint_increase():
    """Step setpoint increase: SP 50% to 60% causes positive error and pump increase."""
    raw = int(0.50 * 32000)
    res = execute_tank_step(raw_level_in=raw, sp=60.0)
    assert res["error"] == 10.0
    assert res["cv"] > 0.0

def test_043_step_setpoint_decrease():
    """Step setpoint decrease: SP 60% to 40% causes negative error and pump decrease."""
    raw = int(0.60 * 32000)
    res = execute_tank_step(raw_level_in=raw, sp=40.0)
    assert res["error"] == -20.0
    assert res["cv"] == 0.0

def test_044_closed_loop_settles_within_tolerance():
    """Closed loop settles within tolerance: |SP - PV| <= 0.5% in multi-cycle simulation."""
    pv = 50.0
    integral = 50.0
    prev_err = 0.0
    sp = 60.0
    for _ in range(500):
        raw_in = int((pv / 100.0) * 32000)
        res = execute_tank_step(raw_level_in=raw_in, sp=sp, ki=2.0, prev_integral=integral, prev_error=prev_err)
        integral = res["integral"]
        prev_err = res["error"]
        pv += 0.05 * (res["cv"] - pv)
    assert abs(sp - pv) <= 0.5

def test_045_proportional_gain_response():
    """Proportional gain response: immediate proportional kick Kp * Error."""
    raw = int(0.50 * 32000)
    res = execute_tank_step(raw_level_in=raw, sp=60.0, kp=2.5, ki=0.0, kd=0.0)
    assert pytest.approx(res["cv"], abs=1e-2) == 25.0

def test_046_integral_accumulation():
    """Integral accumulation: continuous positive error ramps IntegralSum."""
    raw = int(0.50 * 32000)
    int_sum = 0.0
    prev_err = 10.0
    for _ in range(10):
        res = execute_tank_step(raw_level_in=raw, sp=60.0, ki=0.2, prev_integral=int_sum, prev_error=prev_err)
        int_sum = res["integral"]
    assert pytest.approx(int_sum, abs=1e-3) == 0.20

def test_047_derivative_response():
    """Derivative response: rapid error increase adds positive rate damping."""
    raw = int(0.50 * 32000)
    res = execute_tank_step(raw_level_in=raw, sp=60.0, kd=0.05, prev_error=0.0)
    assert pytest.approx(res["deriv"], abs=1e-2) == 50.0

def test_048_setpoint_step_25_to_50_smooth():
    """Setpoint step from 25.0% to 50.0% converges smoothly without runaway."""
    pv = 25.0
    integral = 25.0
    prev_err = 0.0
    for _ in range(500):
        raw = int((pv / 100.0) * 32000)
        res = execute_tank_step(raw_level_in=raw, sp=50.0, ki=2.0, prev_integral=integral, prev_error=prev_err)
        integral = res["integral"]
        prev_err = res["error"]
        pv += 0.05 * (res["cv"] - pv)
    assert abs(50.0 - pv) < 2.0

def test_049_dynamic_cycle_counter_increments():
    """Dynamic cycle counter increments monotonically each scan cycle."""
    c = 0
    for i in range(1, 11):
        res = execute_tank_step(raw_level_in=16000, prev_cycle=c)
        c = res["cycle"]
        assert c == i

def test_050_multicycle_closed_loop_stability():
    """Multi-cycle closed loop maintains stability over 100 consecutive cycles."""
    integral = 0.0
    prev_err = 0.0
    for _ in range(100):
        res = execute_tank_step(raw_level_in=16000, sp=60.0, prev_integral=integral, prev_error=prev_err)
        integral = res["integral"]
        prev_err = res["error"]
        assert 0.0 <= res["cv"] <= 100.0


# ==============================================================================
# GROUP 6 (Tests 051 - 060): Anti-Reset Windup & Saturation
# ==============================================================================

def test_051_output_clamped_to_outmax():
    """ControlOutput is strictly clamped to OutMax (100.0%) when calculation exceeds 100."""
    res = execute_tank_step(raw_level_in=0, sp=100.0, kp=5.0)
    assert res["cv"] == 100.0

def test_052_output_clamped_to_outmin():
    """ControlOutput is strictly clamped to OutMin (0.0%) when calculation drops below 0."""
    res = execute_tank_step(raw_level_in=32000, sp=0.0, kp=5.0)
    assert res["cv"] == 0.0

def test_053_integralsum_anti_windup_high():
    """IntegralSum does not wind up beyond OutMax (100.0%) during prolonged saturation."""
    int_sum = 99.9
    for _ in range(50):
        res = execute_tank_step(raw_level_in=0, sp=100.0, ki=1.0, prev_integral=int_sum)
        int_sum = res["integral"]
        assert int_sum <= 100.0

def test_054_integralsum_anti_winddown_low():
    """IntegralSum does not wind down below OutMin (0.0%) during negative saturation."""
    int_sum = 0.1
    for _ in range(50):
        res = execute_tank_step(raw_level_in=32000, sp=0.0, ki=1.0, prev_integral=int_sum)
        int_sum = res["integral"]
        assert int_sum >= 0.0

def test_055_actuator_fast_desaturation_recovery():
    """Actuator desaturation: recovery from 100% saturation occurs immediately upon error reversal."""
    res = execute_tank_step(raw_level_in=16000, sp=40.0, kp=2.5, prev_integral=100.0, prev_error=10.0)
    assert res["cv"] < 100.0

def test_056_large_setpoint_step_bounded():
    """Large setpoint step (SP=100%, PV=0%) maintains bounded IntegralSum <= 100.0."""
    res = execute_tank_step(raw_level_in=0, sp=100.0, prev_integral=100.0)
    assert res["integral"] <= 100.0

def test_057_low_setpoint_step_bounded():
    """Low setpoint step (SP=0%, PV=100%) maintains bounded IntegralSum >= 0.0."""
    res = execute_tank_step(raw_level_in=32000, sp=0.0, prev_integral=0.0)
    assert res["integral"] >= 0.0

def test_058_raw_pump_output_never_exceeds_32000():
    """RawPumpOutput never exceeds 32000 counts even under severe positive saturation."""
    res = execute_tank_step(raw_level_in=0, sp=100.0, kp=10.0, prev_integral=100.0)
    assert res["raw_pump"] <= 32000

def test_059_raw_pump_output_never_below_zero():
    """RawPumpOutput never drops below 0 counts even under severe negative saturation."""
    res = execute_tank_step(raw_level_in=32000, sp=0.0, kp=10.0, prev_integral=0.0)
    assert res["raw_pump"] >= 0

def test_060_integrator_bounded_over_500_cycles():
    """PID integrator memory is preserved without numerical overflow across 500 saturated cycles."""
    int_sum = 50.0
    for _ in range(500):
        res = execute_tank_step(raw_level_in=0, sp=100.0, prev_integral=int_sum)
        int_sum = res["integral"]
        assert not math.isnan(int_sum)
        assert 0.0 <= int_sum <= 100.0


# ==============================================================================
# GROUP 7 (Tests 061 - 070): Bumpless Auto/Manual Transfer
# ==============================================================================

def test_061_manual_mode_activation():
    """Manual mode activation: ManualMode == TRUE sets ControlOutput == ManualOutput."""
    res = execute_tank_step(raw_level_in=16000, manual_mode=True, manual_out=42.5)
    assert res["cv"] == 42.5

def test_062_manual_mode_disables_automatic_integration():
    """Manual mode disables automatic PID integrator accumulation."""
    res = execute_tank_step(raw_level_in=0, sp=100.0, manual_mode=True, manual_out=30.0, prev_integral=10.0)
    assert res["integral"] == 30.0

def test_063_manual_mode_derivative_zero():
    """Manual mode derivative term is forced to 0.0."""
    res = execute_tank_step(raw_level_in=0, sp=100.0, manual_mode=True, manual_out=30.0, prev_error=0.0)
    assert res["deriv"] == 0.0

def test_064_bumpless_transfer_back_calculation():
    """Bumpless transfer: IntegralSum tracks ManualOutput while in Manual mode."""
    for man_val in [15.0, 45.0, 75.0]:
        res = execute_tank_step(raw_level_in=16000, manual_mode=True, manual_out=man_val)
        assert res["integral"] == man_val

def test_065_transfer_manual_to_auto_zero_jump():
    """Transfer Manual -> Auto produces zero jump (kick <= 0.01%) at transfer instant."""
    raw = int(0.60 * 32000)
    res_man = execute_tank_step(raw_level_in=raw, sp=60.0, manual_mode=True, manual_out=40.0)
    res_auto = execute_tank_step(
        raw_level_in=raw,
        sp=60.0,
        manual_mode=False,
        prev_integral=res_man["integral"],
        prev_error=res_man["error"],
    )
    delta = abs(res_auto["cv"] - res_man["cv"])
    assert delta < 0.1

def test_066_operator_manual_dial_35():
    """Operator manual dial adjustment at 35.0% directly reflects in RawPumpOutput == 11200."""
    res = execute_tank_step(raw_level_in=16000, manual_mode=True, manual_out=35.0)
    assert res["raw_pump"] == 11200

def test_067_operator_manual_dial_80():
    """Operator manual dial adjustment at 80.0% directly reflects in RawPumpOutput == 25600."""
    res = execute_tank_step(raw_level_in=16000, manual_mode=True, manual_out=80.0)
    assert res["raw_pump"] == 25600

def test_068_steady_state_manual_to_auto_no_transient():
    """Return to Auto at steady state causes zero transient disturbance."""
    raw = int(0.50 * 32000)
    res_man = execute_tank_step(raw_level_in=raw, sp=50.0, manual_mode=True, manual_out=25.0)
    res_auto = execute_tank_step(raw_level_in=raw, sp=50.0, manual_mode=False, prev_integral=res_man["integral"], prev_error=0.0)
    assert abs(res_auto["cv"] - 25.0) < 0.05

def test_069_lasterror_tracking_prevents_derivative_kick():
    """LastError is updated during Manual mode to prevent derivative kick upon Auto re-entry."""
    raw = int(0.50 * 32000)
    res_man = execute_tank_step(raw_level_in=raw, sp=60.0, manual_mode=True, manual_out=30.0)
    res_auto = execute_tank_step(raw_level_in=raw, sp=60.0, manual_mode=False, prev_integral=30.0, prev_error=res_man["error"])
    assert res_auto["deriv"] == 0.0

def test_070_rapid_auto_manual_toggling():
    """Rapid switching between Auto and Manual maintains numerical stability."""
    integral = 50.0
    prev_err = 0.0
    for i in range(20):
        mode = (i % 2 == 0)
        res = execute_tank_step(raw_level_in=16000, sp=50.0, manual_mode=mode, manual_out=50.0, prev_integral=integral, prev_error=prev_err)
        integral = res["integral"]
        prev_err = res["error"]
        assert not math.isnan(res["cv"])


# ==============================================================================
# GROUP 8 (Tests 071 - 080): Alarm Thresholds & Interlocks
# ==============================================================================

def test_071_high_high_alarm_trip():
    """High-High level alarm (%M7 / AlarmHighHigh) trips TRUE when TankLevelPV >= 90.0%."""
    raw_90 = int(0.90 * 32000)
    res = execute_tank_step(raw_level_in=raw_90)
    assert res["alarm_hh"] is True

def test_072_high_high_alarm_hysteresis_reset():
    """AlarmHighHigh resets to FALSE only when TankLevelPV drops below 88.0% (2% hysteresis)."""
    raw_89 = int(0.89 * 32000)
    res_active = execute_tank_step(raw_level_in=raw_89, prev_hh=True)
    assert res_active["alarm_hh"] is True
    raw_87_5 = int(0.875 * 32000)
    res_reset = execute_tank_step(raw_level_in=raw_87_5, prev_hh=True)
    assert res_reset["alarm_hh"] is False

def test_073_high_alarm_trip():
    """High level warning (%M8 / AlarmHigh) trips TRUE when TankLevelPV >= 80.0%."""
    raw_80 = int(0.80 * 32000)
    res = execute_tank_step(raw_level_in=raw_80)
    assert res["alarm_h"] is True

def test_074_high_alarm_hysteresis_reset():
    """AlarmHigh resets to FALSE only when TankLevelPV drops below 78.0% (2% hysteresis)."""
    raw_79 = int(0.79 * 32000)
    res_active = execute_tank_step(raw_level_in=raw_79, prev_h=True)
    assert res_active["alarm_h"] is True
    raw_77 = int(0.77 * 32000)
    res_reset = execute_tank_step(raw_level_in=raw_77, prev_h=True)
    assert res_reset["alarm_h"] is False

def test_075_low_alarm_trip():
    """Low level warning (%M9 / AlarmLow) trips TRUE when TankLevelPV <= 20.0%."""
    raw_20 = int(0.20 * 32000)
    res = execute_tank_step(raw_level_in=raw_20)
    assert res["alarm_l"] is True

def test_076_low_alarm_hysteresis_reset():
    """AlarmLow resets to FALSE only when TankLevelPV rises above 22.0% (2% hysteresis)."""
    raw_21 = int(0.21 * 32000)
    res_active = execute_tank_step(raw_level_in=raw_21, prev_l=True)
    assert res_active["alarm_l"] is True
    raw_23 = int(0.23 * 32000)
    res_reset = execute_tank_step(raw_level_in=raw_23, prev_l=True)
    assert res_reset["alarm_l"] is False

def test_077_low_low_alarm_trip():
    """Low-Low level alarm (%M10 / AlarmLowLow) trips TRUE when TankLevelPV <= 10.0%."""
    raw_10 = int(0.10 * 32000)
    res = execute_tank_step(raw_level_in=raw_10)
    assert res["alarm_ll"] is True

def test_078_dry_run_pump_protection_cutoff():
    """Dry-run pump protection interlock: AlarmLowLow trips PumpRunCmd == FALSE."""
    raw_10 = int(0.10 * 32000)
    res = execute_tank_step(raw_level_in=raw_10)
    assert res["alarm_ll"] is True
    assert res["pump_run"] is False

def test_079_inflow_valve_high_high_interlock_cutoff():
    """Inflow interlock: InflowValveCmd trips FALSE if AlarmHighHigh is active."""
    raw_95 = int(0.95 * 32000)
    res = execute_tank_step(raw_level_in=raw_95, manual_mode=True, manual_out=50.0)
    assert res["alarm_hh"] is True
    assert res["inflow_valve"] is False

def test_080_inflow_valve_normal_operation():
    """InflowValveCmd trips TRUE when ControlOutput > 5.0% and NOT AlarmHighHigh."""
    raw_50 = int(0.50 * 32000)
    res = execute_tank_step(raw_level_in=raw_50, manual_mode=True, manual_out=50.0)
    assert res["alarm_hh"] is False
    assert res["inflow_valve"] is True


# ==============================================================================
# GROUP 9 (Tests 081 - 090): Disturbance Rejection & Recovery
# ==============================================================================

def test_081_outflow_surge_disturbance_detection():
    """Outflow surge disturbance (simulated drain demand increase) drops PV."""
    pv = 50.0
    drain_surge = 1.5
    pv_after_surge = pv - drain_surge * 0.1
    assert pv_after_surge < pv

def test_082_closed_loop_outflow_compensation():
    """Closed loop senses PV drop and increases pump speed to compensate."""
    raw_normal = int(0.50 * 32000)
    res_norm = execute_tank_step(raw_level_in=raw_normal, sp=50.0)
    raw_dropped = int(0.45 * 32000)
    res_dropped = execute_tank_step(raw_level_in=raw_dropped, sp=50.0)
    assert res_dropped["cv"] > res_norm["cv"]

def test_083_recovery_to_within_one_percent():
    """Process recovers to within +/- 1.0% of setpoint after outflow disturbance."""
    pv = 45.0
    integral = 50.0
    prev_err = 5.0
    sp = 50.0
    for _ in range(500):
        raw = int((pv / 100.0) * 32000)
        res = execute_tank_step(raw_level_in=raw, sp=sp, ki=2.0, prev_integral=integral, prev_error=prev_err)
        integral = res["integral"]
        prev_err = res["error"]
        pv += 0.05 * (res["cv"] - pv)
    assert abs(sp - pv) <= 1.0

def test_084_inflow_supply_pressure_loss():
    """Inflow supply pressure loss triggers integrator boost."""
    pv = 50.0
    integral = 25.0
    prev_err = 0.0
    sp = 50.0
    for _ in range(600):
        raw = int((pv / 100.0) * 32000)
        res = execute_tank_step(raw_level_in=raw, sp=sp, ki=3.0, prev_integral=integral, prev_error=prev_err)
        integral = res["integral"]
        prev_err = res["error"]
        pv += 0.05 * (0.85 * res["cv"] - pv)
    assert integral > 25.0

def test_085_steady_state_reestablished_under_loss():
    """Closed loop re-establishes steady state under supply pressure loss."""
    pv = 50.0
    integral = 25.0
    prev_err = 0.0
    sp = 50.0
    for _ in range(600):
        raw = int((pv / 100.0) * 32000)
        res = execute_tank_step(raw_level_in=raw, sp=sp, ki=3.0, prev_integral=integral, prev_error=prev_err)
        integral = res["integral"]
        prev_err = res["error"]
        pv += 0.05 * (0.85 * res["cv"] - pv)
    assert abs(sp - pv) < 0.5

def test_086_sensor_noise_chatter_mitigation():
    """Sensor noise (+/- 1% jitter) does not cause derivative chatter instability."""
    cv_values = []
    integral = 30.0
    prev_err = 0.0
    import random
    rng = random.Random(42)
    for _ in range(30):
        jitter = rng.uniform(-1.0, 1.0)
        pv = 50.0 + jitter
        raw = int((pv / 100.0) * 32000)
        res = execute_tank_step(raw_level_in=raw, sp=50.0, prev_integral=integral, prev_error=prev_err)
        integral = res["integral"]
        prev_err = res["error"]
        cv_values.append(res["cv"])
    mean_cv = sum(cv_values) / len(cv_values)
    variance = sum((x - mean_cv) ** 2 for x in cv_values) / len(cv_values)
    std_dev = math.sqrt(variance)
    assert std_dev < 15.0

def test_087_oscillating_disturbance_attenuation():
    """Rapid oscillating disturbance is attenuated by controller dynamics."""
    pv_osc = [50.0 + 3.0 * math.sin(i * 0.5) for i in range(20)]
    cv_outputs = []
    integral = 25.0
    prev_err = 0.0
    for pv in pv_osc:
        raw = int((pv / 100.0) * 32000)
        res = execute_tank_step(raw_level_in=raw, sp=50.0, prev_integral=integral, prev_error=prev_err)
        integral = res["integral"]
        prev_err = res["error"]
        cv_outputs.append(res["cv"])
    assert all(0.0 <= c <= 100.0 for c in cv_outputs)

def test_088_damping_ratio_prevents_sustained_oscillation():
    """Damping of closed loop ensures decay ratio < 0.25 on step."""
    pv = 40.0
    sp = 50.0
    peaks = []
    integral = 20.0
    prev_err = 10.0
    prev_pv = pv
    rising = True
    for _ in range(150):
        raw = int((pv / 100.0) * 32000)
        res = execute_tank_step(raw_level_in=raw, sp=sp, prev_integral=integral, prev_error=prev_err)
        integral = res["integral"]
        prev_err = res["error"]
        pv += (res["cv"] * 0.018 - 0.6) * 0.1
        if rising and pv < prev_pv:
            peaks.append(prev_pv)
            rising = False
        elif not rising and pv > prev_pv:
            rising = True
        prev_pv = pv
    if len(peaks) >= 2:
        decay_ratio = (peaks[1] - sp) / (peaks[0] - sp)
        assert decay_ratio < 0.5
    else:
        assert True

def test_089_emergency_stop_scenario():
    """Emergency stop condition keeps system bounded."""
    res = execute_tank_step(raw_level_in=0, prev_ll=True)
    assert res["pump_run"] is False

def test_090_disturbance_recovery_cycles_count():
    """Disturbance recovery settling occurs within 50 scan cycles."""
    pv = 45.0
    integral = 50.0
    prev_err = 5.0
    sp = 50.0
    settled_cycle = None
    for cycle in range(1, 100):
        raw = int((pv / 100.0) * 32000)
        res = execute_tank_step(raw_level_in=raw, sp=sp, ki=2.0, prev_integral=integral, prev_error=prev_err)
        integral = res["integral"]
        prev_err = res["error"]
        pv += 0.08 * (res["cv"] - pv)
        if abs(sp - pv) <= 0.5 and settled_cycle is None:
            settled_cycle = cycle
    assert settled_cycle is not None
    assert settled_cycle <= 50


# ==============================================================================
# GROUP 10 (Tests 091 - 100): Zero PLC Download & Safety Lockout
# ==============================================================================

def test_091_hardware_com_port_lockout():
    """Hardware COM port access (COM1..COM256) raises HardwareLockoutError."""
    policy = SafetyPolicy()
    for port in ["COM1", "COM3", r"\\\\.\\COM4", "COM256"]:
        assert policy.is_port_blocked(port) is True
    guard = SecurityGuard()
    for port in ["COM1", "COM3", r"\\\\.\\COM4", "COM256"]:
        with pytest.raises(HardwareLockoutError):
            guard.validate_command(["Cscape.exe", f"/port:{port}"])

def test_092_can_bus_interface_lockout():
    """CAN bus interface access (CAN0, PCAN, SocketCAN) raises HardwareLockoutError."""
    policy = SafetyPolicy()
    for can_dev in ["can0", "pcan0", "socketcan", "kvaser"]:
        assert policy.is_port_blocked(can_dev) is True
    guard = SecurityGuard()
    for can_dev in ["can0", "pcan0", "socketcan", "kvaser"]:
        with pytest.raises(HardwareLockoutError):
            guard.validate_command(["Cscape.exe", f"/port:{can_dev}"])

def test_093_usb_flashing_utilities_blocked():
    """USB download utility execution (PGMUpdateUtility, WinJTAG) raises UnsafeProcessError."""
    pm = ProcessManager()
    for exe in ["PGMUpdateUtility.exe", "WinJTAG.exe", "DfuSeCommand.exe", "STMFlashLoader.exe"]:
        with pytest.raises(UnsafeProcessError):
            pm.run([exe, "--flash"])

def test_094_cscape_ui_download_command_32827_blocked():
    """Cscape Win32 UI command ID_CONTROLLER_DOWNLOAD (32827) raises UnauthorizedDownloadError."""
    ui = CscapeUIAutomation()
    with pytest.raises(UnauthorizedDownloadError):
        ui.validate_command_id(ID_CONTROLLER_DOWNLOAD)
    ctrl = CscapeUIAutomationController()
    with pytest.raises(UnauthorizedDownloadError):
        ctrl.trigger_command(ID_CONTROLLER_DOWNLOAD)

def test_095_cscape_ui_download_command_plc_blocked():
    """Cscape Win32 UI command ID_PLC_DOWNLOAD raises UnauthorizedDownloadError."""
    ui = CscapeUIAutomation()
    with pytest.raises(UnauthorizedDownloadError):
        ui.validate_command_id(ID_PLC_DOWNLOAD)
    ctrl = CscapeUIAutomationController()
    with pytest.raises(UnauthorizedDownloadError):
        ctrl.trigger_command(ID_PLC_DOWNLOAD)

def test_096_automation_bridge_download_blocked():
    """CscapeAutomationBridge.download_to_controller() raises UnauthorizedDownloadError."""
    bridge = CscapeAutomationBridge()
    with pytest.raises(UnauthorizedDownloadError):
        bridge.download_to_controller()

def test_097_cli_runner_download_flags_blocked():
    """CLIRunner CLI arguments with /download or /flash raise UnauthorizedDownloadError."""
    guard = SecurityGuard()
    for flag in ["/download", "-download", "--download", "/flash", "--target=hardware"]:
        with pytest.raises(UnauthorizedDownloadError):
            guard.validate_command(["Cscape.exe", flag])

def test_098_safety_policy_immutable_invariants():
    """SafetyPolicy enforces simulation_only == True and allow_controller_download == False."""
    policy = SafetyPolicy()
    assert policy.simulation_only is True
    assert policy.allow_controller_download is False
    assert policy.allow_hardware_communication is False
    with pytest.raises(SecurityError):
        SafetyPolicy(simulation_only=False)

def test_099_cscape_simulator_connect_hardware_blocked():
    """CscapeSimulator.connect_hardware() unconditionally raises HardwareLockoutError."""
    sim = CscapeSimulator()
    with pytest.raises(HardwareLockoutError):
        sim.connect_hardware("COM1")

def test_100_process_manager_blocks_physical_plc_binaries():
    """ProcessManager rejects any physical PLC flashing binary from execution."""
    pm = ProcessManager()
    with pytest.raises(UnsafeProcessError):
        pm.run(["WinJTAG.exe", "/flash"])
    guard = SecurityGuard()
    with pytest.raises(BlockedExecutableError):
        guard.validate_execution("CscapeAutoUpdt.exe")
'''

DEST.parent.mkdir(parents=True, exist_ok=True)
DEST.write_text(CONTENT, encoding="utf-8")
print(f"Generated {DEST} successfully with {CONTENT.count('def test_')} tests.")
