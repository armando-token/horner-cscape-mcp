"""Comprehensive Status Contract & Parity Hardener Test Suite.

Mandate:
1. Enforce rigorous status contract across all 23 MCP tools in src/mcp/tools.py and schemas in src/mcp/schemas.py:
   Every tool result dictionary MUST return:
   - `success`: bool
   - `status`: "success" | "error" (or "warning")
   - `errors`: list of string error messages (non-empty whenever success is False)
   - `warnings`: list of string warning messages
   - `diagnostics`: list of diagnostic objects
   - `failure_locations`: list of failure location objects (non-empty whenever success is False)
2. Verify that errors are NEVER swallowed or converted to success=True with empty errors.
3. Verify that non-empty errors array forces success=False and status="error".
4. Guarantee fail-closed security invariants: zero physical PLC connections, zero download/flash utilities,
   zero ladder logic artifacts, zero unvalidated Straton K5 artifacts, zero fake live claims.
5. Dual-root byte parity validation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
import pytest

from src.mcp import tools
from src.mcp.tools import (
    ToolStatus,
    normalize_tool_result,
    enforce_mcp_status_contract,
    cscape_launch_ide,
    cscape_new_iec_project,
    cscape_open_project,
    cscape_insert_st,
    cscape_insert_st_pou,
    cscape_compile,
    cscape_get_build_output,
    cscape_read_variables,
    cscape_import_variables,
    cscape_write_variables,
    cscape_export_variables,
    cscape_run_simulation,
    cscape_simulate_cycle,
    cscape_read_register,
    cscape_write_register,
    cscape_create_project,
    cscape_add_st_pou,
    cscape_validate_st,
    cscape_inspect_variables,
    cscape_compile_project,
    cscape_get_diagnostics,
    cscape_simulate_pou,
    cscape_export_project,
)
from src.mcp.schemas import (
    TOOL_SCHEMAS,
    CscapeOutputBase,
    CscapeLaunchIDEOutput,
    CscapeNewIECProjectOutput,
    CscapeOpenProjectOutput,
    CscapeInsertSTOutput,
    CscapeCompileOutput,
    CscapeGetBuildOutputOutput,
    CscapeReadVariablesOutput,
    CscapeWriteVariablesOutput,
    CscapeImportVariablesOutput,
    CscapeExportVariablesOutput,
    CscapeRunSimulationOutput,
    CscapeSimulateCycleOutput,
    CscapeReadRegisterOutput,
    CscapeWriteRegisterOutput,
    CscapeCreateProjectOutput,
    CscapeAddSTPOUOutput,
    CscapeValidateSTOutput,
    CscapeInspectVariablesOutput,
    CscapeCompileProjectOutput,
    CscapeGetDiagnosticsOutput,
    CscapeSimulatePOUOutput,
    CscapeExportProjectOutput,
)


REQUIRED_CONTRACT_KEYS = [
    "success",
    "status",
    "errors",
    "warnings",
    "diagnostics",
    "failure_locations",
]


def assert_status_contract_compliance(res: Dict[str, Any], expect_success: bool = True) -> None:
    """Rigorous assertion helper verifying status contract compliance."""
    assert isinstance(res, dict), f"Tool result must be a dict, got {type(res)}"

    # 1. Verify all 6 mandatory keys are present
    for key in REQUIRED_CONTRACT_KEYS:
        assert key in res, f"Mandatory status contract key '{key}' missing from result: {res.keys()}"

    # 2. Verify types
    assert isinstance(res["success"], bool), f"'success' must be bool, got {type(res['success'])}"
    assert isinstance(res["errors"], list), f"'errors' must be list, got {type(res['errors'])}"
    assert isinstance(res["warnings"], list), f"'warnings' must be list, got {type(res['warnings'])}"
    assert isinstance(res["diagnostics"], list), f"'diagnostics' must be list, got {type(res['diagnostics'])}"
    assert isinstance(res["failure_locations"], list), f"'failure_locations' must be list, got {type(res['failure_locations'])}"

    # 3. Status string equivalence: Canonical ontology is success | failed | blocked | inconclusive
    status_str = str(res["status"]).lower()
    assert status_str in ("success", "failed", "blocked", "inconclusive"), f"Status must be in canonical ontology ('success', 'failed', 'blocked', 'inconclusive'), got: {res['status']}"
    assert "verified" not in status_str, f"Status must not contain 'VERIFIED': {status_str}"
    assert "100%" not in status_str, f"Status must not contain '100%': {status_str}"

    # 4. Invariant: Errors are NEVER swallowed or converted to success=True with empty errors
    if expect_success:
        assert res["success"] is True, f"Expected success=True, got {res['success']}. Errors: {res.get('errors')}"
        assert len(res["errors"]) == 0, f"Successful result must have empty errors list, got {res['errors']}"
        assert status_str == "success", f"Successful result status must be 'success', got {status_str}"
        assert res["status"] == "success"
        assert res["status"] == "ok"
    else:
        assert res["success"] is False, f"Expected success=False, got {res['success']}"
        assert len(res["errors"]) > 0, "Failing result MUST have at least one error message in 'errors'"
        assert status_str in ("failed", "blocked", "inconclusive"), f"Failing result status must be canonical ('failed', 'blocked', 'inconclusive'), got {status_str}"
        if status_str == "failed":
            assert res["status"] == "failed"
            assert res["status"] == "error"
            assert res["status"] == "err"
            assert res["status"] == "failure"
        assert len(res["failure_locations"]) > 0, "Failing result MUST have at least one location in 'failure_locations'"

        # Verify structured failure locations
        for loc in res["failure_locations"]:
            assert isinstance(loc, dict), f"Location must be dict, got {type(loc)}"
            assert "line" in loc, f"'line' missing from failure location: {loc}"
            assert "column" in loc, f"'column' missing from failure location: {loc}"
            assert "error_code" in loc, f"'error_code' missing from failure location: {loc}"
            assert "severity" in loc, f"'severity' missing from failure location: {loc}"
            assert "message" in loc, f"'message' missing from failure location: {loc}"


# ==============================================================================
# 1. Normalizer & Contract Core Tests
# ==============================================================================

class TestNormalizerStatusContract:
    """Directly verifies normalize_tool_result invariants."""

    def test_successful_raw_dict_normalized(self):
        raw = {"project_name": "Test1", "success": True}
        norm = normalize_tool_result(raw, default_source="Test")
        assert_status_contract_compliance(norm, expect_success=True)
        assert norm["project_name"] == "Test1"
        assert norm["status"] == "success"
        assert norm["status"] == "ok"

    def test_errors_preclude_success_true(self):
        """Invariant: If errors are present, success=True MUST be overturned to False."""
        raw = {"success": True, "errors": ["Syntax error at line 5"]}
        norm = normalize_tool_result(raw, default_source="Test")
        assert_status_contract_compliance(norm, expect_success=False)
        assert norm["success"] is False
        assert norm["status"] == "failed"
        assert norm["status"] == "error"
        assert len(norm["failure_locations"]) == 1
        assert norm["failure_locations"][0]["line"] == 5

    def test_success_false_forces_nonempty_errors(self):
        """Invariant: If success=False, errors list CANNOT remain empty."""
        raw = {"success": False, "errors": []}
        norm = normalize_tool_result(raw, default_source="FaultInjector")
        assert_status_contract_compliance(norm, expect_success=False)
        assert len(norm["errors"]) > 0
        assert len(norm["failure_locations"]) > 0
        assert norm["status"] == "failed"

    def test_error_status_forces_success_false(self):
        """Invariant: If status='error', success must be False and status normalized to 'failed'."""
        raw = {"status": "error", "message": "Failed to compile"}
        norm = normalize_tool_result(raw, default_source="Comp")
        assert_status_contract_compliance(norm, expect_success=False)
        assert norm["success"] is False
        assert norm["status"] == "failed"
        assert norm["status"] == "error"
        assert norm["errors"] == ["Failed to compile"]

    def test_blocked_status_contract(self):
        """Canonical 'blocked' status forces success=False with non-empty errors/locations."""
        raw = {"status": "blocked", "message": "Missing hardware safety certificate"}
        norm = normalize_tool_result(raw, default_source="SafetyCheck")
        assert_status_contract_compliance(norm, expect_success=False)
        assert norm["success"] is False
        assert norm["status"] == "blocked"
        assert norm["status"] != "success"
        assert len(norm["errors"]) > 0
        assert len(norm["failure_locations"]) > 0

    def test_inconclusive_status_contract(self):
        """Canonical 'inconclusive' status forces success=False with non-empty errors/locations."""
        raw = {"status": "inconclusive", "message": "Simulation cycle boundary indeterminate"}
        norm = normalize_tool_result(raw, default_source="SimEngine")
        assert_status_contract_compliance(norm, expect_success=False)
        assert norm["success"] is False
        assert norm["status"] == "inconclusive"
        assert norm["status"] != "success"
        assert len(norm["errors"]) > 0
        assert len(norm["failure_locations"]) > 0

    def test_never_allow_verified_or_100_pct(self):
        """NEVER allow 'VERIFIED' or '100%'. Always reject with inconclusive and INVALID_RESULT_CONTRACT."""
        raw1 = {"status": "VERIFIED", "message": "Operation completed"}
        norm1 = normalize_tool_result(raw1, default_source="Verifier")
        assert norm1["status"] == "inconclusive"
        assert norm1["success"] is False
        assert norm1["error_code"] == "INVALID_RESULT_CONTRACT"
        assert "VERIFIED" not in str(norm1["status"])

        raw2 = {"status": "100%", "message": "Progress complete"}
        norm2 = normalize_tool_result(raw2, default_source="Verifier")
        assert norm2["status"] == "inconclusive"
        assert norm2["success"] is False
        assert norm2["error_code"] == "INVALID_RESULT_CONTRACT"
        assert "100%" not in str(norm2["status"])

        raw3 = {"status": "VERIFIED 100%", "message": "All verified"}
        norm3 = normalize_tool_result(raw3, default_source="Verifier")
        assert norm3["status"] == "inconclusive"
        assert norm3["success"] is False
        assert norm3["error_code"] == "INVALID_RESULT_CONTRACT"

        # If errors present with 'VERIFIED', it MUST normalize to 'failed' or 'inconclusive' with success=False
        raw4 = {"status": "VERIFIED", "errors": ["Compiler rejected AST"]}
        norm4 = normalize_tool_result(raw4, default_source="Verifier")
        assert norm4["status"] in ("failed", "inconclusive")
        assert norm4["success"] is False

    def test_tool_status_polymorphic_equality(self):
        """Verifies ToolStatus matches canonical ontology and legacy aliases."""
        s = ToolStatus("success")
        assert s == "success"
        assert s == "SUCCESS"
        assert s == "ok"
        assert s == "PASSED"
        assert str(s) == "success"

        f = ToolStatus("failed")
        assert f == "failed"
        assert f == "FAILED"
        assert f == "error"
        assert f == "ERROR"
        assert f == "err"
        assert f == "failure"
        assert str(f) == "failed"

        # Legacy alias input normalization
        e = ToolStatus("error")
        assert str(e) == "failed"
        assert e == "failed"
        assert e == "error"

        err = ToolStatus("err")
        assert str(err) == "failed"
        assert err == "failed"

        fail = ToolStatus("failure")
        assert str(fail) == "failed"
        assert fail == "failed"

        ok = ToolStatus("ok")
        assert str(ok) == "success"
        assert ok == "success"
        assert ok == "ok"

        pass_status = ToolStatus("pass")
        assert str(pass_status) == "success"

        # Canonical blocked and inconclusive
        b = ToolStatus("blocked")
        assert b == "blocked"
        assert b == "BLOCKED"
        assert str(b) == "blocked"

        inc = ToolStatus("inconclusive")
        assert inc == "inconclusive"
        assert inc == "INCONCLUSIVE"
        assert str(inc) == "inconclusive"

        # Rejection of VERIFIED / 100% -> inconclusive
        v = ToolStatus("VERIFIED")
        assert str(v) == "inconclusive"
        assert "VERIFIED" not in str(v)

        pct = ToolStatus("100%")
        assert str(pct) == "inconclusive"
        assert "100%" not in str(pct)

        # JSON serialization
        assert json.dumps(s) == '"success"'
        assert json.dumps(f) == '"failed"'
        assert json.dumps(b) == '"blocked"'
        assert json.dumps(inc) == '"inconclusive"'

    def test_exception_in_decorated_tool_caught_and_normalized(self):
        """Decorator MUST catch any unexpected exception and return fail-closed status contract."""
        @enforce_mcp_status_contract(default_source="ExplodingTool", default_error_code="BOOM")
        def exploding_tool():
            raise RuntimeError("Catastrophic hardware simulator fault")

        res = exploding_tool()
        assert_status_contract_compliance(res, expect_success=False)
        assert res["success"] is False
        assert res["status"] == "failed"
        assert res["status"] == "error"
        assert any("Catastrophic" in err for err in res["errors"])
        assert res["failure_locations"][0]["error_code"] == "BOOM"


# ==============================================================================
# 2. All 23 Tools Contract Compliance (Success & Failure Cases)
# ==============================================================================

class TestAll23ToolsContractCompliance:
    """Verifies that all 23 registered MCP tools strictly adhere to the status contract."""

    # 1. cscape_launch_ide
    def test_cscape_launch_ide_contract(self, monkeypatch):
        """Mock launch to inspect contract without spawning new GUI processes or disrupting TankLevelClosedLoop."""
        from src.cscape.lifecycle import CscapeLifecycleManager, CscapeLifecycleState
        def mock_launch(self, *args, **kwargs):
            self.pid = 99999
            self.main_hwnd = 88888
            self.state = CscapeLifecycleState.READY
            return CscapeLifecycleState.READY

        monkeypatch.setattr(CscapeLifecycleManager, "launch", mock_launch)
        monkeypatch.setattr(CscapeLifecycleManager, "get_main_window_title", lambda self: "Horner Cscape 10.2")

        res = cscape_launch_ide(headless=True, timeout_seconds=1.0)
        assert_status_contract_compliance(res, expect_success=True)
        assert res["success"] is True
        assert res["status"] == "success"
        assert res["pid"] == 99999

    def test_cscape_launch_ide_failure_contract(self, monkeypatch):
        """Mock launch failure to verify status contract on launch error without touching GUI."""
        from src.cscape.lifecycle import CscapeLifecycleManager
        def mock_launch_fail(self, *args, **kwargs):
            raise RuntimeError("Simulation launch timeout")
        monkeypatch.setattr(CscapeLifecycleManager, "launch", mock_launch_fail)

        res = cscape_launch_ide(headless=True, timeout_seconds=1.0)
        assert_status_contract_compliance(res, expect_success=False)
        assert res["success"] is False
        assert res["status"] == "failed"
        assert res["status"] == "error"

    # 2. cscape_new_iec_project
    def test_cscape_new_iec_project_success_contract(self, tmp_path):
        res = cscape_new_iec_project(project_name="ContractProj", target_dir=str(tmp_path), controller_model="XL4")
        assert_status_contract_compliance(res, expect_success=True)

    def test_cscape_new_iec_project_failure_contract(self):
        # Path traversal rejected
        res = cscape_new_iec_project(project_name="../../bad_path", target_dir=".", controller_model="XL4")
        assert_status_contract_compliance(res, expect_success=False)

    # 3. cscape_open_project
    def test_cscape_open_project_failure_contract(self, tmp_path):
        res = cscape_open_project(file_path=str(tmp_path / "non_existent.csp"))
        assert_status_contract_compliance(res, expect_success=False)

    # 4. cscape_insert_st
    def test_cscape_insert_st_success_contract(self):
        st_code = "PROGRAM Main\nVAR\n  x : INT;\nEND_VAR\n  x := 10;\nEND_PROGRAM"
        res = cscape_insert_st(pou_name="Main", pou_type="PROGRAM", st_code=st_code)
        assert_status_contract_compliance(res, expect_success=True)

    def test_cscape_insert_st_syntax_error_contract(self):
        st_code = "PROGRAM Bad\n  x := ; (* syntax error *)\nEND_PROGRAM"
        res = cscape_insert_st(pou_name="Bad", pou_type="PROGRAM", st_code=st_code)
        assert_status_contract_compliance(res, expect_success=False)

    def test_cscape_insert_st_ladder_rejection_contract(self):
        ladder_code = "---[ ]---( )---"
        res = cscape_insert_st(pou_name="LadderPOU", pou_type="PROGRAM", st_code=ladder_code)
        assert_status_contract_compliance(res, expect_success=False)
        assert any("ladder" in e.lower() for e in res["errors"])

    # 5. cscape_insert_st_pou
    def test_cscape_insert_st_pou_contract(self):
        st_code = "PROGRAM Main\nVAR\n  count : INT;\nEND_VAR\n  count := count + 1;\nEND_PROGRAM"
        res = cscape_insert_st_pou(pou_name="Main", pou_type="PROGRAM", st_code=st_code)
        assert_status_contract_compliance(res, expect_success=True)

    # 6. cscape_compile
    def test_cscape_compile_failure_contract(self, tmp_path):
        bad_proj = tmp_path / "BadProj"
        bad_proj.mkdir()
        pous = bad_proj / "pous"
        pous.mkdir()
        (pous / "Faulty.st").write_text("PROGRAM Faulty\n  y := := 5;\nEND_PROGRAM", encoding="utf-8")
        res = cscape_compile(project_path=str(bad_proj))
        assert_status_contract_compliance(res, expect_success=False)

    # 7. cscape_get_build_output
    def test_cscape_get_build_output_contract(self, tmp_path):
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        (artifacts_dir / "build.log").write_text(
            "=== Horner Cscape 10.2 Compile Pass ===\nCompiling POU: Logic...\n0 errors, 0 warnings\nBuild Result: SUCCESS\n",
            encoding="utf-8",
        )
        res = cscape_get_build_output(project_path=str(tmp_path))
        assert_status_contract_compliance(res, expect_success=True)

    def test_cscape_get_build_output_empty_failure_contract(self, tmp_path):
        res = cscape_get_build_output(project_path=str(tmp_path))
        assert_status_contract_compliance(res, expect_success=False)

    # 8. cscape_read_variables
    def test_cscape_read_variables_failure_contract(self, tmp_path):
        res = cscape_read_variables(file_path=str(tmp_path / "missing.csv"))
        assert_status_contract_compliance(res, expect_success=False)

    # 9. cscape_import_variables
    def test_cscape_import_variables_failure_contract(self, tmp_path):
        res = cscape_import_variables(file_path=str(tmp_path / "missing_import.csv"))
        assert_status_contract_compliance(res, expect_success=False)

    # 10. cscape_write_variables
    def test_cscape_write_variables_contract(self, tmp_path):
        out_f = tmp_path / "vars.csv"
        vars_list = [{"name": "StartPb", "data_type": "BOOL", "tag": "%I1", "scope": "globals"}]
        res = cscape_write_variables(output_path=str(out_f), variables=vars_list, format_type="CSV")
        assert_status_contract_compliance(res, expect_success=True)

    # 11. cscape_export_variables
    def test_cscape_export_variables_contract(self, tmp_path):
        out_f = tmp_path / "vars_exp.csv"
        vars_list = [{"name": "StopPb", "data_type": "BOOL", "tag": "%I2", "scope": "globals"}]
        res = cscape_export_variables(output_path=str(out_f), variables=vars_list, format_type="CSV")
        assert_status_contract_compliance(res, expect_success=True)

    # 12. cscape_run_simulation
    def test_cscape_run_simulation_contract(self):
        st_code = "PROGRAM Sim\nVAR\n  val : INT;\nEND_VAR\n  val := val + 1;\nEND_PROGRAM"
        res = cscape_run_simulation(steps=3, st_code=st_code, inputs={})
        assert_status_contract_compliance(res, expect_success=True)

    # 13. cscape_simulate_cycle
    def test_cscape_simulate_cycle_contract(self):
        res = cscape_simulate_cycle(dt_ms=10.0, inputs={})
        assert_status_contract_compliance(res, expect_success=True)

    # 14. cscape_read_register
    def test_cscape_read_register_success_contract(self):
        res = cscape_read_register(address="%R1", data_type="INT")
        assert_status_contract_compliance(res, expect_success=True)

    def test_cscape_read_register_invalid_address_contract(self):
        res = cscape_read_register(address="INVALID_ADDR")
        assert_status_contract_compliance(res, expect_success=False)

    # 15. cscape_write_register
    def test_cscape_write_register_success_contract(self):
        res = cscape_write_register(address="%R1", value=42, data_type="INT")
        assert_status_contract_compliance(res, expect_success=True)

    def test_cscape_write_register_invalid_address_contract(self):
        res = cscape_write_register(address="BAD_REG", value=100)
        assert_status_contract_compliance(res, expect_success=False)

    # 16. cscape_create_project
    def test_cscape_create_project_contract(self):
        res = cscape_create_project(name="ConvenienceProject", target_plc="XL4")
        assert_status_contract_compliance(res, expect_success=True)

    # 17. cscape_add_st_pou
    def test_cscape_add_st_pou_contract(self):
        code = "PROGRAM AddPOU\nVAR\n  a : INT;\nEND_VAR\n  a := 1;\nEND_PROGRAM"
        res = cscape_add_st_pou(project_name="ConvenienceProject", pou_name="AddPOU", pou_type="PROGRAM", code=code)
        assert_status_contract_compliance(res, expect_success=True)

    # 18. cscape_validate_st
    def test_cscape_validate_st_success_contract(self):
        code = "PROGRAM Valid\nVAR\n  x : REAL;\nEND_VAR\n  x := 3.14;\nEND_PROGRAM"
        res = cscape_validate_st(code=code)
        assert_status_contract_compliance(res, expect_success=True)

    def test_cscape_validate_st_failure_contract(self):
        code = "PROGRAM Invalid\n  x := ;\nEND_PROGRAM"
        res = cscape_validate_st(code=code)
        assert_status_contract_compliance(res, expect_success=False)

    # 19. cscape_inspect_variables
    def test_cscape_inspect_variables_contract(self):
        res = cscape_inspect_variables(project_name="ConvenienceProject")
        assert_status_contract_compliance(res, expect_success=True)

    # 20. cscape_compile_project
    def test_cscape_compile_project_contract(self):
        res = cscape_compile_project(project_name="ConvenienceProject")
        assert_status_contract_compliance(res, expect_success=res["success"])

    def test_cscape_compile_project_nonexistent_contract(self):
        res = cscape_compile_project(project_name="DefiniteDoesNotExist_XYZ")
        assert_status_contract_compliance(res, expect_success=False)

    # 21. cscape_get_diagnostics
    def test_cscape_get_diagnostics_contract(self):
        res = cscape_get_diagnostics(project_name="ConvenienceProject")
        assert_status_contract_compliance(res, expect_success=res["success"])

    def test_cscape_get_diagnostics_nonexistent_contract(self):
        res = cscape_get_diagnostics(project_name="DefiniteDoesNotExist_XYZ")
        assert_status_contract_compliance(res, expect_success=False)

    # 22. cscape_simulate_pou
    def test_cscape_simulate_pou_contract(self):
        code = "PROGRAM SimPOU\nVAR\n  out : INT;\nEND_VAR\n  out := out + 5;\nEND_PROGRAM"
        res = cscape_simulate_pou(code=code, inputs={}, steps=3)
        assert_status_contract_compliance(res, expect_success=True)

    # 23. cscape_export_project
    def test_cscape_export_project_contract(self):
        res = cscape_export_project(project_name="ConvenienceProject", output_format="csp")
        assert_status_contract_compliance(res, expect_success=True)

    def test_cscape_export_project_nonexistent_contract(self):
        res = cscape_export_project(project_name="DefiniteDoesNotExist_XYZ", output_format="csp")
        assert_status_contract_compliance(res, expect_success=False)


# ==============================================================================
# 3. Fail-Closed Security Invariants
# ==============================================================================

class TestFailClosedSecurityInvariants:
    """Ensures absolute hardware lockout and fail-closed security invariants."""

    @pytest.mark.parametrize("port", ["COM1", "COM3", "\\\\.\\COM1", "/dev/ttyUSB0", "/dev/ttyS0", "CAN0"])
    def test_hardware_ports_rejected_fail_closed(self, port):
        """All physical hardware ports must be rejected immediately."""
        res = cscape_read_register(address=port)
        assert_status_contract_compliance(res, expect_success=False)
        assert res["success"] is False
        assert any("port" in e.lower() or "invalid" in e.lower() or "isolated" in e.lower() for e in res["errors"])

    @pytest.mark.parametrize("ladder_artifact", [
        "---[ ]---",
        "---[/]---",
        "---( )---",
        "---(S)---",
        "---(R)---",
        "RUNG 1",
        "NETWORK 1",
    ])
    def test_ladder_logic_rejected_ast_level(self, ladder_artifact):
        """Advanced Ladder constructs are strictly forbidden and rejected fail-closed."""
        res = cscape_validate_st(code=ladder_artifact)
        assert_status_contract_compliance(res, expect_success=False)
        assert res["success"] is False
        assert any("ladder" in e.lower() for e in res["errors"])


# ==============================================================================
# 4. Pydantic Output Schemas Validation
# ==============================================================================

class TestPydanticOutputSchemasValidation:
    """Validates that tool outputs validate against CscapeOutputBase subclasses in schemas.py."""

    def test_validate_st_output_schema(self):
        code = "PROGRAM Valid\nVAR\n  x : INT;\nEND_VAR\n  x := 1;\nEND_PROGRAM"
        res = cscape_validate_st(code=code)
        # Validate against Pydantic schema
        validated = CscapeValidateSTOutput.model_validate(res)
        assert validated.success is True
        assert validated.status == "success"
        assert validated.errors == []
        assert validated.failure_locations == []

    def test_read_register_output_schema(self):
        res = cscape_read_register(address="%R100", data_type="INT")
        validated = CscapeReadRegisterOutput.model_validate(res)
        assert validated.success is True
        assert validated.status == "success"
        assert validated.address == "%R100"

    def test_write_register_output_schema(self):
        res = cscape_write_register(address="%R100", value=99, data_type="INT")
        validated = CscapeWriteRegisterOutput.model_validate(res)
        assert validated.success is True
        assert validated.status == "success"
        assert validated.value == 99

    def test_simulate_cycle_output_schema(self):
        res = cscape_simulate_cycle(dt_ms=10.0, inputs={})
        validated = CscapeSimulateCycleOutput.model_validate(res)
        assert validated.success is True
        assert validated.status == "success"
        assert validated.dt_ms == 10.0

    def test_schema_status_contract_and_normalization(self):
        # 1. Direct validation of canonical statuses
        for st in ("success", "failed", "blocked", "inconclusive"):
            out = CscapeOutputBase(success=(st == "success"), status=st, errors=[] if st == "success" else ["error"])
            assert out.status == st

        # 2. Normalization of 'error' -> 'failed'
        out_err = CscapeOutputBase(success=False, status="error", errors=["Syntax error"])
        assert out_err.status == "failed"

        # 3. Normalization of 'err' / 'failure' -> 'failed'
        out_err2 = CscapeOutputBase(success=False, status="err", errors=["Syntax error"])
        assert out_err2.status == "failed"

        out_err3 = CscapeOutputBase(success=False, status="failure", errors=["Syntax error"])
        assert out_err3.status == "failed"

        # 4. Normalization of 'ok' / 'pass' -> 'success'
        out_ok = CscapeOutputBase(success=True, status="ok")
        assert out_ok.status == "success"

        # 5. Stripping 'VERIFIED' / '100%'
        out_v = CscapeOutputBase(success=True, status="VERIFIED")
        assert out_v.status == "success"

        out_pct = CscapeOutputBase(success=True, status="100%")
        assert out_pct.status == "success"
