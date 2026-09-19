"""Test Suite for Step 176: FastMCP Boiler Master Audit."""

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
from scripts.execute_step176_mcp_boiler_master import (
    run_mcp_boiler_master_step176,
    ST_FILE,
    LOG_PATHS,
    CHECKPOINT_PATHS,
)


def test_st_source_file_exists():
    assert ST_FILE.exists()
    content = ST_FILE.read_text(encoding="utf-8")
    assert "PROGRAM SuperheatedSteamBoilerMaster" in content
    assert "---[ ]---" not in content
    assert "---( )---" not in content
    assert "ERR_LADDER_FORBIDDEN" not in content


@pytest.mark.asyncio
async def test_step176_simulation_pipeline():
    gate = get_gate_status()
    if not gate.get("ready_for_tests"):
        pytest.skip(f"Live Cscape gate not ready: status='{gate.get('status')}', reason='{gate.get('reason')}'")

    res = await run_mcp_boiler_master_step176()
    assert res.get("status") == "success"
    assert res["data"]["scenarios_passed"] == 5

    for lp in LOG_PATHS:
        assert lp.exists()
    for cp in CHECKPOINT_PATHS:
        assert cp.exists()


def test_boiler_master_pure_st_ast_validation():
    from src.iec.validator import IECValidator
    from src.iec.st_parser import STParser
    from src.mcp.tools import cscape_validate_st

    code = ST_FILE.read_text(encoding="utf-8")

    # IECValidator AST & Scope check
    val_res = IECValidator.validate(code)
    assert val_res["valid"] is True
    assert val_res["pou_name"] == "SuperheatedSteamBoilerMaster"
    assert val_res["pou_type"] == "PROGRAM"
    assert len(val_res["errors"]) == 0
    assert len(val_res["warnings"]) == 0
    assert len(val_res["variables"]) == 32

    # STParser Semantic check
    st_p_res = STParser.validate(code)
    assert st_p_res.is_valid is True
    assert len(st_p_res.errors) == 0

    # FastMCP Tool contract check
    mcp_res = cscape_validate_st(code)
    assert mcp_res["status"] == "success"
    assert mcp_res["valid"] is True
    assert len(mcp_res["errors"]) == 0


@pytest.mark.parametrize(
    "construct_name,construct_syntax",
    [
        ("Normally Open Contact", "---[ ]---"),
        ("Normally Closed Contact", "---[/]---"),
        ("Normal Output Coil", "---( )---"),
        ("Set Coil", "---(S)---"),
        ("Reset Coil", "---(R)---"),
        ("Rung Header Marker", "RUNG 1: Combustion Interlock"),
        ("Rung Terminator Marker", "END_RUNG"),
        ("Ladder Instruction Mnemonic", "XIC(FlameHealthy)"),
    ],
)
def test_boiler_master_ladder_constructs_rejected_fail_closed(construct_name, construct_syntax):
    from src.iec.validator import IECValidator
    from src.iec.st_parser import STParser
    from src.cscape.st_ld_interop import STLadderInteropGuard, LadderConstructRejectedError
    from src.mcp.tools import cscape_validate_st

    code = ST_FILE.read_text(encoding="utf-8")
    mutated_code = f"{code}\n\n// Injected ladder construct\n{construct_syntax}\n"

    # 1. FastMCP Tool fail-closed check
    mcp_res = cscape_validate_st(mutated_code)
    assert mcp_res["valid"] is False
    assert (
        (mcp_res.get("failure_location") or {}).get("error_code") == "ERR_LADDER_FORBIDDEN"
        or any("ERR_LADDER_FORBIDDEN" in loc.get("error_code", "") for loc in mcp_res.get("failure_locations", []))
    )

    # 2. STLadderInteropGuard fail-closed check
    with pytest.raises(LadderConstructRejectedError):
        STLadderInteropGuard.enforce_st_code(mutated_code)

    # 3. IECValidator fail-closed check
    val_res = IECValidator.validate(mutated_code)
    assert val_res["valid"] is False
    assert any("ERR_LADDER_FORBIDDEN" in err for err in val_res["errors"])

    # 4. STParser fail-closed check
    st_p_res = STParser.validate(mutated_code)
    assert st_p_res.is_valid is False
    assert any(e.code == "ERR_LADDER_FORBIDDEN" for e in st_p_res.errors)

