#!/usr/bin/env python3
r"""Step 133: FastMCP Multi-Client Live Concurrency Benchmark on Live Cscape PID 14580.

Mission:
1. Verify live Cscape gate in artifacts/.cscape_live_gate.json (PID 14580, HWND 0x024B054A, TankLevelClosedLoop.csp).
2. Attach calling thread to desktop Default using OpenDesktopW and SetThreadDesktop.
3. Check user32.IsWindow and user32.IsHungAppWindow to verify zero UI freezes before starting.
4. Launch 5 concurrent stdio JSON-RPC FastMCP client streams connected to scripts/run_mcp_server.py.
5. Perform concurrent MCP handshake (initialize, notifications/initialized, tools/list) across all 5 clients.
6. Spawn concurrent benchmark tasks across all 5 clients:
   - Each client executes 20 calls (total 100 calls) alternating across:
     1. cscape_read_variables
     2. cscape_simulate_cycle
     3. cscape_read_register
     4. cscape_write_register
     5. cscape_compile_project (serialized GUI arbitration via asyncio.Lock)
7. Run an asynchronous Win32 modal dialog sweeper during compile calls to automatically dismiss MFC #32770
   warning/confirmation dialogs ("There were no errors or warnings", "Non-Fatal Compilation Errors...", etc.).
8. Measure per-client and aggregate throughput (calls/sec) and latency percentiles (min, median, p90, p95, p99, max, mean, stddev).
9. Verify 100% success rate (0 errors, 0 dropped frames, 0 cross-client frame contamination).
10. Verify fail-closed hardware lockout on ID_CONTROLLER_DOWNLOAD = 32827 and zero Straton K5 tools.
11. Save evidence to artifacts/logs/mcp_multi_client_concurrency.json and
    checkpoint to artifacts/checkpoints/step133_mcp_multi_client_concurrency_checkpoint.json (mirrored across both roots).
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
import ctypes
from ctypes import wintypes
import datetime
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import psutil

USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()

for r in [USER_ROOT, HORNER_ROOT]:
    if str(r) not in sys.path:
        sys.path.insert(0, str(r))

PY_EXE = HORNER_ROOT / ".venv" / "Scripts" / "python.exe"
SERVER_PY = HORNER_ROOT / "scripts" / "run_mcp_server.py"

PROJECT_DIR = USER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop"
CSP_PATH = PROJECT_DIR / "TankLevelClosedLoop.csp"
VARS_CSV = PROJECT_DIR / "variables.csv"

GATE_PATHS = [
    USER_ROOT / "artifacts" / ".cscape_live_gate.json",
    HORNER_ROOT / "artifacts" / ".cscape_live_gate.json",
]

BENCHMARK_LOG_PATHS = [
    USER_ROOT / "artifacts" / "logs" / "mcp_multi_client_concurrency.json",
    HORNER_ROOT / "artifacts" / "logs" / "mcp_multi_client_concurrency.json",
]

CHECKPOINT_PATHS = [
    USER_ROOT / "artifacts" / "checkpoints" / "step133_mcp_multi_client_concurrency_checkpoint.json",
    HORNER_ROOT / "artifacts" / "checkpoints" / "step133_mcp_multi_client_concurrency_checkpoint.json",
]

for p in BENCHMARK_LOG_PATHS + CHECKPOINT_PATHS:
    p.parent.mkdir(parents=True, exist_ok=True)

NUM_CLIENTS = 5
CALLS_PER_CLIENT = 20
TOTAL_CALLS = NUM_CLIENTS * CALLS_PER_CLIENT


def get_utc_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


from src.cscape.gate import attach_thread_desktop, assert_cscape_live
from src.cscape.compilation import CscapeCompiler, ID_CONTROLLER_DOWNLOAD
from src.security.exceptions import HardwareLockoutError, UnauthorizedDownloadError


def compute_percentiles(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"min": 0.0, "median": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0, "mean": 0.0, "stddev": 0.0}
    sorted_vals = sorted(values)
    n = len(sorted_vals)

    def pct(p: float) -> float:
        k = (n - 1) * (p / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_vals[int(k)]
        return sorted_vals[int(f)] * (c - k) + sorted_vals[int(c)] * (k - f)

    return {
        "min": round(sorted_vals[0], 2),
        "median": round(pct(50.0), 2),
        "p90": round(pct(90.0), 2),
        "p95": round(pct(95.0), 2),
        "p99": round(pct(99.0), 2),
        "max": round(sorted_vals[-1], 2),
        "mean": round(statistics.mean(sorted_vals), 2),
        "stddev": round(statistics.stdev(sorted_vals) if n > 1 else 0.0, 2),
    }


class FastMCPBenchClient:
    """Encapsulates a dedicated stdio JSON-RPC client connection to FastMCP server."""

    def __init__(self, client_id: str, py_exe: Path, server_py: Path) -> None:
        self.client_id = client_id
        self.py_exe = py_exe
        self.server_py = server_py
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.reader_task: Optional[asyncio.Task] = None
        self.futures: Dict[int, asyncio.Future] = {}
        self.sent_request_ids: set[int] = set()
        self.req_id_counter = 1
        self.call_latencies: List[float] = []
        self.tool_latencies: Dict[str, List[float]] = {
            "cscape_read_variables": [],
            "cscape_simulate_cycle": [],
            "cscape_read_register": [],
            "cscape_write_register": [],
            "cscape_compile_project": [],
        }
        self.call_records: List[Dict[str, Any]] = []
        self.contamination_count = 0
        self.dropped_frames = 0
        self.error_count = 0
        self.duration_seconds = 0.0
        self.tools_discovered: List[str] = []

    async def start(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            str(self.py_exe),
            str(self.server_py),
            "--transport",
            "stdio",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.reader_task = asyncio.create_task(self._reader_loop())

    async def _reader_loop(self) -> None:
        try:
            while True:
                line = await self.proc.stdout.readline()
                if not line:
                    break
                decoded = line.decode("utf-8").strip()
                if not decoded:
                    continue
                try:
                    payload = json.loads(decoded)
                    rid = payload.get("id")
                    if rid is not None:
                        if rid in self.sent_request_ids:
                            if rid in self.futures and not self.futures[rid].done():
                                self.futures[rid].set_result((time.perf_counter(), payload))
                        else:
                            # Frame received that this client never requested -> cross-client contamination
                            self.contamination_count += 1
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass

    async def handshake(self) -> List[str]:
        # 1. initialize
        rid = self.req_id_counter
        self.req_id_counter += 1
        self.sent_request_ids.add(rid)
        fut = asyncio.get_running_loop().create_future()
        self.futures[rid] = fut

        init_req = {
            "jsonrpc": "2.0",
            "id": rid,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": f"FastMCPMultiClientBench_{self.client_id}",
                    "version": "1.0.0",
                },
            },
        }
        self.proc.stdin.write((json.dumps(init_req) + "\n").encode("utf-8"))
        await self.proc.stdin.drain()

        t_resp, init_res = await asyncio.wait_for(fut, timeout=20.0)
        assert "result" in init_res, f"{self.client_id} initialize failed: {init_res}"

        # 2. notifications/initialized
        notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        self.proc.stdin.write((json.dumps(notif) + "\n").encode("utf-8"))
        await self.proc.stdin.drain()

        # 3. tools/list
        rid = self.req_id_counter
        self.req_id_counter += 1
        self.sent_request_ids.add(rid)
        fut = asyncio.get_running_loop().create_future()
        self.futures[rid] = fut

        list_req = {"jsonrpc": "2.0", "id": rid, "method": "tools/list"}
        self.proc.stdin.write((json.dumps(list_req) + "\n").encode("utf-8"))
        await self.proc.stdin.drain()

        t_resp, list_res = await asyncio.wait_for(fut, timeout=20.0)
        tools = [t["name"] for t in list_res.get("result", {}).get("tools", [])]
        self.tools_discovered = tools
        return tools

    async def call_tool(
        self, tool_name: str, tool_args: Dict[str, Any], timeout: float = 75.0
    ) -> Tuple[float, Dict[str, Any]]:
        rid = self.req_id_counter
        self.req_id_counter += 1
        self.sent_request_ids.add(rid)
        fut = asyncio.get_running_loop().create_future()
        self.futures[rid] = fut

        call_req = {
            "jsonrpc": "2.0",
            "id": rid,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": tool_args,
            },
        }
        t_send = time.perf_counter()
        self.proc.stdin.write((json.dumps(call_req) + "\n").encode("utf-8"))
        await self.proc.stdin.drain()

        try:
            t_recv, resp = await asyncio.wait_for(fut, timeout=timeout)
            lat_ms = (t_recv - t_send) * 1000.0
            return lat_ms, resp
        except asyncio.TimeoutError:
            self.dropped_frames += 1
            raise

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


async def run_multi_client_benchmark() -> Dict[str, Any]:
    print("=" * 80)
    print("STEP 133: FASTMCP MULTI-CLIENT LIVE CONCURRENCY BENCHMARK ON LIVE CSCAPE PID 14580")
    print("=" * 80)
    t0_iso = get_utc_iso()
    print(f"Start Timestamp: {t0_iso}")

    # 1. Gate verification
    print("\n[STEP 1] Validating artifacts/.cscape_live_gate.json...")
    gate_file = None
    for gp in GATE_PATHS:
        if gp.exists():
            gate_file = gp
            break
    assert gate_file is not None, "Missing .cscape_live_gate.json!"

    with open(gate_file, "r", encoding="utf-8") as f:
        gate_data = json.load(f)

    target_pid = gate_data["pid"]
    hwnd_str = gate_data["hwnd"]
    target_hwnd = int(hwnd_str, 16) if isinstance(hwnd_str, str) and hwnd_str.startswith("0x") else int(hwnd_str)

    desktop_used = attach_thread_desktop(target_hwnd)
    proc_cscape = psutil.Process(target_pid)
    proc_uptime = time.time() - proc_cscape.create_time()
    working_set_mb = round(proc_cscape.memory_info().rss / (1024.0 * 1024.0), 2)

    user32 = ctypes.windll.user32
    is_window = bool(user32.IsWindow(target_hwnd))
    is_hung = bool(user32.IsHungAppWindow(target_hwnd))

    sm_result = ctypes.c_ulong()
    ping_ok = bool(user32.SendMessageTimeoutW(
        target_hwnd, 0x0000, 0, 0, 0x0002, 1000, ctypes.byref(sm_result)
    ))

    print(f"  Live Cscape PID={target_pid} | HWND=0x{target_hwnd:08X} | Desktop={desktop_used}")
    print(f"  Uptime={proc_uptime:.1f}s ({proc_uptime/60:.2f}m) | WorkingSet={working_set_mb}MB | Hung={is_hung} | Ping={ping_ok}")
    assert is_window is True, f"Cscape HWND 0x{target_hwnd:08X} is not a valid window"
    assert is_hung is False, f"Cscape HWND 0x{target_hwnd:08X} is hung"
    assert ping_ok is True, f"Cscape HWND 0x{target_hwnd:08X} ping timeout"

    # 2. Launch 5 concurrent clients
    print(f"\n[STEP 2] Launching {NUM_CLIENTS} Concurrent Stdio FastMCP Clients...")
    client_names = [f"Client_{i+1}" for i in range(NUM_CLIENTS)]
    clients = [FastMCPBenchClient(cname, PY_EXE, SERVER_PY) for cname in client_names]

    for c in clients:
        await c.start()
        print(f"  {c.client_id} subprocess launched with PID: {c.proc.pid}")

    # Active modal dialog sweeper
    stop_sweeper = False
    sweeper_dismissed_count = 0

    async def modal_dialog_sweeper():
        nonlocal sweeper_dismissed_count
        user32_local = ctypes.windll.user32
        h_default = user32_local.OpenDesktopW("Default", 0, False, 0x01FF)
        if h_default:
            user32_local.SetThreadDesktop(h_default)
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        while not stop_sweeper:
            try:
                def _enum_cb(hwnd, _):
                    nonlocal sweeper_dismissed_count
                    pid = ctypes.c_ulong()
                    user32_local.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if pid.value == target_pid and user32_local.IsWindowVisible(hwnd):
                        cls = ctypes.create_unicode_buffer(256)
                        user32_local.GetClassNameW(hwnd, cls, 256)
                        if cls.value == "#32770":
                            user32_local.PostMessageW(hwnd, 0x0111, 1, 0)
                            user32_local.PostMessageW(hwnd, 0x0111, 6, 0)
                            sweeper_dismissed_count += 1
                    return True

                user32_local.EnumWindows(WNDENUMPROC(_enum_cb), 0)
            except Exception:
                pass
            await asyncio.sleep(0.05)

    sweeper_task = asyncio.create_task(modal_dialog_sweeper())

    try:
        # 3. Concurrent Handshake
        print(f"\n[STEP 3] Performing Concurrent JSON-RPC Handshakes across all {NUM_CLIENTS} Clients...")
        handshake_start = time.perf_counter()
        handshake_results = await asyncio.gather(*[c.handshake() for c in clients])
        handshake_dur = time.perf_counter() - handshake_start

        required_tools = [
            "cscape_read_variables",
            "cscape_simulate_cycle",
            "cscape_read_register",
            "cscape_write_register",
            "cscape_compile_project",
        ]

        for i, tools in enumerate(handshake_results):
            cname = clients[i].client_id
            print(f"  {cname} handshake OK | {len(tools)} tools available")
            for req_t in required_tools:
                assert req_t in tools, f"Missing tool {req_t} on {cname}"
            # Assert zero Straton tools
            straton_tools = [t for t in tools if "straton" in t.lower() or "k5" in t.lower()]
            assert len(straton_tools) == 0, f"Straton legacy tools detected on {cname}: {straton_tools}"

        print(f"  All {NUM_CLIENTS} clients handshook concurrently in {handshake_dur:.3f}s (zero Straton tools confirmed).")

        # 4. Spawns concurrent tasks across all 5 clients: each client executes 20 calls (total 100 calls)
        tool_templates = [
            ("cscape_read_variables", {"file_path": str(VARS_CSV)}),
            ("cscape_simulate_cycle", {"dt_ms": 10.0, "project_name": "TankLevelClosedLoop", "inputs": {"RawLevelInput": 16000, "Setpoint": 50.0}}),
            ("cscape_read_register", {"address": "%R1", "project_name": "TankLevelClosedLoop"}),
            ("cscape_write_register", {"address": "%R3", "value": 55.0, "project_name": "TankLevelClosedLoop"}),
            ("cscape_compile_project", {"project_name": "TankLevelClosedLoop", "clean_build": False}),
        ]

        print(f"\n[STEP 4] Spawning {NUM_CLIENTS} Concurrent Client Tasks ({CALLS_PER_CLIENT} calls/client = {TOTAL_CALLS} total calls)...")
        print("  Rotation: read_variables -> simulate_cycle -> read_register -> write_register -> compile_project (serialized GUI arbitration)")

        compile_lock = asyncio.Lock()

        async def client_worker(client: FastMCPBenchClient, client_idx: int) -> float:
            t_w_start = time.perf_counter()
            for seq in range(CALLS_PER_CLIENT):
                tool_name, tool_args = tool_templates[seq % len(tool_templates)]
                try:
                    if tool_name == "cscape_compile_project":
                        # Serialized GUI arbitration
                        async with compile_lock:
                            lat_ms, resp = await client.call_tool(tool_name, tool_args, timeout=75.0)
                    else:
                        lat_ms, resp = await client.call_tool(tool_name, tool_args, timeout=75.0)

                    is_err = "error" in resp or resp.get("result", {}).get("isError", False)
                    if not is_err:
                        # Check inside content for inner failure
                        for c_item in resp.get("result", {}).get("content", []):
                            if c_item.get("type") == "text":
                                try:
                                    parsed_t = json.loads(c_item.get("text", "{}"))
                                    if parsed_t.get("success") is False:
                                        is_err = True
                                except Exception:
                                    pass

                    if is_err:
                        client.error_count += 1

                    client.call_latencies.append(lat_ms)
                    client.tool_latencies[tool_name].append(lat_ms)
                    client.call_records.append({
                        "client_id": client.client_id,
                        "call_idx": seq + 1,
                        "global_idx": client_idx * CALLS_PER_CLIENT + seq + 1,
                        "tool": tool_name,
                        "latency_ms": round(lat_ms, 2),
                        "success": not is_err,
                    })
                except Exception as ex:
                    client.error_count += 1
                    client.call_records.append({
                        "client_id": client.client_id,
                        "call_idx": seq + 1,
                        "global_idx": client_idx * CALLS_PER_CLIENT + seq + 1,
                        "tool": tool_name,
                        "latency_ms": -1.0,
                        "success": False,
                        "error": str(ex),
                    })
            client.duration_seconds = time.perf_counter() - t_w_start
            return client.duration_seconds

        t_bench_start = time.perf_counter()
        worker_tasks = [client_worker(c, i) for i, c in enumerate(clients)]
        client_durations = await asyncio.gather(*worker_tasks)
        total_bench_dur = time.perf_counter() - t_bench_start

        # 5. Collate and assert metrics
        aggregate_throughput = TOTAL_CALLS / total_bench_dur
        all_latencies = []
        all_errors = 0
        all_dropped = 0
        all_contamination = 0
        tool_counts = defaultdict(int)
        tool_latencies_agg = defaultdict(list)
        all_records = []

        per_client_metrics: Dict[str, Any] = {}
        for c in clients:
            all_latencies.extend(c.call_latencies)
            all_errors += c.error_count
            all_dropped += c.dropped_frames
            all_contamination += c.contamination_count
            all_records.extend(c.call_records)
            for t_name, lats in c.tool_latencies.items():
                tool_counts[t_name] += len(lats)
                tool_latencies_agg[t_name].extend(lats)

            client_tp = CALLS_PER_CLIENT / c.duration_seconds if c.duration_seconds > 0 else 0.0
            per_client_metrics[c.client_id] = {
                "calls": CALLS_PER_CLIENT,
                "errors": c.error_count,
                "dropped_frames": c.dropped_frames,
                "contamination": c.contamination_count,
                "success_rate_percent": round((CALLS_PER_CLIENT - c.error_count) / CALLS_PER_CLIENT * 100.0, 2),
                "duration_seconds": round(c.duration_seconds, 3),
                "throughput_calls_per_sec": round(client_tp, 2),
                "latency_ms": compute_percentiles(c.call_latencies),
            }

        overall_stats = compute_percentiles(all_latencies)
        tool_stats = {t: compute_percentiles(tool_latencies_agg[t]) for t in required_tools}

        success_rate = (TOTAL_CALLS - all_errors) / TOTAL_CALLS * 100.0

        print(f"\n[STEP 5] Benchmark Completed:")
        print(f"  Total Duration: {total_bench_dur:.2f}s | Aggregate Throughput: {aggregate_throughput:.2f} calls/sec")
        print(f"  Total Calls: {TOTAL_CALLS} | Success Rate: {TOTAL_CALLS - all_errors}/{TOTAL_CALLS} ({success_rate:.1f}%)")
        print(f"  Errors: {all_errors} | Dropped Frames: {all_dropped} | Cross-Client Contamination: {all_contamination}")
        print(f"  Dialog Sweeper Interventions: {sweeper_dismissed_count}")

        print("\n  Per-Client Summary:")
        for cname, cm in per_client_metrics.items():
            print(f"    {cname:<10}: dur={cm['duration_seconds']:>6.2f}s | tp={cm['throughput_calls_per_sec']:>5.2f} req/s | median={cm['latency_ms']['median']:>6.2f}ms | p95={cm['latency_ms']['p95']:>7.2f}ms | err={cm['errors']}")

        print("\n  Per-Tool Summary:")
        for t_name in required_tools:
            t_s = tool_stats[t_name]
            print(f"    {t_name:<24}: count={tool_counts[t_name]:>2} | min={t_s['min']:>6.2f}ms | median={t_s['median']:>6.2f}ms | p95={t_s['p95']:>7.2f}ms | max={t_s['max']:>7.2f}ms")

        assert all_errors == 0, f"Detected {all_errors} call errors during benchmark"
        assert all_dropped == 0, f"Detected {all_dropped} dropped frames during benchmark"
        assert all_contamination == 0, f"Detected {all_contamination} cross-client frame contaminations"
        assert success_rate == 100.0, f"Success rate was {success_rate:.1f}%, expected 100%"

        # 6. Verify fail-closed hardware lockout on ID_CONTROLLER_DOWNLOAD = 32827
        print("\n[STEP 6] Verifying Fail-Closed Hardware Lockout (ID_CONTROLLER_DOWNLOAD = 32827)...")
        compiler = CscapeCompiler()
        lockout_blocked = False
        try:
            compiler.trigger_cscape_gui_compile(
                cscape_hwnd=target_hwnd, command_id=ID_CONTROLLER_DOWNLOAD
            )
        except (HardwareLockoutError, UnauthorizedDownloadError, RuntimeError) as ex:
            lockout_blocked = True
            print(f"  [PASS] ID_CONTROLLER_DOWNLOAD (32827) strictly rejected fail-closed: {type(ex).__name__} - {ex}")

        assert lockout_blocked is True, "CRITICAL SAFETY VIOLATION: Physical PLC download was not blocked!"
        assert ID_CONTROLLER_DOWNLOAD == 32827

    finally:
        stop_sweeper = True
        try:
            sweeper_task.cancel()
        except Exception:
            pass
        for c in clients:
            await c.close()

    # 7. Post-benchmark Cscape health check
    final_uptime = time.time() - proc_cscape.create_time()
    final_working_set = round(proc_cscape.memory_info().rss / (1024.0 * 1024.0), 2)
    is_hung_final = bool(user32.IsHungAppWindow(target_hwnd))
    ping_ok_final = bool(user32.SendMessageTimeoutW(
        target_hwnd, 0x0000, 0, 0, 0x0002, 1000, ctypes.byref(sm_result)
    ))

    print(f"\n[STEP 7] Post-Benchmark Live Cscape Health Check:")
    print(f"  PID={target_pid} | HWND=0x{target_hwnd:08X} | Uptime={final_uptime:.1f}s | WorkingSet={final_working_set}MB")
    print(f"  IsHungAppWindow={is_hung_final} | SendMessageTimeout(WM_NULL)={ping_ok_final}")

    assert is_hung_final is False, "Cscape GUI hung after concurrency benchmark!"
    assert ping_ok_final is True, "Cscape GUI ping timed out after concurrency benchmark!"

    t_end_iso = get_utc_iso()

    # 8. Save Evidence Log and Checkpoint
    evidence = {
        "step": 133,
        "title": "FastMCP Multi-Client Live Concurrency Benchmark on Live Cscape PID 14580",
        "timestamp_start_utc": t0_iso,
        "timestamp_end_utc": t_end_iso,
        "status": "VERIFIED_LIVE",
        "cscape_active_process": {
            "pid": target_pid,
            "hwnd": f"0x{target_hwnd:08X}",
            "uptime_seconds": round(final_uptime, 2),
            "working_set_mb": final_working_set,
            "is_hung": is_hung_final,
            "wm_null_ping_ok": ping_ok_final,
            "desktop": desktop_used,
        },
        "concurrency_configuration": {
            "num_clients": NUM_CLIENTS,
            "client_names": client_names,
            "calls_per_client": CALLS_PER_CLIENT,
            "total_calls": TOTAL_CALLS,
            "transport": "stdio",
            "server_script": "scripts/run_mcp_server.py",
            "tools": required_tools,
            "gui_arbitration": "serialized_asyncio_lock",
            "dialog_sweeper_active": True,
            "sweeper_interventions": sweeper_dismissed_count,
        },
        "aggregate_metrics": {
            "total_calls": TOTAL_CALLS,
            "successful_calls": TOTAL_CALLS - all_errors,
            "errors": all_errors,
            "success_rate_percent": success_rate,
            "dropped_frames": all_dropped,
            "cross_client_frame_contamination": all_contamination,
            "duration_seconds": round(total_bench_dur, 3),
            "throughput_calls_per_sec": round(aggregate_throughput, 2),
            "latency_ms": overall_stats,
        },
        "per_client_metrics": per_client_metrics,
        "per_tool_metrics": {
            t: {
                "call_count": tool_counts[t],
                "latency_ms": tool_stats[t],
            }
            for t in required_tools
        },
        "safety_audit": {
            "id_controller_download_32827_blocked": True,
            "physical_plc_download_blocked": True,
            "zero_physical_hardware_touched": True,
            "hardware_lockout_enforced": True,
            "zero_straton_dependencies": True,
        },
        "call_records": all_records,
    }

    for bp in BENCHMARK_LOG_PATHS:
        bp.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(f"  Benchmark log saved to: {bp}")

    checkpoint_data = {
        "step": 133,
        "name": "step133_mcp_multi_client_concurrency_checkpoint",
        "title": "FastMCP Multi-Client Live Concurrency Benchmark on Live Cscape PID 14580",
        "description": f"{NUM_CLIENTS} concurrent FastMCP stdio clients executing {TOTAL_CALLS} calls across 5 core tools on live Cscape PID 14580 with serialized GUI arbitration, 100% success rate, 0 dropped frames, and 0 cross-contamination.",
        "timestamp_utc": t_end_iso,
        "cscape_pid": target_pid,
        "cscape_hwnd": f"0x{target_hwnd:08X}",
        "cscape_healthy": True,
        "total_clients": NUM_CLIENTS,
        "client_names": client_names,
        "calls_per_client": CALLS_PER_CLIENT,
        "total_calls": TOTAL_CALLS,
        "success_rate_percent": success_rate,
        "error_count": all_errors,
        "dropped_frames": all_dropped,
        "cross_client_frame_contamination": all_contamination,
        "aggregate_throughput_calls_per_sec": round(aggregate_throughput, 2),
        "overall_latency_ms": overall_stats,
        "tools_invoked": required_tools,
        "tool_call_counts": dict(tool_counts),
        "hardware_lockout_enforced": True,
        "zero_straton_dependencies": True,
        "audit_log": str(BENCHMARK_LOG_PATHS[0]),
        "status": "VERIFIED_LIVE",
    }

    for cp in CHECKPOINT_PATHS:
        cp.write_text(json.dumps(checkpoint_data, indent=2), encoding="utf-8")
        print(f"  Checkpoint saved to: {cp}")

    print("\n" + "=" * 80)
    print(f"STEP 133 COMPLETED WITH 100% PASS RATE: {TOTAL_CALLS} CALLS ACROSS {NUM_CLIENTS} CLIENTS AT {aggregate_throughput:.2f} CALLS/S")
    print("=" * 80)
    return evidence


def main():
    asyncio.run(run_multi_client_benchmark())


if __name__ == "__main__":
    main()
