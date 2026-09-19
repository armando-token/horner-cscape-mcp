"""Comprehensive diagnostics verification test suite for Horner Cscape 10.2 Structured Text.

Deliberately tests all four core classes of IEC 61131-3 ST errors:
1. Missing END_IF (unclosed conditional blocks, nested unclosed IFs, EOF bounds)
2. Mismatched types (incompatible literal assignments, float-to-int, string-to-int, raw-to-time)
3. Undeclared variables (LHS assignments, RHS expression identifiers, undeclared FB invocations)
4. Ladder syntax artifacts (forbidden contacts, coils, rung markers, network headers)

Strictly verifies that CscapeLogParser extracts:
- Exact source line number
- Exact column number
- Error severity level (ERROR, WARNING, INFO)
- Diagnostic message text and error codes
- Associated POU name and source file path
"""

import os
import re
from pathlib import Path
from typing import List, Optional

import pytest

from src.cscape.compiler import (
    BuildStatus,
    CompilerDiagnostic,
    CscapeBuildResult,
    CscapeCompiler,
    CscapeLogParser,
)
from src.cscape.st_ld_interop import LadderConstructRejectedError
from src.iec.st_parser import IssueSeverity, STIssue, STParser
from src.iec.validator import IECValidator
from src.project.manager import CscapeProject
from src.validation.validator import STValidator

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


# ============================================================================
# 1. Missing END_IF Diagnostics Tests
# ============================================================================

class TestMissingEndIfDiagnostics:
    """Verifies deliberate missing END_IF syntax errors and log parsing."""

    def test_single_unclosed_if_log_parsing(self):
        """Verify CscapeLogParser extracts exact line, column, level, and message for missing END_IF."""
        raw_log = "MainControl.st(14,5): error K51001: Syntax error: Missing 'END_IF' for IF statement opened at line 7"
        diags = CscapeLogParser.parse_log(raw_log)

        assert len(diags) == 1
        d = diags[0]
        assert d.line == 14
        assert d.column == 5
        assert d.level == "ERROR"
        assert d.error_code == "K51001"
        assert "Missing 'END_IF'" in d.message
        assert d.file_path == "MainControl.st"
        assert d.pou_name == "MainControl"

    def test_nested_unclosed_if_log_parsing(self):
        """Verify extraction for nested IF blocks where an inner IF is unclosed."""
        raw_log = """
SafetyLogic.st(28,12): error K51002: Syntax error: Expected 'END_IF' for nested block opened at line 20
SafetyLogic.st(45,1): error K51003: Unclosed outer 'IF' block opened at line 15
"""
        diags = CscapeLogParser.parse_log(raw_log)

        assert len(diags) == 2

        assert diags[0].line == 28
        assert diags[0].column == 12
        assert diags[0].level == "ERROR"
        assert diags[0].error_code == "K51002"
        assert "nested block opened at line 20" in diags[0].message
        assert diags[0].pou_name == "SafetyLogic"

        assert diags[1].line == 45
        assert diags[1].column == 1
        assert diags[1].level == "ERROR"
        assert diags[1].error_code == "K51003"
        assert "Unclosed outer 'IF'" in diags[1].message

    def test_unclosed_if_st_parser_and_log_roundtrip(self):
        """Validate unclosed_if fixture via STParser and verify CscapeLogParser extraction."""
        fixture_path = FIXTURES_DIR / "unclosed_if.st"
        assert fixture_path.exists(), f"Fixture missing: {fixture_path}"
        code = fixture_path.read_text(encoding="utf-8")

        # Parse via STParser
        res = STParser.validate(code)
        assert res.is_valid is False
        error_codes = [e.code for e in res.errors]
        assert "ERR_UNCLOSED_IF" in error_codes

        unclosed_issue = [e for e in res.errors if e.code == "ERR_UNCLOSED_IF"][0]
        assert unclosed_issue.severity == IssueSeverity.ERROR
        assert "Unclosed IF block" in unclosed_issue.message

        # Construct Cscape compiler diagnostic line and parse with CscapeLogParser
        simulated_log = f"unclosed_if.st({unclosed_issue.line},{unclosed_issue.column}): error {unclosed_issue.code}: {unclosed_issue.message}"
        diags = CscapeLogParser.parse_log(simulated_log)

        assert len(diags) == 1
        d = diags[0]
        assert d.line == unclosed_issue.line
        assert d.column == unclosed_issue.column
        assert d.level == "ERROR"
        assert d.error_code == "ERR_UNCLOSED_IF"
        assert d.message == unclosed_issue.message
        assert d.pou_name == "unclosed_if"

    def test_unclosed_if_validator_ast_error_extraction(self):
        """Verify IECValidator and AST parser catch missing END_IF with precise line and col."""
        broken_st = """PROGRAM TestUnclosed
VAR
    bCondition : BOOL := TRUE;
    nResult : INT := 0;
END_VAR

IF bCondition THEN
    nResult := 10;
(* Deliberately missing END_IF *)

END_PROGRAM
"""
        val_res = IECValidator.validate(broken_st)
        assert val_res["valid"] is False
        assert len(val_res["errors"]) > 0

        # Verify nesting mismatch or syntax error captured
        has_nesting_or_syntax_err = any(
            "Mismatched" in err or "Unclosed" in err or "Syntax error" in err
            for err in val_res["errors"]
        )
        assert has_nesting_or_syntax_err

        # Format as Cscape log and verify CscapeLogParser extraction
        log_line = "TestUnclosed.st(11,1): error ST_SYNTAX_ERROR: Syntax error at line 11, col 1: Unexpected token in statement: END_PROGRAM"
        diags = CscapeLogParser.parse_log(log_line)
        assert len(diags) == 1
        assert diags[0].line == 11
        assert diags[0].column == 1
        assert diags[0].level == "ERROR"
        assert diags[0].error_code == "ST_SYNTAX_ERROR"
        assert diags[0].pou_name == "TestUnclosed"


# ============================================================================
# 2. Mismatched Types Diagnostics Tests
# ============================================================================

class TestMismatchedTypesDiagnostics:
    """Verifies deliberate data type mismatch errors and log parsing."""

    def test_type_mismatch_log_parsing(self):
        """Verify CscapeLogParser extracts exact line, column, error level, and type mismatch messages."""
        raw_log = """
ProcessControl.st(10,1): error K51004: Type mismatch: Cannot assign numeric literal '123' directly to BOOL variable 'FlagBool'
ProcessControl.st(11,1): error K51005: Type mismatch: Cannot assign STRING literal to integer variable 'CounterInt'
ProcessControl.st(12,1): error K51006: Type mismatch: Cannot assign REAL floating-point literal '3.14159' to integer 'CounterInt' (INT) without explicit conversion
ProcessControl.st(13,1): error K51007: Type mismatch: Literal '500' assigned to TIME variable 'TimerVal' must use 'T#' or 'TIME#' prefix (e.g. T#5s)
"""
        diags = CscapeLogParser.parse_log(raw_log)
        assert len(diags) == 4

        expected = [
            (10, 1, "K51004", "numeric literal '123' directly to BOOL"),
            (11, 1, "K51005", "STRING literal to integer variable"),
            (12, 1, "K51006", "REAL floating-point literal '3.14159' to integer"),
            (13, 1, "K51007", "assigned to TIME variable 'TimerVal' must use 'T#'"),
        ]

        for i, (exp_line, exp_col, exp_code, exp_substr) in enumerate(expected):
            d = diags[i]
            assert d.line == exp_line, f"Mismatch at index {i} line: expected {exp_line}, got {d.line}"
            assert d.column == exp_col, f"Mismatch at index {i} column: expected {exp_col}, got {d.column}"
            assert d.level == "ERROR"
            assert d.error_code == exp_code
            assert exp_substr in d.message
            assert d.pou_name == "ProcessControl"
            assert d.file_path == "ProcessControl.st"

    def test_mismatched_types_fixture_validation_and_log_extraction(self):
        """Validate fixtures/mismatched_types.st with STParser and parse via CscapeLogParser."""
        fix_path = FIXTURES_DIR / "mismatched_types.st"
        assert fix_path.exists(), f"Fixture missing: {fix_path}"
        code = fix_path.read_text(encoding="utf-8")

        res = STParser.validate(code)
        assert res.is_valid is False
        type_errors = [e for e in res.errors if e.code == "ERR_TYPE_MISMATCH"]
        assert len(type_errors) >= 4

        # Verify each type mismatch error has ERROR severity and valid message
        for err in type_errors:
            assert err.severity == IssueSeverity.ERROR
            assert "Type mismatch" in err.message
            assert err.column >= 1

        # Format simulated compiler log from extracted issues
        log_lines = [
            f"mismatched_types.st({err.line},{err.column}): error {err.code}: {err.message}"
            for err in type_errors
        ]
        simulated_log = "\n".join(log_lines)
        diags = CscapeLogParser.parse_log(simulated_log)

        assert len(diags) == len(type_errors)
        for i, d in enumerate(diags):
            assert d.line == type_errors[i].line
            assert d.column == type_errors[i].column
            assert d.level == "ERROR"
            assert d.error_code == "ERR_TYPE_MISMATCH"
            assert d.message == type_errors[i].message
            assert d.pou_name == "mismatched_types"

    @pytest.mark.parametrize(
        "line_no,col_no,expr,target_type,expected_msg",
        [
            (15, 4, "TRUE", "INT", "Cannot assign BOOL literal 'TRUE' to integer"),
            (16, 4, "FALSE", "REAL", "Cannot assign BOOL literal 'FALSE' to floating-point"),
            (17, 4, "'TextValue'", "REAL", "Cannot assign STRING literal to REAL variable"),
            (18, 4, "1234", "STRING", "Cannot assign non-string literal '1234' to STRING variable"),
        ],
    )
    def test_parametrized_type_mismatch_log_extraction(
        self, line_no: int, col_no: int, expr: str, target_type: str, expected_msg: str
    ):
        """Verify type mismatch errors on varied types extract exact position and level."""
        log = f"TypeCheckPOU.st({line_no},{col_no}): error ERR_TYPE_MISMATCH: Type mismatch: {expected_msg} 'TargetVar' ({target_type})"
        diags = CscapeLogParser.parse_log(log)

        assert len(diags) == 1
        d = diags[0]
        assert d.line == line_no
        assert d.column == col_no
        assert d.level == "ERROR"
        assert d.error_code == "ERR_TYPE_MISMATCH"
        assert expected_msg in d.message
        assert d.pou_name == "TypeCheckPOU"


# ============================================================================
# 3. Undeclared Variables Diagnostics Tests
# ============================================================================

class TestUndeclaredVariablesDiagnostics:
    """Verifies deliberate undeclared variable errors and log parsing."""

    def test_undeclared_variables_log_parsing(self):
        """Verify CscapeLogParser extracts exact line, column, level, and identifier names for undeclared variables."""
        raw_log = """
PumpControl.st(7,1): error K51008: Assignment to undeclared variable 'UndeclaredFlag'
PumpControl.st(8,25): error K51009: Undeclared variable or identifier 'PhantomMultiplier' used in logic
PumpControl.st(15,8): error K51010: Undeclared variable or identifier 'bMissingSensor' used in logic
"""
        diags = CscapeLogParser.parse_log(raw_log)
        assert len(diags) == 3

        assert diags[0].line == 7
        assert diags[0].column == 1
        assert diags[0].level == "ERROR"
        assert diags[0].error_code == "K51008"
        assert "Assignment to undeclared variable 'UndeclaredFlag'" in diags[0].message
        assert diags[0].pou_name == "PumpControl"

        assert diags[1].line == 8
        assert diags[1].column == 25
        assert diags[1].level == "ERROR"
        assert diags[1].error_code == "K51009"
        assert "PhantomMultiplier" in diags[1].message

        assert diags[2].line == 15
        assert diags[2].column == 8
        assert diags[2].level == "ERROR"
        assert diags[2].error_code == "K51010"
        assert "bMissingSensor" in diags[2].message

    def test_undeclared_variable_fixture_validation_and_log_roundtrip(self):
        """Validate fixtures/undeclared_variable.st and verify CscapeLogParser extraction."""
        fix_path = FIXTURES_DIR / "undeclared_variable.st"
        assert fix_path.exists(), f"Fixture missing: {fix_path}"
        code = fix_path.read_text(encoding="utf-8")

        res = STParser.validate(code)
        assert res.is_valid is False
        undec_errors = [e for e in res.errors if e.code == "ERR_UNDECLARED_VAR"]
        assert len(undec_errors) >= 2

        # Verify undeclared variable error attributes
        messages = [e.message for e in undec_errors]
        assert any("UndeclaredFlag" in m for m in messages)
        assert any("PhantomMultiplier" in m for m in messages)

        # Build raw log string and parse with CscapeLogParser
        log_entries = [
            f"undeclared_variable.st({e.line},{e.column}): error {e.code}: {e.message}"
            for e in undec_errors
        ]
        parsed_diags = CscapeLogParser.parse_log("\n".join(log_entries))

        assert len(parsed_diags) == len(undec_errors)
        for i, pd in enumerate(parsed_diags):
            assert pd.line == undec_errors[i].line
            assert pd.column == undec_errors[i].column
            assert pd.level == "ERROR"
            assert pd.error_code == "ERR_UNDECLARED_VAR"
            assert pd.message == undec_errors[i].message
            assert pd.pou_name == "undeclared_variable"

    def test_undeclared_variable_warning_level_parsing(self):
        """Verify CscapeLogParser handles WARNING level diagnostics for undeclared variable warnings."""
        raw_log = "LogicModule.st(42,5): warning W3001: Variable 'UninitializedVar' referenced without prior initialization"
        diags = CscapeLogParser.parse_log(raw_log)

        assert len(diags) == 1
        d = diags[0]
        assert d.line == 42
        assert d.column == 5
        assert d.level == "WARNING"
        assert d.error_code == "W3001"
        assert "UninitializedVar" in d.message
        assert d.pou_name == "LogicModule"


# ============================================================================
# 4. Ladder Syntax Artifacts Diagnostics Tests
# ============================================================================

class TestLadderSyntaxArtifactsDiagnostics:
    """Verifies rejection of forbidden ladder logic constructs and log parsing."""

    def test_ladder_contacts_and_coils_log_parsing(self):
        """Verify CscapeLogParser extracts exact line, column, error level, and ladder rejection messages."""
        raw_log = """
LegacyLogic.st(8,1): error ERR_LADDER_FORBIDDEN: Forbidden ladder logic construct 'Rung header' detected: 'RUNG 1:'. Strict constraint violated: ONLY pure IEC 61131-3 Structured Text is permitted.
LegacyLogic.st(9,1): error ERR_LADDER_FORBIDDEN: Forbidden ladder logic construct 'Normally open contact' detected: '---[ ]--- InputContact'. Strict constraint violated: ONLY pure IEC 61131-3 Structured Text is permitted.
LegacyLogic.st(9,28): error ERR_LADDER_FORBIDDEN: Forbidden ladder logic construct 'Relay coil' detected: '--- ( ) --- CoilOutput'. Strict constraint violated: ONLY pure IEC 61131-3 Structured Text is permitted.
LegacyLogic.st(10,1): error ERR_LADDER_FORBIDDEN: Forbidden ladder logic construct 'Rung terminator' detected: 'END_RUNG'. Strict constraint violated: ONLY pure IEC 61131-3 Structured Text is permitted.
"""
        diags = CscapeLogParser.parse_log(raw_log)
        assert len(diags) == 4

        expected = [
            (8, 1, "Rung header"),
            (9, 1, "Normally open contact"),
            (9, 28, "Relay coil"),
            (10, 1, "Rung terminator"),
        ]

        for i, (exp_line, exp_col, exp_construct) in enumerate(expected):
            d = diags[i]
            assert d.line == exp_line
            assert d.column == exp_col
            assert d.level == "ERROR"
            assert d.error_code == "ERR_LADDER_FORBIDDEN"
            assert exp_construct in d.message
            assert "ONLY pure IEC 61131-3 Structured Text is permitted" in d.message
            assert d.pou_name == "LegacyLogic"

    def test_ladder_fixture_validation_and_log_roundtrip(self):
        """Validate fixtures/advanced_ladder_forbidden.st and verify CscapeLogParser extraction."""
        fix_path = FIXTURES_DIR / "advanced_ladder_forbidden.st"
        assert fix_path.exists(), f"Fixture missing: {fix_path}"
        code = fix_path.read_text(encoding="utf-8")

        res = STParser.validate(code)
        assert res.is_valid is False
        ladder_errors = [e for e in res.errors if e.code == "ERR_LADDER_FORBIDDEN"]
        assert len(ladder_errors) >= 3

        # Verify line positions from fixture
        lines = [e.line for e in ladder_errors]
        assert 8 in lines  # RUNG 1:
        assert 9 in lines  # ---[ ]--- ... --- ( ) ---
        assert 10 in lines  # END_RUNG

        # Build raw log and parse via CscapeLogParser
        simulated_log = "\n".join(
            f"advanced_ladder_forbidden.st({e.line},{e.column}): error {e.code}: {e.message}"
            for e in ladder_errors
        )
        diags = CscapeLogParser.parse_log(simulated_log)

        assert len(diags) == len(ladder_errors)
        for i, d in enumerate(diags):
            assert d.line == ladder_errors[i].line
            assert d.column == ladder_errors[i].column
            assert d.level == "ERROR"
            assert d.error_code == "ERR_LADDER_FORBIDDEN"
            assert "ladder logic" in d.message.lower()
            assert d.pou_name == "advanced_ladder_forbidden"

    @pytest.mark.parametrize(
        "pattern_name,ladder_str,line_no,col_no",
        [
            ("Normally closed contact", "---[ / ]--- FaultContact", 12, 1),
            ("Set/Reset coil", "---( S )--- AlarmActive", 14, 20),
            ("Ladder network", "NETWORK 5", 3, 1),
            ("Ladder contact", "CONTACT X10", 7, 5),
            ("Ladder coil", "COIL Y20", 8, 5),
        ],
    )
    def test_additional_ladder_syntax_patterns_extraction(
        self, pattern_name: str, ladder_str: str, line_no: int, col_no: int
    ):
        """Verify extraction for various ladder constructs matching AGENTS.md requirements."""
        log = f"MixedPOU.st({line_no},{col_no}): error ERR_LADDER_FORBIDDEN: Forbidden ladder construct '{pattern_name}' detected: '{ladder_str}'"
        diags = CscapeLogParser.parse_log(log)

        assert len(diags) == 1
        d = diags[0]
        assert d.line == line_no
        assert d.column == col_no
        assert d.level == "ERROR"
        assert d.error_code == "ERR_LADDER_FORBIDDEN"
        assert pattern_name in d.message
        assert ladder_str in d.message
        assert d.pou_name == "MixedPOU"


# ============================================================================
# 5. End-to-End Compiler Diagnostics Integration Tests
# ============================================================================

class TestEndToEndCompilerDiagnosticsIntegration:
    """Verifies end-to-end compilation pass with intentional diagnostics and CscapeLogParser."""

    def test_compile_project_with_deliberate_errors(self, tmp_path):
        """Create project with deliberate ST errors, compile, and parse build.log with CscapeLogParser."""
        project_dir = tmp_path / "DiagnosticsProject"
        proj = CscapeProject.create(project_dir, name="DiagnosticsProject")

        # POU 1: Unclosed IF
        proj.inject_pou(
            "POU_UnclosedIf",
            """PROGRAM POU_UnclosedIf
VAR
    bStart : BOOL := TRUE;
    nSpeed : INT := 100;
END_VAR

IF bStart THEN
    nSpeed := 200;
(* Deliberately missing END_IF *)
END_PROGRAM
""",
            "PROGRAM",
        )

        # POU 2: Ladder syntax artifact - inject_pou must fail closed with LadderConstructRejectedError
        ladder_code = """PROGRAM POU_LadderArtifact
VAR
    x : BOOL := FALSE;
END_VAR

RUNG 1:
---[ ]--- x
END_RUNG
END_PROGRAM
"""
        with pytest.raises(LadderConstructRejectedError):
            proj.inject_pou("POU_LadderArtifact", ladder_code, "PROGRAM")

        # Directly place the file on disk to verify compiler pipeline and build.log diagnostics extraction
        (proj.pous_dir / "POU_LadderArtifact.st").write_text(ladder_code, encoding="utf-8")

        compiler = CscapeCompiler(workspace_root=tmp_path)
        build_result = compiler.compile_project(project_dir)

        # Compilation MUST fail closed
        assert build_result.success is False
        assert build_result.status == BuildStatus.FAILED
        assert build_result.error_count > 0
        assert len(build_result.diagnostics) > 0

        # Verify build.log artifact was generated on disk
        build_log_path = project_dir / "artifacts" / "build.log"
        assert build_log_path.exists()
        log_content = build_log_path.read_text(encoding="utf-8")

        # Parse generated build.log using CscapeLogParser
        parsed_diags = CscapeLogParser.parse_log(log_content)
        assert len(parsed_diags) > 0

        # Verify all parsed diagnostics contain exact line, level, message, and file info
        for diag in parsed_diags:
            assert diag.line is not None
            assert diag.line > 0
            assert diag.level in ("ERROR", "WARNING")
            assert len(diag.message) > 0
            assert diag.pou_name in ("POU_UnclosedIf", "POU_LadderArtifact")
            assert diag.file_path is not None

        # Specifically verify unclosed IF was identified
        unclosed_diags = [d for d in parsed_diags if d.pou_name == "POU_UnclosedIf"]
        assert len(unclosed_diags) > 0
        assert any("Unclosed" in d.message or "Mismatched" in d.message or "Syntax error" in d.message for d in unclosed_diags)

        # Specifically verify ladder artifact was identified
        ladder_diags = [d for d in parsed_diags if d.pou_name == "POU_LadderArtifact"]
        assert len(ladder_diags) > 0
        assert any("ladder" in d.message.lower() for d in ladder_diags)

    def test_compile_project_all_four_error_categories_simultaneous(self, tmp_path):
        """Verify CscapeCompiler and CscapeLogParser across all 4 intentional error categories simultaneously."""
        project_dir = tmp_path / "MultiErrorProject"
        proj = CscapeProject.create(project_dir, name="MultiErrorProject")

        # Single composite POU containing all 4 deliberate error classes
        composite_broken_code = """PROGRAM CompositeErrorPOU
VAR
    bActive : BOOL := FALSE;
    nCounter : INT := 0;
    tDelay : TIME := T#1s;
END_VAR

// 1. Ladder artifact
RUNG 1:
---[ ]--- bActive

// 2. Missing END_IF
IF bActive THEN
    nCounter := nCounter + 1;

// 3. Undeclared variable assignment
UndeclaredFlag := TRUE;

// 4. Mismatched type
nCounter := 'IllegalString';

END_PROGRAM
"""
        # Writing directly to pous_dir simulates compiling a workspace with existing broken files
        (proj.pous_dir / "CompositeErrorPOU.st").write_text(composite_broken_code, encoding="utf-8")

        compiler = CscapeCompiler(workspace_root=tmp_path)
        build_result = compiler.compile_project(project_dir)

        assert build_result.success is False
        assert build_result.status == BuildStatus.FAILED
        assert build_result.error_count >= 2

        # Verify raw log parsing
        parsed = CscapeLogParser.parse_log(build_result.raw_log)
        assert len(parsed) >= 2

        # Check line numbers and error level on all diagnostics
        for d in parsed:
            assert d.level == "ERROR"
            assert d.line is not None and d.line > 0
            assert d.pou_name == "CompositeErrorPOU"
            assert len(d.message) > 0


# ============================================================================
# 6. CscapeLogParser Comprehensive Line, Column, and Level Edge Cases
# ============================================================================

class TestCscapeLogParserEdgeCases:
    """Verifies CscapeLogParser under edge cases, formatting variations, and boundary conditions."""

    def test_line_and_column_variations(self):
        """Verify extraction with multi-digit line and column numbers."""
        log = """
DeepModule.st(128,45): error K51099: Syntax error at column 45
WideModule.st(1024,80): warning K52001: Line length exceeds 80 characters
"""
        diags = CscapeLogParser.parse_log(log)
        assert len(diags) == 2

        assert diags[0].line == 128
        assert diags[0].column == 45
        assert diags[0].level == "ERROR"
        assert diags[0].error_code == "K51099"
        assert diags[0].pou_name == "DeepModule"

        assert diags[1].line == 1024
        assert diags[1].column == 80
        assert diags[1].level == "WARNING"
        assert diags[1].error_code == "K52001"
        assert diags[1].pou_name == "WideModule"

    def test_line_present_column_omitted(self):
        """Verify extraction when column is omitted: file(line): level: message."""
        log = "SimpleModule.st(42): error K51012: Division by zero"
        diags = CscapeLogParser.parse_log(log)

        assert len(diags) == 1
        d = diags[0]
        assert d.line == 42
        assert d.column is None
        assert d.level == "ERROR"
        assert d.error_code == "K51012"
        assert d.message == "Division by zero"
        assert d.pou_name == "SimpleModule"

    def test_line_and_column_omitted(self):
        """Verify extraction when both line and column are omitted."""
        log = "GlobalConfig.st: error: General compilation abort"
        diags = CscapeLogParser.parse_log(log)

        assert len(diags) == 1
        d = diags[0]
        assert d.line is None
        assert d.column is None
        assert d.level == "ERROR"
        assert d.error_code is None
        assert d.message == "General compilation abort"
        assert d.pou_name == "GlobalConfig"

    def test_windows_full_absolute_path_parsing(self):
        """Verify extraction with Windows full drive path including spaces and backslashes."""
        log = r"C:\HornerAI\horner-cscape-mcp\pous\MotorDrive.st(25,10): error K51050: Undeclared variable 'SpeedRPM'"
        diags = CscapeLogParser.parse_log(log)

        assert len(diags) == 1
        d = diags[0]
        assert d.line == 25
        assert d.column == 10
        assert d.level == "ERROR"
        assert d.error_code == "K51050"
        assert d.file_path == r"C:\HornerAI\horner-cscape-mcp\pous\MotorDrive.st"
        assert d.pou_name == "MotorDrive"
        assert "SpeedRPM" in d.message

    def test_generic_fallback_error_format(self):
        """Verify extraction with generic bracketed code format."""
        log = """
ERROR [ST001]: Line 15: Missing semicolon at end of statement
WARNING [ST002]: Line 22: Variable declared but never assigned
INFO [ST003]: Code generation completed successfully
"""
        diags = CscapeLogParser.parse_log(log, default_pou="FallbackPOU")
        assert len(diags) == 3

        assert diags[0].level == "ERROR"
        assert diags[0].line == 15
        assert diags[0].error_code == "ST001"
        assert "Missing semicolon" in diags[0].message
        assert diags[0].pou_name == "FallbackPOU"

        assert diags[1].level == "WARNING"
        assert diags[1].line == 22
        assert diags[1].error_code == "ST002"
        assert "declared but never assigned" in diags[1].message

        assert diags[2].level == "INFO"
        assert diags[2].line is None
        assert diags[2].error_code == "ST003"
        assert "Code generation completed" in diags[2].message

    def test_header_and_separator_filtering(self):
        """Verify that Cscape banner, summary lines, and dividers are cleanly skipped."""
        noisy_log = """
=== Horner Cscape 10.2 Compile Pass: TestProj ===
Clean Build: True
Mode: IEC 61131-3 Structured Text (Advanced Ladder Excluded)
Timestamp: 2026-09-04T00:00:00.000000
----------------------------------------------------------------
Compiling POU: MainControl (256 bytes)...
  MainControl.st(10,5): error K51001: Syntax error near 'END_IF'
Compiling POU: MotorFB (512 bytes)...
  MotorFB.st(3,1): warning: Unused variable 'bAux'
----------------------------------------------------------------
Build Result: FAILED
Errors: 1, Warnings: 1
Duration: 0.125s
Hardware Lockout: ENFORCED (Zero PLC communication / No download)
"""
        diags = CscapeLogParser.parse_log(noisy_log)
        assert len(diags) == 2

        assert diags[0].level == "ERROR"
        assert diags[0].line == 10
        assert diags[0].column == 5
        assert diags[0].file_path == "MainControl.st"
        assert diags[0].pou_name == "MainControl"
        assert "Syntax error" in diags[0].message

        assert diags[1].level == "WARNING"
        assert diags[1].line == 3
        assert diags[1].column == 1
        assert diags[1].file_path == "MotorFB.st"
        assert diags[1].pou_name == "MotorFB"
        assert "Unused variable" in diags[1].message

    def test_empty_and_whitespace_logs(self):
        """Verify parser gracefully handles empty or whitespace-only log text."""
        assert CscapeLogParser.parse_log("") == []
        assert CscapeLogParser.parse_log("   \n\n\t  \n  ") == []
        assert CscapeLogParser.parse_log("----------------------------") == []
        assert CscapeLogParser.parse_log("=== Section Header ===") == []

    def test_to_dict_serialization(self):
        """Verify CompilerDiagnostic serialization contains all required fields."""
        diag = CompilerDiagnostic(
            level="ERROR",
            message="Test error message",
            line=42,
            column=10,
            file_path="Test.st",
            pou_name="Test",
            error_code="E999",
        )
        d = diag.to_dict()
        assert d["level"] == "ERROR"
        assert d["message"] == "Test error message"
        assert d["line"] == 42
        assert d["column"] == 10
        assert d["file_path"] == "Test.st"
        assert d["pou_name"] == "Test"
        assert d["error_code"] == "E999"
