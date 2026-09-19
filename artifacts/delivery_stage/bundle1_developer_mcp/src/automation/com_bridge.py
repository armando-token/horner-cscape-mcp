"""Optional COM / OLE automation helper using pywin32 with CLI/file-based fallback.

Inspects Windows registry for registered Cscape / Straton COM automation interfaces,
attempts safe dispatch or active object binding if available, and provides complete,
seamless fallback to CLI and file-based toolchain manipulation.
"""

from __future__ import annotations

import logging
import platform
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from .cli_runner import CLIRunner
from .process_manager import ProcessResult, is_windows
from .ui_automation import CscapeUIAutomation
from ..security.exceptions import HardwareLockoutError, UnauthorizedDownloadError
from ..security.guard import SecurityGuard

logger = logging.getLogger(__name__)

# Candidate ProgIDs to probe for Cscape / Straton automation
CANDIDATE_PROGIDS: tuple[str, ...] = (
    "Cscape.Application",
    "Cscape.Application.1",
    "Horner.Cscape",
    "Horner.Cscape.1",
    "Straton.Application",
    "K5.Application",
    "cpj.Cscape",
    "csp.Cscape",
)


@dataclass
class COMStatus:
    """Diagnostic status of COM automation capability."""
    pywin32_available: bool
    python_bitness: int
    com_initialized: bool = False
    registered_progids: list[str] = field(default_factory=list)
    active_automation_progid: Optional[str] = None
    is_active_object_found: bool = False
    details: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert status to dictionary."""
        return {
            "pywin32_available": self.pywin32_available,
            "python_bitness": self.python_bitness,
            "com_initialized": self.com_initialized,
            "registered_progids": self.registered_progids,
            "active_automation_progid": self.active_automation_progid,
            "is_active_object_found": self.is_active_object_found,
            "details": self.details,
            "diagnostics": self.diagnostics,
        }


def get_python_bitness() -> int:
    """Return current Python interpreter bitness (32 or 64)."""
    return struct.calcsize("P") * 8


def scan_registry_progids(keywords: Sequence[str] = ("cscape", "straton", "horner")) -> list[str]:
    """Scan HKEY_CLASSES_ROOT for registered ProgIDs matching keywords."""
    found: list[str] = []
    if not is_windows():
        return found

    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "") as root:
            idx = 0
            while True:
                try:
                    key_name = winreg.EnumKey(root, idx)
                    idx += 1
                    lower_name = key_name.lower()
                    if any(kw in lower_name for kw in keywords):
                        found.append(key_name)
                except OSError:
                    break
    except Exception as e:
        logger.warning("Error scanning registry for ProgIDs: %s", e)

    return sorted(found)


def inspect_progid(progid: str) -> dict[str, Any]:
    """Inspect a ProgID in HKEY_CLASSES_ROOT for CLSID and shell verbs."""
    result: dict[str, Any] = {
        "progid": progid,
        "description": None,
        "clsid": None,
        "has_clsid": False,
        "shell_open_command": None,
        "is_automation_server": False,
    }
    if not is_windows():
        return result

    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid) as key:
            try:
                result["description"] = winreg.QueryValue(key, "")
            except OSError:
                pass

            # Check for CLSID (required for COM Automation Dispatch)
            try:
                with winreg.OpenKey(key, "CLSID") as clsid_key:
                    clsid_val = winreg.QueryValue(clsid_key, "")
                    result["clsid"] = clsid_val
                    result["has_clsid"] = True
                    result["is_automation_server"] = True
            except OSError:
                pass

            # Check for shell open command (file association)
            try:
                with winreg.OpenKey(key, r"shell\open\command") as cmd_key:
                    result["shell_open_command"] = winreg.QueryValue(cmd_key, "")
            except OSError:
                pass

    except Exception as e:
        result["error"] = str(e)

    return result


def check_com_environment() -> COMStatus:
    """Safely check the Windows COM automation environment and Cscape registrations."""
    bitness = get_python_bitness()
    status = COMStatus(
        pywin32_available=False,
        python_bitness=bitness,
    )

    if not is_windows():
        status.diagnostics.append("Non-Windows OS platform; COM is not supported.")
        return status

    # Check pywin32 availability
    try:
        import pythoncom
        import win32com.client
        status.pywin32_available = True
        status.diagnostics.append("pywin32 (pythoncom & win32com.client) is available.")
    except ImportError as e:
        status.diagnostics.append(f"pywin32 is not installed or import failed: {e}")
        return status

    # Scan registry for relevant ProgIDs
    found_progids = scan_registry_progids()
    status.registered_progids = found_progids
    status.diagnostics.append(f"Discovered matching registry ProgIDs: {found_progids}")

    # Inspect each candidate and discovered ProgID
    all_to_inspect = set(CANDIDATE_PROGIDS) | set(found_progids)
    for progid in sorted(all_to_inspect):
        info = inspect_progid(progid)
        status.details[progid] = info

        # If has CLSID, attempt test dispatch
        if info.get("has_clsid"):
            try:
                import pythoncom
                import win32com.client
                pythoncom.CoInitialize()
                try:
                    # Test GetActiveObject first
                    active_obj = win32com.client.GetActiveObject(progid)
                    status.active_automation_progid = progid
                    status.is_active_object_found = True
                    status.diagnostics.append(f"Active COM object successfully acquired for: {progid}")
                    break
                except Exception:
                    pass

                # Test Dispatch
                disp = win32com.client.Dispatch(progid)
                if disp is not None:
                    status.active_automation_progid = progid
                    status.diagnostics.append(f"COM Dispatch successfully initialized for: {progid}")
                    break
            except Exception as e:
                status.diagnostics.append(f"COM Dispatch failed for {progid}: {e}")
            finally:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    if not status.active_automation_progid:
        status.diagnostics.append(
            "No active Cscape COM OLE Automation server registered. "
            "System will utilize robust CLI / file-based toolchain fallback."
        )

    return status


class CscapeAutomationBridge:
    """Unified automation bridge offering COM control when available with seamless CLI fallback."""

    def __init__(
        self,
        cli_runner: Optional[CLIRunner] = None,
        prefer_com: bool = True,
    ) -> None:
        self.cli_runner = cli_runner or CLIRunner()
        self.prefer_com = prefer_com
        self.status: COMStatus = check_com_environment()
        self._com_app: Any = None
        self._initialized_com = False

        if self.prefer_com and self.status.active_automation_progid:
            self._init_com()

    @property
    def mode(self) -> Literal["com", "cli_fallback"]:
        """Active automation mode ('com' or 'cli_fallback')."""
        return "com" if self._com_app is not None else "cli_fallback"

    @property
    def is_com_active(self) -> bool:
        """True if currently operating with an active COM automation client."""
        return self._com_app is not None

    def _init_com(self) -> bool:
        """Attempt to instantiate or bind to the COM object."""
        if not self.status.active_automation_progid:
            return False

        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            self._initialized_com = True
            progid = self.status.active_automation_progid
            logger.info("Initializing COM client for ProgID: %s", progid)

            try:
                self._com_app = win32com.client.GetActiveObject(progid)
                logger.info("Bound to existing active COM object: %s", progid)
                return True
            except Exception:
                pass

            self._com_app = win32com.client.Dispatch(progid)
            logger.info("Created new instance of COM object: %s", progid)
            return True
        except Exception as e:
            logger.warning("Failed to initialize COM object: %s", e)
            self._com_app = None
            return False

    def open_project(
        self,
        project_path: Union[str, Path],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Open a Cscape project via COM if connected, otherwise via CLI fallback."""
        proj = Path(project_path).resolve()
        if not proj.exists():
            raise FileNotFoundError(f"Project file not found: {proj}")

        if self.mode == "com" and self._com_app is not None:
            try:
                logger.info("Opening project via COM: %s", proj)
                # Call common automation methods if present
                for method_name in ("OpenProject", "Open", "LoadProject"):
                    if hasattr(self._com_app, method_name):
                        res = getattr(self._com_app, method_name)(str(proj))
                        return {
                            "status": "success",
                            "mode": "com",
                            "method": method_name,
                            "result": str(res),
                            "project_path": str(proj),
                        }
            except Exception as e:
                logger.warning("COM open_project failed (%s), falling back to CLI: %s", e, proj)

        # CLI Fallback
        logger.info("Executing open_project via CLI fallback: %s", proj)
        proc_res = self.cli_runner.launch_project(proj, timeout=timeout)
        return {
            "status": "success" if proc_res.returncode == 0 and not proc_res.timed_out else "failed",
            "mode": "cli_fallback",
            "project_path": str(proj),
            "pid": proc_res.pid,
            "returncode": proc_res.returncode,
            "duration_seconds": proc_res.duration_seconds,
            "artifact_log": proc_res.metadata.get("artifact_log"),
        }

    def compile_project(
        self,
        project_path: Union[str, Path],
        output_dir: Optional[Union[str, Path]] = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        """Compile a Cscape/Straton project via COM or toolchain CLI fallback."""
        proj = Path(project_path).resolve()
        if not proj.exists():
            raise FileNotFoundError(f"Project file not found: {proj}")

        if self.mode == "com" and self._com_app is not None:
            try:
                for method_name in ("Compile", "Build", "BuildAll", "CompileProject"):
                    if hasattr(self._com_app, method_name):
                        res = getattr(self._com_app, method_name)(str(proj))
                        return {
                            "status": "success",
                            "mode": "com",
                            "method": method_name,
                            "result": str(res),
                            "project_path": str(proj),
                        }
            except Exception as e:
                logger.warning("COM compile failed (%s), falling back to CLI", e)

        # CLI Fallback - Verify installation and invoke toolchain
        install_info = self.cli_runner.verify_installation()
        return {
            "status": "failed",
            "mode": "cli_fallback",
            "project_path": str(proj),
            "output_dir": str(output_dir) if output_dir else None,
            "toolchain_ready": install_info.is_installed,
            "error_code": "CLI_COMPILATION_UNAVAILABLE",
            "errors": [
                "Cscape CLI compilation fallback requires active live compiler process or COM automation; "
                "presence of toolchain binaries alone does not constitute successful compilation."
            ],
            "message": "CLI compilation fallback failed: toolchain is installed but headless CLI compile pass is not executed.",
        }

    @property
    def ui(self) -> CscapeUIAutomation:
        """Access Cscape UI automation controller."""
        if not hasattr(self, "_ui") or self._ui is None:
            self._ui = CscapeUIAutomation()
        return self._ui

    def download_project(self, *args: Any, **kwargs: Any) -> None:
        """Unconditionally blocked: Controller download is strictly prohibited.

        Raises:
            UnauthorizedDownloadError: Always.
        """
        SecurityGuard().validate_download(*args, **kwargs)

    def download_to_controller(self, *args: Any, **kwargs: Any) -> None:
        """Unconditionally blocked: Controller download is strictly prohibited.

        Raises:
            UnauthorizedDownloadError: Always.
        """
        SecurityGuard().validate_download(*args, **kwargs)

    def connect_hardware(self, *args: Any, **kwargs: Any) -> None:
        """Unconditionally blocked: Physical hardware connections are locked out.

        Raises:
            HardwareLockoutError: Always.
        """
        SecurityGuard().validate_hardware_connection(*args, **kwargs)

    def configure_interface(
        self,
        interface: str,
        port: Optional[str] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Configure Cscape interface, blocking any physical COM, CAN, or USB interfaces.

        Raises:
            HardwareLockoutError: If attempting to configure physical hardware interfaces.
        """
        return self.ui.configure_interface(interface, port=port, **kwargs)

    def get_diagnostics(self) -> dict[str, Any]:
        """Provide detailed diagnostics on COM status, registry mappings, and fallback mode."""
        install_info = self.cli_runner.verify_installation()
        return {
            "mode": self.mode,
            "is_com_active": self.is_com_active,
            "platform": platform.platform(),
            "python_bitness": self.status.python_bitness,
            "pywin32_available": self.status.pywin32_available,
            "com_status": self.status.to_dict(),
            "cscape_installation": install_info.to_dict(),
            "strategy": (
                "Native COM Automation"
                if self.mode == "com"
                else "Headless CLI & File-Based Automation (Safe WOW64 Toolchain Integration)"
            ),
        }

    def close(self) -> None:
        """Release any active COM resources and uninitialize COM library."""
        if self._com_app is not None:
            try:
                del self._com_app
            except Exception:
                pass
            self._com_app = None

        if self._initialized_com:
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception:
                pass
            self._initialized_com = False

    def __enter__(self) -> "CscapeAutomationBridge":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


CscapeComBridge = CscapeAutomationBridge
