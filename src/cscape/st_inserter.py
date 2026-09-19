"""Horner Cscape 10.2 Structured Text POU Inserter.

Provides automated, robust insertion of IEC 61131-3 Structured Text (ST) POUs
(Program, FunctionBlock, Function) into live or headless Horner Cscape 10.2:
1. Automate adding a new Structured Text POU (Program/FunctionBlock/Function) via
   Cscape MFC Command IDs, Ribbon commands, and creation dialogs.
2. Insert IEC 61131-3 Structured Text code into Cscape's ST editor via:
   - Window handle direct injection (WM_SETTEXT / EM_REPLACESEL / Scintilla)
   - Windows Clipboard paste (win32clipboard + WM_PASTE / Ctrl+V)
   - Keystroke emulation (SendKeys)
   - Project file-backed synchronization
3. Read back and verify that the code is properly and accurately loaded into the editor,
   including SHA-256 hash comparison and IEC 61131-3 AST validation.
4. Enforce strict safety directives: Structured Text ONLY, NO physical PLC download.
"""

from __future__ import annotations

import enum
import hashlib
import json
import logging
import os
import re
import sys
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

# Security and validation imports
from ..security.exceptions import (
    HardwareLockoutError,
    SecurityError,
    UnauthorizedDownloadError,
)
from ..security.guard import SafetyGuard, SecurityGuard
from ..iec.validator import IECValidator
from ..automation.ui_automation import (
    BLOCKED_COMMAND_IDS,
    ID_CONTROLLER_DOWNLOAD,
    ID_PLC_DOWNLOAD,
)

logger = logging.getLogger(__name__)

# ==============================================================================
# Win32 Constants & Message Identifiers
# ==============================================================================

# Standard Win32 Messages
WM_NULL: int = 0x0000
WM_SETTEXT: int = 0x000C
WM_GETTEXT: int = 0x000D
WM_GETTEXTLENGTH: int = 0x000E
WM_CLOSE: int = 0x0010
WM_SETFOCUS: int = 0x0007
WM_COMMAND: int = 0x0111
WM_PASTE: int = 0x0302
WM_CLEAR: int = 0x0303
WM_CHAR: int = 0x0102
WM_KEYDOWN: int = 0x0100
WM_KEYUP: int = 0x0101

# Edit Control Messages
EM_SETSEL: int = 0x00B1
EM_REPLACESEL: int = 0x00C2
EM_GETSEL: int = 0x00B0
EM_GETLINECOUNT: int = 0x00BA
EM_SETMODIFY: int = 0x00B9
EM_GETMODIFY: int = 0x00B8

# Button Messages
BM_CLICK: int = 0x00F5
BM_SETCHECK: int = 0x00F1

# Scintilla Editor Messages (for Scintilla-based code editors)
SCI_SETTEXT: int = 2181
SCI_GETTEXT: int = 2182
SCI_GETTEXTLENGTH: int = 2183
SCI_SELECTALL: int = 2013
SCI_PASTE: int = 2179
SCI_CLEARALL: int = 2004
SCI_ADDTEXT: int = 2001
SCI_GETLINECOUNT: int = 2154

# Dialog Control IDs
ID_OK: int = 1
ID_CANCEL: int = 2

# Cscape MDI & Navigation Window IDs
ID_MDI_CLIENT: int = 59648               # 0xE900 (AFX_IDW_PANE_FIRST / MDIClient)
ID_PROJECT_NAVIGATOR: int = 45012        # Project Navigator dockable bar
ID_PROJECT_NAVIGATOR_TREE: int = 300     # SysTreeView32 inside Project Navigator
ID_PROGRAM_VARIABLES: int = 38053        # Program Variables window
ID_OUTPUT_WINDOW: int = 45011            # Output/Build window

# Cscape MFC Command IDs for IEC 61131 Structured Text POUs
# Discovered from Cscape 10.2 RT_STRING / RT_MENU binary resources:
ID_ST_PROGRAM: int = 38055          # 0x94A7: "IEC Structured Text Block" (ST Block)
ID_ST_FUNCTION_BLOCK: int = 37999   # 0x946F: "IEC Structured Text UDFB Block" (ST UDFB)
ID_ST_FUNCTION: int = 38050         # 0x94A2: "IEC Structured Text Subroutine Block" (ST Subroutine)

# OLE Compound File Binary Format (CFBF) Magic Header
CFBF_MAGIC: bytes = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


# ==============================================================================
# Enumerations and Data Models
# ==============================================================================

class POUType(str, enum.Enum):
    """IEC 61131-3 Program Organization Unit (POU) types supported by Cscape."""
    PROGRAM = "Program"
    FUNCTION_BLOCK = "FunctionBlock"
    FUNCTION = "Function"

    @classmethod
    def from_str(cls, value: str) -> "POUType":
        """Normalize a string or enum value to POUType."""
        if isinstance(value, cls):
            return value
        val = str(value).strip().lower().replace("_", "").replace(" ", "").replace("-", "")
        if val in ("program", "prog", "prg", "stblock"):
            return cls.PROGRAM
        elif val in ("functionblock", "fb", "udfb", "studfb", "userdefinedfunctionblock"):
            return cls.FUNCTION_BLOCK
        elif val in ("function", "fun", "subroutine", "sub", "stsubroutine"):
            return cls.FUNCTION
        raise ValueError(
            f"Unsupported POU type: '{value}'. Must be one of: Program, FunctionBlock, Function."
        )


class InsertionMethod(str, enum.Enum):
    """Strategy for inserting Structured Text code into the editor."""
    WINDOW_HANDLE = "window_handle"  # Direct Win32 / Scintilla message injection
    CLIPBOARD = "clipboard"          # Windows Clipboard paste (win32clipboard + WM_PASTE)
    SENDKEYS = "sendkeys"            # Keystroke typing emulation (pywinauto / uiautomation)
    FILE_SYNC = "file_sync"          # Direct file update in project structure with live sync
    AUTO = "auto"                    # Intelligent priority order: Handle -> Clipboard -> SendKeys -> Sync


@dataclass
class STPOUDefinition:
    """Specification of an IEC 61131-3 Structured Text POU to insert."""
    name: str
    pou_type: POUType
    code: str
    description: str = ""
    cycle_time_ms: int = 10
    inputs: list[dict[str, str]] = field(default_factory=list)
    outputs: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.pou_type = POUType.from_str(self.pou_type)
        self.name = SafetyGuard.validate_pou_name(self.name)
        # Enforce pure ST and reject ladder logic constructs prior to insertion
        from .st_ld_interop import STLadderInteropGuard, LadderConstructRejectedError
        try:
            STLadderInteropGuard.enforce_st_code(self.code)
        except LadderConstructRejectedError as lre:
            raise SecurityError(f"Ladder logic rejected for '{self.name}': {lre}") from lre
        # Validate ST code syntax
        val_result = IECValidator.validate(self.code)
        if not val_result["valid"]:
            errors = "; ".join(val_result["errors"])
            raise SecurityError(f"IEC 61131-3 syntax validation failed for '{self.name}': {errors}")
        # Validate SHA-256 AST hash calculation prior to insertion
        try:
            calculate_ast_hash(self.code)
        except Exception as e:
            raise SecurityError(f"AST validation/hashing failed for '{self.name}': {e}") from e


@dataclass
class EditorWindowInfo:
    """Details of a detected Cscape ST Editor window."""
    hwnd: int
    class_name: str
    title: str
    pou_name: str
    pou_type: POUType
    parent_hwnd: int
    is_visible: bool
    control_type: str = "edit"  # "edit", "scintilla", "richedit", "custom"
    rect: Optional[tuple[int, int, int, int]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "hwnd": self.hwnd,
            "hex_hwnd": hex(self.hwnd),
            "class_name": self.class_name,
            "title": self.title,
            "pou_name": self.pou_name,
            "pou_type": self.pou_type.value,
            "parent_hwnd": self.parent_hwnd,
            "is_visible": self.is_visible,
            "control_type": self.control_type,
            "rect": self.rect,
        }


@dataclass
class STVerificationResult:
    """Outcome of verifying code loaded in the ST editor."""
    verified: bool
    editor_hwnd: Optional[int]
    extracted_code: str
    extracted_length: int
    expected_length: int
    expected_hash: str
    extracted_hash: str
    exact_match: bool
    ast_valid: bool
    ast_errors: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    expected_ast_hash: Optional[str] = None
    extracted_ast_hash: Optional[str] = None
    ast_match: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "editor_hwnd": hex(self.editor_hwnd) if self.editor_hwnd else None,
            "extracted_length": self.extracted_length,
            "expected_length": self.expected_length,
            "expected_hash": self.expected_hash,
            "extracted_hash": self.extracted_hash,
            "exact_match": self.exact_match,
            "ast_valid": self.ast_valid,
            "ast_errors": self.ast_errors,
            "diagnostics": self.diagnostics,
            "expected_ast_hash": self.expected_ast_hash,
            "extracted_ast_hash": self.extracted_ast_hash,
            "ast_match": self.ast_match,
        }


@dataclass
class STInsertionResult:
    """Complete outcome of a POU creation and code insertion operation."""
    success: bool
    pou_name: str
    pou_type: POUType
    method_used: InsertionMethod
    editor_hwnd: Optional[int]
    code_length: int
    code_hash: str
    verified: bool
    verification: Optional[STVerificationResult] = None
    file_path: Optional[str] = None
    duration_seconds: float = 0.0
    error_message: Optional[str] = None
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    ast_hash: Optional[str] = None
    storage_mode: str = "staging"
    is_staging: bool = True
    is_native_persisted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "pou_name": self.pou_name,
            "pou_type": self.pou_type.value,
            "method_used": self.method_used.value,
            "editor_hwnd": hex(self.editor_hwnd) if self.editor_hwnd else None,
            "code_length": self.code_length,
            "code_hash": self.code_hash,
            "ast_hash": self.ast_hash,
            "storage_mode": self.storage_mode,
            "is_staged": self.is_staging,
            "is_native_persisted": self.is_native_persisted,
            "verified": self.verified,
            "verification": self.verification.to_dict() if self.verification else None,
            "file_path": self.file_path,
            "duration_seconds": round(self.duration_seconds, 4),
            "error_message": self.error_message,
            "timestamp": self.timestamp,
        }


# ==============================================================================
# Helper Utilities
# ==============================================================================

def is_windows() -> bool:
    """Return True if running on native Windows."""
    return sys.platform == "win32" or os.name == "nt"


def normalize_st_code(code: str) -> str:
    """Normalize line endings to standard Unix LF and trim trailing whitespace per line."""
    lines = [line.rstrip() for line in code.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    # Strip empty lines from start and end
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def calculate_code_hash(code: str) -> str:
    """Calculate normalized SHA-256 hash of Structured Text code."""
    normalized = normalize_st_code(code).encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def calculate_ast_hash(code: str) -> str:
    """Calculate normalized SHA-256 hash of the IEC 61131-3 Abstract Syntax Tree (AST).

    Parses the Structured Text into an IEC 61131-3 AST, strips source-code location
    metadata (line/col numbers) to remain invariant to comment and formatting variations,
    and returns the deterministic SHA-256 hex digest of the canonical AST structure.

    If AST parsing fails, raises SecurityError.
    """
    from ..iec.parser import Parser, ParseError
    clean_code = normalize_st_code(code)
    try:
        parser = Parser.from_source(clean_code)
        ast = parser.parse()
    except ParseError as pe:
        raise SecurityError(f"IEC 61131-3 syntax error during AST parsing: {pe}") from pe
    except Exception as ex:
        raise SecurityError(f"AST generation failed: {ex}") from ex

    def _strip_loc(node_data: Any) -> Any:
        if isinstance(node_data, dict):
            return {k: _strip_loc(v) for k, v in node_data.items() if k != "loc"}
        elif isinstance(node_data, list):
            return [_strip_loc(elem) for elem in node_data]
        return node_data

    canonical_ast = _strip_loc(ast.to_dict())
    canonical_bytes = json.dumps(canonical_ast, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


# ==============================================================================
# Structured Text Inserter Class
# ==============================================================================

class StructuredTextInserter:
    """Automates Structured Text POU insertion into live and headless Cscape 10.2.

    Features:
    1. Automated command dispatch to create new Structured Text POUs
       (Program, FunctionBlock, Function) using verified MFC Command IDs.
    2. Multi-tier code injection supporting window handle messages,
       Windows clipboard paste, keystroke emulation, and file synchronization.
    3. Rigorous verification reading back buffer content and performing
       cryptographic hash and AST grammar validation.
    4. Hardware safety lockout: blocks any physical PLC download or hardware communication.
    """


    def __init__(
        self,
        main_hwnd: Optional[int] = None,
        cscape_pid: Optional[int] = None,
        workspace_dir: Optional[Union[str, Path]] = None,
        default_method: InsertionMethod = InsertionMethod.AUTO,
    ) -> None:
        self.main_hwnd = main_hwnd
        self.cscape_pid = cscape_pid
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path(r"C:\HornerAI\horner-cscape-mcp")
        self.default_method = default_method
        self.safety_guard = SecurityGuard()

        # Try to resolve running Cscape window if not explicitly provided
        if not self.main_hwnd and is_windows():
            self._auto_discover_cscape()

    def _auto_discover_cscape(self) -> None:
        """Attempt to find active Cscape main window and process ID."""
        try:
            import win32gui
            import win32process
            import psutil

            for proc in psutil.process_iter(["pid", "name"]):
                if "cscape" in proc.info["name"].lower():
                    self.cscape_pid = proc.info["pid"]
                    break

            def enum_cb(hwnd: int, _: Any) -> None:
                if win32gui.IsWindow(hwnd):
                    cls = win32gui.GetClassName(hwnd)
                    if cls.startswith("Afx:") and "cscape" in win32gui.GetWindowText(hwnd).lower():
                        self.main_hwnd = hwnd

            win32gui.EnumWindows(enum_cb, None)
        except Exception as e:
            logger.debug("Auto-discovery of Cscape window skipped: %s", e)

    # --------------------------------------------------------------------------
    # 1. POU Addition Automation
    # --------------------------------------------------------------------------

    def get_command_id_for_pou(self, pou_type: Union[POUType, str]) -> int:
        """Resolve the Cscape MFC Command ID for the requested POU type."""
        ptype = POUType.from_str(pou_type)
        if ptype == POUType.PROGRAM:
            return ID_ST_PROGRAM
        elif ptype == POUType.FUNCTION_BLOCK:
            return ID_ST_FUNCTION_BLOCK
        elif ptype == POUType.FUNCTION:
            return ID_ST_FUNCTION
        raise ValueError(f"Unknown POU type: {pou_type}")

    def add_new_pou_command(self, pou_type: Union[POUType, str]) -> bool:
        """Trigger Cscape's internal command to create a new POU of the given type.

        Dispatches WM_COMMAND with the exact command ID to Cscape's main window.
        """
        ptype = POUType.from_str(pou_type)
        cmd_id = self.get_command_id_for_pou(ptype)

        # Enforce safety guardrail: make sure this command is not blocked
        if cmd_id in (ID_CONTROLLER_DOWNLOAD, ID_PLC_DOWNLOAD):
            raise UnauthorizedDownloadError("Attempted to dispatch prohibited download command.")

        if not self.main_hwnd or not is_windows():
            logger.info("Live Cscape window not present; recording POU command trigger: %s (%s)", ptype, cmd_id)
            return True

        import win32con
        import win32gui

        logger.info("Posting WM_COMMAND (0x%X / %d) for POU type '%s' to hwnd 0x%X", cmd_id, cmd_id, ptype.value, self.main_hwnd)
        win32gui.PostMessage(self.main_hwnd, win32con.WM_COMMAND, cmd_id, 0)
        time.sleep(0.5)

        # Handle any creation wizard / dialog that pops up (e.g. #32770)
        self._handle_pou_creation_modals()
        return True

    def _handle_pou_creation_modals(self, timeout: float = 3.0) -> bool:
        """Detect and dismiss any POU creation modal dialogs (wizard, prompt)."""
        if not is_windows():
            return False

        import win32gui
        import win32con
        import win32process

        target_pid = self.cscape_pid
        if not target_pid and self.main_hwnd:
            try:
                _, target_pid = win32process.GetWindowThreadProcessId(self.main_hwnd)
            except Exception:
                pass
        if not target_pid:
            return False

        target_pids = {target_pid}
        try:
            import psutil
            for child in psutil.Process(target_pid).children(recursive=False):
                target_pids.add(child.pid)
        except Exception:
            pass

        start = time.time()
        while time.time() - start < timeout:
            found_dialog = None

            def cb(hwnd: int, _: Any) -> None:
                nonlocal found_dialog
                if win32gui.IsWindowVisible(hwnd) and win32gui.GetClassName(hwnd) == "#32770":
                    try:
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)
                        if pid in target_pids:
                            found_dialog = hwnd
                    except Exception:
                        pass

            win32gui.EnumWindows(cb, None)
            if found_dialog:
                title = win32gui.GetWindowText(found_dialog)
                logger.info("Detected modal dialog '%s' (hwnd=0x%X) during POU creation", title, found_dialog)
                # If dialog has an OK button (ID 1), click it
                ok_btn = win32gui.GetDlgItem(found_dialog, ID_OK)
                if ok_btn:
                    win32gui.SendMessage(ok_btn, win32con.BM_CLICK, 0, 0)
                    return True
                else:
                    win32gui.PostMessage(found_dialog, win32con.WM_COMMAND, ID_OK, 0)
                    return True
            time.sleep(0.2)
        return False

    # --------------------------------------------------------------------------
    # 2. ST Editor Window Discovery
    # --------------------------------------------------------------------------

    def find_mdi_client_window(self) -> Optional[int]:
        """Find Cscape's MDIClient window handle hosting document views."""
        if not self.main_hwnd or not is_windows():
            return None

        import win32gui

        mdi_hwnd = None

        def cb(hwnd: int, _: Any) -> None:
            nonlocal mdi_hwnd
            if win32gui.GetClassName(hwnd) == "MDIClient":
                mdi_hwnd = hwnd

        win32gui.EnumChildWindows(self.main_hwnd, cb, None)
        return mdi_hwnd

    def find_editor_windows(self, pou_name: Optional[str] = None) -> list[EditorWindowInfo]:
        """Enumerate all open ST editor windows or locate an editor by POU name."""
        results: list[EditorWindowInfo] = []

        if not is_windows() or not self.main_hwnd:
            return results

        import win32gui

        mdi_client = self.find_mdi_client_window()
        search_root = mdi_client if mdi_client else self.main_hwnd

        # Enumerate MDI child windows
        def enum_children(hwnd: int, _: Any) -> None:
            title = win32gui.GetWindowText(hwnd)
            cls_name = win32gui.GetClassName(hwnd)
            visible = bool(win32gui.IsWindowVisible(hwnd))

            # Look for POU title match or editor controls
            matched = False
            extracted_name = pou_name or "ActivePOU"
            if pou_name and pou_name.lower() in title.lower():
                matched = True
                extracted_name = pou_name
            elif title.endswith(".st") or "st" in cls_name.lower():
                matched = True
                extracted_name = title.replace(".st", "").strip("[] ")

            if matched:
                # Find inner text editor control
                inner_editor_hwnd = self._find_inner_editor_control(hwnd)
                ctrl_hwnd = inner_editor_hwnd or hwnd
                ctrl_cls = win32gui.GetClassName(ctrl_hwnd)

                ctrl_type = "edit"
                if "scintilla" in ctrl_cls.lower():
                    ctrl_type = "scintilla"
                elif "richedit" in ctrl_cls.lower():
                    ctrl_type = "richedit"

                results.append(
                    EditorWindowInfo(
                        hwnd=ctrl_hwnd,
                        class_name=ctrl_cls,
                        title=title,
                        pou_name=extracted_name,
                        pou_type=POUType.PROGRAM,
                        parent_hwnd=hwnd,
                        is_visible=visible,
                        control_type=ctrl_type,
                    )
                )

        win32gui.EnumChildWindows(search_root, enum_children, None)
        return results

    def _find_inner_editor_control(self, mdi_child_hwnd: int) -> Optional[int]:
        """Inspect MDI child to find inner Edit / RichEdit / Scintilla text buffer control."""
        import win32gui

        target_hwnd = None
        known_editor_classes = ("edit", "richedit", "riched20", "scintilla", "w5edit", "cw5")

        def cb(hwnd: int, _: Any) -> None:
            nonlocal target_hwnd
            cls_lower = win32gui.GetClassName(hwnd).lower()
            if any(k in cls_lower for k in known_editor_classes):
                target_hwnd = hwnd

        win32gui.EnumChildWindows(mdi_child_hwnd, cb, None)
        return target_hwnd

    # --------------------------------------------------------------------------
    # 3. Code Insertion Implementations
    # --------------------------------------------------------------------------

    def insert_code(
        self,
        editor_hwnd: int,
        code: str,
        method: Optional[InsertionMethod] = None,
        pou_name: Optional[str] = None,
        project_dir: Optional[Union[str, Path]] = None,
    ) -> tuple[bool, InsertionMethod, Optional[str]]:
        """Insert IEC 61131-3 Structured Text code into the specified editor.

        Supports Window Handle messaging, Windows Clipboard, SendKeys, and File Sync.
        """
        chosen_method = method or self.default_method
        clean_code = normalize_st_code(code)

        # 1. Enforce pure ST & reject ladder logic constructs prior to insertion
        from .st_ld_interop import STLadderInteropGuard, LadderConstructRejectedError
        try:
            STLadderInteropGuard.enforce_st_code(clean_code)
        except LadderConstructRejectedError as lre:
            return False, chosen_method, f"Ladder logic rejected: {lre}"

        # 2. Validate ST code syntax prior to insertion
        val = IECValidator.validate(clean_code)
        if not val.get("valid", False):
            errs = "; ".join(val.get("errors", []))
            return False, chosen_method, f"Invalid IEC 61131-3 Structured Text: {errs}"

        # 3. Validate SHA-256 AST hash calculation prior to insertion
        try:
            _ = calculate_ast_hash(clean_code)
        except Exception as e:
            return False, chosen_method, f"AST validation/hashing failed: {e}"


        # 2. AUTO strategy: try Window Handle -> Clipboard -> SendKeys -> File Sync
        if chosen_method == InsertionMethod.AUTO:
            methods_to_try = [
                InsertionMethod.WINDOW_HANDLE,
                InsertionMethod.CLIPBOARD,
                InsertionMethod.SENDKEYS,
            ]
            if project_dir and pou_name:
                methods_to_try.append(InsertionMethod.FILE_SYNC)

            last_error = None
            for m in methods_to_try:
                ok, _, err = self._execute_insertion_method(
                    editor_hwnd=editor_hwnd,
                    code=clean_code,
                    method=m,
                    pou_name=pou_name,
                    project_dir=project_dir,
                )
                if ok:
                    return True, m, None
                last_error = err

            return False, InsertionMethod.AUTO, last_error or "All insertion strategies failed."

        # 3. Single chosen method
        return self._execute_insertion_method(
            editor_hwnd=editor_hwnd,
            code=clean_code,
            method=chosen_method,
            pou_name=pou_name,
            project_dir=project_dir,
        )

    def _execute_insertion_method(
        self,
        editor_hwnd: int,
        code: str,
        method: InsertionMethod,
        pou_name: Optional[str] = None,
        project_dir: Optional[Union[str, Path]] = None,
    ) -> tuple[bool, InsertionMethod, Optional[str]]:
        """Dispatch single insertion strategy."""
        try:
            if method == InsertionMethod.WINDOW_HANDLE:
                return self._insert_via_window_handle(editor_hwnd, code)
            elif method == InsertionMethod.CLIPBOARD:
                return self._insert_via_clipboard(editor_hwnd, code)
            elif method == InsertionMethod.SENDKEYS:
                return self._insert_via_sendkeys(editor_hwnd, code)
            elif method == InsertionMethod.FILE_SYNC:
                if not project_dir or not pou_name:
                    return False, method, "File sync requires valid project_dir and pou_name."
                return self._insert_via_file_sync(Path(project_dir), pou_name, code)
            else:
                return False, method, f"Unsupported insertion method: {method}"
        except Exception as e:
            logger.warning("Insertion method '%s' failed: %s", method, e)
            return False, method, str(e)

    def _insert_via_window_handle(self, hwnd: int, code: str) -> tuple[bool, InsertionMethod, Optional[str]]:
        """Inject Structured Text code using Win32 / Scintilla messages."""
        if not is_windows() or not hwnd:
            return False, InsertionMethod.WINDOW_HANDLE, "Win32 window handle not accessible."

        import win32gui
        import win32con

        try:
            cls_lower = win32gui.GetClassName(hwnd).lower()
        except Exception as e:
            return False, InsertionMethod.WINDOW_HANDLE, f"Invalid window handle or class: {e}"

        # Strategy A: Scintilla control
        if "scintilla" in cls_lower:
            try:
                # Clear existing text and set new code
                win32gui.SendMessage(hwnd, SCI_CLEARALL, 0, 0)
                code_bytes = code.encode("utf-8")
                # Send SCI_SETTEXT
                res = win32gui.SendMessage(hwnd, SCI_SETTEXT, 0, code_bytes)
                return True, InsertionMethod.WINDOW_HANDLE, None
            except Exception as e:
                logger.debug("Scintilla direct message failed: %s", e)

        # Strategy B: Standard Win32 Edit or RichEdit control via WM_SETTEXT
        try:
            # Set focus to control
            win32gui.SendMessage(hwnd, WM_SETFOCUS, 0, 0)
            # Select all and replace, or set whole text
            win32gui.SendMessage(hwnd, EM_SETSEL, 0, -1)
            res = win32gui.SendMessage(hwnd, WM_SETTEXT, 0, code)
            if res != 0:
                win32gui.SendMessage(hwnd, EM_SETMODIFY, 1, 0)
                return True, InsertionMethod.WINDOW_HANDLE, None
        except Exception as e:
            logger.debug("WM_SETTEXT message failed: %s", e)

        # Strategy C: EM_REPLACESEL
        try:
            win32gui.SendMessage(hwnd, EM_SETSEL, 0, -1)
            win32gui.SendMessage(hwnd, EM_REPLACESEL, 1, code)
            return True, InsertionMethod.WINDOW_HANDLE, None
        except Exception as e:
            return False, InsertionMethod.WINDOW_HANDLE, f"Window handle injection failed: {e}"

    def _insert_via_clipboard(self, hwnd: int, code: str) -> tuple[bool, InsertionMethod, Optional[str]]:
        """Insert Structured Text code via Windows Clipboard copy and paste."""
        if not is_windows():
            return False, InsertionMethod.CLIPBOARD, "Clipboard automation requires Windows."

        import win32clipboard
        import win32con
        import win32gui

        # 1. Set Windows clipboard content
        opened = False
        try:
            win32clipboard.OpenClipboard()
            opened = True
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(code, win32clipboard.CF_UNICODETEXT)
        except Exception as e:
            return False, InsertionMethod.CLIPBOARD, f"Failed setting clipboard text: {e}"
        finally:
            if opened:
                try:
                    win32clipboard.CloseClipboard()
                except Exception:
                    pass

        # 2. Direct focus and paste to editor window
        try:
            win32gui.SendMessage(hwnd, WM_SETFOCUS, 0, 0)
            # Select all existing content
            win32gui.SendMessage(hwnd, EM_SETSEL, 0, -1)
            time.sleep(0.05)
            # Send WM_PASTE message
            win32gui.SendMessage(hwnd, WM_PASTE, 0, 0)
            return True, InsertionMethod.CLIPBOARD, None
        except Exception as e:
            logger.debug("WM_PASTE failed, attempting keyboard shortcut: %s", e)

        # Fallback 3: Send Ctrl+V via pywinauto / SendKeys
        try:
            import pywinauto.keyboard as keyboard
            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
            keyboard.send_keys("^a^v")
            return True, InsertionMethod.CLIPBOARD, None
        except Exception as e:
            return False, InsertionMethod.CLIPBOARD, f"Clipboard paste failed: {e}"

    def _insert_via_sendkeys(self, hwnd: int, code: str) -> tuple[bool, InsertionMethod, Optional[str]]:
        """Insert Structured Text code by typing or key sequence emulation."""
        if not is_windows():
            return False, InsertionMethod.SENDKEYS, "SendKeys requires Windows environment."

        try:
            import pywinauto.keyboard as keyboard
            import win32gui

            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
            win32gui.SendMessage(hwnd, WM_SETFOCUS, 0, 0)
            # Clear editor with Ctrl+A, Delete
            keyboard.send_keys("^a{BACKSPACE}")
            time.sleep(0.1)

            # Send lines sequentially
            for line in code.splitlines():
                # Escape pywinauto special chars: { } + ^ % ~ ( )
                escaped = re.sub(r"([{}()+\^%~])", r"{\1}", line)
                keyboard.send_keys(escaped + "{ENTER}", with_spaces=True)
            return True, InsertionMethod.SENDKEYS, None
        except Exception as e:
            return False, InsertionMethod.SENDKEYS, f"SendKeys failed: {e}"

    @staticmethod
    def resolve_target_file(
        target_path: Union[str, Path],
        pou_name: str,
    ) -> tuple[Path, Optional[Path], bool]:
        """Resolve target POU file path, optional CFBF .csp container, and standalone flag.

        Returns:
            (pou_file_path, csp_container_path, is_standalone)

        Supported structures:
        1. Standalone .st file paths (e.g. 'path/to/MyFile.st').
        2. Native CFBF .csp project container paths (e.g. 'path/to/Project.csp').
        3. Project directories containing .csp containers or cscape_project.json.
        4. Standalone directories.
        """
        p = Path(target_path).resolve()

        # Case 1: Standalone .st file path explicitly provided
        if p.suffix.lower() == ".st":
            return p, None, True

        # Case 2: Native .csp container file explicitly provided
        if p.suffix.lower() == ".csp":
            proj_dir = p.parent
            pous_dir = proj_dir / "pous"
            return pous_dir / f"{pou_name}.st", p, False

        # Case 3: Target path is a directory
        direct_st = p / f"{pou_name}.st"
        pous_st = p / "pous" / f"{pou_name}.st"
        manifest_file = p / "cscape_project.json"
        csp_files = list(p.glob("*.csp")) if p.exists() and p.is_dir() else []

        if csp_files or manifest_file.exists():
            csp_file = csp_files[0] if csp_files else (p / f"{p.name}.csp")
            return pous_st, csp_file, False

        if direct_st.exists() and not (p / "pous").exists():
            return direct_st, None, True

        return pous_st, None, True

    @staticmethod
    def validate_cfbf_container(csp_path: Path) -> bool:
        """Validate that a .csp file contains authentic CFBF structure and not corrupt magic+zeros."""
        from .cfbf import is_valid_cfbf
        return is_valid_cfbf(csp_path)

    @staticmethod
    def register_pou_in_manifest(
        manifest_path: Path,
        pou_name: str,
        pou_type: POUType,
        pou_file: Path,
        code: str,
        cycle_time_ms: int = 10,
    ) -> None:
        """Register or update POU metadata in cscape_project.json manifest."""
        try:
            if manifest_path.exists():
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
            else:
                data = {
                    "name": manifest_path.parent.name,
                    "cscape_version": "10.2.751.4",
                    "iec_engine": "IEC 61131-3 Structured Text",
                    "pous": [],
                }

            pous = data.get("pous", [])
            ast_h = None
            try:
                ast_h = calculate_ast_hash(code)
            except Exception:
                pass

            entry = {
                "name": pou_name,
                "pou_type": pou_type.value.upper(),
                "file_path": str(pou_file),
                "language": "ST",
                "code_hash": calculate_code_hash(code),
                "ast_hash": ast_h,
                "cycle_time_ms": cycle_time_ms,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }

            updated = False
            for i, p in enumerate(pous):
                if isinstance(p, dict) and p.get("name") == pou_name:
                    pous[i] = entry
                    updated = True
                    break
            if not updated:
                pous.append(entry)

            data["pous"] = pous
            data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            logger.info("Registered POU '%s' in cscape_project.json: %s", pou_name, manifest_path)
        except Exception as e:
            logger.warning("Failed updating cscape_project.json for POU '%s': %s", pou_name, e)

    def _insert_via_file_sync(
        self,
        project_dir: Path,
        pou_name: str,
        code: str,
    ) -> tuple[bool, InsertionMethod, Optional[str]]:
        """Synchronize code to native CFBF .csp project structure or standalone ST file."""
        try:
            pou_file, csp_container, is_standalone = self.resolve_target_file(project_dir, pou_name)
            pou_file.parent.mkdir(parents=True, exist_ok=True)
            pou_file.write_text(code, encoding="utf-8")

            # If inside a CFBF project structure, update cscape_project.json if present
            proj_root = pou_file.parent.parent if not is_standalone else pou_file.parent
            manifest_file = proj_root / "cscape_project.json"
            if manifest_file.exists() or (csp_container and csp_container.exists()):
                self.register_pou_in_manifest(
                    manifest_path=manifest_file,
                    pou_name=pou_name,
                    pou_type=POUType.PROGRAM,
                    pou_file=pou_file,
                    code=code,
                )
            return True, InsertionMethod.FILE_SYNC, None
        except Exception as e:
            return False, InsertionMethod.FILE_SYNC, f"File sync failed: {e}"

    # --------------------------------------------------------------------------
    # 4. Code Verification Engine
    # --------------------------------------------------------------------------

    def read_editor_code(self, editor_hwnd: int, max_length: int = 1048576) -> str:
        """Extract current text content from the editor window handle."""
        if not is_windows() or not editor_hwnd:
            return ""

        import win32gui
        import win32con

        try:
            cls_lower = win32gui.GetClassName(editor_hwnd).lower()
        except Exception:
            return ""

        # Strategy A: Scintilla SCI_GETTEXT
        if "scintilla" in cls_lower:
            try:
                length = win32gui.SendMessage(editor_hwnd, SCI_GETTEXTLENGTH, 0, 0)
                if length > 0:
                    buf = bytes(length + 1)
                    win32gui.SendMessage(editor_hwnd, SCI_GETTEXT, length + 1, buf)
                    return buf[:length].decode("utf-8", errors="replace")
            except Exception as e:
                logger.debug("Scintilla SCI_GETTEXT failed: %s", e)

        # Strategy B: WM_GETTEXTLENGTH + WM_GETTEXT
        try:
            length = win32gui.SendMessage(editor_hwnd, WM_GETTEXTLENGTH, 0, 0)
            if length > 0:
                buf = win32gui.PyMakeBuffer(length + 1)
                win32gui.SendMessage(editor_hwnd, WM_GETTEXT, length + 1, buf)
                # Parse buffer
                text = bytes(buf)[:length].decode("utf-8", errors="ignore")
                return text
        except Exception as e:
            logger.debug("WM_GETTEXT failed: %s", e)

        # Strategy C: UIAutomation ValuePattern or TextPattern
        try:
            import uiautomation as auto
            ctrl = auto.ControlFromHandle(editor_hwnd)
            if ctrl and ctrl.Exists(0, 0):
                val_pat = ctrl.GetValuePattern()
                if val_pat:
                    return val_pat.Value
                txt_pat = ctrl.GetTextPattern()
                if txt_pat:
                    return txt_pat.DocumentRange.GetText(-1)
        except Exception as e:
            logger.debug("UIA pattern read failed: %s", e)

        # Strategy D: W5EditST Live Editor Read (Focus + Select All + Copy)
        if "w5editst" in cls_lower:
            try:
                import win32clipboard
                try:
                    win32clipboard.OpenClipboard()
                    win32clipboard.EmptyClipboard()
                except Exception:
                    pass
                finally:
                    try:
                        win32clipboard.CloseClipboard()
                    except Exception:
                        pass

                import ctypes
                user32 = ctypes.windll.user32
                user32.SetFocus(editor_hwnd)
                time.sleep(0.1)
                # Ctrl+A
                user32.keybd_event(0x11, 0, 0, 0)
                user32.keybd_event(ord('A'), 0, 0, 0)
                user32.keybd_event(ord('A'), 0, 2, 0)
                user32.keybd_event(0x11, 0, 2, 0)
                time.sleep(0.1)
                # Ctrl+C
                user32.keybd_event(0x11, 0, 0, 0)
                user32.keybd_event(ord('C'), 0, 0, 0)
                user32.keybd_event(ord('C'), 0, 2, 0)
                user32.keybd_event(0x11, 0, 2, 0)
                time.sleep(0.2)

                win32clipboard.OpenClipboard()
                try:
                    if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                        copied = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                        if copied:
                            return copied
                finally:
                    win32clipboard.CloseClipboard()
            except Exception as e:
                logger.debug("Strategy D W5EditST live clipboard read failed: %s", e)

        return ""

    def verify_editor_content(
        self,
        editor_hwnd: int,
        expected_code: str,
        pou_name: Optional[str] = None,
        file_path: Optional[Union[str, Path]] = None,
    ) -> STVerificationResult:
        """Verify that Structured Text code in the editor matches expected content.

        Checks:
        1. Character length comparison.
        2. Normalized SHA-256 cryptographic hash match.
        3. IEC 61131-3 AST grammar validity of the loaded code.
        4. SHA-256 AST hash match between expected and extracted code.
        """
        diagnostics: list[str] = []
        expected_norm = normalize_st_code(expected_code)
        expected_hash = calculate_code_hash(expected_norm)

        expected_ast_hash = None
        try:
            expected_ast_hash = calculate_ast_hash(expected_norm)
            diagnostics.append(f"Expected SHA-256 AST hash: {expected_ast_hash[:12]}...")
        except Exception as e:
            diagnostics.append(f"Warning: Failed calculating expected AST hash: {e}")

        extracted = self.read_editor_code(editor_hwnd)

        # Fail-closed: remove editor-empty -> aux-file verify fallback.
        # If the editor window buffer is empty, do NOT fall back to reading from disk.
        if not extracted:
            diagnostics.append("Editor window buffer is empty (0 characters read). Aux-file fallback is strictly prohibited.")

        extracted_norm = normalize_st_code(extracted)
        extracted_hash = calculate_code_hash(extracted_norm)

        exact_match = (expected_hash == extracted_hash)
        if exact_match:
            diagnostics.append("Cryptographic SHA-256 code hash verified identical.")
        else:
            diagnostics.append(
                f"Hash mismatch: expected={expected_hash[:8]}..., extracted={extracted_hash[:8]}..."
            )

        # Perform IEC AST validation on extracted code
        ast_errors: list[str] = []
        ast_valid = False
        extracted_ast_hash = None
        ast_match = False

        if extracted_norm:
            val_res = IECValidator.validate(extracted_norm)
            ast_valid = val_res["valid"]
            if not ast_valid:
                ast_errors.extend(val_res["errors"])
                diagnostics.append(f"AST validation error: {'; '.join(val_res['errors'])}")
            else:
                diagnostics.append(f"IEC 61131-3 AST validation passed ({val_res['metrics']['total_lines']} lines).")
                try:
                    extracted_ast_hash = calculate_ast_hash(extracted_norm)
                    if expected_ast_hash and extracted_ast_hash:
                        ast_match = (expected_ast_hash == extracted_ast_hash)
                        if ast_match:
                            diagnostics.append("Cryptographic SHA-256 AST hash verified identical.")
                        else:
                            diagnostics.append(
                                f"AST hash mismatch: expected={expected_ast_hash[:8]}..., extracted={extracted_ast_hash[:8]}..."
                            )
                except Exception as e:
                    diagnostics.append(f"Warning: Extracted AST hash calculation failed: {e}")
        else:
            diagnostics.append("Extracted buffer is empty; AST validation not performed.")

        verified = exact_match and ast_valid and (ast_match if (expected_ast_hash and extracted_ast_hash) else False)

        return STVerificationResult(
            verified=verified,
            editor_hwnd=editor_hwnd,
            extracted_code=extracted_norm,
            extracted_length=len(extracted_norm),
            expected_length=len(expected_norm),
            expected_hash=expected_hash,
            extracted_hash=extracted_hash,
            exact_match=exact_match,
            ast_valid=ast_valid,
            ast_errors=ast_errors,
            diagnostics=diagnostics,
            expected_ast_hash=expected_ast_hash,
            extracted_ast_hash=extracted_ast_hash,
            ast_match=ast_match,
        )

    # --------------------------------------------------------------------------
    # 5. High-Level Insertion Workflow
    # --------------------------------------------------------------------------

    def insert_pou(
        self,
        pou_name: str,
        pou_type: Union[POUType, str],
        code: str,
        method: InsertionMethod = InsertionMethod.AUTO,
        project_dir: Optional[Union[str, Path]] = None,
        cycle_time_ms: int = 10,
        verify: bool = True,
    ) -> STInsertionResult:
        """Complete workflow to create an IEC 61131-3 Structured Text POU and insert code.

        Workflow:
        1. Validates POU parameters, IEC 61131-3 syntax, and hardware safety locks.
        2. Automates Cscape command trigger to create POU (Program, FunctionBlock, Function).
        3. Locates target ST editor window handle.
        4. Inserts code via requested method (window handle, clipboard, sendkeys, file sync).
        5. Verifies code is properly loaded via read-back and AST validation.
        """
        start_time = time.time()
        ptype = POUType.from_str(pou_type)
        clean_name = SafetyGuard.validate_pou_name(pou_name)

        # 1. Enforce pure ST & reject ladder logic constructs pre-insertion
        try:
            from .st_ld_interop import STLadderInteropGuard, LadderConstructRejectedError
            STLadderInteropGuard.enforce_st_code(code)
        except LadderConstructRejectedError as lre:
            return STInsertionResult(
                success=False,
                pou_name=clean_name,
                pou_type=ptype,
                method_used=method,
                editor_hwnd=None,
                code_length=len(code),
                code_hash=calculate_code_hash(code),
                verified=False,
                error_message=f"Ladder logic rejected: {lre}",
                duration_seconds=time.time() - start_time,
            )

        # 2. Validate ST code syntax pre-insertion
        val = IECValidator.validate(code)
        if not val["valid"]:
            err_msg = f"Invalid IEC 61131-3 Structured Text: {'; '.join(val['errors'])}"
            return STInsertionResult(
                success=False,
                pou_name=clean_name,
                pou_type=ptype,
                method_used=method,
                editor_hwnd=None,
                code_length=len(code),
                code_hash=calculate_code_hash(code),
                verified=False,
                error_message=err_msg,
                duration_seconds=time.time() - start_time,
            )

        # 3. Calculate SHA-256 AST hash prior to insertion
        ast_hash_val = None
        try:
            ast_hash_val = calculate_ast_hash(code)
        except Exception as e:
            return STInsertionResult(
                success=False,
                pou_name=clean_name,
                pou_type=ptype,
                method_used=method,
                editor_hwnd=None,
                code_length=len(code),
                code_hash=calculate_code_hash(code),
                verified=False,
                error_message=f"AST hash generation failed: {e}",
                duration_seconds=time.time() - start_time,
            )

        # 4. File-system preparation: handle native CFBF .csp projects and standalone ST files
        file_path_str = None
        if project_dir:
            pou_file, csp_container, is_standalone = self.resolve_target_file(project_dir, clean_name)
            pou_file.parent.mkdir(parents=True, exist_ok=True)
            pou_file.write_text(code, encoding="utf-8")
            file_path_str = str(pou_file)

            # Check / register in native CFBF project structure
            proj_root = pou_file.parent.parent if not is_standalone else pou_file.parent
            manifest_file = proj_root / "cscape_project.json"
            if manifest_file.exists() or (csp_container and csp_container.exists()):
                self.register_pou_in_manifest(
                    manifest_path=manifest_file,
                    pou_name=clean_name,
                    pou_type=ptype,
                    pou_file=pou_file,
                    code=code,
                    cycle_time_ms=cycle_time_ms,
                )
            if csp_container and csp_container.exists():
                self.validate_cfbf_container(csp_container)

        # 5. Live UI automation: trigger new POU command
        # 5. Live UI automation: trigger new POU command if main window handle is available
        if self.main_hwnd:
            self.add_new_pou_command(ptype)

        # 6. Locate editor window
        editors = self.find_editor_windows(clean_name)
        editor_hwnd = editors[0].hwnd if editors else None

        # Handle live GUI vs offline file-based injection honestly (no fake HWNDs or mock stores)
        if not editor_hwnd:
            # If live GUI injection was explicitly requested and no live editor window exists, report honest failure
            if method in (InsertionMethod.WINDOW_HANDLE, InsertionMethod.CLIPBOARD, InsertionMethod.SENDKEYS):
                err = (
                    f"Live GUI injection requested via '{method.value}', but no active Cscape editor window "
                    f"was found for POU '{clean_name}'. Live editor window is required for GUI injection, "
                    f"or require offline file-based injection (method=InsertionMethod.FILE_SYNC with project_dir)."
                )
                return STInsertionResult(
                    success=False,
                    pou_name=clean_name,
                    pou_type=ptype,
                    method_used=method,
                    editor_hwnd=None,
                    code_length=len(code),
                    code_hash=calculate_code_hash(code),
                    verified=False,
                    error_message=err,
                    duration_seconds=time.time() - start_time,
                    ast_hash=ast_hash_val,
                )

            # For AUTO or FILE_SYNC: require offline file-based injection
            if not project_dir:
                err = (
                    f"No active Cscape editor window found for POU '{clean_name}' and no project_dir "
                    f"provided for offline file-based injection."
                )
                return STInsertionResult(
                    success=False,
                    pou_name=clean_name,
                    pou_type=ptype,
                    method_used=method,
                    editor_hwnd=None,
                    code_length=len(code),
                    code_hash=calculate_code_hash(code),
                    verified=False,
                    error_message=err,
                    duration_seconds=time.time() - start_time,
                    ast_hash=ast_hash_val,
                )

            # Offline file-based injection succeeded during file preparation (step 4)
            success = True
            used_method = InsertionMethod.FILE_SYNC
            err = None
        else:
            # 7. Insert code into live editor window
            success, used_method, err = self.insert_code(
                editor_hwnd=editor_hwnd,
                code=code,
                method=method,
                pou_name=clean_name,
                project_dir=project_dir,
            )

        # 8. Verification
        ver_result = None
        verified = False
        if success and verify:
            if editor_hwnd:
                ver_result = self.verify_editor_content(
                    editor_hwnd=editor_hwnd,
                    expected_code=code,
                    pou_name=clean_name,
                    file_path=file_path_str,
                )
                verified = ver_result.verified
            elif file_path_str and Path(file_path_str).exists():
                # Staged file verification (offline file sync; no live editor window)
                extracted = Path(file_path_str).read_text(encoding="utf-8")
                extracted_norm = normalize_st_code(extracted)
                expected_norm = normalize_st_code(code)
                exact_match = (calculate_code_hash(expected_norm) == calculate_code_hash(extracted_norm))
                val_res = IECValidator.validate(extracted_norm)
                exp_ast_h = None
                ext_ast_h = None
                ast_match = False
                try:
                    exp_ast_h = calculate_ast_hash(expected_norm)
                    ext_ast_h = calculate_ast_hash(extracted_norm)
                    ast_match = (exp_ast_h == ext_ast_h)
                except Exception:
                    pass
                verified = exact_match and val_res.get("valid", False) and (ast_match if (exp_ast_h and ext_ast_h) else False)
                ver_result = STVerificationResult(
                    verified=verified,
                    editor_hwnd=None,
                    extracted_code=extracted_norm,
                    extracted_length=len(extracted_norm),
                    expected_length=len(expected_norm),
                    expected_hash=calculate_code_hash(expected_norm),
                    extracted_hash=calculate_code_hash(extracted_norm),
                    exact_match=exact_match,
                    ast_valid=val_res.get("valid", False),
                    ast_errors=val_res.get("errors", []),
                    expected_ast_hash=exp_ast_h,
                    extracted_ast_hash=ext_ast_h,
                    ast_match=ast_match,
                    diagnostics=["Staged file verified on disk (offline staging; no live editor window)."],
                )
            else:
                verified = False
            if not verified and not err:
                err = f"Verification failed: exact_match={ver_result.exact_match if ver_result else False}, ast_valid={ver_result.ast_valid if ver_result else False}"

        duration = time.time() - start_time
        return STInsertionResult(
            success=success and (verified if verify else True),
            pou_name=clean_name,
            pou_type=ptype,
            method_used=used_method,
            editor_hwnd=editor_hwnd,
            code_length=len(code),
            code_hash=calculate_code_hash(code),
            verified=verified,
            verification=ver_result,
            file_path=file_path_str,
            duration_seconds=duration,
            error_message=err,
            ast_hash=ast_hash_val,
        )

    @classmethod
    def clear_mock_store(cls) -> None:
        """Deprecated: mock store removed. Kept as no-op for backward compatibility."""
        pass


# Canonical alias for MCP tool binding
CscapeSTInserter = StructuredTextInserter

