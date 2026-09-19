"""Security exception hierarchy for Horner Cscape MCP Server.

Enforces zero-trust safety constraints:
- Zero physical PLC connections.
- Zero controller download or firmware flash operations.
- Intercept and block dangerous commands or executables.
- Block hardware communication ports (COM, LPT, CAN, USB).
- Strict workspace file-system sandboxing.
"""

from typing import Optional


class SecurityError(Exception):
    """Base exception for all security and safety policy violations."""

    def __init__(self, message: str, details: Optional[dict] = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = "blocked"
        self.details = details or {}
        if "status" not in self.details:
            self.details["status"] = "blocked"


class CscapeSafetyViolationError(SecurityError):
    """Raised when an operation violates Cscape physical safety or download lockout policies."""
    pass


class HardwareLockoutError(CscapeSafetyViolationError):
    """Raised when an operation attempts physical PLC hardware communication or port access."""
    pass


class UnauthorizedDownloadError(CscapeSafetyViolationError):
    """Raised when an operation attempts controller download, firmware flash, or binary transfer."""
    pass


class BlockedExecutableError(HardwareLockoutError, UnauthorizedDownloadError):
    """Raised when an intercepted command targets a prohibited executable.
    
    Inherits from both HardwareLockoutError and UnauthorizedDownloadError so callers
    handling either lockouts or download violations catch this exception cleanly.
    """
    pass


class SandboxViolationError(SecurityError):
    """Raised when a file operation violates the workspace filesystem sandbox."""
    pass


class PathTraversalError(SandboxViolationError):
    """Raised when a path attempts directory traversal or escapes allowed roots."""
    pass


class ReadOnlyViolationError(SandboxViolationError):
    """Raised when a write operation is attempted in a read-only area."""
    pass


class DeviceNameViolationError(SandboxViolationError):
    """Raised when a path references a reserved Windows DOS device name (e.g. CON, NUL, COM1)."""
    pass


class DangerousArgumentError(UnauthorizedDownloadError):
    """Raised when command-line arguments contain forbidden flags or dangerous options."""
    pass
