"""End-to-End MCP Closed-Loop Verification Test Suite.

Verifies:
1. Complete closed-loop verification across all 8 MCP tools:
   - cscape_create_project
   - cscape_add_st_pou
   - cscape_validate_st
   - cscape_inspect_variables
   - cscape_compile_project
   - cscape_get_diagnostics
   - cscape_simulate_pou
   - cscape_export_project

2. Intentional Failure Scenarios:
   - Scenario 1: Syntax error (Unclosed IF block)
   - Scenario 2: Missing semicolon (Assignment missing terminating ';')
   - Scenario 3: Undeclared variable (Identifier used without VAR declaration)
   - Scenario 4: Ladder logic injection (Normally open contact '---[ ]---')
   - Scenario 5: Syntax error near ; (Expression syntax error near ';')

3. Exact Failure Location Verification:
   - file path
   - line number
   - column number
   - error code

4. Strict Zero PLC Download Lockout Enforcement.
"""

import shutil
from pathlib import Path
import pytest

from src.mcp.tools import (
    cscape_create_project,
    cscape_add_st_pou,
    cscape_validate_st,
    cscape_inspect_variables,
    cscape_compile_project,
    cscape_get_diagnostics,
    cscape_simulate_pou,
    cscape_export_project,
)
from src.cscape.diagnostics import CscapeLogParser
from src.security.exceptions import UnauthorizedDownloadError, HardwareLockoutError
from src.automation.cli_runner import CLIRunner
from src.automation.com_bridge import CscapeAutomationBridge
from src.cscape.simulation import enforce_software_isolation

REPO_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
PROJECTS_ROOT = REPO_ROOT / "artifacts" / "projects"


@pytest.fixture(scope="module")
def happy_project_name():
    return "E2E_ClosedLoop_Verification"


@pytest.fixture(scope="module", autouse=True)
def cleanup_projects():
    yield
    for name in [
        "E2E_ClosedLoop_Verification",
        "Fail_Syntax_Project",
        "Fail_Semicolon_Project",
        "Fail_Undeclared_Project",
        "Fail_Ladder_Project",
        "Fail_SyntaxNearSemi_Project",
    ]:
        p = PROJECTS_ROOT / name
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)


# ==============================================================================
# 1. Complete E2E Closed-Loop Verification Across All 8 MCP Tools
# ==============================================================================

class TestMCPAll8ToolsClosedLoop:
    """Verifies complete valid execution across all 8 MCP tools."""

    def test_e2e_all_8_tools_pipeline(self, happy_project_name):
        # 1. cscape_create_project
        create_res = cscape_create_project(
            name=happy_project_name,
            description="End-to-End Closed-Loop Verification Project",
            target_plc="XL4",
        )
        assert create_res["status"] == "success"
        assert create_res["success"] is True
        assert create_res["project_name"] == happy_project_name
        assert Path(create_res["project_path"]).exists()
        assert (Path(create_res["project_path"]) / "cscape_project.json").exists()

        # 2. cscape_validate_st (Pre-insertion validation)
        valid_st_code = """PROGRAM ClosedLoopTank
VAR_INPUT
    RawLevelIn : INT;
    SetPoint : REAL := 50.0;
    AutoMode : BOOL := TRUE;
END_VAR
VAR_OUTPUT
    PumpSpeed : INT;
    HighAlarm : BOOL;
END_VAR
VAR
    LevelPercent : REAL;
END_VAR

LevelPercent := (INT_TO_REAL(RawLevelIn) / 32000.0) * 100.0;

IF LevelPercent >= 90.0 THEN
    HighAlarm := TRUE;
ELSE
    HighAlarm := FALSE;
END_IF;

IF AutoMode THEN
    IF LevelPercent < SetPoint THEN
        PumpSpeed := 25000;
    ELSE
        PumpSpeed := 8000;
    END_IF;
ELSE
    PumpSpeed := 0;
END_IF;
END_PROGRAM
"""
        val_res = cscape_validate_st(valid_st_code)
        assert val_res["valid"] is True
        assert val_res["pou_name"] == "ClosedLoopTank"
        assert val_res["pou_type"] == "PROGRAM"
        assert len(val_res["errors"]) == 0
        assert len(val_res["variables"]) == 6

        # 3. cscape_add_st_pou
        add_res = cscape_add_st_pou(
            project_name=happy_project_name,
            pou_name="ClosedLoopTank",
            pou_type="PROGRAM",
            code=valid_st_code,
            cycle_time_ms=10,
        )
        assert add_res["status"] == "success"
        assert add_res["success"] is True
        assert add_res["pou_name"] == "ClosedLoopTank"
        assert Path(add_res["file_path"]).exists()

        # 4. cscape_inspect_variables
        inspect_res = cscape_inspect_variables(happy_project_name)
        assert inspect_res["status"] == "success"
        assert inspect_res["project_name"] == happy_project_name
        assert inspect_res["total_variables"] == 6
        assert "ClosedLoopTank" in inspect_res["pous"]
        inputs = [v["name"] for v in inspect_res["by_scope"]["inputs"]]
        outputs = [v["name"] for v in inspect_res["by_scope"]["outputs"]]
        assert "RawLevelIn" in inputs
        assert "PumpSpeed" in outputs

        # 5. cscape_compile_project
        compile_res = cscape_compile_project(happy_project_name, clean_build=True)
        assert compile_res["status"] == "success"
        assert compile_res["success"] is True
        assert compile_res["compile_successful"] is True
        assert compile_res["error_count"] == 0
        assert len(compile_res["errors"]) == 0
        assert "ClosedLoopTank" in compile_res["pous_compiled"]
        assert compile_res["memory_footprint"]["code_size_bytes"] > 0
        assert "Build Result: SUCCESS" in compile_res["build_log"]

        # 6. cscape_get_diagnostics
        diag_res = cscape_get_diagnostics(happy_project_name)
        assert diag_res["status"] == "success"
        assert diag_res["compile_successful"] is True
        assert diag_res["error_count"] == 0
        assert "diagnostics" in diag_res
        assert "memory_footprint" in diag_res

        # 7. cscape_simulate_pou
        sim_res = cscape_simulate_pou(
            code=valid_st_code,
            inputs={"RawLevelIn": 16000, "SetPoint": 60.0, "AutoMode": True},
            steps=5,
        )
        assert sim_res["success"] is True
        assert sim_res["steps_executed"] == 5
        assert sim_res["isolation_enforced"] is True
        assert sim_res["hardware_lockout_enforced"] is True
        assert "LevelPercent" in sim_res["final_state"]
        assert sim_res["final_state"]["LevelPercent"] == 50.0

        # 8. cscape_export_project
        for fmt in ["csp", "st", "xml", "json"]:
            exp_res = cscape_export_project(happy_project_name, output_format=fmt)
            assert exp_res["status"] == "success"
            assert exp_res["output_format"] == fmt
            assert Path(exp_res["export_file"]).exists()
            assert exp_res["size_bytes"] > 0


# ==============================================================================
# 2. Intentional Failure Scenarios & Failure Location Log Verification
# ==============================================================================

class TestIntentionalFailureLocationVerification:
    """Verifies intentional failure scenarios capture exact file path, line, column, error code."""

    def test_scenario_1_syntax_error_unclosed_if(self):
        """Intentional syntax error: Unclosed IF block missing END_IF."""
        proj_name = "Fail_Syntax_Project"
        cscape_create_project(name=proj_name, description="Syntax Error Failure Test")

        code = """PROGRAM POU_SyntaxError
VAR
    Speed : INT := 100;
END_VAR

IF Speed > 50 THEN
    Speed := 50;
(* Intentional syntax failure: Missing END_IF *)

END_PROGRAM
"""
        # Step A: Pre-validation via cscape_validate_st
        val_res = cscape_validate_st(code)
        assert val_res["valid"] is False
        assert len(val_res["errors"]) > 0
        assert val_res.get("failure_location") is not None
        assert val_res["failure_location"]["file_path"] in ("POU_SyntaxError.st", "Anonymous.st")
        assert val_res["failure_location"]["line"] in (6, 10)
        assert val_res["failure_location"]["column"] >= 1
        assert val_res["failure_location"]["error_code"] in ("ERR_UNCLOSED_IF", "ST_SYNTAX_ERROR", "ERR_UNCLOSED_PROGRAM")

        # Step B: Rejection in cscape_add_st_pou
        add_res = cscape_add_st_pou(
            project_name=proj_name,
            pou_name="POU_SyntaxError",
            pou_type="PROGRAM",
            code=code,
        )
        assert add_res["status"] == "error"
        assert add_res["success"] is False
        assert add_res.get("failure_location") is not None
        assert add_res["failure_location"]["file_path"] == "POU_SyntaxError.st"
        assert add_res["failure_location"]["line"] in (6, 10)

        # Place file on disk to verify compilation diagnostics and build.log location logs
        pou_file = PROJECTS_ROOT / proj_name / "pous" / "POU_SyntaxError.st"
        pou_file.parent.mkdir(parents=True, exist_ok=True)
        pou_file.write_text(code, encoding="utf-8")

        # Step C: Compilation via cscape_compile_project
        comp_res = cscape_compile_project(proj_name, clean_build=True)
        assert comp_res["status"] == "error"
        assert comp_res["compile_successful"] is False
        assert comp_res["error_count"] > 0
        assert comp_res.get("failure_location") is not None
        assert comp_res["failure_location"]["file_path"] == "POU_SyntaxError.st"
        assert comp_res["failure_location"]["line"] in (6, 10)
        assert comp_res["failure_location"]["column"] >= 1
        assert comp_res["failure_location"]["error_code"] in ("ERR_UNCLOSED_IF", "ST_SYNTAX_ERROR", "ERR_UNCLOSED_PROGRAM")

        # Verify build_log captures exact failure location: file path, line, column, error code
        build_log = comp_res["build_log"]
        assert "POU_SyntaxError.st" in build_log
        parsed_diags = CscapeLogParser.parse_log(build_log)
        assert len(parsed_diags) > 0

        syntax_diags = [d for d in parsed_diags if d.pou_name == "POU_SyntaxError"]
        assert len(syntax_diags) > 0
        diag = syntax_diags[0]
        assert diag.file_path == "POU_SyntaxError.st"
        assert diag.line in (6, 10)  # Line 10 (mismatched close) or Line 6 (opened block)
        assert diag.column >= 1
        assert diag.error_code in ("ERR_UNCLOSED_IF", "ST_SYNTAX_ERROR")
        assert diag.level == "ERROR"
        assert any("IF" in d.message or "Unclosed" in d.message or "Mismatched" in d.message for d in syntax_diags)

        # Step D: Retrieve via cscape_get_diagnostics
        get_diag_res = cscape_get_diagnostics(proj_name)
        assert get_diag_res["status"] == "error"
        assert get_diag_res["compile_successful"] is False
        assert len(get_diag_res["diagnostics"]) > 0
        assert get_diag_res.get("failure_location") is not None
        assert get_diag_res["failure_location"]["file_path"] == "POU_SyntaxError.st"
        assert get_diag_res["failure_location"]["line"] in (6, 10)
        assert get_diag_res["failure_location"]["column"] >= 1

    def test_scenario_2_missing_semicolon(self):
        """Intentional syntax error: Statement missing terminating semicolon."""
        proj_name = "Fail_Semicolon_Project"
        cscape_create_project(name=proj_name, description="Missing Semicolon Test")

        code = """PROGRAM POU_MissingSemicolon
VAR
    TargetCount : INT;
END_VAR

TargetCount := 42
END_PROGRAM
"""
        # Step A: Pre-validation via cscape_validate_st
        val_res = cscape_validate_st(code)
        assert val_res["valid"] is False
        assert any("semicolon" in e.lower() for e in val_res["errors"])
        assert val_res.get("failure_location") is not None
        assert val_res["failure_location"]["file_path"] in ("POU_MissingSemicolon.st", "Anonymous.st")
        assert val_res["failure_location"]["line"] in (6, 7)
        assert val_res["failure_location"]["column"] >= 1
        assert val_res["failure_location"]["error_code"] in ("ERR_MISSING_SEMICOLON", "ST_SYNTAX_ERROR")

        # Step B: Rejection in cscape_add_st_pou
        add_res = cscape_add_st_pou(
            project_name=proj_name,
            pou_name="POU_MissingSemicolon",
            pou_type="PROGRAM",
            code=code,
        )
        assert add_res["status"] == "error"
        assert add_res["success"] is False
        assert add_res.get("failure_location") is not None
        assert add_res["failure_location"]["file_path"] == "POU_MissingSemicolon.st"
        assert add_res["failure_location"]["line"] in (6, 7)

        # Place file on disk to verify compilation diagnostics and build.log location logs
        pou_file = PROJECTS_ROOT / proj_name / "pous" / "POU_MissingSemicolon.st"
        pou_file.parent.mkdir(parents=True, exist_ok=True)
        pou_file.write_text(code, encoding="utf-8")

        # Step C: Compilation via cscape_compile_project
        comp_res = cscape_compile_project(proj_name, clean_build=True)
        assert comp_res["status"] == "error"
        assert comp_res["compile_successful"] is False
        assert comp_res["error_count"] > 0
        assert comp_res.get("failure_location") is not None
        assert comp_res["failure_location"]["file_path"] == "POU_MissingSemicolon.st"
        assert comp_res["failure_location"]["line"] in (6, 7)
        assert comp_res["failure_location"]["column"] >= 1
        assert comp_res["failure_location"]["error_code"] in ("ERR_MISSING_SEMICOLON", "ST_SYNTAX_ERROR")

        # Verify build_log captures exact failure location: file path, line, column, error code
        build_log = comp_res["build_log"]
        assert "POU_MissingSemicolon.st" in build_log
        parsed_diags = CscapeLogParser.parse_log(build_log)
        assert len(parsed_diags) > 0

        semi_diags = [d for d in parsed_diags if d.pou_name == "POU_MissingSemicolon"]
        assert len(semi_diags) > 0
        diag = semi_diags[0]
        assert diag.file_path == "POU_MissingSemicolon.st"
        assert diag.line in (6, 7)  # Line 6 (statement) or Line 7 (next token)
        assert diag.column >= 1
        assert diag.error_code in ("ERR_MISSING_SEMICOLON", "ST_SYNTAX_ERROR")
        assert diag.level == "ERROR"
        assert any("semicolon" in d.message.lower() for d in semi_diags)

        # Step D: Retrieve via cscape_get_diagnostics
        get_diag_res = cscape_get_diagnostics(proj_name)
        assert get_diag_res["status"] == "error"
        assert get_diag_res["compile_successful"] is False
        assert get_diag_res.get("failure_location") is not None
        assert get_diag_res["failure_location"]["file_path"] == "POU_MissingSemicolon.st"
        assert get_diag_res["failure_location"]["line"] in (6, 7)
        assert get_diag_res["failure_location"]["column"] >= 1

    def test_scenario_3_undeclared_variable(self):
        """Intentional semantic error: Undeclared variable assignment."""
        proj_name = "Fail_Undeclared_Project"
        cscape_create_project(name=proj_name, description="Undeclared Variable Test")

        code = """PROGRAM POU_UndeclaredVar
VAR
    ValidCounter : INT := 0;
END_VAR

PhantomOutput := 99;
END_PROGRAM
"""
        # Step A: Pre-validation via cscape_validate_st
        val_res = cscape_validate_st(code)
        assert val_res["valid"] is False
        assert any("undeclared" in e.lower() for e in val_res["errors"])
        assert val_res.get("failure_location") is not None
        assert val_res["failure_location"]["file_path"] in ("POU_UndeclaredVar.st", "Anonymous.st")
        assert val_res["failure_location"]["line"] == 6
        assert val_res["failure_location"]["column"] >= 1
        assert val_res["failure_location"]["error_code"] == "ERR_UNDECLARED_VAR"

        # Step B: Rejection in cscape_add_st_pou
        add_res = cscape_add_st_pou(
            project_name=proj_name,
            pou_name="POU_UndeclaredVar",
            pou_type="PROGRAM",
            code=code,
        )
        assert add_res["status"] == "error"
        assert add_res["success"] is False
        assert add_res.get("failure_location") is not None
        assert add_res["failure_location"]["file_path"] == "POU_UndeclaredVar.st"
        assert add_res["failure_location"]["line"] == 6

        # Place file on disk to verify compilation diagnostics and build.log location logs
        pou_file = PROJECTS_ROOT / proj_name / "pous" / "POU_UndeclaredVar.st"
        pou_file.parent.mkdir(parents=True, exist_ok=True)
        pou_file.write_text(code, encoding="utf-8")

        # Step C: Compilation via cscape_compile_project
        comp_res = cscape_compile_project(proj_name, clean_build=True)
        assert comp_res["status"] == "error"
        assert comp_res["compile_successful"] is False
        assert comp_res["error_count"] > 0
        assert comp_res.get("failure_location") is not None
        assert comp_res["failure_location"]["file_path"] == "POU_UndeclaredVar.st"
        assert comp_res["failure_location"]["line"] == 6
        assert comp_res["failure_location"]["column"] >= 1
        assert comp_res["failure_location"]["error_code"] == "ERR_UNDECLARED_VAR"

        # Verify build_log captures exact failure location: file path, line, column, error code
        build_log = comp_res["build_log"]
        assert "POU_UndeclaredVar.st" in build_log
        parsed_diags = CscapeLogParser.parse_log(build_log)
        assert len(parsed_diags) > 0

        undec_diags = [d for d in parsed_diags if d.pou_name == "POU_UndeclaredVar"]
        assert len(undec_diags) > 0
        diag = undec_diags[0]
        assert diag.file_path == "POU_UndeclaredVar.st"
        assert diag.line == 6  # Line 6: PhantomOutput := 99;
        assert diag.column == 1
        assert diag.error_code == "ERR_UNDECLARED_VAR"
        assert "PhantomOutput" in diag.message
        assert diag.level == "ERROR"

        # Step D: Retrieve via cscape_get_diagnostics
        get_diag_res = cscape_get_diagnostics(proj_name)
        assert get_diag_res["status"] == "error"
        assert get_diag_res["compile_successful"] is False
        assert get_diag_res.get("failure_location") is not None
        assert get_diag_res["failure_location"]["file_path"] == "POU_UndeclaredVar.st"
        assert get_diag_res["failure_location"]["line"] == 6
        assert get_diag_res["failure_location"]["column"] >= 1

    def test_scenario_4_ladder_logic_injection(self):
        """Intentional violation: Advanced Ladder logic injection."""
        proj_name = "Fail_Ladder_Project"
        cscape_create_project(name=proj_name, description="Ladder Logic Injection Test")

        code = """PROGRAM POU_LadderInjection
VAR
    InSensor : BOOL := FALSE;
    OutMotor : BOOL;
END_VAR

---[ ]--- InSensor
END_PROGRAM
"""
        # Step A: Pre-validation via cscape_validate_st
        val_res = cscape_validate_st(code)
        assert val_res["valid"] is False
        assert any("ladder" in e.lower() for e in val_res["errors"])
        assert val_res.get("failure_location") is not None
        assert val_res["failure_location"]["file_path"] in ("POU_LadderInjection.st", "Anonymous.st")
        assert val_res["failure_location"]["line"] in (1, 7)
        assert val_res["failure_location"]["column"] >= 1
        assert val_res["failure_location"]["error_code"] == "ERR_LADDER_FORBIDDEN"

        # Step B: Rejection in cscape_add_st_pou
        add_res = cscape_add_st_pou(
            project_name=proj_name,
            pou_name="POU_LadderInjection",
            pou_type="PROGRAM",
            code=code,
        )
        assert add_res["status"] == "error"
        assert add_res["success"] is False
        assert add_res.get("failure_location") is not None
        assert add_res["failure_location"]["file_path"] == "POU_LadderInjection.st"
        assert add_res["failure_location"]["error_code"] == "ERR_LADDER_FORBIDDEN"

        # Place file on disk to verify compilation diagnostics and build.log location logs
        pou_file = PROJECTS_ROOT / proj_name / "pous" / "POU_LadderInjection.st"
        pou_file.parent.mkdir(parents=True, exist_ok=True)
        pou_file.write_text(code, encoding="utf-8")

        # Step C: Compilation via cscape_compile_project
        comp_res = cscape_compile_project(proj_name, clean_build=True)
        assert comp_res["status"] == "error"
        assert comp_res["compile_successful"] is False
        assert comp_res["error_count"] > 0
        assert comp_res.get("failure_location") is not None
        assert comp_res["failure_location"]["file_path"] == "POU_LadderInjection.st"
        assert comp_res["failure_location"]["line"] in (1, 7)
        assert comp_res["failure_location"]["column"] >= 1
        assert comp_res["failure_location"]["error_code"] in ("ERR_LADDER_FORBIDDEN", "ST_SYNTAX_ERROR")

        # Verify build_log captures exact failure location: file path, line, column, error code
        build_log = comp_res["build_log"]
        assert "POU_LadderInjection.st" in build_log
        parsed_diags = CscapeLogParser.parse_log(build_log)
        assert len(parsed_diags) > 0

        ladder_diags = [d for d in parsed_diags if d.pou_name == "POU_LadderInjection"]
        assert len(ladder_diags) > 0
        diag = ladder_diags[0]
        assert diag.file_path == "POU_LadderInjection.st"
        assert diag.line == 7  # Line 7: ---[ ]--- InSensor
        assert diag.column == 1
        assert diag.error_code == "ERR_LADDER_FORBIDDEN"
        assert "ladder" in diag.message.lower()
        assert diag.level == "ERROR"

        # Step D: Retrieve via cscape_get_diagnostics
        get_diag_res = cscape_get_diagnostics(proj_name)
        assert get_diag_res["status"] == "error"
        assert get_diag_res["compile_successful"] is False
        assert get_diag_res.get("failure_location") is not None
        assert get_diag_res["failure_location"]["file_path"] == "POU_LadderInjection.st"
        assert get_diag_res["failure_location"]["line"] in (1, 7)
        assert get_diag_res["failure_location"]["error_code"] in ("ERR_LADDER_FORBIDDEN", "ST_SYNTAX_ERROR")

    def test_scenario_5_syntax_error_near_semicolon(self):
        """Intentional syntax error: Syntax error near ';' (unexpected semicolon)."""
        proj_name = "Fail_SyntaxNearSemi_Project"
        cscape_create_project(name=proj_name, description="Syntax Error Near Semicolon Test")

        code = """PROGRAM POU_SyntaxNearSemi
VAR
    TankLevel : REAL := 50.0;
    TargetLevel : REAL := 60.0;
END_VAR

TargetLevel := TankLevel + ;
END_PROGRAM
"""
        # Step A: Pre-validation via cscape_validate_st
        val_res = cscape_validate_st(code)
        assert val_res["valid"] is False
        assert val_res.get("failure_location") is not None
        v_loc = val_res["failure_location"]
        assert v_loc["file_path"] in ("POU_SyntaxNearSemi.st", "Anonymous.st")
        assert v_loc["line"] == 7
        assert v_loc["column"] >= 1
        assert v_loc["error_code"] == "ST_SYNTAX_ERROR"
        assert ";" in v_loc["message"]

        # Step B: Rejection in cscape_add_st_pou
        add_res = cscape_add_st_pou(
            project_name=proj_name,
            pou_name="POU_SyntaxNearSemi",
            pou_type="PROGRAM",
            code=code,
        )
        assert add_res["status"] == "error"
        assert add_res["success"] is False
        assert add_res.get("failure_location") is not None
        assert add_res["failure_location"]["file_path"] == "POU_SyntaxNearSemi.st"
        assert add_res["failure_location"]["line"] == 7
        assert add_res["failure_location"]["error_code"] == "ST_SYNTAX_ERROR"

        # Place file on disk to verify compilation diagnostics and build.log location logs
        pou_file = PROJECTS_ROOT / proj_name / "pous" / "POU_SyntaxNearSemi.st"
        pou_file.parent.mkdir(parents=True, exist_ok=True)
        pou_file.write_text(code, encoding="utf-8")

        # Step C: Compilation via cscape_compile_project
        comp_res = cscape_compile_project(proj_name, clean_build=True)
        assert comp_res["status"] == "error"
        assert comp_res["compile_successful"] is False
        assert comp_res["error_count"] > 0
        assert comp_res.get("failure_location") is not None
        c_loc = comp_res["failure_location"]
        assert c_loc["file_path"] == "POU_SyntaxNearSemi.st"
        assert c_loc["line"] == 7
        assert c_loc["column"] >= 1
        assert c_loc["error_code"] == "ST_SYNTAX_ERROR"

        # Verify build_log captures exact failure location: file path, line, column, error code
        build_log = comp_res["build_log"]
        assert "POU_SyntaxNearSemi.st" in build_log
        parsed_diags = CscapeLogParser.parse_log(build_log)
        assert len(parsed_diags) > 0

        syntax_diags = [d for d in parsed_diags if d.pou_name == "POU_SyntaxNearSemi"]
        assert len(syntax_diags) > 0
        diag = syntax_diags[0]
        assert diag.file_path == "POU_SyntaxNearSemi.st"
        assert diag.line == 7
        assert diag.column >= 1
        assert diag.error_code == "ST_SYNTAX_ERROR"
        assert diag.level == "ERROR"

        # Step D: Retrieve via cscape_get_diagnostics
        get_diag_res = cscape_get_diagnostics(proj_name)
        assert get_diag_res["status"] == "error"
        assert get_diag_res["compile_successful"] is False
        assert get_diag_res.get("failure_location") is not None
        assert get_diag_res["failure_location"]["file_path"] == "POU_SyntaxNearSemi.st"
        assert get_diag_res["failure_location"]["line"] == 7
        assert get_diag_res["failure_location"]["column"] >= 1
        assert get_diag_res["failure_location"]["error_code"] == "ST_SYNTAX_ERROR"


# ==============================================================================
# 3. Strict Zero PLC Download Lockout Enforcement
# ==============================================================================

class TestStrictZeroPLCDownloadLockout:
    """Verifies strict zero PLC download policy and hardware lockout invariants."""

    def test_strict_zero_plc_download_lockout(self):
        enforce_software_isolation()

        # 1. CLI Runner download lockout
        runner = CLIRunner()
        with pytest.raises(UnauthorizedDownloadError):
            runner.download_to_controller("fake_project.csp")

        # 2. Automation Bridge download and hardware connect lockout
        bridge = CscapeAutomationBridge()
        with pytest.raises(UnauthorizedDownloadError):
            bridge.download_to_controller()

        with pytest.raises(HardwareLockoutError):
            bridge.connect_hardware(target="XL4", port="COM1")
