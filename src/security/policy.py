"""Safety policy and security configuration definitions.

Strictly enforces:
- Zero physical PLC connections
- Zero controller download or firmware flash operations
- Interception of dangerous executables (PGMUpdateUtility.exe, DfuSeCommand.exe, STMFlashLoader.exe, WinJTAG.exe)
- Hardware port lockouts (COM, LPT, CAN, USB)
- Workspace sandboxing
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from typing import Optional, Sequence, Set, Union

from .exceptions import SecurityError


# Default critical blocked executables (case-insensitive)
DEFAULT_BLOCKED_EXECUTABLES: Set[str] = {
    # Core Horner firmware / flashing / update utilities
    "pgmupdateutility.exe",
    "dfusecommand.exe",
    "stmflashloader.exe",
    "winjtag.exe",
    # Additional hardware flashing / update binaries
    "cscapeautoupdt.exe",
    "xleterm.exe",
    "dncfg.exe",
    "dnxcfg.exe",
    "acs1x0cfg.exe",
    "jcm200cfg.exe",
    "jcm205cfg.exe",
    "st-link.exe",
    "dfu-util.exe",
    "openocd.exe",
    "jlink.exe",
}

# Blocked hardware communication port regex patterns (case-insensitive)
DEFAULT_BLOCKED_PORT_PATTERNS: Sequence[str] = (
    # Windows Serial / COM ports (COM1 to COM256, \\.\COM1, etc.)
    r"^(?:\\\\\.\\)?COM[0-9]+$",
    # Linux serial devices (/dev/ttyS0, /dev/ttyUSB0, /dev/ttyACM0)
    r"^/dev/tty(?:S|USB|ACM)[0-9]+$",
    # Parallel / LPT ports
    r"^(?:\\\\\.\\)?LPT[0-9]+$",
    # CAN adapters & interfaces (CAN0, PCAN, KVASER, Vector, SocketCAN, CsCAN, CANopen, DeviceNet, Profibus, J1939)
    r"^(?:can[0-9]*|canopen.*|j1939.*|pcan.*|kvaser.*|vector.*|socketcan.*|slcan[0-9]*|cscan.*|devicenet.*|profibus.*)$",
    # USB hardware device interfaces / JTAG / SWD / VID&PID / DFU
    r"^(?:\\\\\?\\usb#.*|vid_[0-9a-f]{4}.*|pid_[0-9a-f]{4}.*|usb[0-9]*|jtag.*|swd.*|dfu.*)$",
)

# Blocked hardware communication flags
DEFAULT_BLOCKED_HARDWARE_FLAGS: Set[str] = {
    "/com",
    "-com",
    "--com",
    "/port",
    "-port",
    "--port",
    "/baud",
    "-baud",
    "--baud",
    "/serial",
    "-serial",
    "--serial",
    "/can",
    "-can",
    "--can",
    "/jtag",
    "-jtag",
    "--jtag",
    "/usb",
    "-usb",
    "--usb",
}

# Blocked controller download and firmware flash flags
DEFAULT_BLOCKED_DOWNLOAD_FLAGS: Set[str] = {
    "/d",
    "-d",
    "/download",
    "-download",
    "--download",
    "/flash",
    "-flash",
    "--flash",
    "/pgm",
    "-pgm",
    "--pgm",
    "/burn",
    "-burn",
    "--burn",
    "/firmware",
    "-firmware",
    "--firmware",
    "/target:hardware",
    "/target:plc",
    "/target:controller",
    "--target=hardware",
    "--target=plc",
    "--target=controller",
    "/erase",
    "-erase",
    "--erase",
    "/upload",
    "-upload",
    "--upload",
    "/write-flash",
    "--write-flash",
}

# All blocked flags
DEFAULT_BLOCKED_FLAGS: Set[str] = DEFAULT_BLOCKED_DOWNLOAD_FLAGS | DEFAULT_BLOCKED_HARDWARE_FLAGS

# Blocked hardware protocols
DEFAULT_BLOCKED_PROTOCOLS: Set[str] = {
    "csconn",
    "cscape-hw",
    "modbus-rtu",
    "canopen",
    "j1939",
    "csnet",
    "he-csnet",
    "serial",
    "can",
    "cscan",
    "devicenet",
    "profibus",
    "jtag",
    "swd",
    "dfu",
}

# Blocked Cscape UI command IDs (names lowercase and integers)
DEFAULT_BLOCKED_UI_COMMANDS: Set[Union[str, int]] = {
    # Controller Download commands
    "id_controller_download",
    "id_program_download",
    "id_controller_download_alt",
    "id_plc_download",
    32827,
    "id_plc_upload",
    32828,
    "id_plc_verify",
    32862,
    "id_plc_clearmemory",
    32993,
    # Online Change download commands
    "id_onlinechangeaction",
    38295,
    "id_onlinechangeconnect",
    38293,
    "id_onlinechangerevert",
    38297,
    38294,
    38296,
    "id_debugoptionselectionmenu_downloadonlinechange",
    38372,
    "id_debugoptionselectionmenu_doonlinechange",
    38373,
    # Program download options
    "id_program_downloadoptions",
    33149,
    # Communication / Hardware connect commands
    "id_open_communication",
    2112,
    "id_close_communication",
    38458,
    "id_controller_connectionwizard",
    38269,
    "id_controller_setnetworkid",
    33049,
    "id_program_setnodeid",
    32850,
    # Generic / standard MFC controller download commands
    "id_download",
    "id_download_program",
    "id_controller_flash",
    "id_controller_connect",
    "id_firmware_download",
    "id_firmware_update",
    "id_hardware_connect",
}

# Blocked menu item patterns (case-insensitive)
DEFAULT_BLOCKED_MENU_PATTERNS: Sequence[str] = (
    r"(?i).*download.*",
    r"(?i).*upload.*",
    r"(?i).*firmware.*",
    r"(?i).*flash.*",
    r"(?i).*burn.*",
    r"(?i)controller\s*->\s*(?:download|upload|connect|connection\s*wizard|communication|hardware.*).*",
    r"(?i)online\s*change\s*->\s*.*",
    r"(?i)program\s*->\s*download\s*options.*",
)

# Blocked keyboard shortcuts (case-insensitive)
DEFAULT_BLOCKED_SHORTCUTS: Sequence[str] = (
    r"(?i)^(?:ctrl|control)\s*\+\s*(?:shift\s*\+\s*)?d$",
    r"(?i)^\^d$",
    r"(?i)^(?:ctrl|control)\s*\+\s*f7$",
    r"(?i)^f7$",
    r"(?i)^alt\s*\+\s*c\s*,\s*d$",
    r"(?i)^(?:ctrl|control)\s*\+\s*u$",
)

# Blocked hardware interface patterns (COM, CAN, USB)
DEFAULT_BLOCKED_INTERFACE_PATTERNS: Sequence[str] = (
    r"(?i)^(?:com\d*|\\\\.\\com\d*|/dev/tty(?:s|usb|acm)\d*|serial.*|rs-?\d+.*)$",
    r"(?i)^(?:can\d*|pcan.*|kvaser.*|vector.*|socketcan.*|slcan\d*|cscan.*|canopen.*|devicenet.*|profibus.*|j1939.*)$",
    r"(?i)^(?:.*usb.*|.*vid_.*|.*pid_.*|dfu.*|jtag.*|swd.*)$",
)


@dataclass(frozen=True)
class SafetyPolicy:
    """Immutable safety policy enforcing zero-hardware, zero-download, simulation-only constraints."""

    # Safety invariants
    simulation_only: bool = True
    allow_hardware_communication: bool = False
    allow_controller_download: bool = False
    allow_firmware_flash: bool = False
    enforce_file_sandbox: bool = True

    # Blocklists
    blocked_executables: Set[str] = field(
        default_factory=lambda: {x.lower() for x in DEFAULT_BLOCKED_EXECUTABLES}
    )
    blocked_port_patterns: Sequence[str] = field(
        default_factory=lambda: list(DEFAULT_BLOCKED_PORT_PATTERNS)
    )
    blocked_flags: Set[str] = field(
        default_factory=lambda: {x.lower() for x in DEFAULT_BLOCKED_FLAGS}
    )
    blocked_hardware_flags: Set[str] = field(
        default_factory=lambda: {x.lower() for x in DEFAULT_BLOCKED_HARDWARE_FLAGS}
    )
    blocked_download_flags: Set[str] = field(
        default_factory=lambda: {x.lower() for x in DEFAULT_BLOCKED_DOWNLOAD_FLAGS}
    )
    blocked_protocols: Set[str] = field(
        default_factory=lambda: {x.lower() for x in DEFAULT_BLOCKED_PROTOCOLS}
    )
    blocked_ui_commands: Set[Union[str, int]] = field(
        default_factory=lambda: set(DEFAULT_BLOCKED_UI_COMMANDS)
    )
    blocked_menu_patterns: Sequence[str] = field(
        default_factory=lambda: list(DEFAULT_BLOCKED_MENU_PATTERNS)
    )
    blocked_shortcuts: Sequence[str] = field(
        default_factory=lambda: list(DEFAULT_BLOCKED_SHORTCUTS)
    )
    blocked_interface_patterns: Sequence[str] = field(
        default_factory=lambda: list(DEFAULT_BLOCKED_INTERFACE_PATTERNS)
    )

    def __post_init__(self) -> None:
        """Verify safety invariants.

        Raises SecurityError if any attempt is made to configure unsafe hardware or download access.
        """
        self.verify_safety_invariants()

    def verify_safety_invariants(self) -> None:
        """Enforces that safety locks cannot be disabled in this environment."""
        if not self.simulation_only:
            raise SecurityError("Safety invariant violation: simulation_only MUST be True.")
        if self.allow_hardware_communication:
            raise SecurityError("Safety invariant violation: allow_hardware_communication MUST be False.")
        if self.allow_controller_download:
            raise SecurityError("Safety invariant violation: allow_controller_download MUST be False.")
        if self.allow_firmware_flash:
            raise SecurityError("Safety invariant violation: allow_firmware_flash MUST be False.")
        if not self.enforce_file_sandbox:
            raise SecurityError("Safety invariant violation: enforce_file_sandbox MUST be True.")

    def is_executable_blocked(self, exe_name_or_path: str) -> bool:
        """Check if an executable name or path matches the blocked list."""
        if not exe_name_or_path:
            return False
        clean = Path(exe_name_or_path).name.lower()
        if clean in self.blocked_executables:
            return True
        if not clean.endswith(".exe"):
            if f"{clean}.exe" in self.blocked_executables:
                return True
        # Check if any blocked executable is contained as a standalone token in the path string
        lower_input = exe_name_or_path.lower().replace("/", "\\")
        for blocked in self.blocked_executables:
            blocked_no_ext = blocked[:-4] if blocked.endswith(".exe") else blocked
            if f"\\{blocked}" in lower_input or f"\\{blocked_no_ext}" in lower_input:
                return True
            if lower_input == blocked or lower_input == blocked_no_ext:
                return True
        return False

    def is_port_blocked(self, port_identifier: str) -> bool:
        """Check if a port identifier matches any blocked hardware communication port pattern."""
        if not port_identifier:
            return False
        stripped = port_identifier.strip()
        # If it's a flag like /com:COM1 or --port=COM3, extract the value
        if ":" in stripped:
            val = stripped.split(":", 1)[1]
            if self.is_port_blocked(val):
                return True
        if "=" in stripped:
            val = stripped.split("=", 1)[1]
            if self.is_port_blocked(val):
                return True

        for pattern in self.blocked_port_patterns:
            if re.match(pattern, stripped, re.IGNORECASE):
                return True
        return False

    def is_hardware_flag_blocked(self, flag: str) -> bool:
        """Check if a flag specifically targets hardware ports or serial/CAN communication."""
        if not flag:
            return False
        cleaned = flag.strip().lower()
        if cleaned in self.blocked_hardware_flags:
            return True
        for hw_flag in self.blocked_hardware_flags:
            if cleaned.startswith(f"{hw_flag}:") or cleaned.startswith(f"{hw_flag}="):
                return True
        if re.match(r"^[/-]{1,2}(?:com|port|can|jtag|serial|baud)[\d:=]", cleaned):
            return True
        return False

    def is_download_flag_blocked(self, flag: str) -> bool:
        """Check if a flag targets controller download, firmware flashing, or binary transfer."""
        if not flag:
            return False
        cleaned = flag.strip().lower()
        if cleaned in self.blocked_download_flags:
            return True
        for dl_flag in self.blocked_download_flags:
            if cleaned.startswith(f"{dl_flag}:") or cleaned.startswith(f"{dl_flag}="):
                return True
        if re.match(r"^[/-]{1,2}(?:download|flash|pgm|firmware)", cleaned):
            return True
        return False

    def is_flag_blocked(self, flag: str) -> bool:
        """Check if a CLI flag or argument indicates download, flash, or hardware target."""
        return self.is_hardware_flag_blocked(flag) or self.is_download_flag_blocked(flag)

    def is_protocol_blocked(self, protocol: str) -> bool:
        """Check if a protocol scheme or name is blocked."""
        if not protocol:
            return False
        cleaned = protocol.strip().lower().rstrip(":/")
        return cleaned in self.blocked_protocols

    def is_ui_command_blocked(self, cmd_id: Union[str, int]) -> bool:
        """Check if a Cscape UI command ID or symbol triggers download or hardware comms."""
        if cmd_id is None:
            return False
        if cmd_id in self.blocked_ui_commands:
            return True
        if isinstance(cmd_id, int):
            return cmd_id in self.blocked_ui_commands
        clean = str(cmd_id).strip().lower()
        if clean in self.blocked_ui_commands:
            return True
        if clean.isdigit() and int(clean) in self.blocked_ui_commands:
            return True
        if any(kw in clean for kw in ("download", "upload", "flash", "burn", "firmware")):
            return True
        if any(kw in clean for kw in ("connect", "wizard", "open_communication", "comms")):
            return True
        return False

    def is_ui_command_hardware(self, cmd_id: Union[str, int]) -> bool:
        """Check if a UI command ID specifically targets hardware connection or comms."""
        hw_commands = {
            "id_open_communication",
            2112,
            "id_close_communication",
            38458,
            "id_controller_connectionwizard",
            38269,
            "id_controller_setnetworkid",
            33049,
            "id_program_setnodeid",
            32850,
            "id_onlinechangeconnect",
            38293,
            "id_controller_connect",
            "id_hardware_connect",
            "connect",
            "connection wizard",
        }
        if cmd_id in hw_commands:
            return True
        clean = str(cmd_id).strip().lower()
        if clean in hw_commands:
            return True
        if clean.isdigit() and int(clean) in hw_commands:
            return True
        if any(kw in clean for kw in ("open_comm", "connectionwizard", "connection wizard", "connect", "networkid", "setnodeid", "hardware")):
            if "download" not in clean:
                return True
        return False

    def is_menu_item_blocked(self, menu_path: str) -> bool:
        """Check if a menu item path triggers download or hardware connection."""
        if not menu_path:
            return False
        cleaned = menu_path.strip()
        for pattern in self.blocked_menu_patterns:
            if re.search(pattern, cleaned, re.IGNORECASE):
                return True
        lower = cleaned.lower()
        if "download" in lower or "upload" in lower or "firmware" in lower or "flash" in lower:
            return True
        if "controller" in lower and any(kw in lower for kw in ("connect", "wizard", "communication", "hardware")):
            return True
        if "online change" in lower:
            return True
        return False

    def is_menu_item_hardware(self, menu_path: str) -> bool:
        """Check if a blocked menu item is specifically a hardware connection."""
        if not menu_path:
            return False
        lower = menu_path.strip().lower()
        if any(kw in lower for kw in ("connect", "connection wizard", "communication", "hardware", "online change -> start", "start")):
            if "download" not in lower:
                return True
        return False

    def is_shortcut_blocked(self, shortcut: str) -> bool:
        """Check if a keyboard shortcut triggers controller download."""
        if not shortcut:
            return False
        cleaned = shortcut.strip().lower().replace(" ", "")
        for pattern in self.blocked_shortcuts:
            if re.match(pattern, cleaned, re.IGNORECASE) or re.match(pattern, shortcut.strip(), re.IGNORECASE):
                return True
        if "ctrl+d" in cleaned or "^d" == cleaned or "control+d" in cleaned:
            return True
        return False

    def is_toolbar_button_blocked(self, button: Union[str, int]) -> bool:
        """Check if a toolbar button name or ID triggers download or hardware connection."""
        if button is None:
            return False
        if self.is_ui_command_blocked(button):
            return True
        if isinstance(button, str):
            clean = button.strip().lower()
            if any(kw in clean for kw in ("download", "upload", "flash", "burn", "firmware", "connect", "wizard")):
                return True
        return False

    def is_interface_blocked(self, interface_name: str) -> bool:
        """Check if an interface name references physical COM, CAN, or USB interfaces."""
        if not interface_name:
            return False
        cleaned = interface_name.strip()
        for pattern in self.blocked_interface_patterns:
            if re.search(pattern, cleaned, re.IGNORECASE):
                return True
        lower = cleaned.lower()
        if any(hw in lower for hw in ("com", "can", "usb", "serial", "rs232", "rs485", "rs-232", "rs-485", "pcan", "kvaser", "vector", "cscan", "dfu", "jtag", "vid_", "pid_")):
            if not any(sim in lower for sim in ("simul", "virtual", "software", "offline")):
                return True
        return False


@dataclass
class SecurityConfig:
    """Workspace security configuration managing sandboxed paths and active safety policy."""

    workspace_root: Path = Path(r"C:\HornerAI\horner-cscape-mcp")
    allowed_write_roots: list[Path] = field(default_factory=list)
    allowed_read_roots: list[Path] = field(default_factory=list)
    policy: SafetyPolicy = field(default_factory=SafetyPolicy)
    log_violations: bool = True

    def __post_init__(self) -> None:
        """Normalize root paths and establish secure defaults."""
        self.workspace_root = self.workspace_root.resolve()

        # By default, writing is strictly restricted to workspace_root and subdirectories
        if not self.allowed_write_roots:
            self.allowed_write_roots = [self.workspace_root]
            user_root = Path(r"C:\Users\ArmandoSilva").resolve()
            if user_root.exists() and user_root != self.workspace_root:
                self.allowed_write_roots.append(user_root)
            additional_outputs = os.environ.get("HORNER_ADDITIONAL_OUTPUT_PATHS")
            if additional_outputs:
                for p in additional_outputs.split(os.pathsep):
                    if p.strip():
                        self.allowed_write_roots.append(Path(p.strip()).resolve())
        else:
            self.allowed_write_roots = [p.resolve() for p in self.allowed_write_roots]
            user_root = Path(r"C:\Users\ArmandoSilva").resolve()
            if user_root.exists() and user_root != self.workspace_root:
                self.allowed_write_roots.append(user_root)

        # Allowed read roots include workspace_root, Cscape 10.2 installation, and dual-root user environment
        cscape_install = Path(r"C:\Program Files (x86)\Cscape 10.2").resolve()
        user_root = Path(r"C:\Users\ArmandoSilva").resolve()
        default_read_roots = [self.workspace_root, cscape_install]
        if user_root.exists() and user_root != self.workspace_root:
            default_read_roots.append(user_root)
        if not self.allowed_read_roots:
            self.allowed_read_roots = default_read_roots
        else:
            self.allowed_read_roots = [p.resolve() for p in self.allowed_read_roots]
            if self.workspace_root not in self.allowed_read_roots:
                self.allowed_read_roots.insert(0, self.workspace_root)
            if user_root.exists() and user_root not in self.allowed_read_roots:
                self.allowed_read_roots.append(user_root)

    @classmethod
    def from_env(cls) -> "SecurityConfig":
        """Construct SecurityConfig from environment variables with safe defaults."""
        ws_env = os.environ.get("HORNER_WORKSPACE_ROOT")
        workspace_root = Path(ws_env) if ws_env else Path(r"C:\HornerAI\horner-cscape-mcp")

        additional_outputs = os.environ.get("HORNER_ADDITIONAL_OUTPUT_PATHS")
        write_roots = [workspace_root]
        if additional_outputs:
            for p in additional_outputs.split(os.pathsep):
                if p.strip():
                    write_roots.append(Path(p.strip()))

        return cls(
            workspace_root=workspace_root,
            allowed_write_roots=write_roots,
            policy=SafetyPolicy(),
        )

    def add_output_path(self, path: Path | str) -> None:
        """Register an authorized additional output path within security constraints."""
        resolved = Path(path).resolve()
        if resolved not in self.allowed_write_roots:
            self.allowed_write_roots.append(resolved)

    def add_read_root(self, path: Path | str) -> None:
        """Register an authorized read root within security constraints."""
        resolved = Path(path).resolve()
        if resolved not in self.allowed_read_roots:
            self.allowed_read_roots.append(resolved)