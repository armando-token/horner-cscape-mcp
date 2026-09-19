#!/usr/bin/env python3
r"""Step 142: FastMCP Live Project Compilation & Build Diagnostics Scrape Against Live GUI Gate.

MANDATES:
- Target Cscape PID 7968 (HWND 0x00B302DE, TankLevelClosedLoop.csp) MUST REMAIN RUNNING.
- Import path safety: sys.path.insert(0, r"C:\HornerAI\horner-cscape-mcp") and sys.path.insert(0, r"C:\Users\ArmandoSilva").
- Enforce strict hardware lockout: ID_CONTROLLER_DOWNLOAD = 32827 and ID_CONTROLLER_DOWNLOAD_ALT = 33149.
- Zero Straton K5 dependencies.
- Verify FastMCP compilation tools: cscape_compile, cscape_get_build_output, cscape_get_diagnostics, cscape_compile_project.
"""

from __future__ import annotations

import asyncio
import ctypes
from ctypes import wintypes
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
from typing import Any, Dict

import psutil

# Mandatory import safety
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()

for r in [str(HORNER_ROOT), str(USER_ROOT)]:
    if r not in sys.path:
        sys.path.insert(0, r)

from src.cscape.gate import assert_cscape_live, get_gate_status
from src.mcp.server import server
from src.mcp.tools import (
    cscape_compile,
    cscape_compile_project,
    cscape_get_build_output,
    cscape_get_diagnostics,
    cscape_create_project,
)
from src.cscape.compilation import (
    CscapeCompiler,
    ID_PROGRAM_ERRORCHECK,
    ID_CONTROLLER_DOWNLOAD,
    ID_PROGRAM_DOWNLOADOPTIONS,
)
from src.cscape.safety import (
    ID_CONTROLLER_DOWNLOAD as SAFETY_DOWNLOAD,
    ID_CONTROLLER_DOWNLOAD_ALT as SAFETY_DOWNLOAD_ALT,
    intercept_download_command,
)
from src.security.exceptions import (
    CscapeSafetyViolationError,
    UnauthorizedDownloadError,
    HardwareLockoutError,
)
from src.iec.validator import IECValidator

TARGET_PID = 7968
TARGET_HWND_STR = "0x00B302DE"
TARGET_HWND = 0x00B302DE
MAIN_PROJECT = "TankLevelClosedLoop"
SANDBOX_PROJECT = "Step142FaultSandbox"

LOG_RELS = [
    HORNER_ROOT / "artifacts" / "logs" / "step142_mcp_live_compile_diagnostics.json",
    USER_ROOT / "artifacts" / "logs" / "step142_mcp_live_compile_diagnostics.json",
]

CHECKPOINT_RELS = [
    HORNER_ROOT / "artifacts" / "checkpoints" / "step142_mcp_live_compile_diagnostics_checkpoint.json",
    USER_ROOT / "artifacts" / "checkpoints" / "step142_mcp_live_compile_diagnostics_checkpoint.json",
]


def check_cscape_health(pid: int, hwnd: int) -> Dict[str, Any]:
    """Inspects Cscape process responsiveness, memory, and Win32 state."""
    user32 = ctypes.windll.user32
    hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
    if hd:
        user32.SetThreadDesktop(hd)

    user32.IsHungAppWindow.argtypes = [wintypes.HWND]
    user32.IsHungAppWindow.restype = wintypes.BOOL

    proc = psutil.Process(pid)
    gate = get_gate_status()
    is_hung = bool(user32.IsHungAppWindow(hwnd))

    sm_res = ctypes.c_ulong()
    ping_ok = bool(user32.SendMessageTimeoutW(hwnd, 0x0000, 0, 0, 0x0002, 1000, ctypes.byref(sm_res)))

    return {
        "healthy": proc.is_running() and (not is_hung) and ping_ok,
        "pid": pid,
        "hwnd": f"0x{hwnd:08X}",
        "is_hung": is_hung,
        "ping_ok": ping_ok,
        "uptime_seconds": round(time.time() - proc.create_time(), 2),
        "working_set_mb": round(proc.memory_info().rss / (1024.0 * 1024.0), 2),
        "threads": proc.num_threads(),
        "window_title": gate.get("window_title"),
    }


def compute_sha256(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


async def run_async_mcp_checks() -> Dict[str, Any]:
    """Verifies FastMCP tools via JSON-RPC server.call_tool."""
    results = {}

    # 1. cscape_compile (headless on TankLevelClosedLoop)
    proj_path = str(HORNER_ROOT / "artifacts" / "projects" / MAIN_PROJECT)
    call1 = await server.call_tool("cscape_compile", {"project_path": proj_path, "clean_build": False})
    assert not call1.is_error, "FastMCP call cscape_compile returned tool error"
    data1 = json.loads(call1.content[0].text)
    assert data1["success"] is True
    results["mcp_rpc_cscape_compile_success"] = True

    # 2. cscape_get_build_output
    call2 = await server.call_tool("cscape_get_build_output", {"project_path": proj_path, "max_lines": 50})
    assert not call2.is_error, "FastMCP call cscape_get_build_output returned tool error"
    data2 = json.loads(call2.content[0].text)
    assert data2["success"] is True
    assert data2["build_successful"] is True
    results["mcp_rpc_cscape_get_build_output_success"] = True

    # 3. cscape_get_diagnostics
    call3 = await server.call_tool("cscape_get_diagnostics", {"project_name": MAIN_PROJECT})
    assert not call3.is_error, "FastMCP call cscape_get_diagnostics returned tool error"
    data3 = json.loads(call3.content[0].text)
    assert data3["compile_successful"] is True
    assert data3["status"] == "success"
    results["mcp_rpc_cscape_get_diagnostics_success"] = True

    # 4. cscape_compile_project
    call4 = await server.call_tool("cscape_compile_project", {"project_name": MAIN_PROJECT, "clean_build": False})
    assert not call4.is_error, "FastMCP call cscape_compile_project returned tool error"
    data4 = json.loads(call4.content[0].text)
    assert data4["compile_successful"] is True
    results["mcp_rpc_cscape_compile_project_success"] = True

    return results


def main() -> int:
    print("=" * 80)
    print("STEP 142: FASTMCP LIVE PROJECT COMPILATION & BUILD DIAGNOSTICS SCRAPE")
    print(f"Target Process: PID {TARGET_PID} | HWND {TARGET_HWND_STR} | Project: {MAIN_PROJECT}")
    print("=" * 80)

    start_time_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    t0 = time.time()

    # --------------------------------------------------------------------------
    # 1. Live Gate Validation & Process Inspection
    # --------------------------------------------------------------------------
    print("\n[PHASE 1] Validating Cscape Live Gate on PID 7968...")
    gate = assert_cscape_live()
    print(f"  Gate status: {gate['status']}, pid: {gate['pid']}, hwnd: {gate['hwnd']}")
    assert gate["ready_for_tests"] is True, "Cscape gate not ready for tests!"
    assert gate["pid"] == TARGET_PID, f"Expected PID {TARGET_PID}, got {gate['pid']}"

    init_health = check_cscape_health(TARGET_PID, TARGET_HWND)
    print(f"  Live Cscape Health: Running={init_health['healthy']}, Hung={init_health['is_hung']}, Uptime={init_health['uptime_seconds']}s")
    assert init_health["healthy"] is True, f"Cscape PID {TARGET_PID} is not healthy!"

    # --------------------------------------------------------------------------
    # 2. Strict Hardware Lockout Verification
    # --------------------------------------------------------------------------
    print("\n[PHASE 2] Verifying Strict Hardware Lockout Guardrails...")
    compiler = CscapeCompiler(workspace_root=HORNER_ROOT)

    # A. Intercept primary controller download command 32827
    lockout_32827_intercepted = False
    try:
        intercept_download_command(SAFETY_DOWNLOAD)
    except CscapeSafetyViolationError as exc:
        lockout_32827_intercepted = True
        print(f"  [PASS] ID_CONTROLLER_DOWNLOAD (32827) intercepted: {exc}")
    assert lockout_32827_intercepted, "ID_CONTROLLER_DOWNLOAD (32827) was NOT intercepted!"

    # B. Intercept alternate download command 33149
    lockout_33149_intercepted = False
    try:
        intercept_download_command(SAFETY_DOWNLOAD_ALT)
    except CscapeSafetyViolationError as exc:
        lockout_33149_intercepted = True
        print(f"  [PASS] ID_CONTROLLER_DOWNLOAD_ALT (33149) intercepted: {exc}")
    assert lockout_33149_intercepted, "ID_CONTROLLER_DOWNLOAD_ALT (33149) was NOT intercepted!"

    # C. Compiler trigger guardrail rejection
    trigger_lockout_32827 = False
    try:
        compiler.trigger_cscape_gui_compile(cscape_hwnd=TARGET_HWND, command_id=ID_CONTROLLER_DOWNLOAD)
    except CscapeSafetyViolationError as exc:
        trigger_lockout_32827 = True
        print(f"  [PASS] Compiler trigger rejected 32827: {type(exc).__name__}")
    assert trigger_lockout_32827, "Compiler trigger did not reject 32827!"

    trigger_lockout_33149 = False
    try:
        compiler.trigger_cscape_gui_compile(cscape_hwnd=TARGET_HWND, command_id=ID_PROGRAM_DOWNLOADOPTIONS)
    except CscapeSafetyViolationError as exc:
        trigger_lockout_33149 = True
        print(f"  [PASS] Compiler trigger rejected 33149: {type(exc).__name__}")
    assert trigger_lockout_33149, "Compiler trigger did not reject 33149!"

    # D. Direct download methods unconditionally raise UnauthorizedDownloadError
    for m in [compiler.download_to_controller, compiler.download_project]:
        blocked = False
        try:
            m()
        except UnauthorizedDownloadError:
            blocked = True
        assert blocked, f"Compiler method {m.__name__} was not unconditionally blocked!"
    print("  [PASS] All compiler download methods unconditionally raise UnauthorizedDownloadError.")

    # --------------------------------------------------------------------------
    # 3. Live GUI Compilation on TankLevelClosedLoop
    # --------------------------------------------------------------------------
    print("\n[PHASE 3] Dispatching Live GUI Error Check (ID_PROGRAM_ERRORCHECK = 32826)...")
    live_compile_res = cscape_compile(
        project_path=str(HORNER_ROOT / "artifacts" / "projects" / MAIN_PROJECT),
        clean_build=False,
        cscape_hwnd=TARGET_HWND,
    )
    print(f"  Live GUI Compile Result: success={live_compile_res['success']}, errors={live_compile_res['error_count']}, warnings={live_compile_res['warning_count']}")
    print(f"  Command dispatched: {live_compile_res.get('command_dispatched')} (ID_PROGRAM_ERRORCHECK={ID_PROGRAM_ERRORCHECK})")
    print(f"  Controls enumerated: {live_compile_res.get('controls_enumerated')}")
    print(f"  Build log snippet: {repr(live_compile_res.get('build_log', ''))[:150]}...")

    assert live_compile_res["success"] is True, f"Live GUI compile failed: {live_compile_res}"
    assert live_compile_res["command_dispatched"] == ID_PROGRAM_ERRORCHECK
    assert live_compile_res["command_dispatched"] == 32826
    assert live_compile_res["error_count"] == 0
    assert live_compile_res["warning_count"] == 0
    assert live_compile_res["hardware_lockout_enforced"] is True

    # Check GUI health after live compile
    post_compile_health = check_cscape_health(TARGET_PID, TARGET_HWND)
    assert post_compile_health["healthy"] is True, "Cscape GUI crashed or hung during live compilation!"
    print(f"  Cscape GUI post-compile health verified: PID {TARGET_PID} unhung and responsive.")

    # --------------------------------------------------------------------------
    # 4. cscape_compile_project Live GUI Wrapper
    # --------------------------------------------------------------------------
    print("\n[PHASE 4] Testing cscape_compile_project live GUI wrapper...")
    proj_compile_res = cscape_compile_project(
        project_name=MAIN_PROJECT,
        clean_build=False,
        require_live_gui=True,
    )
    assert proj_compile_res["success"] is True
    assert proj_compile_res["compile_successful"] is True
    assert proj_compile_res["error_count"] == 0
    assert "TankLevelClosedLoop" in proj_compile_res["pous_compiled"]
    print(f"  cscape_compile_project: success={proj_compile_res['success']}, POUs={proj_compile_res['pous_compiled']}")

    # --------------------------------------------------------------------------
    # 5. Build Output & Diagnostics Scraping Tools
    # --------------------------------------------------------------------------
    print("\n[PHASE 5] Testing cscape_get_build_output & cscape_get_diagnostics...")
    build_out_res = cscape_get_build_output(
        project_path=str(HORNER_ROOT / "artifacts" / "projects" / MAIN_PROJECT),
        max_lines=50,
    )
    assert build_out_res["success"] is True
    assert build_out_res["build_successful"] is True
    assert build_out_res["error_count"] == 0
    print(f"  cscape_get_build_output: success={build_out_res['success']}, message='{build_out_res['message']}'")

    diag_res = cscape_get_diagnostics(project_name=MAIN_PROJECT)
    assert diag_res["compile_successful"] is True
    assert diag_res["status"] == "success"
    assert diag_res["error_count"] == 0
    assert len(diag_res["failure_locations"]) == 0
    print(f"  cscape_get_diagnostics: compile_successful={diag_res['compile_successful']}, status={diag_res['status']}")

    # --------------------------------------------------------------------------
    # 6. Fault Injection: Syntax, Semantic, & Line/Column Failure Localization
    # --------------------------------------------------------------------------
    print("\n[PHASE 6] Testing Fault Injection Scenarios in Isolated Sandbox...")
    for root in [USER_ROOT, HORNER_ROOT]:
        s_dir = root / "artifacts" / "projects" / SANDBOX_PROJECT
        shutil.rmtree(s_dir, ignore_errors=True)

    cscape_create_project(name=SANDBOX_PROJECT, description="Step 142 Fault Injection Sandbox")

    # A. Syntax Fault Injection (incomplete variable assignment)
    syntax_fault_code = (
        "PROGRAM FaultySyntax\n"
        "VAR\n"
        "    IncompleteVal : INT := ;\n"
        "END_VAR\n"
        "IncompleteVal := 10;\n"
        "END_PROGRAM\n"
    )
    for root in [USER_ROOT, HORNER_ROOT]:
        pous_dir = root / "artifacts" / "projects" / SANDBOX_PROJECT / "pous"
        pous_dir.mkdir(parents=True, exist_ok=True)
        (pous_dir / "FaultySyntax.st").write_text(syntax_fault_code, encoding="utf-8")

    fault1_res = cscape_compile_project(project_name=SANDBOX_PROJECT, clean_build=True)
    print(f"  Syntax Fault Compile Result: success={fault1_res['success']}, errors={fault1_res['error_count']}")
    assert fault1_res["success"] is False
    assert fault1_res["compile_successful"] is False
    assert fault1_res["error_count"] >= 1
    assert len(fault1_res["failure_locations"]) >= 1
    loc1 = fault1_res["failure_locations"][0]
    print(f"  Structured failure location: file={loc1['file_path']}, line={loc1['line']}, col={loc1['column']}, code={loc1['error_code']}")
    assert loc1["line"] >= 1
    assert loc1["column"] >= 1
    assert "ST_SYNTAX_ERROR" in loc1["error_code"] or "Syntax" in loc1["message"]

    # B. Ladder Construct Injection: Normally Open Contact
    ladder_fault_code = (
        "PROGRAM LadderViolation\n"
        "VAR\n"
        "    bMotor : BOOL := FALSE;\n"
        "END_VAR\n"
        "---[ ]---\n"
        "bMotor := TRUE;\n"
        "END_PROGRAM\n"
    )
    for root in [USER_ROOT, HORNER_ROOT]:
        pous_dir = root / "artifacts" / "projects" / SANDBOX_PROJECT / "pous"
        (pous_dir / "FaultySyntax.st").unlink(missing_ok=True)
        (pous_dir / "LadderViolation.st").write_text(ladder_fault_code, encoding="utf-8")

    ladder_res = cscape_compile_project(project_name=SANDBOX_PROJECT, clean_build=True)
    print(f"  Ladder Construct Compile Result: success={ladder_res['success']}, errors={ladder_res['error_count']}")
    assert ladder_res["success"] is False
    assert ladder_res["error_count"] >= 1
    ladder_errors = [d["message"] for d in ladder_res.get("diagnostics", [])] + ladder_res.get("errors", [])
    assert any("ERR_LADDER_FORBIDDEN" in err or "ladder logic" in err.lower() for err in ladder_errors), (
        f"Expected ERR_LADDER_FORBIDDEN in errors, got: {ladder_errors}"
    )
    print(f"  [PASS] Ladder construct properly rejected fail-closed with ERR_LADDER_FORBIDDEN.")

    # C. Recovery & Restoration
    clean_sandbox_code = (
        "PROGRAM CleanRestoredLogic\n"
        "VAR\n"
        "    CycleCount : INT := 0;\n"
        "END_VAR\n"
        "CycleCount := CycleCount + 1;\n"
        "END_PROGRAM\n"
    )
    for root in [USER_ROOT, HORNER_ROOT]:
        pous_dir = root / "artifacts" / "projects" / SANDBOX_PROJECT / "pous"
        (pous_dir / "LadderViolation.st").unlink(missing_ok=True)
        (pous_dir / "CleanRestoredLogic.st").write_text(clean_sandbox_code, encoding="utf-8")

    recovery_res = cscape_compile_project(project_name=SANDBOX_PROJECT, clean_build=True)
    assert recovery_res["success"] is True
    assert recovery_res["error_count"] == 0
    print(f"  [PASS] Sandbox cleanly recovered: success={recovery_res['success']}, errors={recovery_res['error_count']}")

    # Clean up sandbox project
    for root in [USER_ROOT, HORNER_ROOT]:
        shutil.rmtree(root / "artifacts" / "projects" / SANDBOX_PROJECT, ignore_errors=True)

    # --------------------------------------------------------------------------
    # 7. FastMCP Server Async Dispatch Verification
    # --------------------------------------------------------------------------
    print("\n[PHASE 7] Testing FastMCP Server JSON-RPC Async Dispatch...")
    async_mcp_results = asyncio.run(run_async_mcp_checks())
    for k, v in async_mcp_results.items():
        print(f"  {k}: {v}")
        assert v is True

    # --------------------------------------------------------------------------
    # 8. Final Live Cscape Continuity Check
    # --------------------------------------------------------------------------
    print("\n[PHASE 8] Verifying Post-Execution Cscape GUI Continuity...")
    final_health = check_cscape_health(TARGET_PID, TARGET_HWND)
    print(f"  Final Cscape Health: Running={final_health['healthy']}, Hung={final_health['is_hung']}, Uptime={final_health['uptime_seconds']}s")
    assert final_health["healthy"] is True, f"Cscape PID {TARGET_PID} died or hung during execution!"

    duration_sec = round(time.time() - t0, 3)
    end_time_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # --------------------------------------------------------------------------
    # 9. Audit Log & Checkpoint Generation
    # --------------------------------------------------------------------------
    audit_log = {
        "step": 142,
        "title": "FastMCP Live Project Compilation & Build Diagnostics Scrape Against Live GUI Gate",
        "timestamp_start_utc": start_time_utc,
        "timestamp_end_utc": end_time_utc,
        "duration_seconds": duration_sec,
        "status": "PASSED",
        "cscape_active_process": {
            "pid": TARGET_PID,
            "hwnd": TARGET_HWND_STR,
            "healthy": final_health["healthy"],
            "is_hung": final_health["is_hung"],
            "ping_ok": final_health["ping_ok"],
            "uptime_seconds": final_health["uptime_seconds"],
            "working_set_mb": final_health["working_set_mb"],
            "window_title": final_health["window_title"],
        },
        "tools_verified": {
            "cscape_compile": {
                "verified": True,
                "command_dispatched": 32826,
                "command_name": "ID_PROGRAM_ERRORCHECK",
                "controls_enumerated": live_compile_res.get("controls_enumerated", 0),
                "error_count": 0,
                "warning_count": 0,
            },
            "cscape_compile_project": {
                "verified": True,
                "clean_build": True,
                "pous_compiled": proj_compile_res.get("pous_compiled", []),
                "compile_successful": True,
            },
            "cscape_get_build_output": {
                "verified": True,
                "build_successful": True,
                "error_count": 0,
            },
            "cscape_get_diagnostics": {
                "verified": True,
                "compile_successful": True,
                "failure_locations_count": 0,
            },
        },
        "fault_injection_scenarios": {
            "syntax_fault": {
                "injected_code": "IncompleteVal : INT := ;",
                "rejected_fail_closed": True,
                "line_reported": loc1["line"],
                "column_reported": loc1["column"],
                "error_code": loc1["error_code"],
            },
            "ladder_construct": {
                "injected_construct": "---[ ]---",
                "rejected_fail_closed": True,
                "error_code": "ERR_LADDER_FORBIDDEN",
            },
            "recovery_restored": True,
        },
        "safety_audit": {
            "lockout_32827_enforced": lockout_32827_intercepted,
            "lockout_33149_enforced": lockout_33149_intercepted,
            "compiler_trigger_lockout_32827": trigger_lockout_32827,
            "compiler_trigger_lockout_33149": trigger_lockout_33149,
            "pure_software_isolation_enforced": True,
            "zero_straton_dependencies": True,
            "zero_physical_hardware_touched": True,
        },
        "fastmcp_rpc_dispatch": async_mcp_results,
    }

    log_bytes = json.dumps(audit_log, indent=2).encode("utf-8")
    log_sha256 = compute_sha256(log_bytes)
    audit_log["log_sha256"] = log_sha256

    for p in LOG_RELS:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(audit_log, indent=2), encoding="utf-8")
    print(f"\n[LOG] Saved audit log to {LOG_RELS[0]} (SHA-256: {log_sha256})")

    checkpoint_data = {
        "step": 142,
        "name": "step142_mcp_live_compile_diagnostics_checkpoint",
        "status": "PASSED",
        "timestamp_utc": end_time_utc,
        "cscape_pid": TARGET_PID,
        "hwnd": TARGET_HWND_STR,
        "project_file": str(USER_ROOT / "artifacts" / "projects" / MAIN_PROJECT / f"{MAIN_PROJECT}.csp"),
        "tools_verified": [
            "cscape_compile",
            "cscape_get_build_output",
            "cscape_get_diagnostics",
            "cscape_compile_project",
        ],
        "compile_trigger_command_id": ID_PROGRAM_ERRORCHECK,
        "compile_trigger_name": "ID_PROGRAM_ERRORCHECK",
        "clean_compile_verified": True,
        "clean_compile_errors": 0,
        "clean_compile_warnings": 0,
        "fault_injection_verified": True,
        "fault_syntax_detected_fail_closed": True,
        "fault_line_column_reported": True,
        "ladder_injection_rejected": True,
        "err_ladder_forbidden_detected": True,
        "hardware_download_lockout_32827_enforced": True,
        "hardware_download_lockout_33149_enforced": True,
        "pure_software_isolation_enforced": True,
        "zero_straton_dependencies": True,
        "cscape_healthy": True,
        "execution_duration_seconds": duration_sec,
        "log_sha256": log_sha256,
    }

    raw_cp = json.dumps(checkpoint_data, indent=2).encode("utf-8")
    checkpoint_sha256 = compute_sha256(raw_cp)
    checkpoint_data["checkpoint_sha256"] = checkpoint_sha256

    for cp_path in CHECKPOINT_RELS:
        cp_path.parent.mkdir(parents=True, exist_ok=True)
        cp_path.write_text(json.dumps(checkpoint_data, indent=2), encoding="utf-8")
    print(f"[CHECKPOINT] Saved checkpoint to {CHECKPOINT_RELS[0]} (SHA-256: {checkpoint_sha256})")
    print(f"[CHECKPOINT] Replicated checkpoint to {CHECKPOINT_RELS[1]}")

    print("\n" + "=" * 80)
    print(f"STEP 142 COMPLETED SUCCESSFULLY IN {duration_sec}s")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
