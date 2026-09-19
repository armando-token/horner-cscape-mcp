"""Unit and integration test suite for Horner Cscape 10.2 Project Compilation Engine.

Verifies:
1. Fail-closed compilation when project directory does not exist.
2. Honest AST metrics computation without hardcoded synthetic footprints (no fake 1024/512/64).
3. Structured compiler diagnostics for valid ST and syntax error ST.
4. Strict hardware lockout against physical controller download commands.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from unittest.mock import patch
import pytest

from src.cscape.compilation import (
    CscapeCompiler,
    CscapeBuildResult,
    BuildStatus,
    compute_honest_ast_metrics,
    classify_compilation_modal,
    ID_PROGRAM_ERRORCHECK,
    ID_CONTROLLER_DOWNLOAD,
    ID_PROGRAM_DOWNLOADOPTIONS,
    VK_F7_COMMAND,
)
from src.security.exceptions import UnauthorizedDownloadError

SCRATCH_DIR = Path(r"C:\HornerAI\horner-cscape-mcp\scratch")


@pytest.fixture
def temp_project_dir():
    """Provides a temporary project directory inside workspace scratch, cleaned up after test."""
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    p = SCRATCH_DIR / f"test_proj_{uuid.uuid4().hex[:8]}"
    p.mkdir(parents=True, exist_ok=True)
    yield p
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)


class TestCscapeCompilationEngine:
    """Test suite hardening the Cscape compilation engine."""

    def test_compile_nonexistent_project_fails_closed(self, temp_project_dir):
        """Mandate: Compiling a nonexistent project must fail-closed with clear error diagnostics."""
        nonexistent = temp_project_dir / "NonExistentProject_12345"
        compiler = CscapeCompiler()

        res = compiler.compile_project(nonexistent)

        assert res.success is False
        assert res.status == BuildStatus.FAILED
        assert res.error_count >= 1
        assert len(res.diagnostics) >= 1
        assert any("does not exist" in d.message.lower() for d in res.diagnostics)
        assert res.memory_footprint.get("code_size_bytes", 0) == 0
        assert res.memory_footprint.get("data_size_bytes", 0) == 0
        assert res.hardware_lockout_enforced is True

    def test_compute_honest_ast_metrics_accuracy(self):
        """Mandate: compute_honest_ast_metrics must return honest statement, variable, and expression counts."""
        st_code = """PROGRAM MetricCheck
VAR
    Speed : INT := 100;
    Active : BOOL := TRUE;
    OutputVal : REAL := 0.0;
END_VAR
IF Active THEN
    Speed := Speed + 10;
    OutputVal := Speed * 1.5;
END_IF;
END_PROGRAM
"""
        metrics = compute_honest_ast_metrics(st_code)

        assert metrics["ast_variable_count"] == 3
        assert metrics["ast_statement_count"] >= 2
        assert metrics["ast_expression_count"] >= 2
        assert metrics["source_bytes_total"] == len(st_code.encode("utf-8"))

        # Verify not fake numbers
        assert metrics["source_bytes_total"] != 1024
        assert metrics["ast_variable_count"] != 512

    def test_compile_honest_ast_metrics_clean_project(self, temp_project_dir):
        """Mandate: Compile pass must populate memory footprint using honest AST metrics, not fake 1024/512/64."""
        pous_dir = temp_project_dir / "pous"
        pous_dir.mkdir(parents=True, exist_ok=True)
        st_code = """PROGRAM MainPump
VAR
    PumpRunning : BOOL := FALSE;
    FlowRate : REAL := 12.5;
    AlarmCount : INT := 0;
END_VAR
IF FlowRate < 5.0 THEN
    PumpRunning := FALSE;
    AlarmCount := AlarmCount + 1;
ELSE
    PumpRunning := TRUE;
END_IF;
END_PROGRAM
"""
        (pous_dir / "MainPump.st").write_text(st_code, encoding="utf-8")
        compiler = CscapeCompiler()

        res = compiler.compile_project(temp_project_dir, clean_build=True)

        assert res.success is True
        assert res.status in (BuildStatus.SUCCESS, BuildStatus.WARNINGS)
        assert res.error_count == 0

        # Memory footprint must be honest AST metrics
        footprint = res.memory_footprint
        expected_bytes = len(st_code.encode("utf-8"))
        assert footprint["code_size_bytes"] == expected_bytes
        assert footprint["data_size_bytes"] == 3 * 4  # 3 variables * 4 bytes
        assert footprint["ast_variable_count"] == 3
        assert footprint["ast_statement_count"] > 0
        assert footprint["source_bytes_total"] == expected_bytes

        # Guarantee NO fake numbers
        assert footprint["code_size_bytes"] != 1024
        assert footprint["data_size_bytes"] != 512

    def test_compile_syntax_error_fails_closed(self, temp_project_dir):
        """Compiler must detect and report syntax errors with line/column diagnostic locations."""
        pous_dir = temp_project_dir / "pous"
        pous_dir.mkdir(parents=True, exist_ok=True)
        broken_code = """PROGRAM Broken
VAR
    ValidVar : INT := 10;
END_VAR
BrokenAssign :== 999;
END_PROGRAM
"""
        (pous_dir / "Broken.st").write_text(broken_code, encoding="utf-8")
        compiler = CscapeCompiler()

        res = compiler.compile_project(temp_project_dir)

        assert res.success is False
        assert res.status == BuildStatus.FAILED
        assert res.error_count >= 1
        assert any(d.level == "ERROR" for d in res.diagnostics)
        assert res.hardware_lockout_enforced is True

    def test_hardware_download_strictly_blocked(self):
        """Absolute hardware lockout: physical PLC download methods must be unconditionally blocked."""
        compiler = CscapeCompiler()

        with pytest.raises(UnauthorizedDownloadError):
            compiler.download_to_controller()

        with pytest.raises(UnauthorizedDownloadError):
            compiler.download_project()

        with pytest.raises(UnauthorizedDownloadError):
            compiler.download_options()

        with pytest.raises(UnauthorizedDownloadError):
            compiler.trigger_cscape_gui_compile(command_id=ID_CONTROLLER_DOWNLOAD)

        with pytest.raises(UnauthorizedDownloadError):
            compiler.trigger_cscape_gui_compile(command_id=ID_PROGRAM_DOWNLOADOPTIONS)

    def test_cscape_compile_project_nonexistent_fails_closed(self, temp_project_dir):
        """cscape_compile_project fails closed on non-existent project directory."""
        from src.cscape.compilation import cscape_compile_project
        nonexistent = temp_project_dir / "GhostProject_9999"

        res = cscape_compile_project(nonexistent)
        assert res["success"] is False
        assert res["status"] == "failed"
        assert res["error_count"] >= 1
        assert len(res["errors"]) >= 1
        assert any("does not exist" in e.lower() for e in res["errors"])
        assert res["hardware_lockout_enforced"] is True
        assert res["memory_footprint"]["code_size_bytes"] == 0

    def test_cscape_compile_project_syntax_error_fails_closed(self, temp_project_dir):
        """cscape_compile_project detects ST syntax errors and reports diagnostics."""
        from src.cscape.compilation import cscape_compile_project
        pous_dir = temp_project_dir / "pous"
        pous_dir.mkdir(parents=True, exist_ok=True)
        broken_code = """PROGRAM SyntaxFault
VAR
    nCount : INT := 0;
END_VAR
nCount :== 999;
END_PROGRAM
"""
        (pous_dir / "SyntaxFault.st").write_text(broken_code, encoding="utf-8")

        res = cscape_compile_project(temp_project_dir)
        assert res["success"] is False
        assert res["status"] == "failed"
        assert res["error_count"] >= 1
        assert any(d.get("level") == "ERROR" for d in res["diagnostics"])
        assert res["hardware_lockout_enforced"] is True

    def test_cscape_compile_project_honest_ast_metrics_clean(self, temp_project_dir):
        """cscape_compile_project uses honest AST metrics without synthetic footprints."""
        from src.cscape.compilation import cscape_compile_project
        pous_dir = temp_project_dir / "pous"
        pous_dir.mkdir(parents=True, exist_ok=True)
        st_code = """PROGRAM HonestST
VAR
    rTemp : REAL := 25.0;
    bCooling : BOOL := FALSE;
    nCycles : DINT := 0;
END_VAR
IF rTemp > 30.0 THEN
    bCooling := TRUE;
    nCycles := nCycles + 1;
END_IF;
END_PROGRAM
"""
        (pous_dir / "HonestST.st").write_text(st_code, encoding="utf-8")

        res = cscape_compile_project(temp_project_dir, clean_build=True)
        assert res["success"] is True
        assert res["status"] in ("success", "warnings")
        assert res["error_count"] == 0

        fp = res["memory_footprint"]
        expected_bytes = len(st_code.encode("utf-8"))
        assert fp["code_size_bytes"] == expected_bytes
        assert fp["ast_variable_count"] == 3
        assert fp["ast_statement_count"] > 0
        assert fp["data_size_bytes"] == 3 * 4
        # Guarantee no synthetic formulas
        assert fp["code_size_bytes"] != 1024
        assert fp["data_size_bytes"] != 512

    def test_cscape_compile_project_require_live_gui_offline_blocked(self, temp_project_dir):
        """cscape_compile_project with require_live_gui=True when offline fails-closed."""
        from src.cscape.compilation import cscape_compile_project
        pous_dir = temp_project_dir / "pous"
        pous_dir.mkdir(parents=True, exist_ok=True)
        (pous_dir / "Dummy.st").write_text("PROGRAM Dummy\nEND_PROGRAM\n", encoding="utf-8")

        res = cscape_compile_project(temp_project_dir, require_live_gui=True)
        assert res["success"] is False
        assert res["status"] in ("blocked", "failed")
        assert "FAIL-CLOSED" in res["message"]
        assert res["hardware_lockout_enforced"] is True

    def test_mcp_cscape_compile_project_tool(self, temp_project_dir):
        """Verify cscape_compile_project in src.mcp.tools satisfies fail-closed status contract."""
        from src.mcp.tools import cscape_compile_project as mcp_compile

        # Nonexistent project fails-closed
        res_nonexistent = mcp_compile("DefNonExistent_Proj_54321")
        assert res_nonexistent["success"] is False
        assert res_nonexistent["status"] in ("failed", "error")
        assert res_nonexistent["error_count"] >= 1
        assert len(res_nonexistent["errors"]) >= 1
        assert res_nonexistent["hardware_lockout_enforced"] is True

    def test_cscape_compile_project_download_command_blocked(self, temp_project_dir):
        """cscape_compile_project with download command_id (32827, 33149) returns status 'blocked'."""
        from src.cscape.compilation import cscape_compile_project, ID_CONTROLLER_DOWNLOAD, ID_PROGRAM_DOWNLOADOPTIONS

        res1 = cscape_compile_project(temp_project_dir, command_id=ID_CONTROLLER_DOWNLOAD)
        assert res1["success"] is False
        assert res1["status"] == "blocked"
        assert res1["error_code"] == "ERR_HARDWARE_LOCKOUT"
        assert res1["hardware_lockout_enforced"] is True

        res2 = cscape_compile_project(temp_project_dir, command_id=ID_PROGRAM_DOWNLOADOPTIONS)
        assert res2["success"] is False
        assert res2["status"] == "blocked"
        assert res2["error_code"] == "ERR_HARDWARE_LOCKOUT"
        assert res2["hardware_lockout_enforced"] is True

    def test_simulation_classification_tested_mock(self):
        """Simulation modules must declare TESTED_MOCK [offline/DEV only] and never claim VERIFIED_LIVE."""
        from src.cscape import simulator, simulation

        assert simulator.CLASSIFICATION == "TESTED_MOCK [offline/DEV only]"
        assert simulator.VERIFICATION_CLASSIFICATION == "TESTED_MOCK [offline/DEV only]"
        assert simulation.CLASSIFICATION == "TESTED_MOCK [offline/DEV only]"
        assert simulation.VERIFICATION_CLASSIFICATION == "TESTED_MOCK [offline/DEV only]"

    def test_compile_empty_project_zero_source_pous_fails_closed(self, temp_project_dir):
        """Mandate: Compiling a project containing zero .st files must fail closed with NO_SOURCE_POUS."""
        compiler = CscapeCompiler()
        res = compiler.compile_project(temp_project_dir)

        assert res.success is False
        assert res.status == BuildStatus.FAILED
        assert res.error_count >= 1
        assert any(d.error_code == "NO_SOURCE_POUS" for d in res.diagnostics)
        assert any("no structured text" in d.message.lower() for d in res.diagnostics)

    def test_compile_empty_output_fails_closed(self):
        """Mandate: Empty compilation output window must fail closed with COMPILATION_OUTPUT_EMPTY."""
        compiler = CscapeCompiler()
        with patch.object(compiler, "_discover_live_cscape_hwnd", return_value=12345):
            with patch.object(compiler, "_attach_thread_to_window_desktop"):
                with patch.object(compiler, "scrape_output_window", return_value=("", [])):
                    with patch("win32gui.IsWindow", return_value=True):
                        with patch("win32gui.PostMessage", return_value=0):
                            with patch("time.sleep"):
                                res = compiler.trigger_cscape_gui_compile(cscape_hwnd=12345)

        assert res["success"] is False
        assert res["status"] == "failed"
        assert res["error_code"] == "COMPILATION_OUTPUT_EMPTY"
        assert res["error_count"] >= 1
        assert any("empty" in e.lower() for e in res["errors"])

    def test_compile_whitespace_output_fails_closed(self):
        """Mandate: Whitespace-only compilation output must fail closed with COMPILATION_OUTPUT_EMPTY."""
        compiler = CscapeCompiler()
        with patch.object(compiler, "_discover_live_cscape_hwnd", return_value=12345):
            with patch.object(compiler, "_attach_thread_to_window_desktop"):
                with patch.object(compiler, "scrape_output_window", return_value=("   \r\n\t  \n", [])):
                    with patch("win32gui.IsWindow", return_value=True):
                        with patch("win32gui.PostMessage", return_value=0):
                            with patch("time.sleep"):
                                res = compiler.trigger_cscape_gui_compile(cscape_hwnd=12345)

        assert res["success"] is False
        assert res["status"] == "failed"
        assert res["error_code"] == "COMPILATION_OUTPUT_EMPTY"
        assert res["error_count"] >= 1

    def test_compile_stale_success_token_fails_closed(self):
        """Mandate: GUI compilation returning only bare stale token must fail closed."""
        compiler = CscapeCompiler()
        stale_text = "0 error(s), 0 warning(s)"
        with patch.object(compiler, "_discover_live_cscape_hwnd", return_value=12345):
            with patch.object(compiler, "_attach_thread_to_window_desktop"):
                with patch.object(compiler, "scrape_output_window", return_value=(stale_text, [])):
                    with patch("win32gui.IsWindow", return_value=True):
                        with patch("win32gui.PostMessage", return_value=0):
                            with patch("time.sleep"):
                                res = compiler.trigger_cscape_gui_compile(cscape_hwnd=12345)

        assert res["success"] is False
        assert res["status"] == "failed"
        assert res["error_code"] == "STALE_OR_INVALID_BUILD_PROOF"
        assert res["error_count"] >= 1

    def test_compile_modal_non_fatal_auto_yes_eliminated(self):
        """Mandate: Non-fatal error dialogs must never be auto-dismissed with Yes."""
        classification = classify_compilation_modal("Cscape", ["Non-fatal errors detected in project. Continue?"])
        assert classification == "NON_FATAL_ERROR"

    def test_compile_modal_foreign_fails_closed(self):
        """Mandate: Foreign or unknown modal dialogs must fail closed without blind dismissal."""
        foreign_cases = [
            ("Save Project As", ["Save file to disk?"]),
            ("Hardware Configuration Error", ["Controller mismatch"]),
            ("Windows Security", ["Firewall alert"]),
        ]
        for title, texts in foreign_cases:
            cls = classify_compilation_modal(title, texts)
            assert cls == "FOREIGN_MODAL", f"Modal '{title}' should be classified as FOREIGN_MODAL"

    def test_classify_compilation_modal_contract(self):
        """Mandate: Modal classification strictly identifies CLEAN_RESULT, NON_FATAL_ERROR, and FOREIGN_MODAL."""
        assert classify_compilation_modal("Cscape", ["No error detected."]) == "CLEAN_RESULT"
        assert classify_compilation_modal("Compilation succeeded", ["0 error(s), 0 warning(s)"]) == "CLEAN_RESULT"
        assert classify_compilation_modal("Cscape", ["non-fatal error occurred", "Yes", "No"]) == "NON_FATAL_ERROR"
        assert classify_compilation_modal("Cscape", ["Unknown prompt", "Cancel"]) == "FOREIGN_MODAL"



