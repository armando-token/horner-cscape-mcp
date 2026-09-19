"""Test suite verifying MCP STDIO fail-closed safety semantics if Cscape GUI terminates mid-test."""

import json
from pathlib import Path
import pytest

from src.cscape.gate import assert_cscape_live, CscapeLivenessGateError, get_gate_status
from src.security.exceptions import HardwareLockoutError, UnauthorizedDownloadError
from src.security.guard import SafetyGuard
from src.mcp.tools import cscape_compile_project, cscape_simulate_cycle


class TestLiveMCPFailClosedSemantics:
    """Verifies fail-closed enforcement when Cscape is healthy vs when GUI terminates mid-test."""

    def test_live_gate_ready_when_cscape_open(self):
        """Confirms that when Cscape is open on TankLevelClosedLoop, gate passes."""
        try:
            gate = assert_cscape_live()
        except CscapeLivenessGateError as e:
            pytest.skip(f"Live Cscape gate not ready or offline: {e}")
        assert gate["ready_for_tests"] is True
        assert gate["status"] == "READY_FOR_TESTS"
        assert gate["pid"] is not None
        assert "TankLevelClosedLoop" in gate["window_title"]

    def test_live_mcp_compile_succeeds_under_healthy_gate(self):
        """Confirms live MCP compile returns success with zero errors when GUI is healthy."""
        try:
            assert_cscape_live()
        except CscapeLivenessGateError as e:
            pytest.skip(f"Live Cscape gate not ready or offline: {e}")
        res = cscape_compile_project(project_name="TankLevelClosedLoop", clean_build=True)
        assert res["success"] is True
        assert res["status"] == "success"
        assert res["error_count"] == 0
        assert res.get("hardware_lockout_enforced") is True

    def test_fail_closed_if_gui_dies_mid_test(self, monkeypatch, tmp_path):
        """Verifies that if Cscape GUI dies or gate reports offline mid-test, operations halt fail-closed."""
        # Simulate Cscape crash/death in gate status
        dead_gate = {
            "ready_for_tests": False,
            "status": "FAIL_CLOSED_CSCAPE_DEAD",
            "pid": None,
            "hwnd": None,
            "window_title": "",
            "reason": "Cscape crashed unexpectedly with ExitCode=0xC0000005",
        }

        # Monkeypatch get_gate_status to simulate immediate mid-test death
        monkeypatch.setattr("src.cscape.gate.get_gate_status", lambda: dead_gate)

        with pytest.raises(CscapeLivenessGateError) as exc_info:
            assert_cscape_live()
        assert "FAIL-CLOSED" in str(exc_info.value)
        assert "FAIL_CLOSED_CSCAPE_DEAD" in str(exc_info.value)

        # Also verify that MCP tool requiring live GUI fails closed immediately
        tool_res = cscape_compile_project("TankLevelClosedLoop", require_live_gui=True)
        assert tool_res["success"] is False
        assert tool_res["status"] == "error"
        assert "FAIL-CLOSED" in tool_res["message"]
        assert tool_res["failure_location"]["error_code"] == "GUI_DEAD_FAIL_CLOSED"

    def test_fail_closed_if_gate_file_corrupt_or_missing(self, monkeypatch):
        """Verifies fail-closed when gate file is missing or corrupted."""
        missing_gate = {
            "ready_for_tests": False,
            "status": "GATE_FILE_NOT_FOUND",
            "reason": "No active Cscape keepalive gate file detected on disk",
        }
        monkeypatch.setattr("src.cscape.gate.get_gate_status", lambda: missing_gate)

        with pytest.raises(CscapeLivenessGateError) as exc_info:
            assert_cscape_live()
        assert "FAIL-CLOSED" in str(exc_info.value)

        # Also verify that MCP tool requiring live GUI fails closed immediately
        tool_res = cscape_compile_project("TankLevelClosedLoop", require_live_gui=True)
        assert tool_res["success"] is False
        assert tool_res["status"] == "error"
        assert "FAIL-CLOSED" in tool_res["message"]
        assert tool_res["failure_location"]["error_code"] == "GUI_DEAD_FAIL_CLOSED"

    def test_strict_zero_plc_download_lockout(self):
        """Verifies that hardware download commands trigger immediate UnauthorizedDownloadError / HardwareLockoutError."""
        from src.automation.cli_runner import CLIRunner
        from src.automation.com_bridge import CscapeAutomationBridge

        runner = CLIRunner()
        with pytest.raises(UnauthorizedDownloadError):
            runner.download_to_controller("fake_project.csp")

        bridge = CscapeAutomationBridge()
        with pytest.raises(UnauthorizedDownloadError):
            bridge.download_to_controller()

        with pytest.raises(HardwareLockoutError):
            bridge.connect_hardware(target="XL4", port="COM1")


