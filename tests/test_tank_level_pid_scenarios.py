"""Unit Tests for Industrial Closed-Loop Buffer Tank Level PID Control Scenarios.

Scenarios tested:
1. Quiescent steady-state (PV == SP, zero error, stable output, alarms clear)
2. Step setpoint changes (SP increase and decrease in dynamic closed loop)
3. Anti-reset windup clamping (0-32000 counts, 0.0-100.0% limits, fast desaturation)
4. Bumpless manual-to-auto transfer (back-calculation tracking, zero kick, derivative protection)
5. Inflow/outflow disturbance rejection (outflow demand surge, supply pressure loss, noise damping)
"""

import math
from scripts.execute_tank_level_pid_scenarios import (
    run_scenario_1_quiescent_steady_state,
    run_scenario_2_step_setpoint_changes,
    run_scenario_3_anti_windup_clamping,
    run_scenario_4_bumpless_manual_to_auto_transfer,
    run_scenario_5_disturbance_rejection,
)


def test_scenario_1_quiescent_steady_state():
    """Verify quiescent steady state holds error at 0.0% and steady 8000 counts."""
    res = run_scenario_1_quiescent_steady_state()
    assert res["status"] == "PASS"
    assert len(res["trace"]) == 50


def test_scenario_2_step_setpoint_changes():
    """Verify closed-loop step setpoint tracking for both increase and decrease."""
    res = run_scenario_2_step_setpoint_changes()
    assert res["status"] == "PASS"
    assert abs(60.0 - res["final_pv_step_up"]) <= 0.5
    assert abs(40.0 - res["final_pv_step_down"]) <= 0.5


def test_scenario_3_anti_windup_clamping():
    """Verify anti-reset windup limits to [0, 100]% and [0, 32000] counts with fast desaturation."""
    res = run_scenario_3_anti_windup_clamping()
    assert res["status"] == "PASS"
    assert res["high_sat_cycles"] == 100
    assert res["low_sat_cycles"] == 100
    assert res["desaturation_instant_cv"] < 100.0


def test_scenario_4_bumpless_manual_to_auto_transfer():
    """Verify bumpless transfer with delta CV <= 0.05% and zero derivative kick."""
    res = run_scenario_4_bumpless_manual_to_auto_transfer()
    assert res["status"] == "PASS"
    assert res["transfer_delta_cv"] < 0.05
    assert math.isclose(res["derivative_kick"], 0.0, abs_tol=1e-3)
    assert res["rapid_toggles_passed"] == 20


def test_scenario_5_inflow_outflow_disturbance_rejection():
    """Verify disturbance rejection under outflow surge, supply loss, and sensor noise."""
    res = run_scenario_5_disturbance_rejection()
    assert res["status"] == "PASS"
    assert res["outflow_surge_settled_cycle"] <= 50
    assert res["supply_loss_residual_error"] < 0.5
    assert res["supply_loss_boosted_integral"] > 55.0
    assert res["noise_cv_std_dev"] < 15.0
