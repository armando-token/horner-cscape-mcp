"""Test Suite for Step 190: PLC / IEC 61131-3 Pure ST Audit for CCGTHRSGDrumLevelDuctBurnerControl."""

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
from scripts.execute_step190_pure_st_audit import (
    HORNER_ST_FILE,
    USER_ST_FILE,
    EXPECTED_SHA256,
    EXPECTED_BYTE_SIZE,
    LOG_PATHS,
    CHECKPOINT_PATHS,
    run_step190_pure_st_audit,
    compute_sha256,
)


def test_st_source_file_exists_both_roots():
    """Requirement 1: Verify ccgt_hrsg_drum_level_duct_burner_control.st exists in both roots with exact parity."""
    assert HORNER_ST_FILE.exists(), f"Missing file in Horner root: {HORNER_ST_FILE}"
    assert USER_ST_FILE.exists(), f"Missing file in User root: {USER_ST_FILE}"

    horner_bytes = HORNER_ST_FILE.read_bytes()
    user_bytes = USER_ST_FILE.read_bytes()

    sha_horner = compute_sha256(horner_bytes)
    sha_user = compute_sha256(user_bytes)

    assert sha_horner == EXPECTED_SHA256
    assert sha_user == EXPECTED_SHA256
    assert sha_horner == sha_user
    assert len(horner_bytes) == EXPECTED_BYTE_SIZE
    assert len(user_bytes) == EXPECTED_BYTE_SIZE

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
    assert "PROGRAM CCGTHRSGDrumLevelDuctBurnerControl" in content
    assert "END_PROGRAM" in content

    # Ladder contacts
    assert "---[ ]---" not in content, "Normally open contact detected!"
    assert "---[/]---" not in content, "Normally closed contact detected!"
    assert "---[ / ]---" not in content, "Spaced NC contact detected!"

    # Ladder coils
    assert "---( )---" not in content, "Relay coil detected!"
    assert "---(S)---" not in content, "Set coil detected!"
    assert "---(R)---" not in content, "Reset coil detected!"
    assert "---S---" not in content, "Shorthand set coil detected!"
    assert "---R---" not in content, "Shorthand reset coil detected!"

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
        ("Shorthand Set Coil", "---S---"),
        ("Shorthand Reset Coil", "---R---"),
        ("Rung Header Marker", "RUNG 1: CCGT Drum Level Firing"),
        ("Rung Terminator Marker", "END_RUNG"),
        ("Ladder Network Section", "NETWORK 10"),
        ("Instruction Mnemonic XIC", "XIC(GTRunPermissiveAux)"),
        ("Instruction Mnemonic XIO", "XIO(EmergencyBlowdownValveOpen)"),
        ("Instruction Mnemonic OTE", "OTE(DuctBurnerFuelGasBlockOpen)"),
        ("Instruction Mnemonic OTL", "OTL(LowLowDrumLevelTripLatched)"),
        ("Instruction Mnemonic OTU", "OTU(LowLowDrumLevelTripLatched)"),
    ],
)
def test_ladder_constructs_rejected_fail_closed(construct_name, construct_syntax):
    """Requirement 2b: Injected ladder constructs fail-closed with ERR_LADDER_FORBIDDEN."""
    code = HORNER_ST_FILE.read_text(encoding="utf-8")
    mutated_code = code + "\n\n(* Injected Ladder Construct *)\n" + construct_syntax + "\n"

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
        or any("ERR_LADDER_FORBIDDEN" in loc.get("error_code", "") for loc in m_res.get("failure_locations", []))
        or any("ERR_LADDER_FORBIDDEN" in str(e) for e in mcp_res.get("errors", []))
    )


def test_iec61131_syntax_and_datatypes():
    """Requirement 3: Validate standard IEC 61131-3 syntax, variables, OCS addresses for CCGTHRSGDrumLevelDuctBurnerControl."""
    code = HORNER_ST_FILE.read_text(encoding="utf-8")

    val_res = IECValidator.validate(code)
    assert val_res["valid"] is True
    assert val_res["pou_name"] == "CCGTHRSGDrumLevelDuctBurnerControl"
    assert val_res["pou_type"] == "PROGRAM"
    assert len(val_res["errors"]) == 0
    assert len(val_res["variables"]) == 33

    st_p_res = STParser.validate(code)
    assert st_p_res.is_valid is True
    assert len(st_p_res.errors) == 0

    mcp_res = cscape_validate_st(code)
    assert mcp_res["status"] == "success"
    assert mcp_res["valid"] is True
    assert len(mcp_res["errors"]) == 0

    # Verify standard data types
    standard_types = {"BOOL", "REAL"}
    var_dict = {}
    for var in val_res["variables"]:
        vtype = (var.get("type") or var.get("data_type") or "").upper()
        assert vtype in standard_types, f"Non-standard IEC type for {var['name']}: {vtype}"
        var_dict[var["name"]] = var

    # Verify Analog Inputs (%R190-%R197)
    expected_r = {
        "DrumLevel_PV_mm": "%R190",
        "SteamFlow_Rate_kgs": "%R191",
        "FeedwaterFlow_Rate_kgs": "%R192",
        "GT_ExhaustTemp_degC": "%R193",
        "DuctBurnerFiringDemand_pct": "%R194",
        "FeedwaterValveOutput_pct": "%R195",
        "DrumPressure_bar": "%R196",
        "BlowdownFlow_Rate_kgs": "%R197",
    }
    for vname, exp_addr in expected_r.items():
        assert vname in var_dict, f"Missing %R variable: {vname}"
        assert var_dict[vname]["address"] == exp_addr, f"Address mismatch for {vname}"
        assert var_dict[vname]["type"] == "REAL"

    # Verify Digital Inputs (%I36-%I40)
    expected_i = {
        "GTRunPermissiveAux": "%I36",
        "BoilerFeedPumpARunningAux": "%I37",
        "BoilerFeedPumpBRunningAux": "%I38",
        "DuctBurnerFlameDetected": "%I39",
        "EmergencyTripResetPB": "%I40",
    }
    for vname, exp_addr in expected_i.items():
        assert vname in var_dict, f"Missing %I variable: {vname}"
        assert var_dict[vname]["address"] == exp_addr, f"Address mismatch for {vname}"
        assert var_dict[vname]["type"] == "BOOL"

    # Verify Digital Outputs (%Q68-%Q71)
    expected_q = {
        "FeedwaterControlAutoOnline": "%Q68",
        "DuctBurnerFuelGasBlockOpen": "%Q69",
        "EmergencyBlowdownValveOpen": "%Q70",
        "DrumProtectionCommonAlarm": "%Q71",
    }
    for vname, exp_addr in expected_q.items():
        assert vname in var_dict, f"Missing %Q variable: {vname}"
        assert var_dict[vname]["address"] == exp_addr, f"Address mismatch for {vname}"
        assert var_dict[vname]["type"] == "BOOL"

    # Verify Internal Flags (%M90-%M97)
    expected_m = {
        "ThreeElementModeActive": "%M90",
        "DrumSwellShrinkActive": "%M91",
        "HighDrumLevelWarning": "%M92",
        "LowDrumLevelWarning": "%M93",
        "LowLowDrumLevelTripLatched": "%M94",
        "HighHighDrumCarryoverTrip": "%M95",
        "DuctBurnerPermissiveOK": "%M96",
        "BoilerMasterTripActive": "%M97",
    }
    for vname, exp_addr in expected_m.items():
        assert vname in var_dict, f"Missing %M variable: {vname}"
        assert var_dict[vname]["address"] == exp_addr, f"Address mismatch for {vname}"
        assert var_dict[vname]["type"] == "BOOL"


def test_ast_decomposition_and_sha256():
    """Requirement 4: Verify AST decomposition and compute SHA-256 digest of ccgt_hrsg_drum_level_duct_burner_control.st."""
    code = HORNER_ST_FILE.read_text(encoding="utf-8")

    # Verify SHA-256 and byte size
    digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
    assert digest == EXPECTED_SHA256
    assert len(code.encode("utf-8")) == EXPECTED_BYTE_SIZE

    # AST Decomposition via Lexer and Parser
    lexer = Lexer(code)
    tokens = lexer.tokenize()
    assert len(tokens) >= 450

    parser = Parser(tokens)
    ast = parser.parse()

    assert ast.name == "CCGTHRSGDrumLevelDuctBurnerControl"
    assert ast.pou_type == "PROGRAM"
    assert len(ast.var_blocks) == 1
    assert len(ast.var_blocks[0].declarations) == 33
    assert len(ast.body) == 8


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
    audit_res = run_step190_pure_st_audit()
    assert audit_res["status"] == "success"
    assert audit_res["target_pou"]["sha256"] == EXPECTED_SHA256
    assert audit_res["target_pou"]["byte_size"] == EXPECTED_BYTE_SIZE
    assert audit_res["dual_root_parity"] is True
    assert audit_res["cscape_gui_mode"] == "headless_static_analysis_only"

    for lp in LOG_PATHS:
        assert lp.exists()
    for cp in CHECKPOINT_PATHS:
        assert cp.exists()
