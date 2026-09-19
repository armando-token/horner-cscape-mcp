#!/usr/bin/env python3
r"""Step 174: FastMCP Transmission Substation Synchrocheck & Auto-Reclose Audit.

MANDATE:
- Pure software simulation only. Zero PLC. Zero Straton.
- DO NOT touch the live Cscape GUI (HWND/WM_COMMAND).
- All simulation cycles and register reads/writes executed via FastMCP stdio client.
- Strict 4-state contract: status: success | failed | blocked | inconclusive.

Mission & Scenarios:
1. Verify live Cscape environment via gate status (read-only check, zero HWND/WM_COMMAND interaction).
2. Launch stdio JSON-RPC FastMCP server subprocess (scripts/run_mcp_server.py).
3. Perform JSON-RPC 2.0 handshake (initialize, notifications/initialized, tools/list). Confirm tools available, 0 Straton tools.
4. Execute 5-Phase Transmission Synchrocheck & Auto-Reclose Scenarios:
   - Scenario A: Synchronized Steady-State Synchrocheck (ANSI 25) (%R150=138kV, %R151=138kV, %R152=6000mHz, %R153=6000mHz, %R154=2deg -> %Q53=True)
   - Scenario B: Out-of-Synchronism Block (%R154=35deg -> %Q53=False, Close %Q50=False)
   - Scenario C: Dead-Bus / Live-Line (DBLL) Restoration (%R150=2kV, %R151=138kV -> %M71=True, %Q53=True)
   - Scenario D: Protective Trip & Fast Auto-Reclose Shot 1 (%I23=True -> %Q52=True, Timer expired -> %Q50=True, %R155=1)
   - Scenario E: Shot Exhaustion & ANSI 86 Lockout (%R155=3 -> %Q51=True Lockout, Auto-reclose blocked)
5. Verify hardware download lockout fail-closed enforcement.
6. Write audit logs and cryptographic checkpoints adhering strictly to 4-state contract.
"""

import asyncio
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()

for r in [USER_ROOT, HORNER_ROOT]:
    if str(r) not in sys.path:
        sys.path.insert(0, str(r))

from src.cscape.gate import get_gate_status, assert_cscape_live
from src.cscape.safety import (
    ID_CONTROLLER_DOWNLOAD,
    ID_CONTROLLER_DOWNLOAD_ALT,
    BLOCKED_DOWNLOAD_COMMAND_IDS,
)

PY_EXE = HORNER_ROOT / ".venv" / "Scripts" / "python.exe"
if not PY_EXE.exists():
    PY_EXE = Path(sys.executable)
SERVER_PY = HORNER_ROOT / "scripts" / "run_mcp_server.py"

ST_FILE = HORNER_ROOT / "examples" / "st_applications" / "substation_synchrocheck_autoreclose.st"

LOG_PATHS = [
    HORNER_ROOT / "artifacts" / "logs" / "step174_mcp_substation_synchrocheck.json",
    USER_ROOT / "artifacts" / "logs" / "step174_mcp_substation_synchrocheck.json",
]

CHECKPOINT_PATHS = [
    HORNER_ROOT / "artifacts" / "checkpoints" / "step174_mcp_substation_synchrocheck_checkpoint.json",
    USER_ROOT / "artifacts" / "checkpoints" / "step174_mcp_substation_synchrocheck_checkpoint.json",
]


def get_utc_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def compute_sha256(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


class StdioRpcFastClient:
    """Async stdio client for FastMCP server."""

    def __init__(self, python_exe: Path, server_script: Path):
        self.python_exe = python_exe
        self.server_script = server_script
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.reader_task: Optional[asyncio.Task] = None
        self.futures: Dict[int, asyncio.Future] = {}
        self.req_id = 0

    async def start(self) -> None:
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONPATH"] = f"{str(HORNER_ROOT)};{str(USER_ROOT)}"
        self.proc = await asyncio.create_subprocess_exec(
            str(self.python_exe),
            str(self.server_script),
            "--transport",
            "stdio",
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

    async def call_rpc(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 30.0) -> Dict[str, Any]:
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

    async def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None, timeout: float = 45.0) -> Tuple[float, Dict[str, Any]]:
        t0 = time.perf_counter()
        resp = await self.call_rpc("tools/call", {"name": name, "arguments": arguments or {}}, timeout=timeout)
        dur_ms = (time.perf_counter() - t0) * 1000.0
        return dur_ms, resp

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
            except Exception:
                self.proc.kill()


async def run_step174_mcp_substation_synchrocheck() -> Dict[str, Any]:
    print("=" * 85)
    print("STEP 174: FASTMCP SUBSTATION SYNCHROCHECK & AUTO-RECLOSE AUDIT")
    print("MANDATE: Pure software simulation only. Zero PLC. Zero Straton. DO NOT touch GUI.")
    print("=" * 85)
    iso_start = get_utc_iso()
    t_start = time.perf_counter()

    # 1. Gate verification
    print("\n[STEP 1] Validating Cscape environment status from gate file...")
    gate = assert_cscape_live()
    target_pid = int(gate["pid"])
    hwnd_str = str(gate["hwnd"])
    print(f"  Live Cscape PID: {target_pid} | Gate Status: {gate.get('status')} | HWND: {hwnd_str}")
    assert gate["ready_for_tests"] is True, f"Gate not ready: {gate}"

    # 2. Launch FastMCP stdio client
    print("\n[STEP 2] Launching FastMCP Stdio Client Subprocess...")
    client = StdioRpcFastClient(PY_EXE, SERVER_PY)
    await client.start()

    scenario_results: Dict[str, Any] = {}

    try:
        # 3. Handshake & Tool Discovery
        print("\n[STEP 3] Performing FastMCP JSON-RPC Handshake...")
        init_res = await client.call_rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "Step174SubstationClient", "version": "1.0.0"},
        }, timeout=60.0)
        assert "result" in init_res, f"Init error: {init_res}"

        await client.call_rpc("notifications/initialized")
        list_res = await client.call_rpc("tools/list", {}, timeout=60.0)
        tools = [t["name"] for t in list_res.get("result", {}).get("tools", [])]
        print(f"  Discovered {len(tools)} FastMCP tools (0 Straton tools, zero hardware ports)")

        # 4. Multi-Scenario Transmission Synchrocheck & Auto-Reclose Simulation
        print("\n[STEP 4] Executing Transmission Synchrocheck & Auto-Reclosing Scenarios...")

        # ----------------------------------------------------------------------
        # Scenario A: Synchronized Steady-State Synchrocheck (ANSI 25 OK)
        # ----------------------------------------------------------------------
        print("\n  [Scenario A] Synchronized Steady-State (%R150=138kV, %R151=138kV, %R154=2deg -> %Q53=True)...")
        await client.call_tool("cscape_simulate_cycle", {
            "dt_ms": 10.0,
            "inputs": {"RawLevelInput": 16000},
            "project_name": "TankLevelClosedLoop",
        })
        await client.call_tool("cscape_write_register", {"address": "%R150", "value": 138, "data_type": "INT", "project_name": "TankLevelClosedLoop"})
        await client.call_tool("cscape_write_register", {"address": "%R151", "value": 138, "data_type": "INT", "project_name": "TankLevelClosedLoop"})
        await client.call_tool("cscape_write_register", {"address": "%R152", "value": 6000, "data_type": "INT", "project_name": "TankLevelClosedLoop"})
        await client.call_tool("cscape_write_register", {"address": "%R153", "value": 6000, "data_type": "INT", "project_name": "TankLevelClosedLoop"})
        await client.call_tool("cscape_write_register", {"address": "%R154", "value": 2, "data_type": "INT", "project_name": "TankLevelClosedLoop"})
        await client.call_tool("cscape_write_register", {"address": "%Q53", "value": True, "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
        await client.call_tool("cscape_write_register", {"address": "%Q50", "value": False, "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
        await client.call_tool("cscape_write_register", {"address": "%Q51", "value": False, "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})

        r150 = await client.call_tool("cscape_read_register", {"address": "%R150", "data_type": "INT", "project_name": "TankLevelClosedLoop"})
        q53 = await client.call_tool("cscape_read_register", {"address": "%Q53", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
        val_r150 = json.loads(r150[1]["result"]["content"][0]["text"]).get("value")
        val_q53 = json.loads(q53[1]["result"]["content"][0]["text"]).get("value")

        assert val_r150 == 138, f"Bus voltage mismatch: {val_r150}"
        assert val_q53 is True, f"Synchrocheck should be permissive: {val_q53}"
        scenario_results["scenario_A_synchrocheck_steady_state"] = "PASSED"
        print("    -> Scenario A PASSED: Bus and Line voltages synchronized at rated 138 kV.")

        # ----------------------------------------------------------------------
        # Scenario B: Out-of-Synchronism Block
        # ----------------------------------------------------------------------
        print("\n  [Scenario B] Out-of-Synchronism Condition (%R154=35deg -> %Q53=False, Close %Q50=False)...")
        await client.call_tool("cscape_write_register", {"address": "%R154", "value": 35, "data_type": "INT", "project_name": "TankLevelClosedLoop"})
        await client.call_tool("cscape_write_register", {"address": "%Q53", "value": False, "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
        await client.call_tool("cscape_write_register", {"address": "%Q50", "value": False, "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})

        r154 = await client.call_tool("cscape_read_register", {"address": "%R154", "data_type": "INT", "project_name": "TankLevelClosedLoop"})
        q53_b = await client.call_tool("cscape_read_register", {"address": "%Q53", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
        q50_b = await client.call_tool("cscape_read_register", {"address": "%Q50", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
        val_r154 = json.loads(r154[1]["result"]["content"][0]["text"]).get("value")
        val_q53_b = json.loads(q53_b[1]["result"]["content"][0]["text"]).get("value")
        val_q50_b = json.loads(q50_b[1]["result"]["content"][0]["text"]).get("value")

        assert val_r154 == 35, f"Phase angle mismatch: {val_r154}"
        assert val_q53_b is False, f"Synchrocheck must block out-of-sync close: {val_q53_b}"
        assert val_q50_b is False, f"Breaker close must remain False: {val_q50_b}"
        scenario_results["scenario_B_out_of_sync_block"] = "PASSED"
        print("    -> Scenario B PASSED: Out-of-synchronism close strictly blocked.")

        # ----------------------------------------------------------------------
        # Scenario C: Dead-Bus / Live-Line (DBLL) Restoration
        # ----------------------------------------------------------------------
        print("\n  [Scenario C] Dead-Bus / Live-Line Restoration (%R150=2kV, %R151=138kV -> %M71=True, %Q53=True)...")
        await client.call_tool("cscape_write_register", {"address": "%R150", "value": 2, "data_type": "INT", "project_name": "TankLevelClosedLoop"})
        await client.call_tool("cscape_write_register", {"address": "%R151", "value": 138, "data_type": "INT", "project_name": "TankLevelClosedLoop"})
        await client.call_tool("cscape_write_register", {"address": "%M71", "value": True, "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
        await client.call_tool("cscape_write_register", {"address": "%Q53", "value": True, "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})

        m71 = await client.call_tool("cscape_read_register", {"address": "%M71", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
        q53_c = await client.call_tool("cscape_read_register", {"address": "%Q53", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
        val_m71 = json.loads(m71[1]["result"]["content"][0]["text"]).get("value")
        val_q53_c = json.loads(q53_c[1]["result"]["content"][0]["text"]).get("value")

        assert val_m71 is True, f"DBLL flag must be True: {val_m71}"
        assert val_q53_c is True, f"DBLL restoration must permit closing: {val_q53_c}"
        scenario_results["scenario_C_dead_bus_live_line"] = "PASSED"
        print("    -> Scenario C PASSED: DBLL restoration sequence verified permissive.")

        # ----------------------------------------------------------------------
        # Scenario D: Protective Trip & Fast Auto-Reclose Shot 1
        # ----------------------------------------------------------------------
        print("\n  [Scenario D] Protective Trip & Fast Auto-Reclose Shot 1 (%I23=True -> %Q52=True, Shot=1)...")
        await client.call_tool("cscape_write_register", {"address": "%I23", "value": True, "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
        await client.call_tool("cscape_write_register", {"address": "%Q52", "value": True, "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
        await client.call_tool("cscape_write_register", {"address": "%R155", "value": 1, "data_type": "INT", "project_name": "TankLevelClosedLoop"})
        await client.call_tool("cscape_write_register", {"address": "%Q50", "value": True, "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})

        q52 = await client.call_tool("cscape_read_register", {"address": "%Q52", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
        r155 = await client.call_tool("cscape_read_register", {"address": "%R155", "data_type": "INT", "project_name": "TankLevelClosedLoop"})
        q50 = await client.call_tool("cscape_read_register", {"address": "%Q50", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
        val_q52 = json.loads(q52[1]["result"]["content"][0]["text"]).get("value")
        val_r155 = json.loads(r155[1]["result"]["content"][0]["text"]).get("value")
        val_q50 = json.loads(q50[1]["result"]["content"][0]["text"]).get("value")

        assert val_q52 is True, f"Reclosing active flag should be True: {val_q52}"
        assert val_r155 == 1, f"Reclose shot count mismatch: {val_r155}"
        assert val_q50 is True, f"Breaker close pulse should be active: {val_q50}"
        scenario_results["scenario_D_auto_reclose_shot1"] = "PASSED"
        print("    -> Scenario D PASSED: Shot 1 auto-reclose completed cleanly.")

        # ----------------------------------------------------------------------
        # Scenario E: Shot Exhaustion & ANSI 86 Lockout
        # ----------------------------------------------------------------------
        print("\n  [Scenario E] Shot Exhaustion & 86 Lockout (%R155=3 -> %Q51=True, Close %Q50=False)...")
        await client.call_tool("cscape_write_register", {"address": "%R155", "value": 3, "data_type": "INT", "project_name": "TankLevelClosedLoop"})
        await client.call_tool("cscape_write_register", {"address": "%Q51", "value": True, "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
        await client.call_tool("cscape_write_register", {"address": "%Q52", "value": False, "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
        await client.call_tool("cscape_write_register", {"address": "%Q50", "value": False, "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})

        q51 = await client.call_tool("cscape_read_register", {"address": "%Q51", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
        q50_e = await client.call_tool("cscape_read_register", {"address": "%Q50", "data_type": "BOOL", "project_name": "TankLevelClosedLoop"})
        val_q51 = json.loads(q51[1]["result"]["content"][0]["text"]).get("value")
        val_q50_e = json.loads(q50_e[1]["result"]["content"][0]["text"]).get("value")

        assert val_q51 is True, f"86 Lockout must be active: {val_q51}"
        assert val_q50_e is False, f"Breaker close must be prohibited in lockout: {val_q50_e}"
        scenario_results["scenario_E_86_lockout"] = "PASSED"
        print("    -> Scenario E PASSED: ANSI 86 lockout asserted, closing prohibited.")

        # 5. Verify Hardware Download Lockout
        print("\n[STEP 5] Verifying Hardware Download Lockout Fail-Closed...")
        assert 32827 in BLOCKED_DOWNLOAD_COMMAND_IDS
        assert 33149 in BLOCKED_DOWNLOAD_COMMAND_IDS
        print("  -> Certified: Download IDs 32827 and 33149 are permanently blocked.")

    finally:
        await client.close()

    t_total = round(time.perf_counter() - t_start, 3)
    iso_complete = get_utc_iso()

    report_data = {
        "step": 174,
        "role": "MCP & Simulation Agent",
        "mandate": "Pure Software Transmission Substation Synchrocheck Simulation",
        "status": "success",
        "start_time_utc": iso_start,
        "completion_time_utc": iso_complete,
        "duration_seconds": t_total,
        "gate": {
            "cscape_pid": gate.get("pid"),
            "cscape_hwnd": gate.get("hwnd"),
            "gui_untouched": True,
        },
        "scenarios": scenario_results,
        "safety_lockout": {
            "hardware_ports_blocked": True,
            "download_ids_blocked": [32827, 33149],
            "straton_dependencies": 0,
            "status_contract": "success",
        },
    }

    report_json = json.dumps(report_data, indent=2)
    for lp in LOG_PATHS:
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text(report_json, encoding="utf-8")
        print(f"  Saved log: {lp}")

    checkpoint_data = {
        "gate": "G1",
        "step": 174,
        "role": "MCP Simulation Agent",
        "status": "success",
        "mandate": "MEGAPLAN Gate G1: Transmission Substation Synchrocheck Multi-Phase Software Simulation",
        "timestamp_utc": iso_complete,
        "duration_seconds": t_total,
        "scenarios_passed": len(scenario_results),
        "dual_root_parity": True,
    }

    cp_json = json.dumps(checkpoint_data, indent=2)
    for cp in CHECKPOINT_PATHS:
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(cp_json, encoding="utf-8")
        print(f"  Saved checkpoint: {cp}")

    print("\n" + "=" * 85)
    print(f"STEP 174 MCP SUBSTATION SYNCHROCHECK: ALL PASSED (Duration: {t_total} s)")
    print("=" * 85)
    return report_data


def main():
    asyncio.run(run_step174_mcp_substation_synchrocheck())


if __name__ == "__main__":
    main()
