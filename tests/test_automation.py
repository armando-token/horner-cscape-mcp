"""Comprehensive test suite for Windows Automation modules.

Tests process_manager, cli_runner, and com_bridge for:
- Headless execution with window hiding (CREATE_NO_WINDOW)
- Timeouts and graceful termination
- Stderr/stdout capture
- Exit code handling
- Non-blocking async execution
- Safety guardrails (blocking hardware flashing/download utilities)
- Artifact logging
- COM discovery and graceful CLI fallback
"""

import asyncio
import os
import sys
import time
from pathlib import Path
import psutil
import pytest

from src.automation.process_manager import (
    ProcessManager,
    ProcessResult,
    ProcessExecutionError,
    ProcessTimeoutError,
    UnsafeProcessError,
    ExecutableNotFoundError,
    run_process,
    run_process_async,
    is_safe_command,
    kill_process_tree,
    get_windows_startupinfo,
    CREATE_NO_WINDOW,
    STARTF_USESHOWWINDOW,
    SW_HIDE,
    DISALLOWED_EXECUTABLES,
    is_windows,
)
from src.automation.cli_runner import (
    CLIRunner,
    CscapeInstallationInfo,
    resolve_cscape_path,
    get_file_version_info,
)
from src.automation.com_bridge import (
    CscapeAutomationBridge,
    COMStatus,
    check_com_environment,
    scan_registry_progids,
    inspect_progid,
    get_python_bitness,
)


# ============================================================================
# 1. ProcessManager Tests
# ============================================================================

class TestProcessManager:
    """Test suite for process_manager.py."""

    def test_run_success(self):
        """Test synchronous process execution with successful return."""
        cmd = [sys.executable, "-c", "print('PROCESS_TEST_OUTPUT')"]
        result = run_process(cmd)

        assert isinstance(result, ProcessResult)
        assert result.success is True
        assert result.returncode == 0
        assert "PROCESS_TEST_OUTPUT" in result.stdout
        assert result.stderr == ""
        assert result.duration_seconds > 0
        assert result.timed_out is False
        assert result.pid is not None

    def test_run_stderr_capture(self):
        """Test capturing stderr stream accurately."""
        cmd = [sys.executable, "-c", "import sys; sys.stderr.write('CAPTURE_ERROR_STREAM')"]
        result = run_process(cmd)

        assert result.returncode == 0
        assert "CAPTURE_ERROR_STREAM" in result.stderr

    def test_exit_code_check_false(self):
        """Test process exiting with non-zero code when check=False."""
        cmd = [sys.executable, "-c", "import sys; sys.exit(42)"]
        result = run_process(cmd, check=False)

        assert result.success is False
        assert result.returncode == 42
        assert result.timed_out is False

    def test_exit_code_check_true_raises(self):
        """Test process exiting with non-zero code raises ProcessExecutionError when check=True."""
        cmd = [sys.executable, "-c", "import sys; sys.exit(7)"]
        with pytest.raises(ProcessExecutionError) as exc_info:
            run_process(cmd, check=True)

        err = exc_info.value
        assert err.result.returncode == 7
        assert err.result.command == cmd

    def test_timeout_check_false(self):
        """Test process timing out when check=False returns timed_out=True."""
        cmd = [sys.executable, "-c", "import time; time.sleep(5)"]
        result = run_process(cmd, timeout=0.5, check=False)

        assert result.timed_out is True
        assert result.success is False

    def test_timeout_check_true_raises(self):
        """Test process timing out when check=True raises ProcessTimeoutError."""
        cmd = [sys.executable, "-c", "import time; time.sleep(5)"]
        with pytest.raises(ProcessTimeoutError) as exc_info:
            run_process(cmd, timeout=0.5, check=True)

        assert exc_info.value.timeout_seconds == 0.5

    @pytest.mark.asyncio
    async def test_async_run_success(self):
        """Test non-blocking asynchronous execution."""
        cmd = [sys.executable, "-c", "print('ASYNC_SUCCESS')"]
        result = await run_process_async(cmd)

        assert result.success is True
        assert result.returncode == 0
        assert "ASYNC_SUCCESS" in result.stdout

    @pytest.mark.asyncio
    async def test_async_timeout_raises(self):
        """Test non-blocking async execution timeout handling."""
        cmd = [sys.executable, "-c", "import time; time.sleep(5)"]
        with pytest.raises(ProcessTimeoutError):
            await run_process_async(cmd, timeout=0.5, check=True)

    def test_safety_disallowed_executables(self):
        """Strictly test that prohibited flashing/download tools are blocked."""
        for disallowed in DISALLOWED_EXECUTABLES:
            with pytest.raises(UnsafeProcessError) as exc_info:
                run_process([disallowed])
            assert "prohibited by safety directives" in str(exc_info.value).lower()

    def test_safety_disallowed_with_arbitrary_path(self):
        """Test that paths pointing to disallowed executables are also blocked."""
        with pytest.raises(UnsafeProcessError):
            run_process([r"C:\Program Files (x86)\Cscape 10.2\PGMUpdateUtility.exe"])

        with pytest.raises(UnsafeProcessError):
            run_process([r"C:\Tools\DfuSeCommand.exe", "/test"])

    def test_is_safe_command_helper(self):
        """Test is_safe_command boolean helper."""
        assert is_safe_command([sys.executable, "-c", "print(1)"]) is True
        assert is_safe_command(["pgmupdateutility.exe"]) is False
        assert is_safe_command(["STMFlashLoader.exe"]) is False
        assert is_safe_command([]) is False

    def test_executable_not_found_raises(self):
        """Test that an explicitly specified non-existent executable raises ExecutableNotFoundError."""
        with pytest.raises(ExecutableNotFoundError):
            run_process([r"C:\invalid_dir_xyz\nonexistent_tool.exe"])

    def test_empty_command_raises_value_error(self):
        """Test that passing an empty command raises ValueError."""
        with pytest.raises(ValueError):
            run_process([])

    def test_windows_startupinfo_flags(self):
        """Verify Windows flags include CREATE_NO_WINDOW and SW_HIDE."""
        if is_windows():
            creationflags, startupinfo = get_windows_startupinfo(hide_window=True)
            assert creationflags & CREATE_NO_WINDOW == CREATE_NO_WINDOW
            assert startupinfo is not None
            assert startupinfo.dwFlags & STARTF_USESHOWWINDOW == STARTF_USESHOWWINDOW
            assert startupinfo.wShowWindow == SW_HIDE

    def test_kill_process_tree_invalid_pid(self):
        """Verify kill_process_tree gracefully handles non-existent or invalid PID."""
        assert kill_process_tree(-1) is False
        assert kill_process_tree(0) is False
        # PID 999999 likely does not exist
        res = kill_process_tree(999999)
        assert res in (True, False)

    def test_kill_process_tree_terminates_children(self):
        """Verify taskkill /F /T /PID cleanly terminates child processes when parent times out."""
        if not is_windows():
            pytest.skip("Windows taskkill tree termination test")

        parent_code = (
            "import subprocess, sys, time\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            "print(child.pid, flush=True)\n"
            "time.sleep(60)\n"
        )
        res = run_process([sys.executable, "-c", parent_code], timeout=1.5, check=False)
        assert res.timed_out is True
        child_pid_str = res.stdout.strip()
        assert child_pid_str.isdigit()
        child_pid = int(child_pid_str)

        # Allow brief grace period for taskkill tree cleanup to complete
        time.sleep(0.5)
        assert not psutil.pid_exists(child_pid), f"Child process {child_pid} leaked after timeout tree cleanup"

    def test_process_module_reexports(self):
        """Verify src.automation.process re-exports all essential process_manager attributes."""
        import src.automation.process as proc_mod
        assert proc_mod.CREATE_NO_WINDOW == CREATE_NO_WINDOW
        assert proc_mod.STARTF_USESHOWWINDOW == STARTF_USESHOWWINDOW
        assert proc_mod.SW_HIDE == SW_HIDE
        assert proc_mod.ProcessManager is ProcessManager
        assert proc_mod.run_process is run_process
        assert proc_mod.run_process_async is run_process_async
        assert proc_mod.kill_process_tree is kill_process_tree


# ============================================================================
# 2. CLIRunner Tests
# ============================================================================

class TestCLIRunner:
    """Test suite for cli_runner.py."""

    @pytest.fixture
    def runner(self, tmp_path):
        artifacts = tmp_path / "artifacts"
        return CLIRunner(artifacts_dir=artifacts)

    def test_verify_installation_real_environment(self, runner):
        """Verify installation detection on the host machine."""
        info = runner.verify_installation()
        assert isinstance(info, CscapeInstallationInfo)
        assert info.is_installed is True
        assert info.cscape_path is not None
        assert info.cscape_path.exists()
        assert info.version == "10.2.751.4"
        assert info.k5_cmp_dll is not None and info.k5_cmp_dll.exists()
        assert info.k5_xml_dll is not None and info.k5_xml_dll.exists()
        assert info.empty_template_dir is not None and info.empty_template_dir.exists()
        # Ensure prohibited tools in directory are cataloged as blocked
        assert "pgmupdateutility.exe" in [t.lower() for t in info.blocked_dangerous_tools]

    def test_verify_installation_missing(self, tmp_path):
        """Verify diagnostic behavior when Cscape path does not exist."""
        fake_runner = CLIRunner(
            cscape_path=tmp_path / "NonExistentCscape.exe",
            artifacts_dir=tmp_path / "artifacts",
        )
        info = fake_runner.verify_installation()
        assert info.is_installed is False
        assert len(info.errors) > 0
        assert "was not found" in info.errors[0]

    def test_run_toolchain_command_creates_artifact_log(self, runner):
        """Test toolchain command execution creates a structured artifact log."""
        cmd = [sys.executable, "-c", "print('TOOLCHAIN_LOG_TEST')"]
        result = runner.run_toolchain_command(cmd, log_prefix="pytest_toolchain")

        assert result.success is True
        assert "TOOLCHAIN_LOG_TEST" in result.stdout

        # Verify log file was written
        recent_logs = runner.get_recent_logs(5)
        assert len(recent_logs) > 0
        latest_log = recent_logs[0]
        assert latest_log.exists()
        assert latest_log.name.startswith("pytest_toolchain_")

        log_text = latest_log.read_text(encoding="utf-8")
        assert "=== HORNER CSCAPE AUTOMATION EXECUTION LOG ===" in log_text
        assert "TOOLCHAIN_LOG_TEST" in log_text
        assert "Exit Code: 0" in log_text

    @pytest.mark.asyncio
    async def test_run_toolchain_command_async(self, runner):
        """Test asynchronous toolchain command execution and logging."""
        cmd = [sys.executable, "-c", "print('ASYNC_TOOLCHAIN_LOG_TEST')"]
        result = await runner.run_toolchain_command_async(cmd, log_prefix="pytest_async_tc")

        assert result.success is True
        assert "ASYNC_TOOLCHAIN_LOG_TEST" in result.stdout

        recent_logs = runner.get_recent_logs(5)
        matched = [l for l in recent_logs if l.name.startswith("pytest_async_tc_")]
        assert len(matched) > 0

    def test_launch_project_validation_nonexistent(self, runner, tmp_path):
        """Test launch_project raises FileNotFoundError for missing project."""
        missing_proj = tmp_path / "missing.cpj"
        with pytest.raises(FileNotFoundError):
            runner.launch_project(missing_proj)

    def test_launch_project_validation_invalid_ext(self, runner, tmp_path):
        """Test launch_project raises ValueError for invalid extension."""
        invalid_file = tmp_path / "project.txt"
        invalid_file.write_text("dummy", encoding="utf-8")
        with pytest.raises(ValueError) as exc_info:
            runner.launch_project(invalid_file)
        assert "Unsupported project extension" in str(exc_info.value)

    def test_launch_project_purged_k5p_rejected(self, runner, tmp_path):
        """Test that purged legacy .k5p extension is strictly rejected with ValueError."""
        k5p_file = tmp_path / "legacy_appli.k5p"
        k5p_file.write_text("dummy k5p", encoding="utf-8")
        with pytest.raises(ValueError) as exc_info:
            runner.launch_project(k5p_file)
        assert "Unsupported project extension" in str(exc_info.value)

    def test_safety_check_prevents_running_blocked_binary(self, runner):
        """Test that attempting to run a dangerous tool through toolchain command fails."""
        with pytest.raises(UnsafeProcessError):
            runner.run_toolchain_command(["PGMUpdateUtility.exe"])


# ============================================================================
# 3. COMBridge Tests
# ============================================================================

class TestCOMBridge:
    """Test suite for com_bridge.py."""

    def test_get_python_bitness(self):
        """Test bitness detection returns 32 or 64."""
        bitness = get_python_bitness()
        assert bitness in (32, 64)

    def test_check_com_environment(self):
        """Test COM environment check reports status without exception."""
        status = check_com_environment()
        assert isinstance(status, COMStatus)
        if is_windows():
            assert status.pywin32_available is True
            assert isinstance(status.registered_progids, list)
            assert "cpj.Cscape" in status.registered_progids
            assert "csp.Cscape" in status.registered_progids

    def test_scan_registry_progids(self):
        """Test scanning registry for Cscape-related ProgIDs."""
        if is_windows():
            progids = scan_registry_progids(["cscape"])
            assert "cpj.Cscape" in progids
            assert "csp.Cscape" in progids

    def test_inspect_progid(self):
        """Test inspecting a known file association ProgID."""
        if is_windows():
            info = inspect_progid("cpj.Cscape")
            assert info["progid"] == "cpj.Cscape"
            assert info["description"] is not None
            assert info["shell_open_command"] is not None
            assert "Cscape.exe" in info["shell_open_command"]
            assert info["has_clsid"] is False  # File association only, not OLE automation server

    def test_bridge_initialization_and_fallback(self):
        """Test CscapeAutomationBridge initializes in cli_fallback mode when no COM server is registered."""
        with CscapeAutomationBridge() as bridge:
            assert bridge.mode == "cli_fallback"
            assert bridge.is_com_active is False

            diag = bridge.get_diagnostics()
            assert diag["mode"] == "cli_fallback"
            assert "strategy" in diag
            assert "cscape_installation" in diag
            assert diag["cscape_installation"]["is_installed"] is True

    def test_bridge_open_project_validation(self):
        """Test open_project validates project existence."""
        with CscapeAutomationBridge() as bridge:
            with pytest.raises(FileNotFoundError):
                bridge.open_project(r"C:\NonExistentPath\sample.cpj")

    def test_bridge_compile_project_fallback(self, tmp_path):
        """Test compile_project in CLI fallback mode."""
        dummy_proj = tmp_path / "test.cpj"
        dummy_proj.write_text("test content", encoding="utf-8")

        with CscapeAutomationBridge() as bridge:
            res = bridge.compile_project(dummy_proj)
            assert res["status"] == "ready"
            assert res["mode"] == "cli_fallback"
            assert res["toolchain_ready"] is True
            assert res["k5_cmp_dll"] is not None
