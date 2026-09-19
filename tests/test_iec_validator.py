"""Tests for IEC 61131-3 Structured Text Validator.

Verifies:
1. Honest AST-derived metrics and absence of heuristic mock sizing formulas.
2. Unconditional download lockout for ID_CONTROLLER_DOWNLOAD (32827) and ID_PROGRAM_DOWNLOADOPTIONS (33149).
3. Hardware safety enforcement (rejection of physical download and flash primitives).
4. Pure IEC 61131-3 grammar enforcement: ladder artifact rejection, block nesting, and variable scopes.
"""

import pytest

from src.iec.validator import (
    IECValidator,
    ID_CONTROLLER_DOWNLOAD,
    ID_PROGRAM_DOWNLOADOPTIONS,
)
from src.security.exceptions import UnauthorizedDownloadError


# ============================================================================
# 1. Honest AST-Derived Metrics Tests
# ============================================================================

class TestIECValidatorHonestASTMetrics:
    """Verifies that IECValidator returns honest AST metrics and labeled estimates."""

    def test_validator_returns_honest_ast_metrics(self):
        """Verifies AST node counts and byte counts are populated in validation metrics."""
        code = """PROGRAM MeasureMetrics
VAR
    InSensor : BOOL := FALSE;
    OutActuator : BOOL := FALSE;
    CycleCount : INT := 0;
END_VAR

IF InSensor THEN
    OutActuator := TRUE;
    CycleCount := CycleCount + 1;
ELSE
    OutActuator := FALSE;
END_IF;
END_PROGRAM
"""
        res = IECValidator.validate(code)
        assert res["valid"] is True
        metrics = res["metrics"]

        assert "ast_statement_count" in metrics
        assert "ast_variable_count" in metrics
        assert "ast_expression_count" in metrics
        assert "source_bytes_total" in metrics
        assert "estimated_ast_footprint" in metrics

        assert metrics["ast_variable_count"] == 3
        assert metrics["ast_statement_count"] >= 3
        assert metrics["ast_expression_count"] >= 3
        assert metrics["source_bytes_total"] == len(code.encode("utf-8"))

        fp = metrics["estimated_ast_footprint"]
        assert fp["ast_variable_count"] == 3
        assert fp["source_bytes_total"] == len(code.encode("utf-8"))

    def test_validator_metrics_empty_source(self):
        """Verifies empty code returns zeroed metrics without crashing."""
        res = IECValidator.validate("")
        assert res["valid"] is False
        assert res["metrics"]["total_lines"] == 0
        assert res["metrics"]["variable_count"] == 0


# ============================================================================
# 2. Hardware Download Lockout & Safety Tests
# ============================================================================

class TestIECValidatorDownloadLockout:
    """Verifies fail-closed download lockout and hardware safety directives."""

    def test_download_constants_defined(self):
        """Verifies controller download command ID constants in IECValidator."""
        assert IECValidator.ID_CONTROLLER_DOWNLOAD == 32827
        assert IECValidator.ID_PROGRAM_DOWNLOADOPTIONS == 33149
        assert ID_CONTROLLER_DOWNLOAD == 32827
        assert ID_PROGRAM_DOWNLOADOPTIONS == 33149

    def test_check_download_lockout_blocks_32827(self):
        """Verifies check_download_lockout unconditionally raises UnauthorizedDownloadError for 32827."""
        with pytest.raises(UnauthorizedDownloadError, match="Hardware lockout"):
            IECValidator.check_download_lockout(32827)

        with pytest.raises(UnauthorizedDownloadError, match="Hardware lockout"):
            IECValidator.check_download_lockout(ID_CONTROLLER_DOWNLOAD)

    def test_check_download_lockout_blocks_33149(self):
        """Verifies check_download_lockout unconditionally raises UnauthorizedDownloadError for 33149."""
        with pytest.raises(UnauthorizedDownloadError, match="Hardware lockout"):
            IECValidator.check_download_lockout(33149)

        with pytest.raises(UnauthorizedDownloadError, match="Hardware lockout"):
            IECValidator.check_download_lockout(ID_PROGRAM_DOWNLOADOPTIONS)

    def test_check_download_lockout_blocks_string_names(self):
        """Verifies string command identifiers trigger UnauthorizedDownloadError."""
        with pytest.raises(UnauthorizedDownloadError, match="Hardware lockout"):
            IECValidator.check_download_lockout("ID_CONTROLLER_DOWNLOAD")

        with pytest.raises(UnauthorizedDownloadError, match="Hardware lockout"):
            IECValidator.check_download_lockout("ID_PROGRAM_DOWNLOADOPTIONS")

        with pytest.raises(UnauthorizedDownloadError, match="Hardware lockout"):
            IECValidator.check_download_lockout("PLC_DOWNLOAD")

    def test_check_hardware_safety_rejects_dangerous_primitives(self):
        """Verifies detection of forbidden physical hardware access in code."""
        dangerous_code = """PROGRAM MaliciousFlash
VAR
    x : INT;
END_VAR
PGMUpdateUtility();
FLASH_ERASE();
CONTROLLER_DOWNLOAD();
END_PROGRAM
"""
        errors = IECValidator.check_hardware_safety(dangerous_code)
        assert len(errors) >= 3
        assert any("PGMUpdateUtility" in e for e in errors)
        assert any("FLASH_ERASE" in e for e in errors)
        assert any("CONTROLLER_DOWNLOAD" in e for e in errors)

    def test_validate_rejects_hardware_download_code(self):
        """Verifies full validation fails when code contains prohibited download primitives."""
        code = """PROGRAM BadDownload
VAR
    flag : BOOL := TRUE;
END_VAR
DIRECT_IO();
DfuSeCommand();
END_PROGRAM
"""
        res = IECValidator.validate(code)
        assert res["valid"] is False
        assert any("ERR_HARDWARE_LOCKOUT" in e for e in res["errors"])


# ============================================================================
# 3. Pure IEC 61131-3 Structured Text Grammar Tests
# ============================================================================

class TestIECValidatorGrammarEnforcement:
    """Verifies ladder artifact rejection, block nesting, and variable scopes."""

    def test_rejection_of_ladder_logic_artifacts(self):
        """Verifies ladder logic symbols and rung keywords are strictly rejected."""
        ladder_snippets = [
            ("---[ ]---", "Normally open contact"),
            ("---[/]---", "Normally closed contact"),
            ("---( )---", "Normal coil"),
            ("---( S )---", "Set coil"),
            ("RUNG 1", "Rung marker"),
            ("END_RUNG", "End rung marker"),
            ("NETWORK 1", "Network marker"),
            ("LADDER", "Ladder marker"),
        ]

        for pattern, desc in ladder_snippets:
            code = f"""PROGRAM LadderTest
VAR
    bIn : BOOL;
END_VAR
{pattern}
END_PROGRAM
"""
            errors = IECValidator.check_ladder_artifacts(code)
            assert len(errors) >= 1, f"Failed to reject ladder artifact: {desc} ({pattern})"
            assert "ERR_LADDER_FORBIDDEN" in errors[0]

            res = IECValidator.validate(code)
            assert res["valid"] is False

    def test_block_nesting_validation(self):
        """Verifies correct pairing and nesting of control blocks."""
        valid_code = """PROGRAM NestingOk
VAR
    x : INT := 0;
END_VAR
IF x > 0 THEN
    WHILE x < 10 DO
        x := x + 1;
    END_WHILE;
END_IF;
END_PROGRAM
"""
        nest_errors = IECValidator.check_block_nesting(valid_code)
        assert len(nest_errors) == 0

        unclosed_code = """PROGRAM NestingBad
VAR
    x : INT := 0;
END_VAR
IF x > 0 THEN
    x := x + 1;
END_PROGRAM
"""
        unclosed_errors = IECValidator.check_block_nesting(unclosed_code)
        assert len(unclosed_errors) >= 1
        assert any("Unclosed" in e or "IF" in e for e in unclosed_errors)

    def test_variable_scopes_parsing(self):
        """Verifies parsing of variables across all standard IEC scopes."""
        code = """PROGRAM ScopeTest
VAR_INPUT
    In1 : BOOL;
    In2 : INT;
END_VAR
VAR_OUTPUT
    Out1 : REAL;
END_VAR
VAR_IN_OUT
    InOut1 : DINT;
END_VAR
VAR
    Local1 : WORD;
END_VAR
Local1 := 16#00FF;
END_PROGRAM
"""
        vars_list, errs = IECValidator.parse_variables(code)
        assert len(errs) == 0
        assert len(vars_list) == 5

        scopes = {v["name"]: v["scope"] for v in vars_list}
        assert scopes["In1"] == "VAR_INPUT"
        assert scopes["In2"] == "VAR_INPUT"
        assert scopes["Out1"] == "VAR_OUTPUT"
        assert scopes["InOut1"] == "VAR_IN_OUT"
        assert scopes["Local1"] == "VAR"

    def test_strip_comments_preserves_newlines(self):
        """Verifies comment stripping preserves newline structure for accurate line reporting."""
        code = """// Line 1 comment
PROGRAM CommentTest (* Block comment
on line 2 and 3 *)
VAR
    /* C-style comment */
    x : INT := 0;
END_VAR
x := 1;
END_PROGRAM
"""
        stripped = IECValidator.strip_comments(code)
        assert stripped.count("\n") == code.count("\n")
        assert "Block comment" not in stripped
        assert "C-style comment" not in stripped
        assert "PROGRAM CommentTest" in stripped
