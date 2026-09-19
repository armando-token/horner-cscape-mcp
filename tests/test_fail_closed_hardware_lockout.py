"""Headless verification test for fail-closed hardware ban and download lockout.

Mandate:
1. Physical communication ports (COM1..COM256, CAN, USB) strictly raise HardwareLockoutError
   or CscapeSafetyViolationError with status: blocked.
2. Companion flashing utilities (PGMUpdateUtility.exe, DfuSeCommand.exe, STMFlashLoader.exe, WinJTAG.exe)
   strictly raise HardwareLockoutError or CscapeSafetyViolationError with status: blocked.
3. Win32 download command IDs (ID_PROGRAM_DOWNLOAD = 32827, ID_CONTROLLER_DOWNLOAD = 33149)
   strictly raise HardwareLockoutError or CscapeSafetyViolationError with status: blocked.
4. Compilation and MCP tool invocations with download command IDs strictly return status: blocked.
"""

from pathlib import Path
import pytest
from typing import Any, Dict

from src.cscape.safety import (
    ID_CONTROLLER_DOWNLOAD,
    ID_CONTROLLER_DOWNLOAD_ALT,
    ID_PROGRAM_DOWNLOAD,
    ID_PROGRAM_DOWNLOADOPTIONS,
    BLOCKED_DOWNLOAD_COMMAND_IDS,
    BLOCKED_FLASHING_EXECUTABLES,
    BLOCKED_HARDWARE_COMMAND_IDS,
    CscapeSafetyGuard,
    CscapeSafetyViolationError,
    HardwareLockoutError,
    UnauthorizedDownloadError,
    BlockedExecutableError,
    intercept_download_command,
    intercept_hardware_interface,
    intercept_executable,
)
from src.security.guard import SecurityGuard, SafetyGuard
from src.security.policy import SafetyPolicy
from src.cscape.compilation import cscape_compile_project


class TestFailClosedHardwareBanAndDownloadLockout:
    """Rigorous headless verification of fail-closed hardware ban and download lockout."""

    @pytest.fixture
    def guard(self) -> SecurityGuard:
        return SecurityGuard()

    @pytest.fixture
    def cscape_guard(self) -> CscapeSafetyGuard:
        return CscapeSafetyGuard()

    # --------------------------------------------------------------------------
    # 1. Physical Communication Ports (COM1..COM256, CAN, USB)
    # --------------------------------------------------------------------------

    def test_all_serial_ports_com1_to_com256_blocked(self, guard: SecurityGuard) -> None:
        """Verify all serial ports COM1..COM256 raise HardwareLockoutError with status: blocked."""
        for port_num in range(1, 257):
            port = f"COM{port_num}"
            # 1. Guard validate_command
            with pytest.raises((HardwareLockoutError, CscapeSafetyViolationError)) as exc_info:
                guard.validate_command(f"tool.exe {port}")
            err = exc_info.value
            assert getattr(err, "status", None) == "blocked"
            assert isinstance(err, (HardwareLockoutError, CscapeSafetyViolationError))

            # 2. Guard validate_interface
            with pytest.raises((HardwareLockoutError, CscapeSafetyViolationError)) as exc_info:
                guard.validate_interface(port)
            err = exc_info.value
            assert getattr(err, "status", None) == "blocked"

            # 3. Cscape intercept_hardware_interface (test sample)
            if port_num in (1, 2, 4, 16, 64, 128, 256):
                with pytest.raises((HardwareLockoutError, CscapeSafetyViolationError)) as exc_info:
                    intercept_hardware_interface(port)
                err = exc_info.value
                assert getattr(err, "status", None) == "blocked"

    @pytest.mark.parametrize("can_port", [
        "CAN0", "can0", "CAN1", "can1", "pcan", "pcan_usb", "kvaser", "vector_can",
        "socketcan", "slcan0", "cscan", "CsCAN", "canopen", "CANopen", "DeviceNet", "j1939",
    ])
    def test_can_fieldbuses_blocked(self, guard: SecurityGuard, can_port: str) -> None:
        """Verify CAN interfaces and fieldbuses raise HardwareLockoutError with status: blocked."""
        with pytest.raises((HardwareLockoutError, CscapeSafetyViolationError)) as exc_info:
            guard.validate_command(f"tool.exe {can_port}")
        err = exc_info.value
        assert getattr(err, "status", None) == "blocked"

        with pytest.raises((HardwareLockoutError, CscapeSafetyViolationError)) as exc_info:
            guard.validate_interface(can_port)
        err = exc_info.value
        assert getattr(err, "status", None) == "blocked"

        with pytest.raises((HardwareLockoutError, CscapeSafetyViolationError)) as exc_info:
            intercept_hardware_interface(can_port)
        err = exc_info.value
        assert getattr(err, "status", None) == "blocked"

    @pytest.mark.parametrize("usb_port", [
        "USB", "usb", "USB0", "usb0", "USB1", "usb1", "VID_0483", "PID_DF11",
        r"\\?\usb#vid_0483&pid_df11", "JTAG", "jtag", "swd", "dfu",
    ])
    def test_usb_and_debug_interfaces_blocked(self, guard: SecurityGuard, usb_port: str) -> None:
        """Verify USB, VID/PID, and JTAG interfaces raise HardwareLockoutError with status: blocked."""
        with pytest.raises((HardwareLockoutError, CscapeSafetyViolationError)) as exc_info:
            guard.validate_command(f"tool.exe {usb_port}")
        err = exc_info.value
        assert getattr(err, "status", None) == "blocked"

        with pytest.raises((HardwareLockoutError, CscapeSafetyViolationError)) as exc_info:
            guard.validate_interface(usb_port)
        err = exc_info.value
        assert getattr(err, "status", None) == "blocked"

        with pytest.raises((HardwareLockoutError, CscapeSafetyViolationError)) as exc_info:
            intercept_hardware_interface(usb_port)
        err = exc_info.value
        assert getattr(err, "status", None) == "blocked"

    # --------------------------------------------------------------------------
    # 2. Companion Flashing Utilities Lockout
    # --------------------------------------------------------------------------

    @pytest.mark.parametrize("flashing_tool", [
        "PGMUpdateUtility.exe",
        "pgmupdateutility.exe",
        "DfuSeCommand.exe",
        "dfusecommand.exe",
        "STMFlashLoader.exe",
        "stmflashloader.exe",
        "WinJTAG.exe",
        "winjtag.exe",
        "CscapeAutoUpdt.exe",
        "XLeTerm.exe",
        "st-link.exe",
        "dfu-util.exe",
        "openocd.exe",
        "jlink.exe",
    ])
    def test_companion_flashing_utilities_blocked(
        self, guard: SecurityGuard, cscape_guard: CscapeSafetyGuard, flashing_tool: str
    ) -> None:
        """Verify companion flashing utilities raise BlockedExecutableError with status: blocked."""
        # 1. SecurityGuard.validate_command
        with pytest.raises((HardwareLockoutError, CscapeSafetyViolationError)) as exc_info:
            guard.validate_command(f"{flashing_tool} /d")
        err = exc_info.value
        assert getattr(err, "status", None) == "blocked"
        assert isinstance(err, (HardwareLockoutError, CscapeSafetyViolationError))

        # 2. SecurityGuard.validate_execution
        with pytest.raises((HardwareLockoutError, CscapeSafetyViolationError)) as exc_info:
            guard.validate_execution(flashing_tool)
        err = exc_info.value
        assert getattr(err, "status", None) == "blocked"

        # 3. intercept_executable
        with pytest.raises((HardwareLockoutError, CscapeSafetyViolationError)) as exc_info:
            intercept_executable(flashing_tool)
        err = exc_info.value
        assert getattr(err, "status", None) == "blocked"

        # 4. CscapeSafetyGuard.validate_flashing_tool
        with pytest.raises((HardwareLockoutError, CscapeSafetyViolationError)) as exc_info:
            cscape_guard.validate_flashing_tool(flashing_tool)
        err = exc_info.value
        assert getattr(err, "status", None) == "blocked"

    # --------------------------------------------------------------------------
    # 3. Win32 Download Command IDs (ID_PROGRAM_DOWNLOAD = 32827, ID_CONTROLLER_DOWNLOAD = 33149)
    # --------------------------------------------------------------------------

    @pytest.mark.parametrize("cmd_id", [
        32827,
        33149,
        "32827",
        "33149",
        "ID_PROGRAM_DOWNLOAD",
        "ID_CONTROLLER_DOWNLOAD",
        "ID_CONTROLLER_DOWNLOAD_ALT",
        "ID_PROGRAM_DOWNLOADOPTIONS",
    ])
    def test_win32_download_command_ids_strictly_raise(
        self, guard: SecurityGuard, cscape_guard: CscapeSafetyGuard, cmd_id: Any
    ) -> None:
        """Verify download command IDs strictly raise CscapeSafetyViolationError with status: blocked."""
        # 1. intercept_download_command
        with pytest.raises(CscapeSafetyViolationError) as exc_info:
            intercept_download_command(cmd_id)
        err = exc_info.value
        assert getattr(err, "status", None) == "blocked"

        # 2. CscapeSafetyGuard.validate_cscape_download
        with pytest.raises(CscapeSafetyViolationError) as exc_info:
            cscape_guard.validate_cscape_download(cmd_id)
        err = exc_info.value
        assert getattr(err, "status", None) == "blocked"

        # 3. SecurityGuard.validate_ui_command
        with pytest.raises(CscapeSafetyViolationError) as exc_info:
            guard.validate_ui_command(cmd_id)
        err = exc_info.value
        assert getattr(err, "status", None) == "blocked"

    # --------------------------------------------------------------------------
    # 4. Unconditional Lockouts on Direct Download Methods
    # --------------------------------------------------------------------------

    def test_unconditional_download_and_connection_methods_raise(
        self, guard: SecurityGuard, cscape_guard: CscapeSafetyGuard
    ) -> None:
        """Verify unconditional lockout methods strictly raise with status: blocked."""
        # Hardware connection
        with pytest.raises(HardwareLockoutError) as exc_info:
            guard.validate_hardware_connection(target="XL4", port="COM1")
        assert getattr(exc_info.value, "status", None) == "blocked"

        with pytest.raises(HardwareLockoutError) as exc_info:
            cscape_guard.validate_hardware_connection(target="XL4", port="COM1")
        assert getattr(exc_info.value, "status", None) == "blocked"

        # Controller download
        with pytest.raises(UnauthorizedDownloadError) as exc_info:
            guard.validate_download(target="XL4", binary_path="TankLevelClosedLoop.csp")
        assert getattr(exc_info.value, "status", None) == "blocked"

        with pytest.raises(UnauthorizedDownloadError) as exc_info:
            cscape_guard.validate_download(target="XL4", binary_path="TankLevelClosedLoop.csp")
        assert getattr(exc_info.value, "status", None) == "blocked"

        # Firmware flash
        with pytest.raises(UnauthorizedDownloadError) as exc_info:
            guard.validate_firmware_flash(firmware_path="firmware.bin", tool="PGMUpdateUtility.exe")
        assert getattr(exc_info.value, "status", None) == "blocked"

    # --------------------------------------------------------------------------
    # 5. Compiler Interception Returns status: blocked
    # --------------------------------------------------------------------------

    @pytest.mark.parametrize("download_cmd", [32827, 33149])
    def test_compiler_download_command_returns_status_blocked(self, download_cmd: int) -> None:
        """Verify cscape_compile_project returns status: blocked when download command ID is passed."""
        res = cscape_compile_project("TankLevelClosedLoop", command_id=download_cmd)
        assert res["status"] == "blocked"
        assert res["error_code"] == "ERR_HARDWARE_LOCKOUT"
        assert res["compile_successful"] is False
        assert res["error_count"] >= 1
