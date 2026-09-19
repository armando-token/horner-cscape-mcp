"""Audit test suite for Cscape compiler diagnostics scraping and error parsing.

Verifies:
1. Line and column error regexes against Cscape output patterns.
2. Clean build proof (0 errors, 0 warnings) vs syntax error extraction (Line 8 Col 21).
3. Parsing of multi-line error strings into structured CompilerDiagnostic objects.
4. Direct imports and APIs from src.cscape.diagnostics and src.cscape.compilation.
"""

from pathlib import Path
import pytest

from src.cscape.diagnostics import (
    CompilerDiagnostic,
    CleanBuildProof,
    CscapeLogParser,
    parse_diagnostics,
    verify_clean_build,
)
from src.cscape.compilation import (
    CscapeCompiler,
    CscapeBuildResult,
    BuildStatus,
    ID_PROGRAM_ERRORCHECK,
    VK_F7_COMMAND,
    ID_OUTPUT_WINDOW,
    ID_OUTPUT_LISTBOX,
)


class TestDiagnosticsScraperAudit:
    """Verifies regexes, clean build proof, and error parsing accuracy."""

    def test_line_and_column_regexes_against_cscape_patterns(self):
        """Audit 1: Verify line and column error regexes against varied Cscape output patterns."""
        test_cases = [
            # Standard Cscape/Straton format: file(line,col): error code: msg
            ("PRG_BrokenSyntax.st(8,21): error ST_SYNTAX_ERROR: Syntax error at line 8, col 21: Unexpected token in expression: SEMICOLON (';')", 8, 21, "ERROR", "ST_SYNTAX_ERROR"),
            ("MainControl.st(14,5): error K51001: Syntax error near 'END_IF'", 14, 5, "ERROR", "K51001"),
            ("FB_Motor.st(22): warning: Unused variable 'bAux'", 22, None, "WARNING", None),
            # Explicit Line X Col Y inside parens
            ("PRG_BrokenSyntax.st(Line 8 Col 21): error: Empty assignment", 8, 21, "ERROR", None),
            ("PRG_BrokenSyntax.st(Line 8, Col 21): error: Unexpected token", 8, 21, "ERROR", None),
            # Line X Col Y prefix format
            ("Line 8 Col 21: error: Syntax error near ';'", 8, 21, "ERROR", None),
            ("Line 8, Col 21: error K51002: Unexpected semicolon", 8, 21, "ERROR", "K51002"),
            ("(Line 8 Col 21): error: Syntax error", 8, 21, "ERROR", None),
            # Generic line format
            ("ERROR [ST_SYNTAX_ERROR]: Line 8 Col 21: Unexpected semicolon", 8, 21, "ERROR", "ST_SYNTAX_ERROR"),
            ("ERROR: Line 8: Missing token", 8, None, "ERROR", None),
            # Absolute Windows path
            (r"C:\HornerAI\horner-cscape-mcp\pous\PRG_BrokenSyntax.st(8,21): error: Semicolon error", 8, 21, "ERROR", None),
        ]

        for log_line, exp_line, exp_col, exp_level, exp_code in test_cases:
            diags = CscapeLogParser.parse_log(log_line)
            assert len(diags) == 1, f"Failed parsing: {log_line}"
            d = diags[0]
            assert d.line == exp_line, f"Line mismatch for '{log_line}': expected {exp_line}, got {d.line}"
            assert d.column == exp_col, f"Column mismatch for '{log_line}': expected {exp_col}, got {d.column}"
            assert d.level == exp_level, f"Level mismatch for '{log_line}': expected {exp_level}, got {d.level}"
            if exp_code:
                assert d.error_code == exp_code, f"Code mismatch for '{log_line}': expected {exp_code}, got {d.error_code}"

    def test_syntax_error_extraction_line_8_col_21(self):
        """Audit 2A: Verify exact Line 8 Col 21 syntax error extraction."""
        log_snippet = """
=== Horner Cscape 10.2 Compile Pass: proof_syntax_error_project ===
Clean Build: True
Mode: IEC 61131-3 Structured Text (Advanced Ladder Excluded)
Timestamp: 2026-09-04T09:56:12.377491
----------------------------------------------------------------
Compiling POU: PRG_BrokenSyntax (171 bytes)...
  PRG_BrokenSyntax.st(8,21): error ST_SYNTAX_ERROR: Syntax error at line 8, col 21: Unexpected token in expression: SEMICOLON (';')
----------------------------------------------------------------
Build Result: FAILED
Errors: 1, Warnings: 0
Duration: 0.014s
Hardware Lockout: ENFORCED (Zero PLC communication / No download)
"""
        diags = CscapeLogParser.parse_log(log_snippet)
        assert len(diags) == 1
        d = diags[0]
        assert d.line == 8
        assert d.column == 21
        assert d.level == "ERROR"
        assert d.error_code == "ST_SYNTAX_ERROR"
        assert d.pou_name == "PRG_BrokenSyntax"
        assert "SEMICOLON" in d.message
        assert d.file_path == "PRG_BrokenSyntax.st"

        # Verify clean build check reports not clean
        proof = CscapeLogParser.extract_clean_build_proof(log_snippet)
        assert proof.is_clean is False
        assert proof.error_count == 1
        assert proof.warning_count == 0
        assert proof.status_text == "FAILED"

    def test_clean_build_proof_extraction_0_errors_0_warnings(self):
        """Audit 2B: Verify clean build proof (0 errors, 0 warnings) extraction."""
        clean_log = """
=== Horner Cscape 10.2 Compile Pass: proof_clean_project ===
Clean Build: True
Mode: IEC 61131-3 Structured Text (Advanced Ladder Excluded)
Timestamp: 2026-09-04T09:56:12.351638
----------------------------------------------------------------
Compiling POU: PRG_CleanPumpControl (572 bytes)...
  POU 'PRG_CleanPumpControl' parsed and validated cleanly.
----------------------------------------------------------------
Build Result: SUCCESS
Errors: 0, Warnings: 0
Estimated Code Size: 1084 bytes, Data Size: 512 bytes
Duration: 0.017s
Hardware Lockout: ENFORCED (Zero PLC communication / No download)
"""
        diags = CscapeLogParser.parse_log(clean_log)
        assert len(diags) == 0

        proof = CscapeLogParser.extract_clean_build_proof(clean_log)
        assert proof.is_clean is True
        assert proof.error_count == 0
        assert proof.warning_count == 0
        assert proof.status_text == "SUCCESS"
        assert len(proof.proof_lines) >= 2
        assert any("Errors: 0, Warnings: 0" in pl for pl in proof.proof_lines)
        assert any("Build Result: SUCCESS" in pl for pl in proof.proof_lines)

    def test_live_gui_cscape_clean_build_format(self):
        """Audit 2C: Verify Cscape live GUI output window clean format (0 error(s), 0 warning(s))."""
        live_gui_clean_text = """Compilation succeeded.
0 error(s), 0 warning(s)
"""
        diags = CscapeLogParser.parse_log(live_gui_clean_text)
        assert len(diags) == 0

        proof = verify_clean_build(live_gui_clean_text)
        assert proof.is_clean is True
        assert proof.error_count == 0
        assert proof.warning_count == 0
        assert proof.status_text == "SUCCESS"
        assert any("0 error(s), 0 warning(s)" in pl for pl in proof.proof_lines)

    def test_multiline_error_strings_to_structured_diagnostics(self):
        """Audit 3: Confirm parsing of multi-line error strings into structured CompilerDiagnostic objects."""
        multiline_log = """
=== Cscape Build Session: IndustrialPlant ===
Compiling POU: SafetyInterlock (840 bytes)...
SafetyInterlock.st(12,8): error K51003: Type mismatch: Cannot assign REAL to BOOL
Compiling POU: PumpSequencer (1200 bytes)...
PumpSequencer.st(8,21): error ST_SYNTAX_ERROR: Syntax error at line 8, col 21: Unexpected token: SEMICOLON
PumpSequencer.st(45,3): warning W2001: Variable 'rTemp' assigned but never evaluated
Compiling POU: AlarmMonitor (450 bytes)...
AlarmMonitor.st(100): error K51099: Undeclared identifier 'ESTOP_FLAG'
----------------------------------------------------------------
Build Result: FAILED
Errors: 3, Warnings: 1
"""
        diags = parse_diagnostics(multiline_log)
        assert len(diags) == 4

        # Verify item 0
        assert diags[0].level == "ERROR"
        assert diags[0].line == 12
        assert diags[0].column == 8
        assert diags[0].error_code == "K51003"
        assert diags[0].pou_name == "SafetyInterlock"
        assert "Type mismatch" in diags[0].message

        # Verify item 1 (Line 8 Col 21)
        assert diags[1].level == "ERROR"
        assert diags[1].line == 8
        assert diags[1].column == 21
        assert diags[1].error_code == "ST_SYNTAX_ERROR"
        assert diags[1].pou_name == "PumpSequencer"

        # Verify item 2 (Warning)
        assert diags[2].level == "WARNING"
        assert diags[2].line == 45
        assert diags[2].column == 3
        assert diags[2].error_code == "W2001"
        assert diags[2].pou_name == "PumpSequencer"

        # Verify item 3 (Line without column)
        assert diags[3].level == "ERROR"
        assert diags[3].line == 100
        assert diags[3].column is None
        assert diags[3].error_code == "K51099"
        assert diags[3].pou_name == "AlarmMonitor"

        # Verify serialization of all objects
        for d in diags:
            d_dict = d.to_dict()
            assert "level" in d_dict
            assert "message" in d_dict
            assert "line" in d_dict
            assert "column" in d_dict
            assert "file_path" in d_dict
            assert "pou_name" in d_dict
            assert "error_code" in d_dict

    def test_actual_evidence_log_files_exist_and_validate(self):
        """Audit 4: Verify real evidence logs on disk match expected proof metrics."""
        clean_proof_log = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\logs\st_clean_compile_proof.log")
        assert clean_proof_log.exists()
        clean_text = clean_proof_log.read_text(encoding="utf-8")
        clean_proof = verify_clean_build(clean_text)
        assert clean_proof.is_clean is True
        assert clean_proof.error_count == 0

        syntax_proof_log = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\logs\st_syntax_error_proof.log")
        assert syntax_proof_log.exists()
        syntax_text = syntax_proof_log.read_text(encoding="utf-8")
        syntax_diags = parse_diagnostics(syntax_text)
        assert len(syntax_diags) >= 1
        line8_col21_found = any(d.line == 8 and d.column == 21 for d in syntax_diags)
        assert line8_col21_found is True
