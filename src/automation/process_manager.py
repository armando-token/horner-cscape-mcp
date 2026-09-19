"""Robust Windows process management and headless execution.

Provides headless, safe process execution with timeouts, exit code checking,
output capture, graceful process-tree termination, and Windows window-hiding
(CREATE_NO_WINDOW + STARTF_USESHOWWINDOW).
Strictly enforces safety directives preventing hardware downloads or flashing.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple, Union
import logging

logger = logging.getLogger(__name__)

# Windows Process Creation Flags
CREATE_NO_WINDOW: int = 0x08000000
STARTF_USESHOWWINDOW: int = 0x00000001
SW_HIDE: int = 0

# Prohibited dangerous binaries that flash or communicate with physical PLC hardware
# Enforces the safety directive: NO CONTROLLER DOWNLOAD / NO HARDWARE FLASHING
DISALLOWED_EXECUTABLES: frozenset[str] = frozenset({
    "pgmupdateutility.exe",
    "dfusecommand.exe",
    "stmflashloader.exe",
    "winjtag.exe",
})


class ProcessError(Exception):
    """Base exception for process manager errors."""
    pass


class ExecutableNotFoundError(ProcessError):
    """Raised when the specified executable cannot be found on the filesystem."""
    pass


class UnsafeProcessError(ProcessError):
    """Raised when an operation attempts to execute a disallowed/dangerous binary."""
    pass


@dataclass
class ProcessResult:
    """Represents the execution outcome of an executed process."""
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    pid: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """True if process completed with returncode 0 and did not time out."""
        return self.returncode == 0 and not self.timed_out

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary representation."""
        return {
            "command": self.command,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": round(self.duration_seconds, 4),
            "timed_out": self.timed_out,
            "pid": self.pid,
            "success": self.success,
            "metadata": self.metadata,
        }


class ProcessExecutionError(ProcessError):
    """Raised when a process exits with a non-zero status and check=True."""

    def __init__(self, message: str, result: ProcessResult) -> None:
        super().__init__(message)
        self.result = result


class ProcessTimeoutError(ProcessError):
    """Raised when a process execution exceeds the configured timeout."""

    def __init__(
        self,
        command: list[str],
        timeout_seconds: float,
        partial_stdout: str = "",
        partial_stderr: str = "",
        pid: Optional[int] = None,
    ) -> None:
        cmd_str = " ".join(command)
        super().__init__(
            f"Command '{cmd_str}' timed out after {timeout_seconds:.2f}s (pid={pid})"
        )
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.partial_stdout = partial_stdout
        self.partial_stderr = partial_stderr
        self.pid = pid


def is_windows() -> bool:
    """Return True if running on a Windows OS platform."""
    return sys.platform == "win32" or os.name == "nt"


def normalize_command(command: Union[str, Sequence[Union[str, Path]]]) -> list[str]:
    """Normalize a command into a list of strings."""
    if isinstance(command, str):
        if is_windows():
            # shlex.split with posix=False handles Windows paths with backslashes
            return shlex.split(command, posix=False)
        return shlex.split(command)
    return [str(arg) for arg in command]


def validate_command_safety(command: Union[str, Sequence[Union[str, Path]]]) -> list[str]:
    """Validate that the command does not invoke any prohibited hardware/flashing tool.

    Returns the normalized command argument list if safe.
    Raises:
        UnsafeProcessError: If the command invokes a prohibited binary.
        ValueError: If command list is empty.
    """
    cmd_list = normalize_command(command)
    if not cmd_list:
        raise ValueError("Cannot execute an empty command.")

    raw_exe = cmd_list[0]
    exe_name = Path(raw_exe).name.lower()
    if not exe_name.endswith(".exe") and is_windows():
        exe_with_ext = f"{exe_name}.exe"
    else:
        exe_with_ext = exe_name

    if exe_name in DISALLOWED_EXECUTABLES or exe_with_ext in DISALLOWED_EXECUTABLES:
        logger.critical(
            "SAFETY VIOLATION: Disallowed binary attempted for execution: %s", raw_exe
        )
        raise UnsafeProcessError(
            f"Execution of '{raw_exe}' is strictly prohibited by safety directives "
            f"(hardware flashing / controller download tool blocked)."
        )

    return cmd_list


def is_safe_command(command: Union[str, Sequence[Union[str, Path]]]) -> bool:
    """Helper function to check if a command passes safety validation."""
    try:
        validate_command_safety(command)
        return True
    except (UnsafeProcessError, ValueError):
        return False


def get_windows_startupinfo(hide_window: bool = True) -> Tuple[int, Optional[subprocess.STARTUPINFO]]:
    """Build Windows process creation flags and STARTUPINFO for headless execution.

    Args:
        hide_window: Whether to hide GUI windows and console windows.

    Returns:
        Tuple of (creationflags, startupinfo).
    """
    if not is_windows():
        return 0, None

    creationflags = 0
    startupinfo: Optional[subprocess.STARTUPINFO] = None

    if hide_window:
        creationflags |= CREATE_NO_WINDOW
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = SW_HIDE

    return creationflags, startupinfo


def kill_process_tree(pid: int, timeout_sec: float = 3.0) -> bool:
    """Terminate a process and all of its child processes on Windows.

    Uses taskkill.exe /F /T /PID on Windows for clean tree termination.
    Falls back to os.kill or Process.kill if taskkill is unavailable.

    Args:
        pid: The process ID to terminate.
        timeout_sec: Timeout for taskkill execution.

    Returns:
        True if successfully terminated or process does not exist, False otherwise.
    """
    if pid <= 0:
        return False

    if is_windows():
        try:
            taskkill_cmd = ["taskkill.exe", "/F", "/T", "/PID", str(pid)]
            creationflags, startupinfo = get_windows_startupinfo(hide_window=True)
            res = subprocess.run(
                taskkill_cmd,
                capture_output=True,
                creationflags=creationflags,
                startupinfo=startupinfo,
                timeout=timeout_sec,
            )
            if res.returncode == 0 or b"not found" in res.stderr.lower() or b"no running" in res.stderr.lower():
                logger.debug("Successfully terminated process tree for PID %d", pid)
                return True
            logger.warning("taskkill returned code %d: %s", res.returncode, res.stderr.decode(errors="replace"))
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            logger.warning("Failed to invoke taskkill for PID %d: %s", pid, e)

    # Fallback to direct termination
    try:
        if hasattr(os, "kill"):
            import signal
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.1)
            os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        # Process already exited
        return True


def decode_output(raw_bytes: Optional[bytes], encoding: str = "utf-8") -> str:
    """Safely decode process output with resilient fallback encodings."""
    if not raw_bytes:
        return ""
    try:
        return raw_bytes.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        # Fallback to Windows-1252 or replace errors
        try:
            return raw_bytes.decode("cp1252", errors="replace")
        except Exception:
            return raw_bytes.decode("latin-1", errors="replace")


class ProcessManager:
    """Headless, secure process runner for Windows automation."""

    def __init__(
        self,
        default_timeout: Optional[float] = 60.0,
        default_hide_window: bool = True,
        default_encoding: str = "utf-8",
    ) -> None:
        self.default_timeout = default_timeout
        self.default_hide_window = default_hide_window
        self.default_encoding = default_encoding

    def run(
        self,
        command: Union[str, Sequence[Union[str, Path]]],
        cwd: Optional[Union[str, Path]] = None,
        env: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
        check: bool = True,
        hide_window: Optional[bool] = None,
        input_data: Optional[Union[str, bytes]] = None,
        encoding: Optional[str] = None,
        extra_creationflags: int = 0,
    ) -> ProcessResult:
        """Run a process synchronously with strict timeouts and output capture.

        Args:
            command: Command and arguments as list or string.
            cwd: Working directory for process execution.
            env: Environment variables dict (inherits os.environ if None).
            timeout: Timeout in seconds (defaults to self.default_timeout).
            check: If True, raises ProcessExecutionError on non-zero returncode.
            hide_window: If True, hides console/GUI windows (CREATE_NO_WINDOW).
            input_data: Optional stdin string or bytes.
            encoding: Text decoding charset (defaults to self.default_encoding).
            extra_creationflags: Extra Windows creation flags if needed.

        Returns:
            ProcessResult containing stdout, stderr, returncode, and timing.

        Raises:
            UnsafeProcessError: If target binary is in disallowed list.
            ExecutableNotFoundError: If binary path does not exist.
            ProcessTimeoutError: If timeout exceeded and check=True.
            ProcessExecutionError: If returncode != 0 and check=True.
        """
        cmd_list = validate_command_safety(command)
        timeout_val = timeout if timeout is not None else self.default_timeout
        hide_win = hide_window if hide_window is not None else self.default_hide_window
        enc = encoding or self.default_encoding

        # Validate executable existence if given as an explicit path
        target_exe = cmd_list[0]
        if ("\\" in target_exe or "/" in target_exe) and not Path(target_exe).exists():
            raise ExecutableNotFoundError(f"Executable not found: '{target_exe}'")

        creationflags, startupinfo = get_windows_startupinfo(hide_window=hide_win)
        creationflags |= extra_creationflags

        if cwd is not None:
            cwd_path = Path(cwd)
            if not cwd_path.exists():
                raise FileNotFoundError(f"Working directory does not exist: {cwd}")
            cwd_str = str(cwd_path)
        else:
            cwd_str = None

        stdin_bytes = None
        if input_data is not None:
            if isinstance(input_data, str):
                stdin_bytes = input_data.encode(enc)
            else:
                stdin_bytes = input_data

        logger.debug("Executing process: %s (cwd=%s, timeout=%s)", cmd_list, cwd_str, timeout_val)
        start_time = time.perf_counter()

        proc: Optional[subprocess.Popen[bytes]] = None
        stdout_raw: bytes = b""
        stderr_raw: bytes = b""
        timed_out = False
        pid: Optional[int] = None

        try:
            proc = subprocess.Popen(
                cmd_list,
                cwd=cwd_str,
                env=env,
                stdin=subprocess.PIPE if stdin_bytes is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
                startupinfo=startupinfo,
            )
            pid = proc.pid

            try:
                stdout_raw, stderr_raw = proc.communicate(input=stdin_bytes, timeout=timeout_val)
            except subprocess.TimeoutExpired:
                timed_out = True
                logger.warning("Process %s (PID %s) timed out after %ss. Terminating process tree.", cmd_list, pid, timeout_val)
                if pid:
                    kill_process_tree(pid)
                # Try to get any remaining output
                try:
                    stdout_raw, stderr_raw = proc.communicate(timeout=2.0)
                except Exception:
                    pass

        except FileNotFoundError as e:
            raise ExecutableNotFoundError(f"Executable not found on system: {cmd_list[0]}") from e

        duration = time.perf_counter() - start_time
        returncode = proc.returncode if proc and proc.returncode is not None else (-1 if timed_out else -1)

        stdout_str = decode_output(stdout_raw, encoding=enc)
        stderr_str = decode_output(stderr_raw, encoding=enc)

        result = ProcessResult(
            command=cmd_list,
            returncode=returncode,
            stdout=stdout_str,
            stderr=stderr_str,
            duration_seconds=duration,
            timed_out=timed_out,
            pid=pid,
        )

        if timed_out and check:
            raise ProcessTimeoutError(
                command=cmd_list,
                timeout_seconds=timeout_val or 0.0,
                partial_stdout=stdout_str,
                partial_stderr=stderr_str,
                pid=pid,
            )

        if check and result.returncode != 0:
            raise ProcessExecutionError(
                f"Process returned non-zero exit code {result.returncode}: {cmd_list[0]}",
                result=result,
            )

        return result

    async def run_async(
        self,
        command: Union[str, Sequence[Union[str, Path]]],
        cwd: Optional[Union[str, Path]] = None,
        env: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
        check: bool = True,
        hide_window: Optional[bool] = None,
        input_data: Optional[Union[str, bytes]] = None,
        encoding: Optional[str] = None,
        extra_creationflags: int = 0,
    ) -> ProcessResult:
        """Run a process asynchronously without blocking the event loop."""
        cmd_list = validate_command_safety(command)
        timeout_val = timeout if timeout is not None else self.default_timeout
        hide_win = hide_window if hide_window is not None else self.default_hide_window
        enc = encoding or self.default_encoding

        target_exe = cmd_list[0]
        if ("\\" in target_exe or "/" in target_exe) and not Path(target_exe).exists():
            raise ExecutableNotFoundError(f"Executable not found: '{target_exe}'")

        creationflags, startupinfo = get_windows_startupinfo(hide_window=hide_win)
        creationflags |= extra_creationflags

        if cwd is not None:
            cwd_path = Path(cwd)
            if not cwd_path.exists():
                raise FileNotFoundError(f"Working directory does not exist: {cwd}")
            cwd_str = str(cwd_path)
        else:
            cwd_str = None

        stdin_bytes = None
        if input_data is not None:
            if isinstance(input_data, str):
                stdin_bytes = input_data.encode(enc)
            else:
                stdin_bytes = input_data

        logger.debug("Executing process async: %s (cwd=%s, timeout=%s)", cmd_list, cwd_str, timeout_val)
        start_time = time.perf_counter()

        kwargs: dict[str, Any] = {
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "cwd": cwd_str,
            "env": env,
        }
        if stdin_bytes is not None:
            kwargs["stdin"] = asyncio.subprocess.PIPE
        if is_windows():
            kwargs["creationflags"] = creationflags
            if startupinfo is not None:
                kwargs["startupinfo"] = startupinfo

        timed_out = False
        pid: Optional[int] = None
        stdout_raw: bytes = b""
        stderr_raw: bytes = b""

        try:
            proc = await asyncio.create_subprocess_exec(
                cmd_list[0],
                *cmd_list[1:],
                **kwargs,
            )
            pid = proc.pid

            try:
                if timeout_val is not None and timeout_val > 0:
                    stdout_raw, stderr_raw = await asyncio.wait_for(
                        proc.communicate(input=stdin_bytes),
                        timeout=timeout_val,
                    )
                else:
                    stdout_raw, stderr_raw = await proc.communicate(input=stdin_bytes)
            except asyncio.TimeoutError:
                timed_out = True
                logger.warning("Async process %s (PID %s) timed out after %ss.", cmd_list, pid, timeout_val)
                if pid:
                    kill_process_tree(pid)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except Exception:
                    pass

        except FileNotFoundError as e:
            raise ExecutableNotFoundError(f"Executable not found on system: {cmd_list[0]}") from e

        duration = time.perf_counter() - start_time
        returncode = proc.returncode if proc and proc.returncode is not None else (-1 if timed_out else -1)

        stdout_str = decode_output(stdout_raw, encoding=enc)
        stderr_str = decode_output(stderr_raw, encoding=enc)

        result = ProcessResult(
            command=cmd_list,
            returncode=returncode,
            stdout=stdout_str,
            stderr=stderr_str,
            duration_seconds=duration,
            timed_out=timed_out,
            pid=pid,
        )

        if timed_out and check:
            raise ProcessTimeoutError(
                command=cmd_list,
                timeout_seconds=timeout_val or 0.0,
                partial_stdout=stdout_str,
                partial_stderr=stderr_str,
                pid=pid,
            )

        if check and result.returncode != 0:
            raise ProcessExecutionError(
                f"Process returned non-zero exit code {result.returncode}: {cmd_list[0]}",
                result=result,
            )

        return result


# Module-level default process manager instance
_default_manager = ProcessManager()


def run_process(
    command: Union[str, Sequence[Union[str, Path]]],
    cwd: Optional[Union[str, Path]] = None,
    env: Optional[dict[str, str]] = None,
    timeout: Optional[float] = 60.0,
    check: bool = True,
    hide_window: bool = True,
    input_data: Optional[Union[str, bytes]] = None,
    encoding: str = "utf-8",
) -> ProcessResult:
    """Convenience function to run a process with default manager."""
    return _default_manager.run(
        command=command,
        cwd=cwd,
        env=env,
        timeout=timeout,
        check=check,
        hide_window=hide_window,
        input_data=input_data,
        encoding=encoding,
    )


async def run_process_async(
    command: Union[str, Sequence[Union[str, Path]]],
    cwd: Optional[Union[str, Path]] = None,
    env: Optional[dict[str, str]] = None,
    timeout: Optional[float] = 60.0,
    check: bool = True,
    hide_window: bool = True,
    input_data: Optional[Union[str, bytes]] = None,
    encoding: str = "utf-8",
) -> ProcessResult:
    """Convenience function to run a process asynchronously with default manager."""
    return await _default_manager.run_async(
        command=command,
        cwd=cwd,
        env=env,
        timeout=timeout,
        check=check,
        hide_window=hide_window,
        input_data=input_data,
        encoding=encoding,
    )
