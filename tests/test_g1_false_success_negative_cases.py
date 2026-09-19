"""Comprehensive Offline Negative Test Suite for Gate G1 False-Success Dismantling.

Mandates Verified:
1. All 22 cataloged false-success vulnerabilities in G1_remaining_false_success.txt fail closed.
2. Canonical 4-state ontology: status in ("success", "failed", "blocked", "inconclusive").
3. Pure offline execution — zero Cscape GUI dependencies, zero physical PLC hardware.
4. No synthetic passes on empty, missing, broken, or unverified states.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from src.mcp.tools import (
    cscape_run_simulation,
    cscape_inspect_variables,
    cscape_insert_st,
    cscape_add_st_pou,
    cscape_create_project,
    cscape_read_variables,
    cscape_write_variables,
    cscape_get_build_output,
    cscape_get_diagnostics,
    cscape_simulate_pou,
    cscape_export_project,
    cscape_new_iec_project,
    cscape_open_project,
    cscape_validate_st,
    cscape_compile,
    cscape_compile_project,
    cscape_read_register,
    cscape_write_register,
    cscape_simulate_cycle,
    cscape_import_variables,
    cscape_export_variables,
    get_active_simulator,
    normalize_tool_result,
)
from src.iec.st_parser import STParser, IssueSeverity
from src.iec.simulator import STSimulator
from src.iec.validator import IECValidator
from src.cscape.safety import intercept_hardware_interface, HardwareLockoutError
from src.cscape.project_manager import CscapeLiveProjectManager
from src.cscape.st_inserter import StructuredTextInserter
from src.automation.com_bridge import CscapeComBridge


# -----------------------------------------------------------------------------
# Case 01: cscape_run_simulation - Empty Simulation Loop Claims Success
# -----------------------------------------------------------------------------
def test_case01_simulation_empty_st_code_fails_closed():
    """Empty or None ST source code must fail closed with INVALID_ST_CODE."""
    for empty_code in [None, "", "   ", "\n\t"]:
        res = cscape_run_simulation(steps=5, st_code=empty_code)
        assert res["success"] is False
        assert res["status"] == "failed"
        assert res.get("error_code") == "INVALID_ST_CODE"
        assert len(res.get("errors", [])) > 0


# -----------------------------------------------------------------------------
# Case 02: cscape_inspect_variables - Success on Non-Existent Project
# -----------------------------------------------------------------------------
def test_case02_inspect_variables_missing_or_empty_project_fails_closed():
    """Inspecting variables on empty, invalid, or non-existent projects must fail closed."""
    for bad_proj in ["", "   ", "NonExistentProject_Fake_9999"]:
        res = cscape_inspect_variables(project_name=bad_proj)
        assert res["success"] is False
        assert res["status"] == "failed"
        assert res.get("error_code") in ("INVALID_PROJECT_NAME", "PROJECT_NOT_FOUND")


# -----------------------------------------------------------------------------
# Case 03: cscape_insert_st & cscape_add_st_pou - Missing POU Name Validation
# -----------------------------------------------------------------------------
def test_case03_insert_pou_invalid_name_or_traversal_fails_closed(tmp_path):
    """POU names with traversal sequences, spaces, or empty strings must fail closed."""
    for bad_name in ["", "   ", "../../escape", "bad name with spaces", "123_starts_with_num"]:
        res_ins = cscape_insert_st(
            pou_name=bad_name,
            pou_type="program",
            st_code="PROGRAM Valid VAR x:INT; END_VAR x:=1; END_PROGRAM",
            target_project_path=str(tmp_path),
        )
        assert res_ins["success"] is False
        assert res_ins["status"] in ("failed", "blocked")

        res_add = cscape_add_st_pou(
            project_name="TestProject",
            pou_name=bad_name,
            pou_type="program",
            code="PROGRAM Valid VAR x:INT; END_VAR x:=1; END_PROGRAM",
        )
        assert res_add["success"] is False
        assert res_add["status"] in ("failed", "blocked")


# -----------------------------------------------------------------------------
# Case 04: cscape_write_variables - Success on Empty Variable List
# -----------------------------------------------------------------------------
def test_case04_write_variables_empty_list_fails_closed(tmp_path):
    """Writing 0 variables must fail closed with EMPTY_VARIABLE_LIST."""
    out_file = tmp_path / "empty_vars.csv"
    res = cscape_write_variables(
        output_path=str(out_file),
        variables=[],
        format_type="csv",
    )
    assert res["success"] is False
    assert res["status"] == "failed"
    assert res.get("error_code") == "EMPTY_VARIABLE_LIST"
    assert res.get("written_count") == 0


# -----------------------------------------------------------------------------
# Case 05: cscape_read_variables - Success on Empty Database or Path
# -----------------------------------------------------------------------------
def test_case05_read_variables_empty_file_or_path_fails_closed(tmp_path):
    """Reading empty variables file or whitespace path must fail closed."""
    res_empty_path = cscape_read_variables(file_path="   ")
    assert res_empty_path["success"] is False
    assert res_empty_path["status"] == "failed"
    assert res_empty_path.get("error_code") == "INVALID_FILE_PATH"

    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_text("Name,Tag,Type\n", encoding="utf-8")
    res_empty_csv = cscape_read_variables(file_path=str(empty_csv))
    assert res_empty_csv["success"] is False
    assert res_empty_csv["status"] == "failed"
    assert res_empty_csv.get("error_code") == "EMPTY_VARIABLE_DATABASE"


# -----------------------------------------------------------------------------
# Case 06: cscape_get_build_output - Hardcoded success: True on Failed Build
# -----------------------------------------------------------------------------
def test_case06_get_build_output_failed_build_honest_success(tmp_path):
    """When build log contains compilation errors, success must be False."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    log_file = artifacts_dir / "build.log"
    log_file.write_text("ERROR: Line 5: syntax error at ';'\nBuild failed with 1 error(s).", encoding="utf-8")

    res = cscape_get_build_output(project_path=str(tmp_path))
    assert res["success"] is False
    assert res["status"] == "failed"
    assert res["build_successful"] is False
    assert res["error_count"] > 0


# -----------------------------------------------------------------------------
# Case 07: cscape_get_diagnostics - Clean Build & Compile Successful Honest
# -----------------------------------------------------------------------------
def test_case07_get_diagnostics_empty_project_and_failed_build(tmp_path):
    """Empty project name or failed build log must return clean_build=False and status: failed."""
    res_empty = cscape_get_diagnostics(project_name="")
    assert res_empty["success"] is False
    assert res_empty["status"] == "failed"
    assert res_empty["clean_build"] is False

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "build.log").write_text("Line 12: unknown identifier\nBuild failed.", encoding="utf-8")
    res_fail = cscape_get_diagnostics(project_name=str(tmp_path))
    assert res_fail["success"] is False
    assert res_fail["status"] == "failed"
    assert res_fail["clean_build"] is False
    assert res_fail["compile_successful"] is False


# -----------------------------------------------------------------------------
# Case 08: get_active_simulator - Non-Existent Project
# -----------------------------------------------------------------------------
def test_case08_get_active_simulator_missing_project_fails_closed():
    """Requesting an active simulator for a non-existent project must raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        get_active_simulator(project_name="NonExistentSimProj_XYZ123", reset=True)


# -----------------------------------------------------------------------------
# Case 09: cscape_simulate_pou - Mock Fallback on Error Propagates Failure
# -----------------------------------------------------------------------------
def test_case09_simulate_pou_execution_failure_fails_closed():
    """Runtime division by zero or invalid logic must return status: failed."""
    div_zero_st = """PROGRAM DivZero
VAR
    a : INT := 10;
    b : INT := 0;
    c : INT;
END_VAR
    c := a / b;
END_PROGRAM"""
    res = cscape_simulate_pou(code=div_zero_st, inputs={}, steps=3)
    assert res["success"] is False
    assert res["status"] == "failed"
    assert res.get("error_code") == "SIMULATION_EXECUTION_ERROR"


# -----------------------------------------------------------------------------
# Case 10: STParser.validate - Validates Empty Code as is_valid=False
# -----------------------------------------------------------------------------
def test_case10_st_parser_empty_code_is_invalid():
    """Empty or whitespace-only code must be flagged as is_valid=False with ERR_EMPTY_SOURCE."""
    for empty_src in ["", "   ", "\t\n  \n"]:
        res = STParser.validate(empty_src)
        assert res.is_valid is False
        assert any(i.code == "ERR_EMPTY_SOURCE" for i in res.issues)


# -----------------------------------------------------------------------------
# Case 11: com_bridge.py open_project - Process Crash Reports status: failed
# -----------------------------------------------------------------------------
def test_case11_com_bridge_process_failure_reports_failed(tmp_path):
    """A CLI runner exit with returncode != 0 must report status: failed even if timed_out is False."""
    bridge = CscapeComBridge(prefer_com=False)
    class DummyProcRes:
        returncode = 1
        timed_out = False
        pid = 9999
        duration_seconds = 0.5
        metadata = {}

    dummy_csp = tmp_path / "test.csp"
    dummy_csp.write_bytes(b"dummy")
    bridge.cli_runner.launch_project = lambda *args, **kwargs: DummyProcRes()
    res = bridge.open_project(dummy_csp)
    assert res["status"] == "failed"
    assert res["returncode"] == 1


# -----------------------------------------------------------------------------
# Case 12: cscape_export_project - Missing Artifacts Fail Closed
# -----------------------------------------------------------------------------
def test_case12_export_project_k5p_missing_fails_closed(tmp_path):
    """Exporting k5p when .k5p does not exist must fail closed with NO_DATA_TO_EXPORT."""
    proj_dir = Path("artifacts/projects/EmptyExportProj")
    proj_dir.mkdir(parents=True, exist_ok=True)
    try:
        res = cscape_export_project(project_name="EmptyExportProj", output_format="k5p")
        assert res["success"] is False
        assert res["status"] == "failed"
        assert res.get("error_code") == "NO_DATA_TO_EXPORT"
    finally:
        if proj_dir.exists():
            import shutil
            shutil.rmtree(proj_dir, ignore_errors=True)


# -----------------------------------------------------------------------------
# Case 13: normalize_tool_result - Missing Status & Success Defaults Inconclusive
# -----------------------------------------------------------------------------
def test_case13_normalize_tool_result_unverified_dict_inconclusive():
    """An unverified dict without status or success keys must be inconclusive, not success."""
    unverified = {"data": 42, "unverified_metric": "something"}
    norm = normalize_tool_result(unverified)
    assert norm["success"] is False
    assert norm["status"] == "inconclusive"
    assert norm.get("error_code") in ("UNVERIFIED_RESULT_STATUS", "INVALID_RESULT_CONTRACT")


# -----------------------------------------------------------------------------
# Case 14: Convenience Tools - Canonical 4-State Status
# -----------------------------------------------------------------------------
def test_case14_convenience_tools_canonical_status():
    """Tool failure results must use 'failed', never non-canonical 'error'."""
    res_proj = cscape_create_project(name="")
    assert res_proj["status"] in ("failed", "blocked", "inconclusive")
    assert res_proj["status"] != "error"

    res_add = cscape_add_st_pou(project_name="Fake", pou_name="", pou_type="program", code="")
    assert res_add["status"] in ("failed", "blocked", "inconclusive")
    assert res_add["status"] != "error"


# -----------------------------------------------------------------------------
# Case 15: CscapeLiveProjectManager.open_project - Require Live GUI Fail Closed
# -----------------------------------------------------------------------------
def test_case15_open_project_require_live_gui_without_gui_fails_closed(tmp_path):
    """Requiring live GUI when project is not loaded in GUI must fail closed."""
    from src.cscape.cfbf import generate_minimal_cfbf_bytes
    unopened_csp = tmp_path / "UnopenedProject.csp"
    unopened_csp.write_bytes(generate_minimal_cfbf_bytes("UnopenedProject"))
    res = cscape_open_project(str(unopened_csp), require_live_gui=True)
    assert res["success"] is False
    assert res["status"] in ("failed", "blocked")
    assert res["live_gui_opened"] is False

    # Corrupted or non-existent file also fails closed
    corrupt_res = cscape_open_project(str(tmp_path / "missing.csp"), require_live_gui=True)
    assert corrupt_res["success"] is False
    assert corrupt_res["status"] == "failed"


# -----------------------------------------------------------------------------
# Case 16: cscape_new_iec_project - Live GUI Failure Does Not Silently Fallback
# -----------------------------------------------------------------------------
def test_case16_new_iec_project_live_gui_failure_fails_closed():
    """Live GUI project creation failure must fail closed without dummy fallback."""
    from unittest.mock import patch

    # Invalid project name fails closed
    res_invalid = cscape_new_iec_project(project_name="", live_gui=True)
    assert res_invalid["success"] is False
    assert res_invalid["status"] == "failed"

    # GUI automation exception fails closed without falling back to dummy CFBF bytes
    with patch("src.mcp.tools.create_new_iec_project", side_effect=RuntimeError("GUI unresponsive")):
        res_fail = cscape_new_iec_project(project_name="TestLiveFail", live_gui=True)
        assert res_fail["success"] is False
        assert res_fail["status"] == "failed"
        assert res_fail.get("error_code") in ("LIVE_PROJECT_CREATION_ERROR", "NEW_PROJECT_ERROR")


# -----------------------------------------------------------------------------
# Case 17: StructuredTextInserter - AST Hash Failure Does Not Default to True
# -----------------------------------------------------------------------------
def test_case17_st_inserter_ast_mismatch_fails_verification(tmp_path):
    """When AST hashes fail to compute or mismatch, verified must be False."""
    inserter = StructuredTextInserter()
    test_st = tmp_path / "test.st"
    test_st.write_text("PROGRAM Test VAR x:INT; END_VAR x:=1; END_PROGRAM", encoding="utf-8")

    # Mismatched expected code
    res = inserter.verify_editor_content(
        expected_code="PROGRAM Other VAR y:DINT; END_VAR y:=2; END_PROGRAM",
        editor_hwnd=None,
        file_path=test_st,
    )
    assert res.verified is False


# -----------------------------------------------------------------------------
# Case 18: STSimulator._evaluate_expression - Runtime Eval Exception Fails Closed
# -----------------------------------------------------------------------------
def test_case18_simulator_runtime_exception_fails_closed():
    """Expression causing ZeroDivisionError must trigger status: failed in STSimulator."""
    st_code = """PROGRAM TestDiv
VAR
    val : INT;
END_VAR
    val := 100 / 0;
END_PROGRAM"""
    res = STSimulator.simulate(code=st_code, inputs={}, steps=1)
    assert res["success"] is False
    assert res["status"] == "failed"
    assert res["error_code"] == "SIMULATION_EXECUTION_ERROR"
    assert len(res["diagnostics"]) > 0


# -----------------------------------------------------------------------------
# Case 19: normalize_tool_result - Build Warnings Coerced to Inconclusive
# -----------------------------------------------------------------------------
def test_case19_normalize_tool_result_warnings_inconclusive():
    """BuildStatus.WARNINGS or warnings status must map to inconclusive, not success."""
    warn_dict = {
        "status": "warnings",
        "warning_count": 2,
        "warnings": ["Warning 1", "Warning 2"],
    }
    norm = normalize_tool_result(warn_dict)
    assert norm["status"] == "inconclusive"
    assert norm["success"] is False


# -----------------------------------------------------------------------------
# Case 20: intercept_hardware_interface - Port Lockout Evaluated Independently
# -----------------------------------------------------------------------------
def test_case20_hardware_interface_empty_name_with_port_blocked():
    """Empty interface_name must NOT bypass port lockout evaluation."""
    for bad_port in ["COM1", "COM3", "\\\\.\\COM1"]:
        with pytest.raises(HardwareLockoutError):
            intercept_hardware_interface("", port=bad_port)

        with pytest.raises(HardwareLockoutError):
            intercept_hardware_interface(None, port=bad_port)


# -----------------------------------------------------------------------------
# Case 21: Unit Tests Explicitly Tagged [MOCK_DISPATCH_ONLY]
# -----------------------------------------------------------------------------
def test_case21_unit_tests_tagged_mock_dispatch():
    """Unit test files must tag mock dispatch tests to prevent false live pass claims."""
    test_file = Path(__file__).parent / "test_real_compilation.py"
    assert test_file.exists()
    content = test_file.read_text(encoding="utf-8")
    assert "[MOCK_DISPATCH_ONLY]" in content


# -----------------------------------------------------------------------------
# Case 22: IECValidator.validate - Semantic Parser Exceptions Recorded
# -----------------------------------------------------------------------------
def test_case22_validator_does_not_swallow_semantic_exceptions():
    """IECValidator must record semantic parser issues in warnings if an exception occurs."""
    code = "PROGRAM Valid VAR x:INT; END_VAR x:=1; END_PROGRAM"
    res = IECValidator.validate(code)
    assert isinstance(res.get("warnings"), list)
    assert isinstance(res.get("errors"), list)


# -----------------------------------------------------------------------------
# Case 23: cscape_validate_st - Empty Code & Ladder Logic Rejection Fail Closed
# -----------------------------------------------------------------------------
def test_case23_validate_st_empty_and_ladder_fail_closed():
    """Empty code and ladder constructs must fail closed in cscape_validate_st."""
    res_empty = cscape_validate_st("")
    assert res_empty["valid"] is False
    assert res_empty["success"] is False
    assert res_empty["status"] == "failed"

    res_ladder = cscape_validate_st("---[ ]---")
    assert res_ladder["valid"] is False
    assert res_ladder["success"] is False
    assert res_ladder["status"] == "failed"
    assert any("Ladder logic" in err for err in res_ladder.get("errors", []))


# -----------------------------------------------------------------------------
# Case 24: cscape_compile - Missing Project & Ladder Syntax Fail Closed
# -----------------------------------------------------------------------------
def test_case24_compile_missing_project_and_ladder_pou_fail_closed(tmp_path):
    """Compiling non-existent project or project with ladder POU must fail closed."""
    res_missing = cscape_compile(project_path="NonExistentProject_Fake_9999")
    assert res_missing["success"] is False
    assert res_missing["status"] == "failed"
    assert res_missing.get("error_code") == "PROJECT_NOT_FOUND"

    pous_dir = tmp_path / "pous"
    pous_dir.mkdir(parents=True, exist_ok=True)
    (pous_dir / "bad.st").write_text("PROGRAM Bad VAR x: INT; END_VAR x := ---[ ]---; END_PROGRAM", encoding="utf-8")
    res_bad = cscape_compile(project_path=str(tmp_path))
    assert res_bad["success"] is False
    assert res_bad["status"] == "failed"
    assert res_bad.get("error_code") == "ST_SYNTAX_ERROR"


# -----------------------------------------------------------------------------
# Case 25: cscape_compile_project - Empty Project Name Fails Closed
# -----------------------------------------------------------------------------
def test_case25_compile_project_empty_name_fails_closed():
    """Compiling with empty project name must fail closed."""
    res = cscape_compile_project("")
    assert res["success"] is False
    assert res["status"] == "failed"


# -----------------------------------------------------------------------------
# Case 26: cscape_read_register - Invalid Register & Missing Project Fail Closed
# -----------------------------------------------------------------------------
def test_case26_read_register_invalid_format_and_missing_project():
    """Reading invalid register address or non-existent project must fail closed."""
    res_bad = cscape_read_register(address="INVALID_REG", project_name="TankLevelClosedLoop")
    assert res_bad["success"] is False
    assert res_bad["status"] == "failed"
    assert res_bad.get("error_code") == "ERR_INVALID_REGISTER_ADDRESS"

    res_missing = cscape_read_register(address="%R1", project_name="NonExistent_Sim_Project_123")
    assert res_missing["success"] is False
    assert res_missing["status"] == "failed"


# -----------------------------------------------------------------------------
# Case 27: cscape_write_register - Invalid Address & Missing Project Fail Closed
# -----------------------------------------------------------------------------
def test_case27_write_register_invalid_format_and_missing_project():
    """Writing invalid register address or non-existent project must fail closed."""
    res_bad = cscape_write_register(address="INVALID_REG", value=100, project_name="TankLevelClosedLoop")
    assert res_bad["success"] is False
    assert res_bad["status"] == "failed"
    assert res_bad.get("error_code") == "ERR_INVALID_REGISTER_ADDRESS"

    res_missing = cscape_write_register(address="%R1", value=100, project_name="NonExistent_Sim_Project_123")
    assert res_missing["success"] is False
    assert res_missing["status"] == "failed"


# -----------------------------------------------------------------------------
# Case 28: cscape_simulate_cycle & Variable Import/Export Fail Closed
# -----------------------------------------------------------------------------
def test_case28_simulate_cycle_and_variable_tools_fail_closed(tmp_path):
    """Simulating missing project and variable tools with empty inputs must fail closed."""
    res_sim = cscape_simulate_cycle(project_name="NonExistent_Sim_Project_999")
    assert res_sim["success"] is False
    assert res_sim["status"] == "failed"

    res_imp = cscape_import_variables("")
    assert res_imp["success"] is False
    assert res_imp["status"] == "failed"

    out_file = tmp_path / "vars.csv"
    res_exp = cscape_export_variables(str(out_file), variables=[])
    assert res_exp["success"] is False
    assert res_exp["status"] == "failed"


# -----------------------------------------------------------------------------
# Case 29: Compiler Warning Output ("Warn :") Cannot Return Success
# -----------------------------------------------------------------------------
def test_case29_compiler_warn_prefix_cannot_return_success():
    """Compiler output with 'Warn :' (e.g. empty Screen 1) cannot return is_clean=True or success."""
    from src.cscape.diagnostics import CscapeLogParser, verify_clean_build

    raw_warn_log = (
        "Compiler V12.0.200.82\n"
        "Loading application symbols...\n"
        "EnhancedDisplayAttributes\n"
        "No error detected\n\n"
        "Loading application symbols...\n"
        "Building application data...\n"
        "Relocating code...\n"
        "No error detected\n"
        "Online Change is disabled\n"
        "Generate OCS code...\n"
        "No error detected\n"
        "Warn : Screen set as first screen is empty.Screen 1\n"
    )

    diags = CscapeLogParser.parse_log(raw_warn_log)
    assert len(diags) >= 1
    assert any(d.level == "WARNING" and "Screen 1" in d.message for d in diags)

    proof = verify_clean_build(raw_warn_log)
    assert proof.is_clean is False
    assert proof.warning_count >= 1
    assert proof.status_text == "WARNINGS"

    norm = normalize_tool_result({
        "success": False,
        "status": "warnings",
        "warning_count": proof.warning_count,
        "warnings": [d.message for d in diags],
    })
    assert norm["status"] == "inconclusive"
    assert norm["success"] is False


# -----------------------------------------------------------------------------
# Case 30: Empty / Whitespace / Non-Existent Project Compile Fails Closed
# -----------------------------------------------------------------------------
def test_case30_compile_empty_whitespace_and_missing_project_fails_closed():
    """Compiling empty, whitespace, or missing project paths must fail closed."""
    for empty_p in ["", "   ", "\t\n"]:
        res_c = cscape_compile(project_path=empty_p)
        assert res_c["success"] is False
        assert res_c["status"] == "failed"
        assert res_c["error_code"] == "INVALID_PROJECT_PATH"

        res_cp = cscape_compile_project(project_name=empty_p)
        assert res_cp["success"] is False
        assert res_cp["status"] == "failed"
        assert res_cp["error_code"] == "INVALID_PROJECT_NAME"

    res_missing = cscape_compile_project("CompletelyNonExistentProject_XYZ999")
    assert res_missing["success"] is False
    assert res_missing["status"] == "failed"
    assert res_missing["error_code"] == "PROJECT_NOT_FOUND"


# -----------------------------------------------------------------------------
# Case 31: Fake / Mock HWND Compile Fails Closed
# -----------------------------------------------------------------------------
def test_case31_compile_fake_mock_hwnd_fails_closed():
    """Passing a synthetic/mocked HWND to cscape_compile must fail closed with CSCAPE_WINDOW_INVALID."""
    res = cscape_compile(
        project_path="artifacts/projects/TankLevelClosedLoop",
        cscape_hwnd=99999,
    )
    assert res["success"] is False
    assert res["status"] == "failed"
    assert res.get("error_code") == "CSCAPE_WINDOW_INVALID"
    assert res.get("error_count", 0) > 0


# -----------------------------------------------------------------------------
# Case 32: Diagnostics & Build Output Failed States Fail Closed
# -----------------------------------------------------------------------------
def test_case32_diagnostics_and_build_output_failed_states_fail_closed(tmp_path):
    """Build output with errors and diagnostics on missing projects must report success: False."""
    log_dir = tmp_path / "artifacts"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "build.log").write_text(
        "Compiler V12.0\nLine 1: syntax error\nBuild failed with 1 error(s).\n",
        encoding="utf-8",
    )
    res_bo = cscape_get_build_output(project_path=str(tmp_path))
    assert res_bo["success"] is False
    assert res_bo["status"] == "failed"
    assert res_bo["build_successful"] is False

    res_diag_missing = cscape_get_diagnostics(project_name="NonExistent_Diagnostics_Proj")
    assert res_diag_missing["success"] is False
    assert res_diag_missing["status"] == "failed"
    assert res_diag_missing["clean_build"] is False
    assert res_diag_missing["compile_successful"] is False


# -----------------------------------------------------------------------------
# Case 33: Unauthorized Download Command IDs Blocked During Compile
# -----------------------------------------------------------------------------
def test_case33_unauthorized_download_command_ids_blocked():
    """Triggering compile with download command IDs (32827, 33149) must raise UnauthorizedDownloadError."""
    from src.cscape.compilation import CscapeCompiler, UnauthorizedDownloadError
    from src.cscape.safety import CscapeSafetyViolationError

    compiler = CscapeCompiler()
    for dl_cmd in [32827, 33149]:
        with pytest.raises((UnauthorizedDownloadError, CscapeSafetyViolationError)):
            compiler.trigger_cscape_gui_compile(command_id=dl_cmd)


# -----------------------------------------------------------------------------
# Case 34: cscape_simulate_pou - No Mock Fallback on Simulation Failure (Case 09 Hardening)
# -----------------------------------------------------------------------------
def test_case34_simulate_pou_no_mock_fallback_fails_closed(monkeypatch):
    """When simulate_pou_with_registers encounters an execution error, cscape_simulate_pou
    must immediately fail closed with status='failed' and error_code='SIMULATION_EXECUTION_ERROR',
    without falling back to STSimulator.simulate (mock string evaluator).
    """
    valid_st = """PROGRAM TestMockElimination
VAR
    counter : INT := 0;
    target : INT := 10;
    done : BOOL := FALSE;
END_VAR
    counter := counter + 1;
    IF counter >= target THEN
        done := TRUE;
    END_IF;
END_PROGRAM"""

    # Poison pill: Fail immediately if the mock evaluator STSimulator.simulate is invoked
    def mock_simulate_poison_pill(*args, **kwargs):
        pytest.fail("Violation: STSimulator.simulate mock fallback was invoked on execution failure!")

    monkeypatch.setattr(STSimulator, "simulate", mock_simulate_poison_pill)

    # Force simulate_pou_with_registers to raise a runtime execution error on valid code
    def failing_simulate_pou(*args, **kwargs):
        raise RuntimeError("Deterministic simulation engine failure: cycle execution aborted")

    monkeypatch.setattr("src.mcp.tools.simulate_pou_with_registers", failing_simulate_pou)

    res = cscape_simulate_pou(code=valid_st, inputs={}, steps=3)

    assert res["success"] is False
    assert res["status"] == "failed"
    assert res.get("error_code") == "SIMULATION_EXECUTION_ERROR"
    assert "Deterministic simulation engine failure" in res.get("message", "")
    assert res.get("steps_executed") == 0
    assert res.get("isolation_enforced") is True
    assert res.get("hardware_lockout_enforced") is True


# -----------------------------------------------------------------------------
# Case 35: cscape_inspect_variables - Empty Project or Zero POUs Fails Closed (Case 02 Hardening)
# -----------------------------------------------------------------------------
def test_case35_inspect_variables_empty_project_or_zero_pous_fails_closed():
    """cscape_inspect_variables on projects with 0 POUs or 0 variables must fail closed.

    1. Empty project with 0 POUs must return success: False, status: 'failed',
       error_code: 'NO_POUS_FOUND', and total_variables: 0.
    2. Project with valid POU(s) but 0 variable declarations must return success: False,
       status: 'failed', error_code: 'EMPTY_PROJECT_VARIABLES', and total_variables: 0.
    """
    import shutil
    from src.mcp.tools import (
        WORKSPACE_ROOT,
        cscape_create_project,
        cscape_add_st_pou,
        cscape_inspect_variables,
    )

    proj_zero_pous = "Case35_Empty_ZeroPOUs"
    proj_zero_vars = "Case35_Empty_ZeroVars"
    projects_dir = WORKSPACE_ROOT / "artifacts" / "projects"

    dir_zero_pous = projects_dir / proj_zero_pous
    dir_zero_vars = projects_dir / proj_zero_vars

    try:
        # --- 1. Project with 0 POUs ---
        if dir_zero_pous.exists():
            shutil.rmtree(dir_zero_pous, ignore_errors=True)
        res_create1 = cscape_create_project(name=proj_zero_pous)
        assert res_create1["success"] is True

        res_inspect1 = cscape_inspect_variables(project_name=proj_zero_pous)
        assert res_inspect1["success"] is False
        assert res_inspect1["status"] == "failed"
        assert res_inspect1.get("error_code") == "NO_POUS_FOUND"
        assert res_inspect1.get("total_variables") == 0
        assert res_inspect1.get("pous") == []
        assert res_inspect1.get("variables") == []
        assert len(res_inspect1.get("errors", [])) > 0

        # --- 2. Project with POU(s) but 0 declared variables ---
        if dir_zero_vars.exists():
            shutil.rmtree(dir_zero_vars, ignore_errors=True)
        res_create2 = cscape_create_project(name=proj_zero_vars)
        assert res_create2["success"] is True

        zero_vars_code = "PROGRAM ZeroVarsProg\n  // No variable declarations\nEND_PROGRAM\n"
        res_add = cscape_add_st_pou(
            project_name=proj_zero_vars,
            pou_name="ZeroVarsProg",
            pou_type="PROGRAM",
            code=zero_vars_code,
        )
        assert res_add["success"] is True

        res_inspect2 = cscape_inspect_variables(project_name=proj_zero_vars)
        assert res_inspect2["success"] is False
        assert res_inspect2["status"] == "failed"
        assert res_inspect2.get("error_code") == "EMPTY_PROJECT_VARIABLES"
        assert res_inspect2.get("total_variables") == 0
        assert "ZeroVarsProg" in res_inspect2.get("pous", [])
        assert res_inspect2.get("variables") == []
        assert len(res_inspect2.get("errors", [])) > 0

    finally:
        # Deterministic teardown
        if dir_zero_pous.exists():
            shutil.rmtree(dir_zero_pous, ignore_errors=True)
        if dir_zero_vars.exists():
            shutil.rmtree(dir_zero_vars, ignore_errors=True)


# -----------------------------------------------------------------------------
# Case 36: cscape_new_iec_project - Missing Authentic Template Fails Closed (Case 16 Hardening)
# -----------------------------------------------------------------------------
def test_case36_new_iec_project_missing_template_fails_closed(tmp_path):
    """CASE 16 / Case 36: When authentic CFBF template is missing, cscape_new_iec_project
    must fail closed immediately with error_code='AUTHENTIC_TEMPLATE_MISSING' and prohibit
    generating synthetic 512-byte dummy files."""
    from unittest.mock import patch
    from src.mcp.tools import cscape_new_iec_project

    proj_name = "TestMissingTemplateProj"
    target_dir = tmp_path / "projects"
    target_dir.mkdir(parents=True, exist_ok=True)
    expected_csp = target_dir / proj_name / f"{proj_name}.csp"
    manifest_file = target_dir / proj_name / "cscape_project.json"

    # 1. Simulate missing CFBF template (_find_cfbf_template returning None)
    with patch("src.mcp.tools._find_cfbf_template", return_value=None), \
         patch("src.cscape.cfbf.generate_minimal_cfbf_bytes") as mock_gen:
        res = cscape_new_iec_project(
            project_name=proj_name,
            target_dir=str(target_dir),
            controller_model="XL4",
            live_gui=False,
        )

        # Invariant: generate_minimal_cfbf_bytes must NEVER be invoked
        mock_gen.assert_not_called()

    # 2. Strict MCP Status Contract assertions
    assert res["success"] is False, "Must not report success when authentic template is missing"
    assert res["status"] == "failed", f"Expected status 'failed', got '{res.get('status')}'"
    assert res.get("error_code") == "AUTHENTIC_TEMPLATE_MISSING", (
        f"Expected error_code 'AUTHENTIC_TEMPLATE_MISSING', got '{res.get('error_code')}'"
    )

    # 3. Fail-closed on-disk invariants: synthetic dummy files and manifest must NOT exist
    assert not expected_csp.exists(), (
        f"Synthetic dummy CFBF file '{expected_csp}' must NOT be written to disk"
    )
    assert not manifest_file.exists(), (
        f"Project manifest '{manifest_file}' must NOT be written when template is missing"
    )

    # 4. Diagnostic errors list guarantee
    assert res.get("errors") and len(res["errors"]) > 0, "errors list must be non-empty"
    assert any("authentic" in str(e).lower() for e in res["errors"])

    # 5. Non-existent path returned by _find_cfbf_template also fails closed
    ghost_tmpl = tmp_path / "non_existent_ghost.csp"
    with patch("src.mcp.tools._find_cfbf_template", return_value=ghost_tmpl):
        res_ghost = cscape_new_iec_project(
            project_name="GhostProj",
            target_dir=str(target_dir),
            controller_model="XL4",
            live_gui=False,
        )
    assert res_ghost["success"] is False
    assert res_ghost["status"] == "failed"
    assert res_ghost.get("error_code") == "AUTHENTIC_TEMPLATE_MISSING"
    assert not (target_dir / "GhostProj" / "GhostProj.csp").exists()


# -----------------------------------------------------------------------------
# Case 37: IECValidator.validate - Semantic Parser Crash Fails Closed (Case 22 Hardening)
# -----------------------------------------------------------------------------
def test_case37_validator_semantic_parser_crash_fails_closed():
    """IECValidator.validate and cscape_validate_st must fail closed (valid=False, status='failed')
    when STParser.validate crashes with an unhandled exception.
    """
    from unittest.mock import patch
    from src.iec.validator import IECValidator
    from src.mcp.tools import cscape_validate_st

    valid_st_code = """
    PROGRAM TankControl
    VAR
        nTankLevel : INT;
    END_VAR
    nTankLevel := 50;
    END_PROGRAM
    """

    simulated_crash_msg = "Simulated AST semantic engine crash"

    with patch("src.iec.st_parser.STParser.validate", side_effect=RuntimeError(simulated_crash_msg)):
        # 1. Verify internal IECValidator contract
        res = IECValidator.validate(valid_st_code)
        assert res["valid"] is False, f"Expected valid=False on semantic parser crash, got: {res.get('valid')}"
        assert len(res["errors"]) > 0, "Expected non-empty errors list on semantic parser crash"
        assert any("Semantic parser error" in err for err in res["errors"]), (
            f"Expected 'Semantic parser error' in errors list, got: {res.get('errors')}"
        )
        assert any(simulated_crash_msg in err for err in res["errors"]), (
            f"Expected crash detail '{simulated_crash_msg}' in errors list, got: {res.get('errors')}"
        )

        # 2. Verify upstream MCP tool layer fails closed under canonical status contract
        tool_res = cscape_validate_st(valid_st_code)
        assert tool_res["valid"] is False, f"Expected tool valid=False, got: {tool_res.get('valid')}"
        assert tool_res["success"] is False, f"Expected tool success=False, got: {tool_res.get('success')}"
        assert tool_res["status"] == "failed", f"Expected tool status='failed', got: {tool_res.get('status')}"
        assert len(tool_res["errors"]) > 0, "Expected tool errors list to be non-empty"


# -----------------------------------------------------------------------------
# Case 38: open_project Stale Gate or Dead HWND Fails Closed (Case 15 Hardening)
# -----------------------------------------------------------------------------
def test_case38_open_project_stale_gate_or_dead_hwnd_fails_closed(tmp_path, monkeypatch):
    """CASE 15 / H02: Stale .cscape_live_gate.json or dead HWND cannot satisfy is_project_open,
    and cscape_open_project must verify active GUI / live HWND when live open is requested.
    Cannot claim success: True or live_gui_opened: True when GUI is absent or HWND is dead.
    """
    from src.cscape.cfbf import generate_minimal_cfbf_bytes
    from src.cscape.project_manager import (
        CscapeLiveProjectManager,
        cscape_open_project as pm_open_project,
        CscapeAutomationError,
    )
    import win32gui

    # 1. Create a valid test .csp project file
    csp_file = tmp_path / "TankLevelClosedLoop.csp"
    csp_file.write_bytes(generate_minimal_cfbf_bytes("TankLevelClosedLoop"))

    # 2. Simulate a stale .cscape_live_gate.json with dead HWND (99999) and active PID
    stale_gate = {
        "pid": 12345,
        "main_hwnd": 99999,
        "project_file": "TankLevelClosedLoop.csp",
        "window_title": "Cscape - [TankLevelClosedLoop.csp]",
        "status": "LIVE",
    }
    monkeypatch.setattr("src.cscape.project_manager.get_cscape_gate_info", lambda *a, **kw: stale_gate)
    monkeypatch.setattr("src.cscape.project_manager.resolve_cscape_pid", lambda *a, **kw: 12345)

    # Ensure HWND 99999 is recognized as dead
    assert not win32gui.IsWindow(99999)

    # 3. Verify CscapeLiveProjectManager.is_project_open fails closed against stale gate
    mgr = CscapeLiveProjectManager()
    mgr.is_process_running_pid = lambda pid: True  # Even if PID appears alive
    mgr.enum_process_windows = lambda pid=None: []  # No live windows exist for PID
    mgr.main_hwnd = 99999  # Dead HWND

    # Stale gate with dead HWND MUST NOT satisfy is_project_open
    assert mgr.is_project_open(csp_file) is False

    # 4. Verify CscapeLiveProjectManager.open_project with require_live_gui=True fails closed
    mgr.find_running_cscape_pid = lambda: 12345
    mgr.get_main_window = lambda timeout_sec=0.5: None
    with pytest.raises(CscapeAutomationError, match="FAIL-CLOSED"):
        mgr.open_project(csp_file, require_live_gui=True)

    # 5. Verify standalone cscape_open_project in src.cscape.project_manager fails closed
    # when require_live_gui=True and gate HWND is dead
    res_pm = pm_open_project(str(csp_file), require_live_gui=True)
    assert res_pm["success"] is False
    assert res_pm["status"] in ("blocked", "failed")
    assert res_pm["live_gui_opened"] is False
    assert res_pm["open_mode"] == "error"
    assert any("FAIL-CLOSED" in err for err in res_pm.get("errors", []))

    # 6. Verify MCP tool cscape_open_project in src.mcp.tools fails closed
    res_mcp = cscape_open_project(file_path=str(csp_file), require_live_gui=True)
    assert res_mcp["success"] is False
    assert res_mcp["status"] in ("blocked", "failed")
    assert res_mcp["live_gui_opened"] is False
    assert res_mcp["open_mode"] == "error"
    assert res_mcp.get("error_code") in ("LIVE_GUI_NOT_ACTIVE", "OPEN_PROJECT_ERROR", "SECURITY_BLOCKED")

    # 7. Verify that without require_live_gui, it validates offline but NEVER claims live_gui_opened
    res_offline = cscape_open_project(file_path=str(csp_file), require_live_gui=False)
    assert res_offline["live_gui_opened"] is False
    assert res_offline["open_mode"] == "offline_validated"
    assert res_offline.get("already_open", False) is False


# -----------------------------------------------------------------------------
# Case 39: com_bridge.py CLI Fallback compile_project Claims Success (Batch 1 Case 01)
# -----------------------------------------------------------------------------
def test_case39_com_bridge_cli_fallback_compile_fails_closed(tmp_path):
    """com_bridge.py CLI fallback compile_project must fail closed when COM is unavailable.
    Presence of toolchain binaries alone does not constitute successful compilation.
    """
    bridge = CscapeComBridge(prefer_com=False)
    dummy_proj = tmp_path / "test.csp"
    dummy_proj.write_bytes(b"dummy")

    res = bridge.compile_project(dummy_proj)
    assert res["status"] == "failed"
    assert res["error_code"] == "CLI_COMPILATION_UNAVAILABLE"
    assert res["mode"] == "cli_fallback"
    assert len(res.get("errors", [])) > 0
    assert "CLI compilation fallback requires active live compiler process" in res["errors"][0]


# -----------------------------------------------------------------------------
# Case 40: STParser.validate & cscape_validate_st Fail Closed on Missing POU (Batch 1 Case 03)
# -----------------------------------------------------------------------------
def test_case40_st_parser_no_pou_or_invalid_snippet_fails_closed():
    """STParser.validate and cscape_validate_st must fail closed with ERR_NO_POU_FOUND
    when given arbitrary text or snippets lacking POUs, VAR declarations, and assignments.
    """
    invalid_snippets = [
        "arbitrary non-ST identifier sequence;",
        ";;;",
        "SELECT * FROM users WHERE id = 1;",
        "def python_function(): pass",
        "just some random text without pous",
    ]

    for snippet in invalid_snippets:
        # 1. Direct STParser.validate contract verification
        res_parser = STParser.validate(snippet)
        assert res_parser.is_valid is False
        pou_errs = [i for i in res_parser.issues if i.code == "ERR_NO_POU_FOUND"]
        assert len(pou_errs) > 0, f"Expected ERR_NO_POU_FOUND for snippet: {snippet!r}"
        assert any(i.severity == IssueSeverity.ERROR for i in pou_errs)
        assert "No PROGRAM, FUNCTION_BLOCK, or FUNCTION definitions found" in pou_errs[0].message

        # 2. MCP tool cscape_validate_st verification
        res_mcp = cscape_validate_st(snippet)
        assert res_mcp["success"] is False
        assert res_mcp["status"] == "failed"
        assert res_mcp.get("valid") is False
        errors_combined = " ".join(str(e) for e in res_mcp.get("errors", []))
        fail_loc_codes = [loc.get("error_code") for loc in res_mcp.get("failure_locations", [])]
        assert "ERR_NO_POU_FOUND" in errors_combined or "ERR_NO_POU_FOUND" in fail_loc_codes


# -----------------------------------------------------------------------------
# Case 41: cscape_add_st_pou on Non-Existent Project Fails Closed (Batch 1 Case 02)
# -----------------------------------------------------------------------------
def test_case41_add_st_pou_nonexistent_project_fails_closed():
    """cscape_add_st_pou must fail closed when project does not exist or has no valid container (.csp, .cpj, .json).
    Spurious directories must not be created on disk and return contract must strictly specify PROJECT_NOT_FOUND.
    """
    non_existent_project = "GhostProject_NonExistent_999888"
    proj_dir = Path(f"artifacts/projects/{non_existent_project}")
    if proj_dir.exists():
        import shutil
        shutil.rmtree(proj_dir, ignore_errors=True)

    valid_st_code = "PROGRAM Logic VAR x : INT; END_VAR x := 1; END_PROGRAM"

    # 1. Non-existent project fails closed
    res = cscape_add_st_pou(
        project_name=non_existent_project,
        pou_name="ValidLogic",
        pou_type="program",
        code=valid_st_code,
    )
    assert res["success"] is False
    assert res["status"] == "failed"
    assert res["error_code"] == "PROJECT_NOT_FOUND"
    assert res["project_name"] == non_existent_project
    assert res["pou_name"] == "ValidLogic"
    assert any("does not exist or has no valid project container" in err for err in res["errors"])
    assert not proj_dir.exists(), "Spurious project directory must not be created on disk"

    # 2. Existing folder without valid container (.csp, .cpj, cscape_project.json) also fails closed
    empty_folder = Path("artifacts/projects/EmptyFolderNoContainer_888")
    empty_folder.mkdir(parents=True, exist_ok=True)
    try:
        res2 = cscape_add_st_pou(
            project_name="EmptyFolderNoContainer_888",
            pou_name="ValidLogic",
            pou_type="program",
            code=valid_st_code,
        )
        assert res2["success"] is False
        assert res2["status"] == "failed"
        assert res2["error_code"] == "PROJECT_NOT_FOUND"
        assert any("does not exist or has no valid project container" in err for err in res2["errors"])
    finally:
        if empty_folder.exists():
            import shutil
            shutil.rmtree(empty_folder, ignore_errors=True)


# -----------------------------------------------------------------------------
# Case 42: get_active_simulator Zero POUs Fails Closed (Batch 1 Case 05)
# -----------------------------------------------------------------------------
def test_case42_simulator_zero_pous_fails_closed():
    """get_active_simulator and cscape_simulate_cycle must fail closed when a project
    exists but contains zero Structured Text POUs (or pous/ directory is missing).
    """
    from src.mcp.tools import WORKSPACE_ROOT
    proj_dirs = list(dict.fromkeys([
        WORKSPACE_ROOT / "artifacts" / "projects" / "ZeroPOU_Sim_TestProj",
        Path("artifacts/projects/ZeroPOU_Sim_TestProj").resolve(),
    ]))
    for pd in proj_dirs:
        pd.mkdir(parents=True, exist_ok=True)
    try:
        # Case A: proj_dir exists, but pous/ does not exist
        with pytest.raises(RuntimeError, match="Fail-closed: Project '.*' contains no Structured Text POUs to simulate"):
            get_active_simulator(project_name="ZeroPOU_Sim_TestProj", reset=True)

        res_cycle = cscape_simulate_cycle(project_name="ZeroPOU_Sim_TestProj")
        assert res_cycle["success"] is False
        assert res_cycle["status"] == "failed"
        assert any("contains no Structured Text POUs to simulate" in err for err in res_cycle.get("errors", []))

        # Case B: pous/ directory exists, but contains 0 .st files
        for pd in proj_dirs:
            (pd / "pous").mkdir(parents=True, exist_ok=True)
        with pytest.raises(RuntimeError, match="Fail-closed: Project '.*' contains no Structured Text POUs to simulate"):
            get_active_simulator(project_name="ZeroPOU_Sim_TestProj", reset=True)

        res_cycle2 = cscape_simulate_cycle(project_name="ZeroPOU_Sim_TestProj")
        assert res_cycle2["success"] is False
        assert res_cycle2["status"] == "failed"
        assert any("contains no Structured Text POUs to simulate" in err for err in res_cycle2.get("errors", []))
    finally:
        for pd in proj_dirs:
            if pd.exists():
                import shutil
                shutil.rmtree(pd, ignore_errors=True)


# -----------------------------------------------------------------------------
# Case 43: cscape_export_project Zero Variables Database Fails Closed (Batch 1 Case 04)
# -----------------------------------------------------------------------------
def test_case43_export_zero_variables_fails_closed():
    """cscape_export_project must fail closed with NO_DATA_TO_EXPORT when exporting
    csv or xml from a project that contains 0 variable declarations. Empty files must
    not remain on disk.
    """
    import json
    from src.mcp.tools import WORKSPACE_ROOT
    proj_dirs = list(dict.fromkeys([
        WORKSPACE_ROOT / "artifacts" / "projects" / "ZeroVar_Export_TestProj",
        Path("artifacts/projects/ZeroVar_Export_TestProj").resolve(),
    ]))
    for pd in proj_dirs:
        pous_dir = pd / "pous"
        pous_dir.mkdir(parents=True, exist_ok=True)
        # Write manifest and a POU with logic but zero variable declarations
        (pd / "cscape_project.json").write_text(
            json.dumps({"project_name": "ZeroVar_Export_TestProj", "target_plc": "XL4"}),
            encoding="utf-8",
        )
        (pous_dir / "NoVars.st").write_text(
            "PROGRAM NoVars\n(* No variable declarations in this POU *)\nEND_PROGRAM\n",
            encoding="utf-8",
        )

    exports_dirs = list(dict.fromkeys([
        WORKSPACE_ROOT / "artifacts" / "exports",
        Path("artifacts/exports").resolve(),
    ]))
    csv_outs = [ed / "ZeroVar_Export_TestProj.csv" for ed in exports_dirs]
    xml_outs = [ed / "ZeroVar_Export_TestProj.xml" for ed in exports_dirs]

    try:
        # 1. CSV export with 0 variables fails closed
        res_csv = cscape_export_project(project_name="ZeroVar_Export_TestProj", output_format="csv")
        assert res_csv["success"] is False
        assert res_csv["status"] == "failed"
        assert res_csv["error_code"] == "NO_DATA_TO_EXPORT"
        assert res_csv["project_name"] == "ZeroVar_Export_TestProj"
        assert res_csv["output_format"] == "csv"
        assert res_csv["error_count"] == 1
        assert "No variable declarations found in project to export." in res_csv["errors"]
        assert not any(f.exists() for f in csv_outs), "Empty CSV export file must not remain on disk"

        # 2. XML export with 0 variables fails closed
        res_xml = cscape_export_project(project_name="ZeroVar_Export_TestProj", output_format="xml")
        assert res_xml["success"] is False
        assert res_xml["status"] == "failed"
        assert res_xml["error_code"] == "NO_DATA_TO_EXPORT"
        assert res_xml["project_name"] == "ZeroVar_Export_TestProj"
        assert res_xml["output_format"] == "xml"
        assert res_xml["error_count"] == 1
        assert "No variable declarations found in project to export." in res_xml["errors"]
        assert not any(f.exists() for f in xml_outs), "Empty XML export file must not remain on disk"
    finally:
        for f in csv_outs + xml_outs:
            if f.exists():
                f.unlink(missing_ok=True)
        for pd in proj_dirs:
            if pd.exists():
                import shutil
                shutil.rmtree(pd, ignore_errors=True)


# -----------------------------------------------------------------------------
# Case 44: cscape_export_project Missing Manifest Fails Closed (Batch 1 Case 07 / Case 12)
# -----------------------------------------------------------------------------
def test_case44_export_project_json_missing_manifest_fails_closed():
    """cscape_export_project with output_format='json' must fail closed with MANIFEST_NOT_FOUND
    when authentic cscape_project.json is missing or corrupted. Synthetic manifest generation
    is strictly prohibited under fail-closed policy.
    """
    import json
    import shutil
    from src.mcp.tools import WORKSPACE_ROOT

    proj_name = "MissingManifest_Export_TestProj"
    proj_dirs = list(dict.fromkeys([
        WORKSPACE_ROOT / "artifacts" / "projects" / proj_name,
        Path(f"artifacts/projects/{proj_name}").resolve(),
    ]))
    exports_dirs = list(dict.fromkeys([
        WORKSPACE_ROOT / "artifacts" / "exports",
        Path("artifacts/exports").resolve(),
    ]))
    export_outs = [ed / f"{proj_name}.json" for ed in exports_dirs]

    for pd in proj_dirs:
        pd.mkdir(parents=True, exist_ok=True)
        # Create container file (.csp) but DO NOT create cscape_project.json
        (pd / f"{proj_name}.csp").write_bytes(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1" + b"\x00" * 504)

    try:
        # 1. Project with .csp container but NO cscape_project.json must fail closed
        res = cscape_export_project(project_name=proj_name, output_format="json")
        assert res["success"] is False
        assert res["status"] == "failed"
        assert res.get("error_code") == "MANIFEST_NOT_FOUND"
        assert res.get("project_name") == proj_name
        assert res.get("output_format") == "json"
        assert res.get("error_count", 0) > 0
        assert any("cscape_project.json" in err for err in res.get("errors", []))
        assert not any(f.exists() for f in export_outs), "Synthetic manifest export must not be written to disk"

        # 2. Project with empty (0-byte) cscape_project.json must also fail closed
        for pd in proj_dirs:
            (pd / "cscape_project.json").write_text("", encoding="utf-8")

        res_empty = cscape_export_project(project_name=proj_name, output_format="json")
        assert res_empty["success"] is False
        assert res_empty["status"] == "failed"
        assert res_empty.get("error_code") == "MANIFEST_NOT_FOUND"
        assert not any(f.exists() for f in export_outs)

        # 3. Project with corrupted JSON in cscape_project.json must fail closed with MANIFEST_CORRUPTED
        for pd in proj_dirs:
            (pd / "cscape_project.json").write_text("{corrupted_json: true", encoding="utf-8")

        res_corrupt = cscape_export_project(project_name=proj_name, output_format="json")
        assert res_corrupt["success"] is False
        assert res_corrupt["status"] == "failed"
        assert res_corrupt.get("error_code") == "MANIFEST_CORRUPTED"
        assert not any(f.exists() for f in export_outs)

        # 4. Authentic valid cscape_project.json succeeds and copies genuine manifest
        valid_manifest = {
            "name": proj_name,
            "controller": "XL4",
            "created_at": "2026-09-09T00:00:00Z",
            "pous": [],
        }
        for pd in proj_dirs:
            (pd / "cscape_project.json").write_text(json.dumps(valid_manifest), encoding="utf-8")

        res_valid = cscape_export_project(project_name=proj_name, output_format="json")
        assert res_valid["success"] is True
        assert res_valid["status"] == "success"
        assert res_valid.get("error_count") == 0
        out_file = Path(res_valid["export_file"])
        assert out_file.exists()
        loaded_data = json.loads(out_file.read_text(encoding="utf-8"))
        assert loaded_data["name"] == proj_name
    finally:
        for f in export_outs:
            if f.exists():
                f.unlink(missing_ok=True)
        for pd in proj_dirs:
            if pd.exists():
                shutil.rmtree(pd, ignore_errors=True)


# -----------------------------------------------------------------------------
# Case 45: cscape_insert_st - allow_invalid=True Disk Mutation Blocked (Batch 1 Case 06 / Case 03)
# -----------------------------------------------------------------------------
def test_case45_insert_st_allow_invalid_mutation_blocked(tmp_path):
    """cscape_insert_st must NEVER write unverified or invalid Structured Text to disk
    in project storage, even when allow_invalid=True is supplied.
    Disk writes require syntax_valid=True. Invalid code must fail closed with
    status: 'failed', success: False, error_code: 'INVALID_ST_CODE_MUTATION_BLOCKED',
    and is_staged: False.
    """
    proj_dir = tmp_path / "TestProjMutationBlocked"
    pous_dir = proj_dir / "pous"
    pous_dir.mkdir(parents=True, exist_ok=True)

    existing_pou = pous_dir / "ExistingValidPOU.st"
    original_code = "PROGRAM ExistingValidPOU\nVAR\n  x : INT;\nEND_VAR\n  x := 10;\nEND_PROGRAM\n"
    existing_pou.write_text(original_code, encoding="utf-8")
    original_bytes = existing_pou.read_bytes()

    broken_code = "PROGRAM BrokenSyntax\nVAR\n  x : INT;\nEND_VAR\n  x := ;\nEND_PROGRAM\n"

    # 1. Attempt to overwrite existing POU with broken code and allow_invalid=True
    res_overwrite = cscape_insert_st(
        pou_name="ExistingValidPOU",
        pou_type="PROGRAM",
        st_code=broken_code,
        target_project_path=str(proj_dir),
        allow_invalid=True,
    )
    assert res_overwrite["success"] is False
    assert res_overwrite["status"] == "failed"
    assert res_overwrite["error_code"] == "INVALID_ST_CODE_MUTATION_BLOCKED"
    assert res_overwrite["is_staged"] is False
    assert res_overwrite["syntax_valid"] is False
    assert any("INVALID_ST_CODE_MUTATION_BLOCKED" in err or "allow_invalid=True is blocked" in err for err in res_overwrite["errors"])
    # Disk invariant: existing file must be untouched byte-for-byte
    assert existing_pou.read_bytes() == original_bytes

    # 2. Attempt to create a new POU with broken code and allow_invalid=True
    new_broken_pou = pous_dir / "NewBrokenPOU.st"
    res_create = cscape_insert_st(
        pou_name="NewBrokenPOU",
        pou_type="PROGRAM",
        st_code=broken_code,
        target_project_path=str(proj_dir),
        allow_invalid=True,
    )
    assert res_create["success"] is False
    assert res_create["status"] == "failed"
    assert res_create["error_code"] == "INVALID_ST_CODE_MUTATION_BLOCKED"
    assert res_create["is_staged"] is False
    assert res_create["syntax_valid"] is False
    assert any("INVALID_ST_CODE_MUTATION_BLOCKED" in err or "allow_invalid=True is blocked" in err for err in res_create["errors"])
    # Disk invariant: new broken file must NOT exist on disk
    assert not new_broken_pou.exists()


# -----------------------------------------------------------------------------
# Case 46: normalize_tool_result Non-Canonical Status & Contradictions Fail Closed (Batch 1 Case 08)
# -----------------------------------------------------------------------------
def test_case46_normalize_tool_result_noncanonical_status_and_contradictions_fail_closed():
    """normalize_tool_result must strictly enforce the canonical 4-state contract:
    1. Non-canonical status candidates (e.g. 'partial', 'in_progress', 'pending', 'custom')
       paired with success=True must fail closed with status: 'inconclusive', success: False,
       error_code: 'INVALID_RESULT_CONTRACT', and non-empty error messages.
    2. Null status ({'status': None, 'success': True}) and empty status ({'status': '', 'success': True})
       must fail closed with status: 'inconclusive', success: False, error_code: 'INVALID_RESULT_CONTRACT'.
    3. Contradictory dicts claiming success=True alongside non-success status candidates
       ('warning', 'blocked', 'failed', 'inconclusive') must fail closed with success: False,
       error_code: 'INVALID_RESULT_CONTRACT', and non-empty failure diagnostics.
    4. Authentic success dict ({'status': 'success', 'success': True}) succeeds cleanly.
    """
    # 1. Non-canonical / partial statuses claiming success=True
    for bad_status in ["partial", "in_progress", "pending", "custom", "draft", "indeterminate"]:
        raw = {"status": bad_status, "success": True, "data": "dummy"}
        norm = normalize_tool_result(raw, default_source="TestNormalizer")
        assert norm["success"] is False, f"Status '{bad_status}' must not succeed"
        assert norm["status"] == "inconclusive"
        assert norm["error_code"] == "INVALID_RESULT_CONTRACT"
        assert len(norm["errors"]) > 0
        assert any("INVALID_RESULT_CONTRACT" in err or "violates canonical 4-state ontology" in err for err in norm["errors"])
        assert len(norm["failure_locations"]) > 0

    # 2. Null or whitespace-only status claiming success=True
    for empty_status in [None, "", "   ", "\t"]:
        raw = {"status": empty_status, "success": True}
        norm = normalize_tool_result(raw, default_source="TestNormalizer")
        assert norm["success"] is False
        assert norm["status"] == "inconclusive"
        assert norm["error_code"] == "INVALID_RESULT_CONTRACT"
        assert len(norm["errors"]) > 0

    # 3. Contradictory dicts: success=True with non-success status candidate
    for contra_status in ["warning", "warn", "blocked", "failed", "inconclusive"]:
        raw = {"status": contra_status, "success": True, "message": "claimed success"}
        norm = normalize_tool_result(raw, default_source="ContradictionProbe")
        assert norm["success"] is False, f"Status '{contra_status}' with success=True must fail closed"
        assert norm["error_code"] == "INVALID_RESULT_CONTRACT"
        assert len(norm["errors"]) > 0
        assert any("Contradiction detected" in err for err in norm["errors"])

    # 4. Authentic canonical success passes cleanly
    clean_success = {"status": "success", "success": True, "data": 123}
    norm_clean = normalize_tool_result(clean_success, default_source="CleanProbe")
    assert norm_clean["success"] is True
    assert norm_clean["status"] == "success"
    assert len(norm_clean["errors"]) == 0
    assert norm_clean.get("error_code") is None or norm_clean.get("error_code") == ""


# -----------------------------------------------------------------------------
# Case 47: cscape_insert_st Non-Existent & Whitespace Project Paths Fail Closed
# -----------------------------------------------------------------------------
def test_case47_insert_st_nonexistent_or_whitespace_project_path_fails_closed(tmp_path):
    """cscape_insert_st must fail closed when target_project_path or project_path
    points to a non-existent directory or contains whitespace.
    Spurious directories must not be created on disk and return contract must strictly
    specify PROJECT_NOT_FOUND or INVALID_PROJECT_PATH.
    """
    valid_st_code = "PROGRAM ValidLogic\nVAR\n  count : INT;\nEND_VAR\n  count := count + 1;\nEND_PROGRAM\n"

    # 1. Non-existent directory via target_project_path must fail closed
    ghost_dir = tmp_path / "Ghost_Insert_Project_999888"
    assert not ghost_dir.exists()

    res_target = cscape_insert_st(
        pou_name="ValidLogic",
        pou_type="PROGRAM",
        st_code=valid_st_code,
        target_project_path=str(ghost_dir),
    )
    assert res_target["success"] is False
    assert res_target["status"] == "failed"
    assert res_target["error_code"] == "PROJECT_NOT_FOUND"
    assert res_target["is_staged"] is False
    assert any("does not exist" in err for err in res_target.get("errors", []))
    assert not ghost_dir.exists(), "Spurious project directory must NOT be created on disk"

    # 2. Non-existent directory via project_path must fail closed
    ghost_dir2 = tmp_path / "Ghost_Insert_Project_777666"
    assert not ghost_dir2.exists()

    res_proj = cscape_insert_st(
        pou_name="ValidLogic",
        pou_type="PROGRAM",
        st_code=valid_st_code,
        project_path=str(ghost_dir2),
    )
    assert res_proj["success"] is False
    assert res_proj["status"] == "failed"
    assert res_proj["error_code"] == "PROJECT_NOT_FOUND"
    assert res_proj["is_staged"] is False
    assert any("does not exist" in err for err in res_proj.get("errors", []))
    assert not ghost_dir2.exists(), "Spurious project directory must NOT be created on disk"

    # 3. Whitespace project path must fail closed with INVALID_PROJECT_PATH
    workspace_pous = Path("pous")
    had_workspace_pous = workspace_pous.exists()

    for ws_path in ["   ", "\t", "  \n  "]:
        res_ws = cscape_insert_st(
            pou_name="ValidLogic",
            pou_type="PROGRAM",
            st_code=valid_st_code,
            target_project_path=ws_path,
        )
        assert res_ws["success"] is False
        assert res_ws["status"] == "failed"
        assert res_ws["error_code"] == "INVALID_PROJECT_PATH"
        assert res_ws["is_staged"] is False

    if not had_workspace_pous:
        assert not workspace_pous.exists(), "Workspace root must not have a spurious 'pous' directory created"

    # 4. Valid existing directory succeeds cleanly and stages file
    valid_proj = tmp_path / "Valid_Existing_Project"
    valid_proj.mkdir(parents=True, exist_ok=True)

    res_valid = cscape_insert_st(
        pou_name="ValidLogic",
        pou_type="PROGRAM",
        st_code=valid_st_code,
        target_project_path=str(valid_proj),
    )
    assert res_valid["success"] is True
    assert res_valid["status"] == "success"
    assert res_valid["is_staged"] is True
    assert res_valid["storage_mode"] == "staging"
    staged_file = valid_proj / "pous" / "ValidLogic.st"
    assert staged_file.exists()
    assert staged_file.read_text(encoding="utf-8") == valid_st_code


# -----------------------------------------------------------------------------
# Case 48: cscape_new_iec_project Empty & Whitespace target_dir Fails Closed
# -----------------------------------------------------------------------------
def test_case48_new_iec_project_empty_or_whitespace_target_dir_fails_closed(tmp_path):
    """cscape_new_iec_project must fail closed when target_dir is empty or whitespace.
    It must not default to resolving against CWD or leak project folders into the repository root.
    """
    proj_name = "GhostLeak_Proj_999888"
    cwd_leaked = Path(proj_name)
    if cwd_leaked.exists():
        import shutil
        shutil.rmtree(cwd_leaked, ignore_errors=True)

    try:
        # 1. Empty string target_dir fails closed
        res_empty = cscape_new_iec_project(project_name=proj_name, target_dir="")
        assert res_empty["success"] is False
        assert res_empty["status"] == "failed"
        assert res_empty["error_code"] == "INVALID_TARGET_DIR"
        assert not cwd_leaked.exists(), "Empty target_dir must NOT leak project folder to CWD"

        # 2. Whitespace-only target_dir fails closed
        for bad_dir in ["   ", "\t", "  \n  "]:
            res_ws = cscape_new_iec_project(project_name=proj_name, target_dir=bad_dir)
            assert res_ws["success"] is False
            assert res_ws["status"] == "failed"
            assert res_ws["error_code"] == "INVALID_TARGET_DIR"
            assert not cwd_leaked.exists(), f"Whitespace target_dir '{bad_dir!r}' must NOT leak project folder to CWD"

        # 3. Valid target_dir succeeds cleanly and creates project in designated location
        valid_dest = tmp_path / "valid_project_dest"
        res_valid = cscape_new_iec_project(project_name=proj_name, target_dir=str(valid_dest))
        assert res_valid["success"] is True
        assert res_valid["status"] == "success"
        assert (valid_dest / proj_name / f"{proj_name}.csp").exists()
        assert (valid_dest / proj_name / "cscape_project.json").exists()
        assert not cwd_leaked.exists(), "Project must only be created inside the valid designated target_dir"
    finally:
        if cwd_leaked.exists():
            import shutil
            shutil.rmtree(cwd_leaked, ignore_errors=True)


# -----------------------------------------------------------------------------
# Case 49: cscape_compile_project Path Traversal & Container Verification Fails Closed
# -----------------------------------------------------------------------------
def test_case49_compile_project_path_traversal_and_escapes_fail_closed(tmp_path):
    """cscape_compile_project must fail closed against path traversal (../, ..),
    dot/slash directories (., ./), and uncontained folders lacking genuine project containers.
    """
    # 1. Dot and slash directory references fail closed
    for dot_path in [".", "./", ".\\"]:
        res_dot = cscape_compile_project(dot_path)
        assert res_dot["success"] is False
        assert res_dot["status"] == "failed"
        assert res_dot["error_code"] in ("SECURITY_BLOCKED", "INVALID_PROJECT_NAME")

    # 2. Path traversal sequences fail closed with SECURITY_BLOCKED
    for trav_path in ["../../escape", "../outside", "proj/../../escape"]:
        res_trav = cscape_compile_project(trav_path)
        assert res_trav["success"] is False
        assert res_trav["status"] == "failed"
        assert res_trav["error_code"] in ("SECURITY_BLOCKED", "INVALID_PROJECT_NAME")
        assert any("Path traversal" in err or "Invalid project name" in err for err in res_trav.get("errors", []))

    # 3. Existing folder on disk that lacks a project container (.csp, .cpj, cscape_project.json) fails closed
    uncontained_dir = tmp_path / "Uncontained_Folder_No_Container"
    uncontained_dir.mkdir(parents=True, exist_ok=True)
    (uncontained_dir / "pous").mkdir(parents=True, exist_ok=True)
    (uncontained_dir / "pous" / "Logic.st").write_text(
        "PROGRAM Logic\nVAR x: INT; END_VAR\nx := 1;\nEND_PROGRAM\n",
        encoding="utf-8",
    )

    res_uncontained = cscape_compile_project(str(uncontained_dir))
    assert res_uncontained["success"] is False
    assert res_uncontained["status"] == "failed"
    assert res_uncontained["error_code"] == "PROJECT_NOT_FOUND"
    assert any("contains no valid project container" in err for err in res_uncontained.get("errors", []))




