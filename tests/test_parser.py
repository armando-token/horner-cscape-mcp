"""
Unit tests for the IEC 61131-3 Structured Text Lexer and Parser.
"""
import pytest
from src.parser.lexer import Lexer, TokenType, parse_time_literal_ms
from src.parser.parser import Parser, ParseError
from src.parser.ast_nodes import (
    ProgramNode, IfNode, CaseNode, ForNode, WhileNode, RepeatNode,
    AssignmentNode, FBInvocationNode, BinaryOpNode, UnaryOpNode, LiteralNode, VariableNode
)

def test_parse_time_literal():
    assert parse_time_literal_ms("T#500ms") == 500.0
    assert parse_time_literal_ms("t#2s") == 2000.0
    assert parse_time_literal_ms("T#1m") == 60000.0
    assert parse_time_literal_ms("TIME#1h") == 3600000.0
    assert parse_time_literal_ms("T#1d") == 86400000.0
    assert parse_time_literal_ms("T#1m30s500ms") == 90500.0

def test_lexer_tokens():
    code = """
    // Single line comment
    (* Block comment (* nested *) *)
    VAR
        x : INT := 16#FF;
        b : BOOL := TRUE;
        t : TIME := T#2.5s;
    END_VAR
    x := x + 1;
    """
    lexer = Lexer(code)
    tokens = lexer.tokenize()
    types = [t.type for t in tokens if t.type != TokenType.EOF]
    assert TokenType.VAR in types
    assert TokenType.END_VAR in types
    assert TokenType.ASSIGN in types
    assert TokenType.PLUS in types

    # Verify hex value 16#FF
    int_tok = [t for t in tokens if t.type == TokenType.INT_LITERAL][0]
    assert int_tok.value == 255

    # Verify time value T#2.5s
    time_tok = [t for t in tokens if t.type == TokenType.TIME_LITERAL][0]
    assert time_tok.value == 2500.0

def test_parser_pou_structure():
    code = """
    PROGRAM MainControl
    VAR_INPUT
        bStart : BOOL := FALSE;
        bStop : BOOL := FALSE;
    END_VAR
    VAR_OUTPUT
        bRunning : BOOL := FALSE;
    END_VAR
    VAR
        cycleCount : INT := 0;
    END_VAR

    IF bStart AND NOT bStop THEN
        bRunning := TRUE;
    ELSIF bStop THEN
        bRunning := FALSE;
    END_IF;
    END_PROGRAM
    """
    parser = Parser.from_source(code)
    ast = parser.parse()
    assert isinstance(ast, ProgramNode)
    assert ast.name == "MainControl"
    assert ast.pou_type == "PROGRAM"
    assert len(ast.var_blocks) == 3
    assert len(ast.body) == 1
    assert isinstance(ast.body[0], IfNode)

def test_parser_case_statement():
    code = """
    CASE state OF
        0:
            motor := FALSE;
        1..3:
            motor := TRUE;
        4, 5:
            motor := FALSE;
        ELSE
            state := 0;
    END_CASE;
    """
    parser = Parser.from_source(code)
    ast = parser.parse()
    assert len(ast.body) == 1
    case_stmt = ast.body[0]
    assert isinstance(case_stmt, CaseNode)
    assert len(case_stmt.cases) == 3
    assert case_stmt.else_body is not None

def test_parser_loops():
    code = """
    FOR i := 1 TO 10 BY 2 DO
        total := total + i;
    END_FOR;
    WHILE total > 0 DO
        total := total - 1;
        EXIT;
    END_WHILE;
    REPEAT
        total := total + 5;
    UNTIL total >= 50
    END_REPEAT;
    """
    parser = Parser.from_source(code)
    ast = parser.parse()
    assert len(ast.body) == 3
    assert isinstance(ast.body[0], ForNode)
    assert isinstance(ast.body[1], WhileNode)
    assert isinstance(ast.body[2], RepeatNode)

def test_parser_fb_invocation():
    code = """
    timer1(IN := bRun, PT := T#5s);
    counter1(CU := bPulse, RESET := bReset, PV := 10);
    """
    parser = Parser.from_source(code)
    ast = parser.parse()
    assert len(ast.body) == 2
    assert isinstance(ast.body[0], FBInvocationNode)
    assert "IN" in ast.body[0].args
    assert "PT" in ast.body[0].args
    assert isinstance(ast.body[1], FBInvocationNode)
    assert "CU" in ast.body[1].args

def test_parser_syntax_error():
    bad_code = "IF bStart THEN x := 10; (* missing END_IF *)"
    parser = Parser.from_source(bad_code)
    with pytest.raises(ParseError):
        parser.parse()

def test_pou_headers_strictly_reject_trailing_semicolons():
    """Verify IEC 61131-3 strict adherence: POU headers must not end with semicolon."""
    # PROGRAM with bogus trailing semicolon
    bad_prog = "PROGRAM Main;\nx := 1;\nEND_PROGRAM"
    with pytest.raises(ParseError) as exc_info:
        Parser.from_source(bad_prog).parse()
    assert "PROGRAM header 'Main' must not have a trailing semicolon" in str(exc_info.value)

    # FUNCTION_BLOCK with bogus trailing semicolon
    bad_fb = "FUNCTION_BLOCK FB_Test;\nx := 1;\nEND_FUNCTION_BLOCK"
    with pytest.raises(ParseError) as exc_info:
        Parser.from_source(bad_fb).parse()
    assert "FUNCTION_BLOCK header 'FB_Test' must not have a trailing semicolon" in str(exc_info.value)

    # FUNCTION with bogus trailing semicolon
    bad_fn = "FUNCTION Fn_Test : INT;\nFn_Test := 1;\nEND_FUNCTION"
    with pytest.raises(ParseError) as exc_info:
        Parser.from_source(bad_fn).parse()
    assert "FUNCTION header 'Fn_Test' must not have a trailing semicolon" in str(exc_info.value)

def test_ast_node_serialization_to_dict():
    """Verify AST nodes serialize to dictionary structures with full metadata."""
    code = """
    PROGRAM FullAudit
    VAR
        cnt : INT := 10;
        limit : INT := 100;
        flag : BOOL := TRUE;
    END_VAR
    IF flag THEN
        cnt := cnt + 1;
    ELSE
        cnt := 0;
    END_IF;
    END_PROGRAM
    """
    ast = Parser.from_source(code).parse()
    d = ast.to_dict()
    assert d["node_type"] == "ProgramNode"
    assert d["name"] == "FullAudit"
    assert d["pou_type"] == "PROGRAM"
    assert len(d["var_blocks"]) == 1
    assert d["var_blocks"][0]["node_type"] == "VarBlockNode"
    assert len(d["var_blocks"][0]["declarations"]) == 3
    assert d["var_blocks"][0]["declarations"][0]["name"] == "cnt"
    assert len(d["body"]) == 1
    assert d["body"][0]["node_type"] == "IfNode"

def test_ast_node_roundtrip_st():
    """Verify AST node to_st() serialization and re-parsing idempotency roundtrip."""
    source_code = """PROGRAM ControlLoop
    VAR
        i : INT := 0;
        state : INT := 1;
        total : INT := 0;
    END_VAR

    CASE state OF
        1:
            total := 10;
        2..5:
            total := 20;
        ELSE
            total := 0;
    END_CASE;
    FOR i := 1 TO 10 BY 2 DO
        total := total + i;
    END_FOR;
    WHILE total > 0 DO
        total := total - 1;
    END_WHILE;
    REPEAT
        total := total + 5;
    UNTIL total >= 50
    END_REPEAT;
END_PROGRAM"""

    ast1 = Parser.from_source(source_code).parse()
    emitted_st = ast1.to_st()

    # Emitted ST must have no bogus trailing semicolons on headers or closers
    assert "PROGRAM ControlLoop" in emitted_st
    assert "PROGRAM ControlLoop;" not in emitted_st
    assert "END_PROGRAM" in emitted_st
    assert "END_PROGRAM;" not in emitted_st

    ast2 = Parser.from_source(emitted_st).parse()

    d1 = ast1.to_dict()
    d2 = ast2.to_dict()

    assert d1["name"] == d2["name"]
    assert d1["pou_type"] == d2["pou_type"]
    assert len(d1["var_blocks"]) == len(d2["var_blocks"])
    assert len(d1["body"]) == len(d2["body"])

def test_iec61131_import_package():
    """Verify src.iec61131 package re-exports canonical parser."""
    import src.iec61131.parser as iec_parser
    ast = iec_parser.Parser.from_source("PROGRAM P\nx := 1;\nEND_PROGRAM").parse()
    assert ast.name == "P"
    assert ast.pou_type == "PROGRAM"

def test_parser_all_16_elementary_data_types():
    """Verify full parser & AST coverage for all 16 elementary IEC 61131-3 data types."""
    types_tests = [
        ("BOOL", "TRUE", "BOOL"),
        ("BYTE", "16#FF", "INT"),
        ("WORD", "16#FFFF", "INT"),
        ("DWORD", "16#FFFFFFFF", "INT"),
        ("SINT", "-120", "INT"),
        ("INT", "-30000", "INT"),
        ("DINT", "-2000000", "INT"),
        ("LINT", "-9000000000", "INT"),
        ("USINT", "250", "INT"),
        ("UINT", "65000", "INT"),
        ("UDINT", "4000000000", "INT"),
        ("ULINT", "18000000000", "INT"),
        ("REAL", "3.14", "REAL"),
        ("LREAL", "2.71828", "REAL"),
        ("TIME", "T#10s", "TIME"),
        ("STRING", "'AuditString'", "STRING"),
    ]
    st_lines = ["PROGRAM AllTypesAudit", "VAR"]
    for tname, val, _ in types_tests:
        st_lines.append(f"    v_{tname} : {tname} := {val};")
    st_lines.append("END_VAR")
    for tname, val, _ in types_tests:
        st_lines.append(f"    v_{tname} := {val};")
    st_lines.append("END_PROGRAM")
    code = "\n".join(st_lines)

    ast = Parser.from_source(code).parse()
    assert ast.name == "AllTypesAudit"
    assert ast.pou_type == "PROGRAM"
    assert len(ast.var_blocks[0].declarations) == 16
    for decl, (tname, _, _) in zip(ast.var_blocks[0].declarations, types_tests):
        assert decl.name == f"v_{tname}"
        assert decl.data_type == tname
        assert decl.initial_value is not None

    assert len(ast.body) == 16
    for stmt, (tname, val, expected_type) in zip(ast.body, types_tests):
        assert isinstance(stmt, AssignmentNode)
        assert stmt.target.name == f"v_{tname}"
        if val.startswith("-"):
            assert isinstance(stmt.value, UnaryOpNode)
            assert stmt.value.operand.data_type == expected_type
        else:
            assert isinstance(stmt.value, LiteralNode)
            assert stmt.value.data_type == expected_type

def test_parser_function_block_and_function_constructs():
    """Verify structural constructs: FUNCTION_BLOCK and FUNCTION with return types."""
    # FUNCTION_BLOCK test
    fb_code = """
    FUNCTION_BLOCK FB_MotorController
    VAR_INPUT
        RunCmd : BOOL;
        Setpoint : REAL;
    END_VAR
    VAR_OUTPUT
        MotorRunning : BOOL;
        Speed : REAL;
    END_VAR
    IF RunCmd THEN
        MotorRunning := TRUE;
        Speed := Setpoint;
    ELSE
        MotorRunning := FALSE;
        Speed := 0.0;
    END_IF;
    END_FUNCTION_BLOCK
    """
    fb_ast = Parser.from_source(fb_code).parse()
    assert fb_ast.pou_type == "FUNCTION_BLOCK"
    assert fb_ast.name == "FB_MotorController"
    assert fb_ast.return_type is None
    assert len(fb_ast.var_blocks) == 2
    assert fb_ast.var_blocks[0].block_type == "VAR_INPUT"
    assert fb_ast.var_blocks[1].block_type == "VAR_OUTPUT"
    assert len(fb_ast.body) == 1
    assert isinstance(fb_ast.body[0], IfNode)

    # FUNCTION test (with return type)
    func_code = """
    FUNCTION ScaleAnalog : REAL
    VAR_INPUT
        RawInput : INT;
        MinVal : REAL;
        MaxVal : REAL;
    END_VAR
    ScaleAnalog := MinVal + (MaxVal - MinVal) * (INT_TO_REAL(RawInput) / 32767.0);
    END_FUNCTION
    """
    fn_ast = Parser.from_source(func_code).parse()
    assert fn_ast.pou_type == "FUNCTION"
    assert fn_ast.name == "ScaleAnalog"
    assert fn_ast.return_type == "REAL"
    assert len(fn_ast.var_blocks) == 1
    assert len(fn_ast.body) == 1
    assert isinstance(fn_ast.body[0], AssignmentNode)

def test_parser_ast_determinism_multi_run():
    """Verify deterministic AST generation across multiple parse invocations."""
    code = """
    PROGRAM DeterminismCheck
    VAR
        cnt : DINT := 0;
        limit : DINT := 1000;
        flag : BOOL := TRUE;
    END_VAR
    WHILE flag AND (cnt < limit) DO
        cnt := cnt + 1;
        IF cnt >= limit THEN
            flag := FALSE;
        END_IF;
    END_WHILE;
    END_PROGRAM
    """
    baseline_dict = Parser.from_source(code).parse().to_dict()
    for _ in range(10):
        run_dict = Parser.from_source(code).parse().to_dict()
        assert run_dict == baseline_dict

def test_parser_line_column_extraction_precision():
    """Verify precision of line and column coordinate extraction."""
    code = """PROGRAM PrecisionLoc
VAR
    sensor : BOOL := TRUE;
END_VAR
sensor := FALSE;
END_PROGRAM"""

    ast = Parser.from_source(code).parse()
    assert ast.loc.line == 1 and ast.loc.col == 1
    assert ast.var_blocks[0].loc.line == 2 and ast.var_blocks[0].loc.col == 1
    
    decl = ast.var_blocks[0].declarations[0]
    assert decl.loc.line == 3 and decl.loc.col == 5
    assert decl.initial_value.loc.line == 3 and decl.initial_value.loc.col == 22
    
    stmt = ast.body[0]
    assert stmt.loc.line == 5 and stmt.loc.col == 1
    assert stmt.value.loc.line == 5 and stmt.value.loc.col == 11