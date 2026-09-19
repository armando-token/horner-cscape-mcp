"""Test Suite for Step 175: FastMCP Compressor Anti-Surge Audit."""

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
from scripts.execute_step175_mcp_compressor_anti_surge import (
    run_step175_mcp_compressor_anti_surge,
    ST_FILE,
    LOG_PATHS,
    CHECKPOINT_PATHS,
)


def test_st_source_file_exists():
    assert ST_FILE.exists()
    content = ST_FILE.read_text(encoding="utf-8")
    assert "PROGRAM PipelineCompressorAntiSurge" in content
    assert "---[ ]---" not in content
    assert "ERR_LADDER_FORBIDDEN" not in content


@pytest.mark.asyncio
async def test_step175_simulation_pipeline():
    gate = get_gate_status()
    if not gate.get("ready_for_tests"):
        pytest.skip(f"Live Cscape gate not ready: status='{gate.get('status')}', reason='{gate.get('reason')}'")

    res = await run_step175_mcp_compressor_anti_surge()
    assert res.get("status") == "success"
    assert res["scenarios"]["scenario_A_normal_steady_state"] == "PASSED"
    assert res["scenarios"]["scenario_B_recycle_modulation"] == "PASSED"
    assert res["scenarios"]["scenario_C_fast_blowoff_protection"] == "PASSED"
    assert res["scenarios"]["scenario_D_capacity_clamping"] == "PASSED"
    assert res["scenarios"]["scenario_E_protective_trip"] == "PASSED"

    for lp in LOG_PATHS:
        assert lp.exists()
    for cp in CHECKPOINT_PATHS:
        assert cp.exists()
