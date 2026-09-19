"""Comprehensive security test suite for Horner Cscape MCP Server.

Validates:
1. Safety policy invariants and blocklists (executables, ports, flags, protocols).
2. Security configuration and directory boundary rules.
3. Workspace filesystem sandbox: path traversal, ADS, DOS devices, and write protections.
4. Security guard interception for commands, execution, compilation, and export.
5. Mandatory hardware lockouts: Zero physical PLC connections (HardwareLockoutError).
6. Mandatory download lockouts: Zero controller downloads or firmware flash (UnauthorizedDownloadError).
7. Interception of dangerous utilities: PGMUpdateUtility, DfuSeCommand, STMFlashLoader, WinJTAG.
"""

from pathlib import Path
import pytest

from src.security.exceptions import (
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
from src.security.guard import SecurityGuard, SafetyGuard
from src.security.policy import SafetyPolicy, SecurityConfig
from src.security.sandbox import PathSandbox, RESERVED_DOS_DEVICE_NAMES


# ==============================================================================
# 1. Safety Policy Tests
# ==============================================================================

class TestSafetyPolicy:
    """Test SafetyPolicy definitions and immutable invariant enforcement."""

    def test_default_policy_invariants(self) -> None:
        """Verify default policy enforces zero-hardware, zero-download, simulation-only constraints."""
        policy = SafetyPolicy()
        assert policy.simulation_only is True
        assert policy.allow_hardware_communication is False
        assert policy.allow_controller_download is False
        assert policy.allow_firmware_flash is False
        assert policy.enforce_file_sandbox is True

    def test_invariant_violations_raise_security_error(self) -> None:
        """Verify attempting to relax safety constraints raises SecurityError."""
        with pytest.raises(SecurityError, match="simulation_only MUST be True"):
            SafetyPolicy(simulation_only=False)

        with pytest.raises(SecurityError, match="allow_hardware_communication MUST be False"):
            SafetyPolicy(allow_hardware_communication=True)

        with pytest.raises(SecurityError, match="allow_controller_download MUST be False"):
            SafetyPolicy(allow_controller_download=True)

        with pytest.raises(SecurityError, match="allow_firmware_flash MUST be False"):
            SafetyPolicy(allow_firmware_flash=True)

        with pytest.raises(SecurityError, match="enforce_file_sandbox MUST be True"):
            SafetyPolicy(enforce_file_sandbox=False)

    @pytest.mark.parametrize("exe", [
        "PGMUpdateUtility.exe",
        "pgmupdateutility.exe",
        "PGMUPDATEUTILITY.EXE",
        "PGMUpdateUtility",
        "DfuSeCommand.exe",
        "dfusecommand.exe",
        "DFUSECOMMAND",
        "STMFlashLoader.exe",
        "stmflashloader.exe",
        "WinJTAG.exe",
        "winjtag.exe",
        "WINJTAG",
        "CscapeAutoUpdt.exe",
        "XLeTerm.exe",
        "DnCfg.exe",
        "DNXCfg.exe",
        r"C:\Program Files (x86)\Cscape 10.2\PGMUpdateUtility.exe",
        r"C:\Tools\DfuSeCommand.exe",
        r"D:\firmware\STMFlashLoader.exe",
        r"C:\Drivers\WinJTAG.exe",
    ])
    def test_blocked_executables_identified(self, exe: str) -> None:
        """Verify all mandated dangerous executables and variants are flagged."""
        policy = SafetyPolicy()
        assert policy.is_executable_blocked(exe) is True

    @pytest.mark.parametrize("safe_exe", [
        "K5Cmp.exe",
        "K5XML.exe",
        "python.exe",
        "pytest.exe",
        "git.exe",
        "Cscape.exe",
    ])
    def test_safe_executables_not_blocked(self, safe_exe: str) -> None:
        """Verify standard safe development tools are not blocked."""
        policy = SafetyPolicy()
        assert policy.is_executable_blocked(safe_exe) is False

    @pytest.mark.parametrize("port", [
        "COM1",
        "com1",
        "COM256",
        r"\\.\COM1",
        r"\\.\COM4",
        "/dev/ttyS0",
        "/dev/ttyUSB0",
        "/dev/ttyACM0",
        "LPT1",
        "lpt2",
        r"\\.\LPT1",
        "CAN0",
        "can1",
        "pcan_usb",
        "kvaser_leaf",
        "vector_can",
        "socketcan",
        "USB1",
        r"\\?\usb#vid_1234&pid_5678",
        "VID_0483",
        "PID_DF11",
        "JTAG_PORT",
    ])
    def test_blocked_hardware_ports_identified(self, port: str) -> None:
        """Verify hardware communication ports across Windows and Linux conventions are blocked."""
        policy = SafetyPolicy()
        assert policy.is_port_blocked(port) is True

    def test_all_serial_ports_com1_to_com256_blocked(self) -> None:
        """Verify complete COM1..COM256 serial port lockout range across Windows/UNC formats."""
        policy = SafetyPolicy()
        for i in range(1, 257):
            assert policy.is_port_blocked(f"COM{i}") is True
            assert policy.is_port_blocked(f"com{i}") is True
            assert policy.is_port_blocked(rf"\\.\COM{i}") is True

    @pytest.mark.parametrize("fieldbus", [
        "CAN0", "can1", "pcan_usb", "kvaser_leaf", "vector_can", "socketcan", "slcan0",
        "cscan", "canopen", "devicenet", "j1939"
    ])
    def test_fieldbuses_blocked(self, fieldbus: str) -> None:
        """Verify fieldbus adapters and protocols are strictly blocked."""
        policy = SafetyPolicy()
        assert policy.is_port_blocked(fieldbus) or policy.is_interface_blocked(fieldbus) or policy.is_protocol_blocked(fieldbus)

    @pytest.mark.parametrize("debugger", [
        "JTAG", "jtag", "JTAG_PORT", "st-link.exe", "jlink.exe", "openocd.exe", "dfu-util.exe", "WinJTAG.exe"
    ])
    def test_debuggers_blocked(self, debugger: str) -> None:
        """Verify hardware debuggers, flashers, and JTAG interfaces are strictly blocked."""
        policy = SafetyPolicy()
        assert policy.is_port_blocked(debugger) or policy.is_interface_blocked(debugger) or policy.is_executable_blocked(debugger)

    @pytest.mark.parametrize("safe_identifier", [
        "localhost",
        "127.0.0.1",
        "8080",
        "output_file.k5p",
        "stdio",
    ])
    def test_safe_identifiers_not_blocked(self, safe_identifier: str) -> None:
        """Verify non-port identifiers are not falsely blocked."""
        policy = SafetyPolicy()
        assert policy.is_port_blocked(safe_identifier) is False

    @pytest.mark.parametrize("flag", [
        "/d",
        "-d",
        "/download",
        "--download",
        "/flash",
        "-flash",
        "--flash",
        "/pgm",
        "-pgm",
        "--pgm",
        "/burn",
        "-burn",
        "/firmware",
        "--firmware",
        "/target:hardware",
        "/target:plc",
        "--target=hardware",
        "--target=plc",
        "/write-flash",
        "/erase",
        "/upload",
        "/com",
        "/port",
        "/can",
        "/jtag",
    ])
    def test_blocked_command_flags_identified(self, flag: str) -> None:
        """Verify CLI flags triggering controller download or hardware comms are identified."""
        policy = SafetyPolicy()
        assert policy.is_flag_blocked(flag) is True

    @pytest.mark.parametrize("safe_flag", [
        "/c",
        "-c",
        "--compile",
        "/sim",
        "--simulation",
        "-v",
        "--verbose",
        "-o",
        "--output",
        "/help",
        "-h",
    ])
    def test_safe_command_flags_not_blocked(self, safe_flag: str) -> None:
        """Verify legitimate compilation and simulation flags are permitted."""
        policy = SafetyPolicy()
        assert policy.is_flag_blocked(safe_flag) is False


# ==============================================================================
# 2. Security Configuration Tests
# ==============================================================================

class TestSecurityConfig:
    """Test SecurityConfig paths and environment construction."""

    def test_default_config_paths(self) -> None:
        """Verify default configuration establishes workspace root and read/write roots."""
        config = SecurityConfig()
        expected_ws = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
        assert config.workspace_root == expected_ws
        assert expected_ws in config.allowed_write_roots
        assert expected_ws in config.allowed_read_roots

        cscape_path = Path(r"C:\Program Files (x86)\Cscape 10.2").resolve()
        assert cscape_path in config.allowed_read_roots
        # Cscape install directory must NEVER be in allowed write roots
        assert cscape_path not in config.allowed_write_roots

    def test_custom_output_path(self, tmp_path: Path) -> None:
        """Verify adding an authorized output path."""
        config = SecurityConfig()
        config.add_output_path(tmp_path)
        assert tmp_path.resolve() in config.allowed_write_roots


# ==============================================================================
# 3. Workspace Filesystem Sandbox Tests
# ==============================================================================

class TestPathSandbox:
    """Test PathSandbox enforcement against path traversal, ADS, and device names."""

    @pytest.fixture
    def sandbox(self) -> PathSandbox:
        return PathSandbox()

    def test_read_within_workspace_allowed(self, sandbox: PathSandbox) -> None:
        """Reading within workspace is allowed."""
        safe_file = Path(r"C:\HornerAI\horner-cscape-mcp\README.md")
        resolved = sandbox.validate_read_path(safe_file)
        assert resolved == safe_file.resolve()

    def test_read_cscape_templates_allowed(self, sandbox: PathSandbox) -> None:
        """Reading from Cscape installation is allowed for templates and compiler."""
        template_file = Path(r"C:\Program Files (x86)\Cscape 10.2\TEMPLATE\EmptyProject\appli.k5p")
        resolved = sandbox.validate_read_path(template_file)
        assert resolved == template_file.resolve()

    def test_write_within_workspace_allowed(self, sandbox: PathSandbox) -> None:
        """Writing within workspace artifacts or examples is allowed."""
        artifact_path = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\test_project.k5p")
        resolved = sandbox.validate_write_path(artifact_path)
        assert resolved == artifact_path.resolve()

    def test_write_to_cscape_directory_blocked(self, sandbox: PathSandbox) -> None:
        """Writing into Cscape installation directory is blocked as ReadOnlyViolationError."""
        cscape_file = Path(r"C:\Program Files (x86)\Cscape 10.2\test_overwrite.txt")
        with pytest.raises(ReadOnlyViolationError):
            sandbox.validate_write_path(cscape_file)

    def test_write_to_windows_system_dir_blocked(self, sandbox: PathSandbox) -> None:
        """Writing into Windows system directory is blocked as ReadOnlyViolationError."""
        win_file = Path(r"C:\Windows\System32\evil.dll")
        with pytest.raises(ReadOnlyViolationError):
            sandbox.validate_write_path(win_file)

    def test_directory_traversal_blocked(self, sandbox: PathSandbox) -> None:
        """Path traversal sequences (..) escaping the workspace are blocked."""
        traversal_path = r"C:\HornerAI\horner-cscape-mcp\..\..\Windows\evil.txt"
        with pytest.raises((PathTraversalError, ReadOnlyViolationError)):
            sandbox.validate_write_path(traversal_path)

    def test_relative_path_traversal_blocked(self, sandbox: PathSandbox) -> None:
        """Relative path escaping workspace is blocked."""
        with pytest.raises(PathTraversalError):
            sandbox.validate_write_path("../../outside.txt")

    @pytest.mark.parametrize("dev_name", [
        "COM1",
        "COM1.txt",
        "com2",
        "COM3.st",
        "COM9",
        "LPT1",
        "lpt2.dat",
        "CON",
        "PRN",
        "AUX",
        "aux.st",
        "NUL",
        "nul.k5p",
    ])
    def test_reserved_dos_devices_blocked(self, sandbox: PathSandbox, dev_name: str) -> None:
        """Reserved Windows DOS device names are blocked to prevent hardware hangs/comms."""
        target = f"C:\\HornerAI\\horner-cscape-mcp\\artifacts\\{dev_name}"
        with pytest.raises(DeviceNameViolationError):
            sandbox.validate_path(target, for_write=True)

    def test_alternate_data_streams_blocked(self, sandbox: PathSandbox) -> None:
        """Alternate Data Streams (ADS) are blocked to prevent hidden payload writes."""
        ads_path = r"C:\HornerAI\horner-cscape-mcp\artifacts\test.st:stream"
        with pytest.raises(SandboxViolationError, match="Alternate Data Stream"):
            sandbox.validate_path(ads_path, for_write=True)

    def test_unc_network_paths_blocked(self, sandbox: PathSandbox) -> None:
        """UNC paths are blocked to prevent network share traversal and remote execution."""
        unc_path = r"\\malicious-server\share\payload.k5p"
        with pytest.raises(SandboxViolationError, match="UNC network paths are prohibited"):
            sandbox.validate_path(unc_path, for_write=True)

    def test_filename_sanitization(self) -> None:
        """Verify sanitize_filename cleans dangerous characters and device names."""
        assert PathSandbox.sanitize_filename("valid_project.k5p") == "valid_project.k5p"
        assert PathSandbox.sanitize_filename("COM1.txt") == "safe_COM1.txt"
        assert PathSandbox.sanitize_filename("aux.st") == "safe_aux.st"
        assert PathSandbox.sanitize_filename("../../../evil.st") == "evil.st"
        assert PathSandbox.sanitize_filename('bad<file>:name"?.txt') == "bad_file__name__.txt"


# ==============================================================================
# 4. Security Guard Execution & Command Interception Tests
# ==============================================================================

class TestSecurityGuardExecution:
    """Test SecurityGuard command and execution interception."""

    @pytest.fixture
    def guard(self) -> SecurityGuard:
        return SecurityGuard()

    # --------------------------------------------------------------------------
    # Dangerous Executable Interception (Mandate Check)
    # --------------------------------------------------------------------------

    @pytest.mark.parametrize("dangerous_cmd", [
        "PGMUpdateUtility.exe /d",
        "pgmupdateutility.exe",
        r"C:\Program Files (x86)\Cscape 10.2\PGMUpdateUtility.exe",
        "DfuSeCommand.exe -c --de 0",
        "dfusecommand.exe",
        r"C:\Program Files (x86)\Cscape 10.2\DfuSeCommand.exe",
        "STMFlashLoader.exe -c --pn 1",
        "stmflashloader.exe",
        r"C:\Program Files (x86)\Cscape 10.2\STMFlashLoader.exe",
        "WinJTAG.exe",
        "winjtag.exe",
        r"C:\Program Files (x86)\Cscape 10.2\WinJTAG.exe",
        "CscapeAutoUpdt.exe",
        "XLeTerm.exe",
        "cmd.exe /c PGMUpdateUtility.exe",
        "cmd.exe /c DfuSeCommand.exe",
        "powershell.exe -Command STMFlashLoader.exe",
    ])
    def test_dangerous_executables_blocked(self, guard: SecurityGuard, dangerous_cmd: str) -> None:
        """CRITICAL MANDATE: Intercept and block dangerous commands or executables.
        
        Must raise BlockedExecutableError (which inherits from HardwareLockoutError and
        UnauthorizedDownloadError).
        """
        with pytest.raises(BlockedExecutableError) as exc_info:
            guard.validate_command(dangerous_cmd)
        
        # Verify that both HardwareLockoutError and UnauthorizedDownloadError catch this
        assert isinstance(exc_info.value, HardwareLockoutError)
        assert isinstance(exc_info.value, UnauthorizedDownloadError)

    def test_validate_execution_method(self, guard: SecurityGuard) -> None:
        """Verify validate_execution blocks dangerous executables."""
        with pytest.raises(BlockedExecutableError):
            guard.validate_execution("PGMUpdateUtility.exe")

        with pytest.raises(BlockedExecutableError):
            guard.validate_execution("DfuSeCommand.exe")

        with pytest.raises(BlockedExecutableError):
            guard.validate_execution("STMFlashLoader.exe")

        with pytest.raises(BlockedExecutableError):
            guard.validate_execution("WinJTAG.exe")

    # --------------------------------------------------------------------------
    # Hardware Communication Port Blocking (Mandate Check)
    # --------------------------------------------------------------------------

    @pytest.mark.parametrize("cmd_with_port", [
        "Cscape.exe /com:COM1",
        "app.exe --port COM3",
        "app.exe COM10",
        r"app.exe \\.\COM1",
        "app.exe /dev/ttyUSB0",
        "app.exe CAN0",
        "app.exe pcan_usb",
        "app.exe LPT1",
        r"app.exe \\?\usb#vid_0483",
    ])
    def test_hardware_ports_blocked_in_commands(self, guard: SecurityGuard, cmd_with_port: str) -> None:
        """CRITICAL MANDATE: Block hardware communication ports."""
        with pytest.raises(HardwareLockoutError):
            guard.validate_command(cmd_with_port)

    def test_hardware_port_env_vars_blocked(self, guard: SecurityGuard) -> None:
        """Verify environment variable overrides specifying hardware ports are blocked."""
        with pytest.raises(HardwareLockoutError):
            guard.validate_execution("python.exe", env={"CSCAPE_COM_PORT": "COM1"})

        with pytest.raises(HardwareLockoutError):
            guard.validate_execution("python.exe", env={"CAN_PORT": "can0"})

    # --------------------------------------------------------------------------
    # Controller Download & Flash Flags Blocking (Mandate Check)
    # --------------------------------------------------------------------------

    @pytest.mark.parametrize("download_flag", [
        "/d",
        "-d",
        "/download",
        "--download",
        "/flash",
        "-flash",
        "--flash",
        "/pgm",
        "-pgm",
        "/burn",
        "/firmware",
        "/target:hardware",
        "--target=plc",
        "/write-flash",
        "/erase",
        "/upload",
    ])
    def test_download_flags_blocked(self, guard: SecurityGuard, download_flag: str) -> None:
        """CRITICAL MANDATE: Zero controller download or firmware flash operations."""
        cmd = f"Cscape.exe {download_flag}"
        with pytest.raises(UnauthorizedDownloadError):
            guard.validate_command(cmd)

    def test_safe_command_allowed(self, guard: SecurityGuard) -> None:
        """Verify legitimate local compilation commands pass validation."""
        guard.validate_command("python.exe -m pytest tests/")
        guard.validate_command("K5Cmp.exe -c project.k5p")


# ==============================================================================
# 5. Compilation & Export Interception Tests
# ==============================================================================

class TestSecurityGuardCompilationAndExport:
    """Test SecurityGuard compilation and export interception."""

    @pytest.fixture
    def guard(self) -> SecurityGuard:
        return SecurityGuard()

    def test_compilation_simulation_target_allowed(self, guard: SecurityGuard) -> None:
        """Simulation targets are permitted for local offline verification."""
        proj = r"C:\HornerAI\horner-cscape-mcp\fixtures\sample.k5p"
        out = r"C:\HornerAI\horner-cscape-mcp\artifacts"
        guard.validate_compilation(proj, output_dir=out, target="simulation")
        guard.validate_compilation(proj, output_dir=out, target="software")
        guard.validate_compilation(proj, output_dir=out, target="sim")

    @pytest.mark.parametrize("hardware_target", [
        "hardware",
        "plc",
        "controller",
        "device",
        "physical",
        "target_plc",
    ])
    def test_compilation_hardware_target_blocked(self, guard: SecurityGuard, hardware_target: str) -> None:
        """Physical hardware targets during compilation are strictly blocked."""
        proj = r"C:\HornerAI\horner-cscape-mcp\fixtures\sample.k5p"
        with pytest.raises(HardwareLockoutError, match="Physical PLC targets are strictly prohibited"):
            guard.validate_compilation(proj, target=hardware_target)

    def test_compilation_download_flags_blocked(self, guard: SecurityGuard) -> None:
        """Download flags passed to compiler are blocked."""
        proj = r"C:\HornerAI\horner-cscape-mcp\fixtures\sample.k5p"
        with pytest.raises(UnauthorizedDownloadError):
            guard.validate_compilation(proj, target="simulation", flags=["/download"])

        with pytest.raises(UnauthorizedDownloadError):
            guard.validate_compilation(proj, target="simulation", flags=["/flash"])

    def test_compilation_output_traversal_blocked(self, guard: SecurityGuard) -> None:
        """Compilation output directory attempting to write outside workspace is blocked."""
        proj = r"C:\HornerAI\horner-cscape-mcp\fixtures\sample.k5p"
        unsafe_out = r"C:\Windows\System32"
        with pytest.raises(ReadOnlyViolationError):
            guard.validate_compilation(proj, output_dir=unsafe_out, target="simulation")

    def test_export_within_workspace_allowed(self, guard: SecurityGuard) -> None:
        """Exporting files within workspace is permitted."""
        src = r"C:\HornerAI\horner-cscape-mcp\examples\counter.st"
        dst = r"C:\HornerAI\horner-cscape-mcp\artifacts\counter_export.st"
        guard.validate_export(src, dst, format="st")

    def test_export_outside_workspace_blocked(self, guard: SecurityGuard) -> None:
        """Exporting outside workspace is blocked by sandbox."""
        src = r"C:\HornerAI\horner-cscape-mcp\examples\counter.st"
        dst = r"C:\Windows\counter_export.st"
        with pytest.raises(ReadOnlyViolationError):
            guard.validate_export(src, dst)

    @pytest.mark.parametrize("hw_format", ["hardware", "plc", "flash", "dfu", "jtag", "direct_download"])
    def test_export_to_hardware_format_blocked(self, guard: SecurityGuard, hw_format: str) -> None:
        """Exporting to hardware download or flash formats is blocked."""
        src = r"C:\HornerAI\horner-cscape-mcp\examples\counter.st"
        dst = r"C:\HornerAI\horner-cscape-mcp\artifacts\counter.bin"
        with pytest.raises(UnauthorizedDownloadError):
            guard.validate_export(src, dst, format=hw_format)

    def test_export_k5p_quarantine_enforced(self, guard: SecurityGuard) -> None:
        """Legacy k5p export must be quarantined to quarantine/straton_k5_legacy/artifacts/exports/."""
        src = r"C:\HornerAI\horner-cscape-mcp\examples\counter.st"
        # Non-quarantine path raises SecurityError
        bad_dst = r"C:\HornerAI\horner-cscape-mcp\artifacts\legacy.k5p"
        with pytest.raises(SecurityError, match="quarantined"):
            guard.validate_export(src, bad_dst, format="k5p")

        # Quarantined path succeeds
        good_dst = r"C:\HornerAI\horner-cscape-mcp\quarantine\straton_k5_legacy\artifacts\exports\legacy.k5p"
        guard.validate_export(src, good_dst, format="k5p")

    @pytest.mark.parametrize("native_fmt", ["csp", "cpj", "csv", "xml", "st", "json"])
    def test_export_cscape_native_and_tag_formats_allowed(self, guard: SecurityGuard, native_fmt: str) -> None:
        """Authentic Cscape native files (.csp, .cpj) and tag spreadsheets (.csv) are allowed."""
        src = r"C:\HornerAI\horner-cscape-mcp\examples\counter.st"
        dst = rf"C:\HornerAI\horner-cscape-mcp\artifacts\exports\project.{native_fmt}"
        guard.validate_export(src, dst, format=native_fmt)


# ==============================================================================
# 6. Unconditional Lockouts Tests (Zero Hardware, Zero Download Mandate)
# ==============================================================================

class TestUnconditionalLockouts:
    """Test mandatory zero-hardware and zero-download unconditional lockout calls."""

    @pytest.fixture
    def guard(self) -> SecurityGuard:
        return SecurityGuard()

    def test_validate_hardware_connection_always_raises(self, guard: SecurityGuard) -> None:
        """CRITICAL MANDATE: Zero physical PLC connections. Always raises HardwareLockoutError."""
        with pytest.raises(HardwareLockoutError, match="Physical PLC connection rejected"):
            guard.validate_hardware_connection(target="XL4", port="COM1", protocol="csconn")

        with pytest.raises(HardwareLockoutError):
            guard.validate_hardware_connection()

    def test_validate_download_always_raises(self, guard: SecurityGuard) -> None:
        """CRITICAL MANDATE: Zero controller download operations. Always raises UnauthorizedDownloadError."""
        with pytest.raises(UnauthorizedDownloadError, match="Controller download rejected"):
            guard.validate_download(target="XL7", binary_path="appli.k5p")

        with pytest.raises(UnauthorizedDownloadError):
            guard.validate_download()

    def test_validate_firmware_flash_always_raises(self, guard: SecurityGuard) -> None:
        """CRITICAL MANDATE: Zero firmware flash operations. Always raises UnauthorizedDownloadError."""
        with pytest.raises(UnauthorizedDownloadError, match="Firmware flash rejected"):
            guard.validate_firmware_flash(firmware_path="firmware.bin", tool="PGMUpdateUtility")

        with pytest.raises(UnauthorizedDownloadError):
            guard.validate_firmware_flash()

    def test_download_command_ids_32827_and_33149_permanently_blocked(self) -> None:
        """CRITICAL MANDATE: Intercept and block download command IDs 32827 and 33149 fail-closed."""
        policy = SafetyPolicy()
        assert policy.is_ui_command_blocked(32827) is True
        assert policy.is_ui_command_blocked(33149) is True
        assert policy.is_ui_command_blocked("32827") is True
        assert policy.is_ui_command_blocked("33149") is True
        assert policy.is_ui_command_blocked("ID_CONTROLLER_DOWNLOAD") is True
        assert policy.is_ui_command_blocked("ID_PROGRAM_DOWNLOADOPTIONS") is True

        from src.cscape.safety import (
            ID_CONTROLLER_DOWNLOAD,
            ID_CONTROLLER_DOWNLOAD_ALT,
            intercept_download_command,
            CscapeSafetyViolationError,
            CscapeSafetyGuard,
        )
        assert ID_CONTROLLER_DOWNLOAD == 32827
        assert ID_CONTROLLER_DOWNLOAD_ALT == 33149
        for cid in [32827, 33149, "32827", "33149"]:
            with pytest.raises(CscapeSafetyViolationError):
                intercept_download_command(cid)

        cscape_guard = CscapeSafetyGuard()
        for cid in [32827, 33149, "32827", "33149"]:
            with pytest.raises(CscapeSafetyViolationError):
                cscape_guard.validate_cscape_download(cid)


# ==============================================================================
# 7. SafetyGuard Class Methods & Input Validation Tests
# ==============================================================================

class TestSafetyGuardValidationMethods:
    """Test static validation utilities in SecurityGuard/SafetyGuard."""

    def test_validate_project_name_success(self) -> None:
        assert SafetyGuard.validate_project_name("Tank_Control_01") == "Tank_Control_01"
        assert SafetyGuard.validate_project_name("my-project") == "my-project"

    def test_validate_project_name_traversal_fails(self) -> None:
        with pytest.raises(PathTraversalError):
            SafetyGuard.validate_project_name("../evil_project")

    def test_validate_project_name_dos_device_fails(self) -> None:
        with pytest.raises(DeviceNameViolationError):
            SafetyGuard.validate_project_name("COM1")

    def test_validate_pou_name_success(self) -> None:
        assert SafetyGuard.validate_pou_name("Motor_Control") == "Motor_Control"

    def test_validate_pou_name_invalid_identifier(self) -> None:
        with pytest.raises(SecurityError):
            SafetyGuard.validate_pou_name("123Motor")  # cannot start with digit

    def test_validate_target_plc(self) -> None:
        assert SafetyGuard.validate_target_plc("T5SIMUL") == "T5SIMUL"
        assert SafetyGuard.validate_target_plc("XL4") == "XL4"
        with pytest.raises(HardwareLockoutError):
            SafetyGuard.validate_target_plc("PHYSICAL")

    def test_h04_modern_horner_ocs_allowlists(self) -> None:
        """H04: Verify modern Horner OCS hardware series allowlists in schemas and guard."""
        from src.security.guard import ALLOWED_TARGETS, ALLOWED_TARGET_PLCS
        from src.mcp.schemas import ALLOWED_CONTROLLER_MODELS

        required_models = [
            "EXL10", "XL10", "XL+", "Micro OCS", "MICRO OCS", "X2", "X4", "X5", "X7",
            "XL4", "XLE", "XL7", "EXL6", "RCC972", "ZX", "SIMULATION", "SIM", "SOFTWARE",
        ]
        for model in required_models:
            assert any(model.upper() == m.upper() for m in ALLOWED_CONTROLLER_MODELS), f"Model {model} missing from ALLOWED_CONTROLLER_MODELS"
            assert any(model.upper() == m.upper() for m in ALLOWED_TARGETS), f"Model {model} missing from ALLOWED_TARGETS"
            assert any(model.upper() == m.upper() for m in ALLOWED_TARGET_PLCS), f"Model {model} missing from ALLOWED_TARGET_PLCS"
            clean = SafetyGuard.validate_target_plc(model)
            assert clean == model.strip().upper()

    def test_h05_legacy_straton_targets_deprecated_and_quarantined(self) -> None:
        """H05: Verify legacy Straton K5 targets (T5RTI, T5SIMUL) are deprecated and emit DeprecationWarning."""
        from src.security.guard import DEPRECATED_TARGETS, DEPRECATED_TARGET_PLCS
        from src.mcp.schemas import DEPRECATED_CONTROLLER_MODELS
        import warnings

        for model in ("T5RTI", "T5SIMUL"):
            assert model in DEPRECATED_TARGETS
            assert model in DEPRECATED_TARGET_PLCS
            assert model in DEPRECATED_CONTROLLER_MODELS
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                res = SafetyGuard.validate_target_plc(model)
                assert res == model
                assert len(w) == 1
                assert issubclass(w[-1].category, DeprecationWarning)
                assert "deprecated" in str(w[-1].message).lower()

    def test_validate_export_format(self) -> None:
        assert SafetyGuard.validate_export_format("k5p") == "k5p"
        assert SafetyGuard.validate_export_format("st") == "st"
        assert SafetyGuard.validate_export_format("csp") == "csp"
        assert SafetyGuard.validate_export_format("cpj") == "cpj"
        assert SafetyGuard.validate_export_format("csv") == "csv"
        assert SafetyGuard.validate_export_format("xml") == "xml"
        assert SafetyGuard.validate_export_format("json") == "json"
        with pytest.raises(UnauthorizedDownloadError):
            SafetyGuard.validate_export_format("flash")
        with pytest.raises(UnauthorizedDownloadError):
            SafetyGuard.validate_export_format("hardware")
        with pytest.raises(UnauthorizedDownloadError):
            SafetyGuard.validate_export_format("plc")

    def test_assert_compile_only(self) -> None:
        SafetyGuard.assert_compile_only("compile_project")
        with pytest.raises(UnauthorizedDownloadError):
            SafetyGuard.assert_compile_only("download_to_controller")

    def test_get_safety_status(self) -> None:
        status = SafetyGuard.get_safety_status()
        assert status["hardware_lockout_active"] is True
        assert status["physical_plc_allowed"] is False
        assert status["controller_download_allowed"] is False
        assert status["execution_mode"] == "SIMULATION_AND_COMPILE_ONLY"
        assert "PGMUpdateUtility.exe" in status["blocked_executables"]
        assert "DfuSeCommand.exe" in status["blocked_executables"]
        assert "STMFlashLoader.exe" in status["blocked_executables"]
        assert "WinJTAG.exe" in status["blocked_executables"]


# ==============================================================================
# 8. Decorator Tests
# ==============================================================================

class TestSecurityDecorators:
    """Test guard function decorators for compilation, execution, and export."""

    @pytest.fixture
    def guard(self) -> SecurityGuard:
        return SecurityGuard()

    def test_intercept_compilation_decorator(self, guard: SecurityGuard) -> None:
        @guard.intercept_compilation
        def compile_stub(project_path: str, target: str = "simulation", **kwargs) -> str:
            return f"compiled {project_path} for {target}"

        # Safe simulation call succeeds
        res = compile_stub(r"C:\HornerAI\horner-cscape-mcp\fixtures\sample.k5p", target="simulation")
        assert "compiled" in res

        # Unsafe hardware target raises HardwareLockoutError
        with pytest.raises(HardwareLockoutError):
            compile_stub(r"C:\HornerAI\horner-cscape-mcp\fixtures\sample.k5p", target="hardware")

    def test_intercept_execution_decorator(self, guard: SecurityGuard) -> None:
        @guard.intercept_execution
        def exec_stub(cmd: str, **kwargs) -> str:
            return f"executed {cmd}"

        # Safe command succeeds
        res = exec_stub("python.exe --version")
        assert "executed" in res

        # Blocked executable raises BlockedExecutableError
        with pytest.raises(BlockedExecutableError):
            exec_stub("PGMUpdateUtility.exe /d")

    def test_intercept_export_decorator(self, guard: SecurityGuard) -> None:
        @guard.intercept_export
        def export_stub(source_path: str, destination_path: str, format: str = "st", **kwargs) -> str:
            return f"exported to {destination_path}"

        # Safe export succeeds
        res = export_stub(
            r"C:\HornerAI\horner-cscape-mcp\examples\counter.st",
            r"C:\HornerAI\horner-cscape-mcp\artifacts\out.st",
            format="st",
        )
        assert "exported" in res

        # Unsafe export format raises UnauthorizedDownloadError
        with pytest.raises(UnauthorizedDownloadError):
            export_stub(
                r"C:\HornerAI\horner-cscape-mcp\examples\counter.st",
                r"C:\HornerAI\horner-cscape-mcp\artifacts\out.bin",
                format="hardware",
            )


# ==============================================================================
# 9. Offline Gate Simulation Tests (Fail-Closed Liveness Verification)
# ==============================================================================

class TestOfflineGateSimulation:
    """Verify that assert_cscape_live() raises CscapeLivenessGateError when simulated offline."""

    def test_assert_cscape_live_raises_when_gate_not_ready(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When gate indicates ready_for_tests=False, assert_cscape_live strictly raises CscapeLivenessGateError."""
        from src.cscape.gate import assert_cscape_live, CscapeLivenessGateError

        monkeypatch.setattr(
            "src.cscape.gate.get_gate_status",
            lambda: {"ready_for_tests": False, "status": "OFFLINE", "reason": "Simulated offline condition"},
        )
        with pytest.raises(CscapeLivenessGateError, match="FAIL-CLOSED: Operations halted"):
            assert_cscape_live()

    def test_assert_cscape_live_raises_when_gate_file_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When gate file does not exist, assert_cscape_live strictly raises CscapeLivenessGateError."""
        from src.cscape.gate import assert_cscape_live, CscapeLivenessGateError

        monkeypatch.setattr(
            "src.cscape.gate.get_gate_status",
            lambda: {
                "ready_for_tests": False,
                "status": "GATE_FILE_NOT_FOUND",
                "reason": "No active Cscape keepalive gate file detected on disk",
            },
        )
        with pytest.raises(CscapeLivenessGateError, match="GATE_FILE_NOT_FOUND"):
            assert_cscape_live()

    def test_assert_cscape_live_raises_when_process_dead(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When gate indicates ready_for_tests=True but process PID is terminated, raises CscapeLivenessGateError."""
        from src.cscape.gate import assert_cscape_live, CscapeLivenessGateError

        monkeypatch.setattr(
            "src.cscape.gate.get_gate_status",
            lambda: {"ready_for_tests": True, "pid": 99999999, "hwnd": None},
        )
        with pytest.raises(CscapeLivenessGateError, match="has terminated"):
            assert_cscape_live()

    def test_assert_cscape_live_raises_when_title_mismatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When gate reports active window with incorrect title, raises CscapeLivenessGateError."""
        from src.cscape.gate import assert_cscape_live, CscapeLivenessGateError
        import win32gui

        monkeypatch.setattr(
            "src.cscape.gate.get_gate_status",
            lambda: {"ready_for_tests": True, "pid": None, "hwnd": 12345},
        )
        monkeypatch.setattr("src.cscape.gate.attach_thread_desktop", lambda hwnd: None)
        monkeypatch.setattr(win32gui, "IsWindow", lambda hwnd: True)
        monkeypatch.setattr(win32gui, "GetWindowText", lambda hwnd: "Cscape - SomeOtherProject")

        with pytest.raises(CscapeLivenessGateError, match="does not have TankLevelClosedLoop active"):
            assert_cscape_live()

