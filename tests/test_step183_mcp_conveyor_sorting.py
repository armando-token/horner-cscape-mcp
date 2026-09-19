"""Test Suite for Step 183: FastMCP Conveyor Sortation State Machine Simulation Audit."""

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
from scripts.execute_step183_mcp_conveyor_sorting import (
    FBConveyorSortingStateMachine,
    run_step183_mcp_conveyor_sorting,
    ST_FILE,
    LOG_PATHS,
    CHECKPOINT_PATHS,
    compute_sha256,
)


def test_st_source_file_exists():
    """Verify ST source file exists in both roots and matches SHA256."""
    assert ST_FILE.exists(), f"ST file missing: {ST_FILE}"
    content = ST_FILE.read_text(encoding="utf-8")
    assert "FUNCTION_BLOCK FB_ConveyorSortingStateMachine" in content
    assert "Material Handling Conveyor Sortation" in content
    sha = compute_sha256(ST_FILE.read_bytes())
    assert sha.lower() == "8a4891bbc3b409feb2b85b71ed196c588b5ed47c5b074e43e2cc4fc6fe8b439b"


def test_st_source_pure_iec_no_ladder():
    """Enforce pure IEC 61131-3 Structured Text without ladder logic."""
    content = ST_FILE.read_text(encoding="utf-8")
    assert "---[ ]---" not in content, "Ladder contact detected!"
    assert "---( )---" not in content, "Ladder coil detected!"
    assert "---[/]---" not in content, "Inverted contact detected!"
    assert "ERR_LADDER_FORBIDDEN" not in content


def test_invariant_a_normal_parcel_feed_and_divert_lane1():
    """Invariant A: Normal parcel feed, debounce (PackageDetectPE), barcode scan, and divert to Lane 1."""
    fb = FBConveyorSortingStateMachine(cycle_time_sec=0.1)
    fb.StartPB = True
    fb.step()
    fb.StartPB = False
    fb.step()
    assert fb.CurrentState == 10
    assert fb.ConveyorRun is True
    assert fb.CountTotal == 0
    assert fb.CountLane1 == 0

    # Package arrives at infeed: debounce filter test
    fb.PackageDetectPE = True
    fb.step()  # InfeedDebounce = 0.1s >= 0.05s
    assert fb.InfeedConfirmed is True
    assert fb.CurrentState == 20  # INSPECT

    # Barcode decode ready: Lane 1
    fb.BarcodeScanValid = True
    fb.BarcodeDestLane = 1
    fb.step()
    fb.BarcodeScanValid = False
    assert fb.CurrentState == 30  # DIVERT_LANE1
    fb.step()
    assert fb.Diverter1_Extend is True

    # Cylinder extends within stroke timeout
    fb.Diverter1_Extended = True
    fb.DivertersRetracted = False
    fb.step()

    # Package crosses Lane 1 exit sensor
    fb.ExitPE_Lane1 = True
    fb.step()
    fb.ExitPE_Lane1 = False
    assert fb.CurrentState == 60  # PACKAGE_CLEARED
    assert fb.CountLane1 == 1
    assert fb.CountTotal == 1
    assert fb.Diverter1_Extend is False

    # Cylinder retracts home and parcel clears PE
    fb.Diverter1_Extended = False
    fb.DivertersRetracted = True
    fb.PackageDetectPE = False
    fb.step()
    assert fb.InfeedConfirmed is False
    assert fb.CurrentState == 10  # Back to FEED
    fb.step()
    assert fb.ConveyorRun is True


def test_invariant_b_divert_lane2():
    """Invariant B: Divert to Lane 2 on barcode destination 2 (BarcodeDestLane=2)."""
    fb = FBConveyorSortingStateMachine(cycle_time_sec=0.1)
    fb.StartPB = True
    fb.step()
    fb.StartPB = False
    fb.step()
    assert fb.CurrentState == 10

    # Feed parcel
    fb.PackageDetectPE = True
    fb.step()
    assert fb.CurrentState == 20

    # Barcode destination 2
    fb.BarcodeScanValid = True
    fb.BarcodeDestLane = 2
    fb.step()
    fb.BarcodeScanValid = False
    assert fb.CurrentState == 40  # DIVERT_LANE2
    fb.step()
    assert fb.Diverter2_Extend is True

    # Cylinder 2 extends
    fb.Diverter2_Extended = True
    fb.DivertersRetracted = False
    fb.step()

    # Lane 2 discharge sensor
    fb.ExitPE_Lane2 = True
    fb.step()
    fb.ExitPE_Lane2 = False
    assert fb.CurrentState == 60
    assert fb.CountLane2 == 1
    assert fb.CountTotal == 1
    assert fb.Diverter2_Extend is False

    # Retract diverter and clear
    fb.Diverter2_Extended = False
    fb.DivertersRetracted = True
    fb.PackageDetectPE = False
    fb.step()
    assert fb.CurrentState == 10


def test_invariant_c_scanner_timeout_and_unrecognized_reject():
    """Invariant C: Default divert to Reject on scanner timeout (>1.5s) or unrecognized destination."""
    # 1. Scanner timeout test
    fb1 = FBConveyorSortingStateMachine(cycle_time_sec=0.1)
    fb1.StartPB = True
    fb1.step()
    fb1.StartPB = False
    fb1.step()
    fb1.PackageDetectPE = True
    fb1.step()
    assert fb1.CurrentState == 20

    # Wait 1.5 seconds (15 cycles of 0.1s)
    for _ in range(15):
        fb1.step()
    assert fb1.CurrentState == 50  # STATE_REJECT
    assert fb1.LatchedLane == 3
    fb1.step()
    assert fb1.RejectGate_Extend is True

    # Complete reject discharge
    fb1.ExitPE_Reject = True
    fb1.step()
    fb1.ExitPE_Reject = False
    assert fb1.CurrentState == 60
    assert fb1.CountReject == 1
    assert fb1.CountTotal == 1

    # 2. Unrecognized barcode destination test (e.g. lane 5)
    fb2 = FBConveyorSortingStateMachine(cycle_time_sec=0.1)
    fb2.StartPB = True
    fb2.step()
    fb2.StartPB = False
    fb2.step()
    fb2.PackageDetectPE = True
    fb2.step()
    assert fb2.CurrentState == 20

    fb2.BarcodeScanValid = True
    fb2.BarcodeDestLane = 5  # Invalid/unrecognized lane
    fb2.step()
    fb2.BarcodeScanValid = False
    assert fb2.CurrentState == 50  # Routed to REJECT
    fb2.step()
    assert fb2.RejectGate_Extend is True

    fb2.ExitPE_Reject = True
    fb2.step()
    fb2.ExitPE_Reject = False
    assert fb2.CurrentState == 60
    assert fb2.CountReject == 1
    assert fb2.CountTotal == 1


def test_invariant_d_jam_detection_watchdog():
    """Invariant D: Jam detection watchdog: parcel transit exceeding JamTimeoutSec triggers JamAlarm = TRUE, halts line (CurrentState = 90)."""
    fb = FBConveyorSortingStateMachine(cycle_time_sec=0.1)
    fb.StartPB = True
    fb.step()
    fb.StartPB = False
    fb.step()
    fb.PackageDetectPE = True
    fb.step()
    assert fb.CurrentState == 20

    fb.BarcodeScanValid = True
    fb.BarcodeDestLane = 1
    fb.step()
    fb.BarcodeScanValid = False
    assert fb.CurrentState == 30
    fb.step()

    fb.Diverter1_Extended = True
    fb.DivertersRetracted = False
    fb.JamTimeoutSec = 2.0  # Jam timeout set to 2.0s
    fb.ExitPE_Lane1 = False

    # Simulate jam: 2.0s elapse with no exit sensor trigger
    for _ in range(20):
        fb.step()

    assert fb.JamAlarm is True
    assert fb.CurrentState == 90  # STATE_JAM_FAULT

    # Next scan confirms all motion commands halted
    fb.step()
    assert fb.ConveyorRun is False
    assert fb.Diverter1_Extend is False
    assert fb.RunPermissive is False


def test_invariant_e_cylinder_actuator_failure():
    """Invariant E: Cylinder actuator failure: diverter failing to extend within DivertStrokeSec triggers DiverterFault = TRUE (CurrentState = 90)."""
    fb = FBConveyorSortingStateMachine(cycle_time_sec=0.1)
    fb.StartPB = True
    fb.step()
    fb.StartPB = False
    fb.step()
    fb.PackageDetectPE = True
    fb.step()
    assert fb.CurrentState == 20

    fb.BarcodeScanValid = True
    fb.BarcodeDestLane = 1
    fb.step()
    fb.BarcodeScanValid = False
    assert fb.CurrentState == 30
    fb.step()
    assert fb.Diverter1_Extend is True

    # Actuator failure: cylinder fails to extend within DivertStrokeSec
    fb.DivertStrokeSec = 1.2
    for _ in range(12):  # 1.2 seconds of stroke time
        fb.step()

    assert fb.DiverterFault is True
    assert fb.CurrentState == 90
    fb.step()
    assert fb.ConveyorRun is False
    assert fb.Diverter1_Extend is False
    assert fb.RunPermissive is False


def test_invariant_f_fault_reset_and_resume():
    """Invariant F: Fault reset and resume: ResetFault = TRUE clears alarms and restores idle state once diverters retracted."""
    fb = FBConveyorSortingStateMachine(cycle_time_sec=0.1)
    fb.CurrentState = 90
    fb.JamAlarm = True
    fb.DiverterFault = True
    fb.DivertersRetracted = True

    # Pulse ResetFault
    fb.ResetFault = True
    fb.step()
    assert fb.JamAlarm is False
    assert fb.DiverterFault is False
    assert fb.CurrentState == 0  # STATE_IDLE

    # Clear ResetPB and StartPB
    fb.ResetFault = False
    fb.step()
    assert fb.CurrentState == 0

    fb.StartPB = True
    fb.step()
    fb.StartPB = False
    fb.step()
    assert fb.CurrentState == 10  # Line running again
    assert fb.ConveyorRun is True


def test_invariant_g_estop_immediate_trip():
    """Invariant G: Emergency stop trip: EStop = FALSE trips system into CurrentState = 99 immediately, de-energizing all actuators."""
    fb = FBConveyorSortingStateMachine(cycle_time_sec=0.1)
    fb.StartPB = True
    fb.step()
    fb.StartPB = False
    fb.step()
    assert fb.CurrentState == 10
    assert fb.ConveyorRun is True

    # Trip E-Stop
    fb.EStop = False
    fb.step()
    assert fb.CurrentState == 99
    assert fb.RunPermissive is False
    assert fb.ConveyorRun is False
    assert fb.Diverter1_Extend is False
    assert fb.Diverter2_Extend is False
    assert fb.RejectGate_Extend is False

    # Start button cannot restart system while EStop active
    fb.StartPB = True
    fb.step()
    assert fb.CurrentState == 99
    assert fb.RunPermissive is False
    assert fb.ConveyorRun is False
    fb.StartPB = False

    # Restore EStop
    fb.EStop = True
    fb.step()
    assert fb.CurrentState == 0  # Restores to IDLE


def test_invariant_i_fail_closed_hardware_lockout():
    """Invariant I: Fail-closed download lockout enforcement for commands 32827 and 33149."""
    assert 32827 in BLOCKED_DOWNLOAD_COMMAND_IDS
    assert 33149 in BLOCKED_DOWNLOAD_COMMAND_IDS

    guard = SafetyGuard()
    with pytest.raises(UnauthorizedDownloadError):
        guard.validate_download("/download")


def test_step183_checkpoints_and_logs_parity():
    """Verify dual root parity of Step 183 checkpoint and log files."""
    for cp_path in CHECKPOINT_PATHS:
        assert cp_path.exists(), f"Missing checkpoint: {cp_path}"
    assert CHECKPOINT_PATHS[0].read_bytes() == CHECKPOINT_PATHS[1].read_bytes()

    for log_path in LOG_PATHS:
        assert log_path.exists(), f"Missing log: {log_path}"
    assert LOG_PATHS[0].read_bytes() == LOG_PATHS[1].read_bytes()

    cp_data = json.loads(CHECKPOINT_PATHS[0].read_text(encoding="utf-8"))
    assert cp_data["step"] == 183
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
    assert log_data["simulation_results"]["conveyor_sorting_verified"] is True
    assert log_data["concurrency_results"]["straton_tools_count"] == 0
    assert log_data["concurrency_results"]["cross_contamination_detected"] is False
    assert log_data["verification_taxonomy"]["offline_audits"] == "offline/DEV (TESTED_MOCK)"
    assert log_data["verification_taxonomy"]["live_gui_gate"] == "VERIFIED_LIVE"


@pytest.mark.asyncio
async def test_full_step183_pipeline_execution():
    """Verify full Step 183 async simulation and stdio concurrency pipeline."""
    res = await run_step183_mcp_conveyor_sorting()
    assert res["status"] == "success"
    assert "data" in res
    assert "invariant_H_multi_client_stdio_concurrency" in res["data"]
    assert res["data"]["invariant_H_multi_client_stdio_concurrency"]["cross_contamination_detected"] is False
