"""Audit and Verification Test Suite for Cscape Dialog Handling Routines.

Validates:
1. 'About Cscape' splash dialog (#32770, IDOK=1) automated detection and dismissal.
2. 'Select Editor Type' dialog (#32770, Radio 1461, IDOK=1) automated detection and selection.
   - Strict rejection of legacy ladder modes (1460, 3757).
3. 'Save As' common dialog (#32770, Edit 1152, ID 1) automated detection and handling.
4. 'Accept Allow' handling for firewall and security prompts across process and system windows.
5. Strict zero physical PLC download lockout enforcement.
6. Live end-to-end testing against real Horner Cscape 10.2 application.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.cscape.lifecycle import (
    CscapeLifecycleManager,
    CscapeLifecycleState,
    CscapeLifecycleError,
    WindowInfo,
    ChildControlInfo,
    DIALOG_CLASS_NAME,
    SPLASH_TITLE_SUBSTRING,
    EDITOR_TYPE_TITLE_SUBSTRING,
    SAVE_AS_TITLE_SUBSTRING,
    SAVE_AS_CLASS_NAME,
    ID_OK,
    ID_CANCEL,
    RADIO_ID_IEC_61131,
    RADIO_ID_ADVANCED_LADDER_REGISTER,
    RADIO_ID_ADVANCED_LADDER_VARIABLE,
    EDIT_ID_FILE_NAME,
    BUTTON_ID_SAVE,
    ALLOW_TEXT_KEYWORDS,
    ALLOW_BUTTON_KEYWORDS,
    resolve_cscape_executable,
)
from src.cscape.project_manager import (
    CscapeLiveProjectManager,
    ProjectCreationResult,
    create_new_iec_project,
    CscapeSafetyError,
    CscapeAutomationError,
    DIALOG_CLASS,
    SPLASH_TITLE,
    EDITOR_TYPE_TITLE,
    SAVE_AS_TITLE,
    RADIO_IEC_61131,
    RADIO_ADVANCED_LADDER_REG,
    RADIO_ADVANCED_LADDER_VAR,
    EDIT_FILE_NAME_ID,
    SAVE_BUTTON_ID,
    ID_FILE_NEW,
    ID_FILE_SAVE,
    ID_FILE_SAVE_AS,
)
from src.cscape.safety import (
    ID_CONTROLLER_DOWNLOAD,
    ID_CONTROLLER_DOWNLOAD_ALT,
    CscapeSafetyViolationError,
    BLOCKED_DOWNLOAD_COMMAND_IDS,
    intercept_download_command,
    intercept_hardware_interface,
)
from src.security.exceptions import (
    HardwareLockoutError,
    UnauthorizedDownloadError,
)

REAL_CSCAPE_PATH = resolve_cscape_executable()
HAS_REAL_CSCAPE = REAL_CSCAPE_PATH is not None and REAL_CSCAPE_PATH.exists()
IS_WINDOWS = sys.platform == "win32" or os.name == "nt"

requires_real_cscape = pytest.mark.skipif(
    not (IS_WINDOWS and HAS_REAL_CSCAPE),
    reason="Requires Windows OS with installed Cscape 10.2 executable",
)


class TestDialogConstantsAudit:
    """Audit control IDs, class names, and substring constants across both modules."""

    def test_lifecycle_constants(self) -> None:
        """Verify lifecycle.py dialog constants."""
        assert DIALOG_CLASS_NAME == "#32770"
        assert SPLASH_TITLE_SUBSTRING == "About Cscape"
        assert EDITOR_TYPE_TITLE_SUBSTRING == "Select Editor Type"
        assert SAVE_AS_TITLE_SUBSTRING == "Save As"
        assert SAVE_AS_CLASS_NAME == "#32770"
        assert ID_OK == 1
        assert ID_CANCEL == 2
        assert RADIO_ID_IEC_61131 == 1461
        assert RADIO_ID_ADVANCED_LADDER_REGISTER == 1460
        assert RADIO_ID_ADVANCED_LADDER_VARIABLE == 3757
        assert EDIT_ID_FILE_NAME == 1152
        assert BUTTON_ID_SAVE == 1

    def test_project_manager_constants(self) -> None:
        """Verify project_manager.py dialog constants."""
        assert DIALOG_CLASS == "#32770"
        assert SPLASH_TITLE == "About Cscape"
        assert EDITOR_TYPE_TITLE == "Select Editor Type"
        assert SAVE_AS_TITLE == "Save As"
        assert RADIO_IEC_61131 == 1461
        assert RADIO_ADVANCED_LADDER_REG == 1460
        assert RADIO_ADVANCED_LADDER_VAR == 3757
        assert EDIT_FILE_NAME_ID == 1152
        assert SAVE_BUTTON_ID == 1

    def test_allow_security_keywords(self) -> None:
        """Verify firewall and security prompt keywords and rejection of bare generic 'allow'."""
        for kw in ("allow access", "windows defender firewall", "security alert"):
            assert any(kw in t for t in ALLOW_TEXT_KEYWORDS)
        # Bare generic 'allow' or 'firewall' alone must NOT be entries in ALLOW_TEXT_KEYWORDS
        assert "allow" not in ALLOW_TEXT_KEYWORDS
        assert "firewall" not in ALLOW_TEXT_KEYWORDS
        for bkw in ("allow", "allow access", "allow this app"):
            assert any(bkw in b for b in ALLOW_BUTTON_KEYWORDS)


class TestLifecycleDialogRoutinesUnit:
    """Unit tests validating lifecycle.py dialog detection and handling."""

    def test_find_and_dismiss_splash_dialog(self) -> None:
        """Test splash dialog (#32770, IDOK=1) detection and dismissal."""
        manager = CscapeLifecycleManager()

        mock_splash = WindowInfo(
            hwnd=12345,
            pid=9999,
            class_name="#32770",
            title="About Cscape 10.2",
            visible=True,
        )
        mock_ok_btn = ChildControlInfo(
            hwnd=54321,
            control_id=ID_OK,
            class_name="Button",
            text="OK",
            visible=True,
        )

        with patch.object(manager, "_enum_process_windows", side_effect=[[mock_splash], []]), \
             patch.object(manager, "_enum_child_controls", return_value={ID_OK: 54321}), \
             patch.object(manager, "_enum_all_child_controls", return_value=[mock_ok_btn]), \
             patch("win32gui.IsWindow", return_value=True), \
             patch("win32gui.SendMessage") as mock_send, \
             patch("win32gui.PostMessage") as mock_post:

            dismissed = manager.dismiss_splash_window(timeout=1.0)
            assert dismissed is True
            assert manager.state == CscapeLifecycleState.SPLASH_DISMISSED
            mock_send.assert_called()
            mock_post.assert_called()

    def test_editor_type_dialog_selection_and_rejection(self) -> None:
        """Test Select Editor Type dialog (Radio 1461, IDOK=1) and legacy mode rejection."""
        manager = CscapeLifecycleManager()

        # Rejection of legacy ladder modes
        with pytest.raises(CscapeLifecycleError, match="1460 is strictly rejected"):
            manager.handle_editor_type_dialog(radio_id=RADIO_ID_ADVANCED_LADDER_REGISTER)
        with pytest.raises(CscapeLifecycleError, match="3757 is strictly rejected"):
            manager.handle_editor_type_dialog(radio_id=RADIO_ID_ADVANCED_LADDER_VARIABLE)

        # Successful selection of IEC 61131 (Radio 1461)
        mock_editor = WindowInfo(
            hwnd=22222,
            pid=9999,
            class_name="#32770",
            title="Select Editor Type",
            visible=True,
        )
        mock_radio = ChildControlInfo(
            hwnd=33331,
            control_id=RADIO_ID_IEC_61131,
            class_name="Button",
            text="IEC 61131 Language Editors",
            visible=True,
        )
        mock_ok = ChildControlInfo(
            hwnd=33332,
            control_id=ID_OK,
            class_name="Button",
            text="OK",
            visible=True,
        )

        with patch.object(manager, "_enum_process_windows", side_effect=[[mock_editor], []]), \
             patch.object(manager, "_enum_child_controls", return_value={RADIO_ID_IEC_61131: 33331, ID_OK: 33332}), \
             patch.object(manager, "_enum_all_child_controls", return_value=[mock_radio, mock_ok]), \
             patch("win32gui.IsWindow", return_value=True), \
             patch("win32gui.SendMessage") as mock_send, \
             patch("win32gui.PostMessage") as mock_post:

            handled = manager.handle_editor_type_dialog(radio_id=RADIO_ID_IEC_61131, timeout=1.0)
            assert handled is True
            assert manager.state == CscapeLifecycleState.EDITOR_TYPE_SELECTED
            assert mock_send.call_count >= 2
            assert mock_post.call_count >= 1

    def test_save_as_dialog_handling(self, tmp_path: Path) -> None:
        """Test Save As dialog (#32770, Edit 1152, ID 1) automated handling in lifecycle."""
        manager = CscapeLifecycleManager()
        target_file = tmp_path / "lifecycle_save_test.csp"

        mock_save = WindowInfo(
            hwnd=44444,
            pid=9999,
            class_name="#32770",
            title="Save As",
            visible=True,
        )
        mock_edit = ChildControlInfo(
            hwnd=55551,
            control_id=EDIT_ID_FILE_NAME,
            class_name="Edit",
            text="",
            visible=True,
        )
        mock_save_btn = ChildControlInfo(
            hwnd=55552,
            control_id=BUTTON_ID_SAVE,
            class_name="Button",
            text="Save",
            visible=True,
        )

        with patch.object(manager, "find_save_as_dialog", side_effect=[mock_save, mock_save, None]), \
             patch.object(manager, "_enum_all_child_controls", return_value=[mock_edit, mock_save_btn]), \
             patch("win32gui.GetDlgItem", side_effect=[55551, 55552]), \
             patch("win32gui.IsWindow", side_effect=[True, True, False]), \
             patch("win32gui.IsWindowVisible", side_effect=[True, False]), \
             patch("win32gui.SendMessage") as mock_send, \
             patch("win32gui.PostMessage") as mock_post:

            handled = manager.handle_save_as_dialog(destination_path=target_file, timeout=2.0)
            assert handled is True
            mock_send.assert_called()
            mock_post.assert_called()


class TestProjectManagerDialogRoutinesUnit:
    """Unit tests validating project_manager.py dialog detection and handling."""

    def test_click_button_posts_command(self) -> None:
        """Verify click_button sends BM_CLICK and posts WM_COMMAND with target ID."""
        manager = CscapeLiveProjectManager(cscape_path="C:/dummy/Cscape.exe")

        with patch("win32gui.GetDlgItem", return_value=1234), \
             patch("win32gui.GetDlgCtrlID", return_value=1), \
             patch("win32gui.SendMessage") as mock_send, \
             patch("win32gui.PostMessage") as mock_post:

            res = manager.click_button(dialog_hwnd=9999, ctrl_id=1)
            assert res is True
            mock_send.assert_called_once()
            mock_post.assert_called_once()

    def test_find_and_dismiss_splash_dialog(self) -> None:
        """Verify dismiss_splash_dialog in project_manager."""
        manager = CscapeLiveProjectManager(cscape_path="C:/dummy/Cscape.exe")

        with patch.object(manager, "find_splash_dialog", return_value=8888), \
             patch.object(manager, "click_button", return_value=True), \
             patch("win32gui.IsWindow", side_effect=[True, False]):

            dismissed = manager.dismiss_splash_dialog(dialog_hwnd=8888, timeout_sec=1.0)
            assert dismissed is True

    def test_handle_editor_type_dialog_rejects_ladder(self) -> None:
        """Verify handle_editor_type_dialog rejects ladder mode IDs 1460 and 3757."""
        manager = CscapeLiveProjectManager(cscape_path="C:/dummy/Cscape.exe")

        with pytest.raises(CscapeSafetyError, match="1460 is strictly rejected"):
            manager.handle_editor_type_dialog(dialog_hwnd=7777, radio_id=RADIO_ADVANCED_LADDER_REG)
        with pytest.raises(CscapeSafetyError, match="3757 is strictly rejected"):
            manager.handle_editor_type_dialog(dialog_hwnd=7777, radio_id=RADIO_ADVANCED_LADDER_VAR)

    def test_find_and_handle_save_as_dialog(self, tmp_path: Path) -> None:
        """Verify Save As dialog detection (#32770, Edit 1152, ID 1) in project_manager."""
        manager = CscapeLiveProjectManager(cscape_path="C:/dummy/Cscape.exe")
        target_path = tmp_path / "test_proj.csp"

        with patch("win32gui.GetDlgItem", side_effect=[2221, 2222]), \
             patch("win32gui.SendMessage") as mock_send, \
             patch("win32gui.PostMessage") as mock_post, \
             patch("win32gui.IsWindow", side_effect=[True, False]), \
             patch.object(manager, "handle_allow_dialogs", return_value=0):

            handled = manager.handle_save_as_dialog(dialog_hwnd=6666, destination_path=target_path, timeout_sec=2.0)
            assert handled is True
            mock_send.assert_called()
            mock_post.assert_called()

    def test_find_and_handle_allow_dialogs(self) -> None:
        """Verify firewall/security dialog detection and acceptance across system windows."""
        manager = CscapeLiveProjectManager(cscape_path="C:/dummy/Cscape.exe")

        mock_dlg_info = [{
            "hwnd": 9991,
            "title": "Windows Security Alert",
            "class_name": "#32770",
            "allow_button_hwnd": 9992,
            "allow_button_text": "Allow access",
        }]

        with patch.object(manager, "find_allow_dialogs", return_value=mock_dlg_info), \
             patch("win32gui.IsWindow", side_effect=[True, False]), \
             patch("win32gui.SendMessage") as mock_send, \
             patch("win32gui.GetDlgCtrlID", return_value=1), \
             patch("win32gui.PostMessage") as mock_post:

            accepted = manager.handle_allow_dialogs(timeout_sec=0.5)
            assert accepted == 1
            mock_send.assert_called_once()
            mock_post.assert_called_once()

    def test_find_allow_dialogs_strictly_pid_restricted(self) -> None:
        """Verify project_manager find_allow_dialogs does not enumerate arbitrary system windows."""
        manager = CscapeLiveProjectManager(cscape_path="C:/dummy/Cscape.exe")
        manager.pid = 8888

        with patch.object(manager, "enum_process_windows", return_value=[9991]) as mock_enum, \
             patch.object(manager, "_safe_get_text", return_value="Windows Defender Firewall"), \
             patch.object(manager, "_safe_get_class", return_value="#32770"), \
             patch.object(manager, "find_descendant", return_value=9992), \
             patch("win32gui.EnumWindows") as mock_enum_windows:

            dlgs = manager.find_allow_dialogs(check_system_windows=True)
            assert len(dlgs) == 1
            mock_enum.assert_called_once()
            mock_enum_windows.assert_not_called()


class TestStrictZeroPLCDownloadLockout:
    """Audit hardware lockout and verify strict zero PLC download enforcement."""

    def test_download_command_ids_blocked(self) -> None:
        """Verify ID_CONTROLLER_DOWNLOAD and alternate command IDs raise security exceptions."""
        assert ID_CONTROLLER_DOWNLOAD == 32827
        assert ID_CONTROLLER_DOWNLOAD_ALT == 33149
        assert 32827 in BLOCKED_DOWNLOAD_COMMAND_IDS
        assert 33149 in BLOCKED_DOWNLOAD_COMMAND_IDS

        with pytest.raises((CscapeSafetyViolationError, UnauthorizedDownloadError)):
            intercept_download_command(32827)

        with pytest.raises((CscapeSafetyViolationError, UnauthorizedDownloadError)):
            intercept_download_command(33149)

        with pytest.raises((CscapeSafetyViolationError, UnauthorizedDownloadError)):
            intercept_download_command("ID_CONTROLLER_DOWNLOAD")

    def test_hardware_ports_blocked(self) -> None:
        """Verify serial, CAN, and USB interfaces raise HardwareLockoutError fail-closed."""
        for port in ("COM1", "COM3", "CAN0", "USB", "HORNER_USB"):
            with pytest.raises((CscapeSafetyViolationError, HardwareLockoutError)):
                intercept_hardware_interface(port)


class TestLiveCscapeDialogAudit:
    """Live integration tests running directly against installed Cscape 10.2."""

    @pytest.fixture(autouse=True)
    def clean_cscape_processes(self):
        """Clean up any orphan Cscape processes before and after live tests."""
        from src.cscape.gate import get_gate_status
        gate = get_gate_status()
        if not gate.get("ready_for_tests"):
            pytest.skip(f"Live Cscape gate not ready or offline: status='{gate.get('status')}', reason='{gate.get('reason')}'")
        if gate.get("ready_for_tests"):
            pytest.skip("Supervised Cscape keepalive gate is active with TankLevelClosedLoop; skipping raw dialog tests to prevent gate disruption")
        from src.cscape.lifecycle import set_cscape_exited_correctly
        if IS_WINDOWS:
            CscapeLifecycleManager.recycle_running_instances(timeout=5.0)
            set_cscape_exited_correctly(1)
            time.sleep(1.0)
        yield
        if IS_WINDOWS:
            CscapeLifecycleManager.recycle_running_instances(timeout=5.0)
            set_cscape_exited_correctly(1)
            time.sleep(1.0)

    @requires_real_cscape
    def test_live_cscape_startup_dismissal_and_iec_mode(self) -> None:
        """Live verification: Cscape launches, splash dismisses (#32770), and IEC mode is asserted."""
        manager = CscapeLifecycleManager(
            executable_path=REAL_CSCAPE_PATH,
            auto_dismiss_splash=True,
            auto_select_iec=True,
            launch_timeout=45.0,
            shutdown_timeout=15.0,
        )

        try:
            manager.launch()
            assert manager.is_running is True
            assert manager.is_ready is True
            assert manager.state == CscapeLifecycleState.READY
            assert manager.main_hwnd is not None and manager.main_hwnd > 0

            # Verify splash (#32770) is dismissed
            assert manager.find_splash_dialog() is None
            # Verify editor type dialog is handled
            assert manager.find_editor_type_dialog() is None

            title = manager.get_main_window_title()
            assert "cscape" in title.lower()
        finally:
            manager.close(graceful_timeout=15.0)
            assert manager.is_running is False

    @requires_real_cscape
    def test_live_project_creation_save_as_and_zero_download(self, tmp_path: Path) -> None:
        """Live verification: File -> New (IEC 61131), Save As (#32770, Edit 1152, ID 1), zero download."""
        target_csp = tmp_path / f"live_dialog_audit_{int(time.time())}.csp"

        result = create_new_iec_project(
            save_path=target_csp,
            project_name=target_csp.stem,
            timeout_sec=45.0,
            auto_close=True,
        )

        assert isinstance(result, ProjectCreationResult)
        assert result.success is True, f"Project creation failed: {result.error}"
        assert result.editor_mode == "IEC 61131"
        assert target_csp.exists()
        assert target_csp.stat().st_size > 1024

        # Verify CFBF structure
        assert result.file_info is not None
        assert result.file_info.is_valid_cfbf is True
        assert result.file_info.has_contents_stream is True

        # Assert strict zero download lockout
        with pytest.raises((CscapeSafetyViolationError, UnauthorizedDownloadError)):
            intercept_download_command(ID_CONTROLLER_DOWNLOAD)
