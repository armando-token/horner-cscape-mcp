"""Workspace file-system sandboxing implementation.

Validates paths to prevent path traversal, unsafe file access, alternate data streams,
reserved DOS device manipulation, and unauthorized modifications outside the workspace.
"""

import os
from pathlib import Path
import re
from typing import Optional, Sequence, Union

from .exceptions import (
    DeviceNameViolationError,
    PathTraversalError,
    ReadOnlyViolationError,
    SandboxViolationError,
)
from .policy import SecurityConfig


# Windows reserved DOS device names (case-insensitive)
RESERVED_DOS_DEVICE_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    "CLOCK$",
})

# System-level protected directories (write operations are unconditionally blocked)
SYSTEM_PROTECTED_DIRECTORIES = (
    Path(r"C:\Windows"),
    Path(r"C:\Program Files"),
    Path(r"C:\Program Files (x86)"),
    Path(r"C:\ProgramData"),
    Path(r"C:\System Volume Information"),
    Path(r"C:\Recovery"),
)


def is_subpath_of(target: Union[str, Path], parent: Union[str, Path]) -> bool:
    """Check whether target is inside parent or is parent itself, normalized for Windows paths."""
    try:
        norm_target = os.path.normcase(os.path.abspath(str(target)))
        norm_parent = os.path.normcase(os.path.abspath(str(parent)))
        if not norm_parent.endswith(os.sep):
            norm_parent_with_sep = norm_parent + os.sep
        else:
            norm_parent_with_sep = norm_parent
        return norm_target == norm_parent or norm_target.startswith(norm_parent_with_sep)
    except Exception:
        return False


class PathSandbox:
    """Enforces strict path sandboxing around the Horner Cscape workspace and authorized roots."""

    def __init__(self, config: Optional[SecurityConfig] = None) -> None:
        self.config = config or SecurityConfig()
        self.workspace_root = self.config.workspace_root

    def validate_path(
        self,
        path: Union[str, Path],
        for_write: bool = False,
        base_dir: Optional[Union[str, Path]] = None,
    ) -> Path:
        """Validate and resolve a path against sandboxing rules.

        Args:
            path: Target path to validate (str or Path).
            for_write: True if operation intends to create, write, modify, or delete the target.
            base_dir: Base directory for relative paths (defaults to workspace_root).

        Returns:
            Resolved, canonical Path object.

        Raises:
            DeviceNameViolationError: If path contains reserved DOS device names.
            SandboxViolationError: If path contains Alternate Data Streams or UNC escapes.
            ReadOnlyViolationError: If attempting to write into read-only roots (e.g. Cscape install).
            PathTraversalError: If path attempts directory traversal outside sandbox roots.
        """
        if path is None:
            raise SandboxViolationError("Cannot validate null path.")

        path_str = str(path).strip()
        if not path_str:
            raise SandboxViolationError("Path cannot be empty.")

        # Check for UNC network paths (e.g. \\server\share) to prevent remote execution/traversal
        if path_str.startswith(("\\\\", "//")):
            raise SandboxViolationError(
                f"UNC network paths are prohibited by workspace sandbox: '{path_str}'"
            )

        # Check for Alternate Data Streams (colon anywhere other than Windows drive letter index 1)
        colon_count = path_str.count(":")
        if colon_count > 1 or (colon_count == 1 and not re.match(r"^[a-zA-Z]:[\\/]", path_str)):
            raise SandboxViolationError(
                f"Alternate Data Stream (ADS) syntax is prohibited: '{path_str}'"
            )

        # Resolve path relative to base_dir or workspace_root
        base = Path(base_dir).resolve() if base_dir else self.workspace_root
        raw_path = Path(path_str)
        if not raw_path.is_absolute():
            resolved = (base / raw_path).resolve()
        else:
            resolved = raw_path.resolve()

        # Check each part of the path against reserved Windows DOS device names
        for part in resolved.parts:
            # Strip drive letter colon
            clean_part = part.rstrip("\\/ ")
            if clean_part.endswith(":"):
                clean_part = clean_part[:-1]
            # Get stem without extensions
            base_name = clean_part.split(".")[0].upper()
            if base_name in RESERVED_DOS_DEVICE_NAMES:
                raise DeviceNameViolationError(
                    f"Access to reserved Windows device name '{part}' is strictly forbidden: '{resolved}'"
                )

        # Check if the target is within protected system directories for write operations
        if for_write:
            for sys_dir in SYSTEM_PROTECTED_DIRECTORIES:
                if is_subpath_of(resolved, sys_dir):
                    raise ReadOnlyViolationError(
                        f"Write access to system directory '{resolved}' is strictly blocked."
                    )

            # Check if writing is inside any configured allowed write root
            is_writable = any(is_subpath_of(resolved, root) for root in self.config.allowed_write_roots)
            if not is_writable:
                # Check if it was in an allowed read root (e.g. Cscape install)
                is_readable = any(is_subpath_of(resolved, root) for root in self.config.allowed_read_roots)
                if is_readable:
                    raise ReadOnlyViolationError(
                        f"Write access denied: '{resolved}' is in a read-only root."
                    )
                raise PathTraversalError(
                    f"Path traversal blocked: target '{resolved}' is outside allowed write roots "
                    f"({[str(r) for r in self.config.allowed_write_roots]})."
                )
        else:
            # Read access validation
            is_readable = any(is_subpath_of(resolved, root) for root in self.config.allowed_read_roots)
            if not is_readable:
                raise PathTraversalError(
                    f"Read access blocked: target '{resolved}' is outside allowed read roots "
                    f"({[str(r) for r in self.config.allowed_read_roots]})."
                )

        return resolved

    def validate_read_path(self, path: Union[str, Path], base_dir: Optional[Union[str, Path]] = None) -> Path:
        """Validate that a path is safe for reading."""
        return self.validate_path(path, for_write=False, base_dir=base_dir)

    def validate_write_path(self, path: Union[str, Path], base_dir: Optional[Union[str, Path]] = None) -> Path:
        """Validate that a path is safe for writing."""
        return self.validate_path(path, for_write=True, base_dir=base_dir)

    def is_safe_path(self, path: Union[str, Path], for_write: bool = False) -> bool:
        """Check if path is safe without raising an exception."""
        try:
            self.validate_path(path, for_write=for_write)
            return True
        except (SandboxViolationError, DeviceNameViolationError, PathTraversalError, ReadOnlyViolationError):
            return False

    def is_safe_read_path(self, path: Union[str, Path]) -> bool:
        """Check if path is safe to read."""
        return self.is_safe_path(path, for_write=False)

    def is_safe_write_path(self, path: Union[str, Path]) -> bool:
        """Check if path is safe to write."""
        return self.is_safe_path(path, for_write=True)

    def ensure_within_workspace(self, path: Union[str, Path]) -> Path:
        """Ensure path is strictly within the workspace root directory."""
        resolved = self.validate_write_path(path)
        if not is_subpath_of(resolved, self.workspace_root):
            raise PathTraversalError(
                f"Path '{resolved}' escapes workspace root '{self.workspace_root}'."
            )
        return resolved

    @staticmethod
    def sanitize_filename(name: str) -> str:
        """Sanitize a filename by removing illegal characters, null bytes, and DOS device names."""
        if not name:
            raise SandboxViolationError("Filename cannot be empty.")

        # Remove path traversal tokens
        clean = name.replace("..", "").replace("/", "").replace("\\", "").strip()

        # Remove characters forbidden on Windows: < > : " / \ | ? * and control chars 0-31
        clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", clean)

        # Strip trailing dots and spaces (problematic on Windows)
        clean = clean.rstrip(". ")

        if not clean:
            clean = "unnamed_file"

        # Check for DOS reserved device names
        stem = clean.split(".")[0].upper()
        if stem in RESERVED_DOS_DEVICE_NAMES:
            clean = f"safe_{clean}"

        return clean
