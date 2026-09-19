"""Security & Safety subsystem for Horner Cscape MCP Server.

Provides strict safety enforcement:
- Zero physical PLC connections
- Zero controller download or firmware flash operations
- Interception of dangerous utilities (PGMUpdateUtility, DfuSeCommand, STMFlashLoader, WinJTAG)
- Hardware communication port lockouts (COM, LPT, CAN, USB)
- Workspace sandboxing to prevent path traversal or unsafe file access
"""

from .exceptions import (
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
from .guard import (
    SecurityGuard,
    SafetyGuard,
    ALLOWED_TARGETS,
    ALLOWED_TARGET_PLCS,
    DEPRECATED_TARGETS,
    DEPRECATED_TARGET_PLCS,
)
from .policy import SafetyPolicy, SecurityConfig
from .sandbox import PathSandbox

__all__ = [
    "SafetyPolicy",
    "SecurityConfig",
    "PathSandbox",
    "SecurityGuard",
    "SafetyGuard",
    "ALLOWED_TARGETS",
    "ALLOWED_TARGET_PLCS",
    "DEPRECATED_TARGETS",
    "DEPRECATED_TARGET_PLCS",
    "SecurityError",
    "CscapeSafetyViolationError",
    "HardwareLockoutError",
    "UnauthorizedDownloadError",
    "BlockedExecutableError",
    "SandboxViolationError",
    "PathTraversalError",
    "ReadOnlyViolationError",
    "DeviceNameViolationError",
    "DangerousArgumentError",
]
