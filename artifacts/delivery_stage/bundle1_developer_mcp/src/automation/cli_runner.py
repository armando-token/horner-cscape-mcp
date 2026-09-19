"""High-level CLI Runner for Horner Cscape and Straton K5 toolchain.

Manages execution of Cscape.exe and toolchain commands, working directories,
and structured logging into artifacts/logs/.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from .process_manager import (
    ProcessManager,
    ProcessResult,
    ProcessExecutionError,
    ProcessTimeoutError,
    ExecutableNotFoundError,
    UnsafeProcessError,
    DISALLOWED_EXECUTABLES,
    is_windows,
)
from ..security.exceptions import (
    HardwareLockoutError,
    SecurityError,
    UnauthorizedDownloadError,
)
from ..security.guard import SecurityGuard

logger = logging.getLogger(__name__)

# Standard candidate installation paths for Cscape
DEFAULT_CSCAPE_PATHS: list[Path] = [
    Path(r"C:\Program Files (x86)\Cscape 10.2\Cscape.exe"),
    Path(r"C:\Program Files (x86)\Cscape 10.1\Cscape.exe"),
    Path(r"C:\Program Files (x86)\Cscape 10.0\Cscape.exe"),
    Path(r"C:\Program Files\Cscape 10.2\Cscape.exe"),
    Path(r"C:\Program Files\Cscape 10.1\Cscape.exe"),
]

DEFAULT_WORKSPACE_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@dataclass
class CscapeInstallationInfo:
    """Diagnostic details of a detected Cscape and Straton K5 installation."""
    is_installed: bool
    cscape_path: Optional[Path] = None
    install_dir: Optional[Path] = None
    version: Optional[str] = None
    k5_cmp_dll: Optional[Path] = None
    k5_xml_dll: Optional[Path] = None
    k5_zipper_dll: Optional[Path] = None
    k5_is_dll: Optional[Path] = None
    empty_template_dir: Optional[Path] = None
    blocked_dangerous_tools: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert installation diagnostics to dict."""
        return {
            "is_installed": self.is_installed,
            "cscape_path": str(self.cscape_path) if self.cscape_path else None,
            "install_dir": str(self.install_dir) if self.install_dir else None,
            "version": self.version,
            "k5_cmp_dll": str(self.k5_cmp_dll) if self.k5_cmp_dll else None,
            "k5_xml_dll": str(self.k5_xml_dll) if self.k5_xml_dll else None,
            "k5_zipper_dll": str(self.k5_zipper_dll) if self.k5_zipper_dll else None,
            "k5_is_dll": str(self.k5_is_dll) if self.k5_is_dll else None,
            "empty_template_dir": str(self.empty_template_dir) if self.empty_template_dir else None,
            "blocked_dangerous_tools": self.blocked_dangerous_tools,
            "errors": self.errors,
        }


def get_file_version_info(filepath: Union[str, Path]) -> Optional[str]:
    """Retrieve Windows PE file version string using win32api or ctypes."""
    file_str = str(filepath)
    if not is_windows() or not Path(file_str).exists():
        return None

    # Method 1: pywin32 win32api
    try:
        import win32api
        info = win32api.GetFileVersionInfo(file_str, "\\")
        ms = info["FileVersionMS"]
        ls = info["FileVersionLS"]
        return f"{win32api.HIWORD(ms)}.{win32api.LOWORD(ms)}.{win32api.HIWORD(ls)}.{win32api.LOWORD(ls)}"
    except Exception:
        pass

    # Method 2: ctypes fallback
    try:
        import ctypes
        from ctypes import wintypes
        version_dll = ctypes.WinDLL("version.dll")
        dw_len = version_dll.GetFileVersionInfoSizeW(file_str, None)
        if dw_len > 0:
            data = ctypes.create_string_buffer(dw_len)
            if version_dll.GetFileVersionInfoW(file_str, 0, dw_len, data):
                lp_buffer = ctypes.c_void_p()
                u_len = ctypes.c_uint()
                if version_dll.VerQueryValueW(data, "\\", ctypes.byref(lp_buffer), ctypes.byref(u_len)):
                    # VS_FIXEDFILEINFO structure
                    class VS_FIXEDFILEINFO(ctypes.Structure):
                        _fields_ = [
                            ("dwSignature", wintypes.DWORD),
                            ("dwStrucVersion", wintypes.DWORD),
                            ("dwFileVersionMS", wintypes.DWORD),
                            ("dwFileVersionLS", wintypes.DWORD),
                        ]
                    info_ptr = ctypes.cast(lp_buffer, ctypes.POINTER(VS_FIXEDFILEINFO))
                    v_ms = info_ptr.contents.dwFileVersionMS
                    v_ls = info_ptr.contents.dwFileVersionLS
                    return f"{v_ms >> 16}.{v_ms & 0xFFFF}.{v_ls >> 16}.{v_ls & 0xFFFF}"
    except Exception:
        pass

    return None


def resolve_cscape_path(custom_path: Optional[Union[str, Path]] = None) -> Optional[Path]:
    """Resolve the location of Cscape.exe across custom path, env var, registry, and standard paths."""
    # 1. Explicit path parameter
    if custom_path is not None:
        return Path(custom_path).resolve()

    # 2. Environment variable CSCAPE_BIN_PATH
    env_path = os.getenv("CSCAPE_BIN_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists() and p.is_file():
            return p.resolve()

    # 3. Environment variable CSCAPE_DIR
    env_dir = os.getenv("CSCAPE_DIR")
    if env_dir:
        p = Path(env_dir) / "Cscape.exe"
        if p.exists() and p.is_file():
            return p.resolve()

    # 4. Standard default paths
    for candidate in DEFAULT_CSCAPE_PATHS:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()

    # 5. Registry lookup via file association
    if is_windows():
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"cpj.Cscape\shell\open\command") as key:
                cmd_str = winreg.QueryValue(key, "")
                if cmd_str:
                    # e.g. "C:\Program Files (x86)\Cscape 10.2\Cscape.exe" "%1"
                    import shlex
                    parts = shlex.split(cmd_str, posix=False)
                    if parts:
                        p = Path(parts[0].strip('"'))
                        if p.exists() and p.is_file():
                            return p.resolve()
        except Exception:
            pass

    return None


class CLIRunner:
    """High-level runner for Cscape.exe and Straton K5 toolchain operations."""

    def __init__(
        self,
        cscape_path: Optional[Union[str, Path]] = None,
        artifacts_dir: Optional[Union[str, Path]] = None,
        process_manager: Optional[ProcessManager] = None,
    ) -> None:
        self.cscape_path = resolve_cscape_path(cscape_path)
        if artifacts_dir:
            self.artifacts_dir = Path(artifacts_dir)
        else:
            self.artifacts_dir = DEFAULT_WORKSPACE_ROOT / "artifacts"
        self.logs_dir = self.artifacts_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        self.pm = process_manager or ProcessManager()
        self._install_info: Optional[CscapeInstallationInfo] = None

    @property
    def install_dir(self) -> Optional[Path]:
        """Installation folder of Cscape."""
        return self.cscape_path.parent if self.cscape_path else None

    def verify_installation(self, refresh: bool = False) -> CscapeInstallationInfo:
        """Verify the Cscape installation, detect Straton K5 components, and audit safety."""
        if self._install_info and not refresh:
            return self._install_info

        errors: list[str] = []
        blocked_tools: list[str] = []

        if not self.cscape_path or not self.cscape_path.exists():
            errors.append("Cscape executable (Cscape.exe) was not found.")
            info = CscapeInstallationInfo(
                is_installed=False,
                errors=errors,
            )
            self._install_info = info
            return info

        inst_dir = self.cscape_path.parent
        version = get_file_version_info(self.cscape_path)

        # Audit for hazardous binaries in the Cscape directory to ensure safety tracking
        for prohibited in DISALLOWED_EXECUTABLES:
            danger_path = inst_dir / prohibited
            if danger_path.exists():
                blocked_tools.append(prohibited)

        # Verify key Straton K5 engine DLLs
        k5_cmp = inst_dir / "K5Cmp.dll"
        k5_xml = inst_dir / "K5XML.dll"
        k5_zipper = inst_dir / "K5Zipper.dll"
        k5_is = inst_dir / "K5IS.dll"
        template_dir = inst_dir / "TEMPLATE" / "EmptyProject"

        if not k5_cmp.exists():
            errors.append(f"K5 compiler DLL missing: {k5_cmp}")
        if not k5_xml.exists():
            errors.append(f"K5 XML DLL missing: {k5_xml}")
        if not template_dir.exists():
            errors.append(f"Straton template project directory missing: {template_dir}")

        info = CscapeInstallationInfo(
            is_installed=len(errors) == 0,
            cscape_path=self.cscape_path,
            install_dir=inst_dir,
            version=version,
            k5_cmp_dll=k5_cmp if k5_cmp.exists() else None,
            k5_xml_dll=k5_xml if k5_xml.exists() else None,
            k5_zipper_dll=k5_zipper if k5_zipper.exists() else None,
            k5_is_dll=k5_is if k5_is.exists() else None,
            empty_template_dir=template_dir if template_dir.exists() else None,
            blocked_dangerous_tools=blocked_tools,
            errors=errors,
        )
        self._install_info = info
        return info

    def _write_artifact_log(
        self,
        prefix: str,
        command: list[str],
        result: ProcessResult,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Path:
        """Write execution logs into artifacts/logs/."""
        timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        run_id = uuid.uuid4().hex[:8]
        log_file = self.logs_dir / f"{prefix}_{timestamp_str}_{run_id}.log"

        lines = [
            f"=== HORNER CSCAPE AUTOMATION EXECUTION LOG ===",
            f"Timestamp: {datetime.datetime.now().isoformat()}",
            f"Log ID:    {run_id}",
            f"Prefix:    {prefix}",
            f"Command:   {' '.join(command)}",
            f"PID:       {result.pid}",
            f"Exit Code: {result.returncode}",
            f"Duration:  {result.duration_seconds:.4f} seconds",
            f"Timed Out: {result.timed_out}",
            f"Success:   {result.success}",
        ]
        if metadata:
            lines.append("--- Metadata ---")
            for k, v in metadata.items():
                lines.append(f"{k}: {v}")

        lines.extend([
            "--- STDOUT ---",
            result.stdout if result.stdout else "(empty)",
            "--- STDERR ---",
            result.stderr if result.stderr else "(empty)",
            "=== END OF LOG ===",
        ])

        log_file.write_text("\n".join(lines), encoding="utf-8")
        result.metadata["artifact_log"] = str(log_file)
        logger.debug("Artifact log written to: %s", log_file)
        return log_file

    def run_cscape(
        self,
        args: Sequence[Union[str, Path]] = (),
        cwd: Optional[Union[str, Path]] = None,
        timeout: float = 60.0,
        check: bool = False,
        hide_window: bool = True,
        log_prefix: str = "cscape",
    ) -> ProcessResult:
        """Execute Cscape.exe with arguments, writing output to artifacts/logs/.

        Args:
            args: Command line arguments to pass to Cscape.
            cwd: Working directory (defaults to Cscape install directory).
            timeout: Process timeout in seconds.
            check: If True, raises ProcessExecutionError on non-zero return code.
            hide_window: If True, runs headless (CREATE_NO_WINDOW).
            log_prefix: Prefix for artifact log file.

        Returns:
            ProcessResult.
        """
        if not self.cscape_path or not self.cscape_path.exists():
            raise ExecutableNotFoundError(
                f"Cscape.exe not found. Configured path: {self.cscape_path}"
            )

        cmd = [str(self.cscape_path)] + [str(a) for a in args]
        work_dir = cwd or self.install_dir

        # Pre-execution safety validation (blocks download flags and COM/CAN/USB ports)
        SecurityGuard().validate_command(cmd, cwd=work_dir)

        result = self.pm.run(
            command=cmd,
            cwd=work_dir,
            timeout=timeout,
            check=check,
            hide_window=hide_window,
        )

        self._write_artifact_log(prefix=log_prefix, command=cmd, result=result)
        return result

    async def run_cscape_async(
        self,
        args: Sequence[Union[str, Path]] = (),
        cwd: Optional[Union[str, Path]] = None,
        timeout: float = 60.0,
        check: bool = False,
        hide_window: bool = True,
        log_prefix: str = "cscape_async",
    ) -> ProcessResult:
        """Asynchronously execute Cscape.exe without blocking the event loop."""
        if not self.cscape_path or not self.cscape_path.exists():
            raise ExecutableNotFoundError(
                f"Cscape.exe not found. Configured path: {self.cscape_path}"
            )

        cmd = [str(self.cscape_path)] + [str(a) for a in args]
        work_dir = cwd or self.install_dir

        # Pre-execution safety validation (blocks download flags and COM/CAN/USB ports)
        SecurityGuard().validate_command(cmd, cwd=work_dir)

        result = await self.pm.run_async(
            command=cmd,
            cwd=work_dir,
            timeout=timeout,
            check=check,
            hide_window=hide_window,
        )

        self._write_artifact_log(prefix=log_prefix, command=cmd, result=result)
        return result

    def download_to_controller(self, *args: Any, **kwargs: Any) -> None:
        """Unconditionally blocked by safety directive.

        Raises:
            UnauthorizedDownloadError: Always.
        """
        SecurityGuard().validate_download(*args, **kwargs)

    def download_project(self, *args: Any, **kwargs: Any) -> None:
        """Unconditionally blocked by safety directive.

        Raises:
            UnauthorizedDownloadError: Always.
        """
        SecurityGuard().validate_download(*args, **kwargs)

    def launch_project(
        self,
        project_path: Union[str, Path],
        timeout: float = 30.0,
        check: bool = False,
    ) -> ProcessResult:
        """Launch Cscape with a specified project or program file (.cpj, .csp)."""
        proj = Path(project_path).resolve()
        if not proj.exists():
            raise FileNotFoundError(f"Project file not found: {proj}")

        allowed_exts = {".cpj", ".csp"}
        if proj.suffix.lower() not in allowed_exts:
            raise ValueError(
                f"Unsupported project extension '{proj.suffix}'. Expected one of: {allowed_exts}"
            )

        return self.run_cscape(
            args=[str(proj)],
            cwd=proj.parent,
            timeout=timeout,
            check=check,
            log_prefix="cscape_launch_proj",
        )

    def run_toolchain_command(
        self,
        command: Union[str, Sequence[Union[str, Path]]],
        cwd: Optional[Union[str, Path]] = None,
        timeout: float = 60.0,
        check: bool = False,
        hide_window: bool = True,
        log_prefix: str = "toolchain",
    ) -> ProcessResult:
        """Run an arbitrary toolchain binary or utility, with automated logging in artifacts/logs/."""
        work_dir = cwd or self.artifacts_dir
        result = self.pm.run(
            command=command,
            cwd=work_dir,
            timeout=timeout,
            check=check,
            hide_window=hide_window,
        )
        cmd_list = [str(c) for c in (command if isinstance(command, (list, tuple)) else [command])]
        self._write_artifact_log(prefix=log_prefix, command=cmd_list, result=result)
        return result

    async def run_toolchain_command_async(
        self,
        command: Union[str, Sequence[Union[str, Path]]],
        cwd: Optional[Union[str, Path]] = None,
        timeout: float = 60.0,
        check: bool = False,
        hide_window: bool = True,
        log_prefix: str = "toolchain_async",
    ) -> ProcessResult:
        """Asynchronously run a toolchain command."""
        work_dir = cwd or self.artifacts_dir
        result = await self.pm.run_async(
            command=command,
            cwd=work_dir,
            timeout=timeout,
            check=check,
            hide_window=hide_window,
        )
        cmd_list = [str(c) for c in (command if isinstance(command, (list, tuple)) else [command])]
        self._write_artifact_log(prefix=log_prefix, command=cmd_list, result=result)
        return result

    def get_recent_logs(self, limit: int = 10) -> list[Path]:
        """Retrieve recent log files from artifacts/logs/ ordered newest first."""
        if not self.logs_dir.exists():
            return []
        logs = sorted(self.logs_dir.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
        return logs[:limit]
