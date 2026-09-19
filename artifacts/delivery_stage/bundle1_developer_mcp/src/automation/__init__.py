"""Automation package for Horner Cscape & Straton K5 toolchain."""

from .process_manager import (
    ProcessManager,
    ProcessResult,
    ProcessError,
    ProcessExecutionError,
    ProcessTimeoutError,
    UnsafeProcessError,
    ExecutableNotFoundError,
    run_process,
    run_process_async,
    is_safe_command,
    kill_process_tree,
    CREATE_NO_WINDOW,
    DISALLOWED_EXECUTABLES,
)
from .cli_runner import (
    CLIRunner,
    CscapeInstallationInfo,
    resolve_cscape_path,
    get_file_version_info,
)
from .com_bridge import (
    CscapeAutomationBridge,
    COMStatus,
    check_com_environment,
    scan_registry_progids,
    inspect_progid,
)
from .ui_automation import (
    CscapeUIAutomation,
    verify_cscape_hardware_lockout,
    ID_CONTROLLER_DOWNLOAD,
    ID_CONTROLLER_DOWNLOAD_ALT,
    ID_PLC_DOWNLOAD,
    BLOCKED_COMMAND_IDS,
    BLOCKED_MENU_ITEMS,
    BLOCKED_SHORTCUTS,
    BLOCKED_INTERFACES,
)


from .project_manager import ProjectManager
__all__ = [
    "ProjectManager",
    # Process management
    "ProcessManager",
    "ProcessResult",
    "ProcessError",
    "ProcessExecutionError",
    "ProcessTimeoutError",
    "UnsafeProcessError",
    "ExecutableNotFoundError",
    "run_process",
    "run_process_async",
    "is_safe_command",
    "kill_process_tree",
    "CREATE_NO_WINDOW",
    "DISALLOWED_EXECUTABLES",
    # CLI Runner
    "CLIRunner",
    "CscapeInstallationInfo",
    "resolve_cscape_path",
    "get_file_version_info",
    # COM Bridge
    "CscapeAutomationBridge",
    "COMStatus",
    "check_com_environment",
    "scan_registry_progids",
    "inspect_progid",
    # UI Automation & Safety
    "CscapeUIAutomation",
    "verify_cscape_hardware_lockout",
    "ID_CONTROLLER_DOWNLOAD",
    "ID_CONTROLLER_DOWNLOAD_ALT",
    "ID_PLC_DOWNLOAD",
    "BLOCKED_COMMAND_IDS",
    "BLOCKED_MENU_ITEMS",
    "BLOCKED_SHORTCUTS",
    "BLOCKED_INTERFACES",
]
