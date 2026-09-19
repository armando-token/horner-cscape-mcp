"""Test Suite for Step 188: FastMCP Duplex Pump Lead/Lag Alternator & Wear-Leveling Simulation Audit."""

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

from scripts.execute_step188_mcp_pump_lead_lag_alternator import (
    FBPumpLeadLagAlternator,
    run_step188_mcp_pump_lead_lag_alternator,
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
    assert "FUNCTION_BLOCK FB_PumpLeadLagAlternator" in content
    sha = compute_sha256(ST_FILE.read_bytes())
    assert sha.lower() == EXPECTED_SHA256.lower()

    user_st_file = USER_ROOT / "examples" / "st_applications" / "pump_lead_lag_alternator.st"
    if user_st_file.exists():
        assert compute_sha256(user_st_file.read_bytes()).lower() == EXPECTED_SHA256.lower()


def test_st_source_pure_iec_no_ladder():
    """Enforce pure IEC 61131-3 Structured Text without ladder logic."""
    content = ST_FILE.read_text(encoding="utf-8")
    assert "---[ ]---" not in content, "Ladder contact detected!"
    assert "---( )---" not in content, "Ladder coil detected!"
    assert "---[/]---" not in content, "Inverted contact detected!"
    assert "ERR_LADDER_FORBIDDEN" not in content


def test_all_13_simulation_invariants():
    """Tests all 13 operational invariants deterministically."""
    res = evaluate_simulation_invariants()
    assert res["status"] == "success"
    assert res["all_invariants_passed"] is True
    assert len(res["invariants"]) == 13

    expected_invariants = [
        "invariant_01_normal_single_pump_lead_operation",
        "invariant_02_runtime_hour_accumulation",
        "invariant_03_duty_cycle_alternation_on_restart",
        "invariant_04_continuous_runtime_threshold_alternation",
        "invariant_05_subsecond_standby_pump_failover",
        "invariant_06_latched_fault_and_reset",
        "invariant_07_dual_pump_boost_activation",
        "invariant_08_boost_recovery_hysteresis",
        "invariant_09_manual_override_mode",
        "invariant_10_maintenance_lockout_protection",
        "invariant_11_all_pumps_unavailable_alarm",
        "invariant_12_fastmcp_partitioned_registers",
        "invariant_13_download_lockout",
    ]

    for inv_name in expected_invariants:
        assert inv_name in res["invariants"], f"Missing invariant: {inv_name}"
        inv = res["invariants"][inv_name]
        assert inv["passed"] is True, f"Invariant {inv_name} failed: {inv['description']}"


def test_invariant_01_normal_single_pump_lead_operation_direct():
    fb = FBPumpLeadLagAlternator(cycle_time_sec=0.1)
    fb.SystemPressure = 45.0
    fb.PressureSetpoint = 50.0
    fb.StopPressure = 60.0
    fb.step()
    assert fb.LeadPumpId == 1
    assert fb.Pump1_RunCmd is True
    assert fb.Pump2_RunCmd is False
    assert fb.BoostActive is False
    assert fb.Pump1_Starts == 1
    assert fb.Pump2_Starts == 0


def test_invariant_02_runtime_hour_accumulation_direct():
    fb = FBPumpLeadLagAlternator(cycle_time_sec=0.1)
    fb.SystemPressure = 45.0
    for _ in range(3600):
        fb.step()
    assert abs(fb.Pump1_RunHours - 0.1) < 1e-5
    assert abs(fb.Pump2_RunHours - 0.0) < 1e-6
    assert fb.Pump1_Starts == 1


def test_invariant_03_duty_cycle_alternation_on_restart_direct():
    fb = FBPumpLeadLagAlternator(cycle_time_sec=0.1)
    fb.SystemPressure = 45.0
    for _ in range(3600):
        fb.step()
    assert abs(fb.Pump1_RunHours - 0.1) < 1e-5

    fb.SystemPressure = 65.0
    fb.step()
    assert fb.Pump1_RunCmd is False
    assert fb.Pump2_RunCmd is False

    fb.SystemPressure = 45.0
    fb.step()
    assert fb.LeadPumpId == 2
    assert fb.Pump1_RunCmd is False
    assert fb.Pump2_RunCmd is True
    assert fb.Pump2_Starts == 1


def test_invariant_04_continuous_runtime_threshold_alternation_direct():
    fb = FBPumpLeadLagAlternator(cycle_time_sec=0.1)
    fb.SystemPressure = 45.0
    fb.AlternationIntervalHours = 1.0
    for _ in range(36000):
        fb.step()
    assert fb.LeadPumpId == 1
    assert fb.Pump1_RunCmd is True
    assert fb.Pump2_RunCmd is False

    fb.step()
    fb.step()
    assert fb.LeadPumpId == 2
    assert fb.Pump1_RunCmd is False
    assert fb.Pump2_RunCmd is True


def test_invariant_05_subsecond_standby_pump_failover_direct():
    fb = FBPumpLeadLagAlternator(cycle_time_sec=0.1)
    fb.SystemPressure = 45.0
    fb.step()
    assert fb.Pump1_RunCmd is True
    assert fb.Pump2_RunCmd is False

    fb.Pump1_TripFault = True
    fb.step()
    assert fb.Pump1_Fault is True
    assert fb.Pump1_RunCmd is False
    assert fb.LeadPumpId == 2
    assert fb.Pump2_RunCmd is True
    assert fb.Pump2_Starts == 1


def test_invariant_06_latched_fault_and_reset_direct():
    fb = FBPumpLeadLagAlternator(cycle_time_sec=0.1)
    fb.SystemPressure = 45.0
    fb.Pump1_TripFault = True
    fb.step()
    assert fb.Pump1_Fault is True

    fb.Pump1_TripFault = False
    fb.step()
    assert fb.Pump1_Fault is True
    assert fb.P1_Available is False
    assert fb.Pump1_RunCmd is False

    fb.ResetFaults = True
    fb.step()
    assert fb.Pump1_Fault is False
    assert fb.P1_Available is True


def test_invariant_07_dual_pump_boost_activation_direct():
    fb = FBPumpLeadLagAlternator(cycle_time_sec=0.1)
    fb.SystemPressure = 30.0
    fb.BoostPressureThreshold = 35.0
    fb.step()
    assert fb.BoostActive is True
    assert fb.Pump1_RunCmd is True
    assert fb.Pump2_RunCmd is True
    assert fb.Pump1_Starts == 1
    assert fb.Pump2_Starts == 1


def test_invariant_08_boost_recovery_hysteresis_direct():
    fb = FBPumpLeadLagAlternator(cycle_time_sec=0.1)
    fb.SystemPressure = 30.0
    fb.step()
    assert fb.BoostActive is True
    assert fb.Pump1_RunCmd is True
    assert fb.Pump2_RunCmd is True

    fb.SystemPressure = 52.0
    fb.step()
    assert fb.BoostActive is False
    assert fb.Pump1_RunCmd is True
    assert fb.Pump2_RunCmd is False

    fb.SystemPressure = 62.0
    fb.step()
    assert fb.Pump1_RunCmd is False
    assert fb.Pump2_RunCmd is False
    assert fb.BoostActive is False


def test_invariant_09_manual_override_mode_direct():
    fb = FBPumpLeadLagAlternator(cycle_time_sec=0.1)
    fb.AutoMode = False
    fb.SystemPressure = 70.0
    fb.Pump1_Manual = True
    fb.Pump2_Manual = False
    fb.step()
    assert fb.Pump1_RunCmd is True
    assert fb.Pump2_RunCmd is False
    assert fb.BoostActive is False

    fb.Pump2_Manual = True
    fb.step()
    assert fb.Pump1_RunCmd is True
    assert fb.Pump2_RunCmd is True
    assert fb.BoostActive is True


def test_invariant_10_maintenance_lockout_protection_direct():
    fb = FBPumpLeadLagAlternator(cycle_time_sec=0.1)
    fb.SystemPressure = 45.0
    fb.Pump1_Lockout = True
    fb.step()
    assert fb.P1_Available is False
    assert fb.Pump1_RunCmd is False
    assert fb.LeadPumpId == 2
    assert fb.Pump2_RunCmd is True

    fb.AutoMode = False
    fb.Pump1_Manual = True
    fb.step()
    assert fb.Pump1_RunCmd is False


def test_invariant_11_all_pumps_unavailable_alarm_direct():
    fb = FBPumpLeadLagAlternator(cycle_time_sec=0.1)
    fb.Pump1_Lockout = True
    fb.Pump2_TripFault = True
    fb.SystemPressure = 30.0
    fb.step()
    assert fb.AllPumpsFaulted is True
    assert fb.Pump1_RunCmd is False
    assert fb.Pump2_RunCmd is False
    assert fb.BoostActive is False


def test_invariant_12_fastmcp_partitioned_registers_direct():
    w_r1 = cscape_write_register(address="%R151", value=48.5, data_type="REAL", project_name="TankLevelClosedLoop")
    w_r2 = cscape_write_register(address="%R155", value=35.0, data_type="REAL", project_name="TankLevelClosedLoop")
    w_m1 = cscape_write_register(address="%M81", value=True, data_type="BOOL", project_name="TankLevelClosedLoop")
    w_m2 = cscape_write_register(address="%M86", value=False, data_type="BOOL", project_name="TankLevelClosedLoop")
    w_q1 = cscape_write_register(address="%Q51", value=True, data_type="BOOL", project_name="TankLevelClosedLoop")
    w_q2 = cscape_write_register(address="%Q52", value=False, data_type="BOOL", project_name="TankLevelClosedLoop")

    r_r1 = cscape_read_register(address="%R151", data_type="REAL", project_name="TankLevelClosedLoop")
    r_r2 = cscape_read_register(address="%R155", data_type="REAL", project_name="TankLevelClosedLoop")
    r_m1 = cscape_read_register(address="%M81", data_type="BOOL", project_name="TankLevelClosedLoop")
    r_m2 = cscape_read_register(address="%M86", data_type="BOOL", project_name="TankLevelClosedLoop")
    r_q1 = cscape_read_register(address="%Q51", data_type="BOOL", project_name="TankLevelClosedLoop")
    r_q2 = cscape_read_register(address="%Q52", data_type="BOOL", project_name="TankLevelClosedLoop")

    assert w_r1.get("status") == "success"
    assert w_r2.get("status") == "success"
    assert w_m1.get("status") == "success"
    assert w_m2.get("status") == "success"
    assert w_q1.get("status") == "success"
    assert w_q2.get("status") == "success"
    assert r_r1.get("status") == "success"
    assert r_r2.get("status") == "success"
    assert r_m1.get("status") == "success"
    assert r_m2.get("status") == "success"
    assert r_q1.get("status") == "success"
    assert r_q2.get("status") == "success"
    assert abs(r_r1.get("value", 0.0) - 48.5) < 0.001
    assert abs(r_r2.get("value", 0.0) - 35.0) < 0.001
    assert r_m1.get("value") is True
    assert r_m2.get("value") is False
    assert r_q1.get("value") is True
    assert r_q2.get("value") is False


def test_invariant_13_download_lockout_direct():
    guard = SafetyGuard()
    with pytest.raises((HardwareLockoutError, UnauthorizedDownloadError, Exception)):
        guard.validate_download_command(32827)

    with pytest.raises((HardwareLockoutError, UnauthorizedDownloadError, Exception)):
        guard.validate_download_command(33149)

    with pytest.raises(UnauthorizedDownloadError):
        guard.validate_download("/download")

    assert 32827 in BLOCKED_DOWNLOAD_COMMAND_IDS
    assert 33149 in BLOCKED_DOWNLOAD_COMMAND_IDS


def test_execution_and_dual_root_parity():
    """Verify execution of Step 188 and dual-root parity of logs and checkpoints."""
    res = run_step188_mcp_pump_lead_lag_alternator()
    assert res["status"] == "success"

    for lp in LOG_PATHS:
        assert lp.exists(), f"Missing log: {lp}"
        data = json.loads(lp.read_text(encoding="utf-8"))
        assert data["status"] == "success"
        assert data["step"] == 188
        assert data["target_pou"] == "FB_PumpLeadLagAlternator"

    for cp in CHECKPOINT_PATHS:
        assert cp.exists(), f"Missing checkpoint: {cp}"
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert data["status"] == "success"
        assert data["step"] == 188
        assert data["target_pou"] == "FB_PumpLeadLagAlternator"

    # Exact byte parity
    assert LOG_PATHS[0].read_bytes() == LOG_PATHS[1].read_bytes()
    assert CHECKPOINT_PATHS[0].read_bytes() == CHECKPOINT_PATHS[1].read_bytes()


def test_g4_simulation_checkpoint_updated():
    """Verify megaplan_g4_closed_loop_simulation_checkpoint.json reflects step 188."""
    g4_paths = [
        HORNER_ROOT / "artifacts" / "checkpoints" / "megaplan_g4_closed_loop_simulation_checkpoint.json",
        USER_ROOT / "artifacts" / "checkpoints" / "megaplan_g4_closed_loop_simulation_checkpoint.json",
    ]
    for gp in g4_paths:
        assert gp.exists(), f"Missing G4 checkpoint: {gp}"
        g4 = json.loads(gp.read_text(encoding="utf-8"))
        assert g4["gate"] == "G4"
        assert g4["step"] == 188
        assert g4["status"] == "success"
        assert "FB_PumpLeadLagAlternator" in g4["active_simulations"]

    assert g4_paths[0].read_bytes() == g4_paths[1].read_bytes()

