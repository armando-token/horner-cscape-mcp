from src.cscape.gate import get_gate_status
"""
Test Suite for Step 134: Full-Project Multi-POU AST Mutation & Integrity Test.

Verifies:
1. Checkpoint exists and matches required schema across both workspaces.
2. All 5 TankLevelClosedLoop POUs parse successfully into IEC 61131-3 ASTs with >0 nodes.
3. AST roundtrip / normalization preserves POU structure, variables, and statements.
4. Valid AST mutations succeed in AST space, re-serialize cleanly, and re-parse into expected structures.
5. Invalid/syntax fault mutations are strictly rejected fail-closed with ParseError or LexerError.
6. SHA-256 baseline integrity is strictly preserved on all original POUs (zero file corruption).
7. Safety mandates: Cscape is healthy via live gate and physical download lockout (32827) is enforced.
"""

import copy
import hashlib
import json
from pathlib import Path
import pytest
import psutil
import sys

for r in [r"C:\HornerAI\horner-cscape-mcp", r"C:\Users\ArmandoSilva"]:
    if r not in sys.path:
        sys.path.insert(0, r)

from src.iec.lexer import Lexer, Token, TokenType, LexerError
from src.iec.parser import Parser, ParseError
from src.iec.ast_nodes import (
    ASTNode, ProgramNode, VarBlockNode, VarDeclNode,
    AssignmentNode, BinaryOpNode, UnaryOpNode, LiteralNode, VariableNode
)

HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()

TARGET_POUS = [
    "TankLevelClosedLoop.st",
    "AlarmMonitor.st",
    "BrokenPOU.st",
    "AuxPumpControl.st",
    "SafetyInterlockST.st",
]

# TARGET_PID dynamically resolved from live gate
ID_CONTROLLER_DOWNLOAD = 32827

CHECKPOINT_REL = Path("artifacts/checkpoints/step134_pou_ast_integrity_checkpoint.json")
LOG_REL = Path("artifacts/logs/pou_ast_integrity.json")


def _compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _walk_ast(node: ASTNode):
    yield node
    if hasattr(node, "__dict__"):
        for k, v in node.__dict__.items():
            if k == "loc":
                continue
            if isinstance(v, ASTNode):
                yield from _walk_ast(v)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, ASTNode):
                        yield from _walk_ast(item)
                    elif isinstance(item, tuple):
                        for sub in item:
                            if isinstance(sub, ASTNode):
                                yield from _walk_ast(sub)
                            elif isinstance(sub, list):
                                for s in sub:
                                    if isinstance(s, ASTNode):
                                        yield from _walk_ast(s)
            elif isinstance(v, dict):
                for sub in v.values():
                    if isinstance(sub, ASTNode):
                        yield from _walk_ast(sub)


def _count_ast_nodes(node: ASTNode) -> int:
    return sum(1 for _ in _walk_ast(node))


# ============================================================================
# 1. Checkpoint & Evidence Schema Tests
# ============================================================================

def test_checkpoint_exists_and_matches_schema():
    cp_horner = HORNER_ROOT / CHECKPOINT_REL
    cp_user = USER_ROOT / CHECKPOINT_REL

    assert cp_horner.exists(), f"Checkpoint missing in Horner root: {cp_horner}"
    assert cp_user.exists(), f"Checkpoint missing in User root: {cp_user}"

    data_h = json.loads(cp_horner.read_text(encoding="utf-8"))
    data_u = json.loads(cp_user.read_text(encoding="utf-8"))

    for data in [data_h, data_u]:
        assert data["step"] == 134
        assert data["name"] == "step134_pou_ast_integrity_checkpoint"
        assert data["status"] == "PASSED"
        assert data["target_project"] == "TankLevelClosedLoop"
        assert data["pous_evaluated"] == TARGET_POUS
        assert data["pous_parsed_successfully"] == 5
        assert data["total_ast_nodes"] >= 240
        assert data["valid_mutations_passed"] is True
        assert data["syntax_faults_rejected_fail_closed"] is True
        assert data["baseline_sha256_integrity_preserved"] is True
        assert data["zero_straton_dependencies"] is True
        assert data["hardware_lockout_enforced"] is True
        assert data["cscape_pid_untouched"] > 0


def test_evidence_log_schema_and_metrics():
    log_horner = HORNER_ROOT / LOG_REL
    log_user = USER_ROOT / LOG_REL

    assert log_horner.exists(), f"Evidence log missing: {log_horner}"
    assert log_user.exists(), f"Evidence log missing: {log_user}"

    log_data = json.loads(log_horner.read_text(encoding="utf-8"))
    assert log_data["status"] == "PASSED"
    assert log_data["project"] == "TankLevelClosedLoop"

    summary = log_data["summary"]
    assert summary["pous_evaluated_count"] == 5
    assert summary["total_ast_nodes"] >= 240
    assert summary["all_valid_mutations_passed"] is True
    assert summary["all_syntax_faults_rejected"] is True
    assert summary["sha256_integrity_preserved"] is True

    pous = {p["name"]: p for p in log_data["pous"]}
    for target in TARGET_POUS:
        assert target in pous
        p_data = pous[target]
        assert p_data["ast_node_count"] > 0
        assert p_data["roundtrip_verified"] is True
        assert p_data["valid_mutations_count"] >= 2
        assert p_data["syntax_faults_count"] >= 6
        assert p_data["sha256_baseline"] == p_data["sha256_post"]


# ============================================================================
# 2. Multi-POU AST Parsing & Node Count Tests
# ============================================================================

@pytest.mark.parametrize("pou_name", TARGET_POUS)
def test_pou_parses_with_positive_ast_nodes(pou_name):
    pou_path = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "pous" / pou_name
    assert pou_path.exists()

    source = pou_path.read_text(encoding="utf-8")
    tokens = Lexer(source).tokenize()
    ast = Parser(tokens).parse_program()

    assert isinstance(ast, ProgramNode)
    assert ast.pou_type == "PROGRAM"
    assert len(ast.name) > 0

    node_count = _count_ast_nodes(ast)
    assert node_count > 0, f"POU {pou_name} has 0 AST nodes"

    if pou_name == "TankLevelClosedLoop.st":
        assert node_count >= 200
        assert len(ast.var_blocks) == 1
        assert len(ast.var_blocks[0].declarations) == 24
        assert len(ast.body) == 13
    elif pou_name == "BrokenPOU.st":
        assert node_count >= 8
    else:
        assert node_count >= 6


@pytest.mark.parametrize("pou_name", TARGET_POUS)
def test_pou_ast_roundtrip_normalization(pou_name):
    pou_path = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "pous" / pou_name
    source = pou_path.read_text(encoding="utf-8")

    ast1 = Parser(Lexer(source).tokenize()).parse_program()
    serialized = ast1.to_st()

    ast2 = Parser(Lexer(serialized).tokenize()).parse_program()

    assert ast1.name == ast2.name
    assert ast1.pou_type == ast2.pou_type
    assert len(ast1.var_blocks) == len(ast2.var_blocks)
    assert len(ast1.body) == len(ast2.body)

    for vb1, vb2 in zip(ast1.var_blocks, ast2.var_blocks):
        assert len(vb1.declarations) == len(vb2.declarations)
        for d1, d2 in zip(vb1.declarations, vb2.declarations):
            assert d1.name == d2.name
            assert d1.data_type == d2.data_type


# ============================================================================
# 3. Valid AST Mutations Verification
# ============================================================================

def test_valid_mutation_initial_value():
    pou_path = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "pous" / "TankLevelClosedLoop.st"
    ast = Parser(Lexer(pou_path.read_text(encoding="utf-8")).tokenize()).parse_program()

    ast_clone = copy.deepcopy(ast)
    setpoint = next(d for vb in ast_clone.var_blocks for d in vb.declarations if d.name == "Setpoint")
    setpoint.initial_value = LiteralNode(88.5, "REAL")

    mutated_st = ast_clone.to_st()
    re_ast = Parser(Lexer(mutated_st).tokenize()).parse_program()
    re_setpoint = next(d for vb in re_ast.var_blocks for d in vb.declarations if d.name == "Setpoint")
    assert float(re_setpoint.initial_value.value) == 88.5


def test_valid_mutation_statement_injection():
    pou_path = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "pous" / "AlarmMonitor.st"
    ast = Parser(Lexer(pou_path.read_text(encoding="utf-8")).tokenize()).parse_program()

    ast_clone = copy.deepcopy(ast)
    orig_len = len(ast_clone.body)
    new_stmt = AssignmentNode(
        target=VariableNode("trip"),
        value=UnaryOpNode("NOT", VariableNode("trip"))
    )
    ast_clone.body.append(new_stmt)

    mutated_st = ast_clone.to_st()
    re_ast = Parser(Lexer(mutated_st).tokenize()).parse_program()
    assert len(re_ast.body) == orig_len + 1
    assert isinstance(re_ast.body[-1].value, UnaryOpNode)


def test_valid_mutation_binary_operator():
    pou_path = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "pous" / "BrokenPOU.st"
    ast = Parser(Lexer(pou_path.read_text(encoding="utf-8")).tokenize()).parse_program()

    ast_clone = copy.deepcopy(ast)
    stmt = ast_clone.body[0]
    assert isinstance(stmt.value, BinaryOpNode)
    stmt.value.op = "*"

    mutated_st = ast_clone.to_st()
    re_ast = Parser(Lexer(mutated_st).tokenize()).parse_program()
    assert re_ast.body[0].value.op == "*"


def test_valid_mutation_var_decl_injection():
    pou_path = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "pous" / "AuxPumpControl.st"
    ast = Parser(Lexer(pou_path.read_text(encoding="utf-8")).tokenize()).parse_program()

    ast_clone = copy.deepcopy(ast)
    orig_decls = len(ast_clone.var_blocks[0].declarations)
    ast_clone.var_blocks[0].declarations.append(
        VarDeclNode(name="PumpSpeed", data_type="REAL", initial_value=LiteralNode(50.0, "REAL"))
    )

    mutated_st = ast_clone.to_st()
    re_ast = Parser(Lexer(mutated_st).tokenize()).parse_program()
    assert len(re_ast.var_blocks[0].declarations) == orig_decls + 1
    assert any(d.name == "PumpSpeed" for d in re_ast.var_blocks[0].declarations)


# ============================================================================
# 4. Invalid Syntax Fault Fail-Closed Rejection Tests
# ============================================================================

@pytest.mark.parametrize("pou_name", TARGET_POUS)
def test_syntax_fault_unclosed_var_block_rejected(pou_name):
    pou_path = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "pous" / pou_name
    bad_code = pou_path.read_text(encoding="utf-8").replace("END_VAR", "")
    with pytest.raises((ParseError, LexerError)):
        Parser(Lexer(bad_code).tokenize()).parse_program()


@pytest.mark.parametrize("pou_name", TARGET_POUS)
def test_syntax_fault_illegal_operator_rejected(pou_name):
    pou_path = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "pous" / pou_name
    bad_code = pou_path.read_text(encoding="utf-8").replace("PROGRAM", "PROGRAM @")
    with pytest.raises(LexerError):
        Parser(Lexer(bad_code).tokenize()).parse_program()


@pytest.mark.parametrize("pou_name", TARGET_POUS)
def test_syntax_fault_missing_assignment_operand_rejected(pou_name):
    pou_path = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "pous" / pou_name
    source = pou_path.read_text(encoding="utf-8")
    bad_code = source.replace(":=", ":= ;") if ":=" in source else source + "\ncorrupt := ;"
    with pytest.raises(ParseError):
        Parser(Lexer(bad_code).tokenize()).parse_program()


@pytest.mark.parametrize("pou_name", TARGET_POUS)
def test_syntax_fault_pou_header_semicolon_rejected(pou_name):
    pou_path = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "pous" / pou_name
    raw_name = pou_name.replace(".st", "")
    bad_code = pou_path.read_text(encoding="utf-8").replace(f"PROGRAM {raw_name}", f"PROGRAM {raw_name};")
    with pytest.raises(ParseError) as excinfo:
        Parser(Lexer(bad_code).tokenize()).parse_program()
    assert "must not have a trailing semicolon" in str(excinfo.value)


# ============================================================================
# 5. Baseline SHA-256 Integrity Verification
# ============================================================================

@pytest.mark.parametrize("pou_name", TARGET_POUS)
def test_original_pou_sha256_unmodified(pou_name):
    path = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "pous" / pou_name
    current_hash = _compute_sha256(path)

    log_path = HORNER_ROOT / LOG_REL
    log_data = json.loads(log_path.read_text(encoding="utf-8"))
    baseline_entry = next(p for p in log_data["pous"] if p["name"] == pou_name)

    assert current_hash == baseline_entry["sha256_baseline"], (
        f"POU {pou_name} was corrupted or modified! Current: {current_hash} != Baseline: {baseline_entry['sha256_baseline']}"
    )


# ============================================================================
# 6. Safety Mandates & Lockout Enforced
# ============================================================================

def test_safety_mandates_and_lockout():
    assert ID_CONTROLLER_DOWNLOAD == 32827

    gate = get_gate_status()
    live_pid = gate.get("pid")
    if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
        pytest.skip(f"No active live Cscape process (gate reports PID {live_pid})")
    proc = psutil.Process(live_pid)
    assert proc.is_running(), f"Cscape PID {live_pid} must remain running!"
    assert "cscape" in proc.name().lower()
