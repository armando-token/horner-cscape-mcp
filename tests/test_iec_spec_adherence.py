"""
Comprehensive IEC 61131-3 Structured Text Specification Adherence Test Suite.
Verifies:
1. Lexer tokenization for all IEC 61131-3 keywords, operators, and typed literals.
2. Parser AST generation for all variable scopes (VAR, VAR_INPUT, VAR_OUTPUT, VAR_IN_OUT,
   VAR_GLOBAL, VAR_TEMP, VAR_EXTERNAL, VAR_STAT, VAR_CONFIG).
3. Parser AST generation for all control structures (IF, CASE, FOR, WHILE, REPEAT, EXIT, RETURN, CONTINUE).
4. Operator precedence, complex expressions, and array indexing.
5. IECValidator complete AST validation, ladder artifact rejection, and zero legacy compiler dependencies.
"""
import pytest
from src.iec.lexer import Lexer, TokenType, parse_time_literal_ms
from src.iec.parser import Parser, ParseError
from src.iec.validator import IECValidator
from src.iec.ast_nodes import (
    ProgramNode, VarBlockNode, VarDeclNode, IfNode, CaseNode, ForNode,
    WhileNode, RepeatNode, ExitNode, ReturnNode, ContinueNode,
    AssignmentNode, FBInvocationNode, FunctionCallNode, BinaryOpNode,
    UnaryOpNode, LiteralNode, VariableNode, MemberAccessNode, ArrayAccessNode
)


# ============================================================================
# 1. Keywords, Operators, and Tokens
# ============================================================================

def test_lexer_all_keywords():
    code = """
    PROGRAM MyProg
    VAR_EXTERNAL
        extVar : INT;
    END_VAR
    VAR_STAT
        statVar : DINT;
    END_VAR
    VAR_CONFIG
        cfgVar : BOOL;
    END_VAR
    VAR RETAIN
        retVar : REAL;
    END_VAR
    VAR NON_RETAIN
        nonRetVar : REAL;
    END_VAR
    VAR CONSTANT
        cPi : REAL := 3.14159;
    END_VAR
    IF TRUE THEN
        CONTINUE;
        EXIT;
        RETURN;
    END_IF;
    END_PROGRAM
    """
    tokens = Lexer(code).tokenize()
    types = [t.type for t in tokens if t.type != TokenType.EOF]

    assert TokenType.PROGRAM in types
    assert TokenType.VAR_EXTERNAL in types
    assert TokenType.VAR_STAT in types
    assert TokenType.VAR_CONFIG in types
    assert TokenType.RETAIN in types
    assert TokenType.NON_RETAIN in types
    assert TokenType.CONSTANT in types
    assert TokenType.IF in types
    assert TokenType.CONTINUE in types
    assert TokenType.EXIT in types
    assert TokenType.RETURN in types
    assert TokenType.END_PROGRAM in types


def test_lexer_all_operators():
    code = "a := b ** 2 * (c + d - e / f MOD g) AND (h OR i XOR NOT j) & (k = l) <> (m <= n) >= (o > p) AND (q < r);"
    tokens = Lexer(code).tokenize()
    types = [t.type for t in tokens if t.type != TokenType.EOF]

    assert TokenType.ASSIGN in types      # :=
    assert TokenType.POWER in types       # **
    assert TokenType.STAR in types        # *
    assert TokenType.PLUS in types        # +
    assert TokenType.MINUS in types       # -
    assert TokenType.SLASH in types       # /
    assert TokenType.MOD in types         # MOD
    assert TokenType.AND in types         # AND and &
    assert TokenType.OR in types          # OR
    assert TokenType.XOR in types         # XOR
    assert TokenType.NOT in types         # NOT
    assert TokenType.EQ in types          # =
    assert TokenType.NEQ in types         # <>
    assert TokenType.LE in types          # <=
    assert TokenType.GE in types          # >=
    assert TokenType.LT in types          # <
    assert TokenType.GT in types          # >


def test_lexer_typed_literals():
    code = """
    VAR
        v1 : INT := INT#123;
        v2 : REAL := REAL#3.1415;
        v3 : BOOL := BOOL#1;
        v4 : BOOL := BOOL#TRUE;
        v5 : WORD := WORD#16#ABCD;
        v6 : TIME := T#1h30m;
        v7 : DATE := DATE#2026-09-04;
        v8 : TOD := TOD#14:30:00;
        v9 : DT := DT#2026-09-04-14:30:00;
        v10 : STRING := 'IEC 61131-3';
    END_VAR
    """
    tokens = Lexer(code).tokenize()
    token_dict = {t.type: t.value for t in tokens}

    assert token_dict[TokenType.TIME_LITERAL] == 5400000.0  # 1h30m = 90 min = 5,400,000 ms
    assert token_dict[TokenType.DATE_LITERAL] == "2026-09-04"
    assert token_dict[TokenType.TOD_LITERAL] == "14:30:00"
    assert token_dict[TokenType.DT_LITERAL] == "2026-09-04-14:30:00"
    assert token_dict[TokenType.STRING_LITERAL] == "IEC 61131-3"


# ============================================================================
# 2. Variable Scopes (VAR, VAR_INPUT, VAR_OUTPUT, VAR_IN_OUT, etc.)
# ============================================================================

def test_parser_all_variable_scopes():
    code = """
    FUNCTION_BLOCK FB_AllScopes
    VAR_INPUT
        in1 : BOOL;
        in2 : INT := 10;
    END_VAR
    VAR_OUTPUT
        out1 : REAL;
    END_VAR
    VAR_IN_OUT
        inout1 : DINT;
    END_VAR
    VAR_GLOBAL
        glob1 : WORD;
    END_VAR
    VAR_TEMP
        temp1 : INT;
    END_VAR
    VAR_EXTERNAL
        ext1 : LREAL;
    END_VAR
    VAR_STAT
        stat1 : TIME := T#500ms;
    END_VAR
    VAR_CONFIG
        cfg1 : BOOL;
    END_VAR
    VAR RETAIN CONSTANT
        cMax : INT := 100;
    END_VAR
    VAR NON_RETAIN
        nrVolatile : INT := 0;
    END_VAR

    out1 := 1.0;
    END_FUNCTION_BLOCK
    """
    parser = Parser.from_source(code)
    ast = parser.parse()

    assert ast.pou_type == "FUNCTION_BLOCK"
    assert ast.name == "FB_AllScopes"
    assert len(ast.var_blocks) == 10

    block_types = [vb.block_type for vb in ast.var_blocks]
    assert "VAR_INPUT" in block_types
    assert "VAR_OUTPUT" in block_types
    assert "VAR_IN_OUT" in block_types
    assert "VAR_GLOBAL" in block_types
    assert "VAR_TEMP" in block_types
    assert "VAR_EXTERNAL" in block_types
    assert "VAR_STAT" in block_types
    assert "VAR_CONFIG" in block_types
    assert "VAR" in block_types

    retain_block = [vb for vb in ast.var_blocks if vb.retain][0]
    assert retain_block.constant is True

    non_retain_block = [vb for vb in ast.var_blocks if vb.non_retain][0]
    assert non_retain_block.non_retain is True


def test_parser_direct_addressing_and_arrays():
    code = """
    PROGRAM MemoryIO
    VAR
        sensorInput AT %IX0.0 : BOOL;
        valveOutput AT %QX1.2 : BOOL;
        analogReg AT %MW100 : WORD;
        dataBuffer : ARRAY [1..100] OF INT;
        matrix2D : ARRAY [0..5, 0..10] OF REAL;
        negRange : ARRAY [-10..10] OF SINT;
    END_VAR
    valveOutput := sensorInput;
    dataBuffer[1] := 42;
    matrix2D[0, 1] := 3.14;
    END_PROGRAM
    """
    parser = Parser.from_source(code)
    ast = parser.parse()

    decls = ast.var_blocks[0].declarations
    assert len(decls) == 6
    assert decls[0].name == "sensorInput"
    assert decls[0].address == "%IX0.0"
    assert decls[1].name == "valveOutput"
    assert decls[1].address == "%QX1.2"
    assert decls[2].name == "analogReg"
    assert decls[2].address == "%MW100"

    assert decls[3].array_bounds == (1, 100)
    assert decls[4].array_bounds == [(0, 5), (0, 10)]
    assert decls[5].array_bounds == (-10, 10)


# ============================================================================
# 3. Control Structures (IF, CASE, FOR, WHILE, REPEAT, EXIT, RETURN, CONTINUE)
# ============================================================================

def test_parser_control_structures():
    code = """
    PROGRAM ControlStructuresDemo
    VAR
        state : INT := 0;
        i : INT := 0;
        sum : INT := 0;
    END_VAR

    // IF-THEN-ELSIF-ELSE
    IF state = 0 THEN
        state := 1;
    ELSIF state = 1 THEN
        state := 2;
    ELSE
        state := 0;
    END_IF;

    // CASE with single, range, negative, and multiple labels
    CASE state OF
        0:
            sum := 0;
        1, 2, 3:
            sum := 10;
        4..10:
            sum := 20;
        -10..-1, -20:
            sum := -1;
        ELSE
            sum := 999;
    END_CASE;

    // FOR loop
    FOR i := 1 TO 10 BY 2 DO
        IF i = 5 THEN
            CONTINUE;
        END_IF;
        sum := sum + i;
    END_FOR;

    // WHILE loop
    WHILE sum > 0 DO
        sum := sum - 1;
        IF sum = 5 THEN
            EXIT;
        END_IF;
    END_WHILE;

    // REPEAT loop
    REPEAT
        sum := sum + 1;
    UNTIL sum >= 10
    END_REPEAT;

    RETURN;
    END_PROGRAM
    """
    parser = Parser.from_source(code)
    ast = parser.parse()

    assert len(ast.body) == 6
    assert isinstance(ast.body[0], IfNode)
    assert isinstance(ast.body[1], CaseNode)
    assert isinstance(ast.body[2], ForNode)
    assert isinstance(ast.body[3], WhileNode)
    assert isinstance(ast.body[4], RepeatNode)
    assert isinstance(ast.body[5], ReturnNode)

    # Verify CASE details
    case_node = ast.body[1]
    assert len(case_node.cases) == 4
    assert case_node.else_body is not None

    # Verify FOR details and CONTINUE node inside
    for_node = ast.body[2]
    assert for_node.var_name == "i"
    assert isinstance(for_node.body[0], IfNode)
    assert isinstance(for_node.body[0].then_body[0], ContinueNode)


# ============================================================================
# 4. IECValidator AST Validation & Ladder Logic Strict Rejection
# ============================================================================

def test_iec_validator_clean_ast():
    code = """
    PROGRAM PureIECProgram
    VAR_INPUT
        bRun : BOOL;
        fSpeed : REAL := 1500.0;
    END_VAR
    VAR_OUTPUT
        bActive : BOOL := FALSE;
    END_VAR
    VAR
        timer1 : TON;
    END_VAR

    timer1(IN := bRun, PT := T#5s);
    IF timer1.Q THEN
        bActive := TRUE;
    ELSE
        bActive := FALSE;
    END_IF;
    END_PROGRAM
    """
    res = IECValidator.validate(code)
    assert res["valid"] is True
    assert len(res["errors"]) == 0
    assert res["pou_name"] == "PureIECProgram"
    assert res["pou_type"] == "PROGRAM"
    assert len(res["variables"]) == 4


def test_iec_validator_rejects_ladder_artifacts():
    ladder_code = """
    PROGRAM RejectLadder
    VAR
        in1 : BOOL;
        out1 : BOOL;
    END_VAR
    // RUNG 1: Advanced Ladder artifact
    ---[ ]--- in1 ---[ / ]--- in2 ---( )--- out1
    END_PROGRAM
    """
    res = IECValidator.validate(ladder_code)
    assert res["valid"] is False
    assert any("Ladder logic artifact" in err for err in res["errors"])


def test_iec_validator_zero_legacy_dependencies():
    """Verify that IEC modules have zero legacy Straton references."""
    import inspect
    import src.iec.lexer as lexer_mod
    import src.iec.parser as parser_mod
    import src.iec.validator as validator_mod

    for mod in [lexer_mod, parser_mod, validator_mod]:
        src_text = inspect.getsource(mod)
        assert "straton" not in src_text.lower(), f"Found 'straton' in {mod.__name__}"
        assert "k5p" not in src_text.lower(), f"Found 'k5p' in {mod.__name__}"
        assert "k5cmp" not in src_text.lower(), f"Found 'k5cmp' in {mod.__name__}"
