"""Horner Cscape Model Context Protocol (MCP) Tool Schemas.

Defines Pydantic v2 input and output schemas for all core Horner Cscape operations:
- cscape_launch_ide()
- cscape_new_iec_project(project_name, target_dir, controller_model)
- cscape_open_project(file_path)
- cscape_insert_st(pou_name, pou_type, st_code)
- cscape_compile()
- cscape_get_build_output()
- cscape_import_variables(csv_path)
- cscape_export_variables(output_csv_path)
- cscape_run_simulation(steps)

Safety Invariants Enforced:
- extra='forbid' on all models to reject any unauthorized parameter injection
- Zero download parameters: Any download, flash, burn, or hardware port parameter is rejected
- Physical controller lockout: Simulation and software compile-only targets permitted
- Path sanitization and DOS device name protection (CON, PRN, AUX, COM1..9, etc.)
- Structured Text ONLY: Ladder logic artifacts strictly rejected
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import re
from typing import Any, Dict, List, Literal, Optional, Set, Type, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..iec.validator import IECValidator
from ..security.guard import SafetyGuard, SecurityError
from ..security.sandbox import RESERVED_DOS_DEVICE_NAMES


def _get_utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


# Prohibited keywords and substrings that indicate physical controller download or hardware operations
PROHIBITED_DOWNLOAD_TERMS: tuple[str, ...] = (
    "download",
    "flash",
    "burn",
    "firmware_update",
    "online_change",
    "hardware_connect",
    "direct_download",
    "write-flash",
    "pgm_update",
)

PROHIBITED_PORT_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"^COM[0-9]+$", re.IGNORECASE),
    re.compile(r"^LPT[0-9]+$", re.IGNORECASE),
    re.compile(r"^CAN[0-9]*$", re.IGNORECASE),
    re.compile(r"^USB[0-9]*$", re.IGNORECASE),
    re.compile(r"^/dev/tty.*$", re.IGNORECASE),
    re.compile(r"^\\\\\.\\COM.*$", re.IGNORECASE),
)

DEPRECATED_CONTROLLER_MODELS: tuple[str, ...] = (
    "T5RTI",      # Legacy Straton runtime (deprecated, quarantined under legacy Straton K5)
    "T5SIMUL",    # Legacy Straton simulation engine (deprecated, quarantined)
)

ALLOWED_CONTROLLER_MODELS: tuple[str, ...] = (
    # Modern Horner OCS Series
    "EXL10",
    "XL10",
    "XL+",
    "Micro OCS",
    "MICRO OCS",
    "X2",
    "X4",
    "X5",
    "X7",
    "XL4",
    "XLE",
    "XL7",
    "EXL6",
    "RCC972",
    "ZX",
    "SIMULATION",
    "SIM",
    "SOFTWARE",
    # Legacy Straton targets (deprecated)
    "T5RTI",
    "T5SIMUL",
)

# Regex pattern for Horner OCS memory addresses
# Matches: %R100, %M1, %SR43.1, %R100.16, %AI1, %AQ2, %AIG10, %IX1.0, %MW50
OCS_REGISTER_PATTERN: re.Pattern = re.compile(
    r"^%(?P<prefix>AIG|AQG|IG|QG|AI|AQ|SR|IX|QX|MX|IW|QW|MW|ID|QD|MD|R|M|T|I|Q|D|K|S)"
    r"(?P<index>\d+)"
    r"(?:\.(?P<bit>\d+))?$",
    re.IGNORECASE,
)

# Standard index ranges for Horner OCS controller registers
OCS_REGISTER_BOUNDS: dict[str, tuple[int, int]] = {
    "%R": (1, 9999),      # Retentive 16-bit general holding registers
    "%M": (1, 2048),      # Retentive internal bits
    "%T": (1, 2048),      # Temporary non-retentive bits
    "%I": (1, 2048),      # Discrete digital inputs
    "%Q": (1, 2048),      # Discrete digital outputs
    "%AI": (1, 512),      # Analog inputs (16-bit)
    "%AQ": (1, 512),      # Analog outputs (16-bit)
    "%D": (1, 1024),      # Display bits
    "%K": (1, 1024),      # Keypad bits
    "%S": (1, 128),       # System status bits
    "%SR": (1, 256),      # System registers (16-bit)
    "%IG": (1, 2048),     # Global network discrete inputs (CsCAN)
    "%QG": (1, 2048),     # Global network discrete outputs (CsCAN)
    "%AIG": (1, 2048),    # Global network analog inputs (CsCAN)
    "%AQG": (1, 2048),    # Global network analog outputs (CsCAN)
    "%IX": (0, 65535),    # IEC input bits
    "%QX": (0, 65535),    # IEC output bits
    "%MX": (0, 65535),    # IEC memory bits
    "%IW": (0, 65535),    # IEC input words
    "%QW": (0, 65535),    # IEC output words
    "%MW": (0, 65535),    # IEC memory words
    "%ID": (0, 65535),    # IEC input double-words
    "%QD": (0, 65535),    # IEC output double-words
    "%MD": (0, 65535),    # IEC memory double-words
}

OCS_WORD_REGISTERS: frozenset[str] = frozenset({
    "%R", "%AI", "%AQ", "%SR", "%AIG", "%AQG",
    "%IW", "%QW", "%MW",
})

OCS_BIT_REGISTERS: frozenset[str] = frozenset({
    "%M", "%T", "%I", "%Q", "%D", "%K", "%S", "%IG", "%QG",
    "%IX", "%QX", "%MX",
})


def validate_ocs_register(addr_str: str) -> str:
    """Validate and normalize a Horner OCS or standard IEC register address.

    Enforces:
    - Proper '%' prefix followed by recognized Horner OCS register identifier.
    - Strict boundary validation against physical OCS register memory architecture.
    - Bit-of-word indexing constraints (0..16) only on 16-bit word registers.
    - Rejection of bit indexing on discrete bit registers (e.g. %M1.5).

    Returns:
        Canonicalized uppercase register string (e.g. '%R100', '%SR43.1').

    Raises:
        ValueError: If register syntax, prefix, index range, or bit offset is invalid.
    """
    if not addr_str or not isinstance(addr_str, str):
        raise ValueError(f"Invalid register address: {addr_str!r}. Must be a non-empty string.")

    cleaned = addr_str.strip()
    if not cleaned.startswith("%"):
        raise ValueError(f"Horner OCS register address must start with '%', got: '{addr_str}'.")

    match = OCS_REGISTER_PATTERN.match(cleaned)
    if not match:
        raise ValueError(
            f"Invalid Horner OCS register format: '{addr_str}'. "
            f"Expected format: %<Type><Index>[.<Bit>], e.g. %R100, %M1, %SR43.1, %AI5"
        )

    prefix = "%" + match.group("prefix").upper()
    index = int(match.group("index"))

    if prefix not in OCS_REGISTER_BOUNDS:
        raise ValueError(f"Unsupported Horner register prefix '{prefix}' in '{addr_str}'.")

    min_idx, max_idx = OCS_REGISTER_BOUNDS[prefix]
    if not (min_idx <= index <= max_idx):
        raise ValueError(
            f"Register index {index} out of bounds for {prefix} (valid: {min_idx}..{max_idx}) in '{addr_str}'."
        )

    bit_val: Optional[int] = None
    if match.group("bit") is not None:
        bit_val = int(match.group("bit"))
        if prefix in OCS_BIT_REGISTERS:
            raise ValueError(
                f"Bit offset not allowed on discrete bit register '{prefix}' in '{addr_str}'."
            )
        if not (0 <= bit_val <= 16):
            raise ValueError(
                f"Bit offset {bit_val} out of range (0..16) in register '{addr_str}'."
            )

    canonical = f"{prefix}{index}"
    if bit_val is not None:
        canonical += f".{bit_val}"
    return canonical


def is_valid_ocs_register(addr_str: str) -> bool:
    """Return True if addr_str is a valid Horner OCS register, False otherwise."""
    try:
        validate_ocs_register(addr_str)
        return True
    except (ValueError, TypeError):
        return False


def validate_safe_path(
    path_val: Optional[str],
    allowed_extensions: Optional[Set[str]] = None,
    allow_none: bool = False,
    field_name: str = "path",
) -> Optional[str]:
    """Rigorous path traversal and security defense validator for MCP tool path arguments.

    Enforces:
    - Path traversal sequence rejection ('..', relative breakout)
    - Windows DOS reserved device name rejection (CON, PRN, AUX, NUL, COM1..9, LPT1..9, CLOCK$)
    - Prohibited hardware download/flash keywords rejection
    - UNC remote network path rejection (\\\\, //)
    - Alternate Data Stream (ADS) syntax rejection (:stream)
    - Null-byte injection rejection (\\0)
    - Extension whitelisting when specified
    """
    if path_val is None:
        if allow_none:
            return None
        raise ValueError(f"{field_name} cannot be null.")

    clean = str(path_val).strip()
    if not clean:
        if allow_none:
            return None
        raise ValueError(f"{field_name} cannot be empty.")

    # 1. Null-byte injection check
    if "\0" in clean:
        raise ValueError(f"Null byte detected in {field_name}. Operation blocked.")

    # 2. Prohibited hardware/download terms
    for term in PROHIBITED_DOWNLOAD_TERMS:
        if term in clean.lower():
            raise ValueError(
                f"Prohibited term '{term}' detected in {field_name}. Direct hardware operations are blocked."
            )

    # 3. UNC network paths check
    if clean.startswith(("\\\\", "//")):
        raise ValueError(
            f"UNC remote network paths are prohibited in {field_name}: '{clean}'"
        )

    # 4. Alternate Data Stream (ADS) check
    colon_count = clean.count(":")
    if colon_count > 1 or (colon_count == 1 and not re.match(r"^[a-zA-Z]:[\\/]", clean)):
        raise ValueError(
            f"Alternate Data Stream (ADS) syntax is prohibited in {field_name}: '{clean}'"
        )

    # 5. Path traversal sequence check ('..')
    parts = Path(clean).parts
    if (
        any(part == ".." for part in parts)
        or "/../" in clean
        or "\\..\\" in clean
        or clean.startswith("../")
        or clean.startswith("..\\")
        or clean.endswith("/..")
        or clean.endswith("\\..")
        or clean == ".."
    ):
        raise ValueError(
            f"Path traversal sequence ('..') detected in {field_name}: '{clean}'"
        )

    # 6. DOS reserved device names check
    for part in parts:
        clean_part = part.rstrip("\\/ ")
        if clean_part.endswith(":"):
            clean_part = clean_part[:-1]
        base_name = clean_part.split(".")[0].upper()
        if base_name in RESERVED_DOS_DEVICE_NAMES:
            raise ValueError(
                f"Reserved Windows device name '{base_name}' detected in {field_name}: '{clean}'"
            )

    # 7. Allowed extension check
    if allowed_extensions:
        p = Path(clean)
        if not p.suffix or p.suffix.lower() not in allowed_extensions:
            raise ValueError(
                f"Unsupported file extension '{p.suffix}' in {field_name}. "
                f"Expected one of: {sorted(list(allowed_extensions))}"
            )

    return clean


# ==============================================================================
# Base Schema Configuration
# ==============================================================================

class CscapeBaseModel(BaseModel):
    """Base model for all Horner Cscape MCP tool schemas.

    Enforces:
    - extra='forbid': Any extraneous arguments (such as injected download flags or ports)
      cause immediate validation failure.
    - str_strip_whitespace: Automatic stripping of leading/trailing whitespace.
    - validate_assignment: Ensure attributes are validated upon assignment.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        populate_by_name=True,
        use_enum_values=True,
    )


class CscapeOutputBase(CscapeBaseModel):
    """Base model enforcing the rigorous status contract across all MCP tools:
    - success: bool
    - status: Literal["success", "failed", "blocked", "inconclusive", "warning", "error"]
    - errors: List[str]
    - warnings: List[str]
    - diagnostics: List[Dict[str, Any]]
    - failure_locations: List[Dict[str, Any]]
    """
    success: bool = Field(..., description="True if operation completed without fatal errors.")
    status: Literal["success", "failed", "blocked", "inconclusive", "warning", "error"] = Field(
        default="success",
        description="Operation status: 'success' | 'failed' | 'blocked' | 'inconclusive' (canonical), or 'warning' | 'error' (legacy).",
    )
    error_code: Optional[str] = Field(default=None, description="Optional machine-readable error code string enum.")
    classification: Optional[str] = Field(default=None, description="Taxonomy classification contract.")
    verification_classification: Optional[str] = Field(default=None, description="Verification classification contract.")
    provenance: Optional[str] = Field(default=None, description="Emulated/mock provenance classification.")
    hardware_connected: Optional[bool] = Field(default=None, description="Hardware connectivity indicator.")
    isolation_enforced: Optional[bool] = Field(default=None, description="Pure software isolation guarantee.")
    hardware_lockout_enforced: Optional[bool] = Field(default=None, description="Hardware lockout guarantee.")
    errors: List[str] = Field(default_factory=list, description="List of string error messages.")
    warnings: List[str] = Field(default_factory=list, description="List of string warning messages.")
    diagnostics: List[Dict[str, Any]] = Field(default_factory=list, description="List of diagnostic objects.")
    failure_locations: List[Dict[str, Any]] = Field(default_factory=list, description="List of failure locations.")

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, v: Any) -> str:
        if isinstance(v, str):
            clean = re.sub(r"(?i)\bverified\b|100\s*%", "", str(v)).strip(" -_:")
            v_norm = clean.lower()
            if not v_norm:
                return "success"
            if v_norm in ("error", "err", "failure"):
                return "failed"
            if v_norm in ("ok", "pass", "passed"):
                return "success"
            return v_norm
        return v


# ==============================================================================
# Enumerations & Supporting Types
# ==============================================================================

class POUType(str, Enum):
    """IEC 61131-3 Program Organization Unit (POU) types."""
    PROGRAM = "PROGRAM"
    FUNCTION_BLOCK = "FUNCTION_BLOCK"
    FUNCTION = "FUNCTION"


class VariableScope(str, Enum):
    """IEC 61131-3 Variable declaration scopes."""
    VAR = "VAR"
    VAR_INPUT = "VAR_INPUT"
    VAR_OUTPUT = "VAR_OUTPUT"
    VAR_IN_OUT = "VAR_IN_OUT"
    VAR_GLOBAL = "VAR_GLOBAL"
    VAR_EXTERNAL = "VAR_EXTERNAL"
    VAR_TEMP = "VAR_TEMP"


class VariableMergeStrategy(str, Enum):
    """Variable import merge strategies."""
    MERGE = "merge"
    OVERWRITE = "overwrite"


class BuildLogLevel(str, Enum):
    """Log filter levels for build output diagnostics."""
    ALL = "ALL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class VariableDeclaration(CscapeBaseModel):
    """Individual variable definition within an IEC 61131-3 POU or global scope."""
    name: str = Field(..., description="Variable identifier (IEC 61131-3 compliant).")
    data_type: str = Field(..., description="IEC 61131-3 data type (e.g. BOOL, INT, DINT, REAL, STRING, TIME).")
    scope: VariableScope = Field(default=VariableScope.VAR, description="Variable declaration scope.")
    initial_value: Optional[str] = Field(default=None, description="Initial default literal value.")
    comment: Optional[str] = Field(default=None, description="Descriptive comment or engineering notes.")
    address: Optional[str] = Field(default=None, description="Direct hardware address (%I, %Q, %M), if mapped.")
    pou_name: Optional[str] = Field(default=None, description="Associated POU name, or None if global.")

    @field_validator("name")
    @classmethod
    def validate_var_name(cls, v: str) -> str:
        clean = v.strip()
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", clean):
            raise ValueError(f"Invalid variable name '{clean}'. Must follow IEC 61131-3 identifier rules.")
        if clean.upper() in RESERVED_DOS_DEVICE_NAMES:
            raise ValueError(f"Variable name '{clean}' is a reserved system identifier.")
        return clean

    @field_validator("address")
    @classmethod
    def validate_var_address(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        clean = v.strip()
        if not clean:
            return None
        return validate_ocs_register(clean)


class MemoryFootprint(CscapeBaseModel):
    """Horner Cscape compiled bytecode memory footprint estimate."""
    code_size_bytes: int = Field(default=0, ge=0, description="Estimated executable logic bytecode size in bytes.")
    data_size_bytes: int = Field(default=0, ge=0, description="Estimated data segment allocation in bytes.")
    symbol_count: int = Field(default=0, ge=0, description="Total number of registered symbols.")
    retain_size_bytes: int = Field(default=0, ge=0, description="Retained battery-backed memory allocation in bytes.")


class POUCompilationStatus(CscapeBaseModel):
    """Compilation status report for a single POU."""
    name: str = Field(..., description="Name of the compiled POU.")
    type: str = Field(..., description="POU type (PROGRAM, FUNCTION_BLOCK, FUNCTION).")
    valid: bool = Field(..., description="True if POU compiled without syntax or semantic errors.")
    lines: int = Field(default=0, ge=0, description="Source lines in POU.")
    variables: int = Field(default=0, ge=0, description="Variable symbol count in POU.")


class SimulationStepTrace(CscapeBaseModel):
    """Recorded state for a single scan cycle execution during simulation."""
    step: int = Field(..., ge=0, description="Scan cycle index (0-indexed).")
    variables: Dict[str, Any] = Field(default_factory=dict, description="Snapshot of variables after cycle execution.")


# ==============================================================================
# 1. cscape_launch_ide Schemas
# ==============================================================================

class CscapeLaunchIDEInput(CscapeBaseModel):
    """Input parameters for launching Horner Cscape IDE."""

    headless: bool = Field(
        default=False,
        description="If True, launches Cscape in headless background mode (CREATE_NO_WINDOW). "
                    "If False, launches interactive graphical IDE.",
    )
    project_path: Optional[str] = Field(
        default=None,
        description="Optional absolute or relative path to a project file (.cpj, .csp) to open on launch.",
    )
    timeout_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Timeout in seconds to wait for Cscape process startup.",
    )
    kill_existing: bool = Field(
        default=False,
        description="If True, cleanly terminates any pre-existing Cscape.exe instances before launching.",
    )

    @field_validator("project_path")
    @classmethod
    def validate_launch_project_path(cls, v: Optional[str]) -> Optional[str]:
        return validate_safe_path(
            v,
            allowed_extensions={".cpj", ".csp"},
            allow_none=True,
            field_name="project_path",
        )


class CscapeLaunchIDEOutput(CscapeOutputBase):
    """Output results from launching Horner Cscape IDE."""

    pid: Optional[int] = Field(default=None, description="Process ID of the launched or connected Cscape instance.")
    executable_path: Optional[str] = Field(default=None, description="Resolved file path to Cscape.exe.")
    version: Optional[str] = Field(default=None, description="Detected Cscape version string (e.g. '10.2.751.4').")
    mode: str = Field(default="gui", description="Execution mode: 'gui', 'headless', or 'active_instance'.")
    project_opened: Optional[str] = Field(default=None, description="Path of the project opened, if specified.")
    main_hwnd: Optional[int] = Field(default=None, description="Main window handle HWND.")
    window_title: Optional[str] = Field(default=None, description="Main window title.")
    lifecycle_state: Optional[str] = Field(default=None, description="Lifecycle state string.")
    iec_mode_active: Optional[bool] = Field(default=True, description="Whether IEC 61131 mode is active.")
    message: str = Field(..., description="Descriptive status message.")
    timestamp: str = Field(default_factory=_get_utc_now_iso, description="UTC timestamp of launch operation.")
    started_at: Optional[str] = Field(default=None, description="ISO timestamp when process started.")


# Clean aliases
LaunchIDEInput = CscapeLaunchIDEInput
LaunchIDEOutput = CscapeLaunchIDEOutput


# ==============================================================================
# 2. cscape_new_iec_project Schemas
# ==============================================================================

class CscapeNewIECProjectInput(CscapeBaseModel):
    """Input parameters for creating a new Horner Cscape IEC 61131-3 project."""

    project_name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Unique name for the project (alphanumeric, underscores, hyphens only).",
    )
    target_dir: str = Field(
        ...,
        min_length=1,
        description="Target directory path where the project directory and files will be generated.",
    )
    controller_model: str = Field(
        ...,
        description="Target Horner controller model "
                    "(e.g. 'XL4', 'XLE', 'XL7', 'EXL6', 'RCC972', 'ZX', 'T5SIMUL'). "
                    "Physical hardware targets or download commands are strictly forbidden.",
    )
    description: Optional[str] = Field(
        default="",
        max_length=1024,
        description="Optional human-readable description of the automation application.",
    )
    author: Optional[str] = Field(
        default="Horner AI Agent",
        max_length=128,
        description="Author or creator identifier for project metadata.",
    )

    @field_validator("project_name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        try:
            return SafetyGuard.validate_project_name(v)
        except SecurityError as se:
            raise ValueError(str(se)) from se

    @field_validator("controller_model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        clean = v.strip().upper()
        if clean in ("PHYSICAL", "HARDWARE", "PLC_HARDWARE", "DOWNLOAD", "FLASH"):
            raise ValueError(
                f"Controller model '{v}' rejected: Physical hardware targets and direct download commands are forbidden. "
                f"Permitted simulation targets: {', '.join(ALLOWED_CONTROLLER_MODELS)}"
            )
        if clean in DEPRECATED_CONTROLLER_MODELS:
            import warnings
            warnings.warn(
                f"Controller model '{v}' is deprecated. Standalone Straton K5 targets are quarantined; "
                f"use modern Horner OCS targets (e.g. EXL10, XL10, XL+, Micro OCS, XL4, XL7).",
                DeprecationWarning,
                stacklevel=2,
            )
        try:
            return SafetyGuard.validate_target_plc(clean)
        except SecurityError as se:
            raise ValueError(str(se)) from se

    @field_validator("target_dir")
    @classmethod
    def validate_target_directory(cls, v: str) -> str:
        return validate_safe_path(
            v,
            allow_none=False,
            field_name="target_dir",
        )


class CscapeNewIECProjectOutput(CscapeOutputBase):
    """Output results from creating a new Horner Cscape IEC 61131-3 project."""

    project_name: str = Field(..., description="Sanitized name of the project.")
    project_path: str = Field(..., description="Absolute path to the created project root directory.")
    target_dir: str = Field(..., description="Parent destination directory.")
    controller_model: str = Field(..., description="Validated controller model target.")
    project_file: Optional[str] = Field(default=None, description="Path to .csp project file.")
    editor_mode: Optional[str] = Field(default=None, description="Editor mode: 'IEC 61131'.")
    cscape_pid: Optional[int] = Field(default=None, description="Process ID if launched in live GUI.")
    main_hwnd: Optional[int] = Field(default=None, description="Main window handle if launched in live GUI.")
    window_title: Optional[str] = Field(default=None, description="Window title.")
    duration_seconds: Optional[float] = Field(default=None, description="Operation duration in seconds.")
    files_created: List[str] = Field(
        default_factory=list,
        description="List of relative file paths created in the project (cscape_project.json, pous/, variables.xml, etc.).",
    )
    target_plc: Optional[str] = Field(default=None, description="Target PLC identifier (alias for controller_model).")
    message: str = Field(..., description="Descriptive status message.")
    created_at: str = Field(default_factory=_get_utc_now_iso, description="UTC timestamp of project creation.")


# Clean aliases
NewIECProjectInput = CscapeNewIECProjectInput
NewIECProjectOutput = CscapeNewIECProjectOutput


# ==============================================================================
# 3. cscape_open_project Schemas
# ==============================================================================

class CscapeOpenProjectInput(CscapeBaseModel):
    """Input parameters for opening a Horner Cscape project."""

    file_path: str = Field(
        ...,
        min_length=1,
        description="Path to Cscape project file (.cpj, .csp, or .xml).",
    )
    read_only: bool = Field(
        default=False,
        description="If True, opens the project in read-only mode to prevent modifications.",
    )
    timeout_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Timeout in seconds for opening the project.",
    )
    require_live_gui: bool = Field(
        default=False,
        description="If True, requires live Cscape GUI to be running; fails closed if GUI is offline.",
    )

    @field_validator("file_path")
    @classmethod
    def validate_project_file_path(cls, v: str) -> str:
        return validate_safe_path(
            v,
            allowed_extensions={".cpj", ".csp", ".xml"},
            allow_none=False,
            field_name="file_path",
        )


class CscapeOpenProjectOutput(CscapeOutputBase):
    """Output results from opening a Horner Cscape project."""

    file_path: str = Field(..., description="Resolved path of the opened project file.")
    project_name: str = Field(..., description="Name of the opened project.")
    controller_model: Optional[str] = Field(default=None, description="Target PLC model configured in project.")
    file_size_bytes: Optional[int] = Field(default=None, description="Size of project file in bytes.")
    is_valid_cfbf: Optional[bool] = Field(default=None, description="True if project is valid OLE2/CFBF container.")
    cscape_version: Optional[str] = Field(default=None, description="Version string extracted from project.")
    offline_validated: bool = Field(default=False, description="Whether project was validated offline (valid CFBF) without live GUI.")
    live_gui_opened: bool = Field(default=False, description="Whether project was opened in live Cscape GUI.")
    open_mode: str = Field(default="offline_validated", description="Mode used: 'offline_validated' or 'live_gui'.")
    sector_size: Optional[int] = Field(default=None, description="CFBF sector size in bytes.")
    stream_entries: Optional[List[str]] = Field(default=None, description="Streams found in CFBF container.")
    horner_markers: Optional[List[str]] = Field(default=None, description="Horner APG markers found in file.")
    already_open: bool = Field(default=False, description="Whether project was already open.")
    cscape_pid: Optional[int] = Field(default=None, description="PID of live Cscape GUI if running.")
    main_hwnd: Optional[int] = Field(default=None, description="HWND of live Cscape GUI if running.")
    window_title: Optional[str] = Field(default="", description="Title of live Cscape window if open.")
    pou_count: int = Field(default=0, ge=0, description="Number of Program Organization Units (POUs) in project.")
    pous: List[str] = Field(default_factory=list, description="List of POU names found in the project.")
    read_only: bool = Field(default=False, description="Whether project was opened in read-only mode.")
    message: str = Field(..., description="Descriptive status message.")
    opened_at: str = Field(default_factory=_get_utc_now_iso, description="UTC timestamp when project was opened.")


# Clean aliases
OpenProjectInput = CscapeOpenProjectInput
OpenProjectOutput = CscapeOpenProjectOutput


# ==============================================================================
# 4. cscape_insert_st Schemas
# ==============================================================================

class CscapeInsertSTInput(CscapeBaseModel):
    """Input parameters for inserting or updating an IEC 61131-3 Structured Text POU."""

    pou_name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Name of the POU (e.g. 'PRG_Main', 'FB_MotorStarter'). Must be a valid IEC 61131-3 identifier.",
    )
    pou_type: Union[POUType, str] = Field(
        ...,
        description="POU type: 'PROGRAM', 'FUNCTION_BLOCK', or 'FUNCTION'.",
    )
    st_code: str = Field(
        ...,
        min_length=1,
        description="IEC 61131-3 Structured Text source code. Strictly pure ST; ladder logic is forbidden.",
    )
    project_path: Optional[str] = Field(
        default=None,
        description="Optional project path or name. If omitted, target is the current active project.",
    )
    cycle_time_ms: int = Field(
        default=10,
        ge=1,
        le=60000,
        description="Cyclic execution period in milliseconds (default 10ms, range 1 - 60000ms).",
    )

    @field_validator("pou_name")
    @classmethod
    def validate_pou_identifier(cls, v: str) -> str:
        try:
            return SafetyGuard.validate_pou_name(v)
        except SecurityError as se:
            raise ValueError(str(se)) from se

    @field_validator("pou_type")
    @classmethod
    def validate_type(cls, v: Union[POUType, str]) -> str:
        raw_val = v.value if isinstance(v, POUType) else str(v)
        try:
            return SafetyGuard.validate_pou_type(raw_val)
        except SecurityError as se:
            raise ValueError(str(se)) from se

    @field_validator("cycle_time_ms")
    @classmethod
    def validate_cycle(cls, v: int) -> int:
        try:
            return SafetyGuard.validate_cycle_time(v)
        except SecurityError as se:
            raise ValueError(str(se)) from se

    @field_validator("st_code")
    @classmethod
    def validate_st_source(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Structured Text source code cannot be empty.")
        # Reject ladder logic artifacts
        ladder_patterns = [
            r"---[\(\[]",
            r"\[\s*[\/ ]?\s*\]",
            r"\(\s*[\/S R]?\s*\)",
            r"---\s*\(\s*\)\s*---",
        ]
        for pat in ladder_patterns:
            if re.search(pat, clean):
                raise ValueError(
                    "Ladder logic artifact detected in Structured Text source. "
                    "Strictly pure IEC 61131-3 Structured Text is required."
                )
        return clean

    @field_validator("project_path")
    @classmethod
    def validate_st_project_path(cls, v: Optional[str]) -> Optional[str]:
        return validate_safe_path(
            v,
            allow_none=True,
            field_name="project_path",
        )


class CscapeInsertSTOutput(CscapeOutputBase):
    """Output results from inserting or updating an IEC 61131-3 Structured Text POU."""

    pou_name: str = Field(..., description="Validated POU identifier.")
    pou_type: str = Field(..., description="POU type ('PROGRAM', 'FUNCTION_BLOCK', 'FUNCTION').")
    file_path: Optional[str] = Field(default=None, description="Absolute file path of the saved .st file.")
    code_hash: Optional[str] = Field(default=None, description="SHA-256 hash of POU source code.")
    line_count: Optional[int] = Field(default=None, description="Total source lines.")
    cycle_time_ms: int = Field(default=10, description="Execution cycle time in milliseconds.")
    variable_count: int = Field(default=0, ge=0, description="Total number of variables declared within the POU.")
    variables_count: Optional[int] = Field(default=None, description="Alias for variable_count.")
    variables: List[Dict[str, Any]] = Field(default_factory=list, description="Parsed variable declaration details.")
    syntax_valid: bool = Field(default=True, description="True if ST syntax parser passed without fatal errors.")
    failure_location: Optional[Dict[str, Any]] = Field(default=None, description="Primary failure location object.")
    project_name: Optional[str] = Field(default=None, description="Target project name.")
    message: str = Field(..., description="Descriptive status message.")
    updated_at: str = Field(default_factory=_get_utc_now_iso, description="UTC timestamp of POU insertion.")
    inserted_at: Optional[str] = Field(default=None, description="Alias for updated_at.")


# Clean aliases
InsertSTInput = CscapeInsertSTInput
InsertSTOutput = CscapeInsertSTOutput


# ==============================================================================
# 5. cscape_compile Schemas
# ==============================================================================

class CscapeCompileInput(CscapeBaseModel):
    """Input parameters for compiling a Horner Cscape project.

    Safety Guarantee:
    - Strictly compile-only mode.
    - Zero download or flashing parameters are accepted.
    - Any attempt to pass hardware download flags is rejected by schema validation.
    """

    project_path: Optional[str] = Field(
        default=None,
        description="Optional project path or name to compile. If omitted, compiles active project.",
    )
    clean_build: bool = Field(
        default=True,
        description="If True, removes all previous build artifacts and executes a full rebuild.",
    )
    timeout_seconds: float = Field(
        default=60.0,
        ge=1.0,
        le=600.0,
        description="Maximum build timeout in seconds.",
    )

    @field_validator("project_path")
    @classmethod
    def validate_compile_path(cls, v: Optional[str]) -> Optional[str]:
        return validate_safe_path(
            v,
            allow_none=True,
            field_name="project_path",
        )


class CscapeCompileOutput(CscapeOutputBase):
    """Output results from compiling a Horner Cscape project."""

    compile_successful: bool = Field(..., description="True if compilation succeeded with zero fatal errors.")
    project_name: Optional[str] = Field(default=None, description="Name of the compiled project.")
    target_plc: Optional[str] = Field(default=None, description="Target architecture (e.g. 'XL4', 'XLE', 'Horner OCS').")
    clean_build: bool = Field(default=True, description="Whether a clean rebuild was executed.")
    command_dispatched: Optional[int] = Field(default=None, description="Win32 command ID dispatched (e.g. 32826).")
    controls_enumerated: Optional[int] = Field(default=None, description="Count of UI controls enumerated.")
    error_count: int = Field(default=0, ge=0, description="Total number of compilation errors.")
    warning_count: int = Field(default=0, ge=0, description="Total number of compilation warnings.")
    build_log: str = Field(default="", description="Compilation build log output.")
    pous_compiled: List[Any] = Field(default_factory=list, description="Status details or names per compiled POU.")
    memory_footprint: Dict[str, Any] = Field(default_factory=dict, description="Estimated code/data memory consumption.")
    duration_ms: float = Field(default=0.0, ge=0.0, description="Compilation duration in milliseconds.")
    build_time_seconds: Optional[float] = Field(default=None, description="Compilation duration in seconds.")
    hardware_lockout_enforced: bool = Field(
        default=True,
        description="Explicit safety guarantee: Compile-only execution; physical PLC download remained locked out.",
    )
    failure_location: Optional[Dict[str, Any]] = Field(default=None, description="Primary failure location object.")
    message: str = Field(..., description="Descriptive status message.")
    timestamp: str = Field(default_factory=_get_utc_now_iso, description="UTC timestamp of compilation.")
    compiled_at: Optional[str] = Field(default=None, description="Alias for timestamp.")


# Clean aliases
CompileInput = CscapeCompileInput
CompileOutput = CscapeCompileOutput


# ==============================================================================
# 6. cscape_get_build_output Schemas
# ==============================================================================

class CscapeGetBuildOutputInput(CscapeBaseModel):
    """Input parameters for retrieving Cscape compilation logs and diagnostics."""

    project_path: Optional[str] = Field(
        default=None,
        description="Optional project path or name. If omitted, queries active project diagnostics.",
    )
    max_lines: int = Field(
        default=500,
        ge=1,
        le=5000,
        description="Maximum lines of raw build log to retrieve.",
    )
    log_level: Union[BuildLogLevel, str] = Field(
        default=BuildLogLevel.ALL,
        description="Log message level filter: 'ALL', 'ERROR', 'WARNING', or 'INFO'.",
    )

    @field_validator("log_level")
    @classmethod
    def validate_level(cls, v: Union[BuildLogLevel, str]) -> str:
        raw_val = v.value if isinstance(v, BuildLogLevel) else str(v).upper().strip()
        allowed = {"ALL", "ERROR", "WARNING", "INFO"}
        if raw_val not in allowed:
            raise ValueError(f"Invalid log level '{v}'. Expected one of: {allowed}")
        return raw_val

    @field_validator("project_path")
    @classmethod
    def validate_build_project_path(cls, v: Optional[str]) -> Optional[str]:
        return validate_safe_path(
            v,
            allow_none=True,
            field_name="project_path",
        )


class CscapeGetBuildOutputOutput(CscapeOutputBase):
    """Output results containing compilation logs and build diagnostics."""

    compile_successful: bool = Field(..., description="True if the last build completed with zero errors.")
    build_successful: Optional[bool] = Field(default=None, description="Alias for compile_successful.")
    clean_build: Optional[bool] = Field(default=None, description="Whether clean build was requested.")
    project_name: Optional[str] = Field(default=None, description="Name of the queried project.")
    raw_log: Optional[str] = Field(default=None, description="Raw unparsed build log.")
    build_log: str = Field(default="", description="Build log text (truncated to max_lines).")
    error_count: int = Field(default=0, ge=0, description="Count of errors reported in build.")
    warning_count: int = Field(default=0, ge=0, description="Count of warnings reported in build.")
    info: List[str] = Field(default_factory=list, description="Informational messages from toolchain.")
    memory_footprint: Optional[Dict[str, Any]] = Field(default=None, description="Memory consumption summary.")
    failure_location: Optional[Dict[str, Any]] = Field(default=None, description="Primary failure location object.")
    message: str = Field(..., description="Descriptive status message.")
    timestamp: str = Field(default_factory=_get_utc_now_iso, description="UTC timestamp of build report.")


# Clean aliases
GetBuildOutputInput = CscapeGetBuildOutputInput
GetBuildOutputOutput = CscapeGetBuildOutputOutput


# ==============================================================================
# 7. cscape_import_variables Schemas
# ==============================================================================

class CscapeImportVariablesInput(CscapeBaseModel):
    """Input parameters for importing variable declarations from a CSV file."""

    csv_path: str = Field(
        ...,
        min_length=1,
        description="Path to CSV file containing variable declarations (columns: Name, Type, Scope, InitialValue, Comment).",
    )
    project_path: Optional[str] = Field(
        default=None,
        description="Optional project path or name to import variables into. If omitted, targets active project.",
    )
    merge_strategy: Union[VariableMergeStrategy, str] = Field(
        default=VariableMergeStrategy.MERGE,
        description="Merge strategy: 'merge' (updates existing and appends new) or 'overwrite' (replaces all).",
    )
    target_scope: str = Field(
        default="GLOBAL",
        description="Default scope for variables if unspecified in CSV ('GLOBAL', 'RETAIN', 'LOCAL').",
    )

    @field_validator("csv_path")
    @classmethod
    def validate_csv_file_path(cls, v: str) -> str:
        return validate_safe_path(
            v,
            allowed_extensions={".csv", ".txt"},
            allow_none=False,
            field_name="csv_path",
        )

    @field_validator("project_path")
    @classmethod
    def validate_import_project_path(cls, v: Optional[str]) -> Optional[str]:
        return validate_safe_path(
            v,
            allow_none=True,
            field_name="project_path",
        )

    @field_validator("merge_strategy")
    @classmethod
    def validate_strategy(cls, v: Union[VariableMergeStrategy, str]) -> str:
        raw = v.value if isinstance(v, VariableMergeStrategy) else str(v).lower().strip()
        if raw not in ("merge", "overwrite"):
            raise ValueError(f"Invalid merge strategy '{v}'. Expected 'merge' or 'overwrite'.")
        return raw

    @field_validator("target_scope")
    @classmethod
    def validate_scope(cls, v: str) -> str:
        clean = v.strip().upper()
        allowed = {"GLOBAL", "RETAIN", "LOCAL", "VAR_GLOBAL", "VAR", "VAR_INPUT", "VAR_OUTPUT"}
        if clean not in allowed:
            raise ValueError(f"Invalid target scope '{v}'. Allowed scopes: {allowed}")
        return clean


class CscapeImportVariablesOutput(CscapeOutputBase):
    """Output results from importing variables from a CSV file."""

    csv_path: Optional[str] = Field(default=None, description="Path of the imported CSV file.")
    file_path: Optional[str] = Field(default=None, description="Path of the imported variable file.")
    format: Optional[str] = Field(default=None, description="Format detected ('CSV' or 'XML').")
    project_name: Optional[str] = Field(default=None, description="Name of target project.")
    count: Optional[int] = Field(default=None, description="Variables count imported.")
    imported_count: Optional[int] = Field(default=None, description="Alias for count.")
    total_variables: Optional[int] = Field(default=None, description="Total variables count.")
    variables_imported: int = Field(default=0, ge=0, description="Count of newly declared variables added.")
    variables_updated: int = Field(default=0, ge=0, description="Count of existing variables updated.")
    variables_count: int = Field(default=0, ge=0, description="Total active variables in project after import.")
    variables: List[Dict[str, Any]] = Field(default_factory=list, description="Imported variable records.")
    variable_names: List[str] = Field(default_factory=list, description="Names of imported variables.")
    conflicts_detected: int = Field(default=0, description="Count of register address collisions.")
    conflict_details: List[Dict[str, Any]] = Field(default_factory=list, description="Details of collisions.")
    validation_status: str = Field(default="VALID", description="'VALID' or 'INVALID'.")
    validation_errors: List[str] = Field(default_factory=list, description="Validation errors encountered.")
    failure_location: Optional[Dict[str, Any]] = Field(default=None, description="Primary failure location object.")
    message: str = Field(..., description="Descriptive status message.")
    timestamp: str = Field(default_factory=_get_utc_now_iso, description="UTC timestamp of import.")


# Clean aliases
ImportVariablesInput = CscapeImportVariablesInput
ImportVariablesOutput = CscapeImportVariablesOutput


# ==============================================================================
# 8. cscape_export_variables Schemas
# ==============================================================================

class CscapeExportVariablesInput(CscapeBaseModel):
    """Input parameters for exporting project variables to a CSV file."""

    output_csv_path: str = Field(
        ...,
        min_length=1,
        description="Destination CSV file path for exported variable definitions.",
    )
    project_path: Optional[str] = Field(
        default=None,
        description="Optional project path or name to export variables from. If omitted, exports from active project.",
    )
    scope_filter: str = Field(
        default="ALL",
        description="Scope filter: 'ALL', 'GLOBAL', 'RETAIN', 'INPUT', 'OUTPUT', or 'LOCAL'.",
    )
    pou_name: Optional[str] = Field(
        default=None,
        description="Optional specific POU name to filter variables for a single POU.",
    )

    @field_validator("output_csv_path")
    @classmethod
    def validate_export_csv_path(cls, v: str) -> str:
        return validate_safe_path(
            v,
            allowed_extensions={".csv", ".txt"},
            allow_none=False,
            field_name="output_csv_path",
        )

    @field_validator("project_path")
    @classmethod
    def validate_export_project_path(cls, v: Optional[str]) -> Optional[str]:
        return validate_safe_path(
            v,
            allow_none=True,
            field_name="project_path",
        )

    @field_validator("pou_name")
    @classmethod
    def validate_export_pou_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return SafetyGuard.validate_pou_name(v)

    @field_validator("scope_filter")
    @classmethod
    def validate_filter(cls, v: str) -> str:
        clean = v.strip().upper()
        allowed = {"ALL", "GLOBAL", "RETAIN", "INPUT", "OUTPUT", "LOCAL", "VAR_GLOBAL", "VAR_INPUT", "VAR_OUTPUT"}
        if clean not in allowed:
            raise ValueError(f"Invalid scope filter '{v}'. Allowed filters: {allowed}")
        return clean


class CscapeExportVariablesOutput(CscapeOutputBase):
    """Output results from exporting project variables to a CSV file."""

    output_csv_path: Optional[str] = Field(default=None, description="Destination path of exported CSV file.")
    output_path: Optional[str] = Field(default=None, description="Destination path of exported file.")
    format_type: str = Field(default="CSV", description="Format exported ('CSV' or 'XML').")
    project_name: Optional[str] = Field(default=None, description="Name of source project.")
    variables_exported: int = Field(default=0, ge=0, description="Number of variable rows exported.")
    written_count: Optional[int] = Field(default=None, description="Alias for variables_exported.")
    file_size_bytes: int = Field(default=0, ge=0, description="Size in bytes of generated file.")
    sha256: str = Field(default="", description="SHA-256 hash checksum of exported file.")
    variables: List[Dict[str, Any]] = Field(default_factory=list, description="List of exported variables.")
    conflicts_detected: int = Field(default=0, description="Count of register address collisions.")
    conflict_details: List[Dict[str, Any]] = Field(default_factory=list, description="Details of collisions.")
    validation_status: str = Field(default="VALID", description="'VALID' or 'INVALID'.")
    validation_errors: List[str] = Field(default_factory=list, description="Validation errors encountered.")
    failure_location: Optional[Dict[str, Any]] = Field(default=None, description="Primary failure location object.")
    message: str = Field(..., description="Descriptive status message.")
    timestamp: str = Field(default_factory=_get_utc_now_iso, description="UTC timestamp of export.")


# Clean aliases
ExportVariablesInput = CscapeExportVariablesInput
ExportVariablesOutput = CscapeExportVariablesOutput


# ==============================================================================
# 9. cscape_run_simulation Schemas
# ==============================================================================

class CscapeRunSimulationInput(CscapeBaseModel):
    """Input parameters for executing discrete software simulation cycles.

    Safety Guarantee:
    - Pure offline software simulation.
    - Zero connection to physical PLC hardware.
    - Extra parameters (such as IP addresses, COM ports, or hardware communication) are forbidden.
    """

    steps: int = Field(
        default=5,
        ge=1,
        le=10000,
        description="Number of discrete scan cycles to simulate (range: 1 to 10000).",
    )
    code: Optional[str] = Field(
        default=None,
        description="Structured Text source code to simulate. If omitted, uses POU from project.",
    )
    pou_name: Optional[str] = Field(
        default=None,
        description="Name of POU in project to simulate if code is not provided directly.",
    )
    inputs: Dict[str, Any] = Field(
        default_factory=dict,
        description="Map of input variables to their values (scalars or lists of step values, e.g. {'Start': True}).",
    )
    register_map: Optional[Dict[str, str]] = Field(
        default=None,
        description="Optional mapping from Structured Text variable names to Horner OCS registers (e.g. {'StartCmd': '%M1'}).",
    )
    project_path: Optional[str] = Field(
        default=None,
        description="Optional project path if resolving POU by name.",
    )

    @field_validator("steps")
    @classmethod
    def validate_simulation_step_count(cls, v: int) -> int:
        try:
            return SafetyGuard.validate_simulation_steps(v)
        except SecurityError as se:
            raise ValueError(str(se)) from se

    @field_validator("code")
    @classmethod
    def validate_simulation_code(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        clean = v.strip()
        if not clean:
            return None
        # Reject ladder logic
        if re.search(r"---[\(\[]|\[\s*[\/ ]?\s*\]|\(\s*[\/S R]?\s*\)", clean):
            raise ValueError("Ladder logic is not supported in simulation. Structured Text only.")
        return clean

    @field_validator("pou_name")
    @classmethod
    def validate_sim_pou_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return SafetyGuard.validate_pou_name(v)

    @field_validator("project_path")
    @classmethod
    def validate_sim_project_path(cls, v: Optional[str]) -> Optional[str]:
        return validate_safe_path(
            v,
            allow_none=True,
            field_name="project_path",
        )

    @field_validator("register_map")
    @classmethod
    def validate_register_mapping(cls, v: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
        if v is None:
            return None
        validated_map = {}
        for var_name, reg_addr in v.items():
            clean_var = var_name.strip()
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", clean_var):
                raise ValueError(f"Invalid variable name '{clean_var}' in register_map.")
            validated_map[clean_var] = validate_ocs_register(reg_addr)
        return validated_map

    @field_validator("inputs")
    @classmethod
    def validate_inputs_dict(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(v, dict):
            raise ValueError("Simulation inputs must be a dictionary.")
        for key in v.keys():
            if str(key).startswith("%"):
                validate_ocs_register(str(key))
        return v

    @model_validator(mode="after")
    def validate_code_or_pou_specified(self) -> CscapeRunSimulationInput:
        if not self.code and not self.pou_name:
            raise ValueError("Either 'code' (ST source) or 'pou_name' must be provided for simulation.")
        return self


class CscapeRunSimulationOutput(CscapeOutputBase):
    """Output results from executing software simulation cycles."""

    steps_executed: int = Field(default=0, ge=0, description="Total discrete scan cycles executed.")
    total_cycles: Optional[int] = Field(default=None, description="Alias for steps_executed.")
    trace: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Step-by-step execution traces with variable snapshots per scan cycle.",
    )
    final_state: Dict[str, Any] = Field(
        default_factory=dict,
        description="Final variable state dictionary after all simulation steps.",
    )
    final_registers: Dict[str, Any] = Field(
        default_factory=dict,
        description="Final non-zero registers snapshot.",
    )
    final_variables: Dict[str, Any] = Field(
        default_factory=dict,
        description="Final symbolic variable snapshot.",
    )
    execution_time_ms: float = Field(default=0.0, ge=0.0, description="Simulation runtime duration in milliseconds.")
    elapsed_time_ms: Optional[float] = Field(default=None, description="Alias for execution_time_ms.")
    hardware_connected: bool = Field(
        default=False,
        description="Safety certificate: Confirms execution remained 100% offline software simulation.",
    )
    isolation_enforced: bool = Field(
        default=True,
        description="Safety guarantee of 100% software isolation.",
    )
    hardware_lockout_enforced: bool = Field(
        default=True,
        description="Safety guarantee of hardware lockout.",
    )
    failure_location: Optional[Dict[str, Any]] = Field(default=None, description="Primary failure location object.")
    message: str = Field(..., description="Descriptive status message.")
    timestamp: str = Field(default_factory=_get_utc_now_iso, description="UTC timestamp of simulation run.")


# Clean aliases
RunSimulationInput = CscapeRunSimulationInput
RunSimulationOutput = CscapeRunSimulationOutput


# ==============================================================================
# 10. Simulation Cycle & Register Manipulation Schemas
# ==============================================================================

class CscapeSimulateCycleInput(CscapeBaseModel):
    """Input parameters for simulating a single scan cycle in software memory."""

    dt_ms: float = Field(
        default=10.0,
        ge=0.1,
        le=60000.0,
        description="Scan cycle time duration in milliseconds (default 10.0ms).",
    )
    inputs: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional input variable values or register inputs for the cycle.",
    )
    register_writes: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Direct register writes to apply before execution (%R, %AI, %AQ, %I, %Q, %M, %T).",
    )
    project_name: Optional[str] = Field(
        default=None,
        description="Optional project name targeting specific simulation context (defaults to active project).",
    )

    @field_validator("project_name")
    @classmethod
    def validate_sim_proj_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return SafetyGuard.validate_project_name(v)

    @field_validator("inputs")
    @classmethod
    def validate_sim_inputs(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if v is None:
            return None
        for key in v.keys():
            if str(key).startswith("%"):
                validate_ocs_register(str(key))
        return v

    @field_validator("register_writes")
    @classmethod
    def validate_reg_writes(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if v is None:
            return None
        for key in v.keys():
            validate_ocs_register(str(key))
        return v


class CscapeSimulateCycleOutput(CscapeOutputBase):
    """Output results from executing a single simulation scan cycle."""

    cycle: int = Field(..., description="Cycle index after execution.")
    time_ms: float = Field(..., ge=0.0, description="Accumulated simulation time in milliseconds.")
    dt_ms: float = Field(..., ge=0.0, description="Time delta for this cycle.")
    system_bits: Dict[str, bool] = Field(default_factory=dict, description="Horner system bits (%S1..%S9).")
    registers: Dict[str, Any] = Field(default_factory=dict, description="Non-zero register snapshot.")
    variables: Dict[str, Any] = Field(default_factory=dict, description="Symbolic variable snapshot.")
    isolation_enforced: bool = Field(default=True, description="Safety guarantee of 100% software isolation.")
    hardware_lockout_enforced: bool = Field(default=True, description="Safety guarantee of hardware port lockout.")
    failure_location: Optional[Dict[str, Any]] = Field(default=None, description="Primary failure location object.")
    message: str = Field(..., description="Descriptive status message.")
    timestamp: str = Field(default_factory=_get_utc_now_iso, description="UTC timestamp.")


class CscapeReadRegisterInput(CscapeBaseModel):
    """Input parameters for reading a Horner OCS register from simulation memory."""

    address: str = Field(
        ...,
        description="Horner OCS register address to read (e.g. '%R1', '%AI1', '%M7', '%R100.0').",
    )
    data_type: str = Field(
        default="AUTO",
        description="Interpreted data type: 'AUTO', 'INT', 'UINT', 'DINT', 'REAL', or 'BOOL'.",
    )
    project_name: Optional[str] = Field(
        default=None,
        description="Optional project name targeting specific simulation context.",
    )

    @field_validator("address")
    @classmethod
    def validate_read_addr(cls, v: str) -> str:
        return validate_ocs_register(v)

    @field_validator("project_name")
    @classmethod
    def validate_read_proj(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return SafetyGuard.validate_project_name(v)


class CscapeReadRegisterOutput(CscapeOutputBase):
    """Output results from reading a Horner OCS register."""

    address: str = Field(..., description="Canonical uppercase register address.")
    value: Optional[Union[int, float, bool]] = Field(default=None, description="Read register value.")
    data_type: str = Field(default="AUTO", description="Data type representation.")
    bound_variable: Optional[str] = Field(default=None, description="Associated variable name if mapped.")
    isolation_enforced: bool = Field(default=True, description="Pure software isolation guarantee.")
    hardware_lockout_enforced: bool = Field(default=True, description="Hardware lockout guarantee.")
    failure_location: Optional[Dict[str, Any]] = Field(default=None, description="Primary failure location object.")
    message: str = Field(..., description="Descriptive status message.")
    timestamp: str = Field(default_factory=_get_utc_now_iso, description="UTC timestamp.")


class CscapeWriteRegisterInput(CscapeBaseModel):
    """Input parameters for writing a Horner OCS register in simulation memory."""

    address: str = Field(
        ...,
        description="Horner OCS register address to write (e.g. '%R1', '%AI1', '%M7', '%R100.0').",
    )
    value: Union[int, float, bool] = Field(
        ...,
        description="Value to write into register memory (int, float, or bool).",
    )
    data_type: str = Field(
        default="AUTO",
        description="Data type format: 'AUTO', 'INT', 'UINT', 'DINT', 'REAL', or 'BOOL'.",
    )
    project_name: Optional[str] = Field(
        default=None,
        description="Optional project name targeting specific simulation context.",
    )

    @field_validator("address")
    @classmethod
    def validate_write_addr(cls, v: str) -> str:
        return validate_ocs_register(v)

    @field_validator("project_name")
    @classmethod
    def validate_write_proj(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return SafetyGuard.validate_project_name(v)


class CscapeWriteRegisterOutput(CscapeOutputBase):
    """Output results from writing a Horner OCS register."""

    address: str = Field(..., description="Canonical uppercase register address.")
    value: Union[int, float, bool] = Field(..., description="Value written.")
    data_type: str = Field(default="AUTO", description="Data type format.")
    bound_variable: Optional[str] = Field(default=None, description="Associated variable name if mapped.")
    isolation_enforced: bool = Field(default=True, description="Pure software isolation guarantee.")
    hardware_lockout_enforced: bool = Field(default=True, description="Hardware lockout guarantee.")
    failure_location: Optional[Dict[str, Any]] = Field(default=None, description="Primary failure location object.")
    message: str = Field(..., description="Descriptive status message.")
    timestamp: str = Field(default_factory=_get_utc_now_iso, description="UTC timestamp.")


# Clean aliases
SimulateCycleInput = CscapeSimulateCycleInput
SimulateCycleOutput = CscapeSimulateCycleOutput
ReadRegisterInput = CscapeReadRegisterInput
ReadRegisterOutput = CscapeReadRegisterOutput
WriteRegisterInput = CscapeWriteRegisterInput
WriteRegisterOutput = CscapeWriteRegisterOutput


# ==============================================================================
# Convenience & Lifecycle Tool Schemas
# ==============================================================================

class CscapeCreateProjectInput(CscapeBaseModel):
    """Input parameters for cscape_create_project."""
    name: str = Field(..., min_length=1, max_length=64, description="Project name.")
    description: Optional[str] = Field(default="", max_length=1024, description="Description.")
    target_plc: Optional[str] = Field(default="XL4", description="Target PLC model.")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        try:
            return SafetyGuard.validate_project_name(v)
        except SecurityError as se:
            raise ValueError(str(se)) from se

    @field_validator("target_plc")
    @classmethod
    def validate_target(cls, v: Optional[str]) -> str:
        if not v:
            return "XL4"
        try:
            return SafetyGuard.validate_target_plc(v)
        except SecurityError as se:
            raise ValueError(str(se)) from se


class CscapeCreateProjectOutput(CscapeNewIECProjectOutput):
    """Output results from cscape_create_project."""
    pass


class CscapeAddSTPOUInput(CscapeBaseModel):
    """Input parameters for cscape_add_st_pou."""
    project_name: str = Field(..., min_length=1, max_length=64, description="Project name.")
    pou_name: str = Field(..., min_length=1, max_length=64, description="POU identifier.")
    pou_type: Union[POUType, str] = Field(..., description="POU type ('PROGRAM', 'FUNCTION_BLOCK', 'FUNCTION').")
    code: str = Field(..., min_length=1, description="Structured Text source code.")
    cycle_time_ms: int = Field(default=10, ge=1, le=60000, description="Cycle time in ms.")
    allow_invalid: bool = Field(default=False, description="Allow saving invalid code.")


class CscapeAddSTPOUOutput(CscapeInsertSTOutput):
    """Output results from cscape_add_st_pou."""
    pass


class CscapeValidateSTInput(CscapeBaseModel):
    """Input parameters for cscape_validate_st."""
    code: str = Field(..., min_length=1, description="Structured Text source code to validate.")


class CscapeValidateSTOutput(CscapeOutputBase):
    """Output results from cscape_validate_st."""
    valid: bool = Field(..., description="True if ST syntax is valid.")
    pou_name: Optional[str] = Field(default=None, description="Detected POU name.")
    pou_type: Optional[str] = Field(default=None, description="Detected POU type.")
    return_type: Optional[str] = Field(default=None, description="Function return type if FUNCTION POU.")
    metrics: Dict[str, Any] = Field(default_factory=dict, description="AST lines and metrics.")
    variables: List[Dict[str, Any]] = Field(default_factory=list, description="Declared variables.")
    failure_location: Optional[Dict[str, Any]] = Field(default=None, description="Primary failure location.")
    message: str = Field(default="", description="Descriptive validation message.")


class CscapeInspectVariablesInput(CscapeBaseModel):
    """Input parameters for cscape_inspect_variables."""
    project_name: str = Field(..., min_length=1, max_length=64, description="Project name.")


class CscapeInspectVariablesOutput(CscapeOutputBase):
    """Output results from cscape_inspect_variables."""
    project_name: str = Field(..., description="Project name.")
    total_variables: int = Field(default=0, ge=0, description="Total variable count.")
    pous: List[str] = Field(default_factory=list, description="POU names.")
    variables: List[Dict[str, Any]] = Field(default_factory=list, description="Variable declarations.")
    by_scope: Dict[str, Any] = Field(default_factory=dict, description="Variables grouped by scope.")
    message: str = Field(default="", description="Status message.")


class CscapeCompileProjectInput(CscapeBaseModel):
    """Input parameters for cscape_compile_project."""
    project_name: str = Field(..., min_length=1, max_length=64, description="Project name.")
    clean_build: bool = Field(default=True, description="Execute clean rebuild.")
    cscape_hwnd: Optional[int] = Field(default=None, description="Cscape window handle.")
    require_live_gui: bool = Field(default=False, description="Require live Cscape GUI.")


class CscapeCompileProjectOutput(CscapeCompileOutput):
    """Output results from cscape_compile_project."""
    pass


class CscapeGetDiagnosticsInput(CscapeBaseModel):
    """Input parameters for cscape_get_diagnostics."""
    project_name: str = Field(..., min_length=1, max_length=64, description="Project name.")


class CscapeGetDiagnosticsOutput(CscapeGetBuildOutputOutput):
    """Output results from cscape_get_diagnostics."""
    pass


class CscapeSimulatePOUInput(CscapeBaseModel):
    """Input parameters for cscape_simulate_pou."""
    code: str = Field(..., min_length=1, description="Structured Text code.")
    inputs: Dict[str, Any] = Field(default_factory=dict, description="Simulation input values.")
    steps: int = Field(default=5, ge=1, le=10000, description="Simulation steps.")


class CscapeSimulatePOUOutput(CscapeRunSimulationOutput):
    """Output results from cscape_simulate_pou."""
    pass


class CscapeExportProjectInput(CscapeBaseModel):
    """Input parameters for cscape_export_project."""
    project_name: str = Field(..., min_length=1, max_length=64, description="Project name.")
    output_format: str = Field(default="csp", description="Export format.")


class CscapeExportProjectOutput(CscapeOutputBase):
    """Output results from cscape_export_project."""
    project_name: str = Field(..., description="Exported project name.")
    output_format: str = Field(..., description="Format exported.")
    export_file: str = Field(..., description="Path to generated export file.")
    size_bytes: int = Field(default=0, ge=0, description="File size in bytes.")
    sha256: str = Field(default="", description="SHA-256 digest of export file.")
    cfbf_inspection: Optional[Dict[str, Any]] = Field(default=None, description="CFBF container inspection details.")
    warning: Optional[str] = Field(default=None, description="Warning if quarantined format.")
    message: str = Field(default="", description="Status message.")


class CscapeReadVariablesInput(CscapeBaseModel):
    """Input parameters for cscape_read_variables."""
    file_path: str = Field(..., min_length=1, description="File or directory path.")
    merge_strategy: str = Field(default="MERGE", description="Merge strategy.")
    delimiter: Optional[str] = Field(default=None, description="CSV delimiter.")


class CscapeReadVariablesOutput(CscapeImportVariablesOutput):
    """Output results from cscape_read_variables."""
    pass


class CscapeWriteVariablesInput(CscapeBaseModel):
    """Input parameters for cscape_write_variables."""
    output_path: str = Field(..., min_length=1, description="Output file path.")
    variables: Optional[List[Dict[str, Any]]] = Field(default=None, description="Variables list.")
    format_type: str = Field(default="CSV", description="Format ('CSV' or 'XML').")
    delimiter: str = Field(default=";", description="Delimiter.")
    scopes: Optional[List[str]] = Field(default=None, description="Scopes filter.")
    source_file: Optional[str] = Field(default=None, description="Source file.")


class CscapeWriteVariablesOutput(CscapeExportVariablesOutput):
    """Output results from cscape_write_variables."""
    pass


# ==============================================================================
# Phase P3: Native Cscape HMI Schemas
# ==============================================================================

class CscapeHMIInventoryInput(CscapeBaseModel):
    """Input parameters for cscape_hmi_inventory."""
    project_name: Optional[str] = Field(default=None, description="Optional project name.")
    project_path: Optional[str] = Field(default=None, description="Optional path to .csp project.")


class CscapeHMIInventoryOutput(CscapeOutputBase):
    """Output results from cscape_hmi_inventory."""
    model_config = ConfigDict(extra="allow")
    project_name: Optional[str] = Field(default=None, description="Project name.")
    screens: Optional[List[Dict[str, Any]]] = Field(default=None, description="Enumerated screen records.")
    screen_count: Optional[int] = Field(default=None, description="Total screen count.")
    objects: Optional[List[Dict[str, Any]]] = Field(default=None, description="Enumerated graphics objects.")
    object_count: Optional[int] = Field(default=None, description="Total graphics object count.")
    inventory: Optional[Dict[str, Any]] = Field(default=None, description="Structured HMI inventory dictionary.")


class CscapeHMIApplyGroupInput(CscapeBaseModel):
    """Input parameters for cscape_hmi_apply_group."""
    project_name: Optional[str] = Field(default=None, description="Optional project name.")
    project_path: Optional[str] = Field(default=None, description="Optional path to .csp project.")
    screen_id: int = Field(default=1, ge=1, description="Screen ID to apply group objects to.")
    custom_params: Optional[Dict[str, Any]] = Field(default=None, description="Custom parameters dictionary.")


class CscapeHMIApplyGroupOutput(CscapeOutputBase):
    """Output results from cscape_hmi_apply_group."""
    model_config = ConfigDict(extra="allow")
    group_applied: Optional[str] = Field(default=None, description="Applied group identifier.")
    screen_id: Optional[int] = Field(default=None, description="Screen ID.")
    objects_created: Optional[List[Dict[str, Any]]] = Field(default=None, description="Created HMI objects.")


class CscapeHMIReadPropertiesInput(CscapeBaseModel):
    """Input parameters for cscape_hmi_read_properties."""
    project_name: Optional[str] = Field(default=None, description="Optional project name.")
    project_path: Optional[str] = Field(default=None, description="Optional path to .csp project.")
    screen_id: int = Field(default=1, ge=1, description="Target screen ID.")


class CscapeHMIReadPropertiesOutput(CscapeOutputBase):
    """Output results from cscape_hmi_read_properties."""
    model_config = ConfigDict(extra="allow")
    screen_id: Optional[int] = Field(default=None, description="Target screen ID.")
    properties: Optional[Dict[str, Any]] = Field(default=None, description="HMI object properties dictionary.")


class CscapeHMIVerifyBindingsInput(CscapeBaseModel):
    """Input parameters for cscape_hmi_verify_bindings."""
    project_name: Optional[str] = Field(default=None, description="Optional project name.")
    project_path: Optional[str] = Field(default=None, description="Optional path to .csp project.")
    screen_id: int = Field(default=1, ge=1, description="Target screen ID.")
    pou_code: Optional[str] = Field(default=None, description="Associated POU source code.")
    binding_overrides: Optional[Dict[str, str]] = Field(default=None, description="Binding override mapping.")
    custom_objects: Optional[List[Dict[str, Any]]] = Field(default=None, description="Custom object definitions.")


class CscapeHMIVerifyBindingsOutput(CscapeOutputBase):
    """Output results from cscape_hmi_verify_bindings."""
    model_config = ConfigDict(extra="allow")
    bindings_valid: Optional[bool] = Field(default=None, description="True if all HMI variable bindings are valid.")
    verified_bindings: Optional[List[Dict[str, Any]]] = Field(default=None, description="Verified binding records.")


class CscapeHMISaveCloseReopenInput(CscapeBaseModel):
    """Input parameters for cscape_hmi_save_close_reopen."""
    project_name: Optional[str] = Field(default=None, description="Optional project name.")
    project_path: Optional[str] = Field(default=None, description="Optional path to .csp project.")


class CscapeHMISaveCloseReopenOutput(CscapeOutputBase):
    """Output results from cscape_hmi_save_close_reopen."""
    model_config = ConfigDict(extra="allow")
    reopened: Optional[bool] = Field(default=None, description="True if project successfully reopened.")
    durability_verified: Optional[bool] = Field(default=None, description="True if durability checks passed.")


# ==============================================================================
# Phase P4: Fixture Evolution Schemas
# ==============================================================================

class CscapeFixtureRequestToSpecInput(CscapeBaseModel):
    """Input parameters for cscape_fixture_request_to_spec."""
    fixture_id: str = Field(default="TankLevel_P4_Fixture", description="Fixture ID.")
    description: str = Field(default="Closed-loop buffer tank level controller with dual threshold alarms", description="Description.")
    process_variable: str = Field(default="TankLevelPV", description="Process variable name.")
    engineering_unit: str = Field(default="%", description="Engineering unit.")
    lo_limit: float = Field(default=30.0, description="Low limit alarm threshold.")
    hi_limit: float = Field(default=70.0, description="High limit alarm threshold.")
    setpoint: float = Field(default=50.0, description="Target setpoint.")
    level_label: str = Field(default="Tank Level PV", description="Display label.")
    project_name: str = Field(default="TankLevel_P4_Dedicated", description="Project name.")
    screen_id: int = Field(default=1, ge=1, description="Screen ID.")


class CscapeFixtureRequestToSpecOutput(CscapeOutputBase):
    """Output results from cscape_fixture_request_to_spec."""
    model_config = ConfigDict(extra="allow")
    spec: Optional[Dict[str, Any]] = Field(default=None, description="Generated fixture specification dictionary.")


class CscapeFixtureCreateInput(CscapeBaseModel):
    """Input parameters for cscape_fixture_create."""
    spec: Optional[Dict[str, Any]] = Field(default=None, description="Specification dictionary.")
    project_name: Optional[str] = Field(default=None, description="Project name override.")


class CscapeFixtureCreateOutput(CscapeOutputBase):
    """Output results from cscape_fixture_create."""
    model_config = ConfigDict(extra="allow")
    fixture_created: Optional[bool] = Field(default=None, description="True if fixture was created.")
    project_name: Optional[str] = Field(default=None, description="Project name.")


class CscapeFixtureSelectiveEditInput(CscapeBaseModel):
    """Input parameters for cscape_fixture_selective_edit."""
    project_name: str = Field(default="TankLevel_P4_Dedicated", description="Project name.")
    new_lo_limit: float = Field(default=35.0, description="New low limit threshold.")
    new_hi_limit: float = Field(default=75.0, description="New high limit threshold.")
    new_level_label: str = Field(default="Buffer Tank Level PV", description="New display label.")
    expected_prior_revision: Optional[str] = Field(default=None, description="Expected prior revision identifier.")
    expected_prior_hash: Optional[str] = Field(default=None, description="Expected prior content SHA-256 hash.")


class CscapeFixtureSelectiveEditOutput(CscapeOutputBase):
    """Output results from cscape_fixture_selective_edit."""
    model_config = ConfigDict(extra="allow")
    edited: Optional[bool] = Field(default=None, description="True if selective edit succeeded.")
    new_hash: Optional[str] = Field(default=None, description="New content hash.")


class CscapeFixtureRevisionImpactInput(CscapeBaseModel):
    """Input parameters for cscape_fixture_revision_impact."""
    project_name: str = Field(default="TankLevel_P4_Dedicated", description="Project name.")


class CscapeFixtureRevisionImpactOutput(CscapeOutputBase):
    """Output results from cscape_fixture_revision_impact."""
    model_config = ConfigDict(extra="allow")
    impact_analysis: Optional[Dict[str, Any]] = Field(default=None, description="Impact analysis details.")
    revisions: Optional[List[Dict[str, Any]]] = Field(default=None, description="Revision history.")


class CscapeFixtureDurabilityCheckInput(CscapeBaseModel):
    """Input parameters for cscape_fixture_durability_check."""
    project_name: str = Field(default="TankLevel_P4_Dedicated", description="Project name.")


class CscapeFixtureDurabilityCheckOutput(CscapeOutputBase):
    """Output results from cscape_fixture_durability_check."""
    model_config = ConfigDict(extra="allow")
    durability_passed: Optional[bool] = Field(default=None, description="True if durability checks passed.")
    checks: Optional[Dict[str, Any]] = Field(default=None, description="Detailed durability check results.")


class CscapeFixtureDetectConflictInput(CscapeBaseModel):
    """Input parameters for cscape_fixture_detect_conflict."""
    project_name: str = Field(default="TankLevel_P4_Dedicated", description="Project name.")
    expected_hash: str = Field(default="", description="Expected hash to verify concurrency conflict.")


class CscapeFixtureDetectConflictOutput(CscapeOutputBase):
    """Output results from cscape_fixture_detect_conflict."""
    model_config = ConfigDict(extra="allow")
    conflict_detected: Optional[bool] = Field(default=None, description="True if external mutation conflict was detected.")
    current_hash: Optional[str] = Field(default=None, description="Current content hash.")


# ==============================================================================
# Phase P5: Native Modbus PV Provider Schemas
# ==============================================================================

class CscapeModbusCreateConfigInput(CscapeBaseModel):
    """Input parameters for cscape_modbus_create_config."""
    project_name: str = Field(default="TankLevel_P5_Dedicated", description="Target project name.")
    transport: str = Field(default="MODBUS_TCP", description="Transport ('MODBUS_TCP' or 'MODBUS_RTU').")
    ip_address: str = Field(default="127.0.0.1", description="Endpoint IP address.")
    port: int = Field(default=15502, ge=1, le=65535, description="Port number.")
    unit_id: int = Field(default=1, ge=1, le=255, description="Modbus slave/unit ID.")
    function_code: int = Field(default=3, description="Modbus function code (FC03 or FC04).")
    modicon_address: int = Field(default=40001, description="1-based Modicon register address.")
    wire_offset: int = Field(default=0, ge=0, description="0-based wire address offset.")
    ocs_register: str = Field(default="%AI1", description="Target Horner OCS register.")
    variable_name: str = Field(default="TankLevelPV", description="Associated variable name.")
    raw_min: float = Field(default=0.0, description="Raw minimum scale.")
    raw_max: float = Field(default=32000.0, description="Raw maximum scale.")
    eu_min: float = Field(default=0.0, description="Engineering unit minimum (e.g. 0.0%).")
    eu_max: float = Field(default=100.0, description="Engineering unit maximum (e.g. 100.0%).")
    poll_interval_ms: int = Field(default=100, ge=10, description="Polling interval in milliseconds.")
    timeout_ms: int = Field(default=1000, ge=100, description="Response timeout in milliseconds.")
    stale_timeout_ms: int = Field(default=2000, ge=200, description="Stale data timeout in milliseconds.")


class CscapeModbusCreateConfigOutput(CscapeOutputBase):
    """Output results from cscape_modbus_create_config."""
    model_config = ConfigDict(extra="allow")
    project_name: Optional[str] = Field(default=None, description="Project name.")
    config: Optional[Dict[str, Any]] = Field(default=None, description="Modbus configuration dictionary.")


class CscapeModbusPersistConfigInput(CscapeBaseModel):
    """Input parameters for cscape_modbus_persist_config."""
    project_name: str = Field(default="TankLevel_P5_Dedicated", description="Project name.")
    config: Optional[Dict[str, Any]] = Field(default=None, description="Optional configuration dictionary to persist.")


class CscapeModbusPersistConfigOutput(CscapeOutputBase):
    """Output results from cscape_modbus_persist_config."""
    model_config = ConfigDict(extra="allow")
    persisted: Optional[bool] = Field(default=None, description="True if configuration persisted.")
    config_path: Optional[str] = Field(default=None, description="Path to persisted configuration file.")


class CscapeModbusReadConfigInput(CscapeBaseModel):
    """Input parameters for cscape_modbus_read_config."""
    project_name: str = Field(default="TankLevel_P5_Dedicated", description="Project name.")


class CscapeModbusReadConfigOutput(CscapeOutputBase):
    """Output results from cscape_modbus_read_config."""
    model_config = ConfigDict(extra="allow")
    project_name: Optional[str] = Field(default=None, description="Project name.")
    config: Optional[Dict[str, Any]] = Field(default=None, description="Retrieved Modbus configuration dictionary.")


class CscapeModbusProtocolCheckInput(CscapeBaseModel):
    """Input parameters for cscape_modbus_protocol_check."""
    host: str = Field(default="127.0.0.1", description="Endpoint host.")
    port: int = Field(default=15502, ge=1, le=65535, description="Endpoint port.")
    unit_id: int = Field(default=1, ge=1, le=255, description="Unit ID.")
    function_code: int = Field(default=3, description="Function code.")
    start_address: int = Field(default=0, ge=0, description="0-based start register offset.")
    quantity: int = Field(default=1, ge=1, le=125, description="Register quantity.")
    simulated_raw_value: Optional[int] = Field(default=17600, description="Simulated raw integer value.")


class CscapeModbusProtocolCheckOutput(CscapeOutputBase):
    """Output results from cscape_modbus_protocol_check."""
    model_config = ConfigDict(extra="allow")
    protocol_valid: Optional[bool] = Field(default=None, description="True if protocol query validated.")
    raw_value: Optional[int] = Field(default=None, description="Raw register integer value.")
    scaled_value: Optional[float] = Field(default=None, description="Scaled engineering unit value.")


class CscapeModbusConversionDocInput(CscapeBaseModel):
    """Input parameters for cscape_modbus_conversion_doc."""
    level_pct: float = Field(default=55.0, ge=0.0, le=100.0, description="Tank level percentage.")


class CscapeModbusConversionDocOutput(CscapeOutputBase):
    """Output results from cscape_modbus_conversion_doc."""
    model_config = ConfigDict(extra="allow")
    level_pct: Optional[float] = Field(default=None, description="Tank level percentage.")
    doc_markdown: Optional[str] = Field(default=None, description="Markdown conversion guide.")
    scaling_table: Optional[List[Dict[str, Any]]] = Field(default=None, description="Reference scaling lookup table.")


# ==============================================================================
# Air-Gapped Offline Packaging Tool Schemas
# ==============================================================================

class CscapePackageOfflineBundleInput(CscapeBaseModel):
    """Input parameters for cscape_package_offline_bundle."""
    project_name: str = Field(..., description="Target project name to package.")
    output_dir: Optional[str] = Field(default=None, description="Output directory for generated distribution bundle.")
    bundle_name: Optional[str] = Field(default=None, description="Custom package file name without extension.")
    include_st_sources: bool = Field(default=True, description="Whether to include exported Structured Text POUs.")
    include_manifest: bool = Field(default=True, description="Whether to include cryptographic SHA-256 manifest.")
    include_manual_guide: bool = Field(default=True, description="Whether to include field manual loading instructions.")


class CscapePackageOfflineBundleOutput(CscapeOutputBase):
    """Output results from cscape_package_offline_bundle."""
    model_config = ConfigDict(extra="allow")
    project_name: Optional[str] = Field(default=None, description="Packaged project name.")
    bundle_path: Optional[str] = Field(default=None, description="Absolute path to generated ZIP bundle.")
    bundle_size_bytes: Optional[int] = Field(default=None, description="Size of generated package in bytes.")
    file_count: Optional[int] = Field(default=None, description="Total number of archived assets.")
    files_included: Optional[List[str]] = Field(default=None, description="List of relative file paths in package.")
    bundle_sha256: Optional[str] = Field(default=None, description="SHA-256 digest of package zip file.")
    air_gapped_distribution: Optional[bool] = Field(default=None, description="True for air-gapped distribution.")
    zero_download_enforced: Optional[bool] = Field(default=None, description="True when physical download lockout is enforced.")
    manual_commissioning_required: Optional[bool] = Field(default=None, description="True requiring manual engineer commissioning.")


# ==============================================================================
# Tool Schema Registry & Utilities (All Registered Tools)
# ==============================================================================

TOOL_SCHEMAS: Dict[str, Dict[str, Type[CscapeBaseModel]]] = {
    # Air-Gapped Offline Packaging
    "cscape_package_offline_bundle": {
        "input": CscapePackageOfflineBundleInput,
        "output": CscapePackageOfflineBundleOutput,
    },
    # 12 Core Tools
    "cscape_launch_ide": {
        "input": CscapeLaunchIDEInput,
        "output": CscapeLaunchIDEOutput,
    },
    "cscape_new_iec_project": {
        "input": CscapeNewIECProjectInput,
        "output": CscapeNewIECProjectOutput,
    },
    "cscape_open_project": {
        "input": CscapeOpenProjectInput,
        "output": CscapeOpenProjectOutput,
    },
    "cscape_insert_st": {
        "input": CscapeInsertSTInput,
        "output": CscapeInsertSTOutput,
    },
    "cscape_insert_st_pou": {
        "input": CscapeInsertSTInput,
        "output": CscapeInsertSTOutput,
    },
    "cscape_compile": {
        "input": CscapeCompileInput,
        "output": CscapeCompileOutput,
    },
    "cscape_get_build_output": {
        "input": CscapeGetBuildOutputInput,
        "output": CscapeGetBuildOutputOutput,
    },
    "cscape_import_variables": {
        "input": CscapeImportVariablesInput,
        "output": CscapeImportVariablesOutput,
    },
    "cscape_export_variables": {
        "input": CscapeExportVariablesInput,
        "output": CscapeExportVariablesOutput,
    },
    "cscape_run_simulation": {
        "input": CscapeRunSimulationInput,
        "output": CscapeRunSimulationOutput,
    },
    "cscape_simulate_cycle": {
        "input": CscapeSimulateCycleInput,
        "output": CscapeSimulateCycleOutput,
    },
    "cscape_read_register": {
        "input": CscapeReadRegisterInput,
        "output": CscapeReadRegisterOutput,
    },
    "cscape_write_register": {
        "input": CscapeWriteRegisterInput,
        "output": CscapeWriteRegisterOutput,
    },
    # Convenience & Lifecycle Wrappers
    "cscape_create_project": {
        "input": CscapeCreateProjectInput,
        "output": CscapeCreateProjectOutput,
    },
    "cscape_add_st_pou": {
        "input": CscapeAddSTPOUInput,
        "output": CscapeAddSTPOUOutput,
    },
    "cscape_validate_st": {
        "input": CscapeValidateSTInput,
        "output": CscapeValidateSTOutput,
    },
    "cscape_inspect_variables": {
        "input": CscapeInspectVariablesInput,
        "output": CscapeInspectVariablesOutput,
    },
    "cscape_compile_project": {
        "input": CscapeCompileProjectInput,
        "output": CscapeCompileProjectOutput,
    },
    "cscape_get_diagnostics": {
        "input": CscapeGetDiagnosticsInput,
        "output": CscapeGetDiagnosticsOutput,
    },
    "cscape_simulate_pou": {
        "input": CscapeSimulatePOUInput,
        "output": CscapeSimulatePOUOutput,
    },
    "cscape_export_project": {
        "input": CscapeExportProjectInput,
        "output": CscapeExportProjectOutput,
    },
    "cscape_read_variables": {
        "input": CscapeReadVariablesInput,
        "output": CscapeReadVariablesOutput,
    },
    "cscape_write_variables": {
        "input": CscapeWriteVariablesInput,
        "output": CscapeWriteVariablesOutput,
    },
    # Phase P3: Native Cscape HMI Tools
    "cscape_hmi_inventory": {
        "input": CscapeHMIInventoryInput,
        "output": CscapeHMIInventoryOutput,
    },
    "cscape_hmi_apply_group": {
        "input": CscapeHMIApplyGroupInput,
        "output": CscapeHMIApplyGroupOutput,
    },
    "cscape_hmi_read_properties": {
        "input": CscapeHMIReadPropertiesInput,
        "output": CscapeHMIReadPropertiesOutput,
    },
    "cscape_hmi_verify_bindings": {
        "input": CscapeHMIVerifyBindingsInput,
        "output": CscapeHMIVerifyBindingsOutput,
    },
    "cscape_hmi_save_close_reopen": {
        "input": CscapeHMISaveCloseReopenInput,
        "output": CscapeHMISaveCloseReopenOutput,
    },
    # Phase P4: Fixture Evolution Tools
    "cscape_fixture_request_to_spec": {
        "input": CscapeFixtureRequestToSpecInput,
        "output": CscapeFixtureRequestToSpecOutput,
    },
    "cscape_fixture_create": {
        "input": CscapeFixtureCreateInput,
        "output": CscapeFixtureCreateOutput,
    },
    "cscape_fixture_selective_edit": {
        "input": CscapeFixtureSelectiveEditInput,
        "output": CscapeFixtureSelectiveEditOutput,
    },
    "cscape_fixture_revision_impact": {
        "input": CscapeFixtureRevisionImpactInput,
        "output": CscapeFixtureRevisionImpactOutput,
    },
    "cscape_fixture_durability_check": {
        "input": CscapeFixtureDurabilityCheckInput,
        "output": CscapeFixtureDurabilityCheckOutput,
    },
    "cscape_fixture_detect_conflict": {
        "input": CscapeFixtureDetectConflictInput,
        "output": CscapeFixtureDetectConflictOutput,
    },
    # Phase P5: Native Modbus PV Provider Tools
    "cscape_modbus_create_config": {
        "input": CscapeModbusCreateConfigInput,
        "output": CscapeModbusCreateConfigOutput,
    },
    "cscape_modbus_persist_config": {
        "input": CscapeModbusPersistConfigInput,
        "output": CscapeModbusPersistConfigOutput,
    },
    "cscape_modbus_read_config": {
        "input": CscapeModbusReadConfigInput,
        "output": CscapeModbusReadConfigOutput,
    },
    "cscape_modbus_protocol_check": {
        "input": CscapeModbusProtocolCheckInput,
        "output": CscapeModbusProtocolCheckOutput,
    },
    "cscape_modbus_conversion_doc": {
        "input": CscapeModbusConversionDocInput,
        "output": CscapeModbusConversionDocOutput,
    },
}


def get_tool_input_schema(tool_name: str) -> Type[CscapeBaseModel]:
    """Retrieve the Pydantic input schema class for the specified MCP tool."""
    if tool_name not in TOOL_SCHEMAS:
        raise KeyError(f"Unknown Cscape tool '{tool_name}'. Available: {list(TOOL_SCHEMAS.keys())}")
    return TOOL_SCHEMAS[tool_name]["input"]


def get_tool_output_schema(tool_name: str) -> Type[CscapeBaseModel]:
    """Retrieve the Pydantic output schema class for the specified MCP tool."""
    if tool_name not in TOOL_SCHEMAS:
        raise KeyError(f"Unknown Cscape tool '{tool_name}'. Available: {list(TOOL_SCHEMAS.keys())}")
    return TOOL_SCHEMAS[tool_name]["output"]


def list_tool_schemas() -> Dict[str, Dict[str, Type[CscapeBaseModel]]]:
    """Return dictionary mapping all tool names to their input and output schema classes."""
    return TOOL_SCHEMAS.copy()


def validate_tool_input(tool_name: str, arguments: Dict[str, Any]) -> CscapeBaseModel:
    """Validate raw tool input arguments dictionary against the tool's input schema."""
    schema_cls = get_tool_input_schema(tool_name)
    return schema_cls.model_validate(arguments)


def validate_tool_output(tool_name: str, data: Dict[str, Any]) -> CscapeBaseModel:
    """Validate raw tool result data dictionary against the tool's output schema."""
    schema_cls = get_tool_output_schema(tool_name)
    return schema_cls.model_validate(data)


__all__ = [
    # Base
    "CscapeBaseModel",
    "CscapeOutputBase",
    # Enums & Supporting
    "POUType",
    "VariableScope",
    "VariableMergeStrategy",
    "BuildLogLevel",
    "VariableDeclaration",
    "MemoryFootprint",
    "POUCompilationStatus",
    "SimulationStepTrace",
    # Constants
    "ALLOWED_CONTROLLER_MODELS",
    "DEPRECATED_CONTROLLER_MODELS",
    "PROHIBITED_DOWNLOAD_TERMS",
    # 1. Launch IDE
    "CscapeLaunchIDEInput",
    "CscapeLaunchIDEOutput",
    "LaunchIDEInput",
    "LaunchIDEOutput",
    # 2. New Project
    "CscapeNewIECProjectInput",
    "CscapeNewIECProjectOutput",
    "NewIECProjectInput",
    "NewIECProjectOutput",
    # 3. Open Project
    "CscapeOpenProjectInput",
    "CscapeOpenProjectOutput",
    "OpenProjectInput",
    "OpenProjectOutput",
    # 4. Insert ST
    "CscapeInsertSTInput",
    "CscapeInsertSTOutput",
    "InsertSTInput",
    "InsertSTOutput",
    # 5. Compile
    "CscapeCompileInput",
    "CscapeCompileOutput",
    "CompileInput",
    "CompileOutput",
    # 6. Build Output
    "CscapeGetBuildOutputInput",
    "CscapeGetBuildOutputOutput",
    "GetBuildOutputInput",
    "GetBuildOutputOutput",
    # 7. Import Variables
    "CscapeImportVariablesInput",
    "CscapeImportVariablesOutput",
    "ImportVariablesInput",
    "ImportVariablesOutput",
    # 8. Export Variables
    "CscapeExportVariablesInput",
    "CscapeExportVariablesOutput",
    "ExportVariablesInput",
    "ExportVariablesOutput",
    # 9. Run Simulation
    "CscapeRunSimulationInput",
    "CscapeRunSimulationOutput",
    "RunSimulationInput",
    "RunSimulationOutput",
    # 10. Simulation Cycle & Register Manipulation
    "CscapeSimulateCycleInput",
    "CscapeSimulateCycleOutput",
    "SimulateCycleInput",
    "SimulateCycleOutput",
    "CscapeReadRegisterInput",
    "CscapeReadRegisterOutput",
    "ReadRegisterInput",
    "ReadRegisterOutput",
    "CscapeWriteRegisterInput",
    "CscapeWriteRegisterOutput",
    "WriteRegisterInput",
    "WriteRegisterOutput",
    # 11. Convenience & Lifecycle Wrappers
    "CscapeCreateProjectInput",
    "CscapeCreateProjectOutput",
    "CscapeAddSTPOUInput",
    "CscapeAddSTPOUOutput",
    "CscapeValidateSTInput",
    "CscapeValidateSTOutput",
    "CscapeInspectVariablesInput",
    "CscapeInspectVariablesOutput",
    "CscapeCompileProjectInput",
    "CscapeCompileProjectOutput",
    "CscapeGetDiagnosticsInput",
    "CscapeGetDiagnosticsOutput",
    "CscapeSimulatePOUInput",
    "CscapeSimulatePOUOutput",
    "CscapeExportProjectInput",
    "CscapeExportProjectOutput",
    "CscapeReadVariablesInput",
    "CscapeReadVariablesOutput",
    "CscapeWriteVariablesInput",
    "CscapeWriteVariablesOutput",
    # Phase P3 HMI
    "CscapeHMIInventoryInput",
    "CscapeHMIInventoryOutput",
    "CscapeHMIApplyGroupInput",
    "CscapeHMIApplyGroupOutput",
    "CscapeHMIReadPropertiesInput",
    "CscapeHMIReadPropertiesOutput",
    "CscapeHMIVerifyBindingsInput",
    "CscapeHMIVerifyBindingsOutput",
    "CscapeHMISaveCloseReopenInput",
    "CscapeHMISaveCloseReopenOutput",
    # Phase P4 Fixture Evolution
    "CscapeFixtureRequestToSpecInput",
    "CscapeFixtureRequestToSpecOutput",
    "CscapeFixtureCreateInput",
    "CscapeFixtureCreateOutput",
    "CscapeFixtureSelectiveEditInput",
    "CscapeFixtureSelectiveEditOutput",
    "CscapeFixtureRevisionImpactInput",
    "CscapeFixtureRevisionImpactOutput",
    "CscapeFixtureDurabilityCheckInput",
    "CscapeFixtureDurabilityCheckOutput",
    "CscapeFixtureDetectConflictInput",
    "CscapeFixtureDetectConflictOutput",
    # Phase P5 Modbus PV Provider
    "CscapeModbusCreateConfigInput",
    "CscapeModbusCreateConfigOutput",
    "CscapeModbusPersistConfigInput",
    "CscapeModbusPersistConfigOutput",
    "CscapeModbusReadConfigInput",
    "CscapeModbusReadConfigOutput",
    "CscapeModbusProtocolCheckInput",
    "CscapeModbusProtocolCheckOutput",
    "CscapeModbusConversionDocInput",
    "CscapeModbusConversionDocOutput",
    # Air-Gapped Offline Packaging
    "CscapePackageOfflineBundleInput",
    "CscapePackageOfflineBundleOutput",
    # Registry & Validation Helpers
    "TOOL_SCHEMAS",
    "get_tool_input_schema",
    "get_tool_output_schema",
    "list_tool_schemas",
    "validate_tool_input",
    "validate_tool_output",
    # Path & OCS Register Validation
    "validate_safe_path",
    "validate_ocs_register",
    "is_valid_ocs_register",
    "OCS_REGISTER_PATTERN",
    "OCS_REGISTER_BOUNDS",
    "OCS_WORD_REGISTERS",
    "OCS_BIT_REGISTERS",
]
