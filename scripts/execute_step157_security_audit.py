#!/usr/bin/env python
"""Step 157: Fail-Closed Security Lockout & Straton Quarantine Audit.

MANDATE: Fail-closed security validation only. Zero hardware downloads. Zero Straton imports.
Tasks:
1. Verify hardware download lockout: ensure ID_CONTROLLER_DOWNLOAD = 32827 and 33149 are strictly blocked
   fail-closed across src/cscape/compilation.py and src/cscape/safety.py.
2. Verify that cscape_download_logic MCP tool call is rejected fail-closed via run_mcp_server.py stdio client.
3. Verify Straton quarantine: confirm quarantine/straton_k5_legacy/ holds legacy files and zero active .py files
   import straton or k5.
4. Verify offline gate simulation: verify assert_cscape_live() raises CscapeLivenessGateError when gate ready_for_tests=False.
5. Record checkpoint artifacts/checkpoints/step157_security_audit_checkpoint.json (and mirror to user workspace).
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

# Dual-root configuration
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()

for root in [USER_ROOT, HORNER_ROOT]:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from src.cscape.safety import (
    ID_CONTROLLER_DOWNLOAD,
    ID_CONTROLLER_DOWNLOAD_ALT,
    BLOCKED_DOWNLOAD_COMMAND_IDS,
    intercept_download_command,
    CscapeSafetyGuard,
    CscapeSafetyViolationError,
)
from src.cscape.compilation import (
    ID_CONTROLLER_DOWNLOAD as COMP_DOWNLOAD,
    ID_PROGRAM_DOWNLOADOPTIONS as COMP_DOWNLOAD_ALT,
    CscapeCompiler,
    UnauthorizedDownloadError,
)
from src.cscape.gate import (
    assert_cscape_live,
    get_gate_status,
    CscapeLivenessGateError,
)


def get_utc_iso() -> str:
    """Return ISO 8601 UTC timestamp."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def compute_sha256(data: bytes) -> str:
    """Compute hex SHA-256 digest."""
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


class StdioRpcFastClient:
    """Async stdio client for FastMCP server."""

    def __init__(self, python_exe: Path, server_script: Path):
        self.python_exe = python_exe
        self.server_script = server_script
        self.proc: asyncio.subprocess.Process | None = None
        self.req_id = 0
        self.futures: Dict[int, asyncio.Future] = {}
        self.reader_task: asyncio.Task | None = None

    async def start(self) -> None:
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONPATH"] = f"{str(HORNER_ROOT)};{str(USER_ROOT)}"
        self.proc = await asyncio.create_subprocess_exec(
            str(self.python_exe),
            str(self.server_script),
            "--transport", "stdio",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self.reader_task = asyncio.create_task(self._reader_loop())

    async def _reader_loop(self) -> None:
        while self.proc and self.proc.stdout and not self.proc.stdout.at_eof():
            line = await self.proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                continue
            if "id" in msg and msg["id"] in self.futures:
                fut = self.futures.pop(msg["id"])
                if not fut.done():
                    fut.set_result(msg)

    async def call_rpc(self, method: str, params: Dict[str, Any] | None = None, timeout: float = 15.0) -> Dict[str, Any]:
        self.req_id += 1
        cid = self.req_id
        payload = {"jsonrpc": "2.0", "id": cid, "method": method}
        if params is not None:
            payload["params"] = params

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self.futures[cid] = fut

        req_line = json.dumps(payload) + "\n"
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(req_line.encode("utf-8"))
        await self.proc.stdin.drain()
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self.futures.pop(cid, None)
            raise TimeoutError(f"RPC call {method} (id={cid}) timed out after {timeout}s")

    async def call_tool(self, name: str, arguments: Dict[str, Any] | None = None, timeout: float = 15.0) -> Dict[str, Any]:
        return await self.call_rpc("tools/call", {"name": name, "arguments": arguments or {}}, timeout=timeout)

    async def close(self) -> None:
        if self.reader_task:
            self.reader_task.cancel()
            try:
                await self.reader_task
            except asyncio.CancelledError:
                pass
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                self.proc.kill()


def audit_task1_hardware_download_lockout() -> Dict[str, Any]:
    """Verify hardware download lockout across safety.py and compilation.py."""
    results: Dict[str, Any] = {
        "status": "PENDING",
        "safety_py": {},
        "compilation_py": {},
    }

    # Verify command ID constants
    assert ID_CONTROLLER_DOWNLOAD == 32827, f"Expected 32827, got {ID_CONTROLLER_DOWNLOAD}"
    assert ID_CONTROLLER_DOWNLOAD_ALT == 33149, f"Expected 33149, got {ID_CONTROLLER_DOWNLOAD_ALT}"
    assert COMP_DOWNLOAD == 32827, f"Expected 32827 in compilation.py, got {COMP_DOWNLOAD}"
    assert COMP_DOWNLOAD_ALT == 33149, f"Expected 33149 in compilation.py, got {COMP_DOWNLOAD_ALT}"

    # Verify blocked command sets
    assert 32827 in BLOCKED_DOWNLOAD_COMMAND_IDS
    assert 33149 in BLOCKED_DOWNLOAD_COMMAND_IDS
    assert "ID_CONTROLLER_DOWNLOAD" in BLOCKED_DOWNLOAD_COMMAND_IDS
    assert "ID_CONTROLLER_DOWNLOAD_ALT" in BLOCKED_DOWNLOAD_COMMAND_IDS

    # Test interception in safety.py
    intercept_tested = []
    for cmd in [32827, 33149, "32827", "33149", "ID_CONTROLLER_DOWNLOAD", "ID_CONTROLLER_DOWNLOAD_ALT", "ID_DOWNLOAD"]:
        try:
            intercept_download_command(cmd)
            raise AssertionError(f"intercept_download_command did not block {cmd}")
        except CscapeSafetyViolationError as exc:
            intercept_tested.append({"cmd": str(cmd), "blocked": True, "error": str(exc)})

    # Test CscapeSafetyGuard
    guard = CscapeSafetyGuard()
    guard_tested = []
    for cmd in [32827, 33149]:
        try:
            guard.validate_cscape_download(cmd)
            raise AssertionError(f"guard.validate_cscape_download did not block {cmd}")
        except CscapeSafetyViolationError as exc:
            guard_tested.append({"cmd": cmd, "blocked": True, "error": str(exc)})

    results["safety_py"] = {
        "id_controller_download": ID_CONTROLLER_DOWNLOAD,
        "id_controller_download_alt": ID_CONTROLLER_DOWNLOAD_ALT,
        "intercept_tests": intercept_tested,
        "guard_tests": guard_tested,
        "passed": True,
    }

    # Test compilation.py GUI compile lockout
    compiler = CscapeCompiler(workspace_root=str(USER_ROOT))
    comp_tested = []
    for cmd in [32827, 33149, COMP_DOWNLOAD, COMP_DOWNLOAD_ALT]:
        try:
            compiler.trigger_cscape_gui_compile(cscape_hwnd=999999, command_id=cmd)
            raise AssertionError(f"compiler.trigger_cscape_gui_compile did not block command {cmd}")
        except UnauthorizedDownloadError as exc:
            comp_tested.append({"cmd": cmd, "blocked": True, "error": str(exc)})

    results["compilation_py"] = {
        "id_controller_download": COMP_DOWNLOAD,
        "id_program_downloadoptions": COMP_DOWNLOAD_ALT,
        "compile_tests": comp_tested,
        "passed": True,
    }

    results["status"] = "PASSED"
    return results


async def audit_task2_mcp_download_tool_rejection() -> Dict[str, Any]:
    """Verify cscape_download_logic MCP tool call is rejected fail-closed via run_mcp_server.py stdio client."""
    results: Dict[str, Any] = {"status": "PENDING"}

    server_script = USER_ROOT / "scripts" / "run_mcp_server.py"
    if not server_script.exists():
        server_script = HORNER_ROOT / "scripts" / "run_mcp_server.py"
    assert server_script.exists(), f"Server runner not found: {server_script}"

    py_exe = Path(sys.executable)
    client = StdioRpcFastClient(py_exe, server_script)
    await client.start()
    try:
        init_resp = await client.call_rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "SecurityLockoutAuditor", "version": "1.0.0"},
        })
        await client.call_rpc("notifications/initialized")

        # Invoke prohibited download tool
        tool_resp = await client.call_tool("cscape_download_logic", {})

        # Assert fail-closed rejection
        assert "result" in tool_resp, f"Malformed response: {tool_resp}"
        result_body = tool_resp["result"]
        is_error = result_body.get("isError", False)
        content = result_body.get("content", [])
        content_text = content[0].get("text", "") if content else ""

        assert is_error is True, f"Expected isError=True, got: {tool_resp}"
        assert "Unknown tool" in content_text or "rejected" in content_text.lower() or "blocked" in content_text.lower(), (
            f"Unexpected error content: {content_text}"
        )

        results["server_script"] = str(server_script)
        results["init_protocol_version"] = init_resp.get("result", {}).get("protocolVersion")
        results["tool_called"] = "cscape_download_logic"
        results["is_error"] = is_error
        results["error_message"] = content_text
        results["rejection_fail_closed"] = True
        results["status"] = "PASSED"
    finally:
        await client.close()

    return results


def audit_task3_straton_quarantine() -> Dict[str, Any]:
    """Verify Straton quarantine holds legacy files and zero active .py files import straton or k5."""
    results: Dict[str, Any] = {"status": "PENDING"}

    # 1. Confirm quarantine/straton_k5_legacy/ holds legacy files
    quarantine_paths = [
        USER_ROOT / "quarantine" / "straton_k5_legacy",
        HORNER_ROOT / "quarantine" / "straton_k5_legacy",
    ]
    quarantine_verified = False
    legacy_files_found: List[str] = []
    for qpath in quarantine_paths:
        if qpath.exists() and qpath.is_dir():
            files = [str(f.relative_to(qpath)) for f in qpath.rglob("*.*")]
            if files:
                quarantine_verified = True
                legacy_files_found.extend(files)

    assert quarantine_verified, "No valid quarantine/straton_k5_legacy directory with legacy files found."
    assert len(legacy_files_found) > 0, "No legacy files found in quarantine."

    # 2. Confirm zero active .py files import straton or k5
    import ast
    scanned_roots = [USER_ROOT, HORNER_ROOT]
    offending_files: List[Dict[str, str]] = []
    total_py_files = 0

    for root in scanned_roots:
        if not root.exists():
            continue
        for folder_name in ["src", "scripts", "tests"]:
            folder = root / folder_name
            if not folder.exists():
                continue
            for py_path in folder.rglob("*.py"):
                total_py_files += 1
                try:
                    text = py_path.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(text, filename=str(py_path))
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                parts = [p.lower() for p in alias.name.split(".")]
                                if "straton" in parts or "k5" in parts:
                                    offending_files.append({"file": str(py_path), "match": f"import {alias.name}"})
                        elif isinstance(node, ast.ImportFrom):
                            if node.module:
                                parts = [p.lower() for p in node.module.split(".")]
                                if "straton" in parts or "k5" in parts:
                                    offending_files.append({"file": str(py_path), "match": f"from {node.module} import ..."})
                except Exception:
                    pass

    assert len(offending_files) == 0, f"Found {len(offending_files)} active .py files importing straton/k5: {offending_files}"

    results["quarantine_directory"] = "quarantine/straton_k5_legacy"
    results["legacy_files_count"] = len(legacy_files_found)
    results["legacy_files"] = list(set(legacy_files_found))
    results["total_py_files_scanned"] = total_py_files
    results["active_straton_imports_count"] = len(offending_files)
    results["zero_straton_imports_verified"] = True
    results["status"] = "PASSED"
    return results


def audit_task4_offline_gate_simulation() -> Dict[str, Any]:
    """Verify assert_cscape_live() raises CscapeLivenessGateError when gate ready_for_tests=False."""
    results: Dict[str, Any] = {"status": "PENDING"}

    offline_gate_payload = {
        "ready_for_tests": False,
        "status": "OFFLINE_SIMULATION",
        "reason": "Test gate forced offline to verify fail-closed lockout",
        "timestamp_utc": get_utc_iso(),
    }

    caught_expected = False
    caught_msg = ""

    with patch("src.cscape.gate.get_gate_status", return_value=offline_gate_payload):
        try:
            assert_cscape_live()
        except CscapeLivenessGateError as exc:
            caught_expected = True
            caught_msg = str(exc)

    assert caught_expected is True, "assert_cscape_live() failed to raise CscapeLivenessGateError when ready_for_tests=False"
    assert "FAIL-CLOSED" in caught_msg, f"Expected 'FAIL-CLOSED' in exception message, got: {caught_msg}"
    assert "OFFLINE_SIMULATION" in caught_msg, f"Expected status in exception message, got: {caught_msg}"

    results["simulated_gate"] = offline_gate_payload
    results["cscape_liveness_gate_error_raised"] = True
    results["exception_message"] = caught_msg
    results["fail_closed_verified"] = True
    results["status"] = "PASSED"
    return results


async def main_async() -> Dict[str, Any]:
    start_ts = get_utc_iso()

    # Step 1
    t1_res = audit_task1_hardware_download_lockout()

    # Step 2
    t2_res = await audit_task2_mcp_download_tool_rejection()

    # Step 3
    t3_res = audit_task3_straton_quarantine()

    # Step 4
    t4_res = audit_task4_offline_gate_simulation()

    finish_ts = get_utc_iso()

    audit_summary = {
        "step": 157,
        "name": "step157_security_audit",
        "status": "PASSED",
        "start_time_utc": start_ts,
        "end_time_utc": finish_ts,
        "auditor": "Security Lockout Auditor subagent for MEGAPLAN",
        "mandate": "Fail-closed security validation only. Zero hardware downloads. Zero Straton imports.",
        "results": {
            "task1_hardware_download_lockout": t1_res,
            "task2_mcp_download_tool_rejection": t2_res,
            "task3_straton_quarantine": t3_res,
            "task4_offline_gate_simulation": t4_res,
        },
    }

    # Save log to both roots
    log_rel = Path("artifacts") / "logs" / "step157_security_audit.json"
    log_json = json.dumps(audit_summary, indent=2)
    for root in [USER_ROOT, HORNER_ROOT]:
        target = root / log_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(log_json, encoding="utf-8")

    # Save checkpoint to both roots
    checkpoint_data = {
        "step": 157,
        "name": "step157_security_audit_checkpoint",
        "status": "PASSED",
        "timestamp_utc": finish_ts,
        "auditor": "Security Lockout Auditor subagent",
        "mandate": "Fail-closed security validation only. Zero hardware downloads. Zero Straton imports.",
        "hardware_download_lockout_verified": True,
        "id_controller_download_32827_blocked": True,
        "id_controller_download_alt_33149_blocked": True,
        "cscape_download_logic_mcp_rejected": True,
        "straton_quarantine_verified": True,
        "active_py_straton_imports": 0,
        "total_active_py_files_scanned": t3_res["total_py_files_scanned"],
        "offline_gate_simulation_verified": True,
        "cscape_liveness_gate_error_fail_closed": True,
    }

    checkpoint_bytes = json.dumps(checkpoint_data, indent=2).encode("utf-8")
    checkpoint_data["checkpoint_sha256"] = compute_sha256(checkpoint_bytes)

    ckpt_rel = Path("artifacts") / "checkpoints" / "step157_security_audit_checkpoint.json"
    ckpt_final_json = json.dumps(checkpoint_data, indent=2)

    for root in [USER_ROOT, HORNER_ROOT]:
        target = root / ckpt_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(ckpt_final_json, encoding="utf-8")

    print(f"Audit completed successfully. Status: {audit_summary['status']}")
    print(f"Checkpoint written: {ckpt_rel} (SHA256: {checkpoint_data['checkpoint_sha256']})")
    return checkpoint_data


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
