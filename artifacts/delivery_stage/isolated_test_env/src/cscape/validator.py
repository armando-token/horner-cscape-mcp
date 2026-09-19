"""Horner CScape IEC 61131-3 Structured Text Validator.

Provides syntax, AST, and ladder-rejection validation for Structured Text POUs
in Horner Cscape 10.2 environments.
"""

from typing import Any, Dict, Optional
from src.iec.validator import IECValidator


class LadderLogicForbiddenError(Exception):
    """Raised fail-closed when ladder logic artifacts are detected in Structured Text."""
    pass


class STSyntaxError(Exception):
    """Raised when IEC 61131-3 Structured Text syntax or AST parsing fails."""
    pass


def validate_st_source(code: str, raise_on_error: bool = False) -> Dict[str, Any]:
    """Validates IEC 61131-3 Structured Text source code.

    Enforces:
    1. Pure Structured Text grammar (zero ladder artifacts).
    2. Ladder logic rejection with ERR_LADDER_FORBIDDEN fail-closed.
    3. Proper POU structure (PROGRAM, FUNCTION_BLOCK, FUNCTION).
    4. Hardware safety and download lockout enforcement.
    5. Pure-Python AST syntax and variable declaration parsing.

    Args:
        code: IEC 61131-3 Structured Text source code string.
        raise_on_error: If True, raises LadderLogicForbiddenError or STSyntaxError
                        on validation failure instead of returning dict.

    Returns:
        Dictionary containing valid, pou_name, pou_type, errors, warnings, metrics.
    """
    res = IECValidator.validate(code)

    if raise_on_error and not res["valid"]:
        errors_str = "; ".join(res.get("errors", []))
        if any("ERR_LADDER_FORBIDDEN" in err for err in res.get("errors", [])):
            raise LadderLogicForbiddenError(f"ERR_LADDER_FORBIDDEN: {errors_str}")
        raise STSyntaxError(f"ST_SYNTAX_ERROR: {errors_str}")

    return res


__all__ = [
    "validate_st_source",
    "LadderLogicForbiddenError",
    "STSyntaxError",
]
