"""Audit and Verification Test Suite for MCP Tool cscape_compile_project.

Audits and verifies:
1. Execution flow: trigger error check (ID_PROGRAM_ERRORCHECK = 32826 / Ctrl+F7),
   scrape output ListBox (ID 372 in Frame 45011), and return structured JSON response.
2. Confirm structured error diagnostics response:
   {success: bool, errors: list, warnings: list, build_log: str}
   for both clean builds and syntax error builds.
3. Confirm fail-closed handling if compilation hangs or Cscape crashes:
   - Window handle invalid / Cscape crashed before dispatch
   - Cscape hung before dispatch (IsHungAppWindow = True)
   - Cscape crashed during compilation
   - Cscape hung during compilation pass
   - Compilation timeout
"""

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.cscape.compiler import (
    ID_CONTROLLER_DOWNLOAD,
    ID_OUTPUT_LISTBOX,
    ID_OUTPUT_WINDOW,
    ID_PROGRAM_ERRORCHECK,
    VK_F7_COMMAND,
    CscapeCompiler,
)
from src.mcp.server import server
from src.mcp.tools import (
    cscape_compile,
    cscape_compile_project,
    cscape_create_project,
)
from src.project.manager import CscapeProject
from src.security.exceptions import UnauthorizedDownloadError


@pytest.fixture
def audit_project():
    """Fixture creating a temporary clean project directory inside workspace sandbox for audit tests."""
    proj_dir = Path("C:/HornerAI/horner-cscape-mcp/artifacts/projects/AuditProj")
    if proj_dir.exists():
        shutil.rmtree(proj_dir, ignore_errors=True)
    proj = CscapeProject.create(proj_dir, name="AuditProj")
    st_code = """PROGRAM AuditMain
VAR
    Run : BOOL := TRUE;
    Counter : INT := 0;
END_VAR
IF Run THEN
    Counter := Counter + 1;
END_IF;
END_PROGRAM
"""
    proj.inject_pou("AuditMain", st_code, "PROGRAM")
    yield proj_dir
    if proj_dir.exists():
        shutil.rmtree(proj_dir, ignore_errors=True)


class TestMCPCompileExecutionFlow:
    """Requirement 1: Verify execution flow: trigger error check, scrape output ListBox, return structured JSON response."""

    def test_gui_compile_trigger_error_check_and_scrape_listbox(self):
        """Verifies dispatch of ID_PROGRAM_ERRORCHECK (32826) and scraping of ListBox 372 inside Frame 45011."""
        compiler = CscapeCompiler()
        mock_win32gui = MagicMock()
        mock_win32gui.IsWindow.return_value = True

        # When EnumChildWindows is called, simulate discovering Frame 45011 and ListBox 372
        def fake_enum_children(parent_hwnd, callback, extra):
            callback(1001, None)  # Frame 45011
            callback(1002, None)  # ListBox 372

        mock_win32gui.EnumChildWindows.side_effect = fake_enum_children

        def fake_get_ctrl_id(hwnd):
            if hwnd == 1001:
                return ID_OUTPUT_WINDOW  # 45011
            if hwnd == 1002:
                return ID_OUTPUT_LISTBOX  # 372
            return 0

        def fake_get_class_name(hwnd):
            if hwnd == 1001:
                return "Afx:ControlBar:10003"
            if hwnd == 1002:
                return "ListBox"
            return "Static"

        mock_win32gui.GetDlgCtrlID.side_effect = fake_get_ctrl_id
        mock_win32gui.GetClassName.side_effect = fake_get_class_name
        mock_win32gui.GetParent.return_value = 1001

        log_lines = [
            "Compile Started: Project AuditMain",
            "AuditMain.st(10,5): error K51001: Unknown identifier 'BadVar'",
            "AuditMain.st(14): warning: Unused variable 'TempVar'",
            "Compile Finished: 1 error(s), 1 warning(s)",
        ]

        mock_win32con = MagicMock()
        mock_win32con.WM_COMMAND = 273
        mock_win32con.LB_GETCOUNT = 395
        mock_win32con.LB_GETTEXTLEN = 394
        mock_win32con.LB_GETTEXT = 393

        def fake_send_message(hwnd, msg, wparam, lparam):
            if msg == mock_win32con.LB_GETCOUNT:
                return len(log_lines)
            if msg == mock_win32con.LB_GETTEXTLEN:
                return len(log_lines[int(wparam)])
            if msg == mock_win32con.LB_GETTEXT:
                idx = int(wparam)
                lparam.value = log_lines[idx]
                return len(log_lines[idx])
            return 0

        mock_win32gui.SendMessage.side_effect = fake_send_message

        with patch.dict("sys.modules", {"win32gui": mock_win32gui, "win32con": mock_win32con}):
            res = compiler.trigger_cscape_gui_compile(cscape_hwnd=55555)

            # Assert execution flow
            assert res["command_dispatched"] == ID_PROGRAM_ERRORCHECK
            assert res["command_dispatched"] == 32826
            mock_win32gui.PostMessage.assert_called_once_with(55555, 273, 32826, 0)

            # Assert scraping output ListBox
            assert "Compile Started: Project AuditMain" in res["output_text"]
            assert "AuditMain.st(10,5): error K51001" in res["build_log"]

            # Assert structured response
            assert res["success"] is False
            assert res["error_count"] == 1
            assert res["warning_count"] == 1
            assert len(res["errors"]) == 1
            assert "Unknown identifier 'BadVar'" in res["errors"][0]
            assert len(res["warnings"]) == 1
            assert "Unused variable 'TempVar'" in res["warnings"][0]
            assert isinstance(res["build_log"], str)

    def test_mcp_tool_cscape_compile_with_live_hwnd(self):
        """Verifies cscape_compile forwards cscape_hwnd and returns structured JSON response."""
        mock_win32gui = MagicMock()
        mock_win32gui.IsWindow.return_value = True

        log_lines = [
            "Compilation succeeded.",
            "0 error(s), 0 warning(s)",
        ]

        def fake_enum_children(parent_hwnd, callback, extra):
            callback(1001, None)
            callback(1002, None)

        mock_win32gui.EnumChildWindows.side_effect = fake_enum_children
        mock_win32gui.GetDlgCtrlID.side_effect = lambda h: 45011 if h == 1001 else (372 if h == 1002 else 0)
        mock_win32gui.GetClassName.side_effect = lambda h: "ListBox" if h == 1002 else "Afx"

        mock_win32con = MagicMock()
        mock_win32con.WM_COMMAND = 273
        mock_win32con.LB_GETCOUNT = 395
        mock_win32con.LB_GETTEXTLEN = 394
        mock_win32con.LB_GETTEXT = 393

        def fake_send_message(hwnd, msg, wparam, lparam):
            if msg == mock_win32con.LB_GETCOUNT:
                return len(log_lines)
            if msg == mock_win32con.LB_GETTEXTLEN:
                return len(log_lines[int(wparam)])
            if msg == mock_win32con.LB_GETTEXT:
                idx = int(wparam)
                lparam.value = log_lines[idx]
                return len(log_lines[idx])
            return 0

        mock_win32gui.SendMessage.side_effect = fake_send_message

        with patch.dict("sys.modules", {"win32gui": mock_win32gui, "win32con": mock_win32con}):
            res = cscape_compile(cscape_hwnd=55555)
            assert res["success"] is True
            assert res["status"] == "SUCCESS"
            assert isinstance(res["errors"], list)
            assert len(res["errors"]) == 0
            assert isinstance(res["warnings"], list)
            assert len(res["warnings"]) == 0
            assert isinstance(res["build_log"], str)
            assert "Compilation succeeded" in res["build_log"]

    def test_gui_compile_dynamically_discovers_live_hwnd_from_gate(self, tmp_path):
        """Verifies trigger_cscape_gui_compile discovers HWND from artifacts/.cscape_live_gate.json when hwnd=None."""
        compiler = CscapeCompiler(workspace_root=tmp_path)
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        gate_file = artifacts_dir / ".cscape_live_gate.json"
        gate_file.write_text(
            json.dumps({"ready_for_tests": True, "hwnd": "0x00830976", "status": "READY_FOR_TESTS"}),
            encoding="utf-8",
        )

        mock_win32gui = MagicMock()
        mock_win32gui.IsWindow.return_value = True
        mock_win32con = MagicMock(WM_COMMAND=273, LB_GETCOUNT=395, LB_GETTEXTLEN=394, LB_GETTEXT=393)
        mock_win32gui.SendMessage.return_value = 0

        with patch.dict("sys.modules", {"win32gui": mock_win32gui, "win32con": mock_win32con}):
            res = compiler.trigger_cscape_gui_compile(cscape_hwnd=None)

            assert res["command_dispatched"] == ID_PROGRAM_ERRORCHECK
            assert res["command_dispatched"] == 32826
            expected_hwnd = int("0x00830976", 0)
            mock_win32gui.PostMessage.assert_called_once_with(expected_hwnd, 273, 32826, 0)

    def test_honest_ast_metrics_eliminate_heuristic_formula(self, audit_project):
        """Verifies compiler uses honest AST metrics and estimated_ast_footprint, not synthetic mock formulas."""
        compiler = CscapeCompiler()
        build_result = compiler.compile_project(audit_project)

        assert build_result.success is True
        assert hasattr(build_result, "estimated_ast_footprint")
        ast_fp = build_result.estimated_ast_footprint

        assert "ast_statement_count" in ast_fp
        assert "ast_variable_count" in ast_fp
        assert "ast_expression_count" in ast_fp
        assert "source_bytes_total" in ast_fp
        assert ast_fp["ast_statement_count"] > 0
        assert ast_fp["ast_variable_count"] > 0
        assert ast_fp["ast_expression_count"] > 0
        assert ast_fp["source_bytes_total"] > 0

        # Verify build log contains estimated AST footprint, not old synthetic line
        assert "Estimated AST Footprint:" in build_result.raw_log
        assert "Estimated Code Size: 1024" not in build_result.raw_log


class TestStructuredDiagnosticsResponse:
    """Requirement 2: Confirm structured error diagnostics response: {success: bool, errors: list, warnings: list, build_log: str}."""

    def test_clean_project_structured_response(self, audit_project):
        """Verifies clean build returns {success: True, errors: [], warnings: [], build_log: str}."""
        res = cscape_compile(project_path=str(audit_project))

        # Primary Contract Confirmation
        assert "success" in res
        assert "errors" in res
        assert "warnings" in res
        assert "build_log" in res

        assert isinstance(res["success"], bool)
        assert res["success"] is True

        assert isinstance(res["errors"], list)
        assert len(res["errors"]) == 0

        assert isinstance(res["warnings"], list)
        assert len(res["warnings"]) == 0

        assert isinstance(res["build_log"], str)
        assert len(res["build_log"]) > 0
        assert "Build Result: SUCCESS" in res["build_log"]

    def test_syntax_error_project_structured_response(self, audit_project):
        """Verifies syntax error returns {success: False, errors: [...], warnings: list, build_log: str}."""
        broken_file = audit_project / "pous" / "Broken.st"
        broken_file.write_text("PROGRAM Broken\nVAR\n  x: INT := ;\nEND_PROGRAM", encoding="utf-8")

        res = cscape_compile(project_path=str(audit_project))

        # Primary Contract Confirmation
        assert "success" in res
        assert "errors" in res
        assert "warnings" in res
        assert "build_log" in res

        assert isinstance(res["success"], bool)
        assert res["success"] is False

        assert isinstance(res["errors"], list)
        assert len(res["errors"]) >= 1
        assert any("Syntax error" in err or "Unexpected token" in err for err in res["errors"])

        assert isinstance(res["warnings"], list)

        assert isinstance(res["build_log"], str)
        assert len(res["build_log"]) > 0
        assert "ST_SYNTAX_ERROR" in res["build_log"]
        assert "Build Result: FAILED" in res["build_log"]

    def test_cscape_compile_project_wrapper_structured_response(self, tmp_path):
        """Verifies cscape_compile_project wrapper always returns {success, errors, warnings, build_log}."""
        p_name = "WrapperAuditProj"
        p_dir = Path("C:/HornerAI/horner-cscape-mcp/artifacts/projects") / p_name
        shutil.rmtree(p_dir, ignore_errors=True)

        try:
            cscape_create_project(name=p_name, description="Audit Project")
            res = cscape_compile_project(project_name=p_name, clean_build=True)

            assert "success" in res
            assert "errors" in res
            assert "warnings" in res
            assert "build_log" in res

            assert isinstance(res["success"], bool)
            assert isinstance(res["errors"], list)
            assert isinstance(res["warnings"], list)
            assert isinstance(res["build_log"], str)

            # Also verify backward compatible keys
            assert "compile_successful" in res
            assert "status" in res
            assert "project_name" in res
            assert "pous_compiled" in res
            assert "memory_footprint" in res
        finally:
            shutil.rmtree(p_dir, ignore_errors=True)


class TestFailClosedHandling:
    """Requirement 3: Confirm fail-closed handling if compilation hangs or Cscape crashes."""

    def test_fail_closed_on_invalid_cscape_hwnd_or_crashed(self):
        """Verifies fail-closed ValueError / error response when Cscape is not running or crashed before compile."""
        compiler = CscapeCompiler()
        mock_win32gui = MagicMock()
        mock_win32gui.IsWindow.return_value = False  # Process crashed / invalid hwnd

        with patch.dict("sys.modules", {"win32gui": mock_win32gui}):
            with pytest.raises(ValueError, match="Invalid Cscape window handle"):
                compiler.trigger_cscape_gui_compile(cscape_hwnd=999999)

        # Confirm cscape_compile catches it and returns structured fail-closed response
        with patch.dict("sys.modules", {"win32gui": mock_win32gui}):
            res = cscape_compile(cscape_hwnd=999999)
            assert res["success"] is False
            assert res["status"] == "FAILED"
            assert isinstance(res["errors"], list)
            assert len(res["errors"]) > 0
            assert "Invalid Cscape window handle" in res["errors"][0]
            assert isinstance(res["warnings"], list)
            assert isinstance(res["build_log"], str)
            assert "Compilation failed" in res["build_log"]

    def test_fail_closed_on_cscape_hung_before_compile(self):
        """Verifies fail-closed detection when Cscape window message queue is hung before compile."""
        compiler = CscapeCompiler()
        mock_win32gui = MagicMock()
        mock_win32gui.IsWindow.return_value = True

        mock_user32 = MagicMock()
        mock_user32.IsHungAppWindow.return_value = True  # Cscape hung!

        with patch("ctypes.windll.user32", mock_user32, create=True), \
             patch.dict("sys.modules", {"win32gui": mock_win32gui, "win32con": MagicMock(WM_COMMAND=273)}):
            with pytest.raises(RuntimeError, match="hung and not responding"):
                compiler.trigger_cscape_gui_compile(cscape_hwnd=88888)

        # Confirm cscape_compile catches it and returns structured fail-closed response
        with patch("ctypes.windll.user32", mock_user32, create=True), \
             patch.dict("sys.modules", {"win32gui": mock_win32gui, "win32con": MagicMock(WM_COMMAND=273)}):
            res = cscape_compile(cscape_hwnd=88888)
            assert res["success"] is False
            assert res["status"] == "FAILED"
            assert len(res["errors"]) > 0
            assert "hung" in res["errors"][0].lower()
            assert isinstance(res["build_log"], str)

    def test_fail_closed_on_cscape_crashed_during_compilation(self):
        """Verifies fail-closed detection when Cscape process terminates/crashes mid-compilation."""
        compiler = CscapeCompiler()
        mock_win32gui = MagicMock()
        # Returns True on initial check, but False after PostMessage (crashed!)
        mock_win32gui.IsWindow.side_effect = [True, False]

        mock_user32 = MagicMock()
        mock_user32.IsHungAppWindow.return_value = False

        with patch("ctypes.windll.user32", mock_user32, create=True), \
             patch.dict("sys.modules", {"win32gui": mock_win32gui, "win32con": MagicMock(WM_COMMAND=273)}):
            with pytest.raises(RuntimeError, match="crashed or closed unexpectedly"):
                compiler.trigger_cscape_gui_compile(cscape_hwnd=77777)

        # Confirm cscape_compile catches crash and returns structured fail-closed response
        mock_win32gui.IsWindow.side_effect = [True, False]
        with patch("ctypes.windll.user32", mock_user32, create=True), \
             patch.dict("sys.modules", {"win32gui": mock_win32gui, "win32con": MagicMock(WM_COMMAND=273)}):
            res = cscape_compile(cscape_hwnd=77777)
            assert res["success"] is False
            assert res["status"] == "FAILED"
            assert len(res["errors"]) > 0
            assert "crashed" in res["errors"][0].lower()
            assert isinstance(res["build_log"], str)

    def test_fail_closed_on_cscape_hung_during_compilation(self):
        """Verifies fail-closed detection when Cscape hangs mid-compilation."""
        compiler = CscapeCompiler()
        mock_win32gui = MagicMock()
        mock_win32gui.IsWindow.return_value = True

        mock_user32 = MagicMock()
        # First check (before dispatch) -> False (healthy); second check (after dispatch) -> True (hung!)
        mock_user32.IsHungAppWindow.side_effect = [False, True]

        with patch("ctypes.windll.user32", mock_user32, create=True), \
             patch.dict("sys.modules", {"win32gui": mock_win32gui, "win32con": MagicMock(WM_COMMAND=273)}):
            with pytest.raises(RuntimeError, match="hung during compilation"):
                compiler.trigger_cscape_gui_compile(cscape_hwnd=66666)

    def test_fail_closed_on_controller_download_attempt(self):
        """Verifies fail-closed UnauthorizedDownloadError if command ID attempts physical download."""
        compiler = CscapeCompiler()
        with pytest.raises(UnauthorizedDownloadError, match="strictly blocked"):
            compiler.trigger_cscape_gui_compile(cscape_hwnd=12345, command_id=ID_CONTROLLER_DOWNLOAD)

        with pytest.raises(UnauthorizedDownloadError, match="strictly blocked"):
            compiler.trigger_cscape_gui_compile(cscape_hwnd=12345, command_id=32827)

    @pytest.mark.asyncio
    async def test_mcp_server_async_call_tool_structured_response(self, tmp_path):
        """Verifies calling cscape_compile_project through the live MCPServer JSON-RPC interface."""
        p_name = "AsyncAuditProj"
        p_dir = Path("C:/HornerAI/horner-cscape-mcp/artifacts/projects") / p_name
        shutil.rmtree(p_dir, ignore_errors=True)

        try:
            # Create project
            await server.call_tool("cscape_create_project", {"name": p_name})

            # Call cscape_compile_project
            call_res = await server.call_tool("cscape_compile_project", {"project_name": p_name, "clean_build": True})
            assert not call_res.is_error
            assert len(call_res.content) > 0

            data = json.loads(call_res.content[0].text)

            # Confirm structured error diagnostics response: {success: bool, errors: list, warnings: list, build_log: str}
            assert "success" in data
            assert isinstance(data["success"], bool)
            assert "errors" in data
            assert isinstance(data["errors"], list)
            assert "warnings" in data
            assert isinstance(data["warnings"], list)
            assert "build_log" in data
            assert isinstance(data["build_log"], str)
        finally:
            shutil.rmtree(p_dir, ignore_errors=True)
