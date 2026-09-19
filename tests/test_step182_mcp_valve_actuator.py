"""Test Suite for Step 182: FastMCP Industrial Valve Actuator Controller Simulation Audit."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import sys
import pytest

HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()

for r in [str(HORNER_ROOT), str(USER_ROOT)]:
    if r not in sys.path:
        sys.path.insert(0, r)

from src.cscape.gate import get_gate_status
from src.cscape.safety import (
    ID_CONTROLLER_DOWNLOAD,
    ID_CONTROLLER_DOWNLOAD_ALT,
    BLOCKED_DOWNLOAD_COMMAND_IDS,
)
from src.security.guard import SafetyGuard
from src.security.exceptions import HardwareLockoutError, UnauthorizedDownloadError
from scripts.execute_step182_mcp_valve_actuator import (
    FBValveActuator,
    run_step182_mcp_valve_actuator,
    ST_FILE,
    LOG_PATHS,
    CHECKPOINT_PATHS,
    compute_sha256,
)


def test_st_source_file_exists():
    """Verify ST source file exists in both roots and matches SHA256."""
    assert ST_FILE.exists(), f"ST file missing: {ST_FILE}"
    content = ST_FILE.read_text(encoding="utf-8")
    assert "FUNCTION_BLOCK FB_ValveActuator" in content
    assert "Industrial Process Valve Actuator Controller" in content
    sha = compute_sha256(ST_FILE.read_bytes())
    assert sha == "d42e07a1a149d696839e6b2d470c0939a2cf16bd442379b0161331402a1a3dc2"


def test_st_source_pure_iec_no_ladder():
    """Enforce pure IEC 61131-3 Structured Text without ladder logic."""
    content = ST_FILE.read_text(encoding="utf-8")
    assert "---[ ]---" not in content, "Ladder contact detected!"
    assert "---( )---" not in content, "Ladder coil detected!"
    assert "---[/]---" not in content, "Inverted contact detected!"
    assert "ERR_LADDER_FORBIDDEN" not in content


def test_invariant_a_normal_stroke_and_cycle_count():
    """Invariant A: Normal stroke open and close, transit timing, and cycle count increment."""
    fb = FBValveActuator(cycle_time_sec=0.1)
    fb.TransitTimeoutSec = 12.0
    fb.step()
    assert fb.IsClosed is True
    assert fb.IsOpen is False
    assert fb.TotalCycles == 0

    # 1. Open stroke
    fb.OpenCmd = True
    fb.step()
    assert fb.SolOpen is True
    assert fb.IsTraveling is True

    fb.LimitClosed = False  # Left closed seat

    # Stroke for 5.0 seconds
    for _ in range(50):
        fb.step()
        assert fb.SolOpen is True
        assert fb.IsTraveling is True

    # Strikes open limit switch
    fb.LimitOpen = True
    fb.step()
    assert fb.SolOpen is False
    assert fb.IsTraveling is False
    assert fb.IsOpen is True
    assert fb.IsClosed is False
    assert abs(fb.TransitTimeSec - 5.1) < 0.2
    assert fb.TotalCycles == 1

    # 2. Close stroke
    fb.OpenCmd = False
    fb.CloseCmd = True
    fb.step()
    assert fb.SolClose is True
    assert fb.IsTraveling is True

    fb.LimitOpen = False  # Left open seat

    # Stroke for 4.0 seconds
    for _ in range(40):
        fb.step()
        assert fb.SolClose is True
        assert fb.IsTraveling is True

    # Strikes closed limit switch
    fb.LimitClosed = True
    fb.step()
    assert fb.SolClose is False
    assert fb.IsTraveling is False
    assert fb.IsClosed is True
    assert fb.IsOpen is False
    assert abs(fb.TransitTimeSec - 4.1) < 0.2
    assert fb.TotalCycles == 1


def test_invariant_b_travel_timeout_jammed_valve():
    """Invariant B: Jammed / slow-stroking valve timeout detection (TravelFault when stroke > TransitTimeoutSec)."""
    fb = FBValveActuator(cycle_time_sec=0.1)
    fb.TransitTimeoutSec = 4.0
    fb.OpenCmd = True
    fb.step()
    fb.LimitClosed = False

    # Simulate jam at 35% travel: 4.5 seconds elapse without LimitOpen
    for _ in range(45):
        fb.step()

    assert fb.TravelFault is True
    assert fb.SolOpen is False  # Fails safe
    assert fb.IsTraveling is False
    assert fb.IsOpen is False
    assert fb.IsClosed is False


def test_invariant_c_dual_limit_switch_fault_and_motion_inhibit():
    """Invariant C: Dual-limit sensor inconsistency fault detection (SwitchFault when LimitOpen and LimitClosed)."""
    fb = FBValveActuator(cycle_time_sec=0.1)
    fb.LimitOpen = True
    fb.LimitClosed = True
    fb.step()

    assert fb.SwitchFault is True
    assert fb.IsOpen is False
    assert fb.IsClosed is False

    # Verify motion is inhibited
    fb.OpenCmd = True
    fb.step()
    assert fb.SolOpen is False

    fb.OpenCmd = False
    fb.CloseCmd = True
    fb.step()
    assert fb.SolClose is False


def test_invariant_d_safety_interlock_inhibit():
    """Invariant D: Safety interlock motion inhibit (InterlockOpen/Close prevents motion)."""
    fb = FBValveActuator(cycle_time_sec=0.1)
    fb.LimitClosed = True
    fb.LimitOpen = False
    fb.InterlockOpen = False

    # Open commanded while interlock active
    fb.OpenCmd = True
    fb.step()
    assert fb.SolOpen is False
    assert fb.IsTraveling is False

    # Interlock released, open stroke completed
    fb.InterlockOpen = True
    fb.step()
    fb.LimitClosed = False
    fb.LimitOpen = True
    fb.step()
    assert fb.IsOpen is True

    # Close commanded while close interlock active
    fb.InterlockClose = False
    fb.OpenCmd = False
    fb.CloseCmd = True
    fb.step()
    assert fb.SolClose is False
    assert fb.IsTraveling is False


def test_invariant_e_solenoid_pulse_mode_vs_continuous():
    """Invariant E: Solenoid pulse mode vs continuous mode energization."""
    fb_pulse = FBValveActuator(cycle_time_sec=0.1)
    fb_pulse.PulseMode = True
    fb_pulse.PulseDurationSec = 1.0
    fb_pulse.TransitTimeoutSec = 10.0
    fb_pulse.OpenCmd = True
    fb_pulse.step()
    fb_pulse.LimitClosed = False

    # Within pulse window (t <= 1.0s)
    for _ in range(9):
        fb_pulse.step()
        assert fb_pulse.SolOpen is True

    # Past pulse window (t = 1.2s > 1.0s)
    for _ in range(3):
        fb_pulse.step()
    assert fb_pulse.SolOpen is False
    assert fb_pulse.IsTraveling is True

    # Continuous mode comparison
    fb_cont = FBValveActuator(cycle_time_sec=0.1)
    fb_cont.PulseMode = False
    fb_cont.OpenCmd = True
    fb_cont.step()
    fb_cont.LimitClosed = False
    for _ in range(15):
        fb_cont.step()
    assert fb_cont.SolOpen is True


def test_invariant_f_fault_reset_interlock():
    """Invariant F: Fault reset interlock (ResetFault clears faults)."""
    fb = FBValveActuator(cycle_time_sec=0.1)
    fb.TravelFault = True
    fb.SwitchFault = True
    fb.LimitOpen = False
    fb.LimitClosed = True

    fb.ResetFault = True
    fb.step()
    assert fb.TravelFault is False
    assert fb.SwitchFault is False

    fb.ResetFault = False
    fb.step()
    assert fb.TravelFault is False
    assert fb.SwitchFault is False


def test_invariant_h_fail_closed_hardware_lockout():
    """Invariant H: Fail-closed download lockout for commands 32827 and 33149."""
    assert 32827 in BLOCKED_DOWNLOAD_COMMAND_IDS
    assert 33149 in BLOCKED_DOWNLOAD_COMMAND_IDS

    guard = SafetyGuard()
    with pytest.raises(UnauthorizedDownloadError):
        guard.validate_download("/download")


def test_step182_checkpoints_and_logs_parity():
    """Verify dual root parity of Step 182 checkpoint and log files."""
    for cp_path in CHECKPOINT_PATHS:
        assert cp_path.exists(), f"Missing checkpoint: {cp_path}"
    assert CHECKPOINT_PATHS[0].read_bytes() == CHECKPOINT_PATHS[1].read_bytes()

    for log_path in LOG_PATHS:
        assert log_path.exists(), f"Missing log: {log_path}"
    assert LOG_PATHS[0].read_bytes() == LOG_PATHS[1].read_bytes()

    cp_data = json.loads(CHECKPOINT_PATHS[0].read_text(encoding="utf-8"))
    assert cp_data["step"] == 182
    assert cp_data["gate"] == "G4"
    assert cp_data["status"] == "success"
    assert cp_data["dual_root_parity"] is True
    assert cp_data["hardware_safety"]["zero_physical_plc"] is True
    assert cp_data["hardware_safety"]["download_lockout_enforced"] is True


def test_megaplan_g4_log_schema_keys():
    """Ensure megaplan_g4_closed_loop_simulation.json satisfies test_gate_g3_g4_verification requirements."""
    g4_log_h = HORNER_ROOT / "artifacts" / "logs" / "megaplan_g4_closed_loop_simulation.json"
    g4_log_u = USER_ROOT / "artifacts" / "logs" / "megaplan_g4_closed_loop_simulation.json"

    assert g4_log_h.exists()
    assert g4_log_u.exists()
    assert g4_log_h.read_bytes() == g4_log_u.read_bytes()

    log_data = json.loads(g4_log_h.read_text(encoding="utf-8"))
    assert log_data["gate"] == "G4"
    assert log_data["status"] == "success"
    assert log_data["simulation_results"]["hh_trip_verified"] is True
    assert log_data["simulation_results"]["ll_dry_run_verified"] is True
    assert log_data["simulation_results"]["hysteresis_deadbands_verified"] is True
    assert log_data["concurrency_results"]["straton_tools_count"] == 0
    assert log_data["concurrency_results"]["cross_contamination_detected"] is False
    assert log_data["verification_taxonomy"]["offline_audits"] == "offline/DEV (TESTED_MOCK)"
    assert log_data["verification_taxonomy"]["live_gui_gate"] == "VERIFIED_LIVE"


@pytest.mark.asyncio
async def test_full_step182_pipeline_execution():
    """Verify full Step 182 async simulation and stdio concurrency pipeline."""
    res = await run_step182_mcp_valve_actuator()
    assert res["status"] == "success"
    assert "data" in res
    assert "invariant_G_multi_client_stdio_concurrency" in res["data"]
    assert res["data"]["invariant_G_multi_client_stdio_concurrency"]["cross_contamination_detected"] is False
