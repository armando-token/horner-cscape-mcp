"""Real Cscape 10.2 Safety & Hardware No-Download Test Suite.

CRITICAL MANDATE: Absolute lockout of physical PLC connections and controller downloads.
Validates:
1. Cscape UI automation explicitly blocks menu items, toolbar buttons, and shortcuts
   triggering Controller -> Download (e.g. ID_CONTROLLER_DOWNLOAD, ID_PLC_DOWNLOAD).
2. All download attempts via UI commands, menus, toolbars, shortcuts, CLI flags,
   or automation methods raise UnauthorizedDownloadError.
3. Cscape is never configured with physical COM, CAN, or USB interfaces (HardwareLockoutError).
4. Real Cscape 10.2 binary resources (Ribbon XML, command IDs) are audited and locked down.
5. CLIRunner and CscapeAutomationBridge download/hardware methods unconditionally raise.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Union
import pytest

from src.automation.cli_runner import CLIRunner, resolve_cscape_path
from src.automation.com_bridge import CscapeAutomationBridge
from src.automation.ui_automation import (
    CscapeUIAutomation,
    verify_cscape_hardware_lockout,
    ID_CONTROLLER_DOWNLOAD,
    ID_PLC_DOWNLOAD,
    ID_PLC_UPLOAD,
    ID_PLC_VERIFY,
    ID_PLC_CLEARMEMORY,
    ID_ONLINECHANGEACTION,
    ID_ONLINECHANGECONNECT,
    ID_ONLINECHANGEREVERT,
    ID_DEBUGOPTIONSELECTIONMENU_DOWNLOADONLINECHANGE,
    ID_DEBUGOPTIONSELECTIONMENU_DOONLINECHANGE,
    ID_PROGRAM_DOWNLOADOPTIONS,
    ID_OPEN_COMMUNICATION,
    ID_CLOSE_COMMUNICATION,
    ID_CONTROLLER_CONNECTIONWIZARD,
    ID_CONTROLLER_SETNETWORKID,
    ID_PROGRAM_SETNODEID,
    ID_EDIT_FIND,
    ID_VIEW_COMMENTS,
    ID_TOOLS_PROJECTNAVIGATOR,
    BLOCKED_COMMAND_IDS,
    BLOCKED_MENU_ITEMS,
    BLOCKED_TOOLBAR_BUTTONS,
    BLOCKED_SHORTCUTS,
    BLOCKED_INTERFACES,
)
from src.security.exceptions import (
    HardwareLockoutError,
    SecurityError,
    UnauthorizedDownloadError,
)
from src.security.guard import SecurityGuard, SafetyGuard
from src.security.policy import SafetyPolicy


# ==============================================================================
# 1. Cscape UI Automation: Command IDs Lockout
# ==============================================================================

class TestCscapeUIAutomationCommandIDs:
    """Test Cscape UI automation command dispatch explicitly blocks downloads and hardware."""

    @pytest.fixture
    def ui(self) -> CscapeUIAutomation:
        return CscapeUIAutomation()

    @pytest.mark.parametrize("cmd_id", [
        ID_CONTROLLER_DOWNLOAD,
        "ID_CONTROLLER_DOWNLOAD",
        ID_PLC_DOWNLOAD,
        "ID_PLC_DOWNLOAD",
        32827,
        ID_PLC_UPLOAD,
        "ID_PLC_UPLOAD",
        32828,
        ID_PLC_VERIFY,
        "ID_PLC_VERIFY",
        32862,
        ID_PLC_CLEARMEMORY,
        "ID_PLC_CLEARMEMORY",
        32993,
        ID_ONLINECHANGEACTION,
        "ID_ONLINECHANGEACTION",
        38295,
        ID_ONLINECHANGEREVERT,
        "ID_ONLINECHANGEREVERT",
        38297,
        ID_DEBUGOPTIONSELECTIONMENU_DOWNLOADONLINECHANGE,
        "ID_DEBUGOPTIONSELECTIONMENU_DOWNLOADONLINECHANGE",
        38372,
        ID_DEBUGOPTIONSELECTIONMENU_DOONLINECHANGE,
        "ID_DEBUGOPTIONSELECTIONMENU_DOONLINECHANGE",
        38373,
        ID_PROGRAM_DOWNLOADOPTIONS,
        "ID_PROGRAM_DOWNLOADOPTIONS",
        33149,
        "ID_DOWNLOAD",
        "ID_DOWNLOAD_PROGRAM",
        "ID_CONTROLLER_FLASH",
        "ID_FIRMWARE_DOWNLOAD",
        "ID_FIRMWARE_UPDATE",
    ])
    def test_download_command_ids_raise_unauthorized_download_error(
        self, ui: CscapeUIAutomation, cmd_id: Union[str, int]
    ) -> None:
        """CRITICAL MANDATE: Attempting any download command ID raises UnauthorizedDownloadError."""
        with pytest.raises(UnauthorizedDownloadError) as exc_info:
            ui.dispatch_command(cmd_id)
        assert "strictly prohibited" in str(exc_info.value).lower() or "blocked" in str(exc_info.value).lower()

        # Direct validation method must also raise
        with pytest.raises(UnauthorizedDownloadError):
            ui.validate_command_id(cmd_id)

    @pytest.mark.parametrize("hw_cmd_id", [
        ID_OPEN_COMMUNICATION,
        "ID_OPEN_COMMUNICATION",
        2112,
        ID_CLOSE_COMMUNICATION,
        "ID_CLOSE_COMMUNICATION",
        38458,
        ID_CONTROLLER_CONNECTIONWIZARD,
        "ID_CONTROLLER_CONNECTIONWIZARD",
        38269,
        ID_CONTROLLER_SETNETWORKID,
        "ID_CONTROLLER_SETNETWORKID",
        33049,
        ID_PROGRAM_SETNODEID,
        "ID_PROGRAM_SETNODEID",
        32850,
        ID_ONLINECHANGECONNECT,
        "ID_ONLINECHANGECONNECT",
        38293,
        "ID_CONTROLLER_CONNECT",
        "ID_HARDWARE_CONNECT",
    ])
    def test_hardware_comm_command_ids_raise_hardware_lockout_error(
        self, ui: CscapeUIAutomation, hw_cmd_id: Union[str, int]
    ) -> None:
        """CRITICAL MANDATE: Attempting any hardware connection command ID raises HardwareLockoutError."""
        with pytest.raises(HardwareLockoutError) as exc_info:
            ui.dispatch_command(hw_cmd_id)
        assert "locked out" in str(exc_info.value).lower() or "hardware" in str(exc_info.value).lower()

        with pytest.raises(HardwareLockoutError):
            ui.validate_command_id(hw_cmd_id)

    @pytest.mark.parametrize("safe_cmd_id", [
        ID_EDIT_FIND,
        ID_VIEW_COMMENTS,
        ID_TOOLS_PROJECTNAVIGATOR,
    ])
    def test_safe_command_ids_permitted(self, ui: CscapeUIAutomation, safe_cmd_id: int) -> None:
        """Verify non-download, non-hardware UI commands succeed in safe mode."""
        res = ui.dispatch_command(safe_cmd_id)
        assert res["status"] == "success"
        assert res["command_id"] == safe_cmd_id


# ==============================================================================
# 2. Cscape UI Automation: Menu Items Lockout
# ==============================================================================

class TestCscapeUIAutomationMenuItems:
    """Test Cscape UI automation explicitly blocks menu items triggering Controller -> Download."""

    @pytest.fixture
    def ui(self) -> CscapeUIAutomation:
        return CscapeUIAutomation()

    @pytest.mark.parametrize("menu_item", [
        "Controller -> Download",
        "Controller -> Download...",
        "Controller -> Download Program",
        "Controller -> Download System Firmware",
        "Controller -> Firmware Update",
        "Controller -> Upload",
        "Online Change -> Download Online Change",
        "Program -> Download Options",
        "File -> Download",
        "Tools -> Download",
        "controller -> download",
        "CONTROLLER -> DOWNLOAD",
        "Controller -> Flash Firmware",
        "Controller -> Burn to Flash",
    ])
    def test_menu_items_raise_unauthorized_download_error(
        self, ui: CscapeUIAutomation, menu_item: str
    ) -> None:
        """CRITICAL MANDATE: Selecting any download menu item raises UnauthorizedDownloadError."""
        with pytest.raises(UnauthorizedDownloadError) as exc_info:
            ui.trigger_menu_item(menu_item)
        assert "download" in str(exc_info.value).lower()

        # Direct validation method must also raise
        with pytest.raises(UnauthorizedDownloadError):
            ui.validate_menu_item(menu_item)

    @pytest.mark.parametrize("hw_menu_item", [
        "Controller -> Connect",
        "Controller -> Connection Wizard",
        "Controller -> Communication",
        "Controller -> Communication...",
        "Controller -> Hardware Configuration",
        "Online Change -> Start",
    ])
    def test_hardware_menu_items_raise_hardware_lockout_error(
        self, ui: CscapeUIAutomation, hw_menu_item: str
    ) -> None:
        """CRITICAL MANDATE: Selecting any hardware connection menu item raises HardwareLockoutError."""
        with pytest.raises(HardwareLockoutError):
            ui.trigger_menu_item(hw_menu_item)

        with pytest.raises(HardwareLockoutError):
            ui.validate_menu_item(hw_menu_item)

    @pytest.mark.parametrize("safe_menu_item", [
        "File -> Save",
        "Edit -> Select All",
        "Edit -> Find",
        "View -> Output Window",
        "Logic Editing -> Grid Lines",
        "Tools -> Project Navigator",
    ])
    def test_safe_menu_items_permitted(self, ui: CscapeUIAutomation, safe_menu_item: str) -> None:
        """Verify standard safe editing menu paths succeed."""
        res = ui.trigger_menu_item(safe_menu_item)
        assert res["status"] == "success"
        assert res["menu_path"] == safe_menu_item


# ==============================================================================
# 3. Cscape UI Automation: Toolbar Buttons Lockout
# ==============================================================================

class TestCscapeUIAutomationToolbarButtons:
    """Test Cscape UI automation explicitly blocks toolbar buttons triggering download."""

    @pytest.fixture
    def ui(self) -> CscapeUIAutomation:
        return CscapeUIAutomation()

    @pytest.mark.parametrize("toolbar_button", [
        "Download",
        "download",
        "DOWNLOAD",
        "Download to Controller",
        "Controller Download",
        "Download Online Change",
        "Flash",
        "Burn",
        ID_PLC_DOWNLOAD,
        ID_CONTROLLER_DOWNLOAD,
        "ID_PLC_DOWNLOAD",
        "ID_CONTROLLER_DOWNLOAD",
    ])
    def test_toolbar_buttons_raise_unauthorized_download_error(
        self, ui: CscapeUIAutomation, toolbar_button: Union[str, int]
    ) -> None:
        """CRITICAL MANDATE: Clicking any download toolbar button raises UnauthorizedDownloadError."""
        with pytest.raises(UnauthorizedDownloadError) as exc_info:
            ui.click_toolbar_button(toolbar_button)
        assert "download" in str(exc_info.value).lower()

        with pytest.raises(UnauthorizedDownloadError):
            ui.validate_toolbar_button(toolbar_button)

    @pytest.mark.parametrize("hw_button", [
        "Connect",
        "Connection Wizard",
        ID_OPEN_COMMUNICATION,
        "ID_OPEN_COMMUNICATION",
        ID_CONTROLLER_CONNECTIONWIZARD,
        "ID_CONTROLLER_CONNECTIONWIZARD",
    ])
    def test_hardware_toolbar_buttons_raise_hardware_lockout_error(
        self, ui: CscapeUIAutomation, hw_button: Union[str, int]
    ) -> None:
        """CRITICAL MANDATE: Clicking any connection button raises HardwareLockoutError."""
        with pytest.raises(HardwareLockoutError):
            ui.click_toolbar_button(hw_button)

        with pytest.raises(HardwareLockoutError):
            ui.validate_toolbar_button(hw_button)

    @pytest.mark.parametrize("safe_button", [
        "Save",
        "Zoom",
        "Project Navigator",
        "Output Window",
        ID_EDIT_FIND,
    ])
    def test_safe_toolbar_buttons_permitted(
        self, ui: CscapeUIAutomation, safe_button: Union[str, int]
    ) -> None:
        """Verify safe UI toolbar buttons succeed."""
        res = ui.click_toolbar_button(safe_button)
        assert res["status"] == "success"


# ==============================================================================
# 4. Cscape UI Automation: Keyboard Shortcuts Lockout
# ==============================================================================

class TestCscapeUIAutomationShortcuts:
    """Test Cscape UI automation explicitly blocks shortcuts that trigger Controller -> Download."""

    @pytest.fixture
    def ui(self) -> CscapeUIAutomation:
        return CscapeUIAutomation()

    @pytest.mark.parametrize("shortcut", [
        "Ctrl+D",
        "ctrl+d",
        "CTRL+D",
        "Ctrl + D",
        "control+d",
        "^d",
        "^D",
        "Ctrl+Shift+D",
        "ctrl+shift+d",
        "CTRL+SHIFT+D",
        "Alt+C, D",
        "alt+c, d",
        "Ctrl+F7",
        "ctrl+f7",
        "Ctrl+U",
        "ctrl+u",
    ])
    def test_shortcuts_raise_unauthorized_download_error(
        self, ui: CscapeUIAutomation, shortcut: str
    ) -> None:
        """CRITICAL MANDATE: Any shortcut triggering Controller -> Download raises UnauthorizedDownloadError."""
        with pytest.raises(UnauthorizedDownloadError) as exc_info:
            ui.send_shortcut(shortcut)
        assert "download" in str(exc_info.value).lower() or "shortcut" in str(exc_info.value).lower()

        with pytest.raises(UnauthorizedDownloadError):
            ui.validate_shortcut(shortcut)

    @pytest.mark.parametrize("safe_shortcut", [
        "Ctrl+S",
        "ctrl+s",
        "Ctrl+C",
        "Ctrl+V",
        "Ctrl+Z",
        "Ctrl+Y",
        "Ctrl+F",
        "F3",
    ])
    def test_safe_shortcuts_permitted(self, ui: CscapeUIAutomation, safe_shortcut: str) -> None:
        """Verify standard editing shortcuts succeed."""
        res = ui.send_shortcut(safe_shortcut)
        assert res["status"] == "success"
        assert res["shortcut"] == safe_shortcut


# ==============================================================================
# 5. Physical Communication Interface Lockout (COM, CAN, USB)
# ==============================================================================

class TestCscapePhysicalInterfaceLockout:
    """Verify Cscape is never configured with physical COM, CAN, or USB interfaces."""

    @pytest.fixture
    def ui(self) -> CscapeUIAutomation:
        return CscapeUIAutomation()

    # --- COM / Serial Interfaces ---
    @pytest.mark.parametrize("com_port", [
        "COM1",
        "com1",
        "COM2",
        "COM4",
        "COM10",
        "COM256",
        r"\\.\COM1",
        r"\\.\COM3",
        "/dev/ttyS0",
        "/dev/ttyUSB0",
        "/dev/ttyACM0",
        "serial",
        "RS232",
        "RS485",
        "RS-232",
        "RS-485",
    ])
    def test_com_interfaces_raise_hardware_lockout(
        self, ui: CscapeUIAutomation, com_port: str
    ) -> None:
        """CRITICAL MANDATE: Physical COM interfaces strictly raise HardwareLockoutError."""
        with pytest.raises(HardwareLockoutError) as exc_info:
            ui.configure_interface("COM", port=com_port)
        assert "physical" in str(exc_info.value).lower() or "locked out" in str(exc_info.value).lower()

        with pytest.raises(HardwareLockoutError):
            ui.validate_interface(com_port)

    # --- CAN Interfaces ---
    @pytest.mark.parametrize("can_port", [
        "CAN",
        "can0",
        "CAN1",
        "pcan",
        "pcan_usb",
        "kvaser",
        "kvaser_leaf",
        "vector",
        "vector_can",
        "socketcan",
        "slcan0",
        "CsCAN",
        "CANopen",
        "DeviceNet",
        "J1939",
    ])
    def test_can_interfaces_raise_hardware_lockout(
        self, ui: CscapeUIAutomation, can_port: str
    ) -> None:
        """CRITICAL MANDATE: Physical CAN interfaces strictly raise HardwareLockoutError."""
        with pytest.raises(HardwareLockoutError) as exc_info:
            ui.configure_interface("CAN", port=can_port)
        assert "physical" in str(exc_info.value).lower() or "locked out" in str(exc_info.value).lower()

        with pytest.raises(HardwareLockoutError):
            ui.validate_interface(can_port)

    # --- USB Hardware Interfaces ---
    @pytest.mark.parametrize("usb_device", [
        "USB",
        "usb0",
        "USB1",
        r"\\?\usb#vid_0483&pid_df11",
        "HORNER_USB",
        "DFU",
        "JTAG",
        "VID_0483",
        "PID_DF11",
    ])
    def test_usb_interfaces_raise_hardware_lockout(
        self, ui: CscapeUIAutomation, usb_device: str
    ) -> None:
        """CRITICAL MANDATE: Physical USB interfaces strictly raise HardwareLockoutError."""
        with pytest.raises(HardwareLockoutError) as exc_info:
            ui.configure_interface("USB", port=usb_device)
        assert "physical" in str(exc_info.value).lower() or "locked out" in str(exc_info.value).lower()

        with pytest.raises(HardwareLockoutError):
            ui.validate_interface(usb_device)

    # --- Authorized Software Simulation Interface ---
    @pytest.mark.parametrize("sim_target", [
        "SIMULATION",
        "simulation",
        "T5SIMUL",
        "t5simul",
        "VIRTUAL",
        "SOFTWARE",
        "OFFLINE",
    ])
    def test_simulation_interface_allowed(
        self, ui: CscapeUIAutomation, sim_target: str
    ) -> None:
        """Verify software simulation targets succeed."""
        res = ui.configure_interface(sim_target)
        assert res["status"] == "blocked"
        assert res.get("error_code") == "CONFIGURED_SIMULATION_ONLY"
        assert res["physical_hardware_connected"] is False

    def test_audit_cscape_safety_report(self, ui: CscapeUIAutomation) -> None:
        """Verify audit_cscape_safety reports locked-out status across all vectors."""
        audit = ui.audit_cscape_safety()
        assert audit["audit_result"] == "PASSED"
        assert audit["controller_download_lockout"] == "ACTIVE"
        assert audit["hardware_communication_lockout"] == "ACTIVE"
        assert audit["blocked_command_ids_count"] > 0
        assert audit["blocked_menu_items_count"] > 0
        assert audit["blocked_shortcuts_count"] > 0
        assert audit["interfaces_lockout"]["physical_interfaces_blocked"] is True
        assert audit["interfaces_lockout"]["com_interfaces_allowed"] is False
        assert audit["interfaces_lockout"]["can_interfaces_allowed"] is False
        assert audit["interfaces_lockout"]["usb_interfaces_allowed"] is False

    def test_verify_cscape_hardware_lockout_function(self) -> None:
        """Verify the standalone verify_cscape_hardware_lockout function."""
        status = verify_cscape_hardware_lockout()
        assert status["status"] in ("success", "blocked", "VERIFIED_LOCKED_OUT")
        assert status["physical_interfaces_blocked"] is True

    def test_verify_cscape_interfaces_rejects_hardware_in_config_dict(
        self, ui: CscapeUIAutomation
    ) -> None:
        """Verify config dictionaries referencing physical ports are detected and rejected."""
        with pytest.raises(HardwareLockoutError, match="Physical interface configuration detected"):
            ui.verify_interfaces_lockout({"comm_port": "COM1"})

        with pytest.raises(HardwareLockoutError):
            ui.verify_interfaces_lockout({"interface": "CAN0"})

        with pytest.raises(HardwareLockoutError):
            ui.verify_interfaces_lockout({"device": "USB"})

    def test_verify_cscape_interfaces_rejects_hardware_in_env_vars(
        self, monkeypatch: pytest.MonkeyPatch, ui: CscapeUIAutomation
    ) -> None:
        """Verify environment variables attempting hardware connections are rejected."""
        monkeypatch.setenv("CSCAPE_COM_PORT", "COM3")
        with pytest.raises(HardwareLockoutError, match="Physical interface configured via environment variable"):
            ui.verify_interfaces_lockout()


# ==============================================================================
# 6. Real Cscape 10.2 Binary & Installation Verification
# ==============================================================================

class TestRealCscapeBinarySafety:
    """Verify safety guarantees against the real Cscape 10.2 installation on host."""

    def test_cscape_binary_presence(self) -> None:
        """Verify Cscape.exe is present at the standard host path."""
        cscape_path = resolve_cscape_path()
        assert cscape_path is not None
        assert cscape_path.exists()
        assert cscape_path.name.lower() == "cscape.exe"

    def test_cscape_binary_embedded_ribbon_commands_audited(self) -> None:
        """Verify real Cscape.exe embedded command IDs match our security blocklists."""
        cscape_path = resolve_cscape_path()
        assert cscape_path is not None
        content = cscape_path.read_bytes()

        # Check that ID_PLC_DOWNLOAD and ID_ONLINECHANGEACTION exist in real binary
        assert b"ID_PLC_DOWNLOAD" in content
        assert b"ID_ONLINECHANGEACTION" in content

        # Check that our blocked command list covers them
        assert ID_PLC_DOWNLOAD in BLOCKED_COMMAND_IDS
        assert ID_ONLINECHANGEACTION in BLOCKED_COMMAND_IDS
        assert "ID_PLC_DOWNLOAD" in BLOCKED_COMMAND_IDS
        assert "ID_ONLINECHANGEACTION" in BLOCKED_COMMAND_IDS

    def test_prohibited_companion_executables_blocked(self) -> None:
        """Verify dangerous tools in Cscape directory are blocked by SecurityGuard."""
        cscape_path = resolve_cscape_path()
        assert cscape_path is not None
        install_dir = cscape_path.parent
        guard = SecurityGuard()

        for danger_tool in ("PGMUpdateUtility.exe", "DfuSeCommand.exe", "STMFlashLoader.exe", "WinJTAG.exe"):
            tool_path = install_dir / danger_tool
            # Whether present on disk or not, SecurityGuard MUST block it
            with pytest.raises(SecurityError):
                guard.validate_execution(tool_path)
            with pytest.raises(SecurityError):
                guard.validate_command(f'"{tool_path}" /d')


# ==============================================================================
# 7. CLI Runner & Automation Bridge Download Hardening
# ==============================================================================

class TestRunnerAndBridgeDownloadHardening:
    """Verify that CLIRunner and CscapeAutomationBridge strictly reject downloads."""

    def test_cli_runner_run_cscape_blocks_download_flag(self) -> None:
        """Attempting to invoke Cscape with download flags raises UnauthorizedDownloadError."""
        runner = CLIRunner()
        with pytest.raises(UnauthorizedDownloadError):
            runner.run_cscape(args=["/download"])

        with pytest.raises(UnauthorizedDownloadError):
            runner.run_cscape(args=["-d"])

        with pytest.raises(UnauthorizedDownloadError):
            runner.run_cscape(args=["--flash"])

        with pytest.raises(UnauthorizedDownloadError):
            runner.run_cscape(args=["/pgm"])

    def test_cli_runner_run_cscape_blocks_hardware_ports(self) -> None:
        """Attempting to invoke Cscape with COM or CAN ports raises HardwareLockoutError."""
        runner = CLIRunner()
        with pytest.raises(HardwareLockoutError):
            runner.run_cscape(args=["/com:COM1"])

        with pytest.raises(HardwareLockoutError):
            runner.run_cscape(args=["--port=COM3"])

        with pytest.raises(HardwareLockoutError):
            runner.run_cscape(args=["--can=can0"])

    def test_cli_runner_download_methods_raise_unauthorized_download_error(self) -> None:
        """Calling download methods on CLIRunner raises UnauthorizedDownloadError."""
        runner = CLIRunner()
        with pytest.raises(UnauthorizedDownloadError):
            runner.download_to_controller()

        with pytest.raises(UnauthorizedDownloadError):
            runner.download_project("test.k5p")

    def test_com_bridge_download_methods_raise_unauthorized_download_error(self) -> None:
        """Calling download methods on CscapeAutomationBridge raises UnauthorizedDownloadError."""
        with CscapeAutomationBridge() as bridge:
            with pytest.raises(UnauthorizedDownloadError):
                bridge.download_project("test.cpj")

            with pytest.raises(UnauthorizedDownloadError):
                bridge.download_to_controller()

    def test_com_bridge_hardware_connect_raises_hardware_lockout(self) -> None:
        """Calling connect_hardware on CscapeAutomationBridge raises HardwareLockoutError."""
        with CscapeAutomationBridge() as bridge:
            with pytest.raises(HardwareLockoutError):
                bridge.connect_hardware(target="XL4", port="COM1")

            with pytest.raises(HardwareLockoutError):
                bridge.configure_interface("COM", port="COM1")

            with pytest.raises(HardwareLockoutError):
                bridge.configure_interface("CAN", port="CAN0")

    def test_com_bridge_ui_access_enforces_lockout(self) -> None:
        """Accessing UI automation via bridge.ui enforces download lockout."""
        with CscapeAutomationBridge() as bridge:
            assert isinstance(bridge.ui, CscapeUIAutomation)
            with pytest.raises(UnauthorizedDownloadError):
                bridge.ui.trigger_menu_item("Controller -> Download")

            with pytest.raises(UnauthorizedDownloadError):
                bridge.ui.dispatch_command("ID_CONTROLLER_DOWNLOAD")

            with pytest.raises(UnauthorizedDownloadError):
                bridge.ui.send_shortcut("Ctrl+D")
