"""Alias and re-export module for src.automation.process_manager.

Provides backwards-compatible and convenient imports for process management,
including ProcessManager, process execution functions, Windows headless flags
(CREATE_NO_WINDOW, SW_HIDE), and process tree termination helpers.
"""

from .process_manager import (
    CREATE_NO_WINDOW,
    STARTF_USESHOWWINDOW,
    SW_HIDE,
    DISALLOWED_EXECUTABLES,
    ProcessError,
    ExecutableNotFoundError,
    UnsafeProcessError,
    ProcessResult,
    ProcessExecutionError,
    ProcessTimeoutError,
    is_windows,
    normalize_command,
    validate_command_safety,
    is_safe_command,
    get_windows_startupinfo,
    kill_process_tree,
    decode_output,
    ProcessManager,
    run_process,
    run_process_async,
)

__all__ = [
    "CREATE_NO_WINDOW",
    "STARTF_USESHOWWINDOW",
    "SW_HIDE",
    "DISALLOWED_EXECUTABLES",
    "ProcessError",
    "ExecutableNotFoundError",
    "UnsafeProcessError",
    "ProcessResult",
    "ProcessExecutionError",
    "ProcessTimeoutError",
    "is_windows",
    "normalize_command",
    "validate_command_safety",
    "is_safe_command",
    "get_windows_startupinfo",
    "kill_process_tree",
    "decode_output",
    "ProcessManager",
    "run_process",
    "run_process_async",
]
