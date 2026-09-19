import sys
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.cscape.compiler import (
    CscapeCompiler,
    CscapeLogParser,
    CscapeBuildResult,
    BuildStatus,
    ID_PROGRAM_ERRORCHECK,
    ID_CONTROLLER_DOWNLOAD,
    ID_PROGRAM_DOWNLOADOPTIONS,
    ID_OUTPUT_WINDOW,
    ID_OUTPUT_LISTBOX,
    VK_F7_COMMAND,
)
from src.project.manager import CscapeProject
from src.security.exceptions import UnauthorizedDownloadError

def test_compiler_constants():
    """Verify live Cscape compilation command IDs and blocked download command ID."""
    assert ID_PROGRAM_ERRORCHECK == 32826  # Ctrl+F7 (Error Check)
    assert VK_F7_COMMAND == 1136           # Accelerator F7 command
    assert ID_CONTROLLER_DOWNLOAD == 32827 # Controller -> Download (strictly blocked)
    assert ID_PROGRAM_DOWNLOADOPTIONS == 33149
    assert ID_OUTPUT_LISTBOX == 372        # MFC ListBox control ID
    assert ID_OUTPUT_WINDOW == 45011       # Output Window frame ID


def test_trigger_live_compilation_default_errorcheck():
    """[MOCK_DISPATCH_ONLY] Verify live compilation dispatches ID_PROGRAM_ERRORCHECK (32826) by default."""
    compiler = CscapeCompiler()
    mock_win32gui = MagicMock()
    mock_win32gui.IsWindow.return_value = True
    mock_win32gui.EnumChildWindows.return_value = None

    with patch.dict("sys.modules", {"win32gui": mock_win32gui, "win32con": MagicMock(WM_COMMAND=273)}):
        res = compiler.trigger_cscape_gui_compile(cscape_hwnd=99999)
        assert res["command_dispatched"] == ID_PROGRAM_ERRORCHECK
        assert res["command_dispatched"] == 32826
        mock_win32gui.PostMessage.assert_called_once_with(99999, 273, 32826, 0)


def test_trigger_live_compilation_accelerator_vk_f7():
    """Verify live compilation dispatches accelerator VK_F7_COMMAND (1136) when use_accelerator=True."""
    compiler = CscapeCompiler()
    mock_win32gui = MagicMock()
    mock_win32gui.IsWindow.return_value = True
    mock_win32gui.EnumChildWindows.return_value = None

    with patch.dict("sys.modules", {"win32gui": mock_win32gui, "win32con": MagicMock(WM_COMMAND=273)}):
        res = compiler.trigger_cscape_gui_compile(cscape_hwnd=99999, use_accelerator=True)
        assert res["command_dispatched"] == VK_F7_COMMAND
        assert res["command_dispatched"] == 1136
        mock_win32gui.PostMessage.assert_called_once_with(99999, 273, 1136, 0)


def test_trigger_live_compilation_explicit_command_id():
    """Verify live compilation accepts explicit ID_PROGRAM_ERRORCHECK or VK_F7_COMMAND."""
    compiler = CscapeCompiler()
    mock_win32gui = MagicMock()
    mock_win32gui.IsWindow.return_value = True
    mock_win32gui.EnumChildWindows.return_value = None

    with patch.dict("sys.modules", {"win32gui": mock_win32gui, "win32con": MagicMock(WM_COMMAND=273)}):
        res1 = compiler.trigger_cscape_gui_compile(cscape_hwnd=88888, command_id=ID_PROGRAM_ERRORCHECK)
        assert res1["command_dispatched"] == 32826

        mock_win32gui.reset_mock()
        res2 = compiler.trigger_cscape_gui_compile(cscape_hwnd=88888, command_id=VK_F7_COMMAND)
        assert res2["command_dispatched"] == 1136
        mock_win32gui.PostMessage.assert_called_once_with(88888, 273, 1136, 0)


def test_physical_controller_download_strictly_blocked():
    """Verify physical controller download ID_CONTROLLER_DOWNLOAD = 32827 is strictly blocked."""
    compiler = CscapeCompiler()

    # 1. Blocked via trigger_cscape_gui_compile with ID_CONTROLLER_DOWNLOAD
    with pytest.raises(UnauthorizedDownloadError, match="strictly blocked"):
        compiler.trigger_cscape_gui_compile(cscape_hwnd=12345, command_id=ID_CONTROLLER_DOWNLOAD)

    # 2. Blocked via trigger_cscape_gui_compile with literal 32827
    with pytest.raises(UnauthorizedDownloadError, match="strictly blocked"):
        compiler.trigger_cscape_gui_compile(cscape_hwnd=12345, command_id=32827)

    # 3. Blocked via trigger_cscape_gui_compile with download options command 33149
    with pytest.raises(UnauthorizedDownloadError, match="strictly blocked"):
        compiler.trigger_cscape_gui_compile(cscape_hwnd=12345, command_id=ID_PROGRAM_DOWNLOADOPTIONS)

    # 4. Blocked via download_to_controller method
    with pytest.raises(UnauthorizedDownloadError, match="strictly blocked"):
        compiler.download_to_controller()

    # 5. Blocked via download_project method
    with pytest.raises(UnauthorizedDownloadError, match="strictly blocked"):
        compiler.download_project("TestProject")

    # 6. SafetyGuard itself strictly blocks ID_CONTROLLER_DOWNLOAD
    with pytest.raises(UnauthorizedDownloadError):
        compiler.guard.validate_ui_command(ID_CONTROLLER_DOWNLOAD)

    with pytest.raises(UnauthorizedDownloadError):
        compiler.guard.validate_ui_command(32827)


def test_log_parser_cscape_format():
    raw_log = """
MainControl.st(14,5): error K51001: Syntax error near 'END_IF'
FB_Motor.st(22): warning: Unused variable 'bAux'
Informational message
"""
    diags = CscapeLogParser.parse_log(raw_log)
    assert len(diags) == 2
    assert diags[0].level == "ERROR"
    assert diags[0].line == 14
    assert diags[0].column == 5
    assert diags[0].error_code == "K51001"
    assert "Syntax error" in diags[0].message
    assert diags[1].level == "WARNING"
    assert diags[1].line == 22

def test_compile_project_clean(tmp_path):
    project_dir = tmp_path / "TestProj"
    proj = CscapeProject.create(project_dir, name="TestProj")
    st_code = """PROGRAM TestMain
VAR
    x : BOOL := FALSE;
END_VAR
x := TRUE;
END_PROGRAM
"""
    proj.inject_pou("TestMain", st_code, "PROGRAM")
    
    compiler = CscapeCompiler(workspace_root=tmp_path)
    res = compiler.compile_project(project_dir)
    assert res.success is True
    assert res.status in (BuildStatus.SUCCESS, BuildStatus.WARNINGS)
    assert res.error_count == 0
    assert res.hardware_lockout_enforced is True
    assert "Hardware Lockout: ENFORCED (Zero PLC communication / No download)" in res.raw_log
    assert (project_dir / "artifacts" / "build.log").exists()

def test_compile_project_with_syntax_error(tmp_path):
    project_dir = tmp_path / "ErrProj"
    proj = CscapeProject.create(project_dir, name="ErrProj")
    broken_code = """PROGRAM Broken
VAR
    x : BOOL := FALSE
END_VAR
x := 
"""
    proj.inject_pou("Broken", broken_code, "PROGRAM")
    
    compiler = CscapeCompiler(workspace_root=tmp_path)
    res = compiler.compile_project(project_dir)
    assert res.success is False
    assert res.status == BuildStatus.FAILED
    assert res.error_count > 0
    assert len(res.diagnostics) > 0


def test_output_scraping_handles_mfc_listbox_372_and_frame_45011():
    """Verify output scraping detects Frame 45011 and extracts lines from ListBox 372 via EnumChildWindows."""
    compiler = CscapeCompiler()
    
    mock_win32gui = MagicMock()
    mock_win32gui.IsWindow.return_value = True
    # GetDlgItem fails initially, forcing EnumChildWindows
    mock_win32gui.GetDlgItem.side_effect = Exception("Not a direct child")

    # When EnumChildWindows is called, simulate discovering:
    # 1. Frame 45011 (hwnd=1001, cid=45011, cls="Afx:ControlBar:10003")
    # 2. ListBox 372 (hwnd=1002, cid=372, cls="ListBox")
    def fake_enum_children(parent_hwnd, callback, extra):
        callback(1001, None)
        callback(1002, None)

    mock_win32gui.EnumChildWindows.side_effect = fake_enum_children

    def fake_get_ctrl_id(hwnd):
        if hwnd == 1001:
            return ID_OUTPUT_WINDOW  # 45011
        if hwnd == 1002:
            return ID_OUTPUT_LISTBOX  # 372
        return 0

    def fake_get_class_name(hwnd):
        if hwnd == 1001:
            return "Afx:ControlBar:400000:8:10003:10"
        if hwnd == 1002:
            return "ListBox"
        return "Static"

    mock_win32gui.GetDlgCtrlID.side_effect = fake_get_ctrl_id
    mock_win32gui.GetClassName.side_effect = fake_get_class_name
    mock_win32gui.GetParent.return_value = 1001

    log_lines = [
        "MainControl.st(14,5): error K51001: Syntax error near 'END_IF'",
        "FB_Motor.st(22): warning: Unused variable 'bAux'",
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
            idx = int(wparam)
            return len(log_lines[idx])
        if msg == mock_win32con.LB_GETTEXT:
            idx = int(wparam)
            lparam.value = log_lines[idx]
            return len(log_lines[idx])
        return 0

    mock_win32gui.SendMessage.side_effect = fake_send_message

    with patch.dict("sys.modules", {"win32gui": mock_win32gui, "win32con": mock_win32con}):
        # Direct scrape test
        scraped_text = compiler.scrape_output_window(cscape_hwnd=99999)
        assert "MainControl.st(14,5): error K51001" in scraped_text
        assert "FB_Motor.st(22): warning" in scraped_text

        # Full GUI compile trigger test
        res = compiler.trigger_cscape_gui_compile(cscape_hwnd=99999)
        assert res["success"] is False
        assert res["error_count"] == 1
        assert len(res["diagnostics"]) == 2
        assert res["diagnostics"][0]["level"] == "ERROR"
        assert res["diagnostics"][0]["error_code"] == "K51001"
        assert res["diagnostics"][1]["level"] == "WARNING"


def test_output_scraping_direct_getdlgitem_frame_45011():
    """[MOCK_DISPATCH_ONLY] Verify output scraping finds ListBox 372 inside Frame 45011 directly via GetDlgItem."""
    compiler = CscapeCompiler()
    
    mock_win32gui = MagicMock()
    mock_win32gui.IsWindow.return_value = True

    # GetDlgItem(cscape_hwnd, 45011) -> 1001
    # GetDlgItem(1001, 372) -> 1002
    def fake_get_dlg_item(parent, cid):
        if parent == 99999 and cid == ID_OUTPUT_WINDOW:
            return 1001
        if parent == 1001 and cid == ID_OUTPUT_LISTBOX:
            return 1002
        return 0

    mock_win32gui.GetDlgItem.side_effect = fake_get_dlg_item
    mock_win32gui.EnumChildWindows.return_value = None

    mock_win32con = MagicMock()
    mock_win32con.WM_COMMAND = 273
    mock_win32con.LB_GETCOUNT = 395
    mock_win32con.LB_GETTEXTLEN = 394
    mock_win32con.LB_GETTEXT = 393

    clean_lines = [
        "Compilation succeeded.",
        "0 error(s), 0 warning(s)",
    ]

    def fake_send_message(hwnd, msg, wparam, lparam):
        if msg == mock_win32con.LB_GETCOUNT:
            return len(clean_lines)
        if msg == mock_win32con.LB_GETTEXTLEN:
            idx = int(wparam)
            return len(clean_lines[idx])
        if msg == mock_win32con.LB_GETTEXT:
            idx = int(wparam)
            lparam.value = clean_lines[idx]
            return len(clean_lines[idx])
        return 0

    mock_win32gui.SendMessage.side_effect = fake_send_message

    with patch.dict("sys.modules", {"win32gui": mock_win32gui, "win32con": mock_win32con}):
        res = compiler.trigger_cscape_gui_compile(cscape_hwnd=99999)
        assert res["success"] is True
        assert res["error_count"] == 0
        assert "Compilation succeeded" in res["output_text"]


def test_compiler_parse_build_output():
    """Verify CscapeCompiler.parse_build_output parses log text correctly."""
    raw = "POU1.st(5,1): error K50001: Unknown variable\nPOU1.st(8): warning: Unused"
    diags = CscapeCompiler.parse_build_output(raw)
    assert len(diags) == 2
    assert diags[0].level == "ERROR"
    assert diags[0].error_code == "K50001"
    assert diags[1].level == "WARNING"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main(["-v", __file__]))

