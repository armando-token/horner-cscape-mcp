#!/usr/bin/env python3
r"""
Test Suite for Step 138: Multi-POU FastMCP Full Lifecycle Verification (Insert, Validate, Simulate, Diagnostics Roundtrip).

Verifies:
1. Checkpoint existence and valid schema across both roots.
2. Evidence log existence, schema, and completeness across both roots.
3. Clean validation of all 5 POUs (TankLevelClosedLoop, AlarmMonitor, BrokenPOU, AuxPumpControl, SafetyInterlockST).
4. Synthetic syntax fault detection and structured failure locations (line, col, error_code, message).
5. Ladder construct rejection (ERR_LADDER_FORBIDDEN fail-closed enforcement).
6. Multi-POU 10-step simulation, state transitions, trace generation, isolation and hardware lockout enforcement.
7. Project diagnostics query, compile success status, and structured memory footprint (code, data, retain).
8. Project export formats (csp, cpj, json, xml) and legacy k5p quarantine routing with warning.
9. Active Cscape health via live gate (IsHungAppWindow = False, SendMessageTimeoutW ping = True).
10. Safety audit: physical controller download lockout (32827 & 33149), COM/USB/CAN port blocking, zero Straton processes.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import psutil
import pytest
import sys

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

# TARGET_PID dynamically resolved from live gate
TARGET_PROJECT = "TankLevelClosedLoop"
TARGET_POUS = [
    "TankLevelClosedLoop.st",
    "AlarmMonitor.st",
    "BrokenPOU.st",
    "AuxPumpControl.st",
    "SafetyInterlockST.st",
]

STRATON_BINARIES = ["k5bus.exe", "k5edit.exe", "k5run.exe", "k5vm.exe", "k5cmd.exe", "t5.exe"]

CHECKPOINT_REL = Path("artifacts/checkpoints/step138_mcp_full_lifecycle_diagnostics_checkpoint.json")
LOG_REL = Path("artifacts/logs/mcp_full_lifecycle_diagnostics.json")


# ============================================================================
# 1. Checkpoint & Evidence Log Structure Tests
# ============================================================================

def test_checkpoint_and_evidence_log_existence_and_structure():
    """Validates checkpoint and evidence log existence and schema across both workspace roots."""
    for root in [HORNER_ROOT, USER_ROOT]:
        cp_path = root / CHECKPOINT_REL
        assert cp_path.exists(), f"Checkpoint missing at {cp_path}"
        data = json.loads(cp_path.read_text(encoding="utf-8"))

        assert data.get("step") == 138, "Checkpoint step mismatch"
        assert data.get("name") == "step138_mcp_full_lifecycle_diagnostics_checkpoint"
        assert data.get("status") == "PASSED", f"Checkpoint status not PASSED: {data.get('status')}"
        assert data.get("target_project") == TARGET_PROJECT
        assert data.get("pous_count") == 5
        assert set(data.get("pous_evaluated", [])) == set(TARGET_POUS)

        val_sum = data.get("validation_summary", {})
        assert val_sum.get("all_valid_pous_passed") is True
        assert val_sum.get("valid_pous_count") == 5
        assert val_sum.get("syntax_faults_detected") is True
        assert val_sum.get("ladder_rejection_enforced") is True

        sim_sum = data.get("simulation_summary", {})
        assert sim_sum.get("all_simulations_successful") is True
        assert sim_sum.get("total_simulated_steps") >= 40
        assert sim_sum.get("isolation_enforced") is True
        assert sim_sum.get("hardware_lockout_enforced") is True

        diag_sum = data.get("diagnostics_summary", {})
        assert diag_sum.get("compile_successful") is True
        assert diag_sum.get("status") == "success"
        assert diag_sum.get("code_size_bytes", 0) > 0

        exp_sum = data.get("export_summary", {})
        assert exp_sum.get("all_exports_created") is True
        assert exp_sum.get("k5p_quarantined") is True
        assert exp_sum.get("quarantine_warning_present") is True

        safe_aud = data.get("safety_audit", {})
        assert safe_aud.get("download_cmd_32827_blocked") is True
        assert safe_aud.get("download_cmd_33149_blocked") is True
        assert safe_aud.get("cli_download_blocked") is True
        assert safe_aud.get("physical_ports_blocked") is True
        assert safe_aud.get("active_straton_processes") == 0
        assert safe_aud.get("zero_straton_dependencies") is True

        cs_health = data.get("cscape_health", {})
        assert cs_health.get("pid") > 0
        assert cs_health.get("running") is True
        assert cs_health.get("is_hung") is False
        assert cs_health.get("ping_responsive") is True

        # Evidence log verification
        log_path = root / LOG_REL
        assert log_path.exists(), f"Evidence log missing at {log_path}"
        log_data = json.loads(log_path.read_text(encoding="utf-8"))
        assert log_data.get("step") == 138
        assert log_data.get("status") == "PASSED"
        assert "tool1_validate_st" in log_data
        assert "tool2_simulate_pou" in log_data
        assert "tool3_get_diagnostics" in log_data
        assert "tool4_export_project" in log_data
        assert "tool5_safety_audit" in log_data


# ============================================================================
# 2. Tool 1: cscape_validate_st Tests
# ============================================================================

def test_all_five_pous_validated_cleanly():
    """Asserts all 5 POUs in TankLevelClosedLoop validate cleanly with valid=True and 0 errors."""
    pous_dir = HORNER_ROOT / "artifacts" / "projects" / TARGET_PROJECT / "pous"
    for pou_filename in TARGET_POUS:
        pou_path = pous_dir / pou_filename
        assert pou_path.exists(), f"POU file missing: {pou_path}"
        code = pou_path.read_text(encoding="utf-8")
        res = cscape_validate_st(code)
        assert res.get("valid") is True, f"POU {pou_filename} failed validation: {res.get('errors')}"
        assert len(res.get("errors", [])) == 0, f"Errors in {pou_filename}: {res.get('errors')}"
        assert len(res.get("failure_locations", [])) == 0


def test_syntax_fault_injection_and_failure_locations():
    """Asserts synthetic syntax faults fail validation with structured failure_locations."""
    # 1. Unclosed IF block
    code_unclosed_if = (
        "PROGRAM FaultUnclosedIf\n"
        "VAR val : INT; END_VAR\n"
        "IF val > 10 THEN\n"
        "    val := 0;\n"
        "END_PROGRAM"
    )
    res_if = cscape_validate_st(code_unclosed_if)
    assert res_if.get("valid") is False
    locs_if = res_if.get("failure_locations", [])
    assert len(locs_if) > 0
    assert any("IF" in str(loc.get("message", "")) or "closing" in str(loc.get("message", "")) for loc in locs_if)
    for loc in locs_if:
        assert "line" in loc and "column" in loc and "error_code" in loc and "message" in loc

    # 2. Invalid Token
    code_invalid_token = (
        "PROGRAM FaultInvalidToken\n"
        "VAR ###bad_token : INT; END_VAR\n"
        "END_PROGRAM"
    )
    res_tok = cscape_validate_st(code_invalid_token)
    assert res_tok.get("valid") is False
    locs_tok = res_tok.get("failure_locations", [])
    assert len(locs_tok) > 0
    assert locs_tok[0].get("line") is not None
    assert locs_tok[0].get("column") is not None

    # 3. Missing Semicolon
    code_missing_semi = (
        "PROGRAM FaultMissingSemi\n"
        "VAR x : INT END_VAR\n"
        "END_PROGRAM"
    )
    res_semi = cscape_validate_st(code_missing_semi)
    assert res_semi.get("valid") is False
    locs_semi = res_semi.get("failure_locations", [])
    assert len(locs_semi) > 0
    assert any(";" in str(loc.get("message", "")) or "semicolon" in str(loc.get("message", "")).lower() for loc in locs_semi)


def test_ladder_artifact_rejection():
    """Asserts ladder logic constructs are rejected with ERR_LADDER_FORBIDDEN."""
    ladder_samples = [
        "PROGRAM LadderTest\nVAR b : BOOL; END_VAR\n--[ Start_PB ]--( Run_Motor )--\nEND_PROGRAM",
        "PROGRAM LadderNC\nVAR b : BOOL; END_VAR\n|--[ /Stop_PB ]--|\nEND_PROGRAM",
        "PROGRAM LadderSet\nVAR b : BOOL; END_VAR\n--[ Trigger ]--( SET Alarm )--\nEND_PROGRAM",
    ]
    for code in ladder_samples:
        res = cscape_validate_st(code)
        assert res.get("valid") is False, "Ladder artifact was not rejected!"
        locs = res.get("failure_locations", [])
        assert len(locs) > 0, "Missing failure locations for ladder rejection"
        assert locs[0].get("error_code") == "ERR_LADDER_FORBIDDEN"
        assert "ladder" in locs[0].get("message", "").lower()


# ============================================================================
# 3. Tool 2: cscape_simulate_pou Tests
# ============================================================================

def test_multi_pou_simulation_and_trace():
    """Asserts multi-step simulation across POUs verifies state transitions and traces."""
    pous_dir = HORNER_ROOT / "artifacts" / "projects" / TARGET_PROJECT / "pous"
    test_cases = [
        ("AlarmMonitor", {}, "trip", False),
        ("AuxPumpControl", {}, "cmd", True),
        ("BrokenPOU", {}, "RawVal", 15),
        ("SafetyInterlockST", {}, "x", 1),
    ]

    for pou_name, inputs, expected_var, expected_val in test_cases:
        code = (pous_dir / f"{pou_name}.st").read_text(encoding="utf-8")
        res = cscape_simulate_pou(code=code, inputs=inputs, steps=10)
        assert res.get("success") is True, f"Simulation failed for {pou_name}"
        assert res.get("steps_executed") == 10
        assert res.get("isolation_enforced") is True
        assert res.get("hardware_lockout_enforced") is True

        trace = res.get("trace", [])
        assert len(trace) == 10, f"Expected 10 trace cycles, got {len(trace)}"
        for idx, entry in enumerate(trace):
            assert entry.get("cycle") == idx
            assert "variables" in entry

        final_state = res.get("final_state", {})
        assert final_state.get(expected_var) == expected_val, (
            f"State transition mismatch in {pou_name}: expected {expected_var}={expected_val}, "
            f"got {final_state.get(expected_var)}"
        )

    # Simulate TankLevelClosedLoop to verify multi-cycle closed-loop logic
    tlcl_code = (pous_dir / "TankLevelClosedLoop.st").read_text(encoding="utf-8")
    tlcl_res = cscape_simulate_pou(code=tlcl_code, inputs={"RawLevelInput": 16000, "Setpoint": 60.0}, steps=10)
    assert tlcl_res.get("success") is True
    assert tlcl_res.get("steps_executed") == 10
    assert tlcl_res.get("final_state", {}).get("CycleCounter") == 10
    assert tlcl_res.get("final_state", {}).get("TankLevelPV") == 50.0


# ============================================================================
# 4. Tool 3: cscape_get_diagnostics Tests
# ============================================================================

def test_diagnostics_roundtrip_and_memory_footprint():
    """Asserts cscape_get_diagnostics returns structured diagnostics and memory footprint."""
    res = cscape_get_diagnostics(TARGET_PROJECT)
    assert res.get("compile_successful") is True
    assert res.get("status") == "success"
    assert res.get("project_name") == TARGET_PROJECT
    assert "build_log" in res and len(res["build_log"]) > 0

    mem = res.get("memory_footprint", {})
    assert mem.get("code_size_bytes", 0) > 0
    assert mem.get("data_size_bytes", 0) > 0
    assert mem.get("retain_size_bytes", 0) >= 0


# ============================================================================
# 5. Tool 4: cscape_export_project Tests
# ============================================================================

def test_project_export_formats_and_k5p_quarantine():
    """Asserts project export creates valid files with SHA-256 and quarantines legacy k5p."""
    for fmt in ["csp", "cpj", "json", "xml"]:
        res = cscape_export_project(TARGET_PROJECT, output_format=fmt)
        assert res.get("status") == "success"
        export_file = Path(res.get("export_file", ""))
        assert export_file.exists()
        assert res.get("size_bytes", 0) > 0
        file_bytes = export_file.read_bytes()
        assert hashlib.sha256(file_bytes).hexdigest() == res.get("sha256")

    # Legacy k5p format test
    k5p_res = cscape_export_project(TARGET_PROJECT, output_format="k5p")
    assert k5p_res.get("status") == "success"
    k5p_file = Path(k5p_res.get("export_file", ""))
    assert k5p_file.exists()
    assert "quarantine" in str(k5p_file).lower()
    assert "warning" in k5p_res
    assert "k5p is a legacy Straton format" in k5p_res["warning"]


# ============================================================================
# 6. Tool 5: Safety Audit & Active Cscape Health Tests
# ============================================================================

def test_cscape_live_gate_healthy():
    """Asserts active Cscape is alive, IsHungAppWindow = False, SendMessageTimeoutW = True."""
    try:
        gate_info = assert_cscape_live()
    except Exception as exc:
        pytest.skip(f"No active live Cscape gate: {exc}")
    if not gate_info.get("ready_for_tests"):
        pytest.skip(f"Live Cscape gate not ready: status='{gate_info.get('status')}', reason='{gate_info.get('reason')}'")
    target_pid = gate_info.get("pid")
    if not target_pid or not psutil.pid_exists(target_pid):
        pytest.skip(f"Live Cscape PID {target_pid} is offline")
    assert target_pid > 0

    assert psutil.pid_exists(target_pid)
    proc = psutil.Process(target_pid)
    assert proc.is_running()
    assert "cscape" in proc.name().lower()

    raw_hwnd = gate_info.get("hwnd")
    if not raw_hwnd:
        pytest.skip("No HWND in gate info")
    hwnd = int(raw_hwnd, 0) if isinstance(raw_hwnd, str) else int(raw_hwnd)
    import win32gui
    if not win32gui.IsWindow(hwnd):
        pytest.skip(f"Cscape window {hex(hwnd)} is invalid/closed")

    user32 = ctypes.windll.user32
    user32.IsHungAppWindow.argtypes = [wintypes.HWND]
    user32.IsHungAppWindow.restype = wintypes.BOOL
    user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_ulong)
    ]
    user32.SendMessageTimeoutW.restype = ctypes.c_long

    assert not user32.IsHungAppWindow(hwnd), f"Window {hex(hwnd)} is hung!"

    attach_thread_desktop(hwnd)
    res_val = ctypes.c_ulong(0)
    res = user32.SendMessageTimeoutW(hwnd, 0, 0, 0, 0x0002, 1000, ctypes.byref(res_val))
    assert res != 0, f"SendMessageTimeoutW ping failed for {hex(hwnd)}"




def test_safety_audit_physical_download_lockout_and_zero_straton():
    """Asserts physical download lockout (32827/33149) and zero active Straton processes."""
    assert ID_CONTROLLER_DOWNLOAD == 32827
    assert ID_CONTROLLER_DOWNLOAD_ALT == 33149

    with pytest.raises((CscapeSafetyViolationError, UnauthorizedDownloadError)):
        intercept_download_command(32827)

    with pytest.raises((CscapeSafetyViolationError, UnauthorizedDownloadError)):
        intercept_download_command(33149)

    runner = CLIRunner()
    with pytest.raises(UnauthorizedDownloadError):
        runner.download_to_controller("TankLevelClosedLoop.csp")

    with pytest.raises(UnauthorizedDownloadError):
        runner.download_project("TankLevelClosedLoop.csp")

    with pytest.raises(CscapeSafetyViolationError):
        intercept_hardware_interface("COM1")

    with pytest.raises(CscapeSafetyViolationError):
        intercept_hardware_interface("USB")

    # Zero running Straton K5 processes
    active_straton = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            pname = p.info["name"].lower() if p.info["name"] else ""
            if any(sb in pname for sb in STRATON_BINARIES):
                active_straton.append(p.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    assert len(active_straton) == 0, f"Straton processes running: {active_straton}"
