"""Test Suite for Step 187: FastMCP Fluid Flow Numerical Integrator & Telemetry Pulse Generator Simulation Audit."""

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

from scripts.execute_step187_mcp_flow_totalizer_integrator import (
    FBFlowTotalizer,
    run_step187_mcp_flow_totalizer_integrator,
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
    assert "FUNCTION_BLOCK FB_FlowTotalizer" in content
    sha = compute_sha256(ST_FILE.read_bytes())
    assert sha.lower() == EXPECTED_SHA256.lower()

    user_st_file = USER_ROOT / "examples" / "st_applications" / "flow_totalizer_integrator.st"
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
        "invariant_01_steady_state_trapezoidal_accuracy",
        "invariant_02_low_flow_cutoff_threshold",
        "invariant_03_negative_flow_cutoff_evaluation",
        "invariant_04_reverse_flow_integration",
        "invariant_05_trapezoidal_rate_ramping_dynamics",
        "invariant_06_batch_totalizer_reset_independent",
        "invariant_07_daily_totalizer_reset_independent",
        "invariant_08_master_totalizer_reset",
        "invariant_09_telemetry_pulse_generation_threshold",
        "invariant_10_telemetry_pulse_duration_timer",
        "invariant_11_invalid_timebase_protection",
        "invariant_12_fastmcp_partitioned_registers",
        "invariant_13_download_lockout",
    ]

    for inv_name in expected_invariants:
        assert inv_name in res["invariants"], f"Missing invariant: {inv_name}"
        inv = res["invariants"][inv_name]
        assert inv["passed"] is True, f"Invariant {inv_name} failed: {inv['description']}"


def test_invariant_01_steady_state_trapezoidal_accuracy_direct():
    fb = FBFlowTotalizer()
    fb.FlowRate = 3600.0
    fb.TimeBaseSec = 3600.0
    fb.CycleTimeSec = 0.1
    # Scan 1: PrevRate=0.0 -> IncrementalVol = 0.05
    fb.step()
    assert abs(fb.IncrementalVol - 0.05) < 1e-6
    # Scan 2: Steady-state -> PrevRate=3600.0 -> IncrementalVol = 0.1
    fb.step()
    assert abs(fb.IncrementalVol - 0.1) < 1e-6
    assert abs(fb.NetFlowRate - 3600.0) < 1e-6
    assert abs(fb.TotalMaster - 0.15) < 1e-6


def test_invariant_02_low_flow_cutoff_threshold_direct():
    fb = FBFlowTotalizer()
    fb.FlowRate = 0.3
    fb.LowFlowCutoff = 0.5
    fb.step()
    assert abs(fb.NetFlowRate - 0.0) < 1e-6
    assert abs(fb.IncrementalVol - 0.0) < 1e-6
    assert abs(fb.TotalMaster - 0.0) < 1e-6


def test_invariant_03_negative_flow_cutoff_evaluation_direct():
    fb = FBFlowTotalizer()
    fb.FlowRate = -0.4
    fb.LowFlowCutoff = 0.5
    fb.step()
    assert abs(fb.NetFlowRate - 0.0) < 1e-6
    assert abs(fb.IncrementalVol - 0.0) < 1e-6

    fb.FlowRate = -0.499
    fb.step()
    assert abs(fb.NetFlowRate - 0.0) < 1e-6
    assert abs(fb.IncrementalVol - 0.0) < 1e-6


def test_invariant_04_reverse_flow_integration_direct():
    fb = FBFlowTotalizer()
    fb.FlowRate = -1800.0
    fb.LowFlowCutoff = 0.5
    fb.TimeBaseSec = 3600.0
    fb.CycleTimeSec = 0.1
    # Scan 1: PrevRate=0.0 -> IncrementalVol = -0.025
    fb.step()
    assert abs(fb.IncrementalVol - (-0.025)) < 1e-6
    # Scan 2: Steady reverse flow -> IncrementalVol = -0.05
    fb.step()
    assert abs(fb.NetFlowRate - (-1800.0)) < 1e-6
    assert abs(fb.IncrementalVol - (-0.05)) < 1e-6
    assert fb.TotalMaster < 0.0
    assert abs(fb.TotalMaster - (-0.075)) < 1e-6


def test_invariant_05_trapezoidal_rate_ramping_dynamics_direct():
    fb = FBFlowTotalizer()
    fb.TimeBaseSec = 3600.0
    fb.CycleTimeSec = 0.1
    rates = [360.0 * i for i in range(1, 11)]
    for r in rates:
        fb.FlowRate = r
        fb.step()

    assert abs(fb.NetFlowRate - 3600.0) < 1e-6
    # Exact trapezoidal area = 0.5 m3
    assert abs(fb.TotalMaster - 0.5) < 1e-5


def test_invariant_06_batch_totalizer_reset_independent_direct():
    fb = FBFlowTotalizer()
    fb.FlowRate = 3600.0
    fb.TimeBaseSec = 3600.0
    fb.CycleTimeSec = 0.1
    for _ in range(5):
        fb.step()

    master_before = fb.TotalMaster
    daily_before = fb.TotalDaily
    batch_before = fb.TotalBatch

    fb.ResetBatch = True
    fb.step()
    fb.ResetBatch = False
    fb.step()

    assert batch_before > 0.0
    assert abs(fb.TotalBatch - 0.2) < 1e-5
    assert abs(fb.TotalDaily - (daily_before + 0.2)) < 1e-5
    assert abs(fb.TotalMaster - (master_before + 0.2)) < 1e-5
    assert fb.TotalBatch < fb.TotalDaily
    assert abs(fb.TotalDaily - fb.TotalMaster) < 1e-5


def test_invariant_07_daily_totalizer_reset_independent_direct():
    fb = FBFlowTotalizer()
    fb.FlowRate = 3600.0
    fb.TimeBaseSec = 3600.0
    fb.CycleTimeSec = 0.1
    for _ in range(10):
        fb.step()

    master_before = fb.TotalMaster
    daily_before = fb.TotalDaily

    fb.ResetDaily = True
    fb.step()
    fb.ResetDaily = False
    fb.step()

    assert daily_before > 0.0
    assert abs(fb.TotalDaily - 0.2) < 1e-5
    assert abs(fb.TotalMaster - (master_before + 0.2)) < 1e-5
    assert fb.TotalDaily < fb.TotalMaster


def test_invariant_08_master_totalizer_reset_direct():
    fb = FBFlowTotalizer()
    fb.FlowRate = 3600.0
    fb.TimeBaseSec = 3600.0
    fb.CycleTimeSec = 0.1
    for _ in range(10):
        fb.step()
    assert fb.TotalMaster > 0.5

    fb.FlowRate = 0.0
    fb.step()  # flow rate drops to 0.0
    fb.ResetMaster = True
    fb.step()  # Master reset clears TotalMaster to 0.0
    assert abs(fb.TotalMaster - 0.0) < 1e-6
    assert abs(fb.NetFlowRate - 0.0) < 1e-6


def test_invariant_09_telemetry_pulse_generation_threshold_direct():
    fb = FBFlowTotalizer()
    fb.FlowRate = 3600.0
    fb.TimeBaseSec = 3600.0
    fb.CycleTimeSec = 0.1
    fb.PulseVolume = 10.0
    fb.PulseDurationSec = 0.2

    # Step until right before threshold (accumulated < 10.0)
    while fb.PulseVolumeAcc + 0.1 < fb.PulseVolume:
        fb.step()
    assert fb.PulseOut is False
    assert fb.PulseCount == 0
    assert fb.PulseVolumeAcc < 10.0

    # Step to cross threshold >= 10.0
    while not fb.PulseOut:
        fb.step()

    assert fb.PulseOut is True
    assert fb.PulseCount == 1
    assert fb.PulseVolumeAcc < 0.2


def test_invariant_10_telemetry_pulse_duration_timer_direct():
    fb = FBFlowTotalizer()
    fb.FlowRate = 3600.0
    fb.PrevRate = 3600.0
    fb.TimeBaseSec = 3600.0
    fb.CycleTimeSec = 0.05
    fb.PulseVolume = 1.0
    fb.PulseDurationSec = 0.20  # 4 scans of 0.05s

    for _ in range(19):
        fb.step()
    assert fb.PulseOut is False

    fb.step()  # Scan 20: fires pulse
    assert fb.PulseOut is True
    assert abs(fb.PulseTimer - 0.05) < 1e-4

    fb.step()  # Scan 21
    assert fb.PulseOut is True
    assert abs(fb.PulseTimer - 0.10) < 1e-4

    fb.step()  # Scan 22
    assert fb.PulseOut is True
    assert abs(fb.PulseTimer - 0.15) < 1e-4

    fb.step()  # Scan 23: timer reaches 0.20 -> resets
    assert fb.PulseOut is False
    assert abs(fb.PulseTimer - 0.0) < 1e-4


def test_invariant_11_invalid_timebase_protection_direct():
    fb_zero = FBFlowTotalizer()
    fb_zero.FlowRate = 3600.0
    fb_zero.TimeBaseSec = 0.0
    fb_zero.step()
    assert abs(fb_zero.IncrementalVol - 0.0) < 1e-6
    assert abs(fb_zero.TotalMaster - 0.0) < 1e-6

    fb_neg = FBFlowTotalizer()
    fb_neg.FlowRate = 3600.0
    fb_neg.TimeBaseSec = -50.0
    fb_neg.step()
    assert abs(fb_neg.IncrementalVol - 0.0) < 1e-6
    assert abs(fb_neg.TotalMaster - 0.0) < 1e-6

    fb_sub = FBFlowTotalizer()
    fb_sub.FlowRate = 3600.0
    fb_sub.TimeBaseSec = 0.0001
    fb_sub.step()
    assert abs(fb_sub.IncrementalVol - 0.0) < 1e-6
    assert abs(fb_sub.TotalMaster - 0.0) < 1e-6


def test_invariant_12_fastmcp_partitioned_registers_direct():
    w1 = cscape_write_register(address="%R145", value=145.5, data_type="REAL", project_name="TankLevelClosedLoop")
    w2 = cscape_write_register(address="%R155", value=155.75, data_type="REAL", project_name="TankLevelClosedLoop")
    r1 = cscape_read_register(address="%R145", data_type="REAL", project_name="TankLevelClosedLoop")
    r2 = cscape_read_register(address="%R155", data_type="REAL", project_name="TankLevelClosedLoop")

    assert w1.get("status") == "success"
    assert w2.get("status") == "success"
    assert r1.get("status") == "success"
    assert r2.get("status") == "success"
    assert abs(r1.get("value") - 145.5) < 0.001
    assert abs(r2.get("value") - 155.75) < 0.001


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
    """Verify execution of Step 187 and dual-root parity of logs and checkpoints."""
    res = run_step187_mcp_flow_totalizer_integrator()
    assert res["status"] == "success"

    for lp in LOG_PATHS:
        assert lp.exists(), f"Missing log: {lp}"
        data = json.loads(lp.read_text(encoding="utf-8"))
        assert data["status"] == "success"
        assert data["step"] == 187
        assert data["target_pou"] == "FB_FlowTotalizer"

    for cp in CHECKPOINT_PATHS:
        assert cp.exists(), f"Missing checkpoint: {cp}"
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert data["status"] == "success"
        assert data["step"] == 187
        assert data["target_pou"] == "FB_FlowTotalizer"

    # Exact byte parity
    assert LOG_PATHS[0].read_bytes() == LOG_PATHS[1].read_bytes()
    assert CHECKPOINT_PATHS[0].read_bytes() == CHECKPOINT_PATHS[1].read_bytes()


def test_g4_simulation_checkpoint_updated():
    """Verify megaplan_g4_closed_loop_simulation_checkpoint.json reflects step 187."""
    g4_paths = [
        HORNER_ROOT / "artifacts" / "checkpoints" / "megaplan_g4_closed_loop_simulation_checkpoint.json",
        USER_ROOT / "artifacts" / "checkpoints" / "megaplan_g4_closed_loop_simulation_checkpoint.json",
    ]
    for gp in g4_paths:
        assert gp.exists(), f"Missing G4 checkpoint: {gp}"
        g4 = json.loads(gp.read_text(encoding="utf-8"))
        assert g4["gate"] == "G4"
        assert g4["step"] == 187
        assert g4["status"] == "success"
        assert "FB_FlowTotalizer" in g4["active_simulations"]

    assert g4_paths[0].read_bytes() == g4_paths[1].read_bytes()
