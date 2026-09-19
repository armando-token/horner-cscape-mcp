"""Test Suite for Step 189: FastMCP Pipeline Compressor Anti-Surge & Capacity Control Discrete Simulation Audit."""

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

from scripts.execute_step189_mcp_pipeline_compressor import (
    PipelineCompressorAntiSurge,
    run_step189_mcp_pipeline_compressor,
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
    assert "PROGRAM PipelineCompressorAntiSurge" in content
    sha = compute_sha256(ST_FILE.read_bytes())
    assert sha.lower() == EXPECTED_SHA256.lower()

    user_st_file = USER_ROOT / "examples" / "st_applications" / "pipeline_compressor_anti_surge.st"
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
        "invariant_01_steady_state_normal_envelope",
        "invariant_02_incipient_surge_warning",
        "invariant_03_critical_surge_onset",
        "invariant_04_blowoff_test_command",
        "invariant_05_high_discharge_pressure_clamping",
        "invariant_06_multiple_surge_trip_interlock",
        "invariant_07_low_suction_pressure_trip",
        "invariant_08_operator_reset_sequence",
        "invariant_09_stopped_compressor_safe_depressurization",
        "invariant_10_fastmcp_register_partitioning",
        "invariant_11_multi_client_stdio_rpc_isolation",
        "invariant_12_download_lockout",
    ]

    for inv_name in expected_invariants:
        assert inv_name in res["invariants"], f"Missing invariant: {inv_name}"
        inv = res["invariants"][inv_name]
        assert inv["passed"] is True, f"Invariant {inv_name} failed: {inv['description']}"


def test_invariant_01_steady_state_normal_envelope_direct():
    sim = PipelineCompressorAntiSurge(cycle_time_sec=0.1)
    sim.CompressorRunAux = True
    sim.SuctionPressure_psig = 500.0
    sim.DischargePressure_psig = 800.0
    sim.DifferentialPress_inH2O = 60.0
    sim.step()
    assert sim.SurgeMargin_pct > 10.0
    assert sim.RecycleValveOpenCmd is False
    assert sim.FastBlowoffValveCmd is False
    assert sim.SurgeEventAlarmOut is False
    assert sim.TripInterlockOut is False
    assert sim.SurgeMarginLowWarn is False
    assert sim.RecycleModulating is False
    assert sim.CapacityClamped is False
    assert sim.SurgeCount == 0


def test_invariant_02_incipient_surge_warning_direct():
    sim = PipelineCompressorAntiSurge(cycle_time_sec=0.1)
    sim.CompressorRunAux = True
    sim.SuctionPressure_psig = 500.0
    sim.DischargePressure_psig = 800.0
    sim.DifferentialPress_inH2O = 25.5
    sim.step()
    assert sim.SurgeMargin_pct < 10.0
    assert sim.SurgeMargin_pct >= 3.0
    assert sim.SurgeMarginLowWarn is True
    assert sim.RecycleValveOpenCmd is True
    assert sim.RecycleModulating is True
    assert sim.SurgeEventAlarmOut is False
    assert sim.FastBlowoffValveCmd is False
    assert sim.TripInterlockOut is False


def test_invariant_03_critical_surge_onset_direct():
    sim = PipelineCompressorAntiSurge(cycle_time_sec=0.1)
    sim.CompressorRunAux = True
    sim.SuctionPressure_psig = 500.0
    sim.DischargePressure_psig = 800.0
    sim.DifferentialPress_inH2O = 24.0
    sim.step()
    assert sim.SurgeMargin_pct < 3.0
    assert sim.SurgeEventAlarmOut is True
    assert sim.SurgeCycleLatched is True
    assert sim.FastBlowoffValveCmd is True
    assert sim.RecycleValveOpenCmd is True
    assert sim.SurgeCount == 1


def test_invariant_04_blowoff_test_command_direct():
    sim = PipelineCompressorAntiSurge(cycle_time_sec=0.1)
    sim.CompressorRunAux = True
    sim.SuctionPressure_psig = 500.0
    sim.DischargePressure_psig = 800.0
    sim.DifferentialPress_inH2O = 60.0
    sim.FastBlowoffTestCmd = True
    sim.step()
    assert sim.FastBlowoffValveCmd is True
    assert sim.RecycleValveOpenCmd is True
    assert sim.SurgeEventAlarmOut is True
    assert sim.SurgeCycleLatched is True
    assert sim.SurgeCount == 1


def test_invariant_05_high_discharge_pressure_clamping_direct():
    sim = PipelineCompressorAntiSurge(cycle_time_sec=0.1)
    sim.CompressorRunAux = True
    sim.SuctionPressure_psig = 500.0
    sim.DischargePressure_psig = 1250.0
    sim.DifferentialPress_inH2O = 100.0
    sim.step()
    assert sim.CapacityClamped is True
    assert sim.RecycleValveOpenCmd is True
    assert sim.DischargePressure_psig >= 1200.0


def test_invariant_06_multiple_surge_trip_interlock_direct():
    sim = PipelineCompressorAntiSurge(cycle_time_sec=0.1)
    sim.CompressorRunAux = True
    sim.SuctionPressure_psig = 500.0
    sim.DischargePressure_psig = 800.0
    sim.DifferentialPress_inH2O = 22.0
    sim.step()
    assert sim.SurgeCount == 1
    assert sim.TripInterlockOut is False

    sim.step()
    assert sim.SurgeCount >= 2
    assert sim.TripInterlockOut is True
    assert sim.RecycleValveOpenCmd is True
    assert sim.FastBlowoffValveCmd is True


def test_invariant_07_low_suction_pressure_trip_direct():
    sim = PipelineCompressorAntiSurge(cycle_time_sec=0.1)
    sim.CompressorRunAux = True
    sim.SuctionPressure_psig = 180.0
    sim.DischargePressure_psig = 800.0
    sim.DifferentialPress_inH2O = 60.0
    sim.step()
    assert sim.SuctionPressure_psig < 200.0
    assert sim.TripInterlockOut is True
    assert sim.RecycleValveOpenCmd is True
    assert sim.FastBlowoffValveCmd is True


def test_invariant_08_operator_reset_sequence_direct():
    sim = PipelineCompressorAntiSurge(cycle_time_sec=0.1)
    sim.CompressorRunAux = True
    sim.SurgeEventAlarmOut = True
    sim.SurgeCycleLatched = True
    sim.TripInterlockOut = True
    sim.SurgeCount = 2

    # Process normalized + Reset asserted
    sim.SuctionPressure_psig = 500.0
    sim.DischargePressure_psig = 800.0
    sim.DifferentialPress_inH2O = 60.0
    sim.SurgeDetectorResetCmd = True
    sim.step()
    assert sim.SurgeEventAlarmOut is False
    assert sim.SurgeCycleLatched is False
    assert sim.TripInterlockOut is False
    assert sim.SurgeCount == 0

    # Reset released
    sim.SurgeDetectorResetCmd = False
    sim.step()
    assert sim.SurgeEventAlarmOut is False
    assert sim.SurgeCycleLatched is False
    assert sim.TripInterlockOut is False
    assert sim.SurgeCount == 0


def test_invariant_09_stopped_compressor_safe_depressurization_direct():
    sim = PipelineCompressorAntiSurge(cycle_time_sec=0.1)
    sim.CompressorRunAux = False
    sim.SuctionPressure_psig = 400.0
    sim.DischargePressure_psig = 400.0
    sim.DifferentialPress_inH2O = 0.0
    sim.step()
    assert sim.CompressorRunAux is False
    assert sim.RecycleValveOpenCmd is True
    assert sim.FastBlowoffValveCmd is False
    assert sim.SurgeMarginLowWarn is False
    assert sim.RecycleModulating is False
    assert sim.CapacityClamped is False


def test_invariant_10_fastmcp_register_partitioning_direct():
    r_regs = [
        ("%R160", 500.0, "REAL"),
        ("%R161", 800.0, "REAL"),
        ("%R162", 60.0, "REAL"),
        ("%R163", 70.0, "REAL"),
        ("%R164", 10500.0, "REAL"),
        ("%R165", 1.58, "REAL"),
        ("%R166", 150.0, "REAL"),
    ]
    for addr, val, dt in r_regs:
        w = cscape_write_register(address=addr, value=val, data_type=dt, project_name="TankLevelClosedLoop")
        r = cscape_read_register(address=addr, data_type=dt, project_name="TankLevelClosedLoop")
        assert w.get("status") == "success"
        assert r.get("status") == "success"
        assert abs(r.get("value", 0.0) - val) < 0.01

    bit_regs = [
        ("%I24", True), ("%I25", False), ("%I26", True), ("%I27", False),
        ("%Q54", True), ("%Q55", False), ("%Q56", True), ("%Q57", False),
        ("%M75", True), ("%M76", False), ("%M77", True), ("%M78", False),
    ]
    for addr, val in bit_regs:
        w = cscape_write_register(address=addr, value=val, data_type="BOOL", project_name="TankLevelClosedLoop")
        r = cscape_read_register(address=addr, data_type="BOOL", project_name="TankLevelClosedLoop")
        assert w.get("status") == "success"
        assert r.get("status") == "success"
        assert r.get("value") is val


def test_invariant_11_multi_client_stdio_rpc_isolation_direct():
    import concurrent.futures

    def client_worker(address: str, val: float):
        w = cscape_write_register(address=address, value=val, data_type="REAL", project_name="TankLevelClosedLoop")
        r = cscape_read_register(address=address, data_type="REAL", project_name="TankLevelClosedLoop")
        return (w.get("status") == "success" and r.get("status") == "success", r.get("value", 0.0))

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        f1 = executor.submit(client_worker, "%R160", 525.0)
        f2 = executor.submit(client_worker, "%R260", 260.5)
        f3 = executor.submit(client_worker, "%R360", 360.25)
        res1, val1 = f1.result()
        res2, val2 = f2.result()
        res3, val3 = f3.result()

    assert res1 and res2 and res3
    check_r160 = cscape_read_register(address="%R160", data_type="REAL", project_name="TankLevelClosedLoop")
    check_r260 = cscape_read_register(address="%R260", data_type="REAL", project_name="TankLevelClosedLoop")
    check_r360 = cscape_read_register(address="%R360", data_type="REAL", project_name="TankLevelClosedLoop")

    assert abs(check_r160.get("value", 0.0) - 525.0) < 0.001
    assert abs(check_r260.get("value", 0.0) - 260.5) < 0.001
    assert abs(check_r360.get("value", 0.0) - 360.25) < 0.001


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
    """Verify execution of Step 189 and dual-root parity of logs and checkpoints."""
    res = run_step189_mcp_pipeline_compressor()
    assert res["status"] == "success"

    for lp in LOG_PATHS:
        assert lp.exists(), f"Missing log: {lp}"
        data = json.loads(lp.read_text(encoding="utf-8"))
        assert data["status"] == "success"
        assert data["step"] == 189
        assert data["target_pou"] == "PipelineCompressorAntiSurge"

    for cp in CHECKPOINT_PATHS:
        assert cp.exists(), f"Missing checkpoint: {cp}"
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert data["status"] == "success"
        assert data["step"] == 189
        assert data["target_pou"] == "PipelineCompressorAntiSurge"

    # Exact byte parity
    assert LOG_PATHS[0].read_bytes() == LOG_PATHS[1].read_bytes()
    assert CHECKPOINT_PATHS[0].read_bytes() == CHECKPOINT_PATHS[1].read_bytes()


def test_g4_simulation_checkpoint_updated():
    """Verify megaplan_g4_closed_loop_simulation_checkpoint.json reflects step 189."""
    g4_paths = [
        HORNER_ROOT / "artifacts" / "checkpoints" / "megaplan_g4_closed_loop_simulation_checkpoint.json",
        USER_ROOT / "artifacts" / "checkpoints" / "megaplan_g4_closed_loop_simulation_checkpoint.json",
    ]
    for gp in g4_paths:
        assert gp.exists(), f"Missing G4 checkpoint: {gp}"
        g4 = json.loads(gp.read_text(encoding="utf-8"))
        assert g4["gate"] == "G4"
        assert g4["step"] == 189
        assert g4["status"] == "success"
        assert "PipelineCompressorAntiSurge" in g4["active_simulations"]

    assert g4_paths[0].read_bytes() == g4_paths[1].read_bytes()
