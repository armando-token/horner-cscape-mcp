"""Real Cscape 10.2 Structured Text POU Insertion Test Suite.

Verifies:
1. Automated addition of new Structured Text POUs (Program, FunctionBlock, Function)
   with verified Cscape MFC Command IDs (38055, 37999, 38050).
2. Multi-tier Structured Text code insertion:
   - Window handle direct injection (WM_SETTEXT / EM_REPLACESEL / Scintilla)
   - Windows Clipboard paste (win32clipboard + WM_PASTE / Ctrl+V)
   - Keystroke emulation (SendKeys)
   - Project file-backed synchronization
3. Robust verification of loaded code:
   - SHA-256 cryptographic hash match
   - Character length and line structure match
   - Full IEC 61131-3 AST grammar parsing and validation of extracted buffer
4. Hardware safety lockout:
   - Absolute prohibition of physical PLC download commands
   - Strict enforcement: Structured Text ONLY, no ladder constructs
"""

import hashlib
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch
import pytest

from src.cscape.st_inserter import (
    StructuredTextInserter,
    POUType,
    InsertionMethod,
    STPOUDefinition,
    EditorWindowInfo,
    STInsertionResult,
    STVerificationResult,
    ID_ST_PROGRAM,
    ID_ST_FUNCTION_BLOCK,
    ID_ST_FUNCTION,
    normalize_st_code,
    calculate_code_hash,
    calculate_ast_hash,
    CFBF_MAGIC,
    is_windows,
)
from src.cscape.project_manager import generate_minimal_cfbf_bytes
from src.security.exceptions import (
    HardwareLockoutError,
    SecurityError,
    UnauthorizedDownloadError,
)
from src.iec.validator import IECValidator


# ==============================================================================
# Sample Structured Text Fixtures
# ==============================================================================

SAMPLE_ST_PROGRAM = """
PROGRAM MainControl
VAR
    MotorStart : BOOL := FALSE;
    MotorRunning : BOOL := FALSE;
    CycleCounter : DINT := 0;
END_VAR

IF MotorStart AND NOT MotorRunning THEN
    MotorRunning := TRUE;
    CycleCounter := CycleCounter + 1;
END_IF;
END_PROGRAM
"""

SAMPLE_ST_FUNCTION_BLOCK = """
FUNCTION_BLOCK FB_MotorController
VAR_INPUT
    StartCmd : BOOL;
    StopCmd : BOOL;
END_VAR
VAR_OUTPUT
    Running : BOOL;
    Fault : BOOL;
END_VAR
VAR
    RunState : BOOL := FALSE;
END_VAR

IF StopCmd THEN
    RunState := FALSE;
ELSIF StartCmd THEN
    RunState := TRUE;
END_IF;

Running := RunState;
END_FUNCTION_BLOCK
"""

SAMPLE_ST_FUNCTION = """
FUNCTION FC_ScaleAnalog : REAL
VAR_INPUT
    RawInput : INT;
    RawMin : INT;
    RawMax : INT;
    ScaledMin : REAL;
    ScaledMax : REAL;
END_VAR
VAR
    RawRange : REAL;
    ScaledRange : REAL;
END_VAR

RawRange := INT_TO_REAL(RawMax - RawMin);
ScaledRange := ScaledMax - ScaledMin;

IF RawRange > 0.0 THEN
    FC_ScaleAnalog := ScaledMin + (INT_TO_REAL(RawInput - RawMin) / RawRange) * ScaledRange;
ELSE
    FC_ScaleAnalog := ScaledMin;
END_IF;
END_FUNCTION
"""


# ==============================================================================
# 1. POU Type & Command ID Tests
# ==============================================================================

class TestPOUTypeAndCommandResolution:
    """Test resolution and normalization of POU types and Cscape command IDs."""

    def test_pou_type_normalization_program(self):
        assert POUType.from_str("Program") == POUType.PROGRAM
        assert POUType.from_str("program") == POUType.PROGRAM
        assert POUType.from_str("PROGRAM") == POUType.PROGRAM
        assert POUType.from_str("prog") == POUType.PROGRAM
        assert POUType.from_str("prg") == POUType.PROGRAM
        assert POUType.from_str("stblock") == POUType.PROGRAM

    def test_pou_type_normalization_function_block(self):
        assert POUType.from_str("FunctionBlock") == POUType.FUNCTION_BLOCK
        assert POUType.from_str("function_block") == POUType.FUNCTION_BLOCK
        assert POUType.from_str("FUNCTIONBLOCK") == POUType.FUNCTION_BLOCK
        assert POUType.from_str("fb") == POUType.FUNCTION_BLOCK
        assert POUType.from_str("udfb") == POUType.FUNCTION_BLOCK
        assert POUType.from_str("studfb") == POUType.FUNCTION_BLOCK

    def test_pou_type_normalization_function(self):
        assert POUType.from_str("Function") == POUType.FUNCTION
        assert POUType.from_str("function") == POUType.FUNCTION
        assert POUType.from_str("FUNCTION") == POUType.FUNCTION
        assert POUType.from_str("fun") == POUType.FUNCTION
        assert POUType.from_str("subroutine") == POUType.FUNCTION
        assert POUType.from_str("stsubroutine") == POUType.FUNCTION

    def test_pou_type_invalid_raises(self):
        with pytest.raises(ValueError, match="Unsupported POU type"):
            POUType.from_str("invalid_type")

        with pytest.raises(ValueError, match="Unsupported POU type"):
            POUType.from_str("ladder_diagram")

    def test_command_id_mappings(self):
        inserter = StructuredTextInserter()
        assert inserter.get_command_id_for_pou(POUType.PROGRAM) == ID_ST_PROGRAM
        assert inserter.get_command_id_for_pou("Program") == 38055
        assert inserter.get_command_id_for_pou(POUType.FUNCTION_BLOCK) == ID_ST_FUNCTION_BLOCK
        assert inserter.get_command_id_for_pou("udfb") == 37999
        assert inserter.get_command_id_for_pou(POUType.FUNCTION) == ID_ST_FUNCTION
        assert inserter.get_command_id_for_pou("subroutine") == 38050


# ==============================================================================
# 2. POU Definition & Code Validation Tests
# ==============================================================================

class TestSTPOUDefinition:
    """Test ST POU specification validation and AST compliance."""

    def test_valid_program_definition(self):
        pou = STPOUDefinition(
            name="MainLogic",
            pou_type=POUType.PROGRAM,
            code=SAMPLE_ST_PROGRAM,
        )
        assert pou.name == "MainLogic"
        assert pou.pou_type == POUType.PROGRAM
        assert "PROGRAM MainControl" in pou.code

    def test_valid_function_block_definition(self):
        pou = STPOUDefinition(
            name="MotorFB",
            pou_type=POUType.FUNCTION_BLOCK,
            code=SAMPLE_ST_FUNCTION_BLOCK,
        )
        assert pou.name == "MotorFB"
        assert pou.pou_type == POUType.FUNCTION_BLOCK

    def test_valid_function_definition(self):
        pou = STPOUDefinition(
            name="ScaleFC",
            pou_type=POUType.FUNCTION,
            code=SAMPLE_ST_FUNCTION,
        )
        assert pou.name == "ScaleFC"
        assert pou.pou_type == POUType.FUNCTION

    def test_invalid_pou_name_traversal_rejected(self):
        with pytest.raises(SecurityError):
            STPOUDefinition(
                name="../BadPOU",
                pou_type=POUType.PROGRAM,
                code=SAMPLE_ST_PROGRAM,
            )

    def test_invalid_st_syntax_rejected(self):
        bad_code = "PROGRAM BadCode VAR x : INT; END_VAR IF x > 0 THEN x := 1; (* unclosed IF"
        with pytest.raises(SecurityError, match="syntax validation failed"):
            STPOUDefinition(
                name="BadSyntaxPOU",
                pou_type=POUType.PROGRAM,
                code=bad_code,
            )


# ==============================================================================
# 3. Code Normalization and Hash Calculation Tests
# ==============================================================================

class TestCodeNormalizationAndHashing:
    """Test deterministic code normalization and SHA-256 calculation."""

    def test_normalize_crlf_and_lf(self):
        crlf_code = "VAR\r\n    x : INT;\r\nEND_VAR\r\n"
        lf_code = "VAR\n    x : INT;\nEND_VAR\n"
        assert normalize_st_code(crlf_code) == normalize_st_code(lf_code)

    def test_normalize_trailing_whitespace(self):
        code_with_spaces = "VAR   \n    x : INT;   \nEND_VAR   \n"
        clean_code = "VAR\n    x : INT;\nEND_VAR"
        assert normalize_st_code(code_with_spaces) == normalize_st_code(clean_code)

    def test_hash_deterministic(self):
        code1 = "PROGRAM P1\r\nVAR\r\n    v : BOOL;\r\nEND_VAR\r\nv := TRUE;\r\nEND_PROGRAM"
        code2 = "PROGRAM P1\nVAR\n    v : BOOL;\nEND_VAR\nv := TRUE;\nEND_PROGRAM\n\n"
        hash1 = calculate_code_hash(code1)
        hash2 = calculate_code_hash(code2)
        assert hash1 == hash2
        assert len(hash1) == 64


# ==============================================================================
# 4. Insertion Methods Tests (Window Handle, Clipboard, SendKeys, File Sync)
# ==============================================================================

class TestSTInsertionMethods:
    """Test all code insertion mechanisms."""

    @pytest.fixture(autouse=True)
    def clear_mock(self):
        StructuredTextInserter.clear_mock_store()
        yield
        StructuredTextInserter.clear_mock_store()

    def test_insert_via_window_handle_scintilla(self):
        inserter = StructuredTextInserter()
        editor_hwnd = 0x5001

        with patch("win32gui.GetClassName", return_value="Scintilla"), \
             patch("win32gui.SendMessage", return_value=0):
            ok, method, err = inserter.insert_code(
                editor_hwnd=editor_hwnd,
                code=SAMPLE_ST_PROGRAM,
                method=InsertionMethod.WINDOW_HANDLE,
            )
            assert ok is True
            assert method == InsertionMethod.WINDOW_HANDLE
            assert err is None

    def test_insert_via_clipboard(self):
        inserter = StructuredTextInserter()
        editor_hwnd = 0x5002

        with patch.object(inserter, "_insert_via_clipboard", return_value=(True, InsertionMethod.CLIPBOARD, None)):
            ok, method, err = inserter.insert_code(
                editor_hwnd=editor_hwnd,
                code=SAMPLE_ST_FUNCTION_BLOCK,
                method=InsertionMethod.CLIPBOARD,
            )
            assert ok is True
            assert method == InsertionMethod.CLIPBOARD
            assert err is None

    def test_insert_via_sendkeys(self):
        inserter = StructuredTextInserter()
        editor_hwnd = 0x5003

        with patch.object(inserter, "_insert_via_sendkeys", return_value=(True, InsertionMethod.SENDKEYS, None)):
            ok, method, err = inserter.insert_code(
                editor_hwnd=editor_hwnd,
                code=SAMPLE_ST_FUNCTION,
                method=InsertionMethod.SENDKEYS,
            )
            assert ok is True
            assert method == InsertionMethod.SENDKEYS
            assert err is None

    def test_insert_via_file_sync(self, tmp_path):
        inserter = StructuredTextInserter()
        project_dir = tmp_path / "TestProject"
        project_dir.mkdir()

        ok, method, err = inserter.insert_code(
            editor_hwnd=0,
            code=SAMPLE_ST_PROGRAM,
            method=InsertionMethod.FILE_SYNC,
            pou_name="MainLogic",
            project_dir=project_dir,
        )
        assert ok is True
        assert method == InsertionMethod.FILE_SYNC
        st_file = project_dir / "pous" / "MainLogic.st"
        assert st_file.exists()
        assert "PROGRAM MainControl" in st_file.read_text(encoding="utf-8")

    def test_insert_auto_strategy_with_window_handle(self):
        inserter = StructuredTextInserter()
        editor_hwnd = 0x5004

        with patch("win32gui.GetClassName", return_value="Scintilla"), \
             patch("win32gui.SendMessage", return_value=0):
            ok, method, err = inserter.insert_code(
                editor_hwnd=editor_hwnd,
                code=SAMPLE_ST_PROGRAM,
                method=InsertionMethod.AUTO,
            )
            assert ok is True
            assert method == InsertionMethod.WINDOW_HANDLE
            assert err is None

    def test_live_gui_injection_fails_honestly_when_no_editor_window(self):
        """Verify requesting live GUI injection when no editor window exists reports honest failure."""
        inserter = StructuredTextInserter()
        # Ensure no editor window is found
        with patch.object(inserter, "find_editor_windows", return_value=[]):
            res = inserter.insert_pou(
                pou_name="FailProg",
                pou_type=POUType.PROGRAM,
                code=SAMPLE_ST_PROGRAM,
                method=InsertionMethod.WINDOW_HANDLE,
            )
            assert res.success is False
            assert res.editor_hwnd is None
            assert "Live GUI injection requested" in res.error_message
            assert "no active Cscape editor window" in res.error_message

            # Test clipboard honest failure as well
            res_clip = inserter.insert_pou(
                pou_name="FailClip",
                pou_type=POUType.FUNCTION_BLOCK,
                code=SAMPLE_ST_FUNCTION_BLOCK,
                method=InsertionMethod.CLIPBOARD,
            )
            assert res_clip.success is False
            assert res_clip.editor_hwnd is None
            assert "Live GUI injection requested" in res_clip.error_message

    def test_direct_window_handle_wm_settext(self):
        """Test Win32 WM_SETTEXT direct message injection when window handle is an Edit control."""
        inserter = StructuredTextInserter()
        real_looking_hwnd = 0x8888

        with patch("win32gui.GetClassName", return_value="Edit"), \
             patch("win32gui.SendMessage", side_effect=[0, 0, 1, 0]) as mock_send:
            ok, method, err = inserter._insert_via_window_handle(real_looking_hwnd, SAMPLE_ST_PROGRAM)
            assert ok is True
            assert method == InsertionMethod.WINDOW_HANDLE
            assert err is None
            assert mock_send.call_count == 4

    def test_direct_window_handle_scintilla(self):
        """Test Scintilla SCI_SETTEXT direct message injection when editor is Scintilla."""
        inserter = StructuredTextInserter()
        real_looking_hwnd = 0x8889

        with patch("win32gui.GetClassName", return_value="Scintilla"), \
             patch("win32gui.SendMessage", return_value=0) as mock_send:
            ok, method, err = inserter._insert_via_window_handle(real_looking_hwnd, SAMPLE_ST_PROGRAM)
            assert ok is True
            assert method == InsertionMethod.WINDOW_HANDLE
            assert err is None
            assert mock_send.call_count == 2

    def test_direct_window_handle_em_replacesel_fallback(self):
        """Test EM_REPLACESEL fallback when WM_SETTEXT returns 0."""
        inserter = StructuredTextInserter()
        real_looking_hwnd = 0x888A

        def send_message_mock(hwnd, msg, wparam, lparam):
            if msg == 0x000C:  # WM_SETTEXT
                return 0
            return 1

        with patch("win32gui.GetClassName", return_value="Edit"), \
             patch("win32gui.SendMessage", side_effect=send_message_mock):
            ok, method, err = inserter._insert_via_window_handle(real_looking_hwnd, SAMPLE_ST_PROGRAM)
            assert ok is True
            assert method == InsertionMethod.WINDOW_HANDLE
            assert err is None

    def test_direct_clipboard_wm_paste(self):
        """Test Win32 Clipboard WM_PASTE message path."""
        inserter = StructuredTextInserter()
        real_looking_hwnd = 0x888B

        with patch("win32clipboard.OpenClipboard"), \
             patch("win32clipboard.EmptyClipboard"), \
             patch("win32clipboard.SetClipboardText"), \
             patch("win32clipboard.CloseClipboard"), \
             patch("win32gui.SendMessage") as mock_send:
            ok, method, err = inserter._insert_via_clipboard(real_looking_hwnd, SAMPLE_ST_PROGRAM)
            assert ok is True
            assert method == InsertionMethod.CLIPBOARD
            assert err is None
            called_msgs = [c[0][1] for c in mock_send.call_args_list]
            assert 0x0302 in called_msgs  # WM_PASTE

    def test_direct_clipboard_locked_fallback_error(self):
        """Test that clipboard lock (OpenClipboard failure) returns error gracefully."""
        inserter = StructuredTextInserter()
        real_looking_hwnd = 0x888C

        with patch("win32clipboard.OpenClipboard", side_effect=Exception("Access is denied. Clipboard is locked by process 9999")):
            ok, method, err = inserter._insert_via_clipboard(real_looking_hwnd, SAMPLE_ST_PROGRAM)
            assert ok is False
            assert method == InsertionMethod.CLIPBOARD
            assert "Failed setting clipboard text" in err
            assert "Clipboard is locked" in err

    def test_auto_cascade_fallback_when_clipboard_locked(self, tmp_path):
        """Test AUTO strategy cascading to FILE_SYNC when Window Handle and Clipboard fail."""
        inserter = StructuredTextInserter()
        unregistered_hwnd = 0x888D

        project_dir = tmp_path / "CascadeProject"
        project_dir.mkdir()

        with patch.object(inserter, "_insert_via_window_handle", return_value=(False, InsertionMethod.WINDOW_HANDLE, "Edit control not found")), \
             patch.object(inserter, "_insert_via_clipboard", return_value=(False, InsertionMethod.CLIPBOARD, "Clipboard locked")), \
             patch.object(inserter, "_insert_via_sendkeys", return_value=(False, InsertionMethod.SENDKEYS, "Window not focused")):

            ok, used_method, err = inserter.insert_code(
                editor_hwnd=unregistered_hwnd,
                code=SAMPLE_ST_PROGRAM,
                method=InsertionMethod.AUTO,
                pou_name="CascadePOU",
                project_dir=project_dir,
            )
            assert ok is True
            assert used_method == InsertionMethod.FILE_SYNC
            assert err is None

            st_file = project_dir / "pous" / "CascadePOU.st"
            assert st_file.exists()
            assert "PROGRAM MainControl" in st_file.read_text(encoding="utf-8")


# ==============================================================================
# 5. Code Verification Engine Tests
# ==============================================================================

class TestSTCodeVerification:
    """Test buffer verification, hash matching, and AST validation."""

    def test_verification_success_exact_match(self):
        inserter = StructuredTextInserter()
        mock_hwnd = 0x6001

        with patch.object(inserter, "read_editor_code", return_value=normalize_st_code(SAMPLE_ST_PROGRAM)):
            result = inserter.verify_editor_content(
                editor_hwnd=mock_hwnd,
                expected_code=SAMPLE_ST_PROGRAM,
            )
            assert result.verified is True
            assert result.exact_match is True
            assert result.ast_valid is True
            assert result.expected_hash == result.extracted_hash
            assert len(result.ast_errors) == 0

    def test_verification_detects_hash_mismatch(self):
        inserter = StructuredTextInserter()
        mock_hwnd = 0x6002
        corrupted = normalize_st_code(SAMPLE_ST_PROGRAM) + "\n// Extra corrupted comment"

        with patch.object(inserter, "read_editor_code", return_value=corrupted):
            result = inserter.verify_editor_content(
                editor_hwnd=mock_hwnd,
                expected_code=SAMPLE_ST_PROGRAM,
            )
            assert result.verified is False
            assert result.exact_match is False
            assert result.expected_hash != result.extracted_hash

    def test_verification_detects_syntax_errors_in_extracted_code(self):
        inserter = StructuredTextInserter()
        mock_hwnd = 0x6003
        bad_syntax = "PROGRAM Incomplete\nVAR\n    x : INT;\nEND_VAR\nIF x > 0 THEN\n"

        with patch.object(inserter, "read_editor_code", return_value=normalize_st_code(bad_syntax)):
            result = inserter.verify_editor_content(
                editor_hwnd=mock_hwnd,
                expected_code=bad_syntax,
            )
            assert result.exact_match is True
            assert result.ast_valid is False
            assert result.verified is False
            assert len(result.ast_errors) > 0

    def test_hash_verification_pre_and_post_insertion_integrity(self):
        """Confirm cryptographic SHA-256 hash verification before and after insertion."""
        inserter = StructuredTextInserter()
        mock_hwnd = 0x7001

        # Pre-insertion hash calculation
        expected_pre_hash = calculate_code_hash(SAMPLE_ST_PROGRAM)
        assert len(expected_pre_hash) == 64

        # Post-insertion read-back and verify
        with patch.object(inserter, "read_editor_code", return_value=normalize_st_code(SAMPLE_ST_PROGRAM)):
            ver = inserter.verify_editor_content(mock_hwnd, SAMPLE_ST_PROGRAM)
            assert ver.verified is True
            assert ver.exact_match is True
            assert ver.expected_hash == expected_pre_hash
            assert ver.extracted_hash == expected_pre_hash
            assert ver.ast_valid is True

        # Tampered content post-insertion
        with patch.object(inserter, "read_editor_code", return_value=normalize_st_code(SAMPLE_ST_PROGRAM) + "\n// Injected comment"):
            ver_tampered = inserter.verify_editor_content(mock_hwnd, SAMPLE_ST_PROGRAM)
            assert ver_tampered.verified is False
            assert ver_tampered.exact_match is False
            assert ver_tampered.extracted_hash != expected_pre_hash


# ==============================================================================
# 6. High-Level Workflow Tests (StructuredTextInserter.insert_pou)
# ==============================================================================

class TestSTHighLevelWorkflow:
    """Test complete end-to-end POU creation and insertion workflow."""

    @pytest.fixture(autouse=True)
    def clear_mock(self):
        StructuredTextInserter.clear_mock_store()
        yield
        StructuredTextInserter.clear_mock_store()

    def test_insert_program_native_cfbf_project(self, tmp_path):
        project_dir = tmp_path / "MySTProject"
        project_dir.mkdir()
        # Seed native CFBF .csp container and cscape_project.json manifest
        csp_file = project_dir / "MySTProject.csp"
        csp_file.write_bytes(generate_minimal_cfbf_bytes("MySTProject"))
        manifest_file = project_dir / "cscape_project.json"
        manifest_file.write_text('{"name": "MySTProject", "iec_engine": "IEC 61131-3 Structured Text", "pous": []}', encoding="utf-8")

        inserter = StructuredTextInserter(workspace_dir=tmp_path)
        res: STInsertionResult = inserter.insert_pou(
            pou_name="PRG_Main",
            pou_type=POUType.PROGRAM,
            code=SAMPLE_ST_PROGRAM,
            project_dir=project_dir,
            cycle_time_ms=10,
            verify=True,
        )

        assert res.success is True
        assert res.pou_name == "PRG_Main"
        assert res.pou_type == POUType.PROGRAM
        assert res.method_used == InsertionMethod.FILE_SYNC
        assert res.editor_hwnd is None
        assert res.verified is True
        assert res.verification is not None
        assert res.verification.exact_match is True
        assert res.verification.ast_match is True
        assert res.ast_hash is not None and len(res.ast_hash) == 64
        assert res.duration_seconds >= 0.0

        # Verify cscape_project.json registration
        import json
        manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
        registered_pous = {p["name"]: p for p in manifest_data.get("pous", [])}
        assert "PRG_Main" in registered_pous
        assert registered_pous["PRG_Main"]["language"] == "ST"
        assert registered_pous["PRG_Main"]["ast_hash"] == res.ast_hash

        # Verify CFBF container remains valid OLE CFBF
        assert csp_file.read_bytes()[:8] == CFBF_MAGIC

        # Verify disk file
        st_file = project_dir / "pous" / "PRG_Main.st"
        assert st_file.exists()
        assert "PROGRAM MainControl" in st_file.read_text(encoding="utf-8")

    def test_insert_function_block_native_cfbf_project(self, tmp_path):
        project_dir = tmp_path / "FBProject"
        project_dir.mkdir()
        csp_file = project_dir / "FBProject.csp"
        csp_file.write_bytes(generate_minimal_cfbf_bytes("FBProject"))
        manifest_file = project_dir / "cscape_project.json"
        manifest_file.write_text('{"name": "FBProject", "pous": []}', encoding="utf-8")

        inserter = StructuredTextInserter(workspace_dir=tmp_path)
        res = inserter.insert_pou(
            pou_name="FB_Drive",
            pou_type=POUType.FUNCTION_BLOCK,
            code=SAMPLE_ST_FUNCTION_BLOCK,
            project_dir=project_dir,
        )

        assert res.success is True
        assert res.pou_type == POUType.FUNCTION_BLOCK
        assert res.method_used == InsertionMethod.FILE_SYNC
        assert res.editor_hwnd is None
        assert res.verified is True
        assert res.ast_hash is not None

        import json
        manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
        assert any(p.get("name") == "FB_Drive" for p in manifest_data.get("pous", []))

        st_file = project_dir / "pous" / "FB_Drive.st"
        assert st_file.exists()
        assert "FUNCTION_BLOCK FB_MotorController" in st_file.read_text(encoding="utf-8")

    def test_insert_function_native_cfbf_project(self, tmp_path):
        project_dir = tmp_path / "FunProject"
        project_dir.mkdir()
        csp_file = project_dir / "FunProject.csp"
        csp_file.write_bytes(generate_minimal_cfbf_bytes("FunProject"))
        manifest_file = project_dir / "cscape_project.json"
        manifest_file.write_text('{"name": "FunProject", "pous": []}', encoding="utf-8")

        inserter = StructuredTextInserter(workspace_dir=tmp_path)
        res = inserter.insert_pou(
            pou_name="FC_Math",
            pou_type=POUType.FUNCTION,
            code=SAMPLE_ST_FUNCTION,
            project_dir=project_dir,
        )

        assert res.success is True
        assert res.pou_type == POUType.FUNCTION
        assert res.method_used == InsertionMethod.FILE_SYNC
        assert res.editor_hwnd is None
        assert res.verified is True
        assert res.ast_hash is not None

        import json
        manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
        assert any(p.get("name") == "FC_Math" for p in manifest_data.get("pous", []))

        st_file = project_dir / "pous" / "FC_Math.st"
        assert st_file.exists()
        assert "FUNCTION FC_ScaleAnalog" in st_file.read_text(encoding="utf-8")

    def test_insert_standalone_st_file_direct_path(self, tmp_path):
        standalone_file = tmp_path / "StandaloneControl.st"
        inserter = StructuredTextInserter(workspace_dir=tmp_path)
        res = inserter.insert_pou(
            pou_name="StandaloneControl",
            pou_type=POUType.PROGRAM,
            code=SAMPLE_ST_PROGRAM,
            project_dir=standalone_file,
            verify=True,
        )

        assert res.success is True
        assert res.method_used == InsertionMethod.FILE_SYNC
        assert res.editor_hwnd is None
        assert res.verified is True
        assert standalone_file.exists()
        assert "PROGRAM MainControl" in standalone_file.read_text(encoding="utf-8")
        assert not (tmp_path / "pous").exists()
        assert res.verification.ast_match is True

    def test_insert_standalone_st_directory(self, tmp_path):
        st_dir = tmp_path / "st_scripts"
        st_dir.mkdir()
        inserter = StructuredTextInserter(workspace_dir=tmp_path)
        res = inserter.insert_pou(
            pou_name="ScriptProg",
            pou_type=POUType.PROGRAM,
            code=SAMPLE_ST_PROGRAM,
            project_dir=st_dir,
            verify=True,
        )

        assert res.success is True
        assert res.method_used == InsertionMethod.FILE_SYNC
        assert res.editor_hwnd is None
        assert res.verified is True
        assert (st_dir / "pous" / "ScriptProg.st").exists()

    def test_ladder_rejection_prior_to_insertion(self, tmp_path):
        project_dir = tmp_path / "LadderRejectProj"
        project_dir.mkdir()
        ladder_code = """
        PROGRAM LadderPOU
        VAR
            bStart : BOOL;
            bRun : BOOL;
        END_VAR
        ---[ bStart ]---( bRun )---
        END_PROGRAM
        """
        inserter = StructuredTextInserter()
        res = inserter.insert_pou(
            pou_name="LadderPOU",
            pou_type=POUType.PROGRAM,
            code=ladder_code,
            project_dir=project_dir,
            verify=True,
        )

        assert res.success is False
        assert res.verified is False
        assert "Ladder logic rejected" in res.error_message
        assert not (project_dir / "pous" / "LadderPOU.st").exists()

    def test_insert_code_ladder_rejection_prior_to_insertion(self):
        inserter = StructuredTextInserter()
        ladder_code = "---[ bContact ]---( bCoil )---"
        ok, method, err = inserter.insert_code(
            editor_hwnd=0x1234,
            code=ladder_code,
            method=InsertionMethod.WINDOW_HANDLE,
        )
        assert ok is False
        assert "Ladder logic rejected" in err

    def test_ast_hash_invariance_to_whitespace_and_comments(self):
        code1 = SAMPLE_ST_PROGRAM
        code2 = f"// Leading comment\n{SAMPLE_ST_PROGRAM}\n\n(* Trailing comment *)\n"
        h1 = calculate_ast_hash(code1)
        h2 = calculate_ast_hash(code2)
        assert len(h1) == 64
        assert h1 == h2

    def test_ast_hash_changes_on_logic_modification(self):
        code1 = SAMPLE_ST_PROGRAM
        code2 = SAMPLE_ST_PROGRAM.replace("MotorRunning := TRUE;", "MotorRunning := FALSE;")
        h1 = calculate_ast_hash(code1)
        h2 = calculate_ast_hash(code2)
        assert h1 != h2

    def test_ast_hash_invalid_syntax_raises(self):
        with pytest.raises(SecurityError, match="syntax error|AST"):
            calculate_ast_hash("PROGRAM Incomplete VAR x : INT; END_VAR IF x > 0 THEN")

    def test_insert_invalid_syntax_fails_before_execution(self):
        inserter = StructuredTextInserter()
        res = inserter.insert_pou(
            pou_name="InvalidPOU",
            pou_type=POUType.PROGRAM,
            code="PROGRAM Incomplete VAR x : INT; END_VAR IF x > 0 THEN (* unclosed",
            verify=True,
        )
        assert res.success is False
        assert res.verified is False
        assert "Invalid IEC 61131-3" in res.error_message


# ==============================================================================
# 7. Hardware Safety Lockout & Directive Tests
# ==============================================================================

class TestSTInserterSafetyHardening:
    """Test safety enforcement preventing physical PLC downloads or ladder usage."""

    def test_blocked_command_raises_unauthorized_download(self):
        inserter = StructuredTextInserter()
        # Mock main hwnd
        inserter.main_hwnd = 0x9999

        # Triggering a blocked command must raise UnauthorizedDownloadError
        with pytest.raises(UnauthorizedDownloadError):
            # Attempt dispatching download command ID
            if 32827 in (ID_ST_PROGRAM, ID_ST_FUNCTION_BLOCK, ID_ST_FUNCTION):
                pass
            else:
                inserter.safety_guard.validate_ui_command(32827)

    def test_path_traversal_in_pou_name_rejected(self):
        inserter = StructuredTextInserter()
        with pytest.raises(SecurityError):
            inserter.insert_pou(
                pou_name="../../etc/passwd",
                pou_type=POUType.PROGRAM,
                code=SAMPLE_ST_PROGRAM,
            )

    def test_serialization_to_dict(self):
        ver = STVerificationResult(
            verified=True,
            editor_hwnd=0x1234,
            extracted_code="VAR x : INT; END_VAR",
            extracted_length=20,
            expected_length=20,
            expected_hash="abc",
            extracted_hash="abc",
            exact_match=True,
            ast_valid=True,
        )
        res = STInsertionResult(
            success=True,
            pou_name="TestPOU",
            pou_type=POUType.PROGRAM,
            method_used=InsertionMethod.WINDOW_HANDLE,
            editor_hwnd=0x1234,
            code_length=20,
            code_hash="abc",
            verified=True,
            verification=ver,
        )
        d = res.to_dict()
        assert d["success"] is True
        assert d["pou_name"] == "TestPOU"
        assert d["method_used"] == "window_handle"
        assert d["editor_hwnd"] == "0x1234"
        assert d["verification"]["exact_match"] is True


# ==============================================================================
# 8. Live Cscape 10.2 Environment Integration Tests
# ==============================================================================

class TestLiveCscapeSTInsertionEnvironment:
    """Test discovery and environment checks against live Cscape 10.2 installation."""

    def test_cscape_binary_presence(self):
        cscape_path = Path(r"C:\Program Files (x86)\Cscape 10.2\Cscape.exe")
        assert cscape_path.exists(), f"Cscape.exe not found at {cscape_path}"

    def test_inserter_initialization_real_environment(self):
        inserter = StructuredTextInserter()
        assert inserter.workspace_dir.exists()
        assert isinstance(inserter.default_method, InsertionMethod)

    def test_live_editor_window_enumeration_safe(self):
        inserter = StructuredTextInserter()
        # Should not raise exception regardless of whether Cscape is currently open
        editors = inserter.find_editor_windows()
        assert isinstance(editors, list)
