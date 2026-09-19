"""Tests for Cscape Compiler Diagnostics and Error Pattern Parsing Engine.

Verifies:
1. Regex pattern parsing for Cscape and Straton K5 build outputs:
   - PATTERN_LINE_COL_FIRST: Line 8 Col 21: error: ...
   - PATTERN_GENERIC_LINE: ERROR [ST001]: Line 15: ...
   - PATTERN_CSCAPE_LOCATION: file(line,col): level [code]: msg
2. Conversion of raw build logs into structured CompilerDiagnostic instances with failure_location.
3. Clean build proof verification (0 errors, 0 warnings).
4. Unstructured fallback parsing for non-standard error strings.
"""

from pathlib import Path
import pytest

from src.cscape.diagnostics import (
    CleanBuildProof,
    CompilerDiagnostic,
    CscapeLogParser,
    parse_diagnostics,
    verify_clean_build,
)


# ============================================================================
# 1. Error Pattern Parsing Tests
# ============================================================================

class TestErrorPatternParsing:
    """Verifies parsing of varied compiler output formats."""

    def test_pattern_line_col_first(self):
        """Verifies parsing when line and column appear at start of line."""
        cases = [
            ("Line 8 Col 21: error: Syntax error near ';'", 8, 21, "ERROR", None),
            ("Line 12, Col 5: error K51001: Unknown variable", 12, 5, "ERROR", "K51001"),
            ("(Line 20 Col 3): warning: Deprecated instruction", 20, 3, "WARNING", None),
            ("(15, 10): error: Missing parenthesis", 15, 10, "ERROR", None),
        ]
        for log_line, exp_line, exp_col, exp_level, exp_code in cases:
            diags = CscapeLogParser.parse_log(log_line)
            assert len(diags) == 1, f"Failed on: {log_line}"
            d = diags[0]
            assert d.line == exp_line
            assert d.column == exp_col
            assert d.level == exp_level
            if exp_code:
                assert d.error_code == exp_code

    def test_pattern_generic_line(self):
        """Verifies parsing when level appears at start with brackets or generic line syntax."""
        cases = [
            ("ERROR [ST_SYNTAX]: Line 8 Col 21: Unexpected token ';'", 8, 21, "ERROR", "ST_SYNTAX"),
            ("ERROR: Line 45: Assignment type mismatch", 45, None, "ERROR", None),
            ("WARNING [W1002]: Line 10, Col 2: Variable uninitialized", 10, 2, "WARNING", "W1002"),
        ]
        for log_line, exp_line, exp_col, exp_level, exp_code in cases:
            diags = CscapeLogParser.parse_log(log_line)
            assert len(diags) == 1, f"Failed on: {log_line}"
            d = diags[0]
            assert d.line == exp_line
            assert d.column == exp_col
            assert d.level == exp_level
            if exp_code:
                assert d.error_code == exp_code

    def test_pattern_cscape_location(self):
        """Verifies standard Cscape file(line,col) pattern."""
        cases = [
            ("PRG_Main.st(8,21): error ST_SYNTAX_ERROR: Unexpected token ';'", 8, 21, "ERROR", "ST_SYNTAX_ERROR", "PRG_Main"),
            ("MotorControl.st(14,5): error K51001: Syntax error near 'END_IF'", 14, 5, "ERROR", "K51001", "MotorControl"),
            ("FB_Timer.st(22): warning: Unused variable 'tAux'", 22, None, "WARNING", None, "FB_Timer"),
            (r"C:\HornerAI\horner-cscape-mcp\pous\PRG_Broken.st(8,21): error: Unexpected token", 8, 21, "ERROR", None, "PRG_Broken"),
        ]
        for log_line, exp_line, exp_col, exp_level, exp_code, exp_pou in cases:
            diags = CscapeLogParser.parse_log(log_line)
            assert len(diags) == 1, f"Failed on: {log_line}"
            d = diags[0]
            assert d.line == exp_line
            assert d.column == exp_col
            assert d.level == exp_level
            assert d.pou_name == exp_pou
            if exp_code:
                assert d.error_code == exp_code

    def test_fallback_embedded_line_col_extraction(self):
        """Verifies extraction of embedded line and column from unstructured lines."""
        line = "Fatal error: unexpected symbol at line 42, col 17 in expression"
        diags = CscapeLogParser.parse_log(line)
        assert len(diags) == 1
        d = diags[0]
        assert d.level == "ERROR"
        assert d.line == 42
        assert d.column == 17


# ============================================================================
# 2. Structured Diagnostic & Failure Location Serialization
# ============================================================================

class TestStructuredDiagnostic:
    """Verifies CompilerDiagnostic serialization and failure_location."""

    def test_diagnostic_to_dict_contains_failure_location(self):
        """Verifies ERROR level diagnostics produce structured failure_location dictionary."""
        diag = CompilerDiagnostic(
            level="ERROR",
            message="Syntax error near ';'",
            line=8,
            column=21,
            file_path=r"C:\HornerAI\horner-cscape-mcp\pous\Logic.st",
            pou_name="Logic",
            error_code="ST_SYNTAX_ERROR",
        )
        d = diag.to_dict()
        assert d["level"] == "ERROR"
        assert d["line"] == 8
        assert d["column"] == 21
        assert "failure_location" in d

        fl = d["failure_location"]
        assert fl["file_path"] == "Logic.st"
        assert fl["full_path"] == r"C:\HornerAI\horner-cscape-mcp\pous\Logic.st"
        assert fl["line"] == 8
        assert fl["column"] == 21
        assert fl["error_code"] == "ST_SYNTAX_ERROR"
        assert fl["severity"] == "ERROR"


# ============================================================================
# 3. Clean Build Proof Verification Tests
# ============================================================================

class TestCleanBuildProof:
    """Verifies clean build proof (0 errors, 0 warnings) vs failure detection."""

    def test_clean_build_proof_extraction(self):
        """Verifies extract_clean_build_proof on successful compilation log."""
        clean_log = """
=== Horner Cscape 10.2 Compile Pass: DemoClean ===
Clean Build: True
Compiling POU: Logic (300 bytes)...
  POU 'Logic' parsed and validated cleanly.
----------------------------------------------------------------
Build Result: SUCCESS
Errors: 0, Warnings: 0
Duration: 0.015s
Hardware Lockout: ENFORCED (Zero PLC communication / No download)
"""
        proof = CscapeLogParser.extract_clean_build_proof(clean_log)
        assert proof.is_clean is True
        assert proof.error_count == 0
        assert proof.warning_count == 0
        assert proof.status_text == "SUCCESS"
        assert len(proof.proof_lines) >= 2

    def test_failed_build_proof_rejection(self):
        """Verifies extract_clean_build_proof on compilation failure log."""
        fail_log = """
=== Horner Cscape 10.2 Compile Pass: DemoFail ===
Compiling POU: Broken (150 bytes)...
  Broken.st(8,21): error ST_SYNTAX_ERROR: Syntax error at line 8, col 21: Unexpected token ';'
----------------------------------------------------------------
Build Result: FAILED
Errors: 1, Warnings: 0
"""
        proof = verify_clean_build(fail_log)
        assert proof.is_clean is False
        assert proof.error_count == 1
        assert proof.status_text == "FAILED"

    def test_warnings_only_build_status(self):
        """Verifies warnings-only compilation results in WARNINGS status."""
        warn_log = """
=== Horner Cscape 10.2 Compile Pass: DemoWarn ===
Compiling POU: WarnPou (250 bytes)...
  WarnPou.st(15): warning: Variable 'tmp' is unused
----------------------------------------------------------------
Build Result: SUCCESS
Errors: 0, Warnings: 1
"""
        proof = verify_clean_build(warn_log)
        assert proof.is_clean is False
        assert proof.error_count == 0
        assert proof.warning_count == 1
        assert proof.status_text == "WARNINGS"

    def test_empty_output_log_fails_closed(self):
        """Mandate: Empty compilation output log must never be recognized as clean."""
        proof = verify_clean_build("")
        assert proof.is_clean is False
        assert proof.status_text == "FAILED"

    def test_whitespace_output_log_fails_closed(self):
        """Mandate: Whitespace-only compilation log must never be recognized as clean."""
        proof = verify_clean_build("   \r\n\t  \n")
        assert proof.is_clean is False
        assert proof.status_text == "FAILED"

    def test_stale_token_without_compile_activity_fails_closed(self):
        """Mandate: Bare 0-error tokens lacking compilation pass headers fail closed."""
        stale_tokens = [
            "0 errors, 0 warnings",
            "0 error(s), 0 warning(s)",
            "Errors: 0, Warnings: 0",
            "No errors detected",
        ]
        for token in stale_tokens:
            proof = CscapeLogParser.extract_clean_build_proof(token)
            assert proof.is_clean is False, f"Token '{token}' should not be clean without activity"
            assert proof.status_text == "FAILED"

    def test_bare_success_status_line_without_summary_fails_closed(self):
        """Mandate: Bare 'Build Result: SUCCESS' without error count summary fails closed."""
        proof = verify_clean_build("Build Result: SUCCESS")
        assert proof.is_clean is False
        assert proof.status_text == "FAILED"

    def test_truncated_log_without_clean_summary_fails_closed(self):
        """Mandate: Truncated log with compile activity but cut off before summary fails closed."""
        truncated_log = """=== Horner Cscape 10.2 Compile Pass: TestProj ===
Compiling POU: Logic (120 bytes)...
Parsed and validated: 25 statements
"""
        proof = verify_clean_build(truncated_log)
        assert proof.is_clean is False
        assert proof.status_text == "FAILED"

    def test_missing_summary_line_with_success_status_fails_closed(self):
        """Mandate: Compile activity + Build Result: SUCCESS without 0 errors summary fails closed."""
        log = """=== Horner Cscape 10.2 Compile Pass: TestProj ===
Compiling POU: Logic (120 bytes)...
Build Result: SUCCESS
"""
        proof = verify_clean_build(log)
        assert proof.is_clean is False
        assert proof.status_text == "FAILED"

    def test_parse_diagnostics_empty_and_whitespace(self):
        """Mandate: parse_diagnostics on empty or whitespace returns empty list."""
        assert parse_diagnostics("") == []
        assert parse_diagnostics("   \r\n\t  \n") == []

    def test_none_or_non_string_inputs_fail_closed(self):
        """Mandate: parse_diagnostics and verify_clean_build gracefully handle None/non-strings."""
        assert parse_diagnostics(None) == []
        assert parse_diagnostics(9999) == []

        proof_none = verify_clean_build(None)
        assert proof_none.is_clean is False
        assert proof_none.status_text == "FAILED"

    def test_corrupt_ansi_and_binary_characters(self):
        """Mandate: Binary nulls and ANSI escape sequences do not cause crashes or false success."""
        corrupt = "\x00\x01\x1b[31;1mCorrupt Build\x1b[0m\xff\xfe"
        diags = parse_diagnostics(corrupt)
        assert isinstance(diags, list)

        proof = verify_clean_build(corrupt)
        assert proof.is_clean is False
        assert proof.status_text == "FAILED"


