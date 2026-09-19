"""Test Suite for Step 188: PLC / IEC 61131-3 Pure ST Audit for FB_PumpLeadLagAlternator."""

from __future__ import annotations

import difflib
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

from src.cscape.st_ld_interop import (
    STLadderInteropGuard,
    LadderConstructRejectedError,
)
from src.iec.lexer import Lexer
from src.iec.parser import Parser
from src.iec.st_parser import STParser
from src.iec.validator import IECValidator
from src.mcp.tools import cscape_validate_st
from scripts.execute_step188_pure_st_audit import (
    HORNER_ST_FILE,
    USER_ST_FILE,
    EXPECTED_SHA256,
    LOG_PATHS,
    CHECKPOINT_PATHS,
    run_step188_pure_st_audit,
    compute_sha256,
)


def test_st_source_file_exists_both_roots():
    """Requirement 1: Verify pump_lead_lag_alternator.st exists in both roots with exact parity."""
    assert HORNER_ST_FILE.exists(), f"Missing file in Horner root: {HORNER_ST_FILE}"
    assert USER_ST_FILE.exists(), f"Missing file in User root: {USER_ST_FILE}"

    horner_bytes = HORNER_ST_FILE.read_bytes()
    user_bytes = USER_ST_FILE.read_bytes()

    sha_horner = compute_sha256(horner_bytes)
    sha_user = compute_sha256(user_bytes)

    assert sha_horner == EXPECTED_SHA256
    assert sha_user == EXPECTED_SHA256
    assert sha_horner == sha_user

    diff = list(
        difflib.unified_diff(
            horner_bytes.decode("utf-8").splitlines(keepends=True),
            user_bytes.decode("utf-8").splitlines(keepends=True),
            fromfile=str(HORNER_ST_FILE),
            tofile=str(USER_ST_FILE),
        )
    )
    assert len(diff) == 0, f"Diff found between roots:\n{''.join(diff)}"


def test_source_code_scan_zero_ladder_constructs():
    """Requirement 2a: Scan source code to verify zero ladder logic constructs."""
    content = HORNER_ST_FILE.read_text(encoding="utf-8")
    assert "FUNCTION_BLOCK FB_PumpLeadLagAlternator" in content
    assert "END_FUNCTION_BLOCK" in content

    # Ladder contacts
    assert "---[ ]---" not in content, "Normally open contact detected!"
    assert "---[/]---" not in content, "Normally closed contact detected!"
    assert "---[ / ]---" not in content, "Spaced NC contact detected!"

    # Ladder coils
    assert "---( )---" not in content, "Relay coil detected!"
    assert "---(S)---" not in content, "Set coil detected!"
    assert "---(R)---" not in content, "Reset coil detected!"

    # Rung / Network markers
    assert "RUNG" not in content, "Rung marker detected!"
    assert "END_RUNG" not in content, "End rung marker detected!"
    assert "NETWORK" not in content, "Network marker detected!"

    # Instruction mnemonics
    for mnemonic in ["XIC", "XIO", "OTE", "OTL", "OTU", "OSR", "OSF"]:
        assert f"{mnemonic}(" not in content, f"Instruction mnemonic {mnemonic} detected!"

    # Clean validator scan
    assert len(IECValidator.check_ladder_artifacts(content)) == 0
    clean_p_res = STParser.validate(content)
    assert not any(e.code == "ERR_LADDER_FORBIDDEN" for e in clean_p_res.errors)


@pytest.mark.parametrize(
    "construct_name,construct_syntax",
    [
        ("Normally Open Contact", "---[ ]---"),
        ("Normally Closed Contact", "---[/]---"),
        ("Spaced Inverted Contact", "---[ / ]---"),
        ("Normal Output Coil", "---( )---"),
        ("Set Latch Coil", "---(S)---"),
        ("Reset Unlatch Coil", "---(R)---"),
        ("Rung Header Marker", "RUNG 1: Pump Lead Lag Alternator"),
        ("Rung Terminator Marker", "END_RUNG"),
        ("Ladder Network Section", "NETWORK 10"),
        ("Instruction Mnemonic XIC", "XIC(Auto_Enable)"),
        ("Instruction Mnemonic XIO", "XIO(Pump1_Run_Cmd)"),
        ("Instruction Mnemonic OTE", "OTE(Pump2_Run_Cmd)"),
    ],
)
def test_ladder_constructs_rejected_fail_closed(construct_name, construct_syntax):
    """Requirement 2b: Injected ladder constructs fail-closed with ERR_LADDER_FORBIDDEN."""
    code = HORNER_ST_FILE.read_text(encoding="utf-8")
    mutated_code = f"{code}\n\n(* Injected Ladder Construct *)\n{construct_syntax}\n"

    # 1. STLadderInteropGuard check
    guard = STLadderInteropGuard()
    with pytest.raises(LadderConstructRejectedError):
        guard.enforce_st_code(mutated_code)

    # 2. IECValidator check
    val_res = IECValidator.validate(mutated_code)
    assert val_res["valid"] is False
    assert any("ERR_LADDER_FORBIDDEN" in err for err in val_res["errors"])

    # 3. STParser check
    st_p_res = STParser.validate(mutated_code)
    assert st_p_res.is_valid is False
    assert any(e.code == "ERR_LADDER_FORBIDDEN" for e in st_p_res.errors)

    # 4. FastMCP Tool check
    mcp_res = cscape_validate_st(mutated_code)
    assert mcp_res["valid"] is False
    assert (
        (mcp_res.get("failure_location") or {}).get("error_code") == "ERR_LADDER_FORBIDDEN"
        or any("ERR_LADDER_FORBIDDEN" in loc.get("error_code", "") for loc in mcp_res.get("failure_locations", []))
        or any("ERR_LADDER_FORBIDDEN" in str(e) for e in mcp_res.get("errors", []))
    )


def test_iec61131_syntax_and_datatypes():
    """Requirement 3: Validate standard IEC 61131-3 syntax and standard data types for FB_PumpLeadLagAlternator."""
    code = HORNER_ST_FILE.read_text(encoding="utf-8")

    val_res = IECValidator.validate(code)
    assert val_res["valid"] is True
    assert val_res["pou_name"] == "FB_PumpLeadLagAlternator"
    assert val_res["pou_type"] == "FUNCTION_BLOCK"
    assert len(val_res["errors"]) == 0
    assert len(val_res["variables"]) == 44

    st_p_res = STParser.validate(code)
    assert st_p_res.is_valid is True
    assert len(st_p_res.errors) == 0

    mcp_res = cscape_validate_st(code)
    assert mcp_res["status"] == "success"
    assert mcp_res["valid"] is True
    assert len(mcp_res["errors"]) == 0

    # Verify standard data types
    standard_types = {"BOOL", "INT", "REAL", "DINT"}
    for var in val_res["variables"]:
        vtype = (var.get("type") or var.get("data_type") or "").upper()
        assert vtype in standard_types, f"Non-standard IEC type for {var['name']}: {vtype}"

    # Verify input count = 17, output count = 13, local count = 14
    inputs = [v for v in val_res["variables"] if v["scope"] == "VAR_INPUT"]
    outputs = [v for v in val_res["variables"] if v["scope"] == "VAR_OUTPUT"]
    locals_ = [v for v in val_res["variables"] if v["scope"] == "VAR"]

    assert len(inputs) == 17
    assert len(outputs) == 13
    assert len(locals_) == 14

    # Verify AST body statements
    lexer = Lexer(code)
    tokens = lexer.tokenize()
    parser = Parser(tokens)
    ast = parser.parse()
    assert len(ast.body) == 18


def test_ast_decomposition_and_sha256():
    """Requirement 4: Verify AST decomposition and compute SHA-256 digest of pump_lead_lag_alternator.st."""
    code = HORNER_ST_FILE.read_text(encoding="utf-8")

    # Verify SHA-256
    digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
    assert digest == EXPECTED_SHA256

    # AST Decomposition via Lexer and Parser
    lexer = Lexer(code)
    tokens = lexer.tokenize()
    assert len(tokens) >= 300

    parser = Parser(tokens)
    ast = parser.parse()

    assert ast.name == "FB_PumpLeadLagAlternator"
    assert ast.pou_type == "FUNCTION_BLOCK"
    assert len(ast.var_blocks) == 3
    assert len(ast.body) == 18

    # Check var blocks
    assert ast.var_blocks[0].block_type == "VAR_INPUT"
    assert len(ast.var_blocks[0].declarations) == 17

    assert ast.var_blocks[1].block_type == "VAR_OUTPUT"
    assert len(ast.var_blocks[1].declarations) == 13

    assert ast.var_blocks[2].block_type == "VAR"
    assert len(ast.var_blocks[2].declarations) == 14


def test_st_to_ld_conversion_blocked_native():
    """Requirement 5: Verify ST-to-LD conversion is BLOCKED_NATIVE: DOCUMENT_ONLY in Cscape 10.2."""
    doc_file = HORNER_ROOT / "docs" / "st_to_ld_conversion_blocked.md"
    assert doc_file.exists(), f"Missing documentation file: {doc_file}"
    doc_content = doc_file.read_text(encoding="utf-8")
    assert "BLOCKED_NATIVE" in doc_content
    assert "DOCUMENT_ONLY" in doc_content

    evidence_file = HORNER_ROOT / "artifacts" / "evidence" / "cscape_st_to_ld_audit.json"
    assert evidence_file.exists(), f"Missing audit evidence file: {evidence_file}"
    evidence_data = json.loads(evidence_file.read_text(encoding="utf-8"))
    cscape_exports = evidence_data.get("Cscape.exe", {}).get("exports", [])
    assert not any("convert" in exp.lower() and "st" in exp.lower() and "ld" in exp.lower() for exp in cscape_exports)


def test_audit_execution_and_artifacts():
    """Requirement 6: Run headless audit execution and verify artifacts and 4-state contract."""
    audit_res = run_step188_pure_st_audit()
    assert audit_res["status"] == "success"
    assert audit_res["target_pou"]["sha256"] == EXPECTED_SHA256
    assert audit_res["dual_root_parity"] is True
    assert audit_res["cscape_gui_mode"] == "headless_static_analysis_only"

    for lp in LOG_PATHS:
        assert lp.exists()
    for cp in CHECKPOINT_PATHS:
        assert cp.exists()
