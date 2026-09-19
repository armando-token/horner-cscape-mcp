"""Test Suite for Step 181: FastMCP Industrial ISA-18.2 First-Out Alarm Annunciator Simulation Audit."""

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
from scripts.execute_step181_mcp_first_fault_annunciator import (
    FBFirstFaultAnnunciator,
    run_step181_mcp_first_fault_annunciator,
    ST_FILE,
    LOG_PATHS,
    CHECKPOINT_PATHS,
    compute_sha256,
)


def test_st_source_file_exists():
    """Verify ST source file exists in both roots and matches SHA256."""
    assert ST_FILE.exists(), f"ST file missing: {ST_FILE}"
    content = ST_FILE.read_text(encoding="utf-8")
    assert "FUNCTION_BLOCK FB_FirstFaultAnnunciator" in content
    assert "ISA-18.2" in content
    sha = compute_sha256(ST_FILE.read_bytes())
    assert sha == "ec238723d6afc47df848522483d0cd32c5561a7d95413b2ed4bbbd47f6959f33"


def test_st_source_pure_iec_no_ladder():
    """Enforce pure IEC 61131-3 Structured Text without ladder logic."""
    content = ST_FILE.read_text(encoding="utf-8")
    assert "---[ ]---" not in content, "Ladder contact detected!"
    assert "---( )---" not in content, "Ladder coil detected!"
    assert "---[/]---" not in content, "Inverted contact detected!"
    assert "ERR_LADDER_FORBIDDEN" not in content


def test_first_out_discrimination():
    """Invariant A: First-out discrimination latches root cause and ignores subsequent trips."""
    fb = FBFirstFaultAnnunciator(cycle_time_sec=0.1)
    fb.step()
    assert fb.FirstOutId == 0

    fb.AlarmIn1 = True
    fb.step()
    assert fb.FirstOutId == 1
    assert fb.Latched1 is True

    fb.AlarmIn2 = True
    fb.AlarmIn3 = True
    fb.AlarmIn7 = True
    fb.step()
    assert fb.FirstOutId == 1
    assert fb.Latched2 is True
    assert fb.Latched3 is True
    assert fb.Latched7 is True


def test_flasher_discrimination():
    """Invariant B: Fast flash (2.0 Hz) on first-out vs slow flash (1.0 Hz) on subsequent."""
    fb = FBFirstFaultAnnunciator(cycle_time_sec=0.05)
    fb.AlarmIn1 = True
    fb.step()
    fb.AlarmIn2 = True
    fb.step()

    fast_toggles = 0
    slow_toggles = 0
    prev_fast = fb.FlashFastState
    prev_slow = fb.FlashSlowState

    for _ in range(20):
        fb.step()
        if fb.FlashFastState != prev_fast:
            fast_toggles += 1
            prev_fast = fb.FlashFastState
        if fb.FlashSlowState != prev_slow:
            slow_toggles += 1
            prev_slow = fb.FlashSlowState

    assert fast_toggles > slow_toggles
    assert fast_toggles >= 3
    assert slow_toggles >= 1


def test_horn_and_acknowledge():
    """Invariant C: Audible horn sounds on unack; AckPB silences horn and turns lamp steady."""
    fb = FBFirstFaultAnnunciator(cycle_time_sec=0.1)
    fb.AlarmIn4 = True
    fb.step()
    assert fb.Horn is True
    assert fb.AnyUnack is True

    fb.AckPB = True
    fb.step()
    fb.AckPB = False
    fb.step()
    assert fb.Horn is False
    assert fb.AnyUnack is False
    assert fb.Beacon4 is True


def test_failsafe_reset_interlock():
    """Invariant D: Reset only clears points when field sensor is normal; FirstOutId clears on 100% reset."""
    fb = FBFirstFaultAnnunciator(cycle_time_sec=0.1)
    fb.AlarmIn2 = True
    fb.AlarmIn5 = True
    fb.step()
    fb.AckPB = True
    fb.step()
    fb.AckPB = False

    fb.ResetPB = True
    fb.step()
    fb.ResetPB = False
    assert fb.Latched2 is True and fb.Latched5 is True

    fb.AlarmIn2 = False
    fb.ResetPB = True
    fb.step()
    fb.ResetPB = False
    assert fb.Latched2 is False
    assert fb.Latched5 is True
    assert fb.FirstOutId == 2

    fb.AlarmIn5 = False
    fb.ResetPB = True
    fb.step()
    fb.ResetPB = False
    assert fb.Latched5 is False
    assert fb.FirstOutId == 0
    assert fb.AnyAlarmActive is False


def test_lamp_and_horn_test():
    """Invariant E: TestPB illuminates all beacons and horn without clearing unack/latched state."""
    fb = FBFirstFaultAnnunciator(cycle_time_sec=0.1)
    fb.AlarmIn3 = True
    fb.step()
    assert fb.Beacon1 is False

    fb.TestPB = True
    fb.step()
    assert fb.Horn is True
    assert all([
        fb.Beacon1, fb.Beacon2, fb.Beacon3, fb.Beacon4,
        fb.Beacon5, fb.Beacon6, fb.Beacon7, fb.Beacon8
    ])

    fb.TestPB = False
    fb.step()
    assert fb.Beacon1 is False
    assert fb.Latched3 is True
    assert fb.FirstOutId == 3


@pytest.mark.asyncio
async def test_full_pipeline_execution():
    """Verify full Step 181 async simulation and stdio concurrency pipeline."""
    res = await run_step181_mcp_first_fault_annunciator()
    assert res["status"] == "success"
    assert "data" in res
