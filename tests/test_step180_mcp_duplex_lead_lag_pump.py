"""Test Suite for Step 180: FastMCP Industrial Duplex Lead-Lag Alternating Pump Controller Audit."""

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
from scripts.execute_step180_mcp_duplex_lead_lag_pump import (
    FBLeadLagPumpControl,
    run_step180_mcp_duplex_lead_lag_pump,
    ST_FILE,
    LOG_PATHS,
    CHECKPOINT_PATHS,
    compute_sha256,
)


def test_st_source_file_exists():
    """Verify ST source file exists in both roots and matches SHA256."""
    assert ST_FILE.exists(), f"ST file missing: {ST_FILE}"
    content = ST_FILE.read_text(encoding="utf-8")
    assert "FUNCTION_BLOCK FB_LeadLagPumpControl" in content
    assert "Duty/standby wear-leveling" in content or "wear-leveling" in content
    sha = compute_sha256(ST_FILE.read_bytes())
    assert sha == "45c493c7d45e04cd83e8cb6f28efcf807f6358eb0c980068a36831656d097a0e"


def test_st_source_pure_iec_no_ladder():
    """Enforce pure IEC 61131-3 Structured Text without ladder logic."""
    content = ST_FILE.read_text(encoding="utf-8")
    assert "---[ ]---" not in content, "Ladder contact detected!"
    assert "---( )---" not in content, "Ladder coil detected!"
    assert "---[/]---" not in content, "Inverted contact detected!"
    assert "ERR_LADDER_FORBIDDEN" not in content


# ============================================================================
# Unit Tests for FBLeadLagPumpControl Invariant Verification Matrix
# ============================================================================

def test_wear_leveling_duty_standby_rotation():
    """Invariant 1: Wear-leveling duty/standby rotation based on accumulated run hours."""
    fb = FBLeadLagPumpControl(cycle_time_sec=0.1)

    # Initial state: 0 hours each -> Pump 1 is lead
    fb.DemandLevel = 65.0  # Above LeadStartSP (60.0%)
    fb.step()
    assert fb.LeadPumpId == 1
    assert fb.Pump1_RunCmd is True
    assert fb.Pump2_RunCmd is False

    # Simulate Pump 1 accumulating 2.5 hours
    fb.Pump1_Hours = 2.5
    fb.P1_RunTimer = 9000.0  # Well above MinRunTimeSec

    # Stop demand
    fb.DemandLevel = 15.0  # Below StopSP (20.0%)
    fb.step()
    assert fb.Pump1_RunCmd is False
    assert fb.Pump2_RunCmd is False

    # Wear-leveling alternation: next cycle assigns Pump 2 as Lead because Pump2_Hours (0.0) < Pump1_Hours (2.5)
    fb.step()
    assert fb.LeadPumpId == 2

    # Demand returns: Pump 2 must start as duty lead
    fb.DemandLevel = 70.0
    fb.step()
    assert fb.Pump2_RunCmd is True
    assert fb.Pump1_RunCmd is False

    # Simulate Pump 2 accumulating 5.0 hours (more than Pump 1's 2.5h)
    fb.Pump2_Hours = 5.0
    fb.P2_RunTimer = 18000.0
    fb.DemandLevel = 10.0
    fb.step()
    assert fb.Pump1_RunCmd is False and fb.Pump2_RunCmd is False

    # Both stopped: Pump1_Hours (2.5) < Pump2_Hours (5.0) -> Lead switches back to Pump 1
    fb.step()
    assert fb.LeadPumpId == 1


def test_lag_pump_staging_and_destaging():
    """Invariant 2: Automatic lag pump staging when process demand level exceeds LagStartSP (85.0%)."""
    fb = FBLeadLagPumpControl(cycle_time_sec=0.1)

    # Moderate demand: single pump only
    fb.DemandLevel = 75.0  # Between 60% and 85%
    fb.step()
    assert fb.Pump1_RunCmd is True
    assert fb.Pump2_RunCmd is False
    assert fb.LagActive is False

    # High demand surge: exceeds LagStartSP (85.0%)
    fb.DemandLevel = 88.0
    fb.step()
    assert fb.Pump1_RunCmd is True
    assert fb.Pump2_RunCmd is True, "Lag pump must stage in"
    assert fb.LagActive is True, "LagActive must be TRUE"

    # Let pumps satisfy minimum run time (15s = 150 cycles)
    fb.run_cycles(160)

    # Demand decreases below LeadStartSP (60.0%)
    fb.DemandLevel = 55.0
    fb.step()
    assert fb.Pump1_RunCmd is True, "Lead pump remains on until StopSP"
    assert fb.Pump2_RunCmd is False, "Lag pump must destage when demand drops below 60%"
    assert fb.LagActive is False


def test_auto_switchover_failover_trip():
    """Invariant 3A: Auto-switchover and failover on pump thermal overload trip."""
    fb = FBLeadLagPumpControl(cycle_time_sec=0.1)
    fb.DemandLevel = 75.0
    fb.step()
    assert fb.LeadPumpId == 1
    assert fb.Pump1_RunCmd is True

    # Inject Pump 1 thermal trip
    fb.Pump1_Tripped = True
    fb.step()
    assert fb.Pump1_Fault is True
    assert fb.Pump1_RunCmd is False
    assert fb.P1_Available is False
    assert fb.LeadPumpId == 2, "Lead assignment must immediately switch to Pump 2"
    assert fb.Pump2_RunCmd is True, "Standby Pump 2 must automatically start"

    # Reset fault
    fb.Pump1_Tripped = False
    fb.ResetFaults = True
    fb.step()
    assert fb.Pump1_Fault is False
    assert fb.P1_Available is True


def test_auto_switchover_failover_dry_run():
    """Invariant 3B: Auto-switchover and failover on low suction / dry run sensor."""
    fb = FBLeadLagPumpControl(cycle_time_sec=0.1)
    fb.DemandLevel = 75.0
    fb.step()

    # Inject dry-run fault on Pump 1
    fb.Pump1_DryRun = True
    fb.step()
    assert fb.Pump1_Fault is True
    assert fb.Pump1_RunCmd is False
    assert fb.LeadPumpId == 2
    assert fb.Pump2_RunCmd is True


def test_anti_short_cycling_min_rest_and_run():
    """Invariant 4: Anti-short-cycling enforcement (MinRunTimeSec=15s, MinRestTimeSec=20s)."""
    fb = FBLeadLagPumpControl(cycle_time_sec=0.1)
    fb.Pump2_Tripped = True  # Isolate single pump to test anti-short-cycling timers without wear-leveling interference
    fb.step()
    assert fb.LeadPumpId == 1

    # 1. Start Pump 1
    fb.DemandLevel = 70.0
    fb.step()
    assert fb.Pump1_RunCmd is True

    # After 5s (50 cycles), command stop below StopSP (10.0%)
    fb.run_cycles(49)
    assert fb.P1_RunTimer < 15.0
    fb.DemandLevel = 10.0
    fb.step()
    assert fb.Pump1_RunCmd is True, "Pump 1 must continue running to satisfy MinRunTimeSec (15s)"

    # Advance 90 cycles (total run timer = 5.0 + 0.1 + 9.0 = 14.1s < 15.0s)
    fb.run_cycles(90)
    assert fb.P1_RunTimer < 15.0
    assert fb.Pump1_RunCmd is True, "Pump 1 must continue running before 15s"

    # Advance past 15s (15 cycles = 1.5s -> total 15.6s)
    fb.run_cycles(15)
    assert fb.Pump1_RunCmd is False, "Pump 1 safely stops once 15s elapsed"

    # 2. Re-assert demand after only 5s rest (< 20s MinRestTimeSec)
    fb.run_cycles(50)
    assert fb.P1_RestTimer < 20.0
    fb.DemandLevel = 75.0
    fb.step()
    assert fb.Pump1_RunCmd is False, "Pump 1 must NOT restart until 20s rest has elapsed"

    # Demand returns low and wait out rest delay
    fb.DemandLevel = 10.0
    fb.run_cycles(160)
    assert fb.P1_RestTimer >= 20.0

    # Demand returns: pump restarts cleanly
    fb.DemandLevel = 75.0
    fb.step()
    assert fb.Pump1_RunCmd is True, "Pump 1 restarts cleanly after 20s rest delay"


def test_emergency_all_pumps_faulted():
    """Invariant 5: Emergency AllPumpsFaulted alarm assertion when both pumps fail."""
    fb = FBLeadLagPumpControl(cycle_time_sec=0.1)
    fb.DemandLevel = 90.0
    fb.step()

    # Both pumps trip
    fb.Pump1_Tripped = True
    fb.Pump2_Tripped = True
    fb.step()

    assert fb.Pump1_Fault is True and fb.Pump2_Fault is True
    assert fb.P1_Available is False and fb.P2_Available is False
    assert fb.AllPumpsFaulted is True, "AllPumpsFaulted alarm must assert"
    assert fb.Pump1_RunCmd is False and fb.Pump2_RunCmd is False
    assert fb.LagActive is False


def test_manual_mode_override():
    """Verify manual override functionality with safety permissive gating."""
    fb = FBLeadLagPumpControl(cycle_time_sec=0.1)
    fb.ManualMode = True
    fb.Pump1_Manual = True
    fb.step()
    assert fb.Pump1_RunCmd is True
    assert fb.Pump2_RunCmd is False
    assert fb.LagActive is False

    # Manual lag start
    fb.Pump2_Manual = True
    fb.step()
    assert fb.Pump1_RunCmd is True and fb.Pump2_RunCmd is True
    assert fb.LagActive is True

    # Manual mode respects fault lockout: if Pump 1 trips, manual command is blocked
    fb.Pump1_Tripped = True
    fb.step()
    assert fb.Pump1_RunCmd is False, "Faulted pump must not run even in Manual mode"
    assert fb.Pump2_RunCmd is True


def test_maintenance_hour_warnings():
    """Verify preventive maintenance hour warning thresholds."""
    fb = FBLeadLagPumpControl(cycle_time_sec=0.1)
    fb.MaxRuntimeHours = 5000.0

    fb.Pump1_Hours = 4999.0
    fb.Pump2_Hours = 5001.0
    fb.step()

    assert fb.ServiceReqPump1 is False
    assert fb.ServiceReqPump2 is True, "Pump 2 exceeded 5000 hours -> ServiceReqPump2 must be TRUE"


# ============================================================================
# Full FastMCP Stdio Simulation Pipeline Test
# ============================================================================

@pytest.mark.asyncio
async def test_step180_mcp_duplex_lead_lag_pump_pipeline():
    """End-to-end audit test running FastMCP stdio client simulation pipeline."""
    gate = get_gate_status()
    if not gate.get("ready_for_tests"):
        pytest.skip(f"Live Cscape gate not ready: status='{gate.get('status')}'")

    res = await run_step180_mcp_duplex_lead_lag_pump()

    assert res.get("status") == "success"
    assert res.get("step") == 180
    assert res.get("classification") == "offline/DEV (TESTED_MOCK)"
    assert res.get("live_hardware_execution") is False
    assert res.get("straton_runtime_execution") is False

    # Check all invariant scenarios passed
    invariants = res.get("invariants", {})
    assert len(invariants) >= 7
    assert invariants["invariant_A_wear_leveling_alternation"]["status"] == "success"
    assert invariants["invariant_B_lag_pump_staging"]["status"] == "success"
    assert invariants["invariant_C_auto_switchover_failover"]["status"] == "success"
    assert invariants["invariant_D_anti_short_cycling"]["status"] == "success"
    assert invariants["invariant_E_all_pumps_faulted"]["status"] == "success"
    assert invariants["mcp_duplex_pump_register_sync"]["status"] == "success"
    assert invariants["multi_client_stdio_concurrency"]["status"] == "success"
    assert invariants["hardware_download_lockout"]["status"] == "success"

    # Parity verification: check files exist on both roots
    for lp in LOG_PATHS:
        assert lp.exists(), f"Missing log file: {lp}"
        data = json.loads(lp.read_text(encoding="utf-8"))
        assert data["status"] == "success"
        assert data["step"] == 180

    for cp in CHECKPOINT_PATHS:
        assert cp.exists(), f"Missing checkpoint file: {cp}"
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert data["status"] == "success"
        assert data["step"] == 180
        assert data["gate"] == "G4"
        assert data["verification_classification"] == "offline/DEV (TESTED_MOCK)"
