"""Physical PLC Download Lockout Guard & Safety Auditor for Horner Cscape.

CRITICAL MANDATE: Absolute lockout of physical PLC connections and controller downloads.
Enforces:
1. Interception of ID_CONTROLLER_DOWNLOAD (32827) and ID_CONTROLLER_DOWNLOAD_ALT (33149),
   raising CscapeSafetyViolationError (and UnauthorizedDownloadError).
2. Blocking of serial/COM ports (COM1..COM256), CAN, USB, JTAG, and flashing executables.
3. Strict enforcement of pure software simulation (Horner OCS Simulation, SIMULATION).
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Union

from ..security.exceptions import (
    BlockedExecutableError,
    CscapeSafetyViolationError,
    DangerousArgumentError,
    DeviceNameViolationError,
    HardwareLockoutError,
    PathTraversalError,
    ReadOnlyViolationError,
    SandboxViolationError,
    SecurityError,
    UnauthorizedDownloadError,
)
from ..security.guard import SecurityGuard, SafetyGuard
from ..security.policy import (
    DEFAULT_BLOCKED_EXECUTABLES,
    DEFAULT_BLOCKED_FLAGS,
    DEFAULT_BLOCKED_HARDWARE_FLAGS,
    DEFAULT_BLOCKED_PORT_PATTERNS,
    DEFAULT_BLOCKED_PROTOCOLS,
    DEFAULT_BLOCKED_UI_COMMANDS,
    SafetyPolicy,
    SecurityConfig,
)
from ..automation.ui_automation import (
    BLOCKED_COMMAND_IDS,
    BLOCKED_INTERFACES,
    BLOCKED_MENU_ITEMS,
    BLOCKED_SHORTCUTS,
    BLOCKED_TOOLBAR_BUTTONS,
    ID_CLOSE_COMMUNICATION,
    ID_CONTROLLER_CONNECTIONWIZARD,
    ID_CONTROLLER_DOWNLOAD,
    ID_CONTROLLER_DOWNLOAD_ALT,
    ID_CONTROLLER_SETNETWORKID,
    ID_DEBUGOPTIONSELECTIONMENU_DOONLINECHANGE,
    ID_DEBUGOPTIONSELECTIONMENU_DOWNLOADONLINECHANGE,
    ID_ONLINECHANGEACTION,
    ID_ONLINECHANGECONNECT,
    ID_ONLINECHANGEREVERT,
    ID_OPEN_COMMUNICATION,
    ID_PLC_CLEARMEMORY,
    ID_PLC_DOWNLOAD,
    ID_PLC_UPLOAD,
    ID_PLC_VERIFY,
    ID_PROGRAM_DOWNLOADOPTIONS,
    ID_PROGRAM_SETNODEID,
    verify_cscape_hardware_lockout,
)

logger = logging.getLogger(__name__)

# Primary & Alternate Command IDs for Controller Download
ID_CONTROLLER_DOWNLOAD: int = 32827
ID_PROGRAM_DOWNLOAD: int = 32827  # Primary Win32 download command alias
ID_CONTROLLER_DOWNLOAD_ALT: int = 33149  # ID_PROGRAM_DOWNLOADOPTIONS alias
ID_PROGRAM_DOWNLOADOPTIONS: int = 33149

# Primary Blocked Download Command IDs
BLOCKED_DOWNLOAD_COMMAND_IDS: Set[Union[int, str]] = {
    ID_CONTROLLER_DOWNLOAD,
    "ID_CONTROLLER_DOWNLOAD",
    ID_PROGRAM_DOWNLOAD,
    "ID_PROGRAM_DOWNLOAD",
    ID_CONTROLLER_DOWNLOAD_ALT,
    "ID_CONTROLLER_DOWNLOAD_ALT",
    ID_PLC_DOWNLOAD,
    "ID_PLC_DOWNLOAD",
    ID_PLC_UPLOAD,
    "ID_PLC_UPLOAD",
    ID_PLC_VERIFY,
    "ID_PLC_VERIFY",
    ID_PLC_CLEARMEMORY,
    "ID_PLC_CLEARMEMORY",
    ID_PROGRAM_DOWNLOADOPTIONS,
    "ID_PROGRAM_DOWNLOADOPTIONS",
    ID_ONLINECHANGEACTION,
    "ID_ONLINECHANGEACTION",
    ID_ONLINECHANGECONNECT,
    "ID_ONLINECHANGECONNECT",
    ID_ONLINECHANGEREVERT,
    "ID_ONLINECHANGEREVERT",
    ID_DEBUGOPTIONSELECTIONMENU_DOWNLOADONLINECHANGE,
    "ID_DEBUGOPTIONSELECTIONMENU_DOWNLOADONLINECHANGE",
    ID_DEBUGOPTIONSELECTIONMENU_DOONLINECHANGE,
    "ID_DEBUGOPTIONSELECTIONMENU_DOONLINECHANGE",
    32827,
    33149,
    32828,
    32862,
    32993,
    38293,
    38294,
    38295,
    38296,
    38297,
    38372,
    38373,
    "ID_DOWNLOAD",
    "ID_DOWNLOAD_PROGRAM",
    "ID_CONTROLLER_FLASH",
    "ID_FIRMWARE_DOWNLOAD",
    "ID_FIRMWARE_UPDATE",
}

# Blocked Hardware Communication Command IDs
BLOCKED_HARDWARE_COMMAND_IDS: Set[Union[int, str]] = {
    ID_OPEN_COMMUNICATION,
    "ID_OPEN_COMMUNICATION",
    2112,
    ID_CLOSE_COMMUNICATION,
    "ID_CLOSE_COMMUNICATION",
    38458,
    ID_CONTROLLER_CONNECTIONWIZARD,
    "ID_CONTROLLER_CONNECTIONWIZARD",
    38269,
    ID_CONTROLLER_SETNETWORKID,
    "ID_CONTROLLER_SETNETWORKID",
    33049,
    ID_PROGRAM_SETNODEID,
    "ID_PROGRAM_SETNODEID",
    32850,
    "ID_CONTROLLER_CONNECT",
    "ID_HARDWARE_CONNECT",
}

# Blocked Executables Set
BLOCKED_FLASHING_EXECUTABLES: Set[str] = {
    "PGMUpdateUtility.exe",
    "DfuSeCommand.exe",
    "STMFlashLoader.exe",
    "WinJTAG.exe",
    "CscapeAutoUpdt.exe",
    "XLeTerm.exe",
    "DnCfg.exe",
    "DNXCfg.exe",
    "acs1x0cfg.exe",
    "jcm200cfg.exe",
    "jcm205cfg.exe",
    "st-link.exe",
    "dfu-util.exe",
    "openocd.exe",
    "jlink.exe",
}


def intercept_download_command(cmd_id: Union[int, str]) -> None:
    """Intercept physical controller download commands.
    
    Verifies that ID_CONTROLLER_DOWNLOAD (32827) and ID_CONTROLLER_DOWNLOAD_ALT (33149)
    are intercepted and raise CscapeSafetyViolationError (or UnauthorizedDownloadError).
    
    Raises:
        CscapeSafetyViolationError: If cmd_id matches any controller download command.
    """
    if isinstance(cmd_id, str):
        normalized = cmd_id.strip()
        if normalized.isdigit():
            normalized = int(normalized)
    else:
        normalized = cmd_id

    if normalized in BLOCKED_DOWNLOAD_COMMAND_IDS or str(normalized).lower() in {
        str(k).lower() for k in BLOCKED_DOWNLOAD_COMMAND_IDS
    }:
        raise CscapeSafetyViolationError(
            f"Physical controller download command '{cmd_id}' (ID_CONTROLLER_DOWNLOAD={ID_CONTROLLER_DOWNLOAD}, "
            f"ID_CONTROLLER_DOWNLOAD_ALT={ID_CONTROLLER_DOWNLOAD_ALT}) is strictly locked out. "
            "Zero physical PLC flashing permitted."
        )


def intercept_hardware_interface(interface_name: str, port: Optional[str] = None) -> None:
    """Intercept physical hardware communication interfaces.
    
    Verifies blocking of COM1..COM256, CAN, USB, JTAG, and physical ports.
    
    Raises:
        HardwareLockoutError: If interface matches any physical hardware port.
    """
    policy = SafetyPolicy()
    name = interface_name.strip() if (interface_name and isinstance(interface_name, str)) else ""
    port_str = port.strip() if (port and isinstance(port, str)) else ""

    if not name and not port_str:
        return

    is_blocked = False
    if name and (policy.is_interface_blocked(name) or policy.is_port_blocked(name)):
        is_blocked = True
    if port_str and (policy.is_port_blocked(port_str) or policy.is_interface_blocked(port_str)):
        is_blocked = True

    if is_blocked:
        raise HardwareLockoutError(
            f"Physical hardware interface '{interface_name}' (port='{port}') is locked out by SafetyPolicy. "
            "All physical COM/CAN/USB/JTAG communication is strictly prohibited.",
            details={"status": "blocked", "interface": interface_name, "port": port}
        )


def intercept_executable(exe_path: Union[str, Path]) -> None:
    """Intercept prohibited flashing and firmware update binaries.
    
    Raises:
        BlockedExecutableError: If executable is a prohibited flashing utility.
    """
    policy = SafetyPolicy()
    if policy.is_executable_blocked(str(exe_path)):
        raise BlockedExecutableError(
            f"Execution of prohibited flashing binary '{exe_path}' is strictly locked out.",
            details={"status": "blocked", "executable": str(exe_path)}
        )


class CscapeSafetyGuard(SecurityGuard):
    """Cscape-specialized Safety Guard extending SecurityGuard.
    
    Enforces absolute lockout of physical controller downloads and hardware ports.
    """

    def validate_download(
        self,
        target: Optional[str] = None,
        binary_path: Optional[Union[str, Path]] = None,
        destination: Optional[str] = None,
        target_plc: Optional[str] = None,
        port: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Unconditionally block controller downloads, accepting Cscape specific kwargs."""
        raise UnauthorizedDownloadError(
            f"Controller download rejected: target='{target or target_plc}', port='{port}', binary='{binary_path}'. "
            "Physical controller download operations are strictly prohibited."
        )

    def validate_hardware_connection(
        self,
        target: Optional[str] = None,
        port: Optional[str] = None,
        protocol: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Unconditionally block physical PLC connections."""
        raise HardwareLockoutError(
            f"Physical PLC connection rejected: target='{target}', port='{port}', protocol='{protocol}'. "
            "Physical hardware connections are permanently locked out by SafetyPolicy."
        )

    def validate_cscape_download(self, cmd_id: Union[int, str]) -> None:
        """Validate Cscape command ID against download lockout."""
        intercept_download_command(cmd_id)

    def validate_cscape_interface(self, interface: str) -> None:
        """Validate interface name against hardware lockout."""
        intercept_hardware_interface(interface)

    def validate_flashing_tool(self, tool_path: Union[str, Path]) -> None:
        """Validate flashing tool against binary lockout."""
        intercept_executable(tool_path)


__all__ = [
    ID_CONTROLLER_DOWNLOAD,
    ID_CONTROLLER_DOWNLOAD_ALT,
    ID_PROGRAM_DOWNLOAD,
    ID_PROGRAM_DOWNLOADOPTIONS,
    BLOCKED_DOWNLOAD_COMMAND_IDS,
    BLOCKED_HARDWARE_COMMAND_IDS,
    BLOCKED_FLASHING_EXECUTABLES,
    CscapeSafetyViolationError,
    HardwareLockoutError,
    UnauthorizedDownloadError,
    BlockedExecutableError,
    SecurityError,
    SecurityGuard,
    SafetyGuard,
    SafetyPolicy,
    SecurityConfig,
    CscapeSafetyGuard,
    intercept_download_command,
    intercept_hardware_interface,
    intercept_executable,
    verify_cscape_hardware_lockout,
]
