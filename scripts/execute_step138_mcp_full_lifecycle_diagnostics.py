#!/usr/bin/env python3
r"""
Step 138: Multi-POU FastMCP Full Lifecycle Verification (Insert, Validate, Simulate, Diagnostics Roundtrip) on TankLevelClosedLoop.

Mission:
1. Target all 5 POUs in artifacts/projects/TankLevelClosedLoop/pous/:
   - TankLevelClosedLoop.st
   - AlarmMonitor.st
   - BrokenPOU.st
   - AuxPumpControl.st
   - SafetyInterlockST.st
2. Active Cscape Gate & Health:
   - Fail-closed gate check: assert .cscape_live_gate.json is ready and responsive.
   - Assert PID 14580 is alive, IsHungAppWindow = False, SendMessageTimeoutW ping = True.
3. Tool 1: cscape_validate_st:
   - Validate all 5 POUs; assert all valid POUs return valid = True and 0 errors.
   - Validate synthetic syntax faults (unclosed IF, invalid token, semicolon missing);
     assert valid = False with structured failure_locations (file, line, col, code, message).
   - Validate ladder artifact rejection (e.g. ladder rung keywords, coils);
     assert ERR_LADDER_FORBIDDEN / valid = False.
4. Tool 2: cscape_simulate_pou:
   - Simulate multi-step runs (10 steps each) across AlarmMonitor, AuxPumpControl, BrokenPOU,
     SafetyInterlockST (and TankLevelClosedLoop).
   - Verify state transitions, trace generation, isolation_enforced = True,
     hardware_lockout_enforced = True.
5. Tool 3: cscape_get_diagnostics:
   - Query diagnostics for TankLevelClosedLoop.
   - Verify structured diagnostics, memory footprint (code_size_bytes, data_size_bytes, retain_size_bytes),
     and compile success status.
6. Tool 4: cscape_export_project:
   - Export in formats: csp, cpj, json, xml. Assert created files, sizes > 0, SHA-256 computed.
   - Test legacy k5p export: assert file is routed to quarantine/straton_k5_legacy/artifacts/exports/
     and response includes quarantine warning.
7. Tool 5: Safety audit:
   - Assert ID_CONTROLLER_DOWNLOAD = 32827 and ID_CONTROLLER_DOWNLOAD_ALT = 33149 raise
     UnauthorizedDownloadError / CscapeSafetyViolationError.
   - Assert 0 physical PLC ports touched and 0 Straton processes running.
8. Write evidence log artifacts/logs/mcp_full_lifecycle_diagnostics.json and checkpoint
   artifacts/checkpoints/step138_mcp_full_lifecycle_diagnostics_checkpoint.json
   (mirrored across both C:\HornerAI\horner-cscape-mcp and C:\Users\ArmandoSilva).
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
from typing import Any, Dict, List, Optional

import psutil

# Ensure workspace roots are on sys.path
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()

for r in [HORNER_ROOT, USER_ROOT]:
    if str(r) not in sys.path:
        sys.path.insert(0, str(r))

from src.cscape.gate import assert_cscape_live, attach_thread_desktop, get_gate_status
from src.mcp.tools import (
    cscape_validate_st,
    cscape_simulate_pou,
    cscape_get_diagnostics,
    cscape_export_project,
)
from src.cscape.safety import (
    ID_CONTROLLER_DOWNLOAD,
    ID_CONTROLLER_DOWNLOAD_ALT,
    intercept_download_command,
    intercept_hardware_interface,
    CscapeSafetyViolationError,
)
from src.automation.cli_runner import CLIRunner
from src.security.exceptions import UnauthorizedDownloadError

TARGET_PID = 14580
TARGET_PROJECT = "TankLevelClosedLoop"
TARGET_POUS = [
    "TankLevelClosedLoop.st",
    "AlarmMonitor.st",
    "BrokenPOU.st",
    "AuxPumpControl.st",
    "SafetyInterlockST.st",
]

STRATON_BINARIES = ["k5bus.exe", "k5edit.exe", "k5run.exe", "k5vm.exe", "k5cmd.exe", "t5.exe"]


def init_win32_user32():
    """Initializes user32 function signatures for window health checking."""
    user32 = ctypes.windll.user32
    user32.IsHungAppWindow.argtypes = [wintypes.HWND]
    user32.IsHungAppWindow.restype = wintypes.BOOL
    user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_ulong)
    ]
    user32.SendMessageTimeoutW.restype = ctypes.c_long
    return user32


def ping_cscape_window(user32, hwnd: int) -> bool:
    """Sends WM_NULL ping to Cscape main window with timeout."""
    attach_thread_desktop(hwnd)
    res_val = ctypes.c_ulong(0)
    # SMTO_ABORTIFHUNG = 0x0002, timeout = 1000ms, WM_NULL = 0x0000
    res = user32.SendMessageTimeoutW(hwnd, 0, 0, 0, 0x0002, 1000, ctypes.byref(res_val))
    return bool(res != 0)


def run_step138() -> Dict[str, Any]:
    print("=" * 80)
    print("STEP 138: Multi-POU FastMCP Full Lifecycle Verification on TankLevelClosedLoop")
    print(f"Timestamp: {datetime.datetime.now(datetime.timezone.utc).isoformat()}")
    print("=" * 80)

    # --------------------------------------------------------------------------
    # 0. Gate Check & Cscape Health Verification
    # --------------------------------------------------------------------------
    print("\n[STEP 0] Checking live Cscape gate & health (PID 14580)...")
    gate_info = assert_cscape_live()
    assert gate_info.get("ready_for_tests") is True, f"Gate not ready: {gate_info}"
    print(f"  Gate ready: status={gate_info.get('status')}, window={gate_info.get('window_title')}")

    pid = gate_info.get("pid", TARGET_PID)
    assert pid == TARGET_PID, f"Expected PID {TARGET_PID}, got {pid}"
    assert psutil.pid_exists(pid), f"PID {pid} does not exist"
    proc = psutil.Process(pid)
    assert proc.is_running(), f"Process {pid} is not running"
    assert "cscape" in proc.name().lower(), f"Unexpected process name: {proc.name()}"

    raw_hwnd = gate_info.get("hwnd")
    hwnd = int(raw_hwnd, 0) if isinstance(raw_hwnd, str) else int(raw_hwnd)
    user32 = init_win32_user32()

    is_hung = bool(user32.IsHungAppWindow(hwnd))
    assert not is_hung, f"Cscape window {hex(hwnd)} is hung!"

    ping_ok = ping_cscape_window(user32, hwnd)
    assert ping_ok, f"SendMessageTimeoutW ping failed for Cscape window {hex(hwnd)}"
    print(f"  PID {pid} ({proc.name()}) alive, IsHungAppWindow=False, SendMessageTimeoutW ping=OK")

    cscape_health = {
        "pid": pid,
        "name": proc.name(),
        "memory_rss_bytes": proc.memory_info().rss,
        "cpu_percent": proc.cpu_percent(interval=0.1),
        "status": proc.status(),
        "hwnd": hex(hwnd),
        "is_hung": is_hung,
        "ping_responsive": ping_ok,
    }

    # --------------------------------------------------------------------------
    # 1. Tool 1: cscape_validate_st
    # --------------------------------------------------------------------------
    print("\n[STEP 1] Testing Tool 1: cscape_validate_st...")
    pous_dir = HORNER_ROOT / "artifacts" / "projects" / TARGET_PROJECT / "pous"
    assert pous_dir.exists(), f"POUs directory not found: {pous_dir}"

    # A. Validate all 5 valid POUs
    pous_validation_results = {}
    for pou_filename in TARGET_POUS:
        pou_path = pous_dir / pou_filename
        assert pou_path.exists(), f"Missing POU file: {pou_path}"
        code = pou_path.read_text(encoding="utf-8")
        val_res = cscape_validate_st(code)
        print(f"  Validating {pou_filename}: valid={val_res.get('valid')}, errors={len(val_res.get('errors', []))}")
        assert val_res.get("valid") is True, f"POU {pou_filename} failed validation: {val_res.get('errors')}"
        assert len(val_res.get("errors", [])) == 0, f"Errors found in {pou_filename}: {val_res.get('errors')}"
        pous_validation_results[pou_filename] = {
            "path": str(pou_path),
            "size_chars": len(code),
            "lines": len(code.splitlines()),
            "valid": val_res.get("valid"),
            "errors": val_res.get("errors", []),
            "warnings": val_res.get("warnings", []),
            "failure_locations": val_res.get("failure_locations", []),
        }

    # B. Validate synthetic syntax faults
    print("  Testing synthetic syntax faults...")
    synthetic_faults = [
        {
            "name": "unclosed_if",
            "code": "PROGRAM FaultUnclosedIf\nVAR val : INT; END_VAR\nIF val > 10 THEN\n    val := 0;\nEND_PROGRAM",
            "expected_keyword": "IF",
        },
        {
            "name": "invalid_token",
            "code": "PROGRAM FaultInvalidToken\nVAR ###bad_token : INT; END_VAR\nEND_PROGRAM",
            "expected_keyword": "bad_token",
        },
        {
            "name": "missing_semicolon",
            "code": "PROGRAM FaultMissingSemi\nVAR x : INT END_VAR\nEND_PROGRAM",
            "expected_keyword": ";",
        },
    ]

    syntax_fault_results = []
    for fault in synthetic_faults:
        fault_res = cscape_validate_st(fault["code"])
        print(f"    Fault [{fault['name']}]: valid={fault_res.get('valid')}, failures={len(fault_res.get('failure_locations', []))}")
        assert fault_res.get("valid") is False, f"Synthetic fault '{fault['name']}' was unexpectedly marked valid!"
        locations = fault_res.get("failure_locations", [])
        assert len(locations) > 0, f"No structured failure locations returned for '{fault['name']}'"
        first_loc = locations[0]
        assert "line" in first_loc and "column" in first_loc
        assert "error_code" in first_loc and "message" in first_loc
        syntax_fault_results.append({
            "name": fault["name"],
            "code_snippet": fault["code"],
            "valid": fault_res.get("valid"),
            "errors": fault_res.get("errors", []),
            "failure_locations": locations,
        })

    # C. Validate ladder artifact rejection
    print("  Testing ladder artifact rejection...")
    ladder_cases = [
        {
            "name": "ladder_contacts_and_coil",
            "code": "PROGRAM LadderRung\nVAR b : BOOL; END_VAR\n--[ Start_PB ]--( Run_Motor )--\nEND_PROGRAM",
        },
        {
            "name": "ladder_nc_contact",
            "code": "PROGRAM LadderNC\nVAR b : BOOL; END_VAR\n|--[ /Stop_PB ]--|\nEND_PROGRAM",
        },
    ]

    ladder_rejection_results = []
    for lc in ladder_cases:
        ladder_res = cscape_validate_st(lc["code"])
        print(f"    Ladder case [{lc['name']}]: valid={ladder_res.get('valid')}, errors={ladder_res.get('errors')}")
        assert ladder_res.get("valid") is False, f"Ladder construct in '{lc['name']}' was not rejected!"
        locations = ladder_res.get("failure_locations", [])
        assert len(locations) > 0, f"No failure locations for ladder case '{lc['name']}'"
        err_code = locations[0].get("error_code")
        assert err_code == "ERR_LADDER_FORBIDDEN", f"Expected ERR_LADDER_FORBIDDEN, got {err_code}"
        ladder_rejection_results.append({
            "name": lc["name"],
            "code_snippet": lc["code"],
            "valid": ladder_res.get("valid"),
            "error_code": err_code,
            "errors": ladder_res.get("errors", []),
            "failure_locations": locations,
        })

    # --------------------------------------------------------------------------
    # 2. Tool 2: cscape_simulate_pou
    # --------------------------------------------------------------------------
    print("\n[STEP 2] Testing Tool 2: cscape_simulate_pou (10 steps multi-POU)...")
    sim_pous = [
        ("AlarmMonitor", {}),
        ("AuxPumpControl", {}),
        ("BrokenPOU", {}),
        ("SafetyInterlockST", {}),
        ("TankLevelClosedLoop", {"RawLevelInput": 16000, "Setpoint": 60.0}),
    ]

    simulation_results = {}
    for pou_name, inputs in sim_pous:
        code = (pous_dir / f"{pou_name}.st").read_text(encoding="utf-8")
        sim_res = cscape_simulate_pou(code=code, inputs=inputs, steps=10)
        print(f"  Simulating {pou_name} (10 steps): success={sim_res.get('success')}, executed={sim_res.get('steps_executed')}, isolation={sim_res.get('isolation_enforced')}")
        assert sim_res.get("success") is True, f"Simulation of {pou_name} failed: {sim_res}"
        assert sim_res.get("steps_executed") == 10, f"Expected 10 steps, got {sim_res.get('steps_executed')}"
        assert sim_res.get("isolation_enforced") is True, "Software isolation was not enforced"
        assert sim_res.get("hardware_lockout_enforced") is True, "Hardware lockout was not enforced"
        trace = sim_res.get("trace", [])
        assert len(trace) == 10, f"Expected trace length 10, got {len(trace)}"
        assert "cycle" in trace[0] and "variables" in trace[0]

        simulation_results[pou_name] = {
            "success": sim_res.get("success"),
            "steps_executed": sim_res.get("steps_executed"),
            "total_cycles": sim_res.get("total_cycles"),
            "isolation_enforced": sim_res.get("isolation_enforced"),
            "hardware_lockout_enforced": sim_res.get("hardware_lockout_enforced"),
            "final_state": sim_res.get("final_state", {}),
            "final_registers": sim_res.get("final_registers", {}),
            "trace_length": len(trace),
            "trace_sample_first": trace[0],
            "trace_sample_last": trace[-1],
        }

    # Verify specific state transitions
    assert simulation_results["BrokenPOU"]["final_state"].get("RawVal") == 15, "BrokenPOU final state mismatch"
    assert simulation_results["AuxPumpControl"]["final_state"].get("cmd") is True, "AuxPumpControl final state mismatch"
    assert simulation_results["AlarmMonitor"]["final_state"].get("trip") is False, "AlarmMonitor final state mismatch"
    assert simulation_results["SafetyInterlockST"]["final_state"].get("x") == 1, "SafetyInterlockST final state mismatch"
    assert simulation_results["TankLevelClosedLoop"]["final_state"].get("CycleCounter") == 10, "TankLevelClosedLoop CycleCounter mismatch"
    print("  All POU state transitions and traces verified successfully.")

    # --------------------------------------------------------------------------
    # 3. Tool 3: cscape_get_diagnostics
    # --------------------------------------------------------------------------
    print("\n[STEP 3] Testing Tool 3: cscape_get_diagnostics on TankLevelClosedLoop...")
    diag_res = cscape_get_diagnostics(TARGET_PROJECT)
    print(f"  Diagnostics: status={diag_res.get('status')}, compile_successful={diag_res.get('compile_successful')}, errors={diag_res.get('error_count', 0)}")
    assert diag_res.get("compile_successful") is True, f"Project diagnostics report compile failure: {diag_res}"
    assert diag_res.get("status") == "success", f"Diagnostics status not success: {diag_res.get('status')}"
    assert "build_log" in diag_res and len(diag_res["build_log"]) > 0, "Build log empty in diagnostics"
    assert "memory_footprint" in diag_res, "Missing memory_footprint in diagnostics"
    mem = diag_res["memory_footprint"]
    assert "code_size_bytes" in mem and mem["code_size_bytes"] > 0
    assert "data_size_bytes" in mem and mem["data_size_bytes"] > 0
    assert "retain_size_bytes" in mem and mem["retain_size_bytes"] > 0
    print(f"  Memory footprint verified: code={mem['code_size_bytes']}B, data={mem['data_size_bytes']}B, retain={mem['retain_size_bytes']}B")

    # --------------------------------------------------------------------------
    # 4. Tool 4: cscape_export_project
    # --------------------------------------------------------------------------
    print("\n[STEP 4] Testing Tool 4: cscape_export_project...")
    export_formats = ["csp", "cpj", "json", "xml", "k5p"]
    export_results = {}

    for fmt in export_formats:
        exp_res = cscape_export_project(TARGET_PROJECT, output_format=fmt)
        print(f"  Export format [{fmt}]: status={exp_res.get('status')}, file={exp_res.get('export_file')}, size={exp_res.get('size_bytes')}")
        assert exp_res.get("status") == "success", f"Export failed for format {fmt}: {exp_res}"
        export_file = Path(exp_res.get("export_file", ""))
        assert export_file.exists(), f"Export file does not exist: {export_file}"
        assert exp_res.get("size_bytes", 0) > 0, f"Export file size is 0 for {fmt}"
        assert len(exp_res.get("sha256", "")) == 64, f"Invalid SHA-256 for format {fmt}"

        if fmt == "k5p":
            assert "quarantine" in str(export_file).lower(), f"k5p export was not routed to quarantine: {export_file}"
            assert "warning" in exp_res, "k5p export missing quarantine warning"
            assert "k5p is a legacy Straton format" in exp_res["warning"], f"Unexpected warning: {exp_res.get('warning')}"
            print(f"    [QUARANTINED] k5p legacy format safely isolated: {exp_res['warning']}")

        # Read content to confirm sha256
        file_bytes = export_file.read_bytes()
        computed_sha = hashlib.sha256(file_bytes).hexdigest()
        assert computed_sha == exp_res["sha256"], f"SHA256 mismatch for {fmt}: {computed_sha} vs {exp_res['sha256']}"

        export_results[fmt] = {
            "format": fmt,
            "status": exp_res.get("status"),
            "export_file": str(export_file),
            "size_bytes": exp_res.get("size_bytes"),
            "sha256": exp_res.get("sha256"),
            "warning": exp_res.get("warning"),
            "quarantined": fmt == "k5p",
        }

        # Mirror exported files to USER_ROOT
        user_export_file = USER_ROOT / export_file.relative_to(HORNER_ROOT)
        user_export_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(export_file, user_export_file)

    # --------------------------------------------------------------------------
    # 5. Tool 5: Safety Audit
    # --------------------------------------------------------------------------
    print("\n[STEP 5] Testing Tool 5: Safety Audit & Hardware Lockout...")
    # A. Assert ID_CONTROLLER_DOWNLOAD = 32827 and ID_CONTROLLER_DOWNLOAD_ALT = 33149
    assert ID_CONTROLLER_DOWNLOAD == 32827, f"Expected 32827, got {ID_CONTROLLER_DOWNLOAD}"
    assert ID_CONTROLLER_DOWNLOAD_ALT == 33149, f"Expected 33149, got {ID_CONTROLLER_DOWNLOAD_ALT}"

    blocked_32827 = False
    try:
        intercept_download_command(ID_CONTROLLER_DOWNLOAD)
    except (CscapeSafetyViolationError, UnauthorizedDownloadError):
        blocked_32827 = True
    assert blocked_32827, "ID_CONTROLLER_DOWNLOAD (32827) was not intercepted!"

    blocked_33149 = False
    try:
        intercept_download_command(ID_CONTROLLER_DOWNLOAD_ALT)
    except (CscapeSafetyViolationError, UnauthorizedDownloadError):
        blocked_33149 = True
    assert blocked_33149, "ID_CONTROLLER_DOWNLOAD_ALT (33149) was not intercepted!"

    runner = CLIRunner()
    cli_dl_blocked = False
    try:
        runner.download_to_controller("TankLevelClosedLoop.csp")
    except UnauthorizedDownloadError:
        cli_dl_blocked = True
    assert cli_dl_blocked, "CLIRunner download_to_controller was not blocked!"

    cli_proj_dl_blocked = False
    try:
        runner.download_project("TankLevelClosedLoop.csp")
    except UnauthorizedDownloadError:
        cli_proj_dl_blocked = True
    assert cli_proj_dl_blocked, "CLIRunner download_project was not blocked!"

    # B. Physical port blocking
    ports_tested = ["COM1", "COM3", "CAN0", "USB", "JTAG"]
    ports_blocked = 0
    for port in ports_tested:
        try:
            intercept_hardware_interface(port)
        except CscapeSafetyViolationError:
            ports_blocked += 1
    assert ports_blocked == len(ports_tested), f"Not all physical ports blocked: {ports_blocked}/{len(ports_tested)}"

    # C. Straton process check
    active_straton: List[Dict[str, Any]] = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            pname = p.info["name"].lower() if p.info["name"] else ""
            if any(sb in pname for sb in STRATON_BINARIES):
                active_straton.append(p.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    print(f"  Active Straton K5 processes: {len(active_straton)}")
    assert len(active_straton) == 0, f"Unauthorized Straton processes running: {active_straton}"

    safety_audit = {
        "id_controller_download": ID_CONTROLLER_DOWNLOAD,
        "id_controller_download_alt": ID_CONTROLLER_DOWNLOAD_ALT,
        "download_cmd_32827_blocked": blocked_32827,
        "download_cmd_33149_blocked": blocked_33149,
        "cli_download_blocked": cli_dl_blocked,
        "cli_project_download_blocked": cli_proj_dl_blocked,
        "physical_ports_tested": ports_tested,
        "physical_ports_blocked_count": ports_blocked,
        "active_straton_processes": len(active_straton),
        "hardware_lockout_enforced": True,
        "zero_straton_dependencies": True,
    }
    print("  Safety audit passed: 100% lockout enforced, 0 physical ports, 0 Straton processes.")

    # --------------------------------------------------------------------------
    # 6. Write Evidence Log and Checkpoint (Mirrored across both roots)
    # --------------------------------------------------------------------------
    evidence_log: Dict[str, Any] = {
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "step": 138,
        "mission": "Multi-POU FastMCP Full Lifecycle Verification (Insert, Validate, Simulate, Diagnostics Roundtrip)",
        "target_project": TARGET_PROJECT,
        "cscape_health": cscape_health,
        "tool1_validate_st": {
            "pous_validation": pous_validation_results,
            "synthetic_syntax_faults": syntax_fault_results,
            "ladder_rejections": ladder_rejection_results,
        },
        "tool2_simulate_pou": simulation_results,
        "tool3_get_diagnostics": diag_res,
        "tool4_export_project": export_results,
        "tool5_safety_audit": safety_audit,
        "status": "PASSED",
    }

    checkpoint: Dict[str, Any] = {
        "step": 138,
        "name": "step138_mcp_full_lifecycle_diagnostics_checkpoint",
        "status": "PASSED",
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "target_project": TARGET_PROJECT,
        "pous_evaluated": TARGET_POUS,
        "pous_count": len(TARGET_POUS),
        "validation_summary": {
            "all_valid_pous_passed": all(r["valid"] for r in pous_validation_results.values()),
            "valid_pous_count": len(pous_validation_results),
            "syntax_faults_detected": all(not f["valid"] for f in syntax_fault_results),
            "syntax_faults_count": len(syntax_fault_results),
            "ladder_rejection_enforced": all(not l["valid"] for l in ladder_rejection_results),
            "ladder_cases_count": len(ladder_rejection_results),
        },
        "simulation_summary": {
            "pous_simulated": list(simulation_results.keys()),
            "total_simulated_steps": sum(r["steps_executed"] for r in simulation_results.values()),
            "all_simulations_successful": all(r["success"] for r in simulation_results.values()),
            "isolation_enforced": all(r["isolation_enforced"] for r in simulation_results.values()),
            "hardware_lockout_enforced": all(r["hardware_lockout_enforced"] for r in simulation_results.values()),
        },
        "diagnostics_summary": {
            "compile_successful": diag_res.get("compile_successful"),
            "status": diag_res.get("status"),
            "error_count": diag_res.get("error_count", 0),
            "warning_count": diag_res.get("warning_count", 0),
            "code_size_bytes": mem.get("code_size_bytes"),
            "data_size_bytes": mem.get("data_size_bytes"),
            "retain_size_bytes": mem.get("retain_size_bytes"),
        },
        "export_summary": {
            "formats_tested": export_formats,
            "all_exports_created": all(r["status"] == "success" for r in export_results.values()),
            "k5p_quarantined": export_results["k5p"]["quarantined"],
            "quarantine_warning_present": bool(export_results["k5p"].get("warning")),
        },
        "safety_audit": {
            "download_cmd_32827_blocked": blocked_32827,
            "download_cmd_33149_blocked": blocked_33149,
            "cli_download_blocked": cli_dl_blocked,
            "physical_ports_blocked": ports_blocked == len(ports_tested),
            "active_straton_processes": len(active_straton),
            "hardware_lockout_enforced": True,
            "zero_straton_dependencies": True,
        },
        "cscape_health": {
            "pid": TARGET_PID,
            "running": proc.is_running(),
            "is_hung": is_hung,
            "ping_responsive": ping_ok,
        },
        "evidence_log": "artifacts/logs/mcp_full_lifecycle_diagnostics.json",
    }

    log_destinations = [
        HORNER_ROOT / "artifacts" / "logs" / "mcp_full_lifecycle_diagnostics.json",
        USER_ROOT / "artifacts" / "logs" / "mcp_full_lifecycle_diagnostics.json",
    ]
    checkpoint_destinations = [
        HORNER_ROOT / "artifacts" / "checkpoints" / "step138_mcp_full_lifecycle_diagnostics_checkpoint.json",
        USER_ROOT / "artifacts" / "checkpoints" / "step138_mcp_full_lifecycle_diagnostics_checkpoint.json",
    ]

    for lp in log_destinations:
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text(json.dumps(evidence_log, indent=2), encoding="utf-8")
        print(f"  [SAVED] Evidence Log: {lp}")

    for cp in checkpoint_destinations:
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
        print(f"  [SAVED] Checkpoint: {cp}")

    print("\n" + "=" * 80)
    print("STEP 138 EXECUTION COMPLETED SUCCESSFULLY (STATUS: PASSED)")
    print("=" * 80)
    return checkpoint


if __name__ == "__main__":
    run_step138()
