"""Test Suite for Step 177: FastMCP Hydro Governor Audit."""

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
from scripts.execute_step177_mcp_hydro_governor import (
    run_mcp_hydro_governor_step177,
    ST_FILE,
    LOG_PATHS,
    CHECKPOINT_PATHS,
)


def test_st_source_file_exists():
    assert ST_FILE.exists()
    content = ST_FILE.read_text(encoding="utf-8")
    assert "PROGRAM HydroelectricGovernorHeadLevelControl" in content
    assert "---[ ]---" not in content
    assert "---( )---" not in content
    assert "ERR_LADDER_FORBIDDEN" not in content


@pytest.mark.asyncio
async def test_step177_simulation_pipeline():
    gate = get_gate_status()
    if not gate.get("ready_for_tests"):
        pytest.skip(f"Live Cscape gate not ready: status='{gate.get('status')}', reason='{gate.get('reason')}'")

    res = await run_mcp_hydro_governor_step177()
    assert res.get("status") == "success"
    assert res["data"]["scenarios_passed"] == 5

    for lp in LOG_PATHS:
        assert lp.exists()
    for cp in CHECKPOINT_PATHS:
        assert cp.exists()
