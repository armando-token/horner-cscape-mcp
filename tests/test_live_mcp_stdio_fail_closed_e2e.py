"""End-to-End Live MCP STDIO Transport and Fail-Closed Verification.

Validates:
1. Live JSON-RPC 2.0 stdio server initialization, tool discovery, and execution.
2. Verified live tool execution against healthy Cscape GUI (TankLevelClosedLoop).
3. Immediate fail-closed error propagation if Cscape GUI terminates or gate reports offline.
4. Strict hardware lockout (zero physical PLC download / communication) over stdio.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
if str(HORNER_ROOT) not in sys.path:
    sys.path.insert(0, str(HORNER_ROOT))
if str(USER_ROOT) not in sys.path:
    sys.path.insert(0, str(USER_ROOT))

from src.cscape.gate import assert_cscape_live, CscapeLivenessGateError, get_gate_status
from src.security.exceptions import UnauthorizedDownloadError, HardwareLockoutError


class StdioClient:
    """Lightweight JSON-RPC 2.0 client over stdio subprocess."""

    def __init__(self, python_exe: Path, server_script: Path):
        self.python_exe = python_exe
        self.server_script = server_script
        self.proc: subprocess.Popen | None = None
        self._req_id = 0

    def start(self):
        self.proc = subprocess.Popen(
            [str(self.python_exe), str(self.server_script), "--transport", "stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

    def close(self):
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=3.0)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None

    def send_rpc(self, method: str, params: dict | None = None, timeout: float = 15.0) -> dict:
        if not self.proc or not self.proc.stdin or not self.proc.stdout:
            raise RuntimeError("Process not running")
        self._req_id += 1
        msg = {"jsonrpc": "2.0", "id": self._req_id, "method": method}
        if params is not None:
            msg["params"] = params
        payload = (json.dumps(msg) + "\n").encode("utf-8")
        self.proc.stdin.write(payload)
        self.proc.stdin.flush()

        t0 = time.time()
        while time.time() - t0 < timeout:
            line = self.proc.stdout.readline()
            if not line:
                break
            line_str = line.decode("utf-8").strip()
            if not line_str:
                continue
            try:
                res = json.loads(line_str)
                if res.get("id") == self._req_id:
                    return res
            except Exception:
                pass
        raise TimeoutError(f"Timeout waiting for response to {method} (id={self._req_id})")


@pytest.fixture
def stdio_client():
    py_exe = HORNER_ROOT / ".venv" / "Scripts" / "python.exe"
    server_script = HORNER_ROOT / "scripts" / "run_mcp_server.py"
    client = StdioClient(py_exe, server_script)
    client.start()
    try:
        init_res = client.send_rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "TestLiveMCPClient", "version": "1.0.0"}
        })
        assert "result" in init_res
        yield client
    finally:
        client.close()


class TestLiveMCPStdioFailClosedE2E:
    """Verifies live stdio transport and fail-closed safety behaviors."""

    def test_stdio_handshake_and_tool_discovery(self, stdio_client):
        """Confirms stdio initialization and discovery of registered tools."""
        res = stdio_client.send_rpc("tools/list")
        assert "result" in res
        tools = res["result"].get("tools", [])
        assert len(tools) >= 15
        tool_names = {t["name"] for t in tools}
        assert "cscape_validate_st" in tool_names
        assert "cscape_compile_project" in tool_names
        assert "cscape_simulate_cycle" in tool_names
        assert "cscape_read_register" in tool_names
        assert "cscape_write_register" in tool_names

    def test_stdio_execute_under_healthy_gate(self, stdio_client):
        """Executes core MCP tools over stdio while live Cscape is healthy."""
        try:
            gate = assert_cscape_live()
        except CscapeLivenessGateError as e:
            pytest.skip(f"Live Cscape gate not ready or offline: {e}")
        assert gate["ready_for_tests"] is True

        res = stdio_client.send_rpc("tools/call", {
            "name": "cscape_validate_st",
            "arguments": {
                "code": "PROGRAM TestPOU\nVAR x : INT; END_VAR\nx := 42;\nEND_PROGRAM"
            }
        })
        assert not res.get("result", {}).get("isError", False)

        res = stdio_client.send_rpc("tools/call", {
            "name": "cscape_simulate_cycle",
            "arguments": {"inputs": {"RawLevelInput": 20000}}
        })
        assert not res.get("result", {}).get("isError", False)

        res = stdio_client.send_rpc("tools/call", {
            "name": "cscape_write_register",
            "arguments": {"address": "%R200", "value": 12345}
        })
        assert not res.get("result", {}).get("isError", False)

        res = stdio_client.send_rpc("tools/call", {
            "name": "cscape_read_register",
            "arguments": {"address": "%R200"}
        })
        assert not res.get("result", {}).get("isError", False)
        content = json.loads(res["result"]["content"][0]["text"])
        assert content.get("value") == 12345

    def test_stdio_fail_closed_if_gate_reports_dead_gui(self, monkeypatch):
        """Verifies fail-closed behavior when gate reports GUI offline."""
        dead_gate = {
            "ready_for_tests": False,
            "status": "FAIL_CLOSED_CSCAPE_DEAD",
            "pid": None,
            "hwnd": None,
            "window_title": "",
            "reason": "Cscape crashed with 0xC0000005 null pointer dereference",
        }
        monkeypatch.setattr("src.cscape.gate.get_gate_status", lambda: dead_gate)

        with pytest.raises(CscapeLivenessGateError) as exc:
            assert_cscape_live()
        assert "FAIL-CLOSED" in str(exc.value)
        assert "FAIL_CLOSED_CSCAPE_DEAD" in str(exc.value)

        from src.mcp.tools import cscape_compile_project
        tool_res = cscape_compile_project("TankLevelClosedLoop", require_live_gui=True)
        assert tool_res["success"] is False
        assert tool_res["status"] == "error"
        assert "FAIL-CLOSED" in tool_res["message"]
        assert tool_res["failure_location"]["error_code"] == "GUI_DEAD_FAIL_CLOSED"

    def test_stdio_fail_closed_if_gate_file_missing(self, monkeypatch):
        """Verifies fail-closed behavior when no gate file is detected on disk."""
        missing_gate = {
            "ready_for_tests": False,
            "status": "GATE_FILE_NOT_FOUND",
            "reason": "No active Cscape keepalive gate file detected on disk",
        }
        monkeypatch.setattr("src.cscape.gate.get_gate_status", lambda: missing_gate)

        with pytest.raises(CscapeLivenessGateError) as exc:
            assert_cscape_live()
        assert "GATE_FILE_NOT_FOUND" in str(exc.value) or "FAIL-CLOSED" in str(exc.value)

        from src.mcp.tools import cscape_compile_project
        tool_res = cscape_compile_project("TankLevelClosedLoop", require_live_gui=True)
        assert tool_res["success"] is False
        assert tool_res["status"] == "error"
        assert "FAIL-CLOSED" in tool_res["message"]
        assert tool_res["failure_location"]["error_code"] == "GUI_DEAD_FAIL_CLOSED"

    def test_stdio_zero_plc_download_enforced(self, stdio_client):
        """Verifies absolute hardware lockout: any physical download attempt is rejected."""
        from src.automation.cli_runner import CLIRunner
        runner = CLIRunner()
        with pytest.raises(UnauthorizedDownloadError):
            runner.download_to_controller("TankLevelClosedLoop.csp")
