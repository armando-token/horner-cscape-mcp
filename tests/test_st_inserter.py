"""Tests for StructuredTextInserter: Silent Mocks Removal & Honest Injection.

Validates:
1. Complete elimination of _mock_editor_store and fake HWND fabrication.
2. Honest failure reporting when live GUI injection (WINDOW_HANDLE, CLIPBOARD, SENDKEYS) is requested without a live editor window.
3. Offline file-based injection (FILE_SYNC) requiring valid project_dir and setting editor_hwnd=None.
4. Rejection of ladder logic and enforcement of pure Structured Text.
5. Strict PID-restriction of POU creation modal detection to Cscape PID and direct children.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.cscape.st_inserter import (
    StructuredTextInserter,
    InsertionMethod,
    POUType,
    STInsertionResult,
    calculate_code_hash,
    calculate_ast_hash,
    normalize_st_code,
)

SAMPLE_ST_PROGRAM = """
PROGRAM MainControl
VAR
    bStart : BOOL;
    bStop  : BOOL;
    bRunning : BOOL;
    nSpeed : INT;
END_VAR

IF bStart AND NOT bStop THEN
    bRunning := TRUE;
    nSpeed := 1500;
ELSIF bStop THEN
    bRunning := FALSE;
    nSpeed := 0;
END_IF;
END_PROGRAM
"""


class TestMockStoreElimination:
    """Verify that _mock_editor_store and fake HWNDs are completely eliminated."""

    def test_mock_editor_store_removed_from_class_and_instance(self):
        """Confirm _mock_editor_store does not exist on class or instance."""
        assert not hasattr(StructuredTextInserter, "_mock_editor_store")
        inserter = StructuredTextInserter()
        assert not hasattr(inserter, "_mock_editor_store")

    def test_find_editor_windows_returns_empty_when_no_live_cscape(self):
        """find_editor_windows returns empty list and does not return fabricated mock info."""
        inserter = StructuredTextInserter()
        windows = inserter.find_editor_windows("AnyPOU")
        assert windows == []

    def test_read_editor_code_returns_empty_when_no_real_window(self):
        """read_editor_code does not look in mock store; returns empty string for fake handle."""
        inserter = StructuredTextInserter()
        code = inserter.read_editor_code(0x12345)
        assert code == ""


class TestHonestLiveGUIFailure:
    """Verify honest failure when live GUI injection is requested without a live editor window."""

    def test_live_window_handle_fails_honestly(self):
        """WINDOW_HANDLE method fails honestly when no live editor window is present."""
        inserter = StructuredTextInserter()
        res = inserter.insert_pou(
            pou_name="MotorControl",
            pou_type=POUType.PROGRAM,
            code=SAMPLE_ST_PROGRAM,
            method=InsertionMethod.WINDOW_HANDLE,
        )
        assert res.success is False
        assert res.editor_hwnd is None
        assert "Live GUI injection requested via 'window_handle'" in res.error_message
        assert "no active Cscape editor window was found" in res.error_message

    def test_live_clipboard_fails_honestly(self):
        """CLIPBOARD method fails honestly when no live editor window is present."""
        inserter = StructuredTextInserter()
        res = inserter.insert_pou(
            pou_name="MotorControl",
            pou_type=POUType.PROGRAM,
            code=SAMPLE_ST_PROGRAM,
            method=InsertionMethod.CLIPBOARD,
        )
        assert res.success is False
        assert res.editor_hwnd is None
        assert "Live GUI injection requested via 'clipboard'" in res.error_message
        assert "no active Cscape editor window was found" in res.error_message

    def test_live_sendkeys_fails_honestly(self):
        """SENDKEYS method fails honestly when no live editor window is present."""
        inserter = StructuredTextInserter()
        res = inserter.insert_pou(
            pou_name="MotorControl",
            pou_type=POUType.PROGRAM,
            code=SAMPLE_ST_PROGRAM,
            method=InsertionMethod.SENDKEYS,
        )
        assert res.success is False
        assert res.editor_hwnd is None
        assert "Live GUI injection requested via 'sendkeys'" in res.error_message
        assert "no active Cscape editor window was found" in res.error_message

    def test_auto_fails_honestly_when_no_editor_and_no_project_dir(self):
        """AUTO method fails honestly if no live editor window and no project_dir provided."""
        inserter = StructuredTextInserter()
        res = inserter.insert_pou(
            pou_name="OrphanPOU",
            pou_type=POUType.PROGRAM,
            code=SAMPLE_ST_PROGRAM,
            method=InsertionMethod.AUTO,
            project_dir=None,
        )
        assert res.success is False
        assert res.editor_hwnd is None
        assert "No active Cscape editor window found" in res.error_message
        assert "no project_dir provided" in res.error_message


class TestOfflineFileBasedInjection:
    """Verify offline file-based injection when project_dir is supplied."""

    def test_auto_falls_back_to_file_sync_without_fake_hwnd(self, tmp_path: Path):
        """AUTO method uses offline file-based injection (FILE_SYNC) and sets editor_hwnd=None."""
        proj = tmp_path / "OfflineProj"
        proj.mkdir()
        inserter = StructuredTextInserter(workspace_dir=tmp_path)
        res = inserter.insert_pou(
            pou_name="OfflineLogic",
            pou_type=POUType.PROGRAM,
            code=SAMPLE_ST_PROGRAM,
            method=InsertionMethod.AUTO,
            project_dir=proj,
            verify=True,
        )
        assert res.success is True
        assert res.method_used == InsertionMethod.FILE_SYNC
        # Crucial invariant: NO fake fabricated HWNDs!
        assert res.editor_hwnd is None
        assert res.verified is True
        assert (proj / "pous" / "OfflineLogic.st").exists()

    def test_explicit_file_sync_without_fake_hwnd(self, tmp_path: Path):
        """FILE_SYNC explicitly requested performs file injection with editor_hwnd=None."""
        proj = tmp_path / "ExplicitSyncProj"
        proj.mkdir()
        inserter = StructuredTextInserter(workspace_dir=tmp_path)
        res = inserter.insert_pou(
            pou_name="ExplicitLogic",
            pou_type=POUType.PROGRAM,
            code=SAMPLE_ST_PROGRAM,
            method=InsertionMethod.FILE_SYNC,
            project_dir=proj,
            verify=True,
        )
        assert res.success is True
        assert res.method_used == InsertionMethod.FILE_SYNC
        assert res.editor_hwnd is None
        assert res.verified is True

    def test_ladder_logic_rejected_pre_insertion(self, tmp_path: Path):
        """Ladder logic constructs are rejected at AST/interop level before file write."""
        proj = tmp_path / "LadderProj"
        proj.mkdir()
        ladder = "PROGRAM Ladder\nVAR x : BOOL; END_VAR\n---[ x ]---( )---\nEND_PROGRAM"
        inserter = StructuredTextInserter(workspace_dir=tmp_path)
        res = inserter.insert_pou(
            pou_name="BadLadder",
            pou_type=POUType.PROGRAM,
            code=ladder,
            project_dir=proj,
        )
        assert res.success is False
        assert "Ladder logic rejected" in res.error_message
        assert not (proj / "pous" / "BadLadder.st").exists()


class TestPOUCreationModalPIDRestriction:
    """Verify modal dialog handling during POU creation is strictly PID-restricted."""

    def test_handle_pou_creation_modals_ignores_non_cscape_dialogs(self):
        """_handle_pou_creation_modals ignores #32770 dialogs belonging to other PIDs."""
        inserter = StructuredTextInserter(cscape_pid=7777, main_hwnd=0x1111)

        # Non-Cscape dialog
        other_dlg_hwnd = 0x9999
        with patch("win32gui.IsWindowVisible", return_value=True), \
             patch("win32gui.GetClassName", return_value="#32770"), \
             patch("win32process.GetWindowThreadProcessId", return_value=(0, 9999)), \
             patch("win32gui.SendMessage") as mock_send, \
             patch("win32gui.PostMessage") as mock_post:

            def mock_enum(cb, _):
                cb(other_dlg_hwnd, None)
                return True

            with patch("win32gui.EnumWindows", side_effect=mock_enum):
                handled = inserter._handle_pou_creation_modals(timeout=0.2)
                assert handled is False
                mock_send.assert_not_called()
                mock_post.assert_not_called()
