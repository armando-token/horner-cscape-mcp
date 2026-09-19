#!/usr/bin/env python3
r"""Step 182: PLC / IEC 61131-3 Pure ST Audit Script for FB_ValveActuator.

MANDATE & OPERATIONAL RULES:
1. Strict Scope: IEC 61131-3 Structured Text (ST) ONLY. Advanced Ladder logic strictly rejected with ERR_LADDER_FORBIDDEN.
2. Intercept and reject ladder constructs: contacts (---[ ]---), coils (---( )---), rung markers (RUNG, NETWORK), instruction mnemonics (XIC, XIO, OTE).
3. Validate ST files against IEC 61131-3 standard data types and POU structures.
4. Verify examples/st_applications/valve_actuator_controller.st is pure IEC 61131-3 Structured Text.
5. Strict 4-state contract: status: success | failed | blocked | inconclusive.
6. DO NOT touch live Cscape GUI. Headless only.
7. Dual-root parity across C:\HornerAI\horner-cscape-mcp and C:\Users\ArmandoSilva.
"""

from __future__ import annotations

import datetime
import difflib
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()

for root in [HORNER_ROOT, USER_ROOT]:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from src.cscape.st_ld_interop import (
    STLadderInteropGuard,
    LadderConstructRejectedError,
)
from src.iec.lexer import Lexer
from src.iec.parser import Parser
from src.iec.st_parser import STParser
from src.iec.validator import IECValidator
from src.mcp.tools import cscape_validate_st

ST_REL_PATH = Path("examples") / "st_applications" / "valve_actuator_controller.st"
HORNER_ST_FILE = HORNER_ROOT / ST_REL_PATH
USER_ST_FILE = USER_ROOT / ST_REL_PATH

LOG_PATHS = [
    HORNER_ROOT / "artifacts" / "logs" / "step182_pure_st_audit.json",
    USER_ROOT / "artifacts" / "logs" / "step182_pure_st_audit.json",
]

CHECKPOINT_PATHS = [
    HORNER_ROOT / "artifacts" / "checkpoints" / "step182_pure_st_audit_checkpoint.json",
    USER_ROOT / "artifacts" / "checkpoints" / "step182_pure_st_audit_checkpoint.json",
]

EXPECTED_SHA256 = "d42e07a1a149d696839e6b2d470c0939a2cf16bd442379b0161331402a1a3dc2"


def compute_sha256(data: bytes) -> str:
    """Computes SHA-256 hexadecimal hash."""
    return hashlib.sha256(data).hexdigest()


def audit_task1_file_existence_and_parity() -> Dict[str, Any]:
    """Task 1: Verify ST source file exists in both roots with byte parity."""
    t0 = time.perf_counter()
    horner_exists = HORNER_ST_FILE.exists()
    user_exists = USER_ST_FILE.exists()

    if not horner_exists or not user_exists:
        return {
            "status": "failed",
            "error": f"Missing file: horner={horner_exists}, user={user_exists}",
            "horner_path": str(HORNER_ST_FILE),
            "user_path": str(USER_ST_FILE),
            "duration_sec": time.perf_counter() - t0,
        }

    horner_bytes = HORNER_ST_FILE.read_bytes()
    user_bytes = USER_ST_FILE.read_bytes()

    horner_sha = compute_sha256(horner_bytes)
    user_sha = compute_sha256(user_bytes)

    diff = list(
        difflib.unified_diff(
            horner_bytes.decode("utf-8").splitlines(keepends=True),
            user_bytes.decode("utf-8").splitlines(keepends=True),
            fromfile=str(HORNER_ST_FILE),
            tofile=str(USER_ST_FILE),
        )
    )

    is_identical = (horner_sha == user_sha == EXPECTED_SHA256) and (len(diff) == 0)

    return {
        "status": "success" if is_identical else "failed",
        "horner_file": str(HORNER_ST_FILE),
        "user_file": str(USER_ST_FILE),
        "horner_sha256": horner_sha,
        "user_sha256": user_sha,
        "expected_sha256": EXPECTED_SHA256,
        "sha_match": horner_sha == EXPECTED_SHA256,
        "dual_root_parity": horner_sha == user_sha,
        "diff_line_count": len(diff),
        "diff": "".join(diff),
        "file_size_bytes": len(horner_bytes),
        "duration_sec": time.perf_counter() - t0,
    }


def audit_task2_ladder_construct_scan_and_fail_closed() -> Dict[str, Any]:
    """Task 2: Scan ST source for zero ladder logic constructs and test fail-closed rejection."""
    t0 = time.perf_counter()
    code = HORNER_ST_FILE.read_text(encoding="utf-8")

    # 1. Clean source scan
    direct_patterns = [
        ("contact_no", r"---\[\s*\]---"),
        ("contact_nc", r"---\[\s*/\s*\]---"),
        ("coil_normal", r"---\(\s*\)---"),
        ("coil_set_reset", r"---\(\s*[SLR]\s*\)---"),
        ("rung_marker", r"\bRUNG\b"),
        ("end_rung_marker", r"\bEND_RUNG\b"),
        ("network_marker", r"\bNETWORK\s+\d+"),
        ("mnemonic_xic", r"\bXIC\s*\("),
        ("mnemonic_xio", r"\bXIO\s*\("),
        ("mnemonic_ote", r"\bOTE\s*\("),
        ("mnemonic_otl", r"\bOTL\s*\("),
        ("mnemonic_otu", r"\bOTU\s*\("),
    ]

    detected_artifacts = []
    clean_code = IECValidator.strip_comments(code)
    import re

    for name, pattern in direct_patterns:
        match = re.search(pattern, clean_code, re.IGNORECASE)
        if match:
            detected_artifacts.append({"pattern": name, "match": match.group(0)})

    clean_iec_validator_errors = IECValidator.check_ladder_artifacts(code)
    clean_st_parser_res = STParser.validate(code)
    clean_st_parser_ladder_errors = [
        e for e in clean_st_parser_res.errors if e.code == "ERR_LADDER_FORBIDDEN"
    ]

    # 2. Mutated injection fail-closed test
    test_ladder_mutations = [
        ("Normally Open Contact", "---[ ]---"),
        ("Normally Closed Contact", "---[/]---"),
        ("Spaced Inverted Contact", "---[ / ]---"),
        ("Normal Output Coil", "---( )---"),
        ("Set Latch Coil", "---(S)---"),
        ("Reset Unlatch Coil", "---(R)---"),
        ("Rung Header Marker", "RUNG 1: Valve Travel Watchdog"),
        ("Rung Terminator Marker", "END_RUNG"),
        ("Ladder Network Section", "NETWORK 10"),
        ("Instruction Mnemonic XIC", "XIC(LimitOpen)"),
        ("Instruction Mnemonic XIO", "XIO(LimitClosed)"),
        ("Instruction Mnemonic OTE", "OTE(SolOpen)"),
    ]

    guard = STLadderInteropGuard()
    mutation_results = []

    for name, construct in test_ladder_mutations:
        mutated = f"{code}\n\n(* Injected Forbidden Construct *)\n{construct}\n"
        # Interop guard
        guard_rejected = False
        try:
            guard.enforce_st_code(mutated)
        except LadderConstructRejectedError:
            guard_rejected = True

        # IECValidator
        v_res = IECValidator.validate(mutated)
        val_rejected = any("ERR_LADDER_FORBIDDEN" in e for e in v_res.get("errors", []))

        # STParser
        p_res = STParser.validate(mutated)
        parser_rejected = any(e.code == "ERR_LADDER_FORBIDDEN" for e in p_res.errors)

        # FastMCP tool
        m_res = cscape_validate_st(mutated)
        mcp_rejected = (not m_res.get("valid")) and (
            (m_res.get("failure_location") or {}).get("error_code") == "ERR_LADDER_FORBIDDEN"
            or any("ERR_LADDER_FORBIDDEN" in str(e) for e in m_res.get("errors", []))
        )

        all_rejected = guard_rejected and val_rejected and parser_rejected and mcp_rejected
        mutation_results.append({
            "construct_name": name,
            "construct_syntax": construct,
            "guard_rejected": guard_rejected,
            "validator_rejected": val_rejected,
            "parser_rejected": parser_rejected,
            "mcp_rejected": mcp_rejected,
            "fail_closed": all_rejected,
        })

    all_fail_closed = all(m["fail_closed"] for m in mutation_results)
    is_pure_st = (
        len(detected_artifacts) == 0
        and len(clean_iec_validator_errors) == 0
        and len(clean_st_parser_ladder_errors) == 0
        and all_fail_closed
    )

    return {
        "status": "success" if is_pure_st else "failed",
        "clean_scan_artifacts_count": len(detected_artifacts),
        "clean_scan_artifacts": detected_artifacts,
        "clean_validator_errors": clean_iec_validator_errors,
        "clean_st_parser_ladder_errors": [str(e) for e in clean_st_parser_ladder_errors],
        "mutation_tests_total": len(mutation_results),
        "mutation_tests_fail_closed": sum(1 for m in mutation_results if m["fail_closed"]),
        "mutation_results": mutation_results,
        "duration_sec": time.perf_counter() - t0,
    }


def audit_task3_iec61131_syntax_and_datatypes() -> Dict[str, Any]:
    """Task 3: Validate standard IEC 61131-3 syntax and data types for FB_ValveActuator."""
    t0 = time.perf_counter()
    code = HORNER_ST_FILE.read_text(encoding="utf-8")

    # 1. IECValidator check
    val_res = IECValidator.validate(code)
    # 2. STParser check
    st_res = STParser.validate(code)
    # 3. FastMCP tool check
    mcp_res = cscape_validate_st(code)

    # Validate variables and data types
    declared_vars = val_res.get("variables", [])
    expected_data_types = {"BOOL", "REAL", "DINT"}

    var_analysis = []
    type_violations = []

    for v in declared_vars:
        dtype = (v.get("type") or v.get("data_type") or "").upper()
        name = v.get("name", "")
        scope = v.get("scope", "")
        init = v.get("initial_value")
        if dtype not in expected_data_types:
            type_violations.append(f"{name}: {dtype}")
        var_analysis.append({
            "name": name,
            "data_type": dtype,
            "scope": scope,
            "initial_value": init,
        })

    # Expected inputs, outputs, locals
    inputs = [v for v in var_analysis if v["scope"] == "VAR_INPUT"]
    outputs = [v for v in var_analysis if v["scope"] == "VAR_OUTPUT"]
    locals_ = [v for v in var_analysis if v["scope"] == "VAR"]

    is_valid = (
        val_res.get("valid") is True
        and val_res.get("pou_name") == "FB_ValveActuator"
        and val_res.get("pou_type") == "FUNCTION_BLOCK"
        and st_res.is_valid is True
        and len(st_res.errors) == 0
        and mcp_res.get("valid") is True
        and len(type_violations) == 0
        and len(inputs) == 11
        and len(outputs) == 9
        and len(locals_) == 4
    )

    return {
        "status": "success" if is_valid else "failed",
        "pou_name": val_res.get("pou_name"),
        "pou_type": val_res.get("pou_type"),
        "total_variables": len(var_analysis),
        "input_count": len(inputs),
        "output_count": len(outputs),
        "local_count": len(locals_),
        "type_violations": type_violations,
        "iec_validator_valid": val_res.get("valid"),
        "st_parser_valid": st_res.is_valid,
        "mcp_validator_valid": mcp_res.get("valid"),
        "variables": var_analysis,
        "duration_sec": time.perf_counter() - t0,
    }


def audit_task4_ast_decomposition() -> Dict[str, Any]:
    """Task 4: AST decomposition and lexical verification."""
    t0 = time.perf_counter()
    code = HORNER_ST_FILE.read_text(encoding="utf-8")

    lexer = Lexer(code)
    tokens = lexer.tokenize()

    parser = Parser(tokens)
    ast = parser.parse()

    # Decompose AST
    var_blocks_summary = []
    for vb in ast.var_blocks:
        decls = [
            {
                "name": d.name,
                "data_type": d.data_type,
                "initial_value": str(d.initial_value) if d.initial_value else None,
            }
            for d in vb.declarations
        ]
        var_blocks_summary.append({
            "block_type": vb.block_type,
            "declarations_count": len(decls),
            "declarations": decls,
        })

    statements_summary = []
    for idx, stmt in enumerate(ast.body):
        line = stmt.loc.line if stmt.loc else None
        statements_summary.append({
            "index": idx + 1,
            "statement_type": type(stmt).__name__,
            "line": line,
        })

    lines = code.splitlines()
    sha256_val = compute_sha256(code.encode("utf-8"))

    is_valid = (
        ast.name == "FB_ValveActuator"
        and ast.pou_type == "FUNCTION_BLOCK"
        and len(ast.var_blocks) == 3
        and len(ast.body) == 8
        and sha256_val == EXPECTED_SHA256
    )

    return {
        "status": "success" if is_valid else "failed",
        "pou_name": ast.name,
        "pou_type": ast.pou_type,
        "sha256": sha256_val,
        "total_lines": len(lines),
        "total_tokens": len(tokens),
        "var_blocks_count": len(var_blocks_summary),
        "var_blocks": var_blocks_summary,
        "statements_count": len(statements_summary),
        "statements": statements_summary,
        "duration_sec": time.perf_counter() - t0,
    }


def run_step182_pure_st_audit() -> Dict[str, Any]:
    """Runs the complete Step 182 Pure ST Audit with 4-state contract."""
    start_time = time.perf_counter()
    ts_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()

    task1 = audit_task1_file_existence_and_parity()
    task2 = audit_task2_ladder_construct_scan_and_fail_closed()
    task3 = audit_task3_iec61131_syntax_and_datatypes()
    task4 = audit_task4_ast_decomposition()

    all_tasks = [task1, task2, task3, task4]
    overall_success = all(t["status"] == "success" for t in all_tasks)

    duration = time.perf_counter() - start_time

    audit_report = {
        "step": 182,
        "name": "step182_pure_st_audit",
        "status": "success" if overall_success else "failed",
        "timestamp_utc": ts_utc,
        "mandate": "PLC / IEC 61131-3 Pure ST Audit for FB_ValveActuator",
        "execution_duration_sec": round(duration, 4),
        "dual_root_parity": task1["status"] == "success" and task1.get("dual_root_parity", False),
        "cscape_gui_mode": "headless_static_analysis_only",
        "target_pou": {
            "name": "FB_ValveActuator",
            "type": "FUNCTION_BLOCK",
            "relative_path": str(ST_REL_PATH).replace("\\", "/"),
            "sha256": task1.get("horner_sha256"),
            "expected_sha256": EXPECTED_SHA256,
            "byte_size": task1.get("file_size_bytes"),
            "lines": task4.get("total_lines"),
        },
        "tasks": {
            "task1_file_existence_and_parity": task1,
            "task2_ladder_construct_scan_and_fail_closed": task2,
            "task3_iec61131_syntax_and_datatypes": task3,
            "task4_ast_decomposition": task4,
        },
    }

    checkpoint_data = {
        "step": 182,
        "gate": "G4",
        "name": "step182_pure_st_audit_checkpoint",
        "status": "success" if overall_success else "failed",
        "timestamp_utc": ts_utc,
        "mandate": "PLC / IEC 61131-3 Pure ST Audit: valve_actuator_controller.st",
        "execution_duration_sec": round(duration, 4),
        "dual_root_parity": audit_report["dual_root_parity"],
        "sha256": task1.get("horner_sha256"),
        "expected_sha256": EXPECTED_SHA256,
        "pure_iec61131_3_verified": overall_success,
        "ladder_artifacts_detected": task2.get("clean_scan_artifacts_count", 0),
        "ladder_mutations_rejected_fail_closed": task2.get("mutation_tests_fail_closed", 0),
        "pou": "FB_ValveActuator",
        "pou_type": "FUNCTION_BLOCK",
        "total_variables": task3.get("total_variables", 0),
        "total_ast_statements": task4.get("statements_count", 0),
    }

    # Persist logs and checkpoints to both roots
    for lp in LOG_PATHS:
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text(json.dumps(audit_report, indent=2), encoding="utf-8")

    for cp in CHECKPOINT_PATHS:
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(checkpoint_data, indent=2), encoding="utf-8")

    return audit_report


if __name__ == "__main__":
    result = run_step182_pure_st_audit()
    print(f"Audit Completed. Status: {result['status']}")
    print(f"SHA-256: {result['target_pou']['sha256']}")
    print(f"Duration: {result['execution_duration_sec']}s")
    if result["status"] != "success":
        sys.exit(1)
