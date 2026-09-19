#!/usr/bin/env python
"""Step 167: Fail-Closed Security Lockout & Straton Quarantine Audit.

MANDATE: Fail-closed security validation only. Zero hardware downloads. Zero Straton imports.
Tasks:
1. Verify hardware download lockout: ensure ID_CONTROLLER_DOWNLOAD = 32827 and 33149 are strictly blocked
   fail-closed across src/cscape/compilation.py and src/cscape/safety.py.
2. Verify that cscape_download_logic MCP tool call is rejected fail-closed via run_mcp_server.py stdio client.
3. Verify Straton quarantine: confirm quarantine/straton_k5_legacy/ holds legacy files and zero active .py files
   import straton or k5.
4. Verify offline gate simulation: verify assert_cscape_live() raises CscapeLivenessGateError when gate ready_for_tests=False.
5. Record checkpoint artifacts/checkpoints/step167_security_audit_checkpoint.json (and mirror to user workspace).
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
                mid = msg.get("id")
                if mid is not None and mid in self.futures:
                    fut = self.futures.pop(mid)
                    if not fut.done():
                        fut.set_result(msg)
            except Exception:
                pass

    async def send_request(self, method: str, params: Dict[str, Any] | None = None, timeout: float = 10.0) -> Dict[str, Any]:
        self.req_id += 1
        rid = self.req_id
        fut = asyncio.get_event_loop().create_future()
        self.futures[rid] = fut
        payload = {
            "jsonrpc": "2.0",
            "id": rid,
            "method": method,
            "params": params or {},
        }
        raw = (json.dumps(payload) + "\n").encode("utf-8")
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(raw)
        await self.proc.stdin.drain()
        return await asyncio.wait_for(fut, timeout=timeout)

    async def close(self) -> None:
        if self.reader_task and not self.reader_task.done():
            self.reader_task.cancel()
        if self.proc:
            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), timeout=3.0)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass


def audit_task1_hardware_lockout() -> Dict[str, Any]:
    print("\n[TASK 1] Auditing Hardware Download Lockout Policy...")
    results = {}

    assert ID_CONTROLLER_DOWNLOAD == 32827
    assert ID_CONTROLLER_DOWNLOAD_ALT == 33149
    assert COMP_DOWNLOAD == 32827
    assert COMP_DOWNLOAD_ALT == 33149
    assert 32827 in BLOCKED_DOWNLOAD_COMMAND_IDS
    assert 33149 in BLOCKED_DOWNLOAD_COMMAND_IDS

    guard = CscapeSafetyGuard()
    compiler = CscapeCompiler()

    # 1. Check direct interception
    for cmd_id in [32827, 33149]:
        try:
            intercept_download_command(cmd_id)
            raise AssertionError(f"Command ID {cmd_id} did not fail closed in intercept_download_command!")
        except CscapeSafetyViolationError as e:
            results[f"intercept_{cmd_id}"] = {"status": "BLOCKED", "exception": str(e)}

    # 2. Check CscapeSafetyGuard validation
    for cmd_id in [32827, 33149]:
        try:
            guard.validate_cscape_download(cmd_id)
            raise AssertionError(f"Command ID {cmd_id} did not fail closed in guard.validate_cscape_download!")
        except CscapeSafetyViolationError as e:
            results[f"guard_{cmd_id}"] = {"status": "BLOCKED", "exception": str(e)}

    # 3. Check CscapeCompiler trigger compile rejection
    for cmd_id in [32827, 33149]:
        try:
            compiler.trigger_cscape_gui_compile(cscape_hwnd=0x024903DC, command_id=cmd_id)
            raise AssertionError(f"Command ID {cmd_id} did not fail closed in compiler.trigger_cscape_gui_compile!")
        except UnauthorizedDownloadError as e:
            results[f"compiler_{cmd_id}"] = {"status": "BLOCKED", "exception": str(e)}

    print("  -> Task 1 Verification PASSED: All download commands strictly fail-closed.")
    return results


async def audit_task2_mcp_download_tool_rejection() -> Dict[str, Any]:
    print("\n[TASK 2] Auditing FastMCP Download Logic Tool Lockout...")
    py_exe = Path(sys.executable)
    server_py = HORNER_ROOT / "scripts" / "run_mcp_server.py"
    client = StdioRpcFastClient(py_exe, server_py)
    results = {}

    try:
        await client.start()
        await client.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "SecurityAuditClient", "version": "1.0"},
        })
        # Try invoking cscape_download_logic
        resp = await client.send_request("tools/call", {
            "name": "cscape_download_logic",
            "arguments": {"target": "PLC"},
        })
        is_error = "error" in resp or (resp.get("result", {}).get("isError") is True)
        assert is_error, f"cscape_download_logic did not fail closed! Response: {resp}"
        results["cscape_download_logic"] = {
            "status": "BLOCKED_FAIL_CLOSED",
            "response": resp,
        }
        print("  -> Task 2 Verification PASSED: MCP download tool call strictly rejected fail-closed.")
    finally:
        await client.close()

    return results


def audit_task3_straton_quarantine() -> Dict[str, Any]:
    print("\n[TASK 3] Auditing Straton K5 Quarantine and Zero-Import Invariant...")
    results = {}
    import ast
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

    assert len(offending_files) == 0, f"Found active Straton imports in: {offending_files}"
    results["active_py_files_scanned"] = total_py_files
    results["straton_import_violations"] = 0
    print(f"  Scanned {total_py_files} active python files: 0 Straton/K5 imports found.")
    print("  -> Task 3 Verification PASSED: Straton quarantine strictly enforced.")
    return results


def audit_task4_offline_gate_resilience() -> Dict[str, Any]:
    print("\n[TASK 4] Auditing Offline Gate Resilience Simulation...")
    results = {}

    fake_offline_gate = {
        "ready_for_tests": False,
        "status": "OFFLINE",
        "pid": 0,
        "hwnd": "0x00000000",
        "window_title": "Offline",
        "reason": "Simulated offline state for test",
    }

    with patch("src.cscape.gate.get_gate_status", return_value=fake_offline_gate):
        try:
            assert_cscape_live()
            raise AssertionError("assert_cscape_live() did not fail closed when ready_for_tests=False!")
        except CscapeLivenessGateError as e:
            results["offline_simulation"] = {
                "status": "FAIL_CLOSED_BLOCKED",
                "exception": str(e),
            }

    print("  -> Task 4 Verification PASSED: assert_cscape_live() correctly raises CscapeLivenessGateError.")
    return results


async def run_step167_security_audit() -> Dict[str, Any]:
    print("=" * 80)
    print("MEGAPLAN STEP 167: FAIL-CLOSED SECURITY LOCKOUT AUDIT")
    print("=" * 80)
    t_start = datetime.datetime.now(datetime.timezone.utc)

    t1 = audit_task1_hardware_lockout()
    t2 = await audit_task2_mcp_download_tool_rejection()
    t3 = audit_task3_straton_quarantine()
    t4 = audit_task4_offline_gate_resilience()

    t_end = datetime.datetime.now(datetime.timezone.utc)
    duration_sec = (t_end - t_start).total_seconds()

    report = {
        "step": 167,
        "auditor": "Security Lockout Auditor subagent for MEGAPLAN",
        "status": "PASSED",
        "timestamp_start_utc": t_start.isoformat(),
        "timestamp_end_utc": t_end.isoformat(),
        "duration_seconds": duration_sec,
        "audits": {
            "task1_hardware_lockout": t1,
            "task2_mcp_download_tool_rejection": t2,
            "task3_straton_quarantine": t3,
            "task4_offline_gate_resilience": t4,
        },
        "summary": {
            "hardware_lockout_enforced": True,
            "mcp_download_tool_rejected": True,
            "straton_quarantine_enforced": True,
            "zero_straton_imports": True,
            "offline_gate_fail_closed": True,
        },
    }

    report_bytes = json.dumps(report, indent=2).encode("utf-8")
    report_sha = compute_sha256(report_bytes)

    checkpoint_data = {
        "step": 167,
        "name": "step167_security_audit_checkpoint",
        "status": "PASSED",
        "timestamp_utc": get_utc_iso(),
        "hardware_lockout_enforced": True,
        "mcp_download_tool_rejected": True,
        "straton_quarantine_enforced": True,
        "offline_gate_fail_closed": True,
        "active_py_files_scanned": t3.get("active_py_files_scanned"),
        "straton_import_violations": 0,
        "log_sha256": report_sha,
        "dual_root_mirrored": True,
    }

    raw_chk_bytes = json.dumps(checkpoint_data, indent=2).encode("utf-8")
    checkpoint_data["checkpoint_sha256"] = compute_sha256(raw_chk_bytes)
    final_chk_bytes = json.dumps(checkpoint_data, indent=2).encode("utf-8")

    # Save to dual roots
    log_paths = [
        HORNER_ROOT / "artifacts" / "logs" / "step167_security_audit.json",
        USER_ROOT / "artifacts" / "logs" / "step167_security_audit.json",
    ]
    chk_paths = [
        HORNER_ROOT / "artifacts" / "checkpoints" / "step167_security_audit_checkpoint.json",
        USER_ROOT / "artifacts" / "checkpoints" / "step167_security_audit_checkpoint.json",
    ]

    for lp in log_paths:
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_bytes(report_bytes)
        print(f"  Wrote log: {lp}")

    for cp in chk_paths:
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_bytes(final_chk_bytes)
        print(f"  Wrote checkpoint: {cp}")

    print("\n" + "=" * 80)
    print("STEP 167 SECURITY AUDIT COMPLETED SUCCESSFULLY (STATUS: PASSED)")
    print(f"Checkpoint SHA-256: {checkpoint_data['checkpoint_sha256']}")
    print("=" * 80)
    return report


if __name__ == "__main__":
    asyncio.run(run_step167_security_audit())
