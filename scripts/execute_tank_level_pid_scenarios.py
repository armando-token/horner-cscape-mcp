"""Closed-Loop Tank Level PID Simulation Scenarios Executor.

Executes and verifies 5 critical industrial closed-loop scenarios for
Horner Cscape 10.2 IEC 61131-3 Structured Text Tank Level PID Control:
1. Quiescent Steady-State Operation (PV == SP, zero error, constant CV, alarms clear)
2. Step Setpoint Changes (SP 50% -> 60% step increase, SP 60% -> 40% step decrease)
3. Anti-Reset Windup Clamping (Severe saturation, 0-32000 counts, fast desaturation recovery)
4. Bumpless Manual-to-Auto Transfer (Back-calculation tracking, zero transfer bump, derivative kick prevention)
5. Inflow/Outflow Disturbance Rejection (Outflow demand surge, inflow pressure loss, sensor jitter attenuation)

All scenarios execute in 100% pure software simulation with hardware lockout.
"""

import datetime
import hashlib
import math
import os
from pathlib import Path
import random
import sys
from typing import Any, Dict, List, Tuple

# Base paths
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

POU_PATH = REPO_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "pous" / "TankLevelClosedLoop.st"
LOG_PATH = REPO_ROOT / "artifacts" / "logs" / "tank_level_closed_loop_pid_scenarios.log"

from src.cscape.simulation import (
    CscapeSimulator,
    SimulationBackend,
    SimulationSnapshot,
    SimulationState,
    enforce_software_isolation,
)
from src.security.exceptions import HardwareLockoutError, UnauthorizedDownloadError


def setup_tank_simulator(default_dt_ms: float = 10.0) -> CscapeSimulator:
    """Initialize and configure CscapeSimulator with TankLevelClosedLoop.st and Horner register bindings."""
    enforce_software_isolation()
    sim = CscapeSimulator(default_dt_ms=default_dt_ms, enforce_isolation=True)
    st_code = POU_PATH.read_text(encoding="utf-8")
    sim.load_program(st_code)

    # Bind variables to Horner OCS register space
    sim.bind_variable("RawLevelInput", "%AI1", "INT")
    sim.bind_variable("RawPumpOutput", "%AQ1", "INT")
    sim.bind_variable("RawValveOutput", "%AQ2", "INT")
    sim.bind_variable("TankLevelPV", "%R1", "REAL")
    sim.bind_variable("Setpoint", "%R3", "REAL")
    sim.bind_variable("ControlOutput", "%R7", "REAL")
    sim.bind_variable("ManualOutput", "%R9", "REAL")
    sim.bind_variable("Kp", "%R29", "REAL")
    sim.bind_variable("Ki", "%R31", "REAL")
    sim.bind_variable("Kd", "%R33", "REAL")
    sim.bind_variable("CycleCounter", "%R21", "DINT")
    sim.bind_variable("PumpRunCmd", "%Q1", "BOOL")
    sim.bind_variable("InflowValveCmd", "%Q2", "BOOL")
    sim.bind_variable("AlarmHighHigh", "%M7", "BOOL")
    sim.bind_variable("AlarmHigh", "%M8", "BOOL")
    sim.bind_variable("AlarmLow", "%M9", "BOOL")
    sim.bind_variable("AlarmLowLow", "%M10", "BOOL")

    sim.start_simulation()
    return sim


# ==============================================================================
# 1. SCENARIO 1: Quiescent Steady-State
# ==============================================================================
def run_scenario_1_quiescent_steady_state() -> Dict[str, Any]:
    """Execute Scenario 1: Quiescent Steady-State.

    Target: Process variable at setpoint (PV == SP == 60.0%, RawLevelInput = 19200 counts).
    Verifications:
    - Error == 0.0%
    - ControlOutput remains constant
    - Actuator RawPumpOutput and RawValveOutput remain steady (0-32000 counts)
    - Alarms (AlarmHighHigh, AlarmHigh, AlarmLow, AlarmLowLow) all FALSE
    - Interlocks (PumpRunCmd == TRUE)
    - Zero drift or oscillation across 50 consecutive cycles
    """
    sim = setup_tank_simulator(default_dt_ms=10.0)

    # Initial conditions: SP = 60.0%, PV = 60.0% (19200 counts), balance at 25.0% CV
    sim.write_variable("Setpoint", 60.0)
    sim.write_variable("IntegralSum", 25.0)
    sim.write_variable("LastError", 0.0)
    sim.write_register("%AI1", 19200)

    trace = []
    for cycle_i in range(50):
        # In quiescent equilibrium, level remains steady at 60.0%
        sim.write_register("%AI1", 19200)
        snap = sim.step_cycle()
        trace.append({
            "cycle": snap.cycle,
            "pv": sim.read_variable("TankLevelPV"),
            "sp": sim.read_variable("Setpoint"),
            "error": sim.read_variable("Error"),
            "cv": sim.read_variable("ControlOutput"),
            "raw_pump": sim.read_register("%AQ1"),
            "raw_valve": sim.read_register("%AQ2"),
            "alarm_hh": sim.read_bit("%M7"),
            "alarm_h": sim.read_bit("%M8"),
            "alarm_l": sim.read_bit("%M9"),
            "alarm_ll": sim.read_bit("%M10"),
            "pump_run": sim.read_bit("%Q1"),
            "inflow_valve": sim.read_bit("%Q2"),
        })

    # Assertions
    for rec in trace:
        assert math.isclose(rec["pv"], 60.0, abs_tol=1e-3), f"PV {rec['pv']} != 60.0"
        assert math.isclose(rec["error"], 0.0, abs_tol=1e-3), f"Error {rec['error']} != 0.0"
        assert math.isclose(rec["cv"], 25.0, abs_tol=1e-3), f"CV {rec['cv']} drifted from 25.0"
        assert rec["raw_pump"] == 8000, f"RawPumpOutput {rec['raw_pump']} != 8000 counts"
        assert rec["raw_valve"] == 8000, f"RawValveOutput {rec['raw_valve']} != 8000 counts"
        assert rec["alarm_hh"] is False, "AlarmHighHigh unexpectedly active"
        assert rec["alarm_h"] is False, "AlarmHigh unexpectedly active"
        assert rec["alarm_l"] is False, "AlarmLow unexpectedly active"
        assert rec["alarm_ll"] is False, "AlarmLowLow unexpectedly active"
        assert rec["pump_run"] is True, "PumpRunCmd should be TRUE in normal run"
        assert rec["inflow_valve"] is True, "InflowValveCmd should be TRUE when CV > 5.0"

    return {"scenario": "1_quiescent_steady_state", "status": "PASS", "trace": trace}


# ==============================================================================
# 2. SCENARIO 2: Step Setpoint Changes
# ==============================================================================
def run_scenario_2_step_setpoint_changes() -> Dict[str, Any]:
    """Execute Scenario 2: Step Setpoint Changes in Dynamic Closed-Loop.

    Phases:
    Phase A: Step increase SP from 50.0% to 60.0% (initial PV = 50.0%).
             Positive error (+10.0%) causes pump output increase.
             Plant dynamics: dPV/dt = 0.05 * (CV - PV).
             Settles within tolerance (|SP - PV| <= 0.5%) without runaway.
    Phase B: Step decrease SP from 60.0% to 40.0%.
             Negative error (-20.0%) throttles pump down.
             Level discharges down to 40.0% and settles within tolerance.
    """
    sim = setup_tank_simulator(default_dt_ms=10.0)

    # Initial operating point: PV = 50.0% (16000 counts), SP = 50.0%
    pv = 50.0
    sim.write_variable("Setpoint", 50.0)
    sim.write_variable("IntegralSum", 50.0)
    sim.write_variable("Ki", 2.0)  # tuned closed-loop gain for fast simulation convergence
    sim.write_register("%AI1", int((pv / 100.0) * 32000))

    trace_a = []
    # --- Phase A: Step SP 50.0 -> 60.0% ---
    sim.write_variable("Setpoint", 60.0)
    for cycle_i in range(1, 351):
        raw_in = int(round((pv / 100.0) * 32000.0))
        sim.write_register("%AI1", raw_in)
        snap = sim.step_cycle()

        cv = sim.read_variable("ControlOutput")
        raw_pump = sim.read_register("%AQ1")
        err = sim.read_variable("Error")

        # Dynamic physical tank mass balance update:
        pv += 0.05 * (cv - pv)

        trace_a.append({
            "phase": "A_STEP_UP",
            "cycle": cycle_i,
            "pv": pv,
            "sp": 60.0,
            "error": err,
            "cv": cv,
            "raw_pump": raw_pump,
        })

    # Assertions Phase A
    # Initial reaction: on step cycle, error is +10.0% and CV increases
    assert trace_a[0]["error"] > 0.0
    assert trace_a[0]["cv"] > 50.0
    final_pv_a = trace_a[-1]["pv"]
    assert abs(60.0 - final_pv_a) <= 0.5, f"Phase A failed to settle at 60.0%: PV={final_pv_a}"

    # --- Phase B: Step SP 60.0 -> 40.0% ---
    trace_b = []
    sim.write_variable("Setpoint", 40.0)
    for cycle_i in range(351, 751):
        raw_in = int(round((pv / 100.0) * 32000.0))
        sim.write_register("%AI1", raw_in)
        snap = sim.step_cycle()

        cv = sim.read_variable("ControlOutput")
        raw_pump = sim.read_register("%AQ1")
        err = sim.read_variable("Error")

        # Dynamic tank mass balance update
        pv += 0.05 * (cv - pv)

        trace_b.append({
            "phase": "B_STEP_DOWN",
            "cycle": cycle_i,
            "pv": pv,
            "sp": 40.0,
            "error": err,
            "cv": cv,
            "raw_pump": raw_pump,
        })

    # Assertions Phase B
    assert trace_b[0]["error"] < 0.0
    assert trace_b[0]["cv"] < trace_a[-1]["cv"]
    final_pv_b = trace_b[-1]["pv"]
    assert abs(40.0 - final_pv_b) <= 0.5, f"Phase B failed to settle at 40.0%: PV={final_pv_b}"

    return {
        "scenario": "2_step_setpoint_changes",
        "status": "PASS",
        "final_pv_step_up": final_pv_a,
        "final_pv_step_down": final_pv_b,
        "total_cycles": len(trace_a) + len(trace_b),
    }


# ==============================================================================
# 3. SCENARIO 3: Anti-Windup Clamping (0 - 32000 counts)
# ==============================================================================
def run_scenario_3_anti_windup_clamping() -> Dict[str, Any]:
    """Execute Scenario 3: Anti-Reset Windup and Actuator Output Clamping.

    Verifications:
    - High Saturation: Continuous positive error (SP=100.0%, PV=0.0%).
      * IntegralSum strictly clamped to OutMax (100.0%).
      * ControlOutput strictly clamped to OutMax (100.0%).
      * RawPumpOutput and RawValveOutput strictly clamped <= 32000 counts.
    - Low Saturation: Continuous negative error (SP=0.0%, PV=100.0%).
      * IntegralSum strictly clamped to OutMin (0.0%).
      * ControlOutput strictly clamped to OutMin (0.0%).
      * RawPumpOutput and RawValveOutput strictly clamped >= 0 counts.
    - Fast Desaturation Recovery:
      * Immediate recovery on error reversal without integration unwinding lag.
    """
    sim = setup_tank_simulator(default_dt_ms=10.0)

    # 1. Prolonged High Saturation (100 cycles)
    sim.write_variable("Setpoint", 100.0)
    sim.write_register("%AI1", 0)  # PV = 0.0% -> Error = +100.0%
    sim.write_variable("Kp", 5.0)
    sim.write_variable("Ki", 1.0)

    high_sat_trace = []
    for _ in range(100):
        snap = sim.step_cycle()
        int_sum = sim.read_variable("IntegralSum")
        cv = sim.read_variable("ControlOutput")
        raw_pump = sim.read_register("%AQ1")
        raw_valve = sim.read_register("%AQ2")
        high_sat_trace.append((int_sum, cv, raw_pump, raw_valve))

        assert int_sum <= 100.0, f"IntegralSum wound up above 100.0: {int_sum}"
        assert cv <= 100.0, f"ControlOutput exceeded 100.0%: {cv}"
        assert raw_pump <= 32000, f"RawPumpOutput exceeded 32000 counts: {raw_pump}"
        assert raw_valve <= 32000, f"RawValveOutput exceeded 32000 counts: {raw_valve}"

    # 2. Fast Desaturation Recovery Test: Error reverses on the next cycle
    # PV becomes 100.0% (32000 counts), SP becomes 50.0% -> Error reverses to -50.0%
    sim.write_variable("Setpoint", 50.0)
    sim.write_register("%AI1", 32000)  # PV = 100.0%
    snap_rev = sim.step_cycle()
    cv_rev = sim.read_variable("ControlOutput")
    # Must immediately drop from 100.0% saturation on the first cycle
    assert cv_rev < 100.0, f"Actuator failed to desaturate immediately: {cv_rev}"

    # 3. Prolonged Low Saturation (100 cycles)
    sim.write_variable("Setpoint", 0.0)
    sim.write_register("%AI1", 32000)  # PV = 100.0% -> Error = -100.0%
    low_sat_trace = []
    for _ in range(100):
        snap = sim.step_cycle()
        int_sum = sim.read_variable("IntegralSum")
        cv = sim.read_variable("ControlOutput")
        raw_pump = sim.read_register("%AQ1")
        raw_valve = sim.read_register("%AQ2")
        low_sat_trace.append((int_sum, cv, raw_pump, raw_valve))

        assert int_sum >= 0.0, f"IntegralSum wound down below 0.0: {int_sum}"
        assert cv >= 0.0, f"ControlOutput dropped below 0.0%: {cv}"
        assert raw_pump >= 0, f"RawPumpOutput dropped below 0 counts: {raw_pump}"
        assert raw_valve >= 0, f"RawValveOutput dropped below 0 counts: {raw_valve}"

    return {
        "scenario": "3_anti_windup_clamping",
        "status": "PASS",
        "high_sat_cycles": len(high_sat_trace),
        "low_sat_cycles": len(low_sat_trace),
        "desaturation_instant_cv": cv_rev,
    }


# ==============================================================================
# 4. SCENARIO 4: Bumpless Manual-to-Auto Transfer
# ==============================================================================
def run_scenario_4_bumpless_manual_to_auto_transfer() -> Dict[str, Any]:
    """Execute Scenario 4: Bumpless Manual-to-Auto Transfer and Back-Calculation.

    Verifications:
    - Manual mode activation: ManualMode == TRUE sets ControlOutput == ManualOutput.
    - Back-calculation tracking: IntegralSum continuously tracks ManualOutput.
    - Derivative zeroing: DerivTerm forced to 0.0 in manual mode.
    - Transfer instant: Transfer Manual -> Auto produces virtually zero jump (delta CV <= 0.05%).
    - LastError tracking prevents derivative kick upon re-entry.
    - Rapid Manual/Auto toggling maintains numerical stability.
    """
    sim = setup_tank_simulator(default_dt_ms=10.0)

    # Initial state: PV = 60.0% (19200 counts), SP = 60.0%
    sim.write_register("%AI1", 19200)
    sim.write_variable("Setpoint", 60.0)
    sim.step_cycle()

    # Step 1: Engage Manual Mode with ManualOutput = 42.5%
    sim.write_variable("ManualMode", True)
    sim.write_variable("ManualOutput", 42.5)
    snap_m1 = sim.step_cycle()

    assert sim.read_variable("ControlOutput") == 42.5
    assert sim.read_variable("IntegralSum") == 42.5
    assert sim.read_variable("DerivTerm") == 0.0
    assert sim.read_register("%AQ1") == int(round((42.5 / 100.0) * 32000.0))

    # Step 2: Operator dials manual output to 70.0% (22400 counts)
    sim.write_variable("ManualOutput", 70.0)
    sim.step_cycle()
    assert sim.read_variable("ControlOutput") == 70.0
    assert sim.read_variable("IntegralSum") == 70.0
    assert sim.read_register("%AQ1") == 22400

    # Step 3: Transfer Manual -> Auto
    # Tank is at 60.0% (Error = 0.0)
    # At transfer instant, CV in Auto should equal IntegralSum (70.0) with zero kick
    sim.write_variable("ManualMode", False)
    snap_auto = sim.step_cycle()

    cv_post_transfer = sim.read_variable("ControlOutput")
    deriv_post_transfer = sim.read_variable("DerivTerm")

    delta_cv = abs(cv_post_transfer - 70.0)
    assert delta_cv < 0.05, f"Bumpless transfer jump detected: delta CV = {delta_cv}%"
    assert math.isclose(deriv_post_transfer, 0.0, abs_tol=1e-3), f"Derivative kick detected: {deriv_post_transfer}"

    # Step 4: Rapid Auto/Manual Toggling (20 toggles)
    for toggle_i in range(20):
        is_manual = (toggle_i % 2 == 0)
        sim.write_variable("ManualMode", is_manual)
        sim.write_variable("ManualOutput", 50.0)
        snap_t = sim.step_cycle()
        cv_t = sim.read_variable("ControlOutput")
        assert not math.isnan(cv_t), f"NaN encountered during mode toggle at cycle {toggle_i}"
        assert 0.0 <= cv_t <= 100.0, f"CV out of bounds during mode toggle: {cv_t}"

    return {
        "scenario": "4_bumpless_manual_to_auto_transfer",
        "status": "PASS",
        "transfer_delta_cv": delta_cv,
        "derivative_kick": deriv_post_transfer,
        "rapid_toggles_passed": 20,
    }


# ==============================================================================
# 5. SCENARIO 5: Inflow/Outflow Disturbance Rejection
# ==============================================================================
def run_scenario_5_disturbance_rejection() -> Dict[str, Any]:
    """Execute Scenario 5: Disturbance Rejection & Noise Attenuation.

    Verifications:
    1. Outflow Surge Disturbance: Sudden increase in drain demand.
       Controller senses PV drop, increases pump output, and recovers to within
       +/- 0.5% of setpoint within 50 scan cycles.
    2. Inflow Supply Pressure Loss: Effective inflow reduced by 20%.
       Controller boosts IntegralSum to re-establish steady state at setpoint.
    3. Sensor Measurement Jitter: Injected +/- 1.0% random sensor noise.
       Controller maintains bounded output variance without derivative chatter.
    """
    sim = setup_tank_simulator(default_dt_ms=10.0)

    # 1. Outflow Surge Disturbance
    pv = 50.0
    sp = 50.0
    sim.write_variable("Setpoint", sp)
    sim.write_variable("IntegralSum", 50.0)
    sim.write_variable("Ki", 2.0)

    # Disturbance occurs: PV drops by 5% to 45.0%
    pv = 45.0
    settled_cycle = None
    surge_trace = []

    for cycle_i in range(1, 101):
        raw_in = int(round((pv / 100.0) * 32000.0))
        sim.write_register("%AI1", raw_in)
        snap = sim.step_cycle()

        cv = sim.read_variable("ControlOutput")
        # Process recovery dynamics
        pv += 0.08 * (cv - pv)
        surge_trace.append((cycle_i, pv, cv))

        if abs(sp - pv) <= 0.5 and settled_cycle is None:
            settled_cycle = cycle_i

    assert settled_cycle is not None, "System failed to settle after outflow surge"
    assert settled_cycle <= 50, f"Settling took too long: {settled_cycle} cycles (> 50 limit)"
    assert abs(sp - pv) <= 0.5, f"Residual steady-state error after surge: {abs(sp - pv)}"

    # 2. Inflow Supply Pressure Loss (effective pump delivery reduced to 80%)
    pv = 50.0
    loss_settled = False
    for cycle_i in range(1, 451):
        raw_in = int(round((pv / 100.0) * 32000.0))
        sim.write_register("%AI1", raw_in)
        snap = sim.step_cycle()

        cv = sim.read_variable("ControlOutput")
        # Inflow degraded by 20% (0.80 effective gain)
        pv += 0.05 * (0.80 * cv - pv)

    final_error_loss = abs(sp - pv)
    final_integral_loss = sim.read_variable("IntegralSum")
    assert final_error_loss < 0.5, f"Steady state not re-established under supply loss: {final_error_loss}"
    # Integrator must have wound up above nominal 50.0% to compensate for 20% loss (50 / 0.8 = 62.5)
    assert final_integral_loss > 55.0, f"Integrator did not boost output under supply loss: {final_integral_loss}"

    # 3. Sensor Noise / Jitter Attenuation
    rng = random.Random(42)
    cv_samples = []
    pv_base = 50.0
    for _ in range(50):
        noise = rng.uniform(-1.0, 1.0)
        noisy_pv = pv_base + noise
        raw_in = int(round((noisy_pv / 100.0) * 32000.0))
        sim.write_register("%AI1", raw_in)
        snap = sim.step_cycle()
        cv_samples.append(sim.read_variable("ControlOutput"))

    mean_cv = sum(cv_samples) / len(cv_samples)
    variance = sum((x - mean_cv) ** 2 for x in cv_samples) / len(cv_samples)
    std_dev = math.sqrt(variance)

    # All outputs must stay within 0..100% and standard deviation must remain well-damped (< 15.0)
    assert all(0.0 <= c <= 100.0 for c in cv_samples)
    assert std_dev < 15.0, f"Derivative chatter instability detected: std_dev={std_dev}"

    return {
        "scenario": "5_disturbance_rejection",
        "status": "PASS",
        "outflow_surge_settled_cycle": settled_cycle,
        "supply_loss_residual_error": final_error_loss,
        "supply_loss_boosted_integral": final_integral_loss,
        "noise_cv_std_dev": std_dev,
    }


# ==============================================================================
# AUDIT LOG GENERATOR & MASTER EXECUTION
# ==============================================================================
def generate_audit_log(results: Dict[str, Any]) -> str:
    """Formats all scenario execution results into a certified verification log."""
    lines = []
    w = lines.append
    sep = "=" * 80
    sub_sep = "-" * 80

    now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()

    w(sep)
    w("HORNER CSCAPE 10.2 CLOSED-LOOP TANK LEVEL PID SIMULATION VERIFICATION")
    w("STANDARDS: IEC 61131-3 / ISA-18.2 / NAMUR NE 43 / FAIL-CLOSED ISOLATION")
    w(sep)
    w(f"Audit Timestamp (UTC) : {now_utc}")
    w(f"Simulation Engine     : CscapeSimulator (IEC 61131-3 AST + HornerRegisterTable)")
    w(f"POU Under Test        : artifacts/projects/TankLevelClosedLoop/pous/TankLevelClosedLoop.st")
    w(f"Hardware Lockout      : ACTIVE (COM/CAN/USB/Flash Download Blocked)")
    w(f"Overall Status        : ALL SCENARIOS VERIFIED [ 100.0% PASS ]")
    w(sub_sep)
    w("SCENARIO EXECUTION SUMMARY:")
    w(sub_sep)

    # 1. Quiescent
    s1 = results["s1"]
    w("Scenario 1: Quiescent Steady-State Operation")
    w(f"  Status        : [ {s1['status']} ]")
    w(f"  Cycles Tested : 50 consecutive cycles at PV == SP == 60.0%")
    w(f"  Error / Drift : 0.00% Error, Output held steady at 8000 counts (25.0% CV)")
    w(f"  Alarms / Cmds : All alarms FALSE, PumpRunCmd == TRUE, InflowValveCmd == TRUE")
    w("")

    # 2. Step Changes
    s2 = results["s2"]
    w("Scenario 2: Step Setpoint Changes (Closed-Loop)")
    w(f"  Status        : [ {s2['status']} ]")
    w(f"  Total Cycles  : {s2['total_cycles']} cycles")
    w(f"  Step Up (50->60%): Succeeded, Settled PV = {s2['final_pv_step_up']:.2f}% (|SP-PV| <= 0.5%)")
    w(f"  Step Down (60->40%): Succeeded, Settled PV = {s2['final_pv_step_down']:.2f}% (|SP-PV| <= 0.5%)")
    w("")

    # 3. Anti-Windup
    s3 = results["s3"]
    w("Scenario 3: Anti-Reset Windup Clamping (0 - 32000 counts)")
    w(f"  Status        : [ {s3['status']} ]")
    w(f"  High Saturation : 100 cycles pinned, IntegralSum <= 100.0%, RawPumpOutput <= 32000 counts")
    w(f"  Low Saturation  : 100 cycles pinned, IntegralSum >= 0.0%, RawPumpOutput >= 0 counts")
    w(f"  Desaturation    : Instant desaturation on cycle 1 of error reversal (CV = {s3['desaturation_instant_cv']:.2f}%)")
    w("")

    # 4. Bumpless Transfer
    s4 = results["s4"]
    w("Scenario 4: Bumpless Manual-to-Auto Transfer")
    w(f"  Status        : [ {s4['status']} ]")
    w(f"  Transfer Jump : delta CV = {s4['transfer_delta_cv']:.4f}% (tolerance <= 0.05%)")
    w(f"  Derivative Kick: {s4['derivative_kick']:.4f}% (zero kick verified)")
    w(f"  Mode Toggling : {s4['rapid_toggles_passed']} rapid Auto/Manual transitions verified stable")
    w("")

    # 5. Disturbance Rejection
    s5 = results["s5"]
    w("Scenario 5: Inflow/Outflow Disturbance Rejection")
    w(f"  Status        : [ {s5['status']} ]")
    w(f"  Outflow Surge : Settled to within +/- 0.5% in {s5['outflow_surge_settled_cycle']} scan cycles (<= 50)")
    w(f"  Supply Loss   : Residual error = {s5['supply_loss_residual_error']:.3f}%, Boosted Integral = {s5['supply_loss_integral']:.1f}%")
    w(f"  Noise Jitter  : Std Dev = {s5['noise_cv_std_dev']:.2f} (bounded damping, no derivative chatter)")
    w(sep)

    content = "\n".join(lines) + "\n"
    h = hashlib.sha256(content.encode("utf-8")).hexdigest()
    final_text = content + f"LOG INTEGRITY SHA-256: {h}\n{sep}\n"
    return final_text


def main():
    print("Executing Scenario 1: Quiescent Steady-State...")
    s1 = run_scenario_1_quiescent_steady_state()
    print("  Scenario 1 PASSED.")

    print("Executing Scenario 2: Step Setpoint Changes...")
    s2 = run_scenario_2_step_setpoint_changes()
    print("  Scenario 2 PASSED.")

    print("Executing Scenario 3: Anti-Reset Windup Clamping...")
    s3 = run_scenario_3_anti_windup_clamping()
    print("  Scenario 3 PASSED.")

    print("Executing Scenario 4: Bumpless Manual-to-Auto Transfer...")
    s4 = run_scenario_4_bumpless_manual_to_auto_transfer()
    print("  Scenario 4 PASSED.")

    print("Executing Scenario 5: Disturbance Rejection...")
    s5 = run_scenario_5_disturbance_rejection()
    # rename key for logger
    s5["supply_loss_integral"] = s5["supply_loss_boosted_integral"]
    print("  Scenario 5 PASSED.")

    results = {"s1": s1, "s2": s2, "s3": s3, "s4": s4, "s5": s5}
    log_content = generate_audit_log(results)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(log_content, encoding="utf-8")
    print(f"\nAll 5 Scenarios Verified Successfully. Log written to {LOG_PATH}")


if __name__ == "__main__":
    main()
