"""
Unit tests for IEC 61131-3 Structured Text Validator and Safety Guard.
"""
import pytest
from src.validation.validator import STValidator

def test_validator_valid_code():
    code = """
    PROGRAM PumpController
    VAR_INPUT
        bStart : BOOL := FALSE;
        bStop : BOOL := FALSE;
    END_VAR
    VAR_OUTPUT
        bPumpActive : BOOL := FALSE;
    END_VAR
    VAR
        runTimer : TON;
    END_VAR

    runTimer(IN := bStart, PT := T#10s);
    IF bStart AND NOT bStop THEN
        bPumpActive := TRUE;
    ELSIF bStop THEN
        bPumpActive := FALSE;
    END_IF;
    END_PROGRAM
    """
    val = STValidator()
    res = val.validate(code)
    assert res.is_valid is True
    assert len(res.errors) == 0
    assert "bStart" in res.declared_variables or "BSTART" in res.declared_variables
    assert "TON" in res.used_function_blocks

def test_validator_syntax_error():
    bad_code = """
    PROGRAM BadSyntax
    VAR
        x : INT
    END_VAR
    x := 5;
    END_PROGRAM
    """
    val = STValidator()
    res = val.validate(bad_code)
    assert res.is_valid is False
    assert len(res.errors) > 0
    assert any("Syntax error" in str(e) or "Expected" in str(e) for e in res.errors)

def test_validator_safety_hardware_violation():
    dangerous_code = """
    PROGRAM MaliciousHardwareAccess
    VAR
        x : INT := 0;
    END_VAR
    // Attempting prohibited physical PLC flash/download operation
    PGMUpdateUtility(command := 1);
    DIRECT_IO(port := 2);
    FLASH_ERASE();
    x := 10;
    END_PROGRAM
    """
    val = STValidator()
    res = val.validate(dangerous_code)
    assert res.is_valid is False
    assert len(res.errors) >= 3
    error_texts = [str(e) for e in res.errors]
    assert any("PGMUpdateUtility" in t for t in error_texts)
    assert any("DIRECT_IO" in t for t in error_texts)
    assert any("FLASH_ERASE" in t for t in error_texts)

def test_validator_warnings():
    code = """
    PROGRAM WarningTest
    VAR
        x : INT := 0;
        x : INT := 10; // Duplicate declaration
        customVar : CUSTOM_SPECIAL_TYPE; // Non-standard type
    END_VAR
    x := 20;
    undeclaredVar := 50; // Undeclared variable reference
    END_PROGRAM
    """
    val = STValidator()
    res = val.validate(code)
    assert len(res.warnings) >= 2
    warn_texts = [str(w) for w in res.warnings]
    assert any("Duplicate" in t for t in warn_texts)
    assert any("CUSTOM_SPECIAL_TYPE" in t for t in warn_texts)
    assert any("UNDECLAREDVAR" in t for t in warn_texts)