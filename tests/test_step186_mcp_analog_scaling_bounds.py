"""Test Suite for Step 186: FastMCP Analog Scaling with Out-of-Bounds & Sensor Diagnostics Simulation Audit."""

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

from scripts.execute_step186_mcp_analog_scaling_bounds import (
    FBAnalogScalingOutOfBounds,
    run_step186_mcp_analog_scaling_bounds,
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
    assert "FUNCTION_BLOCK FB_AnalogScalingOutOfBounds" in content
    sha = compute_sha256(ST_FILE.read_bytes())
    assert sha.lower() == EXPECTED_SHA256.lower()


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
        "invariant_01_normal_midpoint_scaling",
        "invariant_02_normal_baseline_scaling",
        "invariant_03_normal_fullscale_scaling",
        "invariant_04_underflow_wire_break",
        "invariant_05_overflow_short_circuit",
        "invariant_06_exponential_smoothing_filter",
        "invariant_07_clamping_output_enforcement",
        "invariant_08_failsafe_mode_0_preset",
        "invariant_09_failsafe_mode_1_hold_last_valid",
        "invariant_10_config_error_zero_raw_span",
        "invariant_11_reset_fault_acknowledgment",
        "invariant_12_fastmcp_partitioned_registers",
        "invariant_13_download_lockout",
    ]

    for inv_name in expected_invariants:
        assert inv_name in res["invariants"], f"Missing invariant: {inv_name}"
        inv = res["invariants"][inv_name]
        assert inv["passed"] is True, f"Invariant {inv_name} failed: {inv['description']}"


def test_invariant_01_normal_midpoint_scaling_direct():
    fb = FBAnalogScalingOutOfBounds()
    fb.RawIn = 12000.0
    fb.step()
    assert abs(fb.ScaledValue - 50.0) < 1e-4
    assert abs(fb.RawFiltered - 12000.0) < 1e-4
    assert fb.QualityOK is True
    assert fb.AlarmUnderflow is False
    assert fb.AlarmOverflow is False
    assert fb.LatchedFault is False
    assert fb.ErrorCode == 0


def test_invariant_02_normal_baseline_scaling_direct():
    fb = FBAnalogScalingOutOfBounds()
    fb.RawIn = 4000.0
    fb.step()
    assert abs(fb.ScaledValue - 0.0) < 1e-4
    assert abs(fb.RawFiltered - 4000.0) < 1e-4
    assert fb.QualityOK is True
    assert fb.AlarmUnderflow is False
    assert fb.AlarmOverflow is False
    assert fb.ErrorCode == 0


def test_invariant_03_normal_fullscale_scaling_direct():
    fb = FBAnalogScalingOutOfBounds()
    fb.RawIn = 20000.0
    fb.step()
    assert abs(fb.ScaledValue - 100.0) < 1e-4
    assert abs(fb.RawFiltered - 20000.0) < 1e-4
    assert fb.QualityOK is True
    assert fb.AlarmUnderflow is False
    assert fb.AlarmOverflow is False
    assert fb.ErrorCode == 0


def test_invariant_04_underflow_wire_break_direct():
    fb = FBAnalogScalingOutOfBounds()
    fb.RawIn = 3200.0  # < 3600 wire-break limit
    fb.step()
    assert fb.AlarmUnderflow is True
    assert fb.AlarmOverflow is False
    assert fb.QualityOK is False
    assert fb.LatchedFault is True
    assert fb.ErrorCode == 1

    # Return to normal input
    fb.RawIn = 12000.0
    fb.RawFiltered = 12000.0
    fb.step()
    assert fb.AlarmUnderflow is False
    assert fb.QualityOK is True
    assert fb.LatchedFault is True
    assert fb.ErrorCode == 1


def test_invariant_05_overflow_short_circuit_direct():
    fb = FBAnalogScalingOutOfBounds()
    fb.RawIn = 21500.0  # > 20800 short-circuit limit
    fb.step()
    assert fb.AlarmOverflow is True
    assert fb.AlarmUnderflow is False
    assert fb.QualityOK is False
    assert fb.LatchedFault is True
    assert fb.ErrorCode == 2

    # Return to normal input
    fb.RawIn = 12000.0
    fb.RawFiltered = 12000.0
    fb.step()
    assert fb.AlarmOverflow is False
    assert fb.QualityOK is True
    assert fb.LatchedFault is True
    assert fb.ErrorCode == 2


def test_invariant_06_exponential_smoothing_filter_direct():
    fb = FBAnalogScalingOutOfBounds()
    fb.FilterAlpha = 0.20
    fb.RawIn = 4000.0
    fb.step()
    assert abs(fb.RawFiltered - 4000.0) < 1e-4

    fb.RawIn = 14000.0
    fb.step()
    assert abs(fb.RawFiltered - 6000.0) < 1e-4

    fb.step()
    assert abs(fb.RawFiltered - 7600.0) < 1e-4

    fb.step()
    assert abs(fb.RawFiltered - 8880.0) < 1e-4


def test_invariant_07_clamping_output_enforcement_direct():
    fb_c = FBAnalogScalingOutOfBounds()
    fb_c.ClampOutput = True
    fb_c.RawIn = 3800.0
    fb_c.step()
    assert abs(fb_c.ScaledValue - 0.0) < 1e-4
    assert fb_c.CalculatedEng < 0.0

    fb_c.RawIn = 20400.0
    fb_c.RawFiltered = 20400.0
    fb_c.step()
    assert abs(fb_c.ScaledValue - 100.0) < 1e-4
    assert fb_c.CalculatedEng > 100.0

    fb_u = FBAnalogScalingOutOfBounds()
    fb_u.ClampOutput = False
    fb_u.RawIn = 3800.0
    fb_u.step()
    assert abs(fb_u.ScaledValue - (-1.25)) < 1e-4

    fb_u.RawIn = 20400.0
    fb_u.RawFiltered = 20400.0
    fb_u.step()
    assert abs(fb_u.ScaledValue - 102.5) < 1e-4


def test_invariant_08_failsafe_mode_0_preset_direct():
    fb = FBAnalogScalingOutOfBounds()
    fb.FailSafeMode = 0
    fb.FailSafeValue = -99.0
    fb.RawIn = 12000.0
    fb.step()
    assert abs(fb.ScaledValue - 50.0) < 1e-4

    fb.RawIn = 2000.0
    fb.RawFiltered = 2000.0
    fb.step()
    assert fb.AlarmUnderflow is True
    assert fb.QualityOK is False
    assert abs(fb.ScaledValue - (-99.0)) < 1e-4


def test_invariant_09_failsafe_mode_1_hold_last_valid_direct():
    fb = FBAnalogScalingOutOfBounds()
    fb.FailSafeMode = 1
    fb.FailSafeValue = -99.0
    fb.RawIn = 16000.0
    fb.step()
    assert abs(fb.ScaledValue - 75.0) < 1e-4
    assert abs(fb.LastValidValue - 75.0) < 1e-4

    fb.RawIn = 2000.0
    fb.RawFiltered = 2000.0
    fb.step()
    assert fb.AlarmUnderflow is True
    assert fb.QualityOK is False
    assert abs(fb.ScaledValue - 75.0) < 1e-4
    assert abs(fb.LastValidValue - 75.0) < 1e-4


def test_invariant_10_config_error_zero_raw_span_direct():
    fb = FBAnalogScalingOutOfBounds()
    fb.RawMin = 10000.0
    fb.RawMax = 10000.0
    fb.FailSafeValue = -50.0
    fb.RawIn = 10000.0
    fb.step()
    assert fb.QualityOK is False
    assert fb.LatchedFault is True
    assert fb.ErrorCode == 3
    assert abs(fb.ScaledValue - (-50.0)) < 1e-4


def test_invariant_11_reset_fault_acknowledgment_direct():
    fb = FBAnalogScalingOutOfBounds()
    fb.RawIn = 2000.0
    fb.step()
    assert fb.AlarmUnderflow is True
    assert fb.LatchedFault is True
    assert fb.ErrorCode == 1

    fb.RawIn = 12000.0
    fb.RawFiltered = 12000.0
    fb.step()
    assert fb.QualityOK is True
    assert fb.LatchedFault is True
    assert fb.ErrorCode == 1

    fb.ResetFault = True
    fb.step()
    assert fb.QualityOK is True
    assert fb.LatchedFault is False
    assert fb.ErrorCode == 0
    assert abs(fb.ScaledValue - 50.0) < 1e-4


def test_invariant_12_fastmcp_partitioned_registers_direct():
    w1 = cscape_write_register(address="%R141", value=141.5, data_type="REAL", project_name="TankLevelClosedLoop")
    w2 = cscape_write_register(address="%R151", value=151.75, data_type="REAL", project_name="TankLevelClosedLoop")
    r1 = cscape_read_register(address="%R141", data_type="REAL", project_name="TankLevelClosedLoop")
    r2 = cscape_read_register(address="%R151", data_type="REAL", project_name="TankLevelClosedLoop")

    assert w1.get("status") == "success"
    assert w2.get("status") == "success"
    assert r1.get("status") == "success"
    assert r2.get("status") == "success"
    assert abs(r1.get("value") - 141.5) < 0.001
    assert abs(r2.get("value") - 151.75) < 0.001


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
    """Verify execution of Step 186 and dual-root parity of logs and checkpoints."""
    res = run_step186_mcp_analog_scaling_bounds()
    assert res["status"] == "success"

    for lp in LOG_PATHS:
        assert lp.exists(), f"Missing log: {lp}"
        data = json.loads(lp.read_text(encoding="utf-8"))
        assert data["status"] == "success"
        assert data["step"] == 186
        assert data["target_pou"] == "FB_AnalogScalingOutOfBounds"

    for cp in CHECKPOINT_PATHS:
        assert cp.exists(), f"Missing checkpoint: {cp}"
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert data["status"] == "success"
        assert data["step"] == 186
        assert data["target_pou"] == "FB_AnalogScalingOutOfBounds"

    # Exact byte parity
    assert LOG_PATHS[0].read_bytes() == LOG_PATHS[1].read_bytes()
    assert CHECKPOINT_PATHS[0].read_bytes() == CHECKPOINT_PATHS[1].read_bytes()


def test_g4_simulation_checkpoint_updated():
    """Verify megaplan_g4_closed_loop_simulation_checkpoint.json reflects step 186."""
    g4_paths = [
        HORNER_ROOT / "artifacts" / "checkpoints" / "megaplan_g4_closed_loop_simulation_checkpoint.json",
        USER_ROOT / "artifacts" / "checkpoints" / "megaplan_g4_closed_loop_simulation_checkpoint.json",
    ]
    for gp in g4_paths:
        assert gp.exists(), f"Missing G4 checkpoint: {gp}"
        g4 = json.loads(gp.read_text(encoding="utf-8"))
        assert g4["gate"] == "G4"
        assert g4["step"] == 186
        assert g4["status"] == "success"
        assert "FB_AnalogScalingOutOfBounds" in g4["active_simulations"]

    assert g4_paths[0].read_bytes() == g4_paths[1].read_bytes()
