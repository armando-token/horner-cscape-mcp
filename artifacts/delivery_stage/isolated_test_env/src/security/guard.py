"""Security & Safety Guard implementation for Horner Cscape MCP server.

Intercepts all compilation, execution, and export operations.
Validates command arguments, verifies safety locks, and strictly enforces:
- Zero physical PLC connections (HardwareLockoutError)
- Zero controller download or firmware flash operations (UnauthorizedDownloadError)
- Blocking of dangerous utilities (PGMUpdateUtility, DfuSeCommand, STMFlashLoader, WinJTAG)
- Hardware port lockouts (COM, LPT, CAN, USB)
- Strict workspace file-system sandboxing
"""

from functools import wraps
import os
from pathlib import Path
import re
import shlex
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Union

from .exceptions import (
    BlockedExecutableError,
    DangerousArgumentError,
    DeviceNameViolationError,
    HardwareLockoutError,
    PathTraversalError,
    ReadOnlyViolationError,
    SandboxViolationError,
    SecurityError,
    UnauthorizedDownloadError,
)
from .policy import SafetyPolicy, SecurityConfig
from .sandbox import PathSandbox, RESERVED_DOS_DEVICE_NAMES


def _split_command_line(cmd: str) -> list[str]:
    """Safely split command line string on Windows while preserving quotes."""
    if not cmd or not cmd.strip():
        return []
    try:
        return shlex.split(cmd, posix=False)
    except Exception:
        return cmd.split()


class SecurityGuard:
    """Enforces safety constraints, operation interceptions, and input sanitization."""

    BLOCKED_EXECUTABLES: List[str] = [
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
    ]

    BLOCKED_PORTS: List[str] = [
        "COM*",
        "LPT*",
        "CAN*",
        "USB*",
    ]

    BLOCKED_COMMANDS: List[str] = [
        "download",
        "flash",
        "burn",
        "firmware_update",
        "online_change",
        "hardware_connect",
    ]

    DEPRECATED_TARGET_PLCS: List[str] = [
        "T5RTI",      # Legacy Straton T5 Runtime (deprecated)
        "T5SIMUL",    # Legacy Straton T5 Software Simulation (deprecated)
    ]
    DEPRECATED_TARGETS: List[str] = DEPRECATED_TARGET_PLCS

    ALLOWED_TARGET_PLCS: List[str] = [
        "EXL10",      # Horner EXL10 Series (10.4\" Color-Touch OCS)
        "XL10",       # Horner XL10 Series OCS
        "XL+",        # Horner XL+ Series OCS
        "MICRO OCS",  # Horner Micro OCS Series
        "Micro OCS",  # Horner Micro OCS Series (mixed case support)
        "X2",         # Horner Micro OCS X2
        "X4",         # Horner Micro OCS X4
        "X5",         # Horner Micro OCS X5
        "X7",         # Horner Micro OCS X7
        "XL4",        # Horner XL4 Series OCS (simulation model)
        "XLE",        # Horner XLE Series OCS (simulation model)
        "XL7",        # Horner XL7 Series OCS (simulation model)
        "EXL6",       # Horner EXL6 Series OCS (simulation model)
        "RCC972",     # Horner RCC Coprocessor (simulation model)
        "ZX",         # Horner ZX Series (simulation model)
        "SIMULATION",
        "SIM",
        "SOFTWARE",
        "T5RTI",      # Legacy Straton T5 Runtime (deprecated)
        "T5SIMUL",    # Legacy Straton T5 Software Simulation (deprecated)
    ]
    ALLOWED_TARGETS: List[str] = ALLOWED_TARGET_PLCS

    ALLOWED_EXPORT_FORMATS: List[str] = [
        "k5p",
        "xml",
        "st",
        "json",
        "csp",
        "cpj",
        "csv",
    ]

    ALLOWED_POU_TYPES: List[str] = [
        "PROGRAM",
        "FUNCTION_BLOCK",
        "FUNCTION",
    ]

    RESERVED_NAMES: List[str] = sorted(list(RESERVED_DOS_DEVICE_NAMES))

    def __init__(
        self,
        config: Optional[SecurityConfig] = None,
        sandbox: Optional[PathSandbox] = None,
    ) -> None:
        self.config = config or SecurityConfig()
        self.policy: SafetyPolicy = self.config.policy
        self.sandbox: PathSandbox = sandbox or PathSandbox(self.config)

        # Invariant check: verify zero-hardware, zero-download, simulation-only
        self.policy.verify_safety_invariants()

    # --------------------------------------------------------------------------
    # Command & Execution Interception
    # --------------------------------------------------------------------------

    def validate_command(
        self,
        cmd: Union[str, Sequence[str]],
        cwd: Optional[Union[str, Path]] = None,
    ) -> None:
        """Inspect and validate a command string or token sequence.

        Args:
            cmd: Command string or list of argument tokens.
            cwd: Optional working directory for command execution.

        Raises:
            BlockedExecutableError: If command invokes a dangerous executable.
            HardwareLockoutError: If arguments reference hardware ports (COM, CAN, etc.).
            UnauthorizedDownloadError: If arguments include download or flash flags.
            SandboxViolationError: If cwd or path arguments violate the workspace sandbox.
        """
        if isinstance(cmd, str):
            tokens = _split_command_line(cmd)
            raw_cmd_str = cmd
        else:
            tokens = list(cmd)
            raw_cmd_str = " ".join(tokens)

        if not tokens:
            return

        # 1. Check primary executable
        exe_token = tokens[0]
        if self.policy.is_executable_blocked(exe_token):
            raise BlockedExecutableError(
                f"Execution of dangerous executable '{exe_token}' is blocked. "
                "Hardware flashing, firmware updates, and direct download utilities are strictly prohibited."
            )

        # 2. Check all tokens and command string for blocked executables
        for token in tokens[1:]:
            clean_token = token.strip("\"'")
            if self.policy.is_executable_blocked(clean_token):
                raise BlockedExecutableError(
                    f"Command contains prohibited executable '{token}'. Execution blocked."
                )

        # 3. Check for hardware ports and communication flags in arguments
        for token in tokens[1:]:
            clean_token = token.strip("\"'")

            # Hardware communication ports, interfaces, protocols, and flags check
            if (
                self.policy.is_port_blocked(clean_token)
                or self.policy.is_interface_blocked(clean_token)
                or self.policy.is_protocol_blocked(clean_token)
                or self.policy.is_hardware_flag_blocked(clean_token)
            ):
                raise HardwareLockoutError(
                    f"Hardware port, interface, or communication parameter '{token}' detected in command arguments. "
                    "Physical communication is locked out."
                )

            # Prohibited download and flashing flags check
            if self.policy.is_download_flag_blocked(clean_token):
                raise DangerousArgumentError(
                    f"Prohibited download/flashing flag '{token}' detected in command arguments. "
                    "Controller downloads and flashing are strictly prohibited."
                )

        # 4. Check working directory
        if cwd is not None:
            self.sandbox.validate_path(cwd, for_write=False)

    def validate_execution(
        self,
        target: Union[str, Path],
        args: Optional[Sequence[str]] = None,
        cwd: Optional[Union[str, Path]] = None,
        env: Optional[dict] = None,
    ) -> None:
        """Validate target executable and execution parameters before process launch.

        Raises:
            BlockedExecutableError: If executable is in blocked list.
            HardwareLockoutError: If hardware port arguments or env overrides are detected.
            UnauthorizedDownloadError: If download/flash flags are detected.
            SandboxViolationError: If cwd violates sandbox.
        """
        target_str = str(target)
        if self.policy.is_executable_blocked(target_str):
            raise BlockedExecutableError(
                f"Execution of prohibited utility '{target}' is blocked by SafetyPolicy."
            )

        if args:
            tokens = [target_str] + list(args)
            self.validate_command(tokens, cwd=cwd)
        elif cwd:
            self.sandbox.validate_path(cwd, for_write=False)

        # Check environment variables for hardware communication overrides
        if env:
            for k, v in env.items():
                k_upper = k.upper()
                if any(hw_term in k_upper for hw_term in ("COM_PORT", "CAN_PORT", "PLC_ADDR", "TARGET_HARDWARE")):
                    raise HardwareLockoutError(
                        f"Environment variable '{k}={v}' specifies hardware communication parameters, which is prohibited."
                    )
                if isinstance(v, str) and (self.policy.is_port_blocked(v) or self.policy.is_flag_blocked(v)):
                    raise HardwareLockoutError(
                        f"Environment variable '{k}' contains prohibited hardware or download value: '{v}'."
                    )

    # --------------------------------------------------------------------------
    # Path & Sandbox Validation
    # --------------------------------------------------------------------------

    def validate_path(
        self,
        path: Union[str, Path],
        for_write: bool = False,
        base_dir: Optional[Union[str, Path]] = None,
    ) -> Path:
        """Validate and resolve a path against sandboxing rules."""
        return self.sandbox.validate_path(path, for_write=for_write, base_dir=base_dir)

    # --------------------------------------------------------------------------
    # Compilation Interception
    # --------------------------------------------------------------------------

    def validate_compilation(
        self,
        project_path: Union[str, Path],
        output_dir: Optional[Union[str, Path]] = None,
        target: str = "simulation",
        flags: Optional[Sequence[str]] = None,
    ) -> None:
        """Intercept and validate compilation operations.

        Ensures:
        - Target is strictly simulation/software (no physical PLC compilation target).
        - Project path is readable within sandbox.
        - Output directory is writable within workspace sandbox.
        - No download or flash flags are passed to the compiler.

        Raises:
            HardwareLockoutError: If target is hardware/PLC or hardware flags are specified.
            UnauthorizedDownloadError: If download flags are specified.
            SandboxViolationError: If project_path or output_dir violate the sandbox.
        """
        if not self.policy.simulation_only:
            raise HardwareLockoutError("SafetyPolicy requires simulation_only mode.")

        # Validate compilation target
        target_norm = (target or "").strip().upper()
        if target_norm in ("HARDWARE", "PLC", "CONTROLLER", "DEVICE", "PHYSICAL", "TARGET_PLC"):
            raise HardwareLockoutError(
                f"Compilation target '{target}' blocked: Physical PLC targets are strictly prohibited. "
                "Only simulation/software targets are permitted."
            )

        # Validate project file path (must be readable within sandbox)
        self.sandbox.validate_read_path(project_path)

        # Validate output directory (must be writable within sandbox)
        if output_dir is not None:
            self.sandbox.validate_write_path(output_dir)

        # Validate compilation flags
        if flags:
            for flag in flags:
                clean_flag = flag.strip()
                if self.policy.is_download_flag_blocked(clean_flag):
                    raise UnauthorizedDownloadError(
                        f"Prohibited compilation flag '{flag}': Download and flash operations are forbidden."
                    )
                if self.policy.is_port_blocked(clean_flag) or self.policy.is_hardware_flag_blocked(clean_flag):
                    raise HardwareLockoutError(
                        f"Prohibited hardware parameter '{flag}' specified in compilation flags."
                    )

    # --------------------------------------------------------------------------
    # Export Interception
    # --------------------------------------------------------------------------

    def validate_export(
        self,
        source_path: Union[str, Path],
        destination_path: Union[str, Path],
        format: Optional[str] = None,
    ) -> None:
        """Intercept and validate project/file export operations.

        Ensures:
        - Source path is safe to read.
        - Destination path is inside workspace sandbox (cannot write to system or external dirs).
        - Format does not target direct hardware flashing or controller upload.

        Raises:
            UnauthorizedDownloadError: If export format attempts direct hardware flashing.
            SandboxViolationError: If destination or source violates sandbox.
        """
        # Validate source path
        self.sandbox.validate_read_path(source_path)

        # Validate destination path
        self.sandbox.validate_write_path(destination_path)

        # Check export format
        if format:
            fmt_clean = format.strip().lower()
            if fmt_clean in ("hardware", "plc", "flash", "dfu", "jtag", "direct_download"):
                raise UnauthorizedDownloadError(
                    f"Export format '{format}' is blocked. Direct export to hardware or flashing formats is prohibited."
                )

            # Quarantine enforcement for legacy k5p format
            if fmt_clean == "k5p" or str(destination_path).lower().endswith(".k5p"):
                norm_dest = str(destination_path).replace("\\", "/").lower()
                if "quarantine/straton_k5_legacy/artifacts/exports" not in norm_dest:
                    raise SecurityError(
                        f"Legacy 'k5p' exports must be quarantined to 'quarantine/straton_k5_legacy/artifacts/exports/'. "
                        f"Attempted export destination: '{destination_path}'"
                    )
        elif str(destination_path).lower().endswith(".k5p"):
            norm_dest = str(destination_path).replace("\\", "/").lower()
            if "quarantine/straton_k5_legacy/artifacts/exports" not in norm_dest:
                raise SecurityError(
                    f"Legacy 'k5p' exports must be quarantined to 'quarantine/straton_k5_legacy/artifacts/exports/'. "
                    f"Attempted export destination: '{destination_path}'"
                )

    # --------------------------------------------------------------------------
    # Unconditional Safety Lockouts (Zero Hardware, Zero Download)
    # --------------------------------------------------------------------------

    def validate_hardware_connection(
        self,
        target: Optional[str] = None,
        port: Optional[str] = None,
        protocol: Optional[str] = None,
    ) -> None:
        """Unconditionally block physical PLC connections.

        Raises:
            HardwareLockoutError: Always, enforcing the zero physical PLC connection mandate.
        """
        raise HardwareLockoutError(
            f"Physical PLC connection rejected: target='{target}', port='{port}', protocol='{protocol}'. "
            "Physical hardware connections are permanently locked out by SafetyPolicy."
        )

    def validate_download(
        self,
        target: Optional[str] = None,
        binary_path: Optional[Union[str, Path]] = None,
        destination: Optional[str] = None,
    ) -> None:
        """Unconditionally block controller downloads.

        Raises:
            UnauthorizedDownloadError: Always, enforcing the zero controller download mandate.
        """
        raise UnauthorizedDownloadError(
            f"Controller download rejected: target='{target}', binary='{binary_path}', destination='{destination}'. "
            "Controller download operations are strictly prohibited."
        )

    def validate_firmware_flash(
        self,
        firmware_path: Optional[Union[str, Path]] = None,
        tool: Optional[str] = None,
    ) -> None:
        """Unconditionally block firmware flashing operations.

        Raises:
            UnauthorizedDownloadError: Always, enforcing the zero firmware flash mandate.
        """
        raise UnauthorizedDownloadError(
            f"Firmware flash rejected: tool='{tool}', firmware='{firmware_path}'. "
            "Firmware flash operations are strictly prohibited."
        )

    # --------------------------------------------------------------------------
    # Cscape UI Automation & Interface Interception
    # --------------------------------------------------------------------------

    def validate_ui_command(self, cmd_id: Union[str, int]) -> None:
        """Validate a Cscape UI automation command ID against download and hardware rules.

        Raises:
            HardwareLockoutError: If the command attempts physical hardware communication.
            UnauthorizedDownloadError: If the command attempts controller download or flashing.
        """
        if self.policy.is_ui_command_blocked(cmd_id):
            if self.policy.is_ui_command_hardware(cmd_id):
                raise HardwareLockoutError(
                    f"Cscape UI command '{cmd_id}' attempts physical hardware communication. "
                    "Physical communication is permanently locked out."
                )
            raise UnauthorizedDownloadError(
                f"Cscape UI command '{cmd_id}' (e.g. ID_CONTROLLER_DOWNLOAD / ID_PLC_DOWNLOAD) "
                "attempts controller download or flashing. Operation strictly prohibited."
            )

    def validate_menu_item(self, menu_path: str) -> None:
        """Validate a Cscape menu item path against download and hardware rules.

        Raises:
            HardwareLockoutError: If menu item triggers physical hardware connection.
            UnauthorizedDownloadError: If menu item triggers controller download or flashing.
        """
        if self.policy.is_menu_item_blocked(menu_path):
            if self.policy.is_menu_item_hardware(menu_path):
                raise HardwareLockoutError(
                    f"Cscape menu item '{menu_path}' attempts physical hardware connection. "
                    "Physical communication is permanently locked out."
                )
            raise UnauthorizedDownloadError(
                f"Cscape menu item '{menu_path}' (Controller -> Download) is strictly blocked by SafetyPolicy. "
                "Controller downloads are prohibited."
            )

    def validate_toolbar_button(self, button: Union[str, int]) -> None:
        """Validate a Cscape toolbar button against download and hardware rules.

        Raises:
            HardwareLockoutError: If toolbar button triggers physical connection.
            UnauthorizedDownloadError: If toolbar button triggers download.
        """
        if self.policy.is_toolbar_button_blocked(button):
            if self.policy.is_ui_command_hardware(button):
                raise HardwareLockoutError(
                    f"Cscape toolbar button '{button}' attempts physical hardware connection. "
                    "Physical communication is permanently locked out."
                )
            raise UnauthorizedDownloadError(
                f"Cscape toolbar button '{button}' triggers controller download. "
                "Controller downloads are strictly prohibited."
            )

    def validate_shortcut(self, shortcut: str) -> None:
        """Validate a keyboard shortcut against controller download shortcuts.

        Raises:
            UnauthorizedDownloadError: If shortcut triggers controller download (e.g. Ctrl+D).
        """
        if self.policy.is_shortcut_blocked(shortcut):
            raise UnauthorizedDownloadError(
                f"Keyboard shortcut '{shortcut}' triggers Controller -> Download. "
                "Controller downloads are strictly prohibited."
            )

    def validate_interface(self, interface: str, port: Optional[str] = None) -> None:
        """Verify that an interface configuration never specifies physical COM, CAN, or USB interfaces.

        Raises:
            HardwareLockoutError: If interface references physical COM, CAN, or USB hardware.
        """
        if self.policy.is_interface_blocked(interface) or (port and self.policy.is_port_blocked(port)):
            raise HardwareLockoutError(
                f"Configuration with physical interface '{interface}' (port='{port}') is strictly prohibited. "
                "Physical COM, CAN, and USB interfaces are locked out."
            )

    def verify_cscape_interfaces(self, config: Optional[Any] = None) -> dict[str, Any]:
        """Verify Cscape is never configured with physical COM, CAN, or USB interfaces.

        Audits provided config, environment variables, and active policy.

        Raises:
            HardwareLockoutError: If physical COM, CAN, or USB interface configuration is detected.
        """
        # 1. Audit provided configuration structure if provided
        if config is not None:
            if isinstance(config, dict):
                for k, v in config.items():
                    k_str, v_str = str(k), str(v)
                    if self.policy.is_interface_blocked(k_str) or self.policy.is_interface_blocked(v_str):
                        raise HardwareLockoutError(
                            f"Physical interface configuration detected in config key '{k}': '{v}'. "
                            "Physical COM, CAN, and USB interfaces are locked out."
                        )
                    if self.policy.is_port_blocked(k_str) or self.policy.is_port_blocked(v_str):
                        raise HardwareLockoutError(
                            f"Physical port detected in config '{k}={v}'. Physical communication is locked out."
                        )
            elif isinstance(config, (str, Path)):
                cfg_path = Path(config)
                if cfg_path.exists() and cfg_path.is_file():
                    content = cfg_path.read_text(encoding="utf-8", errors="ignore")
                    for line in content.splitlines():
                        line_stripped = line.strip()
                        if line_stripped.startswith(";") or line_stripped.startswith("#"):
                            continue
                        if re.search(r"(?i)\b(?:COM[0-9]+|CAN[0-9]*|USB[0-9]*)\b", line_stripped):
                            if "simul" not in line_stripped.lower():
                                raise HardwareLockoutError(
                                    f"Physical interface setting detected in file '{cfg_path}': {line_stripped}"
                                )

        # 2. Audit environment variables
        for env_var in ("CSCAPE_COM_PORT", "CAN_PORT", "PLC_ADDR", "TARGET_HARDWARE", "CSCAPE_INTERFACE"):
            if env_var in os.environ and os.environ[env_var].strip():
                val = os.environ[env_var].strip()
                if self.policy.is_interface_blocked(val) or self.policy.is_port_blocked(val):
                    raise HardwareLockoutError(
                        f"Physical interface configured via environment variable '{env_var}={val}'."
                    )

        # 3. Audit policy invariants
        self.policy.verify_safety_invariants()

        return {
            "physical_interfaces_blocked": True,
            "com_interfaces_allowed": False,
            "can_interfaces_allowed": False,
            "usb_interfaces_allowed": False,
            "simulation_only": True,
            "lockout_state": "LOCKED_OUT",
            "status": "success",
        }

    # --------------------------------------------------------------------------
    # Static & Class Validation Utilities for Inputs
    # --------------------------------------------------------------------------

    @classmethod
    def validate_project_name(cls, name: str) -> str:
        """Sanitizes and validates a project name against path traversal and reserved names."""
        if not name or not isinstance(name, str):
            raise SecurityError("Project name must be a non-empty string.")

        clean_name = name.strip()
        if len(clean_name) > 64:
            raise SecurityError("Project name exceeds maximum length of 64 characters.")

        if ".." in clean_name or "/" in clean_name or "\\" in clean_name:
            raise PathTraversalError("Path traversal sequences are strictly forbidden in project names.")

        if clean_name.upper() in RESERVED_DOS_DEVICE_NAMES:
            raise DeviceNameViolationError(f"Project name '{clean_name}' is a reserved system identifier.")

        if not re.match(r"^[a-zA-Z0-9_\-]+$", clean_name):
            raise SecurityError(
                f"Invalid project name '{clean_name}'. Only alphanumeric characters, hyphens, and underscores are permitted."
            )

        return clean_name

    @classmethod
    def validate_pou_name(cls, name: str) -> str:
        """Validates that a POU name follows IEC 61131-3 identifier conventions."""
        if not name or not isinstance(name, str):
            raise SecurityError("POU name must be a non-empty string.")

        clean_name = name.strip()
        if len(clean_name) > 64:
            raise SecurityError("POU name exceeds maximum length of 64 characters.")

        if ".." in clean_name or "/" in clean_name or "\\" in clean_name:
            raise PathTraversalError("Path traversal sequences are strictly forbidden in POU names.")

        if clean_name.upper() in RESERVED_DOS_DEVICE_NAMES:
            raise DeviceNameViolationError(f"POU name '{clean_name}' is a reserved system identifier.")

        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", clean_name):
            raise SecurityError(
                f"Invalid POU name '{clean_name}'. Must start with a letter/underscore and contain only alphanumeric characters or underscores."
            )

        return clean_name

    @classmethod
    def validate_target_plc(cls, target_plc: str) -> str:
        """Validates that the target PLC architecture is supported and safe."""
        if not target_plc or not isinstance(target_plc, str):
            raise SecurityError("Target PLC must be specified.")

        clean_target = target_plc.strip().upper()
        if clean_target in ("PHYSICAL", "HARDWARE", "PLC_HARDWARE"):
            raise HardwareLockoutError(f"Hardware target PLC '{target_plc}' is strictly prohibited.")

        if clean_target not in cls.ALLOWED_TARGET_PLCS:
            raise SecurityError(
                f"Unsupported target PLC '{target_plc}'. Allowed targets: {', '.join(cls.ALLOWED_TARGET_PLCS)}"
            )

        if clean_target in cls.DEPRECATED_TARGET_PLCS:
            import warnings
            warnings.warn(
                f"Target PLC '{target_plc}' is deprecated and quarantined under legacy Straton K5 support. "
                f"Please use modern Horner OCS targets (e.g., EXL10, XL10, XL+, Micro OCS, XL4, XL7).",
                DeprecationWarning,
                stacklevel=2,
            )

        return clean_target

    @classmethod
    def validate_export_format(cls, output_format: str) -> str:
        """Validates export format."""
        if not output_format or not isinstance(output_format, str):
            raise SecurityError("Output format must be specified.")

        clean_fmt = output_format.strip().lower()
        if clean_fmt in ("hardware", "plc", "flash", "dfu", "jtag", "direct_download"):
            raise UnauthorizedDownloadError(f"Export format '{output_format}' directly targets hardware.")

        if clean_fmt not in cls.ALLOWED_EXPORT_FORMATS:
            raise SecurityError(
                f"Unsupported export format '{output_format}'. Allowed formats: {', '.join(cls.ALLOWED_EXPORT_FORMATS)}"
            )

        return clean_fmt

    @classmethod
    def validate_pou_type(cls, pou_type: str) -> str:
        """Validates IEC 61131-3 POU type."""
        if not pou_type or not isinstance(pou_type, str):
            raise SecurityError("POU type must be specified.")

        clean_type = pou_type.strip().upper()
        if clean_type not in cls.ALLOWED_POU_TYPES:
            raise SecurityError(
                f"Unsupported POU type '{pou_type}'. Allowed types: {', '.join(cls.ALLOWED_POU_TYPES)}"
            )

        return clean_type

    @classmethod
    def validate_cycle_time(cls, cycle_time_ms: int) -> int:
        """Validates cyclic execution time in milliseconds."""
        if not isinstance(cycle_time_ms, int) or cycle_time_ms < 1 or cycle_time_ms > 60000:
            raise SecurityError(f"Cycle time must be an integer between 1 and 60000 ms (got {cycle_time_ms}).")
        return cycle_time_ms

    @classmethod
    def validate_simulation_steps(cls, steps: int) -> int:
        """Validates simulation step count."""
        if not isinstance(steps, int) or steps < 1 or steps > 10000:
            raise SecurityError(f"Simulation steps must be an integer between 1 and 10000 (got {steps}).")
        return steps

    @classmethod
    def assert_compile_only(cls, operation: str = "operation") -> None:
        """Enforces that operations remain local/software only."""
        for blocked in cls.BLOCKED_COMMANDS:
            if blocked in operation.lower():
                raise UnauthorizedDownloadError(
                    f"Security violation: Operation '{operation}' violates the strict 'NO PHYSICAL PLC DOWNLOAD' directive."
                )

    @classmethod
    def get_safety_status(cls) -> Dict[str, Any]:
        """Returns the current safety lockout configuration and active constraints."""
        return {
            "status": "success",
            "hardware_lockout_active": True,
            "physical_plc_allowed": False,
            "controller_download_allowed": False,
            "ui_download_blocked": True,
            "physical_interfaces_blocked": True,
            "blocked_ports": cls.BLOCKED_PORTS,
            "blocked_executables": cls.BLOCKED_EXECUTABLES,
            "blocked_commands": cls.BLOCKED_COMMANDS,
            "execution_mode": "SIMULATION_AND_COMPILE_ONLY",
            "allowed_target_plcs": cls.ALLOWED_TARGET_PLCS,
            "allowed_targets": cls.ALLOWED_TARGETS,
            "deprecated_targets": cls.DEPRECATED_TARGETS,
            "allowed_export_formats": cls.ALLOWED_EXPORT_FORMATS,
        }

    @classmethod
    def verify_cscape_hardware_lockout(cls, config: Optional[Any] = None) -> Dict[str, Any]:
        """Verify Cscape is never configured with physical COM, CAN, or USB interfaces."""
        return cls().verify_cscape_interfaces(config)

    # --------------------------------------------------------------------------
    # Decorators for Operational Interception
    # --------------------------------------------------------------------------

    def intercept_compilation(self, func: Callable) -> Callable:
        """Decorator that validates compilation parameters before invoking func."""
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            proj = kwargs.get("project_path") or (args[0] if args else None)
            out_dir = kwargs.get("output_dir") or (args[1] if len(args) > 1 else None)
            target = kwargs.get("target", "simulation")
            flags = kwargs.get("flags")
            if proj is not None:
                self.validate_compilation(proj, output_dir=out_dir, target=target, flags=flags)
            return func(*args, **kwargs)
        return wrapper

    def intercept_execution(self, func: Callable) -> Callable:
        """Decorator that validates command execution arguments before invoking func."""
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            cmd = kwargs.get("cmd") or kwargs.get("target") or (args[0] if args else None)
            cwd = kwargs.get("cwd")
            if cmd is not None:
                if isinstance(cmd, (str, list, tuple)):
                    self.validate_command(cmd, cwd=cwd)
                else:
                    self.validate_execution(cmd, cwd=cwd)
            return func(*args, **kwargs)
        return wrapper

    def intercept_export(self, func: Callable) -> Callable:
        """Decorator that validates export file operations before invoking func."""
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            src = kwargs.get("source_path") or (args[0] if args else None)
            dst = kwargs.get("destination_path") or (args[1] if len(args) > 1 else None)
            fmt = kwargs.get("format")
            if src is not None and dst is not None:
                self.validate_export(src, dst, format=fmt)
            return func(*args, **kwargs)
        return wrapper


# Backward and peer compatibility aliases
SafetyGuard = SecurityGuard
ALLOWED_TARGETS = SecurityGuard.ALLOWED_TARGETS
ALLOWED_TARGET_PLCS = SecurityGuard.ALLOWED_TARGET_PLCS
DEPRECATED_TARGETS = SecurityGuard.DEPRECATED_TARGETS
DEPRECATED_TARGET_PLCS = SecurityGuard.DEPRECATED_TARGET_PLCS