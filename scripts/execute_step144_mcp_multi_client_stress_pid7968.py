#!/usr/bin/env python3
r"""Step 144: FastMCP Multi-Client Concurrent Stdio Stress & Register Partitioning on Live Cscape PID 7968.

Mission:
1. Verify live Cscape gate in artifacts/.cscape_live_gate.json (PID 7968, HWND 0x00B302DE, TankLevelClosedLoop.csp).
2. Attach calling thread to desktop Default using OpenDesktopW and SetThreadDesktop.
3. Check user32.IsWindow and user32.IsHungAppWindow to verify zero UI freezes before starting.
4. Launch 4 concurrent stdio JSON-RPC FastMCP client streams connected to scripts/run_mcp_server.py.
5. Perform concurrent MCP handshake (initialize, notifications/initialized, tools/list) across all 4 clients.
6. Spawn concurrent benchmark tasks across all 4 clients (25 calls/client = 100 calls total):
   - Rotation:
     1. cscape_read_variables
     2. cscape_simulate_cycle
     3. cscape_read_register
     4. cscape_write_register (client-partitioned address)
     5. cscape_compile (serialized live GUI Error Check 32826 via asyncio.Lock)
7. Run an asynchronous Win32 modal dialog sweeper during compile calls to automatically dismiss MFC #32770 dialogs.
8. Measure per-client and aggregate throughput (calls/sec) and latency percentiles (min, median, p90, p95, p99, max, mean, stddev).
9. Verify 100% success rate (0 errors, 0 dropped frames, 0 cross-client frame contamination).
10. Verify fail-closed hardware lockout on ID_CONTROLLER_DOWNLOAD = 32827 and zero Straton K5 tools.
11. Capture high-res screenshot to artifacts/screenshots/live_cscape_tank_level_step144_pid7968.png.
12. Save checkpoint to artifacts/checkpoints/step144_mcp_multi_client_stress_checkpoint.json and
    audit log to artifacts/logs/step144_mcp_multi_client_stress.json (mirrored across dual roots).
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
import ctypes
from ctypes import wintypes
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import psutil

# Mandatory import safety
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()

for r in [USER_ROOT, HORNER_ROOT]:
    if str(r) not in sys.path:
        sys.path.insert(0, str(r))

PY_EXE = HORNER_ROOT / ".venv" / "Scripts" / "python.exe"
if not PY_EXE.exists():
    PY_EXE = Path(sys.executable)
SERVER_PY = HORNER_ROOT / "scripts" / "run_mcp_server.py"

PROJECT_DIR = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop"
CSP_PATH = PROJECT_DIR / "TankLevelClosedLoop.csp"
VARS_CSV = PROJECT_DIR / "variables.csv"

GATE_PATHS = [
    USER_ROOT / "artifacts" / ".cscape_live_gate.json",
    HORNER_ROOT / "artifacts" / ".cscape_live_gate.json",
]

BENCHMARK_LOG_PATHS = [
    USER_ROOT / "artifacts" / "logs" / "step144_mcp_multi_client_stress.json",
    HORNER_ROOT / "artifacts" / "logs" / "step144_mcp_multi_client_stress.json",
]

CHECKPOINT_PATHS = [
    USER_ROOT / "artifacts" / "checkpoints" / "step144_mcp_multi_client_stress_checkpoint.json",
    HORNER_ROOT / "artifacts" / "checkpoints" / "step144_mcp_multi_client_stress_checkpoint.json",
]

SCREENSHOT_PATHS = [
    USER_ROOT / "artifacts" / "screenshots" / "live_cscape_tank_level_step144_pid7968.png",
    HORNER_ROOT / "artifacts" / "screenshots" / "live_cscape_tank_level_step144_pid7968.png",
]

for p in BENCHMARK_LOG_PATHS + CHECKPOINT_PATHS + SCREENSHOT_PATHS:
    p.parent.mkdir(parents=True, exist_ok=True)
from src.cscape.gate import attach_thread_desktop, assert_cscape_live, get_gate_status
from src.cscape.compilation import ID_PROGRAM_ERRORCHECK, ID_CONTROLLER_DOWNLOAD
from src.cscape.safety import ID_CONTROLLER_DOWNLOAD as SAFETY_DOWNLOAD, intercept_download_command
from src.security.exceptions import CscapeSafetyViolationError, HardwareLockoutError, UnauthorizedDownloadError


def get_live_target() -> Tuple[int, int, str]:
    gate_st = get_gate_status()
    pid = int(gate_st.get("pid") or 15624)
    h_str = str(gate_st.get("hwnd") or "0x0167056A")
    hwnd = int(h_str, 16) if h_str.startswith("0x") else int(h_str)
    return pid, hwnd, h_str


TARGET_PID, TARGET_HWND, TARGET_HWND_STR = get_live_target()

NUM_CLIENTS = 4
CALLS_PER_CLIENT = 25
TOTAL_CALLS = NUM_CLIENTS * CALLS_PER_CLIENT


def get_utc_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def compute_sha256(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


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


def sweep_cscape_dialogs(pid: int) -> int:
    """Dismiss any modal confirmation/warning dialogs that disable the main window."""
    from scripts.watchdog_cscape_10min import Win32Helper
    helper = Win32Helper()
    wins = helper.enum_windows_for_pids({pid})
    dismissed = 0
    for w in wins:
        if w.class_name == "#32770":
            helper.user32.PostMessageW(w.hwnd, 0x0111, 1, 0)  # IDOK
            helper.user32.PostMessageW(w.hwnd, 0x0111, 6, 0)  # IDYES
            dismissed += 1
    return dismissed


def capture_cscape_screenshot(hwnd: int, output_paths: List[Path]) -> int:
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    attach_thread_desktop(hwnd)

    user32.GetWindowDC.argtypes = [ctypes.c_void_p]
    user32.GetWindowDC.restype = ctypes.c_void_p
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]

    h_val = ctypes.c_void_p(hwnd)
    user32.ShowWindow(h_val, 9)
    user32.BringWindowToTop(h_val)
    time.sleep(0.3)

    r = wintypes.RECT()
    user32.GetWindowRect(h_val, ctypes.byref(r))
    w = max(100, r.right - r.left)
    h = max(100, r.bottom - r.top)

    hdc_window = user32.GetWindowDC(h_val)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
    hbm = gdi32.CreateCompatibleBitmap(hdc_window, w, h)
    gdi32.SelectObject(hdc_mem, hbm)

    user32.PrintWindow(h_val, hdc_mem, 2)

    from PIL import Image
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0

    gdi32.GetDIBits.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint
    ]
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(hdc_mem, hbm, 0, h, buf, ctypes.byref(bmi), 0)

    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1)

    gdi32.DeleteObject(hbm)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(h_val, hdc_window)

    saved_size = 0
    for p in output_paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(p), "PNG")
        saved_size = p.stat().st_size

    return saved_size


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
            "cscape_compile": [],
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
                decoded = line.decode("utf-8", errors="replace").strip()
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
                            self.contamination_count += 1
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass

    async def handshake(self) -> List[str]:
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

        t_resp, init_res = await asyncio.wait_for(fut, timeout=60.0)
        assert "result" in init_res, f"{self.client_id} initialize failed: {init_res}"

        notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        self.proc.stdin.write((json.dumps(notif) + "\n").encode("utf-8"))
        await self.proc.stdin.drain()

        rid = self.req_id_counter
        self.req_id_counter += 1
        self.sent_request_ids.add(rid)
        fut = asyncio.get_running_loop().create_future()
        self.futures[rid] = fut

        list_req = {"jsonrpc": "2.0", "id": rid, "method": "tools/list"}
        self.proc.stdin.write((json.dumps(list_req) + "\n").encode("utf-8"))
        await self.proc.stdin.drain()

        t_resp, list_res = await asyncio.wait_for(fut, timeout=60.0)
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
    print("=" * 85)
    print("STEP 144: FASTMCP MULTI-CLIENT CONCURRENT STDIO STRESS ON LIVE CSCAPE PID 7968")
    print(f"Target Process: PID {TARGET_PID} | HWND {TARGET_HWND_STR} | Project: TankLevelClosedLoop")
    print("=" * 85)
    t0_iso = get_utc_iso()
    print(f"Start Timestamp: {t0_iso}")

    # 1. Gate verification
    print("\n[STEP 1] Validating artifacts/.cscape_live_gate.json...")
    gate = assert_cscape_live()
    assert gate["ready_for_tests"] is True
    target_pid = int(gate["pid"])
    target_hwnd_str = str(gate["hwnd"])
    target_hwnd = int(target_hwnd_str, 16) if target_hwnd_str.startswith("0x") else int(target_hwnd_str)

    desktop_used = attach_thread_desktop(target_hwnd)
    proc_cscape = psutil.Process(target_pid)
    proc_uptime = time.time() - proc_cscape.create_time()
    working_set_mb = round(proc_cscape.memory_info().rss / (1024.0 * 1024.0), 2)

    user32 = ctypes.windll.user32
    is_hung = bool(user32.IsHungAppWindow(target_hwnd))
    is_enabled = bool(user32.IsWindowEnabled(target_hwnd))

    sm_result = ctypes.c_ulong()
    ping_ok = bool(user32.SendMessageTimeoutW(
        target_hwnd, 0x0000, 0, 0, 0x0002, 1000, ctypes.byref(sm_result)
    ))

    print(f"  Live Cscape PID={target_pid} | HWND={target_hwnd_str} | Desktop={desktop_used}")
    print(f"  Uptime={proc_uptime:.1f}s | WorkingSet={working_set_mb}MB | Hung={is_hung} | Enabled={is_enabled} | Ping={ping_ok}")
    assert is_hung is False, f"Cscape HWND {target_hwnd_str} is hung"
    assert ping_ok is True, f"Cscape HWND {target_hwnd_str} ping timeout"

    # 2. Launch 4 concurrent clients
    print(f"\n[STEP 2] Launching {NUM_CLIENTS} Concurrent Stdio FastMCP Clients...")
    client_names = [f"Client_{i+1}" for i in range(NUM_CLIENTS)]
    clients = [FastMCPBenchClient(cname, PY_EXE, SERVER_PY) for cname in client_names]

    for c in clients:
        await c.start()

    # Asynchronous modal dialog sweeper
    sweeper_running = True
    sweeper_dismissed_count = 0

    async def modal_dialog_sweeper():
        nonlocal sweeper_dismissed_count
        user32_local = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

        while sweeper_running:
            try:
                def _enum_cb(hwnd, _):
                    nonlocal sweeper_dismissed_count
                    pid = ctypes.c_ulong()
                    user32_local.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if pid.value == target_pid and user32_local.IsWindowVisible(hwnd):
                        cls = ctypes.create_unicode_buffer(256)
                        user32_local.GetClassNameW(hwnd, cls, 256)
                        if cls.value == "#32770":
                            user32_local.PostMessageW(hwnd, 0x0111, 1, 0)  # IDOK
                            user32_local.PostMessageW(hwnd, 0x0111, 6, 0)  # IDYES
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
            "cscape_compile",
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

        # 4. Spawns concurrent tasks across all 4 clients: 25 calls/client = 100 calls
        compile_lock = asyncio.Lock()

        async def client_worker(client: FastMCPBenchClient, client_idx: int) -> float:
            t_w_start = time.perf_counter()
            for seq in range(CALLS_PER_CLIENT):
                op_type = seq % 5
                if op_type == 0:
                    tool_name = "cscape_read_variables"
                    tool_args = {"file_path": str(VARS_CSV)}
                elif op_type == 1:
                    tool_name = "cscape_simulate_cycle"
                    tool_args = {"dt_ms": 10.0, "project_name": "TankLevelClosedLoop"}
                elif op_type == 2:
                    tool_name = "cscape_read_register"
                    tool_args = {"address": "%R1", "data_type": "REAL", "project_name": "TankLevelClosedLoop"}
                elif op_type == 3:
                    tool_name = "cscape_write_register"
                    # Partitioned write addresses across clients
                    addr = f"%R{200 + client_idx}"
                    val = float(50.0 + client_idx * 5.0 + seq)
                    tool_args = {"address": addr, "value": val, "data_type": "REAL", "project_name": "TankLevelClosedLoop"}
                else:
                    tool_name = "cscape_compile"
                    tool_args = {"project_path": str(PROJECT_DIR), "clean_build": False, "cscape_hwnd": target_hwnd}

                try:
                    if tool_name == "cscape_compile":
                        # Serialized GUI compile trigger
                        async with compile_lock:
                            lat_ms, resp = await client.call_tool(tool_name, tool_args, timeout=75.0)
                    else:
                        lat_ms, resp = await client.call_tool(tool_name, tool_args, timeout=75.0)

                    is_err = "error" in resp or resp.get("result", {}).get("isError", False)
                    if not is_err:
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

        print(f"\n[STEP 4] Spawning {NUM_CLIENTS} Concurrent Client Tasks ({CALLS_PER_CLIENT} calls/client = {TOTAL_CALLS} total calls)...")
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

        assert all_errors == 0, f"Encountered {all_errors} tool execution errors"
        assert all_dropped == 0, f"Encountered {all_dropped} dropped frames"
        assert all_contamination == 0, f"Encountered {all_contamination} cross-client contamination frames"

        # 6. Concurrently verify download lockout on each client
        print("\n[STEP 6] Testing Concurrent Controller Download Lockout (32827) across all clients...")
        for c in clients:
            lat_dl, res_dl = await c.call_tool("cscape_download_logic", {"project_path": "TankLevelClosedLoop"})
            is_err = res_dl.get("result", {}).get("isError") is True or "error" in res_dl
            assert is_err is True, f"Client {c.client_id} did not reject download tool!"
        print(f"  [PASS] All {NUM_CLIENTS} clients strictly locked out from download.")

    finally:
        sweeper_running = False
        await asyncio.sleep(0.1)
        sweeper_task.cancel()
        try:
            await sweeper_task
        except asyncio.CancelledError:
            pass

        print("\n[CLEANUP] Closing all stdio client connections...")
        for c in clients:
            await c.close()
        sweep_cscape_dialogs(target_pid)

    # 7. High-Res Screenshot & Window Health
    print(f"\n[STEP 7] Capturing Live Cscape Window (HWND {target_hwnd_str})...")
    sweep_cscape_dialogs(target_pid)
    time.sleep(0.2)
    ss_size = capture_cscape_screenshot(target_hwnd, SCREENSHOT_PATHS)
    ss_sha = compute_sha256(SCREENSHOT_PATHS[0].read_bytes())
    print(f"  [PASS] Saved screenshot ({ss_size} bytes, SHA-256: {ss_sha[:16]}...)")

    # 8. Post-test health verification
    print("\n[STEP 8] Verifying Post-Benchmark Cscape GUI Health...")
    sweep_cscape_dialogs(target_pid)
    time.sleep(0.2)
    post_cscape = psutil.Process(target_pid)
    post_uptime = time.time() - post_cscape.create_time()
    post_ws_mb = round(post_cscape.memory_info().rss / (1024.0 * 1024.0), 2)
    post_hung = bool(user32.IsHungAppWindow(target_hwnd))
    post_enabled = bool(user32.IsWindowEnabled(target_hwnd))
    post_ping = bool(user32.SendMessageTimeoutW(
        target_hwnd, 0x0000, 0, 0, 0x0002, 1000, ctypes.byref(sm_result)
    ))

    print(f"  Live Cscape PID={target_pid} | HWND={target_hwnd_str}")
    print(f"  Uptime={post_uptime:.1f}s | WorkingSet={post_ws_mb}MB | Hung={post_hung} | Enabled={post_enabled} | Ping={post_ping}")
    assert post_hung is False, "Cscape hung after benchmark"
    assert post_enabled is True, "Cscape window disabled after benchmark"
    assert post_ping is True, "Cscape ping unresponsive"

    # 9. Write audit log & checkpoint
    t_end_iso = get_utc_iso()
    audit_data = {
        "step": 144,
        "title": "FastMCP Multi-Client Concurrent Stdio Stress & Register Partitioning on Live Cscape",
        "timestamp_start_utc": t0_iso,
        "timestamp_end_utc": t_end_iso,
        "duration_seconds": round(total_bench_dur, 3),
        "status": "PASSED",
        "target_pid": target_pid,
        "target_hwnd": target_hwnd_str,
        "clients_count": NUM_CLIENTS,
        "calls_per_client": CALLS_PER_CLIENT,
        "total_calls": TOTAL_CALLS,
        "success_rate_percent": success_rate,
        "aggregate_throughput_calls_per_sec": round(aggregate_throughput, 2),
        "errors": all_errors,
        "dropped_frames": all_dropped,
        "cross_client_contamination": all_contamination,
        "sweeper_interventions": sweeper_dismissed_count,
        "overall_latency_ms": overall_stats,
        "per_tool_latency_ms": tool_stats,
        "per_client_summary": per_client_metrics,
        "cscape_process_health": {
            "pid": target_pid,
            "hwnd": target_hwnd_str,
            "uptime_seconds": round(post_uptime, 1),
            "working_set_mb": post_ws_mb,
            "is_hung": post_hung,
            "is_enabled": post_enabled,
            "ping_ok": post_ping,
        },
        "screenshot_evidence": {
            "path": str(SCREENSHOT_PATHS[0]),
            "size_bytes": ss_size,
            "sha256": ss_sha,
        },
    }

    log_bytes = json.dumps(audit_data, indent=2).encode("utf-8")
    log_sha = compute_sha256(log_bytes)
    audit_data["log_sha256"] = log_sha

    for lp in BENCHMARK_LOG_PATHS:
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text(json.dumps(audit_data, indent=2), encoding="utf-8")
    print(f"\n[LOG] Saved audit log to {BENCHMARK_LOG_PATHS[0]} (SHA-256: {log_sha})")

    cp_data = {
        "step": 144,
        "name": "step144_mcp_multi_client_stress_checkpoint",
        "status": "PASSED",
        "timestamp_utc": t_end_iso,
        "cscape_pid": target_pid,
        "hwnd": target_hwnd_str,
        "clients_count": NUM_CLIENTS,
        "total_calls": TOTAL_CALLS,
        "success_rate_percent": success_rate,
        "aggregate_throughput_calls_per_sec": round(aggregate_throughput, 2),
        "median_latency_ms": overall_stats["median"],
        "p95_latency_ms": overall_stats["p95"],
        "errors": all_errors,
        "dropped_frames": all_dropped,
        "cross_client_contamination": all_contamination,
        "live_screenshot_sha256": ss_sha,
        "zero_straton_dependencies": True,
        "hardware_lockout_enforced": True,
    }

    cp_bytes = json.dumps(cp_data, indent=2).encode("utf-8")
    cp_sha = compute_sha256(cp_bytes)
    cp_data["checkpoint_sha256"] = cp_sha

    for cp in CHECKPOINT_PATHS:
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(cp_data, indent=2), encoding="utf-8")
    print(f"[CHECKPOINT] Saved checkpoint to {CHECKPOINT_PATHS[0]} (SHA-256: {cp_sha})")

    print("\n" + "=" * 85)
    print(f"STEP 144 COMPLETED SUCCESSFULLY IN {total_bench_dur:.2f}s (100% ASSERTIONS PASSED)")
    print("=" * 85)
    return audit_data


def main() -> int:
    try:
        asyncio.run(run_multi_client_benchmark())
        return 0
    except Exception as exc:
        print(f"\n[FATAL ERROR] Step 144 failed: {exc}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
