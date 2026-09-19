"""End-to-End Live MCP Server Tool Exerciser Test Suite.

Exercises the 4 core MCP tools against the live TankLevelClosedLoop project:
1. cscape_open_project
2. cscape_compile_project
3. cscape_read_variables
4. cscape_simulate_cycle

Confirms all return valid JSON responses with zero errors.
"""

import json
from pathlib import Path
import pytest

from src.mcp import tools
from src.mcp.server import server

from src.cscape.gate import assert_cscape_live, get_gate_status, CscapeLivenessGateError

LIVE_PROJECT_DIR = tools.WORKSPACE_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop"
LIVE_CSP_PATH = LIVE_PROJECT_DIR / "TankLevelClosedLoop.csp"
LIVE_VARS_PATH = LIVE_PROJECT_DIR / "variables.csv"


class TestLiveMCPE2EToolExerciser:
    """Exercises live MCP server tools against the active project."""

    def test_00_cscape_tanklevel_confirmed_before_live_mcp(self):
        """Pre-flight assertion: Confirms Cscape TankLevelClosedLoop is active and healthy before live MCP."""
        try:
            gate = assert_cscape_live()
        except CscapeLivenessGateError as exc:
            pytest.skip(f"Live Cscape gate offline or not ready: {exc}")
        assert gate.get("ready_for_tests") is True
        assert gate.get("status") == "READY_FOR_TESTS"
        assert "tanklevel" in gate.get("window_title", "").lower()
        assert gate.get("pid") is not None

    def test_01_cscape_open_project_direct(self):
        """Exercises cscape_open_project directly on live .csp file."""
        assert LIVE_CSP_PATH.exists(), f"Live project file missing: {LIVE_CSP_PATH}"
        res = tools.cscape_open_project(file_path=str(LIVE_CSP_PATH))
        
        # Valid JSON serializable
        json_str = json.dumps(res)
        assert json_str is not None
        
        # Zero error assertions
        assert res.get("success") is True
        assert res.get("is_valid_cfbf") is True
        assert res.get("project_name") == "TankLevelClosedLoop"
        assert res.get("file_size_bytes") > 0
        assert "Root Entry" in res.get("stream_entries", [])
        assert "Contents" in res.get("stream_entries", [])

    @pytest.mark.asyncio
    async def test_01_cscape_open_project_mcp_server(self):
        """Exercises cscape_open_project via MCPServer.call_tool."""
        tool_res = await server.call_tool(
            "cscape_open_project",
            {"file_path": str(LIVE_CSP_PATH)},
        )
        assert not tool_res.is_error
        raw_text = tool_res.content[0].text
        data = json.loads(raw_text)
        assert data["success"] is True
        assert data["is_valid_cfbf"] is True
        assert data["project_name"] == "TankLevelClosedLoop"

    def test_02_cscape_compile_project_direct(self):
        """Exercises cscape_compile_project directly on live project."""
        res = tools.cscape_compile_project(project_name="TankLevelClosedLoop", clean_build=True)
        
        # Valid JSON serializable
        json_str = json.dumps(res)
        assert json_str is not None
        
        # Zero error assertions
        assert res.get("success") is True
        assert res.get("compile_successful") is True
        assert res.get("status") == "success"
        assert res.get("error_count") == 0
        assert len(res.get("errors", [])) == 0
        assert len(res.get("failure_locations", [])) == 0
        assert res.get("hardware_lockout_enforced") is True
        assert "TankLevelClosedLoop" in res.get("pous_compiled", [])

    @pytest.mark.asyncio
    async def test_02_cscape_compile_project_mcp_server(self):
        """Exercises cscape_compile_project via MCPServer.call_tool."""
        tool_res = await server.call_tool(
            "cscape_compile_project",
            {"project_name": "TankLevelClosedLoop", "clean_build": True},
        )
        assert not tool_res.is_error
        raw_text = tool_res.content[0].text
        data = json.loads(raw_text)
        assert data["success"] is True
        assert data["error_count"] == 0
        assert len(data["errors"]) == 0
        assert data["hardware_lockout_enforced"] is True

    def test_03_cscape_read_variables_direct(self):
        """Exercises cscape_read_variables directly on live variables.csv."""
        assert LIVE_VARS_PATH.exists(), f"Live variables file missing: {LIVE_VARS_PATH}"
        res = tools.cscape_read_variables(file_path=str(LIVE_VARS_PATH))
        
        # Valid JSON serializable
        json_str = json.dumps(res)
        assert json_str is not None
        
        # Zero error assertions
        assert res.get("success") is True
        assert res.get("validation_status") == "VALID"
        assert res.get("conflicts_detected") == 0
        assert len(res.get("validation_errors", [])) == 0
        assert len(res.get("conflict_details", [])) == 0
        assert res.get("count") > 0
        assert len(res.get("variables", [])) == res.get("count")

    @pytest.mark.asyncio
    async def test_03_cscape_read_variables_mcp_server(self):
        """Exercises cscape_read_variables via MCPServer.call_tool."""
        tool_res = await server.call_tool(
            "cscape_read_variables",
            {"file_path": str(LIVE_VARS_PATH)},
        )
        assert not tool_res.is_error
        raw_text = tool_res.content[0].text
        data = json.loads(raw_text)
        assert data["success"] is True
        assert data["validation_status"] == "VALID"
        assert data["conflicts_detected"] == 0
        assert len(data["validation_errors"]) == 0

    def test_04_cscape_simulate_cycle_direct(self):
        """Exercises cscape_simulate_cycle directly in pure software simulation."""
        res = tools.cscape_simulate_cycle(
            dt_ms=10.0,
            inputs={"RawLevelIn": 16000, "AutoMode": True},
            project_name="TankLevelClosedLoop",
        )
        
        # Valid JSON serializable
        json_str = json.dumps(res)
        assert json_str is not None
        
        # Zero error assertions
        assert res.get("success") is True
        assert res.get("cycle") >= 0
        assert res.get("isolation_enforced") is True
        assert res.get("hardware_lockout_enforced") is True
        assert isinstance(res.get("system_bits"), dict)
        assert isinstance(res.get("registers"), dict)
        assert isinstance(res.get("variables"), dict)

    @pytest.mark.asyncio
    async def test_04_cscape_simulate_cycle_mcp_server(self):
        """Exercises cscape_simulate_cycle via MCPServer.call_tool."""
        tool_res = await server.call_tool(
            "cscape_simulate_cycle",
            {
                "dt_ms": 10.0,
                "inputs": {"RawLevelIn": 16000, "AutoMode": True},
                "project_name": "TankLevelClosedLoop",
            },
        )
        assert not tool_res.is_error
        raw_text = tool_res.content[0].text
        data = json.loads(raw_text)
        assert data["success"] is True
        assert data["cycle"] >= 0
        assert data["isolation_enforced"] is True
        assert data["hardware_lockout_enforced"] is True

    def test_05_live_mcp_e2e_fail_closed_if_gui_dies_direct(self, monkeypatch):
        """Direct tool: Asserts fail-closed behavior when Cscape GUI dies or is offline."""
        # 1. Direct dead HWND
        res_dead_hwnd = tools.cscape_compile_project(
            project_name="TankLevelClosedLoop",
            cscape_hwnd=99999999,
        )
        assert res_dead_hwnd["success"] is False
        assert res_dead_hwnd["compile_successful"] is False
        assert res_dead_hwnd["hardware_lockout_enforced"] is True
        assert len(res_dead_hwnd["errors"]) > 0
        assert "Invalid Cscape window handle" in res_dead_hwnd["errors"][0]

        # 2. Gate reporting GUI dead with require_live_gui=True
        import src.cscape.gate as gate_mod
        monkeypatch.setattr(
            gate_mod,
            "get_gate_status",
            lambda: {"ready_for_tests": False, "status": "FAIL_CLOSED_CSCAPE_DEAD", "reason": "GUI terminated unexpectedly"}
        )
        res_dead_gate = tools.cscape_compile_project(
            project_name="TankLevelClosedLoop",
            require_live_gui=True,
        )
        assert res_dead_gate["success"] is False
        assert res_dead_gate["compile_successful"] is False
        assert res_dead_gate["status"] == "error"
        assert res_dead_gate["hardware_lockout_enforced"] is True
        assert any("FAIL-CLOSED" in err for err in res_dead_gate["errors"])

    @pytest.mark.asyncio
    async def test_05_live_mcp_e2e_fail_closed_if_gui_dies_mcp_server(self, monkeypatch):
        """MCP server: Asserts fail-closed behavior via FastMCP/call_tool when Cscape GUI dies."""
        # 1. Dead HWND via MCP tool call
        tool_res = await server.call_tool(
            "cscape_compile_project",
            {"project_name": "TankLevelClosedLoop", "cscape_hwnd": 99999999},
        )
        raw_text = tool_res.content[0].text
        data = json.loads(raw_text)
        assert data["success"] is False
        assert data["compile_successful"] is False
        assert data["hardware_lockout_enforced"] is True
        assert "Invalid Cscape window handle" in data["errors"][0]

        # 2. Dead gate via MCP tool call with require_live_gui=True
        import src.cscape.gate as gate_mod
        monkeypatch.setattr(
            gate_mod,
            "get_gate_status",
            lambda: {"ready_for_tests": False, "status": "FAIL_CLOSED_CSCAPE_DEAD", "reason": "GUI terminated unexpectedly"}
        )
        tool_res2 = await server.call_tool(
            "cscape_compile_project",
            {"project_name": "TankLevelClosedLoop", "require_live_gui": True},
        )
        raw_text2 = tool_res2.content[0].text
        data2 = json.loads(raw_text2)
        assert data2["success"] is False
        assert data2["compile_successful"] is False
        assert data2["hardware_lockout_enforced"] is True
        assert any("FAIL-CLOSED" in err for err in data2["errors"])

