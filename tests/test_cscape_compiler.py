"""Tests for Cscape Compiler Pipeline and Mock Elimination.

Verifies:
1. Honest AST-derived memory metrics and elimination of arbitrary mock formulas (code_size = max(...)).
2. Unconditional fail-closed download lockout for ID_CONTROLLER_DOWNLOAD (32827) and ID_PROGRAM_DOWNLOADOPTIONS (33149).
3. Compiler pipeline execution: clean builds, syntax errors, and structured diagnostics.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.cscape.compilation import (
    BuildStatus,
    CscapeBuildResult,
    CscapeCompiler,
    classify_compilation_modal,
    ID_CONTROLLER_DOWNLOAD,
    ID_PROGRAM_DOWNLOADOPTIONS,
    ID_PROGRAM_ERRORCHECK,
    VK_F7_COMMAND,
    compute_honest_ast_metrics,
)
from src.security.exceptions import UnauthorizedDownloadError


# ============================================================================
# 1. Honest AST Memory Metrics & Mock Formula Elimination Tests
# ============================================================================

class TestHonestASTMetrics:
    """Verifies honest AST-derived metrics replace arbitrary heuristic mock formulas."""

    def test_compute_honest_ast_metrics_structured_program(self):
        """Verifies accurate node counting for statements, variables, and expressions."""
        code = """PROGRAM MainControl
VAR
    bStart : BOOL := FALSE;
    bStop : BOOL := FALSE;
    nCount : INT := 0;
    rSpeed : REAL := 0.0;
END_VAR

IF bStart AND NOT bStop THEN
    nCount := nCount + 1;
    rSpeed := 1500.0;
ELSIF bStop THEN
    nCount := 0;
    rSpeed := 0.0;
END_IF;
END_PROGRAM
"""
        metrics = compute_honest_ast_metrics(code)

        assert isinstance(metrics, dict)
        assert "ast_statement_count" in metrics
        assert "ast_variable_count" in metrics
        assert "ast_expression_count" in metrics
        assert "source_bytes_total" in metrics

        # 4 declared variables in VAR block
        assert metrics["ast_variable_count"] == 4
        # At least 1 IF statement + assignment statements
        assert metrics["ast_statement_count"] >= 3
        # Multiple expressions (AND, NOT, binary add, literals)
        assert metrics["ast_expression_count"] >= 4
        # Byte length equals UTF-8 encoded length
        assert metrics["source_bytes_total"] == len(code.encode("utf-8"))

    def test_compute_honest_ast_metrics_loops_and_case(self):
        """Verifies AST metrics calculation for loops and CASE statements."""
        code = """PROGRAM LoopAndCase
VAR
    i : INT := 0;
    nMode : INT := 1;
    nTotal : DINT := 0;
END_VAR

FOR i := 1 TO 10 BY 1 DO
    nTotal := nTotal + i;
END_FOR;

CASE nMode OF
    1: nTotal := nTotal + 10;
    2: nTotal := nTotal + 20;
    ELSE nTotal := 0;
END_CASE;
END_PROGRAM
"""
        metrics = compute_honest_ast_metrics(code)
        assert metrics["ast_variable_count"] == 3
        assert metrics["ast_statement_count"] >= 4
        assert metrics["ast_expression_count"] >= 4
        assert metrics["source_bytes_total"] == len(code.encode("utf-8"))

    def test_compute_honest_ast_metrics_fallback_on_syntax_error(self):
        """Verifies fallback metric estimation does not use fake mock formulas when code has syntax errors."""
        broken_code = """PROGRAM Broken
VAR
    a : INT := 1;
    b : INT := 2;
END_VAR
a := ;
IF THEN
"""
        metrics = compute_honest_ast_metrics(broken_code)
        assert "ast_statement_count" in metrics
        assert "ast_variable_count" in metrics
        assert "ast_expression_count" in metrics
        assert "source_bytes_total" in metrics
        assert metrics["ast_variable_count"] == 2
        assert metrics["source_bytes_total"] == len(broken_code.encode("utf-8"))

    def test_compile_project_embeds_honest_ast_footprint(self, tmp_path: Path):
        """Verifies compile_project uses estimated_ast_footprint and does not use heuristic mock size."""
        proj_dir = tmp_path / "AuditProj"
        pous_dir = proj_dir / "pous"
        pous_dir.mkdir(parents=True)

        st_file = pous_dir / "Logic.st"
        st_file.write_text(
            """PROGRAM Logic
VAR
    RunCmd : BOOL := TRUE;
    StepVal : INT := 10;
END_VAR
IF RunCmd THEN
    StepVal := StepVal + 1;
END_IF;
END_PROGRAM
""",
            encoding="utf-8",
        )

        compiler = CscapeCompiler(workspace_root=tmp_path)
        result = compiler.compile_project(proj_dir)

        assert result.success is True
        assert result.status == BuildStatus.SUCCESS

        # Verify estimated_ast_footprint is populated honestly
        ast_fp = result.estimated_ast_footprint
        assert ast_fp["ast_variable_count"] == 2
        assert ast_fp["ast_statement_count"] >= 2
        assert ast_fp["source_bytes_total"] == len(st_file.read_text(encoding="utf-8").encode("utf-8"))
        assert ast_fp["pou_count"] == 1

        # Verify memory_footprint embeds honest AST metrics
        mf = result.memory_footprint
        assert mf["ast_variable_count"] == 2
        assert mf["code_size_bytes"] == ast_fp["source_bytes_total"]
        assert mf["data_size_bytes"] == 2 * 4  # 4 bytes per variable
        assert mf["total_size_bytes"] == mf["code_size_bytes"] + mf["data_size_bytes"]

        # Verify raw build log explicitly displays Estimated AST Footprint and no fake mock sizing
        assert "Estimated AST Footprint:" in result.raw_log
        assert "Estimated Code Size: 1024" not in result.raw_log
        assert "Hardware Lockout: ENFORCED" in result.raw_log


# ============================================================================
# 2. Absolute Hardware Lockout Policy Tests (Zero Download Mandate)
# ============================================================================

class TestHardwareDownloadLockout:
    """Verifies that download command IDs unconditionally raise UnauthorizedDownloadError."""

    def test_id_controller_download_constant(self):
        """Confirms ID_CONTROLLER_DOWNLOAD is 32827."""
        assert ID_CONTROLLER_DOWNLOAD == 32827

    def test_id_program_downloadoptions_constant(self):
        """Confirms ID_PROGRAM_DOWNLOADOPTIONS is 33149."""
        assert ID_PROGRAM_DOWNLOADOPTIONS == 33149

    def test_trigger_gui_compile_blocks_controller_download_by_constant(self):
        """Confirms ID_CONTROLLER_DOWNLOAD raises UnauthorizedDownloadError unconditionally."""
        compiler = CscapeCompiler()
        with pytest.raises(UnauthorizedDownloadError, match="strictly blocked"):
            compiler.trigger_cscape_gui_compile(cscape_hwnd=12345, command_id=ID_CONTROLLER_DOWNLOAD)

    def test_trigger_gui_compile_blocks_controller_download_by_integer_32827(self):
        """Confirms command_id=32827 raises UnauthorizedDownloadError unconditionally."""
        compiler = CscapeCompiler()
        with pytest.raises(UnauthorizedDownloadError, match="strictly blocked"):
            compiler.trigger_cscape_gui_compile(cscape_hwnd=12345, command_id=32827)

    def test_trigger_gui_compile_blocks_download_options_by_constant(self):
        """Confirms ID_PROGRAM_DOWNLOADOPTIONS raises UnauthorizedDownloadError unconditionally."""
        compiler = CscapeCompiler()
        with pytest.raises(UnauthorizedDownloadError, match="strictly blocked"):
            compiler.trigger_cscape_gui_compile(cscape_hwnd=12345, command_id=ID_PROGRAM_DOWNLOADOPTIONS)

    def test_trigger_gui_compile_blocks_download_options_by_integer_33149(self):
        """Confirms command_id=33149 raises UnauthorizedDownloadError unconditionally."""
        compiler = CscapeCompiler()
        with pytest.raises(UnauthorizedDownloadError, match="strictly blocked"):
            compiler.trigger_cscape_gui_compile(cscape_hwnd=12345, command_id=33149)

    def test_download_lockout_unconditional_even_without_hwnd(self):
        """Confirms download lockout triggers immediately without attempting HWND discovery."""
        compiler = CscapeCompiler()
        # Even with cscape_hwnd=None and no live Cscape running, UnauthorizedDownloadError MUST be raised
        with pytest.raises(UnauthorizedDownloadError, match="strictly blocked"):
            compiler.trigger_cscape_gui_compile(cscape_hwnd=None, command_id=32827)

        with pytest.raises(UnauthorizedDownloadError, match="strictly blocked"):
            compiler.trigger_cscape_gui_compile(cscape_hwnd=None, command_id=33149)

    def test_download_to_controller_method_unconditionally_blocked(self):
        """Confirms download_to_controller method unconditionally raises UnauthorizedDownloadError."""
        compiler = CscapeCompiler()
        with pytest.raises(UnauthorizedDownloadError, match="Hardware lockout"):
            compiler.download_to_controller()

    def test_download_project_method_unconditionally_blocked(self):
        """Confirms download_project method unconditionally raises UnauthorizedDownloadError."""
        compiler = CscapeCompiler()
        with pytest.raises(UnauthorizedDownloadError, match="Hardware lockout"):
            compiler.download_project()

    def test_download_options_method_unconditionally_blocked(self):
        """Confirms download_options method unconditionally raises UnauthorizedDownloadError."""
        compiler = CscapeCompiler()
        with pytest.raises(UnauthorizedDownloadError, match="Hardware lockout"):
            compiler.download_options()


# ============================================================================
# 3. Compiler Pipeline Integrity Tests
# ============================================================================

class TestCompilerPipelineIntegrity:
    """Verifies compilation workflow, error diagnostic generation, and result objects."""

    def test_clean_build_workflow(self, tmp_path: Path):
        """Verifies clean compilation pass generates SUCCESS status and 0 errors."""
        proj_dir = tmp_path / "CleanProj"
        pous_dir = proj_dir / "pous"
        pous_dir.mkdir(parents=True)

        (pous_dir / "PRG_Main.st").write_text(
            """PROGRAM PRG_Main
VAR
    PumpOn : BOOL := FALSE;
    Flow : REAL := 0.0;
END_VAR
PumpOn := TRUE;
Flow := 10.5;
END_PROGRAM
""",
            encoding="utf-8",
        )

        compiler = CscapeCompiler(workspace_root=tmp_path)
        res = compiler.compile_project(proj_dir, clean_build=True)

        assert res.success is True
        assert res.status == BuildStatus.SUCCESS
        assert res.error_count == 0
        assert res.warning_count == 0
        assert len(res.diagnostics) == 0
        assert res.hardware_lockout_enforced is True
        assert (proj_dir / "artifacts" / "build.log").exists()

    def test_syntax_error_workflow(self, tmp_path: Path):
        """Verifies compilation with syntax error generates FAILED status and structured diagnostic."""
        proj_dir = tmp_path / "ErrorProj"
        pous_dir = proj_dir / "pous"
        pous_dir.mkdir(parents=True)

        # Missing expression in assignment on line 6
        (pous_dir / "PRG_Broken.st").write_text(
            """PROGRAM PRG_Broken
VAR
    x : INT := 0;
END_VAR
x := ;
END_PROGRAM
""",
            encoding="utf-8",
        )

        compiler = CscapeCompiler(workspace_root=tmp_path)
        res = compiler.compile_project(proj_dir, clean_build=True)

        assert res.success is False
        assert res.status == BuildStatus.FAILED
        assert res.error_count >= 1
        assert len(res.diagnostics) >= 1

        first_err = res.diagnostics[0]
        assert first_err.level == "ERROR"
        assert first_err.pou_name == "PRG_Broken"
        assert first_err.line == 5 or first_err.line == 6

    def test_result_to_dict_serialization(self):
        """Verifies CscapeBuildResult serialization contains all required keys."""
        res = CscapeBuildResult(
            success=True,
            status=BuildStatus.SUCCESS,
            project_name="Demo",
            project_path=r"C:\Demo",
            build_time_seconds=0.05,
            error_count=0,
            warning_count=0,
            raw_log="Build Result: SUCCESS",
            memory_footprint={"code_size_bytes": 500},
            estimated_ast_footprint={"ast_statement_count": 10},
            hardware_lockout_enforced=True,
        )
        d = res.to_dict()
        assert d["success"] is True
        assert d["status"] == "SUCCESS"
        assert d["project_name"] == "Demo"
        assert d["hardware_lockout_enforced"] is True
        assert "estimated_ast_footprint" in d
        assert "memory_footprint" in d


# ============================================================================
# 4. Phase C3 Offline/DEV Negative & Modal Contract Tests
# ============================================================================

class TestC3CompilerOfflineNegativeContracts:
    """Explicit verification of Phase C3 offline/DEV compiler negative contracts."""

    def test_c3_compile_empty_project_zero_source_pous_fails_closed(self, tmp_path: Path):
        """Mandate: Compiling a project directory with zero source POUs fails closed with NO_SOURCE_POUS."""
        proj_dir = tmp_path / "EmptyProj"
        proj_dir.mkdir(parents=True)
        (proj_dir / "pous").mkdir(parents=True)

        compiler = CscapeCompiler(workspace_root=tmp_path)
        res = compiler.compile_project(proj_dir)

        assert res.success is False
        assert res.status == BuildStatus.FAILED
        assert res.error_count >= 1
        assert any(d.error_code == "NO_SOURCE_POUS" for d in res.diagnostics)
        assert "No Structured Text (*.st) source files found in project." in res.raw_log

    def test_c3_compile_empty_output_fails_closed(self):
        """Mandate: Empty or whitespace compiler output is rejected fail-closed."""
        from src.cscape.diagnostics import verify_clean_build

        empty_proof = verify_clean_build("")
        assert empty_proof.is_clean is False
        assert empty_proof.status_text == "FAILED"

        whitespace_proof = verify_clean_build("   \n\t  \r\n  ")
        assert whitespace_proof.is_clean is False
        assert whitespace_proof.status_text == "FAILED"

    def test_c3_compile_stale_build_proof_fails_closed(self):
        """Mandate: Stale success token without genuine build summary is rejected fail-closed."""
        from src.cscape.diagnostics import CscapeLogParser, verify_clean_build

        # 1. Bare zero-error tokens lacking compilation activity fail closed
        for token in ["0 error(s), 0 warning(s)", "Errors: 0, Warnings: 0", "No errors detected"]:
            proof = CscapeLogParser.extract_clean_build_proof(token)
            assert proof.is_clean is False
            assert proof.status_text == "FAILED"

        # 2. Bare success status line without 0-error count summary fails closed
        bare_proof = verify_clean_build("Build Result: SUCCESS")
        assert bare_proof.is_clean is False
        assert bare_proof.status_text == "FAILED"


    def test_c3_modal_classification_contracts(self):
        """Mandate: Modal classification strictly distinguishes non-fatal error dialogs from foreign modals."""
        non_fatal = classify_compilation_modal(
            title="Cscape",
            child_texts=["Non-Fatal Compilation Errors encountered. Do you wish to continue?"],
        )
        assert non_fatal == "NON_FATAL_ERROR"

        clean = classify_compilation_modal(
            title="Cscape",
            child_texts=["Compilation succeeded -- 0 error(s), 0 warning(s)"],
        )
        assert clean == "CLEAN_RESULT"

        foreign = classify_compilation_modal(
            title="Unknown External Tool",
            child_texts=["An unexpected third-party error has occurred."],
        )
        assert foreign == "FOREIGN_MODAL"


