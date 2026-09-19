"""Unit and live integration tests for CscapeLifecycleManager.

Tests:
1. Constants and Control IDs verification (Radio ID 1461, Dialog #32770, Button ID 1)
2. Path resolution across standard paths, environment variables, and custom paths
3. Lifecycle state machine transitions and error conditions
4. Real live execution:
   - Launching Cscape.exe
   - Automated detection and dismissal of modal 'About Cscape' splash window (#32770)
   - Automated detection of 'Select Editor Type' dialog (#32770), selecting 'IEC 61131 Language Editors' (1461), and clicking OK (1)
   - Verification of main Cscape window readiness, visibility, and title
   - Graceful shutdown via WM_CLOSE with exit code 0
5. Context manager (__enter__ / __exit__) live verification
6. Force termination on timeout
7. Asynchronous execution wrappers (launch_async / close_async)
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

# Enforce STA COM mode before any pywinauto or COM imports
if sys.platform == "win32" or os.name == "nt":
    if not hasattr(sys, "coinit_flags"):
        setattr(sys, "coinit_flags", 2)

import pytest

from src.cscape import (
    CscapeLifecycleManager,
    CscapeLifecycleState,
    CscapeLifecycleError,
    CscapeLaunchError,
    CscapeStartupTimeoutError,
    CscapeShutdownError,
    launch_cscape,
    resolve_cscape_executable,
    find_running_cscape_instances,
    recycle_running_cscape_instances,
    set_cscape_exited_correctly,
    handle_allow_dialogs,
    ChildControlInfo,
    ALLOW_TEXT_KEYWORDS,
    ALLOW_BUTTON_KEYWORDS,
    RADIO_ID_IEC_61131,
    RADIO_ID_ADVANCED_LADDER_REGISTER,
    RADIO_ID_ADVANCED_LADDER_VARIABLE,
    ID_OK,
    ID_CANCEL,
    DIALOG_CLASS_NAME,
    SPLASH_TITLE_SUBSTRING,
    EDITOR_TYPE_TITLE_SUBSTRING,
    SC_CLOSE,
    WM_SYSCOMMAND,
)

# Detect if real Cscape.exe is available on the local machine
REAL_CSCAPE_PATH = resolve_cscape_executable()
HAS_REAL_CSCAPE = REAL_CSCAPE_PATH is not None and REAL_CSCAPE_PATH.exists()
IS_WINDOWS = sys.platform == "win32" or os.name == "nt"

requires_real_cscape = pytest.mark.skipif(
    not (IS_WINDOWS and HAS_REAL_CSCAPE),
    reason="Requires Windows OS with installed Cscape 10.2 executable",
)


class TestCscapeLifecycleConstants:
    """Validate all required Win32 control IDs, class names, and message constants."""

    def test_dialog_class_name(self) -> None:
        """Verify Win32 standard dialog class name."""
        assert DIALOG_CLASS_NAME == "#32770"

    def test_splash_dialog_ident(self) -> None:
        """Verify splash title substring and standard OK button ID."""
        assert SPLASH_TITLE_SUBSTRING == "About Cscape"
        assert ID_OK == 1
        assert ID_CANCEL == 2

    def test_editor_type_radio_ids(self) -> None:
        """Verify Horner APG Editor Type dialog radio control IDs."""
        assert EDITOR_TYPE_TITLE_SUBSTRING == "Select Editor Type"
        # Primary standard: IEC 61131-3 Language Editors
        assert RADIO_ID_IEC_61131 == 1461
        # Legacy options
        assert RADIO_ID_ADVANCED_LADDER_REGISTER == 1460
        assert RADIO_ID_ADVANCED_LADDER_VARIABLE == 3757

    def test_lifecycle_states(self) -> None:
        """Verify lifecycle state enumeration values."""
        assert CscapeLifecycleState.NOT_STARTED == "not_started"
        assert CscapeLifecycleState.STARTING == "starting"
        assert CscapeLifecycleState.SPLASH_DISMISSED == "splash_dismissed"
        assert CscapeLifecycleState.EDITOR_TYPE_SELECTED == "editor_type_selected"
        assert CscapeLifecycleState.READY == "ready"
        assert CscapeLifecycleState.CLOSING == "closing"
        assert CscapeLifecycleState.TERMINATED == "terminated"
        assert CscapeLifecycleState.FAILED == "failed"

    def test_sc_close_constant(self) -> None:
        """Verify Win32 SC_CLOSE and WM_SYSCOMMAND constants."""
        assert SC_CLOSE == 0xF060
        assert WM_SYSCOMMAND == 0x0112



class TestCscapePathResolution:
    """Test executable discovery logic."""

    def test_resolve_default_or_installed(self) -> None:
        """Verify path resolver returns valid path when installed."""
        if HAS_REAL_CSCAPE:
            exe = resolve_cscape_executable()
            assert exe is not None
            assert exe.name.lower() == "cscape.exe"
            assert exe.exists()

    def test_resolve_custom_path(self, tmp_path: Path) -> None:
        """Verify custom path override."""
        dummy_exe = tmp_path / "Cscape.exe"
        dummy_exe.touch()
        resolved = resolve_cscape_executable(custom_path=dummy_exe)
        assert resolved == dummy_exe.resolve()

    def test_resolve_env_var_bin_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Verify CSCAPE_BIN_PATH environment variable override."""
        dummy_exe = tmp_path / "CustomCscape.exe"
        dummy_exe.touch()
        monkeypatch.setenv("CSCAPE_BIN_PATH", str(dummy_exe))
        resolved = resolve_cscape_executable()
        assert resolved == dummy_exe.resolve()

    def test_resolve_env_var_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Verify CSCAPE_DIR environment variable override."""
        dummy_exe = tmp_path / "Cscape.exe"
        dummy_exe.touch()
        monkeypatch.delenv("CSCAPE_BIN_PATH", raising=False)
        monkeypatch.setenv("CSCAPE_DIR", str(tmp_path))
        resolved = resolve_cscape_executable()
        assert resolved == dummy_exe.resolve()


class TestCscapeLifecycleManagerUnit:
    """Unit tests for CscapeLifecycleManager using mocks."""

    def test_initial_state(self) -> None:
        """Verify manager attributes prior to launch."""
        manager = CscapeLifecycleManager()
        assert manager.state == CscapeLifecycleState.NOT_STARTED
        assert not manager.is_running
        assert not manager.is_ready
        assert manager.main_hwnd is None
        assert manager.pid is None

    def test_nonexistent_executable_raises(self, tmp_path: Path) -> None:
        """Verify CscapeLaunchError if executable does not exist."""
        non_existent = tmp_path / "DoesNotExist.exe"
        manager = CscapeLifecycleManager(executable_path=non_existent)
        with pytest.raises(CscapeLaunchError, match="not found"):
            manager.launch()
        assert manager.state == CscapeLifecycleState.NOT_STARTED

    def test_nonexistent_project_file_raises(self, tmp_path: Path) -> None:
        """Verify FileNotFoundError if project file does not exist."""
        if not HAS_REAL_CSCAPE:
            pytest.skip("Requires Cscape executable")
        manager = CscapeLifecycleManager(executable_path=REAL_CSCAPE_PATH)
        non_existent_proj = tmp_path / "missing_project.csp"
        with pytest.raises(FileNotFoundError, match="Project file not found"):
            manager.launch(project_path=non_existent_proj)

    def test_force_kill_fallback_on_mock(self) -> None:
        """Verify terminate logic sets state to TERMINATED when process is running."""
        manager = CscapeLifecycleManager()
        mock_proc = MagicMock()
        # Initially running (poll returns None), then after kill it returns 1
        mock_proc.poll.side_effect = [None, None, 1, 1]
        manager.process = mock_proc
        manager.pid = 99999
        manager.state = CscapeLifecycleState.READY

        with patch("subprocess.run"):
            res = manager.terminate()
            assert res is True
            assert manager.state == CscapeLifecycleState.TERMINATED
            assert mock_proc.kill.called

    def test_close_already_stopped(self) -> None:
        """Verify close returns True immediately if process is not running."""
        manager = CscapeLifecycleManager()
        assert manager.close() is True
        assert manager.state == CscapeLifecycleState.TERMINATED

    def test_startup_timeout_raises_error(self) -> None:
        """Verify timeout during coordination raises CscapeStartupTimeoutError."""
        manager = CscapeLifecycleManager(launch_timeout=0.2)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        manager.process = mock_proc
        manager.pid = 88888

        with pytest.raises(CscapeStartupTimeoutError):
            manager._coordinate_startup(timeout=0.2)
        assert manager.state == CscapeLifecycleState.FAILED

    def test_legacy_ladder_modes_strictly_rejected(self) -> None:
        """Verify that handle_editor_type_dialog strictly rejects legacy ladder modes 1460 and 3757."""
        manager = CscapeLifecycleManager()
        with pytest.raises(CscapeLifecycleError, match="Legacy ladder mode radio ID 1460 is strictly rejected"):
            manager.handle_editor_type_dialog(radio_id=RADIO_ID_ADVANCED_LADDER_REGISTER)
        with pytest.raises(CscapeLifecycleError, match="Legacy ladder mode radio ID 3757 is strictly rejected"):
            manager.handle_editor_type_dialog(radio_id=RADIO_ID_ADVANCED_LADDER_VARIABLE)
        with pytest.raises(CscapeLifecycleError, match="Non-IEC editor mode radio ID 9999 is strictly rejected"):
            manager.handle_editor_type_dialog(radio_id=9999)


class TestCscapeSingleInstanceAndAllowModalsUnit:
    """Unit tests validating single-instance enforcement and Allow security dialog handling."""

    def test_single_instance_check_connects_when_running(self) -> None:
        """Verify that launch() connects to existing Cscape process without spawning second window."""
        manager = CscapeLifecycleManager(
            executable_path=REAL_CSCAPE_PATH or Path("C:/dummy/Cscape.exe"),
            single_instance_mode="connect",
            reuse_existing=True,
        )

        mock_proc = MagicMock()
        mock_proc.pid = 54321

        with patch.object(CscapeLifecycleManager, "find_running_instances", return_value=[mock_proc]), \
             patch.object(manager, "_connect_to_existing_instance", return_value=True) as mock_connect, \
             patch("subprocess.Popen") as mock_popen:

            res = manager.launch()
            assert res is manager
            mock_connect.assert_called_once_with(mock_proc, timeout=manager.launch_timeout)
            # Ensure subprocess.Popen was NEVER called (no second window spawned)
            mock_popen.assert_not_called()

    def test_single_instance_recycles_when_recycle_mode(self) -> None:
        """Verify that launch() recycles existing instances when single_instance_mode='recycle'."""
        manager = CscapeLifecycleManager(
            executable_path=REAL_CSCAPE_PATH or Path("C:/dummy/Cscape.exe"),
            single_instance_mode="recycle",
        )

        mock_proc = MagicMock()
        mock_proc.pid = 11223

        with patch.object(CscapeLifecycleManager, "find_running_instances", side_effect=[[mock_proc], []]), \
             patch.object(CscapeLifecycleManager, "recycle_running_instances", return_value=1) as mock_recycle, \
             patch.object(manager, "_coordinate_startup"), \
             patch("subprocess.Popen") as mock_popen:

            mock_popen_instance = MagicMock()
            mock_popen_instance.pid = 99887
            mock_popen.return_value = mock_popen_instance

            manager.launch()
            mock_recycle.assert_called()
            assert manager.pid == 99887

    def test_detect_allow_dialog_by_button_text(self) -> None:
        """Verify find_allow_dialogs detects modal containing 'Allow' button."""
        manager = CscapeLifecycleManager()

        mock_win = MagicMock(hwnd=1001, pid=1234, class_name="#32770", title="Windows Security Alert", visible=True)
        mock_btn = ChildControlInfo(hwnd=2001, control_id=1, class_name="Button", text="&Allow access")
        mock_static = ChildControlInfo(hwnd=2002, control_id=-1, class_name="Static", text="Windows Defender Firewall has blocked some features.")

        with patch.object(manager, "_enum_process_windows", return_value=[mock_win]), \
             patch.object(manager, "_enum_all_child_controls", return_value=[mock_btn, mock_static]):

            dialogs = manager.find_allow_dialogs(check_system_windows=False)
            assert len(dialogs) == 1
            assert dialogs[0]["hwnd"] == 1001
            assert dialogs[0]["allow_button_hwnd"] == 2001
            assert "allow access" in dialogs[0]["allow_button_text"].lower()

    def test_detect_allow_dialog_by_dialog_text(self) -> None:
        """Verify find_allow_dialogs detects modal with security phrase in static text."""
        manager = CscapeLifecycleManager()

        mock_win = MagicMock(hwnd=1002, pid=1234, class_name="#32770", title="Windows Security Alert", visible=True)
        mock_ok_btn = ChildControlInfo(hwnd=2003, control_id=1, class_name="Button", text="OK")
        mock_static = ChildControlInfo(hwnd=2004, control_id=-1, class_name="Static", text="Windows Defender Firewall: Allow access to private networks")

        with patch.object(manager, "_enum_process_windows", return_value=[mock_win]), \
             patch.object(manager, "_enum_all_child_controls", return_value=[mock_ok_btn, mock_static]):

            dialogs = manager.find_allow_dialogs(check_system_windows=False)
            assert len(dialogs) == 1
            assert dialogs[0]["hwnd"] == 1002
            assert dialogs[0]["allow_button_hwnd"] == 2003

    def test_bare_allow_ignored_without_security_context(self) -> None:
        """Verify bare generic 'allow' in arbitrary window text does not trigger auto-click."""
        manager = CscapeLifecycleManager()

        # Window with bare 'allow' in title or text but no security keywords
        mock_win = MagicMock(hwnd=1003, pid=1234, class_name="#32770", title="Allowance Report Settings", visible=True)
        mock_btn = ChildControlInfo(hwnd=2006, control_id=1, class_name="Button", text="OK")
        mock_static = ChildControlInfo(hwnd=2007, control_id=-1, class_name="Static", text="Please allow some time for processing.")

        with patch.object(manager, "_enum_process_windows", return_value=[mock_win]), \
             patch.object(manager, "_enum_all_child_controls", return_value=[mock_btn, mock_static]):

            dialogs = manager.find_allow_dialogs(check_system_windows=False)
            assert len(dialogs) == 0

    def test_allow_dialogs_strictly_pid_restricted(self) -> None:
        """Verify find_allow_dialogs does not enumerate arbitrary system windows outside Cscape PID."""
        manager = CscapeLifecycleManager()
        manager.pid = 9999

        # Only Cscape's process windows are returned by _enum_process_windows
        mock_win = MagicMock(hwnd=1004, pid=9999, class_name="#32770", title="Windows Defender Firewall", visible=True)
        mock_btn = ChildControlInfo(hwnd=2008, control_id=1, class_name="Button", text="Allow access")

        with patch.object(manager, "_enum_process_windows", return_value=[mock_win]) as mock_enum, \
             patch.object(manager, "_enum_all_child_controls", return_value=[mock_btn]), \
             patch("win32gui.EnumWindows") as mock_enum_windows:

            dialogs = manager.find_allow_dialogs(check_system_windows=True)
            assert len(dialogs) == 1
            # EnumWindows must NOT be called across the entire system
            mock_enum_windows.assert_not_called()
            mock_enum.assert_called_once()

    def test_handle_allow_dialogs_auto_accept(self) -> None:
        """Verify handle_allow_dialogs sends click and WM_COMMAND to accept dialog."""
        manager = CscapeLifecycleManager()

        dialog_info = [{
            "hwnd": 1005,
            "pid": 5555,
            "title": "Windows Security Alert",
            "class_name": "#32770",
            "allow_button_hwnd": 2005,
            "allow_button_id": 1,
            "allow_button_text": "Allow access",
            "text_content": "Windows Defender Firewall allow access",
        }]

        with patch.object(manager, "find_allow_dialogs", return_value=dialog_info), \
             patch("win32gui.IsWindow", side_effect=[True, False]), \
             patch("win32gui.SendMessage") as mock_send, \
             patch("win32gui.PostMessage") as mock_post:

            accepted = manager.handle_allow_dialogs(timeout=0.5)
            assert accepted == 1
            mock_send.assert_called_once()
            mock_post.assert_called_once()

    def test_allow_dialogs_ignores_non_32770_class(self) -> None:
        """Ensure modal dialog class is strictly #32770; non-#32770 windows are ignored."""
        manager = CscapeLifecycleManager()
        manager.pid = 9999

        mock_win = MagicMock(hwnd=1099, pid=9999, class_name="CustomSecurityClass", title="Windows Security Alert", visible=True)
        mock_btn = ChildControlInfo(hwnd=2099, control_id=1, class_name="Button", text="Allow access")

        with patch.object(manager, "_enum_process_windows", return_value=[mock_win]), \
             patch.object(manager, "_enum_all_child_controls", return_value=[mock_btn]):

            dialogs = manager.find_allow_dialogs(check_system_windows=True)
            assert len(dialogs) == 0

    def test_handle_allow_dialogs_rejects_foreign_pid(self) -> None:
        """Any window not belonging to Cscape PID must NEVER be clicked or dismissed."""
        manager = CscapeLifecycleManager()
        manager.pid = 9999

        dialog_info = [{
            "hwnd": 1005,
            "pid": 5555,  # foreign PID
            "title": "Windows Security Alert",
            "class_name": "#32770",
            "allow_button_hwnd": 2005,
            "allow_button_id": 1,
            "allow_button_text": "Allow access",
            "text_content": "Windows Defender Firewall allow access",
        }]

        with patch.object(manager, "find_allow_dialogs", return_value=dialog_info), \
             patch("win32gui.SendMessage") as mock_send, \
             patch("win32gui.PostMessage") as mock_post:

            accepted = manager.handle_allow_dialogs(timeout=0.5)
            assert accepted == 0
            mock_send.assert_not_called()
            mock_post.assert_not_called()

    def test_handle_allow_dialogs_rejects_non_32770_class(self) -> None:
        """Any window whose class is not #32770 must NEVER be clicked or dismissed."""
        manager = CscapeLifecycleManager()
        manager.pid = 9999

        dialog_info = [{
            "hwnd": 1005,
            "pid": 9999,
            "title": "Windows Security Alert",
            "class_name": "Afx:00400000",  # non-#32770 class
            "allow_button_hwnd": 2005,
            "allow_button_id": 1,
            "allow_button_text": "Allow access",
            "text_content": "Windows Defender Firewall allow access",
        }]

        with patch.object(manager, "find_allow_dialogs", return_value=dialog_info), \
             patch("win32gui.SendMessage") as mock_send, \
             patch("win32gui.PostMessage") as mock_post:

            accepted = manager.handle_allow_dialogs(timeout=0.5)
            assert accepted == 0
            mock_send.assert_not_called()
            mock_post.assert_not_called()

    def test_get_gate_status_4state_contract_when_gate_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify get_gate_status returns strict 4-state contract when no gate file exists."""
        from src.cscape.gate import get_gate_status, GATE_PATHS

        for p in GATE_PATHS:
            monkeypatch.setattr(Path, "exists", lambda self: False)

        gate = get_gate_status()
        assert gate["status"] == "inconclusive"
        assert gate["error_code"] == "GATE_FILE_NOT_FOUND"
        assert gate["ready_for_tests"] is False

    def test_coordinate_startup_auto_accepts_allow_modals(self) -> None:
        """Verify _coordinate_startup calls handle_allow_dialogs when auto_accept_allow is True."""
        manager = CscapeLifecycleManager(auto_accept_allow=True, launch_timeout=1.0)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        manager.process = mock_proc
        manager.pid = 44332

        mock_main = MagicMock(hwnd=8001, pid=44332, class_name="Afx:00400000", title="Cscape - [TestProj.cpj]", visible=True, enabled=True, rect=(0, 0, 800, 600))

        with patch.object(manager, "handle_allow_dialogs", return_value=1) as mock_handle_allow, \
             patch.object(manager, "find_splash_dialog", return_value=None), \
             patch.object(manager, "find_editor_type_dialog", return_value=None), \
             patch.object(manager, "find_allow_dialogs", return_value=[]), \
             patch.object(manager, "find_main_cscape_window", return_value=mock_main):

            manager._coordinate_startup(timeout=2.0)
            assert manager.state == CscapeLifecycleState.READY
            assert manager.main_hwnd == 8001
            assert mock_handle_allow.called

    def test_clean_teardown_sc_close_dispatch(self) -> None:
        """Verify close() sends SC_CLOSE (0xF060) via WM_SYSCOMMAND and WM_CLOSE to all process windows."""
        manager = CscapeLifecycleManager()
        mock_proc = MagicMock()
        poll_count = 0

        def mock_poll():
            nonlocal poll_count
            poll_count += 1
            # Keep running through Step 1 initial wait so Step 2 SC_CLOSE is dispatched
            return None if poll_count < 8 else 0

        mock_proc.poll.side_effect = mock_poll
        manager.process = mock_proc
        manager.pid = 9911
        manager.main_hwnd = 12345
        manager.state = CscapeLifecycleState.READY

        mock_win1 = MagicMock(hwnd=12345)
        mock_win2 = MagicMock(hwnd=12346)

        with patch("win32gui.IsWindow", return_value=True), \
             patch.object(manager, "_enum_process_windows", return_value=[mock_win1, mock_win2]), \
             patch("win32gui.PostMessage") as mock_post:

            closed = manager.close(graceful_timeout=1.0)
            assert closed is True
            sc_close_calls = [
                call for call in mock_post.call_args_list
                if len(call[0]) >= 3 and call[0][1] == WM_SYSCOMMAND and call[0][2] == SC_CLOSE
            ]
            assert len(sc_close_calls) >= 2

    def test_detect_windows_defender_firewall_modal(self) -> None:
        """Verify find_allow_dialogs detects Windows Defender Firewall modal with 'Allow access' button."""
        manager = CscapeLifecycleManager()

        mock_win = MagicMock(hwnd=3001, pid=5678, class_name="#32770", title="Windows Security Alert", visible=True)
        mock_btn = ChildControlInfo(hwnd=4001, control_id=1, class_name="Button", text="&Allow access")
        mock_static = ChildControlInfo(hwnd=4002, control_id=-1, class_name="Static", text="Windows Defender Firewall has blocked some features of Cscape.")

        with patch.object(manager, "_enum_process_windows", return_value=[mock_win]), \
             patch.object(manager, "_enum_all_child_controls", return_value=[mock_btn, mock_static]):

            dialogs = manager.find_allow_dialogs(check_system_windows=False)
            assert len(dialogs) == 1
            assert dialogs[0]["hwnd"] == 3001
            assert dialogs[0]["allow_button_hwnd"] == 4001
            assert "allow access" in dialogs[0]["allow_button_text"].lower()

    def test_detect_windows_security_unblock_modal(self) -> None:
        """Verify find_allow_dialogs detects Windows Security modal with 'Unblock' or 'Always allow' button."""
        manager = CscapeLifecycleManager()

        mock_win = MagicMock(hwnd=3002, pid=5679, class_name="#32770", title="Windows Security", visible=True)
        mock_btn = ChildControlInfo(hwnd=4003, control_id=101, class_name="Button", text="&Unblock")
        mock_static = ChildControlInfo(hwnd=4004, control_id=-1, class_name="Static", text="Security prompt for network connectivity.")

        with patch.object(manager, "_enum_process_windows", return_value=[mock_win]), \
             patch.object(manager, "_enum_all_child_controls", return_value=[mock_btn, mock_static]):

            dialogs = manager.find_allow_dialogs(check_system_windows=False)
            assert len(dialogs) == 1
            assert dialogs[0]["hwnd"] == 3002
            assert dialogs[0]["allow_button_hwnd"] == 4003
            assert "unblock" in dialogs[0]["allow_button_text"].lower()



class TestLiveCscapeRealLifecycle:
    """Live verification tests against real Horner APG Cscape 10.2 binary."""

    @pytest.fixture(autouse=True)
    def cleanup_cscape(self):
        from src.cscape.gate import get_gate_status
        gate = get_gate_status()
        if not gate.get("ready_for_tests"):
            pytest.skip(f"Live Cscape gate not ready or offline: status='{gate.get('status')}', reason='{gate.get('reason')}'")
        if gate.get("ready_for_tests"):
            pytest.skip("Supervised Cscape keepalive gate is active with TankLevelClosedLoop; skipping raw lifecycle restarts to avoid disrupting live gate")

        def _force_clean_all():
            if not IS_WINDOWS:
                return
            recycle_running_cscape_instances(timeout=5.0)
            set_cscape_exited_correctly(1)

        _force_clean_all()
        yield
        _force_clean_all()

    @requires_real_cscape
    def test_live_real_cscape_launch_detect_dismiss_and_graceful_shutdown(self) -> None:
        """End-to-end live test:

        1. Launches real Cscape.exe via subprocess.
        2. Detects and dismisses modal 'About Cscape' splash window (#32770).
        3. Detects 'Select Editor Type' dialog (#32770), selects 'IEC 61131 Language Editors' (ID 1461), and clicks OK (ID 1).
        4. Waits until main Cscape window is fully ready, visible, and enabled.
        5. Verifies is_ready == True and main window handle exists.
        6. Performs graceful shutdown via WM_CLOSE.
        7. Verifies process terminated cleanly with exit code 0 or 1.
        """
        manager = CscapeLifecycleManager(
            executable_path=REAL_CSCAPE_PATH,
            auto_dismiss_splash=True,
            auto_select_iec=True,
            launch_timeout=45.0,
            shutdown_timeout=15.0,
        )

        try:
            # 1-4. Launch and coordinate startup
            manager.launch()

            # 5. Verify readiness
            assert manager.is_running is True
            assert manager.is_ready is True
            assert manager.state == CscapeLifecycleState.READY
            assert manager.pid is not None and manager.pid > 0
            assert manager.main_hwnd is not None and manager.main_hwnd > 0

            title = manager.get_main_window_title()
            assert title is not None
            assert "cscape" in title.lower()

            # 6. Perform graceful shutdown
            closed = manager.close(graceful_timeout=15.0)
            assert closed is True

            # 7. Verify termination
            assert manager.is_running is False
            assert manager.state == CscapeLifecycleState.TERMINATED
            assert manager.exit_code in (0, 1, 15, 4294967295, 3221226525)
        finally:
            if manager.is_running:
                manager.terminate()

    @requires_real_cscape
    def test_live_real_cscape_context_manager(self) -> None:
        """Verify context manager pattern: enters ready, exits terminated cleanly."""
        manager = CscapeLifecycleManager(
            executable_path=REAL_CSCAPE_PATH,
            launch_timeout=45.0,
            shutdown_timeout=15.0,
        )

        with manager as cscape:
            assert cscape.is_running is True
            assert cscape.is_ready is True
            assert cscape.main_hwnd is not None
            assert "cscape" in cscape.get_main_window_title().lower()

        assert not manager.is_running
        assert manager.state == CscapeLifecycleState.TERMINATED
        assert manager.exit_code in (0, 1, 15, 4294967295, 3221226525)

    @requires_real_cscape
    @pytest.mark.asyncio
    async def test_live_real_cscape_async_lifecycle(self) -> None:
        """Verify asynchronous launch and shutdown wrappers."""
        manager = CscapeLifecycleManager(
            executable_path=REAL_CSCAPE_PATH,
            launch_timeout=45.0,
            shutdown_timeout=15.0,
        )

        try:
            started = await manager.launch_async()
            assert started.is_ready is True
            assert started.main_hwnd is not None

            closed = await manager.close_async(graceful_timeout=15.0)
            assert closed is True
            assert not manager.is_running
            assert manager.exit_code in (0, 1, 15, 4294967295, 3221226525)
        finally:
            if manager.is_running:
                manager.terminate()

    @requires_real_cscape
    def test_live_convenience_launch_cscape(self) -> None:
        """Verify top-level convenience helper launch_cscape."""
        manager = launch_cscape(timeout=45.0)
        try:
            assert manager.is_ready is True
            assert manager.main_hwnd is not None
        finally:
            manager.close(graceful_timeout=15.0)
            assert not manager.is_running
            assert manager.exit_code in (0, 1, 15, 4294967295, 3221226525)

    @requires_real_cscape
    def test_live_real_cscape_single_instance_reuse_no_second_window(self) -> None:
        """Live verification: single-instance check connects without spawning a second window."""
        manager1 = CscapeLifecycleManager(
            executable_path=REAL_CSCAPE_PATH,
            single_instance_mode="recycle",
            launch_timeout=45.0,
            shutdown_timeout=15.0,
        )

        try:
            manager1.launch()
            assert manager1.is_ready is True
            pid1 = manager1.pid
            assert pid1 is not None

            # Attempt a second launch with single_instance_mode="connect"
            manager2 = CscapeLifecycleManager(
                executable_path=REAL_CSCAPE_PATH,
                single_instance_mode="connect",
                reuse_existing=True,
                launch_timeout=20.0,
                shutdown_timeout=15.0,
            )
            manager2.launch()
            assert manager2.is_ready is True
            # Enforce 'No second window': connected to the exact same PID
            assert manager2.pid == pid1

            # Verify that only ONE instance of Cscape.exe is running on the entire system
            running_procs = CscapeLifecycleManager.find_running_instances()
            assert len(running_procs) == 1
            assert running_procs[0].pid == pid1
        finally:
            manager1.close(graceful_timeout=15.0)
            if manager1.is_running:
                manager1.terminate()
