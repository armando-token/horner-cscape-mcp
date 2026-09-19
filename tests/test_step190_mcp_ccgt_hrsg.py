"""Test Suite for Step 190: FastMCP CCGT HRSG Drum Level & Duct Burner Control Discrete Simulation Audit."""

from __future__ import annotations

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

from scripts.execute_step190_mcp_ccgt_hrsg import (
    CCGTHRSGDrumLevelDuctBurnerControl,
    run_step190_mcp_ccgt_hrsg,
    evaluate_simulation_invariants,
    ST_FILE,
    EXPECTED_SHA256,
    LOG_PATHS,
    CHECKPOINT_PATHS,
    compute_sha256,
)
from src.cscape.safety import BLOCKED_DOWNLOAD_COMMAND_IDS
from src.security.guard import SafetyGuard
from src.security.exceptions import HardwareLockoutError, UnauthorizedDownloadError
from src.mcp.tools import cscape_write_register, cscape_read_register


def test_st_source_file_exists():
    """Verify ST source file exists in both roots and matches SHA256."""
    assert ST_FILE.exists(), f"ST file missing: {ST_FILE}"
    content = ST_FILE.read_text(encoding="utf-8")
    assert "PROGRAM CCGTHRSGDrumLevelDuctBurnerControl" in content
    sha = compute_sha256(ST_FILE.read_bytes())
    assert sha.lower() == EXPECTED_SHA256.lower()

    user_st_file = USER_ROOT / "examples" / "st_applications" / "ccgt_hrsg_drum_level_duct_burner_control.st"
    if user_st_file.exists():
        assert compute_sha256(user_st_file.read_bytes()).lower() == EXPECTED_SHA256.lower()


def test_st_source_pure_iec_no_ladder():
    """Enforce pure IEC 61131-3 Structured Text without ladder logic."""
    content = ST_FILE.read_text(encoding="utf-8")
    assert "---[ ]---" not in content, "Ladder contact detected!"
    assert "---( )---" not in content, "Ladder coil detected!"
    assert "---[/]---" not in content, "Inverted contact detected!"
    assert "ERR_LADDER_FORBIDDEN" not in content


def test_all_12_simulation_invariants():
    """Tests all 12 operational invariants deterministically."""
    res = evaluate_simulation_invariants()
    assert res["status"] == "success"
    assert res["all_invariants_passed"] is True
    assert len(res["invariants"]) == 12

    expected_invariants = [
        "invariant_01_steady_state_normal_control",
        "invariant_02_incipient_low_drum_level_warning",
        "invariant_03_incipient_high_drum_level_warning",
        "invariant_04_critical_low_low_boil_dry_trip",
        "invariant_05_critical_high_high_carryover_trip",
        "invariant_06_dynamic_swell_shrink_compensation",
        "invariant_07_duct_burner_permissive_satisfied",
        "invariant_08_duct_burner_trip_flame_loss_temp_drop",
        "invariant_09_operator_emergency_trip_reset_interlock",
        "invariant_10_single_element_fallback",
        "invariant_11_fastmcp_register_partitioning",
        "invariant_12_download_lockout",
    ]

    for inv_name in expected_invariants:
        assert inv_name in res["invariants"], f"Missing invariant: {inv_name}"
        inv = res["invariants"][inv_name]
        assert inv["passed"] is True, f"Invariant {inv_name} failed: {inv['description']}"


def test_invariant_01_steady_state_normal_control_direct():
    sim = CCGTHRSGDrumLevelDuctBurnerControl(cycle_time_sec=0.1)
    sim.DrumLevel_PV_mm = 0.0
    sim.SteamFlow_Rate_kgs = 85.0
    sim.FeedwaterFlow_Rate_kgs = 85.0
    sim.BoilerFeedPumpARunningAux = True
    sim.FlowTransmittersHealthy = True
    sim.step()
    expected_valve_pos = (85.0 / 120.0) * 85.0
    assert sim.FeedwaterControlAutoOnline is True
    assert sim.ThreeElementModeActive is True
    assert abs(sim.LevelError_mm) < 0.001
    assert abs(sim.FlowMismatch_kgs) < 0.001
    assert abs(sim.TargetValvePos_pct - expected_valve_pos) < 0.01
    assert abs(sim.FeedwaterValveOutput_pct - expected_valve_pos) < 0.01
    assert sim.BoilerMasterTripActive is False
    assert sim.DrumProtectionCommonAlarm is False


def test_invariant_02_incipient_low_drum_level_warning_direct():
    sim = CCGTHRSGDrumLevelDuctBurnerControl(cycle_time_sec=0.1)
    sim.DrumLevel_PV_mm = -180.0
    sim.step()
    assert sim.LowDrumLevelWarning is True
    assert sim.HighDrumLevelWarning is False
    assert sim.LowLowDrumLevelTripLatched is False
    assert sim.BoilerMasterTripActive is False
    assert sim.DrumProtectionCommonAlarm is False


def test_invariant_03_incipient_high_drum_level_warning_direct():
    sim = CCGTHRSGDrumLevelDuctBurnerControl(cycle_time_sec=0.1)
    sim.DrumLevel_PV_mm = 180.0
    sim.step()
    assert sim.HighDrumLevelWarning is True
    assert sim.LowDrumLevelWarning is False
    assert sim.HighHighDrumCarryoverTrip is False
    assert sim.EmergencyBlowdownValveOpen is False
    assert sim.BoilerMasterTripActive is False


def test_invariant_04_critical_low_low_boil_dry_trip_direct():
    sim = CCGTHRSGDrumLevelDuctBurnerControl(cycle_time_sec=0.1)
    sim.DrumLevel_PV_mm = -325.0
    sim.DuctBurnerFiringDemand_pct = 50.0
    sim.DuctBurnerFlameDetected = True
    sim.step()
    assert sim.LowLowDrumLevelTripLatched is True
    assert sim.BoilerMasterTripActive is True
    assert sim.DrumProtectionCommonAlarm is True
    assert sim.DuctBurnerFuelGasBlockOpen is False
    assert sim.FeedwaterControlAutoOnline is False


def test_invariant_05_critical_high_high_carryover_trip_direct():
    sim = CCGTHRSGDrumLevelDuctBurnerControl(cycle_time_sec=0.1)
    sim.DrumLevel_PV_mm = 375.0
    sim.DuctBurnerFiringDemand_pct = 50.0
    sim.DuctBurnerFlameDetected = True
    sim.step()
    assert sim.HighHighDrumCarryoverTrip is True
    assert sim.BoilerMasterTripActive is True
    assert sim.DrumProtectionCommonAlarm is True
    assert sim.EmergencyBlowdownValveOpen is True
    assert sim.DuctBurnerFuelGasBlockOpen is False


def test_invariant_06_dynamic_swell_shrink_compensation_direct():
    sim = CCGTHRSGDrumLevelDuctBurnerControl(cycle_time_sec=0.1)
    sim.DrumLevel_PV_mm = 0.0
    sim.DuctBurnerFiringDemand_pct = 75.0
    sim.SteamFlow_Rate_kgs = 85.0
    sim.BoilerFeedPumpARunningAux = True
    sim.step()
    assert sim.DrumSwellShrinkActive is True

    sim.DuctBurnerFiringDemand_pct = 40.0
    sim.step()
    assert sim.DrumSwellShrinkActive is False


def test_invariant_07_duct_burner_permissive_satisfied_direct():
    sim = CCGTHRSGDrumLevelDuctBurnerControl(cycle_time_sec=0.1)
    sim.GTRunPermissiveAux = True
    sim.GT_ExhaustTemp_degC = 540.0
    sim.BoilerFeedPumpARunningAux = True
    sim.DrumLevel_PV_mm = 0.0
    sim.DuctBurnerFiringDemand_pct = 45.0
    sim.DuctBurnerFlameDetected = True
    sim.step()
    assert sim.DuctBurnerPermissiveOK is True
    assert sim.DuctBurnerFuelGasBlockOpen is True
    assert sim.BoilerMasterTripActive is False


def test_invariant_08_duct_burner_trip_flame_loss_temp_drop_direct():
    sim = CCGTHRSGDrumLevelDuctBurnerControl(cycle_time_sec=0.1)
    sim.GTRunPermissiveAux = True
    sim.GT_ExhaustTemp_degC = 540.0
    sim.BoilerFeedPumpARunningAux = True
    sim.DrumLevel_PV_mm = 0.0
    sim.DuctBurnerFiringDemand_pct = 45.0
    sim.DuctBurnerFlameDetected = True
    sim.step()
    assert sim.DuctBurnerFuelGasBlockOpen is True

    # Flame loss
    sim.DuctBurnerFlameDetected = False
    sim.step()
    assert sim.DuctBurnerFuelGasBlockOpen is False

    # Restore flame, reduce exhaust temp
    sim.DuctBurnerFlameDetected = True
    sim.GT_ExhaustTemp_degC = 420.0
    sim.step()
    assert sim.DuctBurnerPermissiveOK is False
    assert sim.DuctBurnerFuelGasBlockOpen is False


def test_invariant_09_operator_emergency_trip_reset_interlock_direct():
    sim = CCGTHRSGDrumLevelDuctBurnerControl(cycle_time_sec=0.1)
    # Trip condition
    sim.DrumLevel_PV_mm = -350.0
    sim.step()
    assert sim.LowLowDrumLevelTripLatched is True

    # Normalize PV
    sim.DrumLevel_PV_mm = 0.0

    # Reset attempt WITHOUT feed pump running -> reset blocked
    sim.BoilerFeedPumpARunningAux = False
    sim.BoilerFeedPumpBRunningAux = False
    sim.EmergencyTripResetPB = True
    sim.step()
    assert sim.LowLowDrumLevelTripLatched is True
    assert sim.BoilerMasterTripActive is True

    # Reset with feed pump running -> successfully cleared
    sim.BoilerFeedPumpARunningAux = True
    sim.EmergencyTripResetPB = True
    sim.step()
    assert sim.LowLowDrumLevelTripLatched is False
    assert sim.HighHighDrumCarryoverTrip is False
    assert sim.BoilerMasterTripActive is False
    assert sim.DrumProtectionCommonAlarm is False
    assert sim.EmergencyBlowdownValveOpen is False


def test_invariant_10_single_element_fallback_direct():
    sim = CCGTHRSGDrumLevelDuctBurnerControl(cycle_time_sec=0.1)
    sim.DrumLevel_PV_mm = -20.0
    sim.SteamFlow_Rate_kgs = 85.0
    sim.FeedwaterFlow_Rate_kgs = 85.0
    sim.BoilerFeedPumpARunningAux = True
    sim.FlowTransmittersHealthy = False
    sim.step()

    expected_val = 50.0 + (20.0 * 0.1)
    assert sim.ThreeElementModeActive is False
    assert sim.DrumSwellShrinkActive is False
    assert sim.FeedwaterControlAutoOnline is True
    assert abs(sim.LevelError_mm - 20.0) < 0.01
    assert abs(sim.TargetValvePos_pct - expected_val) < 0.01
    assert abs(sim.FeedwaterValveOutput_pct - expected_val) < 0.01


def test_invariant_11_fastmcp_register_partitioning_direct():
    r_regs = [
        ("%R190", 15.5, "REAL"),
        ("%R191", 85.0, "REAL"),
        ("%R192", 84.5, "REAL"),
        ("%R193", 540.0, "REAL"),
        ("%R194", 55.0, "REAL"),
        ("%R195", 62.5, "REAL"),
        ("%R196", 65.0, "REAL"),
        ("%R197", 1.2, "REAL"),
    ]
    for addr, val, dt in r_regs:
        w = cscape_write_register(address=addr, value=val, data_type=dt, project_name="TankLevelClosedLoop")
        r = cscape_read_register(address=addr, data_type=dt, project_name="TankLevelClosedLoop")
        assert w.get("status") == "success"
        assert r.get("status") == "success"
        assert abs(r.get("value", 0.0) - val) < 0.01

    bit_regs = [
        ("%I36", True), ("%I37", True), ("%I38", False), ("%I39", True), ("%I40", False),
        ("%Q68", True), ("%Q69", True), ("%Q70", False), ("%Q71", False),
        ("%M90", True), ("%M91", False), ("%M92", False), ("%M93", False),
        ("%M94", False), ("%M95", False), ("%M96", True), ("%M97", False),
    ]
    for addr, val in bit_regs:
        w = cscape_write_register(address=addr, value=val, data_type="BOOL", project_name="TankLevelClosedLoop")
        r = cscape_read_register(address=addr, data_type="BOOL", project_name="TankLevelClosedLoop")
        assert w.get("status") == "success"
        assert r.get("status") == "success"
        assert r.get("value") is val

    import concurrent.futures

    def client_worker(address: str, val: float):
        w = cscape_write_register(address=address, value=val, data_type="REAL", project_name="TankLevelClosedLoop")
        r = cscape_read_register(address=address, data_type="REAL", project_name="TankLevelClosedLoop")
        return (w.get("status") == "success" and r.get("status") == "success", r.get("value", 0.0))

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        f1 = executor.submit(client_worker, "%R190", 25.0)
        f2 = executor.submit(client_worker, "%R290", 125.0)
        f3 = executor.submit(client_worker, "%R390", 225.0)
        res1, val1 = f1.result()
        res2, val2 = f2.result()
        res3, val3 = f3.result()

    assert res1 and res2 and res3
    check_r190 = cscape_read_register(address="%R190", data_type="REAL", project_name="TankLevelClosedLoop")
    check_r290 = cscape_read_register(address="%R290", data_type="REAL", project_name="TankLevelClosedLoop")
    check_r390 = cscape_read_register(address="%R390", data_type="REAL", project_name="TankLevelClosedLoop")

    assert abs(check_r190.get("value", 0.0) - 25.0) < 0.001
    assert abs(check_r290.get("value", 0.0) - 125.0) < 0.001
    assert abs(check_r390.get("value", 0.0) - 225.0) < 0.001


def test_invariant_12_download_lockout_direct():
    guard = SafetyGuard()
    with pytest.raises((HardwareLockoutError, UnauthorizedDownloadError, Exception)):
        guard.validate_download_command(32827)

    with pytest.raises((HardwareLockoutError, UnauthorizedDownloadError, Exception)):
        guard.validate_download_command(33149)

    with pytest.raises(UnauthorizedDownloadError):
        guard.validate_download("/download")

    with pytest.raises(UnauthorizedDownloadError):
        guard.validate_download("/flash")

    assert 32827 in BLOCKED_DOWNLOAD_COMMAND_IDS
    assert 33149 in BLOCKED_DOWNLOAD_COMMAND_IDS


def test_execution_and_dual_root_parity():
    """Verify execution of Step 190 and dual-root parity of logs and checkpoints."""
    res = run_step190_mcp_ccgt_hrsg()
    assert res["status"] == "success"

    for lp in LOG_PATHS:
        assert lp.exists(), f"Missing log: {lp}"
        data = json.loads(lp.read_text(encoding="utf-8"))
        assert data["status"] == "success"
        assert data["step"] == 190
        assert data["target_pou"] == "CCGTHRSGDrumLevelDuctBurnerControl"

    for cp in CHECKPOINT_PATHS:
        assert cp.exists(), f"Missing checkpoint: {cp}"
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert data["status"] == "success"
        assert data["step"] == 190
        assert data["target_pou"] == "CCGTHRSGDrumLevelDuctBurnerControl"

    # Exact byte parity
    assert LOG_PATHS[0].read_bytes() == LOG_PATHS[1].read_bytes()
    assert CHECKPOINT_PATHS[0].read_bytes() == CHECKPOINT_PATHS[1].read_bytes()


def test_g4_simulation_checkpoint_updated():
    """Verify megaplan_g4_closed_loop_simulation_checkpoint.json reflects step 190."""
    g4_paths = [
        HORNER_ROOT / "artifacts" / "checkpoints" / "megaplan_g4_closed_loop_simulation_checkpoint.json",
        USER_ROOT / "artifacts" / "checkpoints" / "megaplan_g4_closed_loop_simulation_checkpoint.json",
    ]
    for gp in g4_paths:
        assert gp.exists(), f"Missing G4 checkpoint: {gp}"
        g4 = json.loads(gp.read_text(encoding="utf-8"))
        assert g4["gate"] == "G4"
        assert g4["step"] == 190
        assert g4["status"] == "success"
        assert "CCGTHRSGDrumLevelDuctBurnerControl" in g4["active_simulations"]

    assert g4_paths[0].read_bytes() == g4_paths[1].read_bytes()
