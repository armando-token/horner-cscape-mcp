"""Comprehensive Compiler Pipeline Tests for Horner Cscape MCP.

Verifies:
1. Compiler command constants:
   - ID_PROGRAM_ERRORCHECK = 32826
   - ID_PROGRAM_DOWNLOAD = 32827
   - ID_CONTROLLER_DOWNLOAD = 32827 (and 33149 alias)
   - ID_PROGRAM_DOWNLOADOPTIONS = 33149
2. Unconditional fail-closed download lockout for both 32827 and 33149.
3. AstDiagnostics extracts structured syntax and semantic errors on compilation failure.
4. CscapeCompiler and MCP tools (cscape_compile, cscape_compile_project, cscape_get_diagnostics).
"""

from pathlib import Path
import shutil
import pytest

from src.cscape.compiler import (
    CscapeCompiler,
    CscapeBuildResult,
    BuildStatus,
    CompilerDiagnostic,
    AstDiagnostics,
    CscapeLogParser,
    compute_honest_ast_metrics,
    ID_PROGRAM_ERRORCHECK,
    ID_PROGRAM_DOWNLOAD,
    ID_PROGRAM_DOWNLOADOPTIONS,
    ID_CONTROLLER_DOWNLOAD,
    ID_CONTROLLER_DOWNLOAD_ALT,
)
from src.security.exceptions import UnauthorizedDownloadError
from src.mcp.tools import (
    cscape_compile,
    cscape_compile_project,
    cscape_get_diagnostics,
    WORKSPACE_ROOT,
)

# Re-export all test classes from test_cscape_compiler to ensure 100% test coverage
from tests.test_cscape_compiler import (
    TestHonestASTMetrics,
    TestHardwareDownloadLockout,
    TestCompilerPipelineIntegrity,
    TestC3CompilerOfflineNegativeContracts,
)


class TestCompilerPipelineContract:
    """Explicit verification of MEGAPLAN Gate G1 Compiler Pipeline Mandates."""

    def test_command_ids_exact_values(self):
        """Confirms all compilation and download command IDs match Cscape 10.2 specifications."""
        assert ID_PROGRAM_ERRORCHECK == 32826, "ID_PROGRAM_ERRORCHECK must be 32826 (Ctrl+F7)"
        assert ID_PROGRAM_DOWNLOAD == 32827, "ID_PROGRAM_DOWNLOAD must be 32827"
        assert ID_CONTROLLER_DOWNLOAD in (32827, 33149), "ID_CONTROLLER_DOWNLOAD must be in (32827, 33149)"
        assert ID_PROGRAM_DOWNLOADOPTIONS == 33149, "ID_PROGRAM_DOWNLOADOPTIONS must be 33149"
        assert ID_CONTROLLER_DOWNLOAD_ALT == 33149, "ID_CONTROLLER_DOWNLOAD_ALT must be 33149"

    def test_download_lockout_all_variants_raise_unauthorized(self):
        """Confirms every download command ID variant is blocked unconditionally fail-closed."""
        compiler = CscapeCompiler()
        for cmd_id in (
            ID_PROGRAM_DOWNLOAD,
            ID_CONTROLLER_DOWNLOAD,
            ID_PROGRAM_DOWNLOADOPTIONS,
            ID_CONTROLLER_DOWNLOAD_ALT,
            32827,
            33149,
        ):
            with pytest.raises(UnauthorizedDownloadError, match="strictly blocked"):
                compiler.trigger_cscape_gui_compile(cscape_hwnd=None, command_id=cmd_id)

    def test_ast_diagnostics_extracts_syntax_error(self):
        """Confirms AstDiagnostics isolates line, column, and message from invalid ST code."""
        broken_code = """PROGRAM BrokenSyntax
VAR
    nCount : INT := 0;
END_VAR
nCount := ;
END_PROGRAM
"""
        diags = AstDiagnostics.extract_diagnostics(broken_code, default_pou="BrokenSyntax")
        assert len(diags) >= 1
        err = next(d for d in diags if d.level == "ERROR")
        assert err.line in (4, 5, 6)
        assert err.error_code in ("ST_SYNTAX_ERROR", "ERR_SYNTAX") or "error" in err.message.lower() or "syntax" in err.message.lower()

    def test_ast_diagnostics_extracts_semantic_ladder_error(self):
        """Confirms AstDiagnostics detects forbidden ladder logic constructs."""
        ladder_code = """PROGRAM ForbiddenLadder
VAR
    bIn : BOOL;
    bOut : BOOL;
END_VAR
---[ ]--- bIn ---[ ]--- bOut;
END_PROGRAM
"""
        diags = AstDiagnostics.extract_diagnostics(ladder_code, default_pou="ForbiddenLadder")
        assert len(diags) >= 1
        err = next(d for d in diags if d.level == "ERROR")
        assert "ERR_LADDER_FORBIDDEN" in err.error_code or "ladder" in err.message.lower()

    def test_ast_diagnostics_parses_cscape_log_output(self):
        """Confirms AstDiagnostics parses raw Cscape build logs."""
        raw_log = """=== Compilation Started ===
Line 14, Col 5: error K51001: Unknown identifier 'MotorSpeed'
Main.st(22, 10): warning: Variable 'UnusedVar' declared but never used
Build Result: FAILED (1 error, 1 warning)
"""
        diags = AstDiagnostics.extract_diagnostics(raw_log)
        assert len(diags) == 2

        err = next(d for d in diags if d.level == "ERROR")
        assert err.line == 14
        assert err.column == 5
        assert "MotorSpeed" in err.message

        warn = next(d for d in diags if d.level == "WARNING")
        assert warn.line == 22
        assert warn.column == 10
        assert "UnusedVar" in warn.message

    def test_mcp_tools_cscape_compile_on_valid_project(self):
        """Confirms cscape_compile MCP tool handles clean build with honest AST metrics."""
        proj = WORKSPACE_ROOT / "artifacts" / "projects" / "_test_mcp_clean_proj"
        pous = proj / "pous"
        if proj.exists():
            shutil.rmtree(proj, ignore_errors=True)
        try:
            pous.mkdir(parents=True)
            (pous / "Main.st").write_text(
                """PROGRAM Main
VAR
    x : INT := 10;
END_VAR
x := x + 1;
END_PROGRAM
""",
                encoding="utf-8",
            )

            res = cscape_compile(project_path=str(proj), clean_build=True)
            assert res["status"] in ("success", "SUCCESS")
            assert res["error_count"] == 0
            assert res["hardware_lockout_enforced"] is True
            assert res["memory_footprint"]["ast_statement_count"] >= 1
        finally:
            if proj.exists():
                shutil.rmtree(proj, ignore_errors=True)

    def test_mcp_tools_cscape_compile_on_error_project(self):
        """Confirms cscape_compile MCP tool returns structured error diagnostics on syntax failure."""
        proj = WORKSPACE_ROOT / "artifacts" / "projects" / "_test_mcp_error_proj"
        pous = proj / "pous"
        if proj.exists():
            shutil.rmtree(proj, ignore_errors=True)
        try:
            pous.mkdir(parents=True)
            (pous / "Main.st").write_text(
                """PROGRAM Main
VAR
    x : INT := 10;
END_VAR
x := ;
END_PROGRAM
""",
                encoding="utf-8",
            )

            res = cscape_compile(project_path=str(proj), clean_build=True)
            assert res["status"] in ("failed", "FAILED", "error")
            assert res["error_count"] >= 1
            assert len(res["diagnostics"]) >= 1
        finally:
            if proj.exists():
                shutil.rmtree(proj, ignore_errors=True)

    def test_mcp_tools_cscape_compile_project(self):
        """Confirms cscape_compile_project tool returns standard diagnostics schema."""
        proj = WORKSPACE_ROOT / "artifacts" / "projects" / "_test_compile_proj"
        pous = proj / "pous"
        if proj.exists():
            shutil.rmtree(proj, ignore_errors=True)
        try:
            pous.mkdir(parents=True)
            (pous / "Main.st").write_text(
                """PROGRAM Main
VAR
    val : REAL := 0.0;
END_VAR
val := 3.14;
END_PROGRAM
""",
                encoding="utf-8",
            )

            res = cscape_compile_project(project_name=str(proj), clean_build=True)
            assert res["status"] in ("success", "SUCCESS")
            assert res["compile_successful"] is True
            assert "pous_compiled" in res
            assert "failure_locations" in res
        finally:
            if proj.exists():
                shutil.rmtree(proj, ignore_errors=True)

    def test_mcp_tools_cscape_get_diagnostics_missing_project(self):
        """Confirms cscape_get_diagnostics handles non-existent project fail-closed."""
        missing = WORKSPACE_ROOT / "artifacts" / "projects" / "_non_existent_proj"
        res = cscape_get_diagnostics(project_name=str(missing))
        assert res["status"] in ("failed", "error", "FAILED")
        assert res["compile_successful"] is False
        assert res["error_count"] >= 1
