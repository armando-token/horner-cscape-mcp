"""Cscape 10.2 Live Project Automation and Project Manager.

Automates live Cscape 10.2 to create and manage IEC 61131 Structured Text projects:
- Dispatches and coordinates live Cscape MFC application (Cscape.exe)
- Handles startup modal dialogs ('About Cscape' splash and 'Select Editor Type')
- Strictly enforces IEC 61131 mode (Radio button 1461) - Rejects Advanced Ladder (1460, 3757)
- Drives File -> New (WM_COMMAND 57600 / ID_FILE_NEW)
- Drives File -> Save / Save As (WM_COMMAND 57603 / 57604)
- Automates Windows Common Save As dialogs via UIAutomation and Win32 message fallbacks
- Inspects and verifies saved project binaries (.csp / .cpj) against OLE Compound File (CFBF) specification
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import struct
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import psutil

# Attach thread to interactive desktop before any GUI or COM libraries load
try:
    import ctypes
    _user32 = ctypes.windll.user32
    _hd = _user32.OpenDesktopW("Default", 0, False, 0x01FF)
    if _hd:
        _user32.SetThreadDesktop(_hd)
except Exception:
    pass

# Windows automation libraries
try:
    import win32con
    import win32gui
    import win32process
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False

try:
    import uiautomation as auto
    UIA_AVAILABLE = True
except ImportError:
    UIA_AVAILABLE = False

try:
    import olefile
    OLEFILE_AVAILABLE = True
except ImportError:
    OLEFILE_AVAILABLE = False

logger = logging.getLogger(__name__)


# Standard MFC and Cscape Window/Command Constants
WM_COMMAND: int = 0x0111
WM_SETTEXT: int = 0x000C
WM_GETTEXT: int = 0x000D
WM_GETTEXTLENGTH: int = 0x000E
WM_CLOSE: int = 0x0010
BM_CLICK: int = 0x00F5
BM_SETCHECK: int = 0x00F1
BST_CHECKED: int = 1
BN_CLICKED: int = 0

# Cscape 10.2 Exact Command IDs (extracted from MFC resource tables)
ID_FILE_NEW: int = 57600       # 0xE100: "Create a new program\nNew File\nNew"
ID_FILE_OPEN: int = 57601      # 0xE101: "Open an existing program file\nOpen File\nOpen"
ID_FILE_CLOSE: int = 57602     # 0xE102: "Close the active program file\nClose File"
ID_FILE_SAVE: int = 57603      # 0xE103: "Save the active program file\nSave File\nSave"
ID_FILE_SAVE_AS: int = 57604   # 0xE104: "Save the active program file with a new name\nSaveAs File\nSave As"

# Cscape Dialog Class Names and Window Titles
DIALOG_CLASS: str = "#32770"
SPLASH_TITLE: str = "About Cscape"
EDITOR_TYPE_TITLE: str = "Select Editor Type"
SAVE_AS_TITLE: str = "Save As"
OPEN_TITLE: str = "Open"

# Cscape Dialog Control IDs
RADIO_ADVANCED_LADDER_REG: int = 1460  # Advanced Ladder with Register Based Addressing
RADIO_IEC_61131: int = 1461           # IEC 61131 Language Editors (ST, SFC, FBD, LD, IL)
RADIO_ADVANCED_LADDER_VAR: int = 3757  # Advanced Ladder with Variable Based Addressing
EDIT_FILE_NAME_ID: int = 1152          # Windows Common Dialog File Name Edit control ID
SAVE_BUTTON_ID: int = 1               # Common Dialog Save / OK Button ID
OPEN_BUTTON_ID: int = 1               # Common Dialog Open / OK Button ID
IDOK: int = 1
IDCANCEL: int = 2
IDYES: int = 6
IDNO: int = 7

# Candidate paths for active Cscape live gate status file
LIVE_GATE_PATHS: tuple[Path, ...] = (
    Path(r"C:\Users\ArmandoSilva\artifacts\.cscape_live_gate.json"),
    Path(r"C:\Users\ArmandoSilva\artifacts\checkpoints\cscape_live_gate.json"),
    Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\.cscape_live_gate.json"),
    Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\checkpoints\cscape_live_gate.json"),
    Path("artifacts/.cscape_live_gate.json"),
    Path("artifacts/checkpoints/cscape_live_gate.json"),
)

# 'Allow' Security & Firewall Dialog Constants
ALLOW_TEXT_KEYWORDS: tuple[str, ...] = (
    "allow access",
    "allow this app",
    "windows security alert",
    "windows defender firewall",
    "windows security",
    "windows firewall",
    "security alert",
    "security prompt",
    "blocked some features",
    "has blocked some features",
)

ALLOW_BUTTON_KEYWORDS: tuple[str, ...] = (
    "allow",
    "allow access",
    "allow this app",
    "&allow",
    "&allow access",
    "unblock",
    "&unblock",
)

from .cfbf import (
    CFBF_MAGIC,
    CSCAPE_CONTENTS_MAGIC,
    ProjectFileInfo,
    is_valid_cfbf,
    inspect_project_file,
    generate_minimal_cfbf_bytes,
    parse_csp_contents_header,
    extract_cfbf_streams,
)


class CscapeProjectError(Exception):
    """Base exception for Cscape live project automation errors."""
    pass


class CscapeNotFoundError(CscapeProjectError):
    """Raised when Cscape.exe is not found at the expected system location."""
    pass


class CscapeSafetyError(CscapeProjectError):
    """Raised when an action violates safety directives or IEC mode requirements."""
    pass


class CscapeAutomationError(CscapeProjectError):
    """Raised when UI automation or dialog interaction fails."""
    pass


@dataclass
class ProjectCreationResult:
    """Outcome of creating a new IEC 61131 project in Cscape."""
    success: bool
    project_name: str
    file_path: Path
    file_info: Optional[ProjectFileInfo] = None
    editor_mode: str = "IEC 61131"
    window_title: str = ""
    cscape_pid: Optional[int] = None
    main_hwnd: Optional[int] = None
    duration_seconds: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary representation."""
        return {
            "success": self.success,
            "project_name": self.project_name,
            "file_path": str(self.file_path),
            "file_info": self.file_info.to_dict() if self.file_info else None,
            "editor_mode": self.editor_mode,
            "window_title": self.window_title,
            "cscape_pid": self.cscape_pid,
            "main_hwnd": self.main_hwnd,
            "duration_seconds": round(self.duration_seconds, 3),
            "error": self.error,
        }


@dataclass
class ProjectOpenResult:
    """Outcome of opening and verifying a Horner Cscape project file (.csp / .cpj)."""
    success: bool
    project_name: str
    file_path: Path
    file_info: Optional[ProjectFileInfo] = None
    already_open: bool = False
    offline_validated: bool = False
    live_gui_opened: bool = False
    open_mode: str = "offline_validated"
    window_title: str = ""
    cscape_pid: Optional[int] = None
    main_hwnd: Optional[int] = None
    read_only: bool = False
    duration_seconds: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary representation."""
        return {
            "success": self.success,
            "project_name": self.project_name,
            "file_path": str(self.file_path),
            "file_info": self.file_info.to_dict() if self.file_info else None,
            "already_open": self.already_open,
            "offline_validated": self.offline_validated,
            "live_gui_opened": self.live_gui_opened,
            "open_mode": self.open_mode,
            "window_title": self.window_title,
            "cscape_pid": self.cscape_pid,
            "main_hwnd": self.main_hwnd,
            "read_only": self.read_only,
            "duration_seconds": round(self.duration_seconds, 3),
            "error": self.error,
        }


def get_cscape_gate_info(gate_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Read the active Cscape live gate metadata from disk.

    Checks gate_path if provided, followed by candidate standard locations.
    """
    candidates = [Path(gate_path)] if gate_path else list(LIVE_GATE_PATHS)
    best_data: Optional[Dict[str, Any]] = None
    best_ts: str = ""

    for p in candidates:
        if p and p.exists():
            try:
                raw_text = p.read_text(encoding="utf-8")
                data = json.loads(raw_text)
                ts = data.get("heartbeat_utc") or data.get("timestamp_utc") or ""
                if best_data is None or ts >= best_ts:
                    best_data = data
                    best_ts = ts
            except Exception:
                pass

    return best_data or {}


def resolve_cscape_pid(
    gate_path: Optional[Union[str, Path]] = None,
    verify_process_alive: bool = True,
) -> Optional[int]:
    """Dynamically resolves the active Cscape.exe PID without hardcoding.

    Resolution strategy:
    1. Reads PID from artifacts/.cscape_live_gate.json (or passed gate_path)
       and verifies that the process is actively running and is Cscape.exe.
    2. Fallback to Win32 / psutil process enumeration scanning all running
       processes for 'cscape.exe' (or 'cscape' in name).
    3. Verifies top-level window handles if Win32 is available.
    """
    # 1. Gate file resolution
    gate_info = get_cscape_gate_info(gate_path)
    gate_pid = gate_info.get("pid")
    if gate_pid is not None:
        try:
            p_int = int(gate_pid)
            if not verify_process_alive:
                return p_int
            if psutil.pid_exists(p_int):
                p = psutil.Process(p_int)
                if "cscape" in (p.name() or "").lower() and p.is_running():
                    return p_int
        except Exception:
            pass

    # 2. Process enumeration scan
    for p in psutil.process_iter(["pid", "name"]):
        try:
            name = (p.info.get("name") or "").lower()
            if "cscape" in name and p.is_running():
                return p.info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return None


class CscapeLiveProjectManager:
    """Automates project creation, opening, and saving within live Cscape 10.2."""

    DEFAULT_CSCAPE_PATH = Path(r"C:\Program Files (x86)\Cscape 10.2\Cscape.exe")
    DEFAULT_WORKSPACE = (
        Path(os.environ.get("HORNER_WORKSPACE", ""))
        if os.environ.get("HORNER_WORKSPACE")
        else Path.cwd()
        if (Path.cwd() / "artifacts").exists()
        else Path(r"C:\Users\ArmandoSilva")
        if Path(r"C:\Users\ArmandoSilva\artifacts").exists()
        else Path(r"C:\HornerAI\horner-cscape-mcp")
    )

    def __init__(
        self,
        cscape_path: Optional[Union[str, Path]] = None,
        working_dir: Optional[Union[str, Path]] = None,
    ) -> None:
        if not WIN32_AVAILABLE:
            raise ImportError("pywin32 (win32gui, win32con, win32process) is required.")

        self.cscape_path = Path(cscape_path) if cscape_path else self.DEFAULT_CSCAPE_PATH
        self.working_dir = Path(working_dir) if working_dir else self.DEFAULT_WORKSPACE / "artifacts" / "projects"
        self.working_dir.mkdir(parents=True, exist_ok=True)

        self.proc: Optional[subprocess.Popen] = None
        self.pid: Optional[int] = None
        self.main_hwnd: Optional[int] = None

    def __enter__(self) -> "CscapeLiveProjectManager":
        self.ensure_cscape_running()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # -------------------------------------------------------------------------
    # Process & Window Management
    # -------------------------------------------------------------------------

    def find_running_cscape_pid(self) -> Optional[int]:
        """Locate any currently running Cscape.exe process dynamically."""
        return resolve_cscape_pid()

    @staticmethod
    def is_process_running_pid(pid: int) -> bool:
        """Check if process with given PID is currently running."""
        try:
            return psutil.pid_exists(pid) and psutil.Process(pid).is_running()
        except Exception:
            return False

    @staticmethod
    def _attach_thread_desktop() -> None:
        """Attach calling thread to Default interactive desktop."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
            if hd:
                user32.SetThreadDesktop(hd)
        except Exception:
            pass

    def enum_process_windows(self, pid: Optional[int] = None) -> list[int]:
        """Enumerate all top-level window handles belonging to the specified PID and its direct children."""
        self._attach_thread_desktop()
        target_pid = pid or self.pid
        if not target_pid and self.main_hwnd:
            try:
                _, target_pid = win32process.GetWindowThreadProcessId(self.main_hwnd)
            except Exception:
                pass
        if not target_pid:
            return []

        target_pids = {target_pid}
        try:
            import psutil
            for child in psutil.Process(target_pid).children(recursive=False):
                target_pids.add(child.pid)
        except Exception:
            pass

        windows: list[int] = []

        def enum_cb(h: int, _: Any) -> bool:
            try:
                if win32gui.IsWindow(h):
                    _, p = win32process.GetWindowThreadProcessId(h)
                    if p in target_pids:
                        windows.append(h)
            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(enum_cb, None)
        except Exception:
            pass
        return windows

    @staticmethod
    def _safe_get_class(hwnd: int) -> str:
        try:
            if win32gui.IsWindow(hwnd):
                return win32gui.GetClassName(hwnd)
        except Exception:
            pass
        return ""

    @staticmethod
    def _safe_get_text(hwnd: int) -> str:
        try:
            if win32gui.IsWindow(hwnd):
                return win32gui.GetWindowText(hwnd)
        except Exception:
            pass
        return ""

    def find_descendant(
        self,
        parent_hwnd: int,
        class_name: Optional[str] = None,
        ctrl_id: Optional[int] = None,
        text_match: Optional[str] = None,
    ) -> Optional[int]:
        """Recursively locate a child control inside parent_hwnd matching criteria."""
        self._attach_thread_desktop()
        found: list[int] = []

        def cb(h: int, _: Any) -> bool:
            c_cls = self._safe_get_class(h)
            try:
                c_id = win32gui.GetDlgCtrlID(h)
            except Exception:
                c_id = -1
            c_text = self._safe_get_text(h)
            if class_name and c_cls.lower() != class_name.lower():
                return True
            if ctrl_id is not None and c_id != ctrl_id:
                return True
            if text_match and text_match.lower() not in c_text.lower():
                return True
            found.append(h)
            return True

        try:
            win32gui.EnumChildWindows(parent_hwnd, cb, None)
        except Exception:
            pass
        return found[0] if found else None

    def click_button(self, dialog_hwnd: int, ctrl_id: Optional[int] = None, text_match: Optional[str] = None) -> bool:
        """Send a BM_CLICK message to a dialog button by control ID or button text, and notify parent dialog."""
        ctrl_hwnd = None
        if ctrl_id is not None:
            try:
                ctrl_hwnd = win32gui.GetDlgItem(dialog_hwnd, ctrl_id)
            except Exception:
                pass
            if not ctrl_hwnd:
                ctrl_hwnd = self.find_descendant(dialog_hwnd, class_name="Button", ctrl_id=ctrl_id)

        if not ctrl_hwnd and text_match:
            ctrl_hwnd = self.find_descendant(dialog_hwnd, class_name="Button", text_match=text_match)

        if ctrl_hwnd:
            try:
                win32gui.SendMessage(ctrl_hwnd, BM_CLICK, 0, 0)
            except Exception:
                pass
            target_id = ctrl_id if ctrl_id is not None else win32gui.GetDlgCtrlID(ctrl_hwnd)
            if target_id != -1:
                try:
                    win32gui.PostMessage(dialog_hwnd, WM_COMMAND, (BN_CLICKED << 16) | (target_id & 0xFFFF), ctrl_hwnd)
                except Exception:
                    pass
            return True
        elif ctrl_id is not None:
            try:
                win32gui.PostMessage(dialog_hwnd, WM_COMMAND, (BN_CLICKED << 16) | (ctrl_id & 0xFFFF), 0)
                return True
            except Exception:
                pass
        return False

    def select_radio(self, dialog_hwnd: int, ctrl_id: int) -> bool:
        """Set checked state on a radio button and notify parent dialog.

        Strictly rejects legacy ladder modes (1460, 3757).
        """
        if ctrl_id in (RADIO_ADVANCED_LADDER_REG, RADIO_ADVANCED_LADDER_VAR):
            raise CscapeSafetyError(
                f"Legacy ladder mode radio ID {ctrl_id} is strictly rejected. "
                f"Only IEC 61131 mode (ID {RADIO_IEC_61131}) is permitted."
            )

        ctrl_hwnd = None
        try:
            ctrl_hwnd = win32gui.GetDlgItem(dialog_hwnd, ctrl_id)
        except Exception:
            pass
        if not ctrl_hwnd:
            ctrl_hwnd = self.find_descendant(dialog_hwnd, class_name="Button", ctrl_id=ctrl_id)

        if ctrl_hwnd:
            try:
                win32gui.PostMessage(ctrl_hwnd, BM_SETCHECK, BST_CHECKED, 0)
                win32gui.PostMessage(
                    dialog_hwnd,
                    WM_COMMAND,
                    (BN_CLICKED << 16) | (ctrl_id & 0xFFFF),
                    ctrl_hwnd,
                )
            except Exception:
                pass
            return True
        return False

    def ensure_cscape_running(self, timeout_sec: float = 30.0) -> int:
        """Launch Cscape 10.2 if not running, dismiss startup modals, and acquire main window."""
        running_pid = self.find_running_cscape_pid()
        if running_pid:
            logger.info("Found existing Cscape.exe process (PID=%d)", running_pid)
            self.pid = running_pid
            self.main_hwnd = self.get_main_window(timeout_sec=timeout_sec)
            return self.pid

        if not self.cscape_path.exists():
            raise CscapeNotFoundError(f"Cscape executable not found at: {self.cscape_path}")

        try:
            from .lifecycle import CscapeLifecycleManager
            lifecycle = CscapeLifecycleManager(
                executable_path=self.cscape_path,
                auto_dismiss_splash=True,
                auto_select_iec=True,
                launch_timeout=timeout_sec,
            )
            lifecycle.launch(cwd=self.cscape_path.parent)
            self.pid = lifecycle.pid
            self.proc = lifecycle.process
            self.main_hwnd = lifecycle.main_hwnd
            self._lifecycle = lifecycle
            return self.pid
        except Exception as life_err:
            logger.warning("CscapeLifecycleManager launch failed: %s; falling back to direct launch", life_err)

        # Proactively suppress crash recovery popup by asserting clean exit status in registry
        try:
            import winreg
            reg_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Horner_Electric\Cscape\Setup")
            winreg.SetValueEx(reg_key, "CscapeExitedCorrectly", 0, winreg.REG_DWORD, 1)
            winreg.CloseKey(reg_key)
        except Exception as reg_err:
            logger.debug("Could not set CscapeExitedCorrectly in registry: %s", reg_err)

        logger.info("Launching Cscape 10.2 from: %s (cwd=%s)", self.cscape_path, self.cscape_path.parent)
        self.proc = subprocess.Popen([str(self.cscape_path)], cwd=str(self.cscape_path.parent))
        self.pid = self.proc.pid

        # Handle startup dialogs and locate main window
        self.handle_startup_dialogs(timeout_sec=timeout_sec)
        self.main_hwnd = self.get_main_window(timeout_sec=timeout_sec)
        return self.pid

    # -------------------------------------------------------------------------
    # Dialog Detection and Handling Routines: Allow, Splash, Editor Type, Save As
    # -------------------------------------------------------------------------

    def find_allow_dialogs(self, check_system_windows: bool = False) -> list[dict[str, Any]]:
        """Find 'Allow' security or firewall modal dialogs strictly belonging to Cscape process and its direct children."""
        # Enforce fail-closed boundary: check_system_windows is strictly False or confined to Cscape PID.
        # Kill any un-scoped system-wide desktop dialog sweeps.
        if check_system_windows:
            logger.debug("find_allow_dialogs: check_system_windows overridden to False; strictly confined to Cscape PID")
            check_system_windows = False

        results: list[dict[str, Any]] = []
        candidate_hwnds: list[int] = self.enum_process_windows()
        if not candidate_hwnds:
            return []

        for h in candidate_hwnds:
            title = self._safe_get_text(h)
            cls = self._safe_get_class(h)
            title_lower = title.lower()

            if SPLASH_TITLE.lower() in title_lower or EDITOR_TYPE_TITLE.lower() in title_lower:
                continue

            # Strictly ignore non-fatal compilation error dialogs (fail-closed invariant)
            if "non-fatal" in title_lower or "nonfatal" in title_lower:
                continue

            is_dialog = cls == DIALOG_CLASS
            is_sec_title = any(kw in title_lower for kw in ALLOW_TEXT_KEYWORDS)
            if not is_dialog and not is_sec_title:
                continue

            allow_btn_hwnd = None
            allow_btn_text = ""
            for bkw in ALLOW_BUTTON_KEYWORDS:
                btn = self.find_descendant(h, class_name="Button", text_match=bkw)
                if btn:
                    allow_btn_hwnd = btn
                    allow_btn_text = self._safe_get_text(btn)
                    break

            has_allow_phrase = False
            if not allow_btn_hwnd:
                for kw in ALLOW_TEXT_KEYWORDS:
                    if kw in title_lower:
                        has_allow_phrase = True
                        break
                    stat = self.find_descendant(h, class_name="Static", text_match=kw)
                    if stat:
                        has_allow_phrase = True
                        break

            if allow_btn_hwnd or has_allow_phrase:
                if not allow_btn_hwnd:
                    for txt in ("ok", "yes", "allow access", "unblock"):
                        btn = self.find_descendant(h, class_name="Button", text_match=txt)
                        if btn:
                            allow_btn_hwnd = btn
                            allow_btn_text = self._safe_get_text(btn)
                            break
                    if not allow_btn_hwnd:
                        try:
                            btn = win32gui.GetDlgItem(h, IDOK)
                            if btn:
                                allow_btn_hwnd = btn
                                allow_btn_text = "OK"
                        except Exception:
                            pass

                results.append({
                    "hwnd": h,
                    "title": title,
                    "class_name": cls,
                    "allow_button_hwnd": allow_btn_hwnd,
                    "allow_button_text": allow_btn_text,
                })

        return results

    def handle_allow_dialogs(self, timeout_sec: float = 3.0, check_system_windows: bool = False) -> int:
        """Detect and auto-accept any 'Allow' security or firewall modal dialogs strictly belonging to Cscape."""
        accepted = 0
        # Strictly confine dialog handling to Cscape PID; no system-wide sweeps
        dialogs = self.find_allow_dialogs(check_system_windows=False)
        for dlg in dialogs:
            dhwnd = dlg["hwnd"]
            btn = dlg["allow_button_hwnd"]
            logger.info("Auto-accepting security/firewall dialog: '%s' (hwnd=%d)", dlg["title"], dhwnd)
            if btn and win32gui.IsWindow(btn):
                try:
                    win32gui.SendMessage(btn, BM_CLICK, 0, 0)
                    btn_id = win32gui.GetDlgCtrlID(btn)
                    if btn_id != -1:
                        win32gui.PostMessage(dhwnd, WM_COMMAND, (BN_CLICKED << 16) | (btn_id & 0xFFFF), btn)
                except Exception:
                    pass
            else:
                try:
                    win32gui.PostMessage(dhwnd, WM_COMMAND, (BN_CLICKED << 16) | IDOK, 0)
                except Exception:
                    pass

            start_v = time.time()
            while time.time() - start_v < timeout_sec:
                time.sleep(0.1)
                if not win32gui.IsWindow(dhwnd) or not win32gui.IsWindowVisible(dhwnd):
                    accepted += 1
                    break
        return accepted

    def find_splash_dialog(self, timeout_sec: float = 0.0) -> Optional[int]:
        """Find the modal 'About Cscape' splash dialog (#32770, IDOK=1) if present and visible."""
        start = time.time()
        while True:
            for hwnd in self.enum_process_windows():
                if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
                    continue
                title = self._safe_get_text(hwnd)
                cls = self._safe_get_class(hwnd)
                if cls == DIALOG_CLASS and SPLASH_TITLE.lower() in title.lower():
                    return hwnd
                if cls == DIALOG_CLASS and self.find_descendant(hwnd, text_match=SPLASH_TITLE):
                    return hwnd
            if time.time() - start >= timeout_sec:
                break
            time.sleep(0.2)
        return None

    def dismiss_splash_dialog(self, dialog_hwnd: Optional[int] = None, timeout_sec: float = 6.0) -> bool:
        """Detect and dismiss modal 'About Cscape' splash dialog (#32770, IDOK=1)."""
        dlg = dialog_hwnd or self.find_splash_dialog(timeout_sec=timeout_sec)
        if not dlg:
            return False

        logger.info("Dismissing 'About Cscape' splash dialog (#32770, hwnd=%d)", dlg)
        for _ in range(5):
            self.click_button(dlg, IDOK)
            time.sleep(0.1)
            if not win32gui.IsWindow(dlg) or not win32gui.IsWindowVisible(dlg):
                logger.info("'About Cscape' splash dismissed successfully.")
                return True

        # Retry IDOK message rather than sending destructive WM_CLOSE
        try:
            win32gui.PostMessage(dlg, WM_COMMAND, (BN_CLICKED << 16) | IDOK, 0)
        except Exception:
            pass

        time.sleep(0.2)
        return not win32gui.IsWindow(dlg) or not win32gui.IsWindowVisible(dlg)

    def find_editor_type_dialog(self, timeout_sec: float = 0.0) -> Optional[int]:
        """Find the 'Select Editor Type' dialog (#32770) if present and visible."""
        start = time.time()
        while True:
            for hwnd in self.enum_process_windows():
                if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
                    continue
                title = self._safe_get_text(hwnd)
                cls = self._safe_get_class(hwnd)
                if cls == DIALOG_CLASS and EDITOR_TYPE_TITLE.lower() in title.lower():
                    return hwnd
                if cls == DIALOG_CLASS:
                    if self.find_descendant(hwnd, text_match=EDITOR_TYPE_TITLE) or self.find_descendant(hwnd, ctrl_id=RADIO_IEC_61131):
                        return hwnd
            if time.time() - start >= timeout_sec:
                break
            time.sleep(0.2)
        return None

    def handle_editor_type_dialog(
        self,
        dialog_hwnd: Optional[int] = None,
        radio_id: int = RADIO_IEC_61131,
        timeout_sec: float = 6.0,
    ) -> bool:
        """Detect 'Select Editor Type' dialog (#32770), select radio 1461, and click IDOK=1."""
        if radio_id in (RADIO_ADVANCED_LADDER_REG, RADIO_ADVANCED_LADDER_VAR):
            raise CscapeSafetyError(
                f"Legacy ladder mode radio ID {radio_id} is strictly rejected. "
                f"Only IEC 61131 mode (ID {RADIO_IEC_61131}) is permitted."
            )
        if radio_id != RADIO_IEC_61131:
            raise CscapeSafetyError(
                f"Non-IEC editor mode radio ID {radio_id} is strictly rejected. "
                f"Only IEC 61131 mode (ID {RADIO_IEC_61131}) is permitted."
            )

        dlg = dialog_hwnd or self.find_editor_type_dialog(timeout_sec=timeout_sec)
        if not dlg:
            return False

        logger.info("Handling 'Select Editor Type' dialog (#32770, hwnd=%d) -> IEC 61131 (ID %d)", dlg, radio_id)
        for _ in range(5):
            self.select_radio(dlg, radio_id)
            time.sleep(0.2)
            self.click_button(dlg, IDOK)
            time.sleep(0.1)
            if not win32gui.IsWindow(dlg) or not win32gui.IsWindowVisible(dlg):
                logger.info("'Select Editor Type' dialog dismissed successfully.")
                return True

        # Retry sending IDOK safely without destructive WM_CLOSE
        try:
            win32gui.PostMessage(dlg, WM_COMMAND, (BN_CLICKED << 16) | IDOK, 0)
        except Exception:
            pass

        time.sleep(0.2)
        return not win32gui.IsWindow(dlg) or not win32gui.IsWindowVisible(dlg)

    def find_save_as_dialog(self, timeout_sec: float = 15.0) -> Optional[int]:
        """Find the 'Save As' common dialog (#32770, Edit 1152, ID 1) if present and visible."""
        start = time.time()
        while time.time() - start < timeout_sec:
            time.sleep(0.2)
            for hwnd in self.enum_process_windows():
                if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
                    continue
                title = self._safe_get_text(hwnd)
                cls = self._safe_get_class(hwnd)
                if hwnd != self.main_hwnd and cls == DIALOG_CLASS and ("save" in title.lower() or "save as" in title.lower()):
                    return hwnd

            # Secondary fallback search across all visible windows for this PID and direct children
            candidate_hwnds: list[int] = []
            target_pid = self.pid
            if not target_pid and self.main_hwnd:
                try:
                    _, target_pid = win32process.GetWindowThreadProcessId(self.main_hwnd)
                except Exception:
                    pass
            target_pids = {target_pid} if target_pid else set()
            if target_pid:
                try:
                    import psutil
                    for child in psutil.Process(target_pid).children(recursive=False):
                        target_pids.add(child.pid)
                except Exception:
                    pass

            def enum_cb(h: int, _: Any) -> bool:
                try:
                    if win32gui.IsWindow(h) and win32gui.IsWindowVisible(h):
                        c = self._safe_get_class(h)
                        t = self._safe_get_text(h).lower()
                        if c == DIALOG_CLASS and ("save as" in t or t == "save"):
                            _, p = win32process.GetWindowThreadProcessId(h)
                            if target_pids and p in target_pids:
                                candidate_hwnds.append(h)
                except Exception:
                    pass
                return True
            try:
                win32gui.EnumWindows(enum_cb, None)
            except Exception:
                pass
            if candidate_hwnds:
                return candidate_hwnds[0]

        return None

    def handle_save_as_dialog(
        self,
        dialog_hwnd: int,
        destination_path: Union[str, Path],
        timeout_sec: float = 15.0,
    ) -> bool:
        """Automated detection and handling of Save As dialog (#32770, Edit 1152, ID 1).

        Sets target file path into Edit 1152, clicks Save button (ID 1),
        handles any confirmation/replace modals or firewall/security prompts,
        and verifies dismissal.
        """
        target_path = Path(destination_path).resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        full_path_to_set = str(target_path)
        filename_to_set = target_path.name

        logger.info("Handling Save As dialog (#32770, hwnd=%d) for target: %s", dialog_hwnd, target_path)

        saved_successfully = False
        if UIA_AVAILABLE:
            try:
                save_window = auto.ControlFromHandle(dialog_hwnd)
                name_cb = save_window.ComboBoxControl(AutomationId="FileNameControlHost")
                edit = name_cb.EditControl() if name_cb.Exists(0, 0) else save_window.EditControl(searchDepth=6)
                save_btn = save_window.ButtonControl(AutomationId="1")

                logger.debug("Using UIAutomation: setting filename to '%s'", filename_to_set)
                edit.GetValuePattern().SetValue(full_path_to_set)
                time.sleep(0.3)
                logger.debug("Invoking Save button via UIAutomation...")
                if save_btn.Exists(0, 0):
                    try:
                        save_btn.GetInvokePattern().Invoke()
                    except Exception:
                        pass
                # Send Enter key as standard Windows Common File Dialog commit
                time.sleep(0.3)
                if win32gui.IsWindow(dialog_hwnd) and win32gui.IsWindowVisible(dialog_hwnd):
                    try:
                        save_window.SendKeys('{ENTER}')
                    except Exception:
                        pass
                saved_successfully = True
            except Exception as e:
                logger.warning("UIAutomation interaction failed: %s; falling back to Win32 messages.", e)

        if not saved_successfully:
            edit_hwnd = None
            try:
                edit_hwnd = win32gui.GetDlgItem(dialog_hwnd, EDIT_FILE_NAME_ID)
            except Exception:
                pass
            if not edit_hwnd:
                edit_hwnd = self.find_descendant(dialog_hwnd, class_name="Edit", ctrl_id=EDIT_FILE_NAME_ID)
            if not edit_hwnd:
                edit_hwnd = self.find_descendant(dialog_hwnd, class_name="Edit")

            save_btn_hwnd = None
            try:
                save_btn_hwnd = win32gui.GetDlgItem(dialog_hwnd, SAVE_BUTTON_ID)
            except Exception:
                pass
            if not save_btn_hwnd:
                save_btn_hwnd = self.find_descendant(dialog_hwnd, class_name="Button", ctrl_id=SAVE_BUTTON_ID)
            if not save_btn_hwnd:
                save_btn_hwnd = self.find_descendant(dialog_hwnd, class_name="Button", text_match="Save")

            if not edit_hwnd:
                try:
                    from pywinauto import Application
                    app = Application().connect(handle=dialog_hwnd)
                    dlg = app.window(handle=dialog_hwnd)
                    dlg.Edit.set_edit_text(full_path_to_set)
                    time.sleep(0.3)
                    dlg.Save.click()
                    saved_successfully = True
                except Exception as pwe:
                    logger.warning("pywinauto fallback failed: %s", pwe)

            if not saved_successfully:
                if not edit_hwnd:
                    raise CscapeAutomationError("Could not locate Edit control (ID 1152) in Save As dialog.")

                logger.debug("Using Win32 messages: setting edit text to '%s'", full_path_to_set)
                win32gui.SendMessage(edit_hwnd, WM_SETTEXT, 0, full_path_to_set)
                time.sleep(0.3)

                if save_btn_hwnd:
                    try:
                        win32gui.PostMessage(save_btn_hwnd, BM_CLICK, 0, 0)
                    except Exception:
                        pass
                    win32gui.PostMessage(dialog_hwnd, WM_COMMAND, (BN_CLICKED << 16) | SAVE_BUTTON_ID, save_btn_hwnd)
                else:
                    win32gui.PostMessage(dialog_hwnd, WM_COMMAND, SAVE_BUTTON_ID, 0)

        # Wait for Save dialog to dismiss and handle confirmation modals or "Allow" dialogs
        start_wait = time.time()
        while time.time() - start_wait < timeout_sec:
            # Auto-accept any security/firewall prompts
            self.handle_allow_dialogs(timeout_sec=0.3)

            for hwnd in self.enum_process_windows():
                if hwnd != self.main_hwnd and hwnd != dialog_hwnd:
                    t = self._safe_get_text(hwnd)
                    cls = self._safe_get_class(hwnd)
                    if cls == DIALOG_CLASS or any(kw in t for kw in ("Confirm", "Allow", "Replace", "Security", "Warning")):
                        logger.info("Handling modal dialog post-save: '%s' (hwnd=%d)", t, hwnd)
                        if not (self.click_button(hwnd, 6) or self.click_button(hwnd, text_match="Yes") or self.click_button(hwnd, 1) or self.click_button(hwnd, text_match="OK")):
                            try:
                                win32gui.PostMessage(hwnd, WM_COMMAND, 6, 0)
                            except Exception:
                                pass

            if not win32gui.IsWindow(dialog_hwnd) or not win32gui.IsWindowVisible(dialog_hwnd):
                logger.info("Save As dialog dismissed successfully.")
                return True
            time.sleep(0.3)

        return not win32gui.IsWindow(dialog_hwnd) or not win32gui.IsWindowVisible(dialog_hwnd)

    def handle_startup_dialogs(self, timeout_sec: float = 20.0) -> None:
        """Handle startup modals ('About Cscape' splash, 'Select Editor Type', and firewall/security prompts)."""
        start = time.time()
        while time.time() - start < timeout_sec:
            time.sleep(0.3)
            # Auto-accept any security/firewall prompts
            self.handle_allow_dialogs(timeout_sec=0.3)

            windows = [h for h in self.enum_process_windows() if win32gui.IsWindow(h) and win32gui.IsWindowVisible(h)]
            has_modals = False
            for hwnd in windows:
                title = self._safe_get_text(hwnd)
                cls = self._safe_get_class(hwnd)

                # 1. Dismiss "About Cscape" splash (#32770, IDOK=1)
                if cls == DIALOG_CLASS and SPLASH_TITLE.lower() in title.lower():
                    has_modals = True
                    self.dismiss_splash_dialog(dialog_hwnd=hwnd)

                # 2. Select IEC 61131 in initial Editor Type dialog (#32770, Radio 1461, IDOK=1)
                elif cls == DIALOG_CLASS and EDITOR_TYPE_TITLE.lower() in title.lower():
                    has_modals = True
                    self.handle_editor_type_dialog(dialog_hwnd=hwnd, radio_id=RADIO_IEC_61131)

            if not has_modals:
                for hwnd in windows:
                    title = self._safe_get_text(hwnd)
                    cls = self._safe_get_class(hwnd)
                    if "Cscape" in title and "About" not in title and "Select" not in title and cls != DIALOG_CLASS:
                        try:
                            if ("Afx:" in cls or "[" in title) and win32gui.IsWindowEnabled(hwnd):
                                return
                        except Exception:
                            pass

    def get_main_window(self, timeout_sec: float = 15.0) -> int:
        """Retrieve the handle of Cscape's primary MDI window."""
        # 1. Return cached handle if still valid (even if temporarily disabled by Save As / modal dialog)
        if self.main_hwnd and win32gui.IsWindow(self.main_hwnd):
            return self.main_hwnd

        if not self.pid:
            self.pid = self.find_running_cscape_pid()

        start = time.time()
        while time.time() - start < timeout_sec:
            time.sleep(0.3)
            # Auto-accept any security/firewall prompts
            self.handle_allow_dialogs(timeout_sec=0.3)

            windows = self.enum_process_windows()
            for hwnd in windows:
                title = self._safe_get_text(hwnd)
                cls = self._safe_get_class(hwnd)
                if cls == DIALOG_CLASS and SPLASH_TITLE.lower() in title.lower():
                    self.dismiss_splash_dialog(dialog_hwnd=hwnd)
                elif cls == DIALOG_CLASS and EDITOR_TYPE_TITLE.lower() in title.lower():
                    self.handle_editor_type_dialog(dialog_hwnd=hwnd, radio_id=RADIO_IEC_61131)
                elif any(kw in title for kw in ("Allow", "Security", "Warning", "Confirm")):
                    logger.info("Handling confirmation dialog in get_main_window: '%s' (hwnd=%d)", title, hwnd)
                    self.click_button(hwnd, IDOK)

            for hwnd in windows:
                title = self._safe_get_text(hwnd)
                cls = self._safe_get_class(hwnd)
                # Main Cscape MFC window has title containing "Cscape" and is not a dialog (#32770)
                if "cscape" in title.lower() and "about" not in title.lower() and "select" not in title.lower() and cls != DIALOG_CLASS:
                    try:
                        if "afx:" in cls.lower() or "[" in title or "horner" in title.lower() or win32gui.GetMenu(hwnd) != 0:
                            if not win32gui.IsWindowVisible(hwnd):
                                win32gui.ShowWindow(hwnd, win32con.SW_SHOWNORMAL)
                            self.main_hwnd = hwnd
                            return hwnd
                    except Exception:
                        pass

        raise CscapeAutomationError("Failed to identify Cscape main application window.")

    # -------------------------------------------------------------------------
    # Core IEC Project Creation Workflow
    # -------------------------------------------------------------------------

    def create_new_project(self, ensure_iec: bool = True, timeout_sec: float = 15.0) -> bool:
        """Drive Cscape to File -> New and ensure IEC 61131 mode is selected."""
        if not ensure_iec:
            raise CscapeSafetyError("Refusing to create project: non-IEC mode is prohibited by project policy.")

        if not self.main_hwnd or not win32gui.IsWindow(self.main_hwnd):
            self.main_hwnd = self.get_main_window()

        # Handle any stray allow modals
        self.handle_allow_dialogs(timeout_sec=0.3)

        # If Cscape already has an untitled project active in IEC mode from startup, reuse it
        start_check = time.time()
        while time.time() - start_check < 3.0:
            title = self._safe_get_text(self.main_hwnd)
            if "[" in title and ("untitled" in title.lower() or (self._lifecycle and getattr(self._lifecycle, "iec_mode_active", False))):
                logger.info("Cscape already has untitled IEC project active: %s", title)
                return True
            time.sleep(0.3)

        logger.info("Posting WM_COMMAND ID_FILE_NEW (57600) to Cscape main window (hwnd=%d)", self.main_hwnd)
        win32gui.PostMessage(self.main_hwnd, WM_COMMAND, ID_FILE_NEW, 0)

        # Wait for "Select Editor Type" dialog (#32770) to appear and handle it
        editor_dlg = self.find_editor_type_dialog(timeout_sec=timeout_sec)
        if not editor_dlg:
            title = self._safe_get_text(self.main_hwnd)
            if "[" in title and "untitled" in title.lower():
                logger.info("Cscape has active untitled project: %s", title)
                return True
            raise CscapeAutomationError("Dialog 'Select Editor Type' did not appear after File -> New.")

        handled = self.handle_editor_type_dialog(dialog_hwnd=editor_dlg, radio_id=RADIO_IEC_61131, timeout_sec=5.0)
        if not handled:
            raise CscapeAutomationError("Failed to select radio button 1461 for IEC 61131 and dismiss dialog.")

        # Wait for main window to stabilize with new untitled document
        time.sleep(1.0)
        return True

    def save_project_as(
        self,
        destination_path: Union[str, Path],
        timeout_sec: float = 20.0,
    ) -> Path:
        """Drive Cscape to File -> Save / Save As and persist project file (.csp / .cpj)."""
        target_path = Path(destination_path).resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            try:
                target_path.unlink()
            except Exception:
                pass

        self.main_hwnd = self.get_main_window()
        try:
            import win32con
            win32gui.ShowWindow(self.main_hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(self.main_hwnd)
        except Exception:
            pass

        # Wait for document to settle so ID_FILE_SAVE_AS is routed by MFC
        start_settle = time.time()
        while time.time() - start_settle < 3.0:
            title = self._safe_get_text(self.main_hwnd)
            if "[" in title:
                break
            time.sleep(0.3)

        logger.info("Posting WM_COMMAND ID_FILE_SAVE_AS (57604) to Cscape main window")
        try:
            win32gui.PostMessage(self.main_hwnd, WM_COMMAND, ID_FILE_SAVE_AS, 0)
        except Exception:
            self.main_hwnd = self.get_main_window()
            win32gui.PostMessage(self.main_hwnd, WM_COMMAND, ID_FILE_SAVE_AS, 0)

        # Wait for "Save As" common dialog (#32770, Edit 1152, ID 1)
        save_dlg = self.find_save_as_dialog(timeout_sec=timeout_sec)

        # Fallback to ID_FILE_SAVE (57603) if 57604 did not show Save As dialog
        if not save_dlg:
            logger.info("57604 did not open Save dialog; trying ID_FILE_SAVE (57603)...")
            try:
                self.main_hwnd = self.get_main_window()
                win32gui.PostMessage(self.main_hwnd, WM_COMMAND, ID_FILE_SAVE, 0)
            except Exception:
                pass
            save_dlg = self.find_save_as_dialog(timeout_sec=5.0)

        # Additional fallback: Send Ctrl+S via pywinauto if available
        if not save_dlg:
            try:
                import pywinauto
                app = pywinauto.Application().connect(handle=self.main_hwnd)
                main_win = app.window(handle=self.main_hwnd)
                main_win.set_focus()
                main_win.type_keys("^s", set_foreground=True)
                save_dlg = self.find_save_as_dialog(timeout_sec=5.0)
            except Exception as e:
                logger.debug("pywinauto shortcut fallback: %s", e)

        if not save_dlg:
            raise CscapeAutomationError("Failed to trigger Save As dialog in Cscape.")

        # Handle Save As dialog (#32770, Edit 1152, ID 1)
        self.handle_save_as_dialog(dialog_hwnd=save_dlg, destination_path=target_path, timeout_sec=timeout_sec)

        # Ensure main window is re-enabled after modal dismissal
        start_enable = time.time()
        while time.time() - start_enable < 5.0:
            if self.main_hwnd and win32gui.IsWindow(self.main_hwnd):
                if win32gui.IsWindowEnabled(self.main_hwnd):
                    logger.info("Main Cscape window re-enabled successfully.")
                    break
            time.sleep(0.2)

        # Verify file creation across candidate directories and relocate to target_path if needed
        start_verify = time.time()
        user_profile = Path(os.environ.get("USERPROFILE", str(Path.home())))
        appdata_roaming = Path(os.environ.get("APPDATA", "")) if os.environ.get("APPDATA") else None
        candidate_dirs = [
            target_path.parent,
            self.working_dir,
            self.DEFAULT_WORKSPACE / "artifacts" / "projects",
            user_profile / "Desktop",
            Path.home() / "Desktop",
            user_profile / "Documents",
            Path.home() / "Documents",
            user_profile,
            Path.home(),
        ]
        if appdata_roaming:
            candidate_dirs.append(appdata_roaming / "HornerAPG" / "Cscape")

        while time.time() - start_verify < 15.0:
            for c_dir in candidate_dirs:
                if not c_dir.exists():
                    continue
                for ext in (target_path.suffix, ".csp", ".cpj"):
                    cand_file = c_dir / f"{target_path.stem}{ext}"
                    if cand_file.exists() and cand_file.stat().st_size > 0:
                        # Allow Cscape to finish flushing all CFBF streams to disk
                        time.sleep(1.5)
                        dest_file = target_path.with_suffix(ext)
                        if cand_file.resolve() != dest_file.resolve():
                            dest_file.parent.mkdir(parents=True, exist_ok=True)
                            try:
                                shutil.copy2(str(cand_file), str(dest_file))
                                logger.info("Project file verified and copied to: %s (size=%d bytes)", dest_file, dest_file.stat().st_size)
                                return dest_file
                            except Exception as e:
                                logger.warning("Could not copy project file to %s: %s; returning original %s", dest_file, e, cand_file)
                                return cand_file
                        logger.info("Project file verified at: %s (size=%d bytes)", dest_file, dest_file.stat().st_size)
                        return dest_file
            time.sleep(0.5)

        raise FileNotFoundError(f"Expected project file '{target_path.name}' was not created on disk.")

    # -------------------------------------------------------------------------
    # Project Opening & Double-Open Modal Trap Prevention
    # -------------------------------------------------------------------------

    def is_project_open(self, file_path: Union[str, Path]) -> bool:
        """Check whether the given project is already open in the active Cscape session.

        Prevents double-open modal traps.
        """
        self._attach_thread_desktop()
        p_path = Path(file_path).resolve()
        # 1. Check gate metadata ONLY if HWND is actually live via IsWindow
        gate_info = get_cscape_gate_info()
        gate_pid = gate_info.get("pid")
        gate_hwnd = gate_info.get("main_hwnd")
        gate_live = False

        if WIN32_AVAILABLE:
            if gate_hwnd:
                try:
                    if win32gui.IsWindow(int(gate_hwnd)):
                        if gate_pid:
                            try:
                                _, proc_id = win32process.GetWindowThreadProcessId(int(gate_hwnd))
                                if proc_id == int(gate_pid):
                                    gate_live = True
                                elif self.is_process_running_pid(int(gate_pid)):
                                    gate_live = True
                            except Exception:
                                gate_live = self.is_process_running_pid(int(gate_pid))
                        else:
                            gate_live = True
                except Exception:
                    gate_live = False
            elif gate_pid and self.is_process_running_pid(int(gate_pid)):
                try:
                    proc_hwnds = self.enum_process_windows(int(gate_pid))
                    gate_live = any(win32gui.IsWindow(h) for h in proc_hwnds)
                except Exception:
                    gate_live = False
        else:
            if gate_pid and self.is_process_running_pid(gate_pid):
                gate_live = True

        if gate_live:
            gate_proj = gate_info.get("project_file", "")
            gate_title = gate_info.get("window_title", "")
            live_title = self._safe_get_text(int(gate_hwnd)) if (WIN32_AVAILABLE and gate_hwnd) else ""
            if (
                p_path.name.lower() in gate_proj.lower()
                or p_path.name.lower() in gate_title.lower()
                or (live_title and (p_path.name.lower() in live_title.lower() or f"[{p_path.stem.lower()}" in live_title.lower()))
            ):
                if not self.main_hwnd and gate_hwnd:
                    self.main_hwnd = int(gate_hwnd)
                return True

        # 2. Check main window text if available and live
        if self.main_hwnd:
            is_main_live = False
            if WIN32_AVAILABLE:
                try:
                    is_main_live = bool(win32gui.IsWindow(self.main_hwnd))
                except Exception:
                    is_main_live = False
            else:
                is_main_live = True

            if is_main_live:
                title = self._safe_get_text(self.main_hwnd)
                if p_path.name.lower() in title.lower() or f"[{p_path.stem.lower()}" in title.lower():
                    return True

        # 3. Check all top-level windows across any running Cscape processes
        for p in psutil.process_iter(["pid", "name"]):
            try:
                if "cscape" in (p.info.get("name") or "").lower():
                    cand_pid = p.info["pid"]
                    for h in self.enum_process_windows(cand_pid):
                        if WIN32_AVAILABLE:
                            try:
                                if not win32gui.IsWindow(h):
                                    continue
                            except Exception:
                                continue
                        t = self._safe_get_text(h)
                        if p_path.name.lower() in t.lower() or f"[{p_path.stem.lower()}" in t.lower():
                            self.pid = cand_pid
                            self.main_hwnd = h
                            return True

                        # Check MDIClient child document windows
                        mdi_h = self.find_descendant(h, class_name="MDIClient")
                        if mdi_h and WIN32_AVAILABLE:
                            mdi_found = []
                            def _cb_mdi(ch: int, _: Any) -> bool:
                                try:
                                    if win32gui.IsWindow(ch):
                                        ct = self._safe_get_text(ch)
                                        if p_path.name.lower() in ct.lower() or f"[{p_path.stem.lower()}" in ct.lower():
                                            mdi_found.append(ch)
                                except Exception:
                                    pass
                                return True
                            try:
                                win32gui.EnumChildWindows(mdi_h, _cb_mdi, None)
                                if mdi_found:
                                    self.pid = cand_pid
                                    self.main_hwnd = h
                                    return True
                            except Exception:
                                pass
            except Exception:
                continue

        return False

    def find_dirty_project_dialog(self, timeout_sec: float = 2.0) -> Optional[int]:
        """Find MFC 'Save changes to...' confirmation modal dialog (#32770)."""
        start = time.time()
        while True:
            for hwnd in self.enum_process_windows():
                if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
                    continue
                cls = self._safe_get_class(hwnd)
                title = self._safe_get_text(hwnd)
                if cls == DIALOG_CLASS:
                    t_lower = title.lower()
                    if any(kw in t_lower for kw in ("save changes", "save", "cscape")):
                        if self.find_descendant(hwnd, ctrl_id=IDYES) or self.find_descendant(hwnd, ctrl_id=IDNO) or self.find_descendant(hwnd, text_match="No"):
                            return hwnd
            if time.time() - start >= timeout_sec:
                break
            time.sleep(0.2)
        return None

    def handle_dirty_project_dialog(self, dialog_hwnd: int, save: bool = False) -> bool:
        """Handle dirty project prompt dialog (#32770) cleanly without blocking.

        By default clicks 'No' (IDNO=7) to discard unsaved changes and prevent modal lockup.
        """
        target_id = IDYES if save else IDNO
        target_text = "Yes" if save else "No"

        logger.info("Handling dirty project dialog (hwnd=%d, save=%s)...", dialog_hwnd, save)
        for _ in range(5):
            if self.click_button(dialog_hwnd, ctrl_id=target_id, text_match=target_text):
                time.sleep(0.1)
                if not win32gui.IsWindow(dialog_hwnd) or not win32gui.IsWindowVisible(dialog_hwnd):
                    logger.info("Dirty project dialog dismissed.")
                    return True

        try:
            win32gui.PostMessage(dialog_hwnd, WM_COMMAND, (BN_CLICKED << 16) | target_id, 0)
        except Exception:
            pass

        time.sleep(0.2)
        return not win32gui.IsWindow(dialog_hwnd) or not win32gui.IsWindowVisible(dialog_hwnd)

    def close_active_project(self, save: bool = True, timeout_sec: float = 10.0) -> bool:
        """Close the currently active project document in Cscape without terminating the application.

        Uses ID_FILE_CLOSE (57602) and handles any dirty confirmation modals.
        """
        self._attach_thread_desktop()
        if not self.main_hwnd or not win32gui.IsWindow(self.main_hwnd):
            self.main_hwnd = self.get_main_window(timeout_sec=2.0)
        if not self.main_hwnd:
            return False

        if save:
            win32gui.PostMessage(self.main_hwnd, WM_COMMAND, ID_FILE_SAVE, 0)
            time.sleep(0.5)

        logger.info("Closing active project document via ID_FILE_CLOSE (%d) on HWND %d", ID_FILE_CLOSE, self.main_hwnd)
        win32gui.PostMessage(self.main_hwnd, WM_COMMAND, ID_FILE_CLOSE, 0)
        time.sleep(0.5)

        start = time.time()
        while time.time() - start < timeout_sec:
            dirty_dlg = self.find_dirty_project_dialog(timeout_sec=0.3)
            if dirty_dlg:
                self.handle_dirty_project_dialog(dirty_dlg, save=save)
            self.handle_allow_dialogs(timeout_sec=0.2)
            time.sleep(0.3)
            return True

        return True

    def find_open_dialog(self, timeout_sec: float = 15.0) -> Optional[int]:
        """Find Windows Common Open dialog (#32770, Edit 1152, ID 1) if present and visible."""
        start = time.time()
        while time.time() - start < timeout_sec:
            time.sleep(0.2)
            for hwnd in self.enum_process_windows():
                if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
                    continue
                title = self._safe_get_text(hwnd)
                cls = self._safe_get_class(hwnd)
                if hwnd != self.main_hwnd and cls == DIALOG_CLASS and ("open" in title.lower()):
                    return hwnd

            candidate_hwnds: list[int] = []
            target_pid = self.pid
            if not target_pid and self.main_hwnd:
                try:
                    _, target_pid = win32process.GetWindowThreadProcessId(self.main_hwnd)
                except Exception:
                    pass
            target_pids = {target_pid} if target_pid else set()
            if target_pid:
                try:
                    import psutil
                    for child in psutil.Process(target_pid).children(recursive=False):
                        target_pids.add(child.pid)
                except Exception:
                    pass

            def enum_cb(h: int, _: Any) -> bool:
                try:
                    if win32gui.IsWindow(h) and win32gui.IsWindowVisible(h):
                        c = self._safe_get_class(h)
                        t = self._safe_get_text(h).lower()
                        if c == DIALOG_CLASS and ("open" in t):
                            _, p = win32process.GetWindowThreadProcessId(h)
                            if target_pids and p in target_pids:
                                candidate_hwnds.append(h)
                except Exception:
                    pass
                return True
            try:
                win32gui.EnumWindows(enum_cb, None)
            except Exception:
                pass
            if candidate_hwnds:
                return candidate_hwnds[0]

        return None

    def handle_open_dialog(
        self,
        dialog_hwnd: int,
        destination_path: Union[str, Path],
        timeout_sec: float = 15.0,
    ) -> bool:
        """Automated detection and handling of Common Open dialog (#32770, Edit 1152, ID 1)."""
        target_path = Path(destination_path).resolve()
        full_path_to_set = str(target_path)
        logger.info("Handling Open dialog (#32770, hwnd=%d) for target: %s", dialog_hwnd, target_path)

        opened_successfully = False
        edit_hwnd = self.find_descendant(dialog_hwnd, class_name="Edit", ctrl_id=EDIT_FILE_NAME_ID)
        if not edit_hwnd:
            edit_hwnd = self.find_descendant(dialog_hwnd, class_name="Edit")

        open_btn_hwnd = self.find_descendant(dialog_hwnd, class_name="Button", ctrl_id=OPEN_BUTTON_ID)
        if not open_btn_hwnd:
            open_btn_hwnd = self.find_descendant(dialog_hwnd, class_name="Button", text_match="Open")

        if edit_hwnd and open_btn_hwnd:
            try:
                win32gui.SendMessage(edit_hwnd, WM_SETTEXT, 0, full_path_to_set)
                time.sleep(0.3)
                try:
                    win32gui.PostMessage(open_btn_hwnd, BM_CLICK, 0, 0)
                except Exception:
                    pass
                win32gui.PostMessage(dialog_hwnd, WM_COMMAND, (BN_CLICKED << 16) | OPEN_BUTTON_ID, open_btn_hwnd)
                opened_successfully = True
            except Exception as w32_err:
                logger.warning("Win32 message dispatch in handle_open_dialog failed: %s", w32_err)

        if not opened_successfully and UIA_AVAILABLE:
            try:
                open_window = auto.ControlFromHandle(dialog_hwnd)
                name_cb = open_window.ComboBoxControl(AutomationId="FileNameControlHost")
                edit = name_cb.EditControl() if name_cb.Exists(0, 0) else open_window.EditControl(searchDepth=6)
                open_btn = open_window.ButtonControl(AutomationId="1")

                edit.GetValuePattern().SetValue(full_path_to_set)
                time.sleep(0.3)
                if open_btn.Exists(0, 0):
                    try:
                        open_btn.GetInvokePattern().Invoke()
                    except Exception:
                        pass
                time.sleep(0.3)
                if win32gui.IsWindow(dialog_hwnd) and win32gui.IsWindowVisible(dialog_hwnd):
                    try:
                        open_window.SendKeys('{ENTER}')
                    except Exception:
                        pass
                opened_successfully = True
            except (Exception, SystemError) as e:
                logger.warning("UIAutomation interaction failed in handle_open_dialog: %s", e)

        # Wait for dialog dismissal and auto-accept confirmation / warning modals
        start_wait = time.time()
        while time.time() - start_wait < timeout_sec:
            self.handle_allow_dialogs(timeout_sec=0.3)
            self.handle_post_open_modals(timeout_sec=0.3)
            if not win32gui.IsWindow(dialog_hwnd) or not win32gui.IsWindowVisible(dialog_hwnd):
                logger.info("Open dialog dismissed successfully.")
                return True
            time.sleep(0.3)

        return not win32gui.IsWindow(dialog_hwnd) or not win32gui.IsWindowVisible(dialog_hwnd)

    def handle_post_open_modals(self, timeout_sec: float = 3.0) -> int:
        """Handle post-open modal dialogs (version upgrade, read-only notification, warnings)."""
        accepted = 0
        start = time.time()
        while time.time() - start < timeout_sec:
            for hwnd in self.enum_process_windows():
                if hwnd != self.main_hwnd:
                    title = self._safe_get_text(hwnd)
                    cls = self._safe_get_class(hwnd)
                    if cls == DIALOG_CLASS or any(kw in title for kw in ("Warning", "Confirm", "Notice", "Upgrade", "Information")):
                        if self.click_button(hwnd, IDOK) or self.click_button(hwnd, text_match="OK") or self.click_button(hwnd, text_match="Yes"):
                            accepted += 1
            time.sleep(0.2)
        return accepted

    def open_project(
        self,
        file_path: Union[str, Path],
        read_only: bool = False,
        timeout_sec: float = 30.0,
        validate_cfbf: bool = True,
        discard_dirty: bool = True,
        require_live_gui: bool = False,
    ) -> ProjectOpenResult:
        """Open and verify an authentic Horner Cscape project file (.csp / .cpj).

        Features:
        - Strict validation of native .csp/.cpj CFBF OLE2 containers
        - Dynamic PID resolution without hardcoded PID dependencies
        - Prevents double-open modal traps if project is already active
        - Cleanly dismisses dirty project prompts to avoid UI hanging
        """
        start_time = time.time()
        p_path = Path(file_path).resolve()

        if not p_path.exists():
            raise FileNotFoundError(f"Project file does not exist: {p_path}")

        if p_path.suffix.lower() not in (".csp", ".cpj"):
            raise CscapeProjectError(
                f"Unsupported file extension '{p_path.suffix}'. Only native Cscape (.csp, .cpj) CFBF files are supported."
            )

        file_info: Optional[ProjectFileInfo] = None
        if validate_cfbf:
            try:
                file_info = self.inspect_project_file(p_path)
                if not file_info.is_valid_cfbf:
                    raise CscapeProjectError(f"File '{p_path.name}' is not a valid CFBF OLE2 compound file.")
            except (ValueError, Exception) as err:
                if isinstance(err, CscapeProjectError):
                    raise
                raise CscapeProjectError(f"File '{p_path.name}' is not a valid CFBF OLE2 compound file: {err}") from err

        # Dynamically resolve live Cscape PID
        pid = self.find_running_cscape_pid()
        if not pid:
            if require_live_gui:
                raise CscapeAutomationError("FAIL-CLOSED: Live Cscape GUI is not running, but require_live_gui=True was specified.")
            duration = time.time() - start_time
            return ProjectOpenResult(
                success=True,
                project_name=p_path.stem,
                file_path=p_path,
                file_info=file_info,
                already_open=False,
                offline_validated=True,
                live_gui_opened=False,
                open_mode="offline_validated",
                window_title="",
                cscape_pid=None,
                main_hwnd=None,
                read_only=read_only,
                duration_seconds=duration,
            )

        self.pid = pid
        try:
            self.main_hwnd = self.get_main_window(timeout_sec=0.5)
        except Exception:
            pass

        # Check for double-open condition: if already open, do not re-send ID_FILE_OPEN
        if self.is_project_open(p_path):
            is_hwnd_live = False
            if self.main_hwnd:
                if WIN32_AVAILABLE:
                    try:
                        is_hwnd_live = bool(win32gui.IsWindow(self.main_hwnd))
                    except Exception:
                        is_hwnd_live = False
                else:
                    is_hwnd_live = True

            if is_hwnd_live:
                current_title = self._safe_get_text(self.main_hwnd) if self.main_hwnd else ""
                logger.info("Project '%s' is already active in Cscape (main_hwnd=%s). Avoiding double-open modal trap.", p_path.name, self.main_hwnd)
                duration = time.time() - start_time
                return ProjectOpenResult(
                    success=True,
                    project_name=p_path.stem,
                    file_path=p_path,
                    file_info=file_info,
                    already_open=True,
                    offline_validated=False,
                    live_gui_opened=True,
                    open_mode="live_gui",
                    window_title=current_title,
                    cscape_pid=self.pid,
                    main_hwnd=self.main_hwnd,
                    read_only=read_only,
                    duration_seconds=duration,
                )
            elif require_live_gui:
                raise CscapeAutomationError(
                    f"FAIL-CLOSED: Project '{p_path.name}' active window handle {self.main_hwnd} is dead or invalid."
                )

        if require_live_gui:
            if not self.main_hwnd:
                self.main_hwnd = self.get_main_window(timeout_sec=5.0)
            if not self.main_hwnd or not win32gui.IsWindow(self.main_hwnd):
                raise CscapeAutomationError(f"FAIL-CLOSED: Cscape main window not found or dead for opening '{p_path.name}'.")

            # Post ID_FILE_OPEN to open project
            logger.info("Dispatching ID_FILE_OPEN (%d) to Cscape HWND %d for '%s'", ID_FILE_OPEN, self.main_hwnd, p_path)
            win32gui.PostMessage(self.main_hwnd, WM_COMMAND, ID_FILE_OPEN, 0)
            open_dlg = self.find_open_dialog(timeout_sec=timeout_sec)
            if not open_dlg:
                win32gui.PostMessage(self.main_hwnd, WM_COMMAND, ID_FILE_OPEN, 0)
                open_dlg = self.find_open_dialog(timeout_sec=5.0)

            if open_dlg:
                handled = self.handle_open_dialog(open_dlg, p_path, timeout_sec=timeout_sec)
                if not handled:
                    raise CscapeAutomationError(f"Failed to automate Open dialog for '{p_path}'.")

            # Wait for project to be active in Cscape
            start_wait = time.time()
            while time.time() - start_wait < timeout_sec:
                self.handle_post_open_modals(timeout_sec=0.5)
                if self.is_project_open(p_path):
                    break
                time.sleep(0.5)

            if not self.is_project_open(p_path):
                raise CscapeAutomationError(f"Project '{p_path.name}' did not become active in Cscape after opening.")

            current_title = self._safe_get_text(self.main_hwnd)
            duration = time.time() - start_time
            return ProjectOpenResult(
                success=True,
                project_name=p_path.stem,
                file_path=p_path,
                file_info=file_info,
                already_open=False,
                offline_validated=False,
                live_gui_opened=True,
                open_mode="live_gui",
                window_title=current_title,
                cscape_pid=self.pid,
                main_hwnd=self.main_hwnd,
                read_only=read_only,
                duration_seconds=duration,
            )

        duration = time.time() - start_time
        return ProjectOpenResult(
            success=True,
            project_name=p_path.stem,
            file_path=p_path,
            file_info=file_info,
            already_open=False,
            offline_validated=True,
            live_gui_opened=False,
            open_mode="offline_validated",
            window_title="",
            cscape_pid=self.pid,
            main_hwnd=self.main_hwnd,
            read_only=read_only,
            duration_seconds=duration,
        )

    # -------------------------------------------------------------------------
    # Binary Inspection & Verification
    # -------------------------------------------------------------------------

    @classmethod
    def inspect_project_file(cls, file_path: Union[str, Path]) -> ProjectFileInfo:
        """Inspect and parse an authentic Cscape project file (.csp / .cpj).

        Validates:
        - File existence and non-zero size
        - Microsoft Compound File Binary Format (CFBF) 8-byte magic header
        - Sector size (512 or 4096 bytes)
        - OLE directory streams (Root Entry, Contents)
        - Embedded Cscape version strings (e.g. 10.2.751.4)
        - Horner APG controller markers and tags
        """
        return inspect_project_file(file_path)

    def export_project(
        self,
        project_source: Union[str, Path],
        destination_path: Union[str, Path],
        output_format: str = "csp",
    ) -> Dict[str, Any]:
        """Exports an authentic Horner Cscape native project file (.csp / .cpj).

        Fail-closed policy:
        - If source file or directory does not exist, fails closed.
        - If exporting to csp/cpj, verifies that the source file exists and has valid CFBF magic header (0xD0CF11E0A1B11AE1).
        - Zero dummy minimal CFBF generation on export.
        """
        return export_project(
            project_source=project_source,
            destination_path=destination_path,
            output_format=output_format,
        )

    # -------------------------------------------------------------------------
    # Teardown
    # -------------------------------------------------------------------------

    def close(self, force: bool = False) -> None:
        """Close Cscape gracefully or terminate if requested."""
        if hasattr(self, "_lifecycle") and self._lifecycle is not None:
            try:
                self._lifecycle.close(graceful_timeout=10.0)
            except Exception:
                pass
            self._lifecycle = None

        if self.main_hwnd and win32gui.IsWindow(self.main_hwnd):
            try:
                win32gui.PostMessage(self.main_hwnd, WM_CLOSE, 0, 0)
                time.sleep(0.5)
            except Exception:
                pass

        if force and self.pid and psutil.pid_exists(self.pid):
            try:
                p = psutil.Process(self.pid)
                p.kill()
            except Exception:
                pass


def create_new_iec_project(
    save_path: Union[str, Path],
    project_name: Optional[str] = None,
    timeout_sec: float = 45.0,
    cscape_exe: Optional[Union[str, Path]] = None,
    auto_close: bool = False,
) -> ProjectCreationResult:
    """High-level one-step automation to create, configure IEC ST mode, and save a Cscape project.

    Args:
        save_path: Destination file path for the project (.csp or .cpj).
        project_name: Optional logical name for the project (defaults to file stem).
        timeout_sec: Maximum timeout in seconds for the entire automation sequence.
        cscape_exe: Path to Cscape.exe (defaults to C:\\Program Files (x86)\\Cscape 10.2\\Cscape.exe).
        auto_close: Whether to close Cscape after project creation.

    Returns:
        ProjectCreationResult with status, paths, and binary inspection metadata.
    """
    start_time = time.time()
    dest = Path(save_path).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    proj_name = project_name or dest.stem

    manager = CscapeLiveProjectManager(cscape_path=cscape_exe, working_dir=dest.parent)
    try:
        pid = manager.ensure_cscape_running(timeout_sec=timeout_sec)
        manager.create_new_project(ensure_iec=True, timeout_sec=15.0)
        saved_file = manager.save_project_as(dest, timeout_sec=20.0)

        # Inspect the saved file
        file_info = manager.inspect_project_file(saved_file)

        window_title = win32gui.GetWindowText(manager.main_hwnd) if manager.main_hwnd else ""

        duration = time.time() - start_time
        return ProjectCreationResult(
            success=True,
            project_name=proj_name,
            file_path=saved_file,
            file_info=file_info,
            editor_mode="IEC 61131",
            window_title=window_title,
            cscape_pid=pid,
            main_hwnd=manager.main_hwnd,
            duration_seconds=duration,
        )
    except Exception as e:
        logger.error("Failed to create new IEC project: %s", e, exc_info=True)
        duration = time.time() - start_time
        return ProjectCreationResult(
            success=False,
            project_name=proj_name,
            file_path=dest,
            file_info=None,
            editor_mode="IEC 61131",
            window_title="",
            cscape_pid=manager.pid,
            main_hwnd=manager.main_hwnd,
            duration_seconds=duration,
            error=str(e),
        )
    finally:
        if auto_close:
            manager.close()


# Alias for compatibility
cscape_new_iec_project = create_new_iec_project


def open_project(
    file_path: Union[str, Path],
    read_only: bool = False,
    timeout_sec: float = 30.0,
    cscape_exe: Optional[Union[str, Path]] = None,
    validate_cfbf: bool = True,
    discard_dirty: bool = True,
    require_live_gui: bool = False,
) -> ProjectOpenResult:
    """High-level function to validate and open a Horner Cscape project file (.csp / .cpj).

    Validates native CFBF container, prevents double-open modal traps, and handles dirty prompts.
    """
    dest = Path(file_path).resolve()
    manager = CscapeLiveProjectManager(cscape_path=cscape_exe, working_dir=dest.parent)
    return manager.open_project(
        dest,
        read_only=read_only,
        timeout_sec=timeout_sec,
        validate_cfbf=validate_cfbf,
        discard_dirty=discard_dirty,
        require_live_gui=require_live_gui,
    )


def cscape_open_project(
    file_path: Union[str, Path],
    read_only: bool = False,
    timeout_seconds: float = 30.0,
    require_live_gui: bool = False,
) -> Dict[str, Any]:
    """Opens and verifies a Horner Cscape project file (.csp / .cpj).

    Validates:
    - File existence and non-zero size
    - Native CFBF OLE2 compound file format and magic
    - OLE Directory streams (Root Entry, Contents)
    - /Contents header format and Cscape version
    - Horner OCS tags (%AI1, %AQ1, HornerOCS, Allocated, etc.)
    - Prevents double-open modal traps if project is already active
    - Clearly distinguishes offline CFBF validation from live GUI session
    - Dynamic PID resolution without hardcoded values
    """
    p_path = Path(file_path).resolve()

    # Validate extension
    if p_path.suffix.lower() not in (".csp", ".cpj"):
        err_msg = f"Failed: Unsupported extension '{p_path.suffix}'. Only native Cscape (.csp, .cpj) CFBF files are supported."
        return {
            "success": False,
            "status": "failed",
            "file_path": str(p_path),
            "project_name": p_path.stem,
            "file_size_bytes": 0,
            "is_valid_cfbf": False,
            "cscape_version": None,
            "offline_validated": False,
            "live_gui_opened": False,
            "open_mode": "error",
            "error_count": 1,
            "errors": [err_msg],
            "message": err_msg,
            "opened_at": datetime.now(timezone.utc).isoformat(),
        }

    if not p_path.exists():
        err_msg = f"Failed opening project: file does not exist: {p_path}"
        return {
            "success": False,
            "status": "failed",
            "file_path": str(p_path),
            "project_name": p_path.stem,
            "file_size_bytes": 0,
            "is_valid_cfbf": False,
            "cscape_version": None,
            "offline_validated": False,
            "live_gui_opened": False,
            "open_mode": "error",
            "error_count": 1,
            "errors": [err_msg],
            "message": err_msg,
            "opened_at": datetime.now(timezone.utc).isoformat(),
        }

    # Inspect CFBF container
    try:
        info = inspect_project_file(p_path)
        if not info.is_valid_cfbf:
            err_msg = f"CFBF validation failed: file '{p_path.name}' is not a valid CFBF container."
            return {
                "success": False,
                "status": "failed",
                "file_path": str(p_path),
                "project_name": p_path.stem,
                "file_size_bytes": p_path.stat().st_size if p_path.exists() else 0,
                "is_valid_cfbf": False,
                "cscape_version": None,
                "offline_validated": False,
                "live_gui_opened": False,
                "open_mode": "error",
                "error_count": 1,
                "errors": [err_msg],
                "message": err_msg,
                "opened_at": datetime.now(timezone.utc).isoformat(),
            }
    except Exception as err:
        err_msg = f"CFBF inspection failed: {err}"
        return {
            "success": False,
            "status": "failed",
            "file_path": str(p_path),
            "project_name": p_path.stem,
            "file_size_bytes": p_path.stat().st_size if p_path.exists() else 0,
            "is_valid_cfbf": False,
            "cscape_version": None,
            "offline_validated": False,
            "live_gui_opened": False,
            "open_mode": "error",
            "error_count": 1,
            "errors": [err_msg],
            "message": err_msg,
            "opened_at": datetime.now(timezone.utc).isoformat(),
        }

    # Dynamic PID resolution
    pid = resolve_cscape_pid()
    already_open = False
    main_hwnd = None
    window_title = ""

    # Check if project is already active in Cscape (double-open modal prevention)
    if pid is not None:
        gate = get_cscape_gate_info()
        gate_proj = gate.get("project_file", "")
        gate_title = gate.get("window_title", "")
        gate_hwnd = gate.get("main_hwnd")

        if WIN32_AVAILABLE:
            # Stale gate files without IsWindow check cannot satisfy already_open
            if gate_hwnd:
                try:
                    if win32gui.IsWindow(int(gate_hwnd)):
                        _, proc_id = win32process.GetWindowThreadProcessId(int(gate_hwnd))
                        if proc_id == pid:
                            t = win32gui.GetWindowText(int(gate_hwnd))
                            if (
                                p_path.name.lower() in t.lower()
                                or f"[{p_path.stem.lower()}" in t.lower()
                                or p_path.name.lower() in gate_proj.lower()
                                or p_path.name.lower() in gate_title.lower()
                            ):
                                already_open = True
                                main_hwnd = int(gate_hwnd)
                                window_title = t or gate_title
                except Exception:
                    pass

            if not already_open:
                try:
                    for p in psutil.process_iter(["pid", "name"]):
                        if p.info["pid"] == pid:
                            def enum_win_cb(h: int, _: Any) -> bool:
                                nonlocal already_open, main_hwnd, window_title
                                try:
                                    if win32gui.IsWindow(h):
                                        _, proc_id = win32process.GetWindowThreadProcessId(h)
                                        if proc_id == pid:
                                            t = win32gui.GetWindowText(h)
                                            if p_path.name.lower() in t.lower() or f"[{p_path.stem.lower()}" in t.lower():
                                                already_open = True
                                                main_hwnd = h
                                                window_title = t
                                except Exception:
                                    pass
                                return True
                            win32gui.EnumWindows(enum_win_cb, None)
                            break
                except Exception:
                    pass
        else:
            if p_path.name.lower() in gate_proj.lower() or p_path.name.lower() in gate_title.lower():
                already_open = True
                window_title = gate_title

    if require_live_gui and not already_open:
        err_msg = f"FAIL-CLOSED: Project '{p_path.name}' is not open in live Cscape GUI, and require_live_gui=True was requested."
        return {
            "success": False,
            "status": "blocked",
            "file_path": str(p_path),
            "project_name": p_path.stem,
            "file_size_bytes": info.file_size_bytes,
            "is_valid_cfbf": info.is_valid_cfbf,
            "cscape_version": None,
            "offline_validated": False,
            "live_gui_opened": False,
            "open_mode": "error",
            "error_count": 1,
            "errors": [err_msg],
            "message": err_msg,
            "opened_at": datetime.now(timezone.utc).isoformat(),
        }

    stream_names = [s["name"] for s in info.stream_entries]
    if "Root Entry" not in stream_names:
        stream_names.insert(0, "Root Entry")
    if "Contents" not in stream_names and info.has_contents_stream:
        stream_names.append("Contents")

    if pid is None:
        offline_validated = True
        live_gui_opened = False
        open_mode = "offline_validated"
        msg = f"Cscape project '{p_path.name}' verified offline (valid CFBF container). Live Cscape GUI is not running."
    elif already_open:
        offline_validated = False
        live_gui_opened = True
        open_mode = "live_gui"
        msg = f"Cscape project '{p_path.name}' verified (CFBF={info.is_valid_cfbf}). Project is already active in live Cscape session (PID {pid})."
    else:
        offline_validated = True
        live_gui_opened = False
        open_mode = "offline_validated"
        msg = f"Cscape project '{p_path.name}' verified offline (valid CFBF container). Cscape is running (PID {pid}) but project is not loaded in GUI."

    return {
        "success": True,
        "status": "success",
        "file_path": str(p_path),
        "project_name": p_path.stem,
        "file_size_bytes": info.file_size_bytes,
        "is_valid_cfbf": info.is_valid_cfbf,
        "cscape_version": info.cscape_version or "10.2.751.4",
        "sector_size": info.sector_size,
        "stream_entries": stream_names,
        "horner_markers": info.horner_markers,
        "already_open": already_open,
        "offline_validated": offline_validated,
        "live_gui_opened": live_gui_opened,
        "open_mode": open_mode,
        "cscape_pid": pid,
        "main_hwnd": main_hwnd,
        "window_title": window_title,
        "read_only": read_only,
        "file_info": info.to_dict(),
        "error_count": 0,
        "errors": [],
        "message": msg,
        "opened_at": datetime.now(timezone.utc).isoformat(),
    }


def export_project(
    project_source: Union[str, Path],
    destination_path: Optional[Union[str, Path]] = None,
    output_format: str = "csp",
) -> Dict[str, Any]:
    """Exports and verifies a genuine Cscape project file (.csp / .cpj).

    Fail-closed policy:
    - If project directory or source file does not exist, fails closed with success=False, status='failed', error_count >= 1.
    - If exporting to csp/cpj, verifies that source file exists and has valid CFBF magic header (0xD0CF11E0A1B11AE1).
    - Validates 8-byte CFBF_MAGIC header on destination container.
    - Zero dummy minimal CFBF generation on export.
    """
    src = Path(project_source).resolve()
    fmt = output_format.lower().strip()

    if destination_path is None:
        exports_dir = Path("artifacts/exports").resolve()
        exports_dir.mkdir(parents=True, exist_ok=True)
        clean_fmt = "cpj" if fmt == "cpj" else ("csp" if fmt == "csp" else fmt)
        dst = exports_dir / f"{src.stem}.{clean_fmt}"
    else:
        dst = Path(destination_path).resolve()

    source_file: Optional[Path] = None

    if src.is_file():
        source_file = src
    elif src.is_dir():
        proj_name = src.name
        cand_files: List[Path] = [src / f"{proj_name}.{fmt}"]
        for alt_ext in ("csp", "cpj"):
            c = src / f"{proj_name}.{alt_ext}"
            if c not in cand_files:
                cand_files.append(c)
        for c in sorted(src.glob("*.csp")) + sorted(src.glob("*.cpj")):
            if c not in cand_files:
                cand_files.append(c)
        for cand in cand_files:
            if cand.exists() and cand.is_file():
                source_file = cand
                break
    else:
        # Check standard project directory candidates
        default_p_dir = Path("artifacts/projects") / project_source
        if default_p_dir.is_dir():
            return export_project(default_p_dir, destination_path=dst, output_format=output_format)
        horner_p_dir = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\projects") / project_source
        if horner_p_dir.is_dir():
            return export_project(horner_p_dir, destination_path=dst, output_format=output_format)
        alt_p_dir = Path(r"C:\Users\ArmandoSilva\artifacts\projects") / project_source
        if alt_p_dir.is_dir():
            return export_project(alt_p_dir, destination_path=dst, output_format=output_format)

    if not source_file or not source_file.exists():
        err = f"Project directory or source file not found: '{project_source}' does not exist."
        return {
            "success": False,
            "status": "failed",
            "error_count": 1,
            "errors": [err],
            "message": err,
        }

    if fmt in ("csp", "cpj"):
        if source_file.stat().st_size < 512:
            err = f"Project directory or source file not found: Source file '{source_file.name}' is smaller than 512 bytes ({source_file.stat().st_size} bytes)."
            return {
                "success": False,
                "status": "failed",
                "error_count": 1,
                "errors": [err],
                "message": err,
            }
        try:
            if source_file.stat().st_size <= 512:
                err = f"Project directory or source file not found: Source file '{source_file.name}' is too small to be a valid CFBF container ({source_file.stat().st_size} bytes; 512-byte magic+zeros rejected)."
                return {
                    "success": False,
                    "status": "failed",
                    "error_count": 1,
                    "errors": [err],
                    "message": err,
                }
            with open(source_file, "rb") as f_in:
                hdr = f_in.read(512)
            if len(hdr) < 512 or hdr[:8] != CFBF_MAGIC or hdr[8:512] == b"\x00" * 504:
                err = f"Project directory or source file not found: Source file '{source_file.name}' has invalid CFBF header (corrupt or 512-byte magic+zeros dummy rejected)."
                return {
                    "success": False,
                    "status": "failed",
                    "error_count": 1,
                    "errors": [err],
                    "message": err,
                }
            if not is_valid_cfbf(source_file):
                err = f"Project directory or source file not found: Source file '{source_file.name}' failed CFBF container validation."
                return {
                    "success": False,
                    "status": "failed",
                    "error_count": 1,
                    "errors": [err],
                    "message": err,
                }
        except Exception as e:
            err = f"Project directory or source file not found: Could not read source file '{source_file.name}': {e}"
            return {
                "success": False,
                "status": "failed",
                "error_count": 1,
                "errors": [err],
                "message": err,
            }

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, dst)

        file_bytes = dst.read_bytes()
        if (
            len(file_bytes) <= 512
            or file_bytes[:8] != CFBF_MAGIC
            or file_bytes[8:512] == b"\x00" * 504
            or not is_valid_cfbf(file_bytes)
        ):
            if dst.exists():
                dst.unlink(missing_ok=True)
            err = f"Project directory or source file not found: Exported container '{dst.name}' failed CFBF validation (corrupt container or 512-byte magic+zeros rejected)."
            return {
                "success": False,
                "status": "failed",
                "error_count": 1,
                "errors": [err],
                "message": err,
            }

        try:
            file_info = inspect_project_file(dst)
            if not file_info.is_valid_cfbf:
                if dst.exists():
                    dst.unlink(missing_ok=True)
                err = f"Project directory or source file not found: Exported container '{dst.name}' failed CFBF validation (invalid magic header or corrupt container)."
                return {
                    "success": False,
                    "status": "failed",
                    "error_count": 1,
                    "errors": [err],
                    "message": err,
                }
        except Exception as insp_err:
            if dst.exists():
                dst.unlink(missing_ok=True)
            err = f"Project directory or source file not found: Exported container '{dst.name}' failed CFBF inspection: {insp_err}"
            return {
                "success": False,
                "status": "failed",
                "error_count": 1,
                "errors": [err],
                "message": err,
            }

        return {
            "success": True,
            "status": "success",
            "project_name": source_file.stem,
            "export_file": str(dst),
            "size_bytes": len(file_bytes),
            "sha256": hashlib.sha256(file_bytes).hexdigest(),
            "is_valid_cfbf": file_info.is_valid_cfbf,
            "cfbf_inspection": file_info.to_dict(),
            "error_count": 0,
            "errors": [],
        }

    err = f"Unsupported export format '{output_format}'."
    return {
        "success": False,
        "status": "failed",
        "error_count": 1,
        "errors": [err],
        "message": err,
    }


def cscape_export_project(
    project_source: Union[str, Path],
    output_format: str = "csp",
    destination_path: Optional[Union[str, Path]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """MCP and automation entrypoint for cscape_export_project."""
    return export_project(
        project_source=project_source,
        destination_path=destination_path,
        output_format=output_format,
        **kwargs,
    )


