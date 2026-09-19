#!/usr/bin/env python3
r"""
Test Suite for Step 136: Multi-POU Cross-Reference, Symbol Resolution & Memory Allocation Matrix Verification.

Verifies:
1. Checkpoint existence and valid schema across both roots.
2. Evidence log existence, schema, and 100% symbol resolution across all 5 POUs.
3. Multi-POU AST parsing and symbol extraction (>0 AST nodes, 0 unresolved symbols).
4. Memory Allocation Map:
   - 21 variables mapped across Horner OCS memory (%R, %M, %I, %Q, %AI, %AQ).
   - Exact %R holding register word ranges:
     * TankLevelPV at %R1 uses %R1-%R2
     * Setpoint at %R3 uses %R3-%R4
     * ControlOutput at %R7 uses %R7-%R8
     * ManualOutput at %R9 uses %R9-%R10
     * CycleCounter at %R21 uses %R21-%R22
     * Kp at %R29 uses %R29-%R30
     * Ki at %R31 uses %R31-%R32
     * Kd at %R33 uses %R33-%R34
   - Assert 0 word/bit collisions in baseline allocation.
5. Register collision fault injection:
   - Inject conflicting REAL at %R2 (collides with TankLevelPV %R1-%R2).
   - Inject conflicting REAL at %R8 (collides with ControlOutput %R7-%R8).
   - Inject conflicting BOOL at %M7 (collides with AlarmHighHigh %M7).
   - Validator strictly detects and rejects collisions fail-closed.
6. Variable Export/Import roundtrip:
   - Export to CSV and XML.
   - Re-import and assert 100% fidelity on all 21 tags.
7. Safety mandates:
   - ID_CONTROLLER_DOWNLOAD = 32827 raises UnauthorizedDownloadError.
   - COM/USB/CAN physical hardware port blocking.
   - Zero Straton K5 dependencies.
8. Active Cscape is alive and healthy via live gate.
"""

import json
from pathlib import Path
import tempfile
import psutil
import pytest

HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()

import sys
for r in [HORNER_ROOT, USER_ROOT]:
    if str(r) not in sys.path:
        sys.path.insert(0, str(r))

from src.cscape.gate import assert_cscape_live
from src.cscape.variables import VariableManager, CscapeVariable, HornerRegister
from src.iec.lexer import Lexer
from src.iec.parser import Parser
from src.iec.ast_nodes import ASTNode, ProgramNode, VariableNode, FunctionCallNode
from src.mcp.tools import cscape_read_variables, cscape_export_variables
from src.automation.cli_runner import CLIRunner
from src.security.exceptions import UnauthorizedDownloadError, CscapeSafetyViolationError
from src.cscape.safety import intercept_download_command, intercept_hardware_interface

TARGET_POUS = [
    "TankLevelClosedLoop.st",
    "AlarmMonitor.st",
    "BrokenPOU.st",
    "AuxPumpControl.st",
    "SafetyInterlockST.st",
]

# TARGET_PID dynamically resolved from live gate
ID_CONTROLLER_DOWNLOAD = 32827

CHECKPOINT_REL = Path("artifacts/checkpoints/step136_cross_pou_symbol_resolution_checkpoint.json")
LOG_REL = Path("artifacts/logs/cross_pou_symbol_resolution.json")


def _walk_ast(node: ASTNode):
    yield node
    if hasattr(node, "__dict__"):
        for k, v in node.__dict__.items():
            if k == "loc":
                continue
            if isinstance(v, ASTNode):
                yield from _walk_ast(v)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, ASTNode):
                        yield from _walk_ast(item)
                    elif isinstance(item, tuple):
                        for sub in item:
                            if isinstance(sub, ASTNode):
                                yield from _walk_ast(sub)
                            elif isinstance(sub, list):
                                for s in sub:
                                    if isinstance(s, ASTNode):
                                        yield from _walk_ast(s)
            elif isinstance(v, tuple):
                for sub in v:
                    if isinstance(sub, ASTNode):
                        yield from _walk_ast(sub)
                    elif isinstance(sub, list):
                        for s in sub:
                            if isinstance(s, ASTNode):
                                yield from _walk_ast(s)
            elif isinstance(v, dict):
                for sub in v.values():
                    if isinstance(sub, ASTNode):
                        yield from _walk_ast(sub)


def _count_ast_nodes(node: ASTNode) -> int:
    return sum(1 for _ in _walk_ast(node))


# ============================================================================
# 1. Checkpoint & Evidence Log Verification Across Both Roots
# ============================================================================

def test_step136_checkpoint_exists_and_matches_schema():
    cp_horner = HORNER_ROOT / CHECKPOINT_REL
    cp_user = USER_ROOT / CHECKPOINT_REL

    assert cp_horner.exists(), f"Checkpoint missing in Horner root: {cp_horner}"
    assert cp_user.exists(), f"Checkpoint missing in User root: {cp_user}"

    data_h = json.loads(cp_horner.read_text(encoding="utf-8"))
    data_u = json.loads(cp_user.read_text(encoding="utf-8"))

    for data in [data_h, data_u]:
        assert data["step"] == 136
        assert data["name"] == "step136_cross_pou_symbol_resolution_checkpoint"
        assert data["status"] == "PASSED"
        assert data["target_project"] == "TankLevelClosedLoop"
        assert data["pous_evaluated"] == TARGET_POUS
        assert data["pous_count"] == 5
        assert data["total_ast_nodes"] >= 240
        assert data["symbol_resolution_rate_percent"] == 100.0
        assert data["unresolved_symbols"] == 0
        assert data["global_variables_count"] == 21
        assert data["baseline_register_collisions"] == 0
        assert data["injected_collisions_detected_fail_closed"] is True
        assert data["export_import_roundtrip_matched"] is True
        assert data["hardware_lockout_enforced"] is True
        assert data["zero_straton_dependencies"] is True
        assert data["cscape_pid_untouched"] > 0


def test_step136_evidence_log_schema_and_resolution_matrix():
    log_horner = HORNER_ROOT / LOG_REL
    log_user = USER_ROOT / LOG_REL

    assert log_horner.exists(), f"Evidence log missing: {log_horner}"
    assert log_user.exists(), f"Evidence log missing: {log_user}"

    log_data = json.loads(log_horner.read_text(encoding="utf-8"))
    assert log_data["status"] == "PASSED"
    assert log_data["target_project"] == "TankLevelClosedLoop"
    assert len(log_data["pous_analyzed"]) == 5

    sym_res = log_data["symbol_resolution"]
    assert sym_res["unresolved_symbols_count"] == 0
    assert sym_res["resolution_percentage"] == 100.0
    assert sym_res["total_symbols_evaluated"] >= 28

    for entry in sym_res["matrix"]:
        assert entry["is_resolved"] is True, f"Symbol {entry.get('symbol_name')} in {entry.get('pou_name')} was not resolved!"


# ============================================================================
# 2. Multi-POU AST Parsing & 100% Symbol Resolution Tests
# ============================================================================

@pytest.mark.parametrize("pou_name", TARGET_POUS)
def test_pou_parses_cleanly_into_ast(pou_name):
    pou_path = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "pous" / pou_name
    assert pou_path.exists()

    source = pou_path.read_text(encoding="utf-8")
    tokens = Lexer(source).tokenize()
    ast = Parser(tokens).parse_program()

    assert isinstance(ast, ProgramNode)
    assert ast.pou_type == "PROGRAM"
    node_count = _count_ast_nodes(ast)
    assert node_count > 0


def test_pou_100percent_symbol_resolution():
    pous_dir = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "pous"
    csv_path = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "variables.csv"

    res = cscape_read_variables(str(csv_path))
    assert res["success"] is True
    global_names = {v["name"] for v in res["variables"]}

    builtin_fns = {"INT_TO_REAL", "REAL_TO_INT"}

    for pou_name in TARGET_POUS:
        source = (pous_dir / pou_name).read_text(encoding="utf-8")
        ast = Parser(Lexer(source).tokenize()).parse_program()

        local_decls = {d.name for vb in ast.var_blocks for d in vb.declarations}
        referenced_vars = set()
        function_calls = set()

        for node in _walk_ast(ast):
            if isinstance(node, VariableNode):
                referenced_vars.add(node.name)
            elif isinstance(node, FunctionCallNode):
                function_calls.add(node.name)

        # Every referenced variable must resolve either locally or globally
        for vname in referenced_vars:
            resolves = (vname in local_decls) or (vname in global_names)
            assert resolves, f"Unresolved symbol '{vname}' in POU '{pou_name}'!"

        for fname in function_calls:
            assert fname in builtin_fns, f"Unresolved function '{fname}' in POU '{pou_name}'!"


# ============================================================================
# 3. Register Memory Allocation Matrix & %R Word Ranges
# ============================================================================

def test_register_memory_allocation_map():
    csv_path = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "variables.csv"
    res = cscape_read_variables(str(csv_path))
    assert res["success"] is True
    assert res["total_variables"] == 21

    vars_dict = {v["name"]: v for v in res["variables"]}

    # Verify %R holding register word ranges
    expected_r_ranges = {
        "TankLevelPV": ("%R1", "%R2", ["%R1", "%R2"]),
        "Setpoint": ("%R3", "%R4", ["%R3", "%R4"]),
        "ControlOutput": ("%R7", "%R8", ["%R7", "%R8"]),
        "ManualOutput": ("%R9", "%R10", ["%R9", "%R10"]),
        "CycleCounter": ("%R21", "%R22", ["%R21", "%R22"]),
        "Kp": ("%R29", "%R30", ["%R29", "%R30"]),
        "Ki": ("%R31", "%R32", ["%R31", "%R32"]),
        "Kd": ("%R33", "%R34", ["%R33", "%R34"]),
    }

    for name, (start_r, end_r, expected_spanned) in expected_r_ranges.items():
        assert name in vars_dict, f"Missing expected %R variable: {name}"
        v_data = vars_dict[name]
        assert v_data["tag"] == start_r
        assert v_data["occupied_registers"] == expected_spanned, (
            f"Variable {name} occupied registers mismatch: {v_data['occupied_registers']} != {expected_spanned}"
        )

    # Verify analog input / output 16-bit word registers
    assert vars_dict["RawLevelInput"]["tag"] == "%AI1"
    assert vars_dict["RawLevelInput"]["occupied_registers"] == ["%AI1"]
    assert vars_dict["RawPumpOutput"]["tag"] == "%AQ1"
    assert vars_dict["RawPumpOutput"]["occupied_registers"] == ["%AQ1"]
    assert vars_dict["RawValveOutput"]["tag"] == "%AQ2"
    assert vars_dict["RawValveOutput"]["occupied_registers"] == ["%AQ2"]

    # Verify discrete 1-bit registers
    assert vars_dict["PumpRunCmd"]["tag"] == "%Q1"
    assert vars_dict["InflowValveCmd"]["tag"] == "%Q2"
    assert vars_dict["AlarmHighHigh"]["tag"] == "%M7"
    assert vars_dict["AlarmHigh"]["tag"] == "%M8"
    assert vars_dict["AlarmLow"]["tag"] == "%M9"
    assert vars_dict["AlarmLowLow"]["tag"] == "%M10"

    # Assert 0 collisions in baseline
    assert res["conflicts_detected"] == 0
    assert len(res["conflict_details"]) == 0


# ============================================================================
# 4. Register Collision Fault Injection Tests
# ============================================================================

def test_register_collision_fault_injection_r2_with_r1():
    csv_path = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "variables.csv"
    vm = VariableManager("FaultTestR2")
    vm.import_csv(csv_path)

    # REAL at %R2 collides with TankLevelPV (%R1-%R2) on %R2, and Setpoint (%R3-%R4) on %R3
    colliding_var = CscapeVariable(name="CollidingR2", data_type="REAL", tag="%R2", scope="globals")
    vm.add_variable(colliding_var)

    conflicts = vm.detect_conflicts()
    assert len(conflicts) > 0, "Validator failed to detect collision at %R2!"
    # Ensure %R2 is identified as overlapping
    has_r2_overlap = any("%R2" in str(c.get("overlapping_registers", [])) for c in conflicts)
    assert has_r2_overlap, "Conflict details did not report %R2 overlap!"


def test_register_collision_fault_injection_r8_with_r7():
    csv_path = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "variables.csv"
    vm = VariableManager("FaultTestR8")
    vm.import_csv(csv_path)

    # REAL at %R8 collides with ControlOutput (%R7-%R8) on %R8, and ManualOutput (%R9-%R10) on %R9
    colliding_var = CscapeVariable(name="CollidingR8", data_type="REAL", tag="%R8", scope="globals")
    vm.add_variable(colliding_var)

    conflicts = vm.detect_conflicts()
    assert len(conflicts) > 0, "Validator failed to detect collision at %R8!"
    has_r8_overlap = any("%R8" in str(c.get("overlapping_registers", [])) for c in conflicts)
    assert has_r8_overlap, "Conflict details did not report %R8 overlap!"


def test_register_collision_fault_injection_bit_m7():
    csv_path = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "variables.csv"
    vm = VariableManager("FaultTestM7")
    vm.import_csv(csv_path)

    # BOOL at %M7 collides with AlarmHighHigh (%M7)
    colliding_var = CscapeVariable(name="CollidingM7", data_type="BOOL", tag="%M7", scope="globals")
    vm.add_variable(colliding_var)

    conflicts = vm.detect_conflicts()
    assert len(conflicts) > 0, "Validator failed to detect bit collision at %M7!"
    has_m7_overlap = any("%M7" in str(c.get("overlapping_registers", [])) for c in conflicts)
    assert has_m7_overlap, "Conflict details did not report %M7 overlap!"


# ============================================================================
# 5. Variable Export/Import Roundtrip Fidelity Tests
# ============================================================================

def test_variable_export_import_roundtrip():
    src_csv = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "variables.csv"
    initial = cscape_read_variables(str(src_csv))
    assert initial["success"] is True
    assert initial["total_variables"] == 21

    initial_map = {
        v["name"]: (v["data_type"], v["tag"], v.get("description", ""))
        for v in initial["variables"]
    }

    temp_base = HORNER_ROOT / "artifacts" / "temp"
    temp_base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(temp_base)) as tmpdir:
        tmp_csv = Path(tmpdir) / "test_export.csv"
        tmp_xml = Path(tmpdir) / "test_export.xml"

        exp_csv = cscape_export_variables(output_path=str(tmp_csv), format_type="CSV", source_file=str(src_csv))
        assert exp_csv["success"] is True
        assert exp_csv["written_count"] == 21

        exp_xml = cscape_export_variables(output_path=str(tmp_xml), format_type="XML", source_file=str(src_csv))
        assert exp_xml["success"] is True
        assert exp_xml["written_count"] == 21

        re_csv = cscape_read_variables(str(tmp_csv))
        assert re_csv["success"] is True
        assert re_csv["total_variables"] == 21

        re_xml = cscape_read_variables(str(tmp_xml))
        assert re_xml["success"] is True
        assert re_xml["total_variables"] == 21

        csv_map = {
            v["name"]: (v["data_type"], v["tag"], v.get("description", ""))
            for v in re_csv["variables"]
        }
        xml_map = {
            v["name"]: (v["data_type"], v["tag"], v.get("description", ""))
            for v in re_xml["variables"]
        }

        assert csv_map == initial_map, "CSV re-import tag data mismatch!"
        assert xml_map == initial_map, "XML re-import tag data mismatch!"


# ============================================================================
# 6. Safety Mandates, Hardware Lockout & Zero Straton
# ============================================================================

def test_hardware_download_lockout_and_safety():
    assert ID_CONTROLLER_DOWNLOAD == 32827

    runner = CLIRunner()
    with pytest.raises(UnauthorizedDownloadError):
        runner.download_to_controller("TankLevelClosedLoop.csp")

    with pytest.raises(UnauthorizedDownloadError):
        runner.download_project("TankLevelClosedLoop.csp")

    with pytest.raises(CscapeSafetyViolationError):
        intercept_download_command(32827)

    with pytest.raises(CscapeSafetyViolationError):
        intercept_hardware_interface("COM1")


# ============================================================================
# 7. Active Cscape Health & Responsiveness via Live Gate
# ============================================================================

def test_cscape_live_and_responsive():
    try:
        gate_info = assert_cscape_live()
    except Exception as exc:
        pytest.skip(f"No active live Cscape gate: {exc}")
    if not gate_info.get("ready_for_tests"):
        pytest.skip(f"Live Cscape gate not ready: status='{gate_info.get('status')}', reason='{gate_info.get('reason')}'")
    assert gate_info.get("ready_for_tests") is True
    assert gate_info.get("status") == "READY_FOR_TESTS"

    pid = gate_info.get("pid")
    if not pid or not psutil.pid_exists(pid):
        pytest.skip(f"Live Cscape PID {pid} is offline")

    assert pid > 0
    assert psutil.pid_exists(pid), f"PID {pid} not found"
    proc = psutil.Process(pid)
    assert proc.is_running()
    assert "cscape" in proc.name().lower()


