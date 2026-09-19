"""Test Suite for Step 185: FastMCP PID Temperature Controller Simulation Audit."""

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

from scripts.execute_step185_mcp_pid_temperature_controller import (
    FBPIDTemperatureControl,
    run_step185_mcp_pid_temperature_controller,
    evaluate_simulation_invariants,
    ST_FILE,
    EXPECTED_SHA256,
    LOG_PATHS,
    CHECKPOINT_PATHS,
    compute_sha256,
)


def test_st_source_file_exists():
    """Verify ST source file exists in both roots and matches SHA256."""
    assert ST_FILE.exists(), f"ST file missing: {ST_FILE}"
    content = ST_FILE.read_text(encoding="utf-8")
    assert "FUNCTION_BLOCK FB_PIDTemperatureControl" in content
    sha = compute_sha256(ST_FILE.read_bytes())
    assert sha.lower() == EXPECTED_SHA256.lower()


def test_st_source_pure_iec_no_ladder():
    """Enforce pure IEC 61131-3 Structured Text without ladder logic."""
    content = ST_FILE.read_text(encoding="utf-8")
    assert "---[ ]---" not in content, "Ladder contact detected!"
    assert "---( )---" not in content, "Ladder coil detected!"
    assert "---[/]---" not in content, "Inverted contact detected!"
    assert "ERR_LADDER_FORBIDDEN" not in content


def test_all_14_simulation_invariants():
    """Tests all 14 operational invariants deterministically."""
    res = evaluate_simulation_invariants()
    assert res["status"] == "success"
    assert res["all_invariants_passed"] is True
    assert len(res["invariants"]) == 14

    expected_invariants = [
        "invariant_01_normal_equilibrium",
        "invariant_02_positive_error_heat_demand",
        "invariant_03_negative_error_cool_demand",
        "invariant_04_deadband_filtering",
        "invariant_05_alpha_low_pass_filtering",
        "invariant_06_bumpless_transfer",
        "invariant_07_pwm_ssr_pulse",
        "invariant_08_alarm_hh",
        "invariant_09_alarm_ll",
        "invariant_10_alarm_hl",
        "invariant_11_sensor_fault",
        "invariant_12_reset_alarm",
        "invariant_13_fastmcp_partitioned_registers",
        "invariant_14_download_lockout",
    ]

    for inv_name in expected_invariants:
        assert inv_name in res["invariants"], f"Missing invariant: {inv_name}"
        inv = res["invariants"][inv_name]
        assert inv["passed"] is True, f"Invariant {inv_name} failed: {inv['description']}"


def test_invariant_01_normal_equilibrium_direct():
    fb = FBPIDTemperatureControl()
    fb.Setpoint = 150.0
    fb.RawPV = 150.0
    fb.FilteredPV = 150.0
    fb.LastPV = 150.0
    fb.IntegralSum = 50.0
    fb.step()
    assert fb.EffectiveError == 0.0
    assert fb.Error == 0.0
    assert abs(fb.TotalEffort - 50.0) < 1e-4
    assert fb.HeatOutput == 0.0
    assert fb.CoolOutput == 0.0
    assert fb.PWM_Heater is False
    assert fb.LoopHealthy is True


def test_invariant_02_positive_error_heat_demand_direct():
    fb = FBPIDTemperatureControl()
    fb.Setpoint = 150.0
    fb.RawPV = 130.0
    fb.FilteredPV = 130.0
    fb.LastPV = 130.0
    fb.IntegralSum = 50.0
    fb.step()
    assert fb.Error == 20.0
    assert fb.EffectiveError == 20.0
    assert fb.TotalEffort == 100.0
    assert fb.HeatOutput == 100.0
    assert fb.CoolOutput == 0.0


def test_invariant_03_negative_error_cool_demand_direct():
    fb = FBPIDTemperatureControl()
    fb.Setpoint = 150.0
    fb.RawPV = 170.0
    fb.FilteredPV = 170.0
    fb.LastPV = 170.0
    fb.IntegralSum = 50.0
    fb.step()
    assert fb.Error == -20.0
    assert fb.EffectiveError == -20.0
    assert fb.TotalEffort == 0.0
    assert fb.CoolOutput == 100.0
    assert fb.HeatOutput == 0.0


def test_invariant_04_deadband_filtering_direct():
    fb = FBPIDTemperatureControl()
    fb.Setpoint = 150.0
    fb.RawPV = 150.3
    fb.FilteredPV = 150.3
    fb.LastPV = 150.3
    fb.IntegralSum = 50.0
    fb.step()
    assert abs(fb.Error - (-0.3)) < 1e-4
    assert fb.EffectiveError == 0.0
    assert fb.PropTerm == 0.0
    assert abs(fb.IntegralSum - 50.0) < 1e-4
    assert fb.HeatOutput == 0.0 and fb.CoolOutput == 0.0


def test_invariant_05_alpha_low_pass_filtering_direct():
    fb = FBPIDTemperatureControl()
    fb.FilteredPV = 25.0
    fb.FilterAlpha = 0.25
    fb.RawPV = 125.0
    fb.step()
    assert abs(fb.FilteredPV - 50.0) < 1e-4
    fb.step()
    assert abs(fb.FilteredPV - 68.75) < 1e-4


def test_invariant_06_bumpless_transfer_direct():
    fb = FBPIDTemperatureControl()
    fb.ManualMode = True
    fb.ManualOutput = 75.0
    fb.step()
    assert abs(fb.TotalEffort - 75.0) < 1e-4
    assert abs(fb.IntegralSum - 75.0) < 1e-4
    fb.ManualMode = False
    fb.RawPV = fb.FilteredPV
    fb.Setpoint = fb.FilteredPV
    fb.step()
    assert abs(fb.TotalEffort - 75.0) < 1e-4
    assert fb.PropTerm == 0.0
    assert fb.EffectiveError == 0.0


def test_invariant_07_pwm_ssr_pulse_direct():
    fb = FBPIDTemperatureControl()
    fb.ManualMode = True
    fb.ManualOutput = 70.0
    fb.step()
    assert abs(fb.HeatOutput - 40.0) < 1e-4
    pulses = [fb.step() or fb.PWM_Heater for _ in range(50)]
    assert sum(1 for p in pulses if p) == 20


def test_invariant_08_alarm_hh_direct():
    fb = FBPIDTemperatureControl()
    fb.RawPV = 225.0
    fb.FilteredPV = 225.0
    fb.step()
    assert fb.AlarmHH is True
    assert fb.LoopHealthy is False
    assert fb.HeatOutput == 0.0 and fb.PWM_Heater is False
    fb.RawPV = 150.0
    fb.FilteredPV = 150.0
    fb.step()
    assert fb.AlarmHH is True


def test_invariant_09_alarm_ll_direct():
    fb = FBPIDTemperatureControl()
    fb.RawPV = 45.0
    fb.FilteredPV = 45.0
    fb.step()
    assert fb.AlarmLL is True
    fb.RawPV = 100.0
    fb.FilteredPV = 100.0
    fb.step()
    assert fb.AlarmLL is True


def test_invariant_10_alarm_hl_direct():
    fb = FBPIDTemperatureControl()
    fb.RawPV = 190.0
    fb.FilteredPV = 190.0
    fb.step()
    assert fb.AlarmH is True and fb.AlarmL is False
    fb.RawPV = 150.0
    fb.FilteredPV = 150.0
    fb.step()
    assert fb.AlarmH is False and fb.AlarmL is False
    fb.RawPV = 70.0
    fb.FilteredPV = 70.0
    fb.step()
    assert fb.AlarmL is True and fb.AlarmH is False
    fb.RawPV = 100.0
    fb.FilteredPV = 100.0
    fb.step()
    assert fb.AlarmL is False and fb.AlarmH is False


def test_invariant_11_sensor_fault_direct():
    fb = FBPIDTemperatureControl()
    fb.SensorFault = True
    fb.step()
    assert fb.LoopHealthy is False
    assert fb.HeatOutput == 0.0 and fb.CoolOutput == 0.0 and fb.PWM_Heater is False


def test_invariant_12_reset_alarm_direct():
    fb = FBPIDTemperatureControl()
    fb.RawPV = 230.0
    fb.FilteredPV = 230.0
    fb.step()
    assert fb.AlarmHH is True
    fb.RawPV = 150.0
    fb.FilteredPV = 150.0
    fb.ResetAlarm = True
    fb.step()
    assert fb.AlarmHH is False
    assert fb.AlarmLL is False
    assert fb.LoopHealthy is True


def test_execution_and_dual_root_parity():
    """Verify execution of Step 185 and dual-root parity of logs and checkpoints."""
    res = run_step185_mcp_pid_temperature_controller()
    assert res["status"] == "success"

    for lp in LOG_PATHS:
        assert lp.exists(), f"Missing log: {lp}"
        data = json.loads(lp.read_text(encoding="utf-8"))
        assert data["status"] == "success"
        assert data["step"] == 185
        assert data["target_pou"] == "FB_PIDTemperatureControl"

    for cp in CHECKPOINT_PATHS:
        assert cp.exists(), f"Missing checkpoint: {cp}"
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert data["status"] == "success"
        assert data["step"] == 185
        assert data["target_pou"] == "FB_PIDTemperatureControl"

    # Exact byte parity
    assert LOG_PATHS[0].read_bytes() == LOG_PATHS[1].read_bytes()
    assert CHECKPOINT_PATHS[0].read_bytes() == CHECKPOINT_PATHS[1].read_bytes()


def test_g4_simulation_checkpoint_updated():
    """Verify megaplan_g4_closed_loop_simulation_checkpoint.json reflects step 185."""
    g4_paths = [
        HORNER_ROOT / "artifacts" / "checkpoints" / "megaplan_g4_closed_loop_simulation_checkpoint.json",
        USER_ROOT / "artifacts" / "checkpoints" / "megaplan_g4_closed_loop_simulation_checkpoint.json",
    ]
    for gp in g4_paths:
        assert gp.exists(), f"Missing G4 checkpoint: {gp}"
        g4 = json.loads(gp.read_text(encoding="utf-8"))
        assert g4["gate"] == "G4"
        assert g4["step"] == 185
        assert g4["status"] == "success"
        assert "FB_PIDTemperatureControl" in g4["active_simulations"]

    assert g4_paths[0].read_bytes() == g4_paths[1].read_bytes()
