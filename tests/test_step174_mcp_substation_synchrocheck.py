"""Test Suite for Step 174: FastMCP Substation Synchrocheck Audit."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import pytest

HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()

for r in [str(HORNER_ROOT), str(USER_ROOT)]:
    if r not in sys.path:
        sys.path.insert(0, r)

from src.cscape.gate import get_gate_status
from scripts.execute_step174_mcp_substation_synchrocheck import (
    run_step174_mcp_substation_synchrocheck,
    ST_FILE,
    LOG_PATHS,
    CHECKPOINT_PATHS,
)


def test_st_source_file_exists():
    assert ST_FILE.exists()
    content = ST_FILE.read_text(encoding="utf-8")
    assert "PROGRAM SubstationSynchrocheckAutoReclose" in content
    assert "---[ ]---" not in content
    assert "ERR_LADDER_FORBIDDEN" not in content  # clean ST without embedded error markers


@pytest.mark.asyncio
async def test_step174_simulation_pipeline():
    gate = get_gate_status()
    if not gate.get("ready_for_tests"):
        pytest.skip(f"Live Cscape gate not ready: status='{gate.get('status')}', reason='{gate.get('reason')}'")

    res = await run_step174_mcp_substation_synchrocheck()
    assert res.get("status") == "success"
    assert res["scenarios"]["scenario_A_synchrocheck_steady_state"] == "PASSED"
    assert res["scenarios"]["scenario_B_out_of_sync_block"] == "PASSED"
    assert res["scenarios"]["scenario_C_dead_bus_live_line"] == "PASSED"
    assert res["scenarios"]["scenario_D_auto_reclose_shot1"] == "PASSED"
    assert res["scenarios"]["scenario_E_86_lockout"] == "PASSED"

    for lp in LOG_PATHS:
        assert lp.exists()
    for cp in CHECKPOINT_PATHS:
        assert cp.exists()
