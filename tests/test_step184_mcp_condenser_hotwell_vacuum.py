"""Test Suite for Step 184: FastMCP Condenser Hotwell Vacuum Simulation Audit."""

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

from scripts.execute_step184_mcp_condenser_hotwell_vacuum import (
    FBCondenserHotwellVacuumControl,
    run_step184_mcp_condenser_hotwell_vacuum,
    evaluate_simulation_invariants,
    ST_FILE,
    LOG_PATHS,
    CHECKPOINT_PATHS,
    compute_sha256,
)


def test_st_source_file_exists():
    assert ST_FILE.exists(), f"ST file missing: {ST_FILE}"
    content = ST_FILE.read_text(encoding="utf-8")
    assert "FUNCTION_BLOCK FB_CondenserHotwellVacuumControl" in content
    sha = compute_sha256(ST_FILE.read_bytes())
    assert sha.lower() == "7a6513aa5a08468597ad2ccce03029447fc8df5cea3a031f86359423f35db1de"


def test_st_source_pure_iec_no_ladder():
    content = ST_FILE.read_text(encoding="utf-8")
    assert "---[ ]---" not in content
    assert "---( )---" not in content
    assert "---[/]---" not in content
    assert "ERR_LADDER_FORBIDDEN" not in content


def test_all_simulation_invariants():
    res = evaluate_simulation_invariants()
    assert res["status"] == "success"
    assert res["all_invariants_passed"] is True
    for name, inv in res["invariants"].items():
        assert inv["passed"] is True, f"Invariant {name} failed: {inv['description']}"


def test_execution_and_dual_root_parity():
    res = run_step184_mcp_condenser_hotwell_vacuum()
    assert res["status"] == "success"

    for lp in LOG_PATHS:
        assert lp.exists()
        data = json.loads(lp.read_text(encoding="utf-8"))
        assert data["status"] == "success"
        assert data["step"] == 184

    for cp in CHECKPOINT_PATHS:
        assert cp.exists()
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert data["status"] == "success"
        assert data["step"] == 184

    # Parity check
    sha_log0 = compute_sha256(LOG_PATHS[0].read_bytes())
    sha_log1 = compute_sha256(LOG_PATHS[1].read_bytes())
    assert sha_log0 == sha_log1

    sha_chk0 = compute_sha256(CHECKPOINT_PATHS[0].read_bytes())
    sha_chk1 = compute_sha256(CHECKPOINT_PATHS[1].read_bytes())
    assert sha_chk0 == sha_chk1
