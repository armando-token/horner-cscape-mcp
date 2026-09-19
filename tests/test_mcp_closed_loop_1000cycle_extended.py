"""Pytest suite for 1,000-Cycle Extended Closed-Loop Dynamic Simulation.

Validates the full 1,000-cycle execution across all 5 operational phases:
1. Quiescent steady-state PID setpoint tracking at 60.0% SP
2. Physical disturbance rejection: Inflow line pressure surge (+30%) and outflow surge (+20%)
3. Bumpless Manual Transfer: ManualMode=TRUE, ManualOutput=45.0%, back-calculation of IntegralSum=45.0%
4. Step Setpoint Response: Step SP 60% -> 75% and 75% -> 40%
5. Long-term regulation with stochastic sensor noise (+/-0.5% ADC count jitter)
"""

import json
from pathlib import Path
import pytest

from scripts.run_mcp_closed_loop_1000cycle_extended import (
    run_1000cycle_extended_simulation,
    verify_live_gate,
)


def test_001_cscape_gate_live_verification():
    """Verify Cscape live gate is active in artifacts/.cscape_live_gate.json."""
    try:
        gate = verify_live_gate()
    except Exception as e:
        pytest.skip(f"Live Cscape gate not active or offline: {e}")
    assert gate["ready_for_tests"] is True
    assert gate["status"] == "READY_FOR_TESTS"
    assert gate["pid"] > 0
    assert "TankLevelClosedLoop" in gate["project_file"]


def test_002_1000cycle_extended_simulation_execution():
    """Verify execution of full 1,000-cycle extended closed-loop dynamic simulation."""
    try:
        verify_live_gate()
    except Exception as e:
        pytest.skip(f"Live Cscape gate not active or offline: {e}")
    checkpoint = run_1000cycle_extended_simulation()
    assert checkpoint["status"] == "PASSED"
    assert checkpoint["total_cycles_executed"] == 1000
    assert checkpoint["zero_plc_download_enforced"] is True
    assert checkpoint["zero_straton_dependencies_enforced"] is True

    phases = checkpoint["phases"]

    # Phase 1: Steady State
    p1 = phases["phase_1_steady_state_pid_tracking"]
    assert p1["status"] == "PASSED"
    assert abs(p1["final_pv"] - 60.0) <= 0.01

    # Phase 2: Disturbance Rejection
    p2 = phases["phase_2_physical_disturbance_rejection"]
    assert p2["status"] == "PASSED"
    assert p2["final_error"] <= 0.50

    # Phase 3: Bumpless Manual Transfer
    p3 = phases["phase_3_bumpless_manual_transfer"]
    assert p3["status"] == "PASSED"
    assert p3["back_calculated_integral_sum"] == 45.0
    assert p3["transfer_delta_cv"] <= 0.05
    assert p3["derivative_kick"] <= 0.01

    # Phase 4: Step Setpoint Response
    p4 = phases["phase_4_step_setpoint_response"]
    assert p4["status"] == "PASSED"
    assert p4["step_up_60_to_75"]["settled_cycles"] <= 40
    assert p4["step_up_60_to_75"]["overshoot_percent"] <= 5.0
    assert p4["step_down_75_to_40"]["settled_cycles"] <= 40
    assert p4["step_down_75_to_40"]["undershoot_percent"] <= 5.0

    # Phase 5: Stochastic Sensor Noise Regulation
    p5 = phases["phase_5_stochastic_sensor_noise_regulation"]
    assert p5["status"] == "PASSED"
    assert abs(p5["mean_pv"] - 60.0) <= 0.10
    assert abs(p5["drift_percent"]) <= 0.05


def test_003_artifact_files_exist_and_synchronized():
    """Verify that all log, trajectory, and checkpoint artifacts exist in both repos."""
    user_root = Path(r"C:\Users\ArmandoSilva")
    horner_root = Path(r"C:\HornerAI\horner-cscape-mcp")

    for root in [user_root, horner_root]:
        traj = root / "artifacts" / "logs" / "mcp_closed_loop_1000cycle_extended_trajectory.json"
        log = root / "artifacts" / "logs" / "mcp_closed_loop_1000cycle_extended_trajectory.log"
        ckpt = root / "artifacts" / "checkpoints" / "step12_1000cycle_extended_trajectory_checkpoint.json"

        assert traj.exists(), f"Missing {traj}"
        assert log.exists(), f"Missing {log}"
        assert ckpt.exists(), f"Missing {ckpt}"

        traj_data = json.loads(traj.read_text(encoding="utf-8"))
        assert len(traj_data["trajectory"]) == 1000
        assert traj_data["overall_status"] == "PASSED"
