"""IEC 61131-3 Structured Text (ST) Parser, AST Builder, and Validator.

Supports full IEC 61131-3 Structured Text syntax:
- POUs: PROGRAM, FUNCTION_BLOCK, FUNCTION
- Variable Scopes: VAR, VAR_INPUT, VAR_OUTPUT, VAR_IN_OUT, VAR_GLOBAL, VAR_TEMP, VAR_EXTERNAL (RETAIN, CONSTANT)
- Data Types: BOOL, BYTE, WORD, DWORD, SINT, INT, DINT, LINT, USINT, UINT, UDINT, ULINT, REAL, LREAL, TIME, STRING
- Statements: IF-THEN-ELSIF-ELSE, CASE-OF, FOR-TO-BY-DO, WHILE-DO, REPEAT-UNTIL, RETURN, EXIT, assignments, calls
- Strict error checking: Missing semicolons, undeclared variables, mismatched types, syntax anomalies
- Enforces Structured Text only: strictly rejects Advanced Ladder logic constructs
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union


# ============================================================================
# Enums and Data Models
# ============================================================================

class POUKind(str, Enum):
    PROGRAM = "PROGRAM"
    FUNCTION_BLOCK = "FUNCTION_BLOCK"
    FUNCTION = "FUNCTION"


class VarScope(str, Enum):
    VAR = "VAR"
    VAR_INPUT = "VAR_INPUT"
    VAR_OUTPUT = "VAR_OUTPUT"
    VAR_IN_OUT = "VAR_IN_OUT"
    VAR_GLOBAL = "VAR_GLOBAL"
    VAR_TEMP = "VAR_TEMP"
    VAR_EXTERNAL = "VAR_EXTERNAL"


class IssueSeverity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


# All 16 standard IEC 61131-3 elementary types specified in requirements
STANDARD_DATA_TYPES: Set[str] = {
    "BOOL",
    "BYTE", "WORD", "DWORD", "LWORD",
    "SINT", "INT", "DINT", "LINT",
    "USINT", "UINT", "UDINT", "ULINT",
    "REAL", "LREAL",
    "TIME",
    "STRING",
    # Extended standard types
    "DATE", "TIME_OF_DAY", "TOD", "DATE_AND_TIME", "DT", "WSTRING",
}

INTEGER_TYPES: Set[str] = {
    "SINT", "INT", "DINT", "LINT",
    "USINT", "UINT", "UDINT", "ULINT",
    "BYTE", "WORD", "DWORD", "LWORD",
}

REAL_TYPES: Set[str] = {"REAL", "LREAL"}

BOOLEAN_TYPES: Set[str] = {"BOOL"}

STRING_TYPES: Set[str] = {"STRING", "WSTRING"}

TIME_TYPES: Set[str] = {"TIME"}

# Built-in standard functions, standard function blocks, and keywords
STANDARD_FUNCTIONS: Set[str] = {
    "ABS", "SQRT", "LN", "LOG", "EXP", "SIN", "COS", "TAN", "ASIN", "ACOS", "ATAN",
    "EXPT", "ADD", "MUL", "SUB", "DIV", "MOD", "MOVE",
    "TRUNC", "ROUND", "SEL", "MAX", "MIN", "LIMIT", "MUX",
    "SHL", "SHR", "ROL", "ROR", "AND", "OR", "XOR", "NOT",
    "LEN", "LEFT", "RIGHT", "MID", "CONCAT", "INSERT", "DELETE", "REPLACE", "FIND",
}

# Dynamically populate standard IEC conversions <TYPE1>_TO_<TYPE2>
for _t1 in STANDARD_DATA_TYPES:
    for _t2 in STANDARD_DATA_TYPES:
        STANDARD_FUNCTIONS.add(f"{_t1}_TO_{_t2}")

STANDARD_FUNCTION_BLOCKS: Set[str] = {
    "TON", "TOF", "TP", "R_TRIG", "F_TRIG", "SR", "RS", "SEMA",
    "CTU", "CTD", "CTUD", "RTC", "PID",
}

LADDER_PATTERNS = [
    (r"---\[\s*\]---", "Normally open contact"),
    (r"---\[\s*/\s*\]---", "Normally closed contact"),
    (r"---\(\s*\)---", "Relay coil"),
    (r"---\(\s*[SLR]\s*\)---", "Set/Reset coil"),
    (r"---\s*[SLRU]\s*---", "Set/Reset coil shorthand"),
    (r"^\s*RUNG\b", "Rung header"),
    (r"^\s*END_RUNG\b", "Rung terminator"),
    (r"^\s*NETWORK\s+\d+", "Ladder network"),
    (r"\bCONTACT\b", "Ladder contact"),
    (r"\bCOIL\b", "Ladder coil"),
    (r"\b(XIC|XIO|OTE|OTL|OTU|OSR|OSF)\s*\(", "Ladder mnemonic instruction"),
]


@dataclass
class STIssue:
    severity: IssueSeverity
    code: str
    message: str
    line: int
    column: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "line": self.line,
            "column": self.column,
        }


@dataclass
class STVariable:
    name: str
    data_type: str
    scope: VarScope = VarScope.VAR
    initial_value: Optional[str] = None
    is_retain: bool = False
    is_constant: bool = False
    is_array: bool = False
    array_bounds: Optional[str] = None
    address: Optional[str] = None
    comment: Optional[str] = None
    line: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "data_type": self.data_type,
            "scope": self.scope.value,
            "initial_value": self.initial_value,
            "is_retain": self.is_retain,
            "is_constant": self.is_constant,
            "is_array": self.is_array,
            "array_bounds": self.array_bounds,
            "address": self.address,
            "comment": self.comment,
            "line": self.line,
        }


@dataclass
class STPOU:
    kind: POUKind
    name: str
    return_type: Optional[str] = None
    variables: List[STVariable] = field(default_factory=list)
    body: str = ""
    description: str = ""
    line: int = 1

    def get_variables_by_scope(self, scope: VarScope) -> List[STVariable]:
        return [v for v in self.variables if v.scope == scope]

    def get_variable(self, name: str) -> Optional[STVariable]:
        for v in self.variables:
            if v.name.lower() == name.lower():
                return v
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "name": self.name,
            "return_type": self.return_type,
            "description": self.description,
            "line": self.line,
            "variables": [v.to_dict() for v in self.variables],
            "body_line_count": len(self.body.splitlines()),
        }


@dataclass
class STValidationResult:
    is_valid: bool
    issues: List[STIssue] = field(default_factory=list)
    pous: List[STPOU] = field(default_factory=list)
    global_variables: List[STVariable] = field(default_factory=list)

    @property
    def errors(self) -> List[STIssue]:
        return [i for i in self.issues if i.severity == IssueSeverity.ERROR]

    @property
    def warnings(self) -> List[STIssue]:
        return [i for i in self.issues if i.severity == IssueSeverity.WARNING]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [i.to_dict() for i in self.issues],
            "pous": [p.to_dict() for p in self.pous],
            "global_variable_count": len(self.global_variables),
        }


# ============================================================================
# Parser and Validator Implementation
# ============================================================================

class STParser:
    """Parses and validates IEC 61131-3 Structured Text programs."""

    KEYWORDS = {
        "PROGRAM", "END_PROGRAM",
        "FUNCTION_BLOCK", "END_FUNCTION_BLOCK",
        "FUNCTION", "END_FUNCTION",
        "VAR", "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT",
        "VAR_GLOBAL", "VAR_TEMP", "VAR_EXTERNAL", "END_VAR",
        "RETAIN", "CONSTANT", "AT",
        "IF", "THEN", "ELSIF", "ELSE", "END_IF",
        "CASE", "OF", "END_CASE",
        "FOR", "TO", "BY", "DO", "END_FOR",
        "WHILE", "END_WHILE",
        "REPEAT", "UNTIL", "END_REPEAT",
        "RETURN", "EXIT",
        "AND", "OR", "XOR", "NOT", "MOD",
        "TRUE", "FALSE",
        "ARRAY",
    }

    def __init__(self, code: str):
        self.raw_code = code
        self.clean_code = ""
        self.lines: List[str] = code.splitlines()
        self.issues: List[STIssue] = []
        self.pous: List[STPOU] = []
        self.global_variables: List[STVariable] = []

    # ------------------------------------------------------------------------
    # Comment Stripping & Ladder Logic Detection
    # ------------------------------------------------------------------------

    @staticmethod
    def strip_comments(code: str) -> str:
        """Strips IEC block (* ... *), C-style /* ... */, and // comments while preserving line count."""
        def preserve_newlines(match: re.Match) -> str:
            return "\n" * match.group(0).count("\n")

        # Strip IEC block comments (* ... *)
        no_iec = re.sub(r"\(\*[\s\S]*?\*\)", preserve_newlines, code)
        # Strip C-style block comments /* ... */
        no_c = re.sub(r"/\*[\s\S]*?\*/", preserve_newlines, no_iec)
        # Strip single line comments // ...
        no_line = re.sub(r"//.*$", "", no_c, flags=re.MULTILINE)
        return no_line

    def _check_forbidden_ladder(self) -> bool:
        """Strictly detects and rejects any Advanced Ladder constructs."""
        found_ladder = False
        clean_code = self.strip_comments(self.raw_code)
        clean_lines = clean_code.splitlines()

        for line_idx, clean_line in enumerate(clean_lines, start=1):
            if not clean_line.strip():
                continue

            raw_line = self.lines[line_idx - 1] if line_idx - 1 < len(self.lines) else clean_line

            for pattern, desc in LADDER_PATTERNS:
                m_ladder = re.search(pattern, clean_line, re.IGNORECASE)
                if m_ladder:
                    col_idx = m_ladder.start() + 1
                    self.issues.append(
                        STIssue(
                            severity=IssueSeverity.ERROR,
                            code="ERR_LADDER_FORBIDDEN",
                            message=(
                                f"Forbidden ladder logic construct '{desc}' detected: '{raw_line.strip()}'. "
                                "Strict constraint violated: ONLY pure IEC 61131-3 Structured Text is permitted."
                            ),
                            line=line_idx,
                            column=col_idx,
                        )
                    )
                    found_ladder = True
        return found_ladder

    # ------------------------------------------------------------------------
    # Unclosed Block Detection
    # ------------------------------------------------------------------------

    def _check_block_pairing(self, code: str) -> None:
        """Checks that all block start/end pairs match properly."""
        block_pairs = [
            ("PROGRAM", "END_PROGRAM", "ERR_UNCLOSED_PROGRAM"),
            ("FUNCTION_BLOCK", "END_FUNCTION_BLOCK", "ERR_UNCLOSED_FUNCTION_BLOCK"),
            ("FUNCTION", "END_FUNCTION", "ERR_UNCLOSED_FUNCTION"),
            ("IF", "END_IF", "ERR_UNCLOSED_IF"),
            ("CASE", "END_CASE", "ERR_UNCLOSED_CASE"),
            ("FOR", "END_FOR", "ERR_UNCLOSED_FOR"),
            ("WHILE", "END_WHILE", "ERR_UNCLOSED_WHILE"),
            ("REPEAT", "END_REPEAT", "ERR_UNCLOSED_REPEAT"),
        ]

        # Check comment closures
        open_iec_comments = len(re.findall(r"\(\*", code))
        close_iec_comments = len(re.findall(r"\*\)", code))
        if open_iec_comments != close_iec_comments:
            self.issues.append(
                STIssue(
                    severity=IssueSeverity.ERROR,
                    code="ERR_UNCLOSED_COMMENT",
                    message=f"Mismatched IEC block comments: found {open_iec_comments} '(*' and {close_iec_comments} '*)'.",
                    line=1,
                )
            )

        open_c_comments = len(re.findall(r"/\*", code))
        close_c_comments = len(re.findall(r"\*/", code))
        if open_c_comments != close_c_comments:
            self.issues.append(
                STIssue(
                    severity=IssueSeverity.ERROR,
                    code="ERR_UNCLOSED_COMMENT",
                    message=f"Mismatched C-style comments: found {open_c_comments} '/*' and {close_c_comments} '*/'.",
                    line=1,
                )
            )

        stripped = self.strip_comments(code)
        tokens = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", stripped)

        for open_kw, close_kw, err_code in block_pairs:
            # Special check for FUNCTION vs FUNCTION_BLOCK
            if open_kw == "FUNCTION":
                # Only count FUNCTION that is not followed by _BLOCK
                opens = sum(1 for t in tokens if t.upper() == "FUNCTION")
                fb_opens = sum(1 for t in tokens if t.upper() == "FUNCTION_BLOCK")
                opens = opens - fb_opens
                closes = sum(1 for t in tokens if t.upper() == "END_FUNCTION")
                fb_closes = sum(1 for t in tokens if t.upper() == "END_FUNCTION_BLOCK")
                closes = closes - fb_closes
            else:
                opens = sum(1 for t in tokens if t.upper() == open_kw)
                closes = sum(1 for t in tokens if t.upper() == close_kw)

            if opens > closes:
                m_open = re.search(r"\b" + open_kw + r"\b", stripped, re.IGNORECASE)
                if m_open:
                    open_line = stripped[:m_open.start()].count("\n") + 1
                    open_col = m_open.start() - max(0, stripped.rfind("\n", 0, m_open.start()))
                else:
                    open_line, open_col = 1, 1
                self.issues.append(
                    STIssue(
                        severity=IssueSeverity.ERROR,
                        code=err_code,
                        message=f"Unclosed {open_kw} block: {opens} '{open_kw}' opened, but only {closes} '{close_kw}' closed.",
                        line=open_line,
                        column=open_col,
                    )
                )
            elif closes > opens:
                self.issues.append(
                    STIssue(
                        severity=IssueSeverity.ERROR,
                        code="ERR_EXTRA_CLOSE_BLOCK",
                        message=f"Unexpected '{close_kw}' without matching '{open_kw}'.",
                        line=1,
                    )
                )

        # Check VAR ... END_VAR pairs
        var_starts = len(
            re.findall(
                r"\b(VAR|VAR_INPUT|VAR_OUTPUT|VAR_IN_OUT|VAR_GLOBAL|VAR_TEMP|VAR_EXTERNAL)\b",
                stripped,
                re.IGNORECASE,
            )
        )
        var_ends = len(re.findall(r"\bEND_VAR\b", stripped, re.IGNORECASE))
        if var_starts > var_ends:
            self.issues.append(
                STIssue(
                    severity=IssueSeverity.ERROR,
                    code="ERR_UNCLOSED_VAR",
                    message=f"Unclosed variable declaration: {var_starts} VAR block(s) opened, but only {var_ends} 'END_VAR' found.",
                    line=1,
                )
            )
        elif var_ends > var_starts:
            self.issues.append(
                STIssue(
                    severity=IssueSeverity.ERROR,
                    code="ERR_EXTRA_END_VAR",
                    message="Unexpected 'END_VAR' without matching VAR block.",
                    line=1,
                )
            )

    # ------------------------------------------------------------------------
    # Variable Declaration Parsing
    # ------------------------------------------------------------------------

    def _parse_var_block(
        self,
        block_text: str,
        scope: VarScope,
        is_retain: bool,
        is_constant: bool,
        start_line: int,
    ) -> List[STVariable]:
        """Parses individual variable declarations within a VAR...END_VAR block."""
        variables: List[STVariable] = []
        raw_lines = block_text.splitlines()

        for offset, raw_line in enumerate(raw_lines):
            current_line_no = start_line + offset
            clean = raw_line.strip()
            if not clean:
                continue

            # Strip comments on this line for parsing
            comment = None
            if "(*" in clean and "*)" in clean:
                m = re.search(r"\(\*([\s\S]*?)\*\)", clean)
                if m:
                    comment = m.group(1).strip()
                clean = re.sub(r"\(\*[\s\S]*?\*\)", "", clean).strip()
            elif "//" in clean:
                parts = clean.split("//", 1)
                clean = parts[0].strip()
                comment = parts[1].strip()

            if not clean:
                continue

            # Check for missing semicolon at end of declaration line
            if not clean.endswith(";"):
                self.issues.append(
                    STIssue(
                        severity=IssueSeverity.ERROR,
                        code="ERR_MISSING_SEMICOLON",
                        message=f"Variable declaration missing terminating semicolon: '{raw_line.strip()}'",
                        line=current_line_no,
                    )
                )
                # Continue parsing with synthesized semicolon
                clean += ";"

            decl = clean[:-1].strip()  # remove ';'

            # Check for address binding: Name AT %IX0.0 : TYPE
            address = None
            if " AT " in decl.upper():
                m_at = re.search(r"^(.*?)\s+AT\s+([%A-Za-z0-9_\.]+)\s*:\s*(.*)$", decl, re.IGNORECASE)
                if m_at:
                    names_part = m_at.group(1).strip()
                    address = m_at.group(2).strip()
                    type_part = m_at.group(3).strip()
                else:
                    self.issues.append(
                        STIssue(
                            severity=IssueSeverity.ERROR,
                            code="ERR_VAR_DECLARATION",
                            message=f"Malformed address declaration: '{raw_line.strip()}'",
                            line=current_line_no,
                        )
                    )
                    continue
            else:
                if ":" not in decl:
                    self.issues.append(
                        STIssue(
                            severity=IssueSeverity.ERROR,
                            code="ERR_VAR_DECLARATION",
                            message=f"Missing ':' in variable declaration: '{raw_line.strip()}'",
                            line=current_line_no,
                        )
                    )
                    continue
                parts = decl.split(":", 1)
                names_part = parts[0].strip()
                type_part = parts[1].strip()

            # Parse initial value: TYPE := init_val
            init_val = None
            if ":=" in type_part:
                t_parts = type_part.split(":=", 1)
                var_type_raw = t_parts[0].strip()
                init_val = t_parts[1].strip()
            else:
                var_type_raw = type_part

            # Parse array: ARRAY [1..10] OF INT
            is_array = False
            array_bounds = None
            m_arr = re.search(r"^ARRAY\s*\[\s*([^\]]+)\s*\]\s+OF\s+(.*)$", var_type_raw, re.IGNORECASE)
            if m_arr:
                is_array = True
                array_bounds = m_arr.group(1).strip()
                var_type = m_arr.group(2).strip().upper()
            else:
                var_type = var_type_raw.upper()

            # Normalize STRING(size)
            if var_type.startswith("STRING"):
                norm_type = "STRING"
            else:
                norm_type = var_type

            # Parse comma-separated names
            name_tokens = [n.strip() for n in names_part.split(",") if n.strip()]
            for name in name_tokens:
                if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
                    self.issues.append(
                        STIssue(
                            severity=IssueSeverity.ERROR,
                            code="ERR_INVALID_IDENTIFIER",
                            message=f"Invalid variable identifier '{name}' in declaration.",
                            line=current_line_no,
                        )
                    )
                    continue

                var_obj = STVariable(
                    name=name,
                    data_type=var_type,
                    scope=scope,
                    initial_value=init_val,
                    is_retain=is_retain,
                    is_constant=is_constant,
                    is_array=is_array,
                    array_bounds=array_bounds,
                    address=address,
                    comment=comment,
                    line=current_line_no,
                )
                variables.append(var_obj)

                # Check if type is standard or recognized
                base_type = norm_type.split("(")[0].strip()
                if base_type not in STANDARD_DATA_TYPES and base_type not in STANDARD_FUNCTION_BLOCKS:
                    # Could be user defined FB or UDT, log as INFO
                    self.issues.append(
                        STIssue(
                            severity=IssueSeverity.INFO,
                            code="INFO_CUSTOM_TYPE",
                            message=f"Variable '{name}' declared with custom/FB type '{var_type}'.",
                            line=current_line_no,
                        )
                    )

        return variables

    # ------------------------------------------------------------------------
    # Semicolon and Statement Syntax Checking
    # ------------------------------------------------------------------------

    def _check_statement_semicolons(self, body_text: str, start_line: int) -> None:
        """Checks for missing semicolons on executable statements within the POU body."""
        lines = body_text.splitlines()
        control_openers = ("IF", "ELSIF", "ELSE", "CASE", "FOR", "WHILE", "REPEAT")
        control_closers = ("END_IF", "END_CASE", "END_FOR", "END_WHILE", "UNTIL", "END_REPEAT")

        i = 0
        while i < len(lines):
            line_no = start_line + i
            raw = lines[i].strip()
            i += 1

            if not raw or raw.startswith("//") or raw.startswith("(*") or raw.startswith("/*"):
                continue

            # Strip inline comments
            clean = re.sub(r"\(\*[\s\S]*?\*\)", "", raw)
            clean = re.sub(r"//.*$", "", clean).strip()
            if not clean:
                continue

            upper = clean.upper()

            # Skip control openers
            if any(upper.startswith(op) for op in control_openers):
                # Ensure control block header is well-formed
                if upper.startswith("IF ") or upper == "IF" or upper.startswith("ELSIF ") or upper == "ELSIF":
                    if not re.search(r"\bTHEN\b", upper):
                        combined_upper = upper
                        peek_idx = i
                        while not re.search(r"\bTHEN\b", combined_upper) and peek_idx < len(lines):
                            next_line = lines[peek_idx].strip()
                            next_clean = re.sub(r"\(\*[\s\S]*?\*\)", "", next_line)
                            next_clean = re.sub(r"//.*$", "", next_clean).strip()
                            if not next_clean:
                                peek_idx += 1
                                continue
                            next_upper = next_clean.upper()
                            if any(next_upper.startswith(cl) for cl in control_closers) or any(
                                next_upper.startswith(op)
                                for op in ("IF ", "CASE ", "FOR ", "WHILE ", "REPEAT", "PROGRAM ", "FUNCTION")
                            ):
                                break
                            combined_upper += " " + next_upper
                            peek_idx += 1
                            if re.search(r"\bTHEN\b", next_upper):
                                break
                            if next_clean.endswith(";"):
                                break

                        if re.search(r"\bTHEN\b", combined_upper):
                            i = peek_idx
                        else:
                            op_name = "IF" if upper.startswith("IF") else "ELSIF"
                            self.issues.append(
                                STIssue(
                                    severity=IssueSeverity.ERROR,
                                    code=f"ERR_SYNTAX_{op_name}",
                                    message=f"{op_name} statement missing 'THEN': '{raw}'",
                                    line=line_no,
                                )
                            )
                elif upper.startswith("CASE ") or upper == "CASE":
                    if not re.search(r"\bOF\b", upper):
                        self.issues.append(
                            STIssue(
                                severity=IssueSeverity.ERROR,
                                code="ERR_SYNTAX_CASE",
                                message=f"CASE statement missing 'OF': '{raw}'",
                                line=line_no,
                            )
                        )
                elif upper.startswith("FOR ") or upper == "FOR":
                    if not re.search(r"\bDO\b", upper):
                        self.issues.append(
                            STIssue(
                                severity=IssueSeverity.ERROR,
                                code="ERR_SYNTAX_FOR",
                                message=f"FOR statement missing 'DO': '{raw}'",
                                line=line_no,
                            )
                        )
                elif upper.startswith("WHILE ") or upper == "WHILE":
                    if not re.search(r"\bDO\b", upper):
                        combined_upper = upper
                        peek_idx = i
                        while not re.search(r"\bDO\b", combined_upper) and peek_idx < len(lines):
                            next_line = lines[peek_idx].strip()
                            next_clean = re.sub(r"\(\*[\s\S]*?\*\)", "", next_line)
                            next_clean = re.sub(r"//.*$", "", next_clean).strip()
                            if not next_clean:
                                peek_idx += 1
                                continue
                            next_upper = next_clean.upper()
                            if any(next_upper.startswith(cl) for cl in control_closers) or any(
                                next_upper.startswith(op)
                                for op in ("IF ", "CASE ", "FOR ", "WHILE ", "REPEAT", "PROGRAM ", "FUNCTION")
                            ):
                                break
                            combined_upper += " " + next_upper
                            peek_idx += 1
                            if re.search(r"\bDO\b", next_upper):
                                break
                            if next_clean.endswith(";"):
                                break

                        if re.search(r"\bDO\b", combined_upper):
                            i = peek_idx
                        else:
                            self.issues.append(
                                STIssue(
                                    severity=IssueSeverity.ERROR,
                                    code="ERR_SYNTAX_WHILE",
                                    message=f"WHILE statement missing 'DO': '{raw}'",
                                    line=line_no,
                                )
                            )
                continue

            # CASE branch label, e.g. "10:" or "1, 2, 3:" or "1..5:" or "ELSE"
            if re.match(r"^[0-9A-Za-z_,\.\s]+:\s*$", clean) or clean == "ELSE":
                continue

            # End block markers: END_IF;, END_CASE;, END_FOR;, END_WHILE;
            if any(upper.startswith(cl) for cl in control_closers):
                if not clean.endswith(";"):
                    self.issues.append(
                        STIssue(
                            severity=IssueSeverity.ERROR,
                            code="ERR_MISSING_SEMICOLON",
                            message=f"Missing semicolon at end of '{clean}'",
                            line=line_no,
                        )
                    )
                continue

            # Assignments, calls, RETURN, EXIT
            if ":=" in clean or upper == "RETURN" or upper.startswith("RETURN") or upper == "EXIT" or "(" in clean:
                if not clean.endswith(";"):
                    # Check if this statement continues across subsequent lines
                    # (e.g. multi-line expressions, multi-line function calls)
                    peek_idx = i
                    found_terminator = False
                    interrupted = False
                    combined_statement = clean
                    paren_depth = clean.count("(") - clean.count(")")

                    while peek_idx < len(lines):
                        next_line = lines[peek_idx].strip()
                        next_clean = re.sub(r"\(\*[\s\S]*?\*\)", "", next_line)
                        next_clean = re.sub(r"//.*$", "", next_clean).strip()
                        if not next_clean:
                            peek_idx += 1
                            continue
                        next_upper = next_clean.upper()

                        # Check for hard boundaries that indicate missing semicolon on the previous statement
                        if (
                            any(next_upper.startswith(cl) for cl in control_closers)
                            or any(next_upper.startswith(op) for op in control_openers)
                            or any(next_upper.startswith(kw) for kw in ("PROGRAM", "END_PROGRAM", "FUNCTION", "END_FUNCTION", "VAR", "END_VAR", "RETURN", "EXIT"))
                            or (paren_depth <= 0 and re.match(r"^[0-9A-Za-z_,\.\s]+:\s*$", next_clean))
                            or (paren_depth <= 0 and re.match(r"^[A-Za-z_][A-Za-z0-9_\.\[\]]*\s*:=", next_clean))
                        ):
                            interrupted = True
                            break

                        paren_depth += next_clean.count("(") - next_clean.count(")")
                        combined_statement += " " + next_clean

                        if next_clean.endswith(";") and paren_depth <= 0:
                            found_terminator = True
                            peek_idx += 1
                            break

                        peek_idx += 1

                    if found_terminator and not interrupted:
                        i = peek_idx
                        continue

                    col_idx = len(raw.rstrip()) + 1
                    self.issues.append(
                        STIssue(
                            severity=IssueSeverity.ERROR,
                            code="ERR_MISSING_SEMICOLON",
                            message=f"Statement missing terminating semicolon: '{clean}'",
                            line=line_no,
                            column=col_idx,
                        )
                    )

    # ------------------------------------------------------------------------
    # Undeclared Variables and Type Checking
    # ------------------------------------------------------------------------

    def _check_semantics(self, pou: STPOU, start_line: int) -> None:
        """Validates variable usage, undeclared identifiers, and obvious type mismatches."""
        symbols: Dict[str, STVariable] = {}
        for gv in self.global_variables:
            symbols[gv.name.upper()] = gv
        for lv in pou.variables:
            symbols[lv.name.upper()] = lv

        # If POU is FUNCTION, the function name itself is a valid variable representing return value
        if pou.kind == POUKind.FUNCTION and pou.return_type:
            symbols[pou.name.upper()] = STVariable(
                name=pou.name,
                data_type=pou.return_type,
                scope=VarScope.VAR_OUTPUT,
            )

        body_clean = self.strip_comments(pou.body)
        lines = body_clean.splitlines()

        for offset, raw_line in enumerate(lines):
            line_no = start_line + offset
            line = raw_line.strip()
            if not line:
                continue

            # Check assignments: target := expr;
            if ":=" in line:
                m_assign = re.match(r"^([A-Za-z_%][A-Za-z0-9_\.\[\]]*)\s*:=\s*(.*?);?$", line)
                if m_assign:
                    target_full = m_assign.group(1).strip()
                    expr = m_assign.group(2).strip().rstrip(";")

                    if not target_full.startswith("%"):
                        target_base = re.split(r"[\.\[]", target_full)[0].strip().upper()

                        if target_base not in symbols:
                            col_idx = raw_line.find(target_full) + 1
                            if col_idx <= 0:
                                col_idx = 1
                            self.issues.append(
                                STIssue(
                                    severity=IssueSeverity.ERROR,
                                    code="ERR_UNDECLARED_VAR",
                                    message=f"Assignment to undeclared variable '{target_full}'.",
                                    line=line_no,
                                    column=col_idx,
                                )
                            )
                        else:
                            target_var = symbols[target_base]
                            target_type = target_var.data_type.upper()
                            self._validate_assignment_types(target_full, target_type, expr, line_no)

            # Check undeclared variables in expressions
            clean_for_ids = re.sub(r"'[^']*'", " ", line)
            clean_for_ids = re.sub(r'"[^"]*"', " ", clean_for_ids)
            clean_for_ids = re.sub(r"\b(T|TIME|DATE|D|TOD|DT)#[0-9A-Za-z_\.]+\b", " ", clean_for_ids, flags=re.IGNORECASE)
            clean_for_ids = re.sub(r"\b(16|2|8)#[0-9A-Fa-f_]+\b", " ", clean_for_ids)
            clean_for_ids = re.sub(r"%[A-Za-z0-9_\.]+\b", " ", clean_for_ids)

            candidate_ids = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", clean_for_ids)
            for cid in candidate_ids:
                u_cid = cid.upper()
                if (
                    u_cid in self.KEYWORDS
                    or u_cid in STANDARD_DATA_TYPES
                    or u_cid in STANDARD_FUNCTIONS
                    or u_cid in STANDARD_FUNCTION_BLOCKS
                    or u_cid in ("TRUE", "FALSE")
                ):
                    continue

                # Member access (e.g. FB.Q, don't flag Q as undeclared if preceded by '.')
                if re.search(r"\.\s*" + re.escape(cid) + r"\b", clean_for_ids):
                    continue

                # Function block call named argument (e.g. PT := T#5s, IN := True)
                if re.search(r"\(\s*" + re.escape(cid) + r"\s*:=", clean_for_ids) or re.search(r",\s*" + re.escape(cid) + r"\s*:=", clean_for_ids):
                    continue

                if u_cid not in symbols:
                    col_idx = raw_line.find(cid) + 1
                    if col_idx <= 0:
                        col_idx = 1
                    self.issues.append(
                        STIssue(
                            severity=IssueSeverity.ERROR,
                            code="ERR_UNDECLARED_VAR",
                            message=f"Undeclared variable or identifier '{cid}' used in logic.",
                            line=line_no,
                            column=col_idx,
                        )
                    )

    def _validate_assignment_types(
        self,
        target_name: str,
        target_type: str,
        expr: str,
        line_no: int,
    ) -> None:
        """Checks for blatant type incompatibilities on assignment."""
        clean_expr = expr.strip()

        # Target is BOOL
        if target_type in BOOLEAN_TYPES:
            if re.match(r"^[0-9]+(\.[0-9]+)?$", clean_expr):
                self.issues.append(
                    STIssue(
                        severity=IssueSeverity.ERROR,
                        code="ERR_TYPE_MISMATCH",
                        message=f"Type mismatch: Cannot assign numeric literal '{clean_expr}' directly to BOOL variable '{target_name}'.",
                        line=line_no,
                    )
                )
            elif clean_expr.startswith("'") or clean_expr.startswith('"'):
                self.issues.append(
                    STIssue(
                        severity=IssueSeverity.ERROR,
                        code="ERR_TYPE_MISMATCH",
                        message=f"Type mismatch: Cannot assign STRING literal to BOOL variable '{target_name}'.",
                        line=line_no,
                    )
                )

        # Target is Integer type
        elif target_type in INTEGER_TYPES:
            if re.match(r"^[0-9]+\.[0-9]+$", clean_expr):
                self.issues.append(
                    STIssue(
                        severity=IssueSeverity.ERROR,
                        code="ERR_TYPE_MISMATCH",
                        message=f"Type mismatch: Cannot assign REAL floating-point literal '{clean_expr}' to integer '{target_name}' ({target_type}) without explicit conversion.",
                        line=line_no,
                    )
                )
            elif clean_expr.upper() in ("TRUE", "FALSE"):
                self.issues.append(
                    STIssue(
                        severity=IssueSeverity.ERROR,
                        code="ERR_TYPE_MISMATCH",
                        message=f"Type mismatch: Cannot assign BOOL literal '{clean_expr}' to integer '{target_name}' ({target_type}).",
                        line=line_no,
                    )
                )
            elif clean_expr.startswith("'") or clean_expr.startswith('"'):
                self.issues.append(
                    STIssue(
                        severity=IssueSeverity.ERROR,
                        code="ERR_TYPE_MISMATCH",
                        message=f"Type mismatch: Cannot assign STRING literal to integer variable '{target_name}'.",
                        line=line_no,
                    )
                )

        # Target is REAL / LREAL
        elif target_type in REAL_TYPES:
            if clean_expr.upper() in ("TRUE", "FALSE"):
                self.issues.append(
                    STIssue(
                        severity=IssueSeverity.ERROR,
                        code="ERR_TYPE_MISMATCH",
                        message=f"Type mismatch: Cannot assign BOOL literal '{clean_expr}' to floating-point '{target_name}' ({target_type}).",
                        line=line_no,
                    )
                )
            elif clean_expr.startswith("'") or clean_expr.startswith('"'):
                self.issues.append(
                    STIssue(
                        severity=IssueSeverity.ERROR,
                        code="ERR_TYPE_MISMATCH",
                        message=f"Type mismatch: Cannot assign STRING literal to REAL variable '{target_name}'.",
                        line=line_no,
                    )
                )

        # Target is STRING
        elif target_type in STRING_TYPES:
            if re.match(r"^[0-9]+(\.[0-9]+)?$", clean_expr) or clean_expr.upper() in ("TRUE", "FALSE"):
                self.issues.append(
                    STIssue(
                        severity=IssueSeverity.ERROR,
                        code="ERR_TYPE_MISMATCH",
                        message=f"Type mismatch: Cannot assign non-string literal '{clean_expr}' to STRING variable '{target_name}'.",
                        line=line_no,
                    )
                )

        # Target is TIME
        elif target_type in TIME_TYPES:
            if not (clean_expr.upper().startswith("T#") or clean_expr.upper().startswith("TIME#")):
                if re.match(r"^[0-9]+(\.[0-9]+)?$", clean_expr) or clean_expr.upper() in ("TRUE", "FALSE"):
                    self.issues.append(
                        STIssue(
                            severity=IssueSeverity.ERROR,
                            code="ERR_TYPE_MISMATCH",
                            message=f"Type mismatch: Literal '{clean_expr}' assigned to TIME variable '{target_name}' must use 'T#' or 'TIME#' prefix (e.g. T#5s).",
                            line=line_no,
                        )
                    )

    # ------------------------------------------------------------------------
    # Full Parse Pipeline
    # ------------------------------------------------------------------------

    def parse(self) -> STValidationResult:
        """Executes full parsing, validation, and AST construction."""
        # 1. First enforce strict prohibition of Ladder logic
        if self._check_forbidden_ladder():
            return STValidationResult(is_valid=False, issues=self.issues)

        # 2. Check block and comment pairing
        self._check_block_pairing(self.raw_code)

        self.clean_code = self.strip_comments(self.raw_code)
        if not self.clean_code.strip():
            self.issues.append(
                STIssue(
                    severity=IssueSeverity.ERROR,
                    code="ERR_EMPTY_SOURCE",
                    message="Structured Text source code is empty or contains only comments/whitespace.",
                    line=1,
                )
            )
            return STValidationResult(
                is_valid=False,
                issues=self.issues,
                pous=self.pous,
                global_variables=self.global_variables,
            )

        # 3. Parse VAR_GLOBAL blocks outside of POUs if any
        global_pattern = re.compile(
            r"\b(VAR_GLOBAL)\b(?:\s+(RETAIN|CONSTANT))?([\s\S]*?)\bEND_VAR\b",
            re.IGNORECASE,
        )
        for match in global_pattern.finditer(self.clean_code):
            scope = VarScope.VAR_GLOBAL
            modifier = match.group(2).upper() if match.group(2) else ""
            is_retain = "RETAIN" in modifier
            is_constant = "CONSTANT" in modifier
            content = match.group(3)
            start_line = self.clean_code[:match.start()].count("\n") + 1
            g_vars = self._parse_var_block(content, scope, is_retain, is_constant, start_line)
            self.global_variables.extend(g_vars)

        # 4. Parse POUs: PROGRAM, FUNCTION_BLOCK, FUNCTION
        pou_pattern = re.compile(
            r"\b(PROGRAM|FUNCTION_BLOCK|FUNCTION)\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s*:\s*([A-Za-z_][A-Za-z0-9_]*))?\b([\s\S]*?)\b(END_PROGRAM|END_FUNCTION_BLOCK|END_FUNCTION)\b",
            re.IGNORECASE,
        )

        found_pous = list(pou_pattern.finditer(self.clean_code))

        if not found_pous:
            # Check if this is a raw ST statement snippet / body
            var_match = re.search(r"\b(VAR|VAR_INPUT|VAR_OUTPUT)\b", self.clean_code, re.IGNORECASE)
            assign_match = ":=" in self.clean_code
            if var_match or assign_match:
                anon_pou = STPOU(kind=POUKind.PROGRAM, name="AnonymousST", line=1)
                self._extract_pou_contents(anon_pou, self.clean_code, 1)
                self.pous.append(anon_pou)
            else:
                self.issues.append(
                    STIssue(
                        severity=IssueSeverity.ERROR,
                        code="ERR_NO_POU_FOUND",
                        message="No PROGRAM, FUNCTION_BLOCK, or FUNCTION definitions found in Structured Text.",
                        line=1,
                    )
                )
        else:
            for match in found_pous:
                kind_str = match.group(1).upper()
                name = match.group(2)
                return_type = match.group(3)
                inner_content = match.group(4)
                closer = match.group(5).upper()

                pou_line = self.clean_code[:match.start()].count("\n") + 1

                # Verify matching closer
                expected_closer = f"END_{kind_str}"
                if closer != expected_closer:
                    self.issues.append(
                        STIssue(
                            severity=IssueSeverity.ERROR,
                            code="ERR_MISMATCHED_POU_CLOSER",
                            message=f"POU '{name}' started with '{kind_str}' but closed with '{closer}' (expected '{expected_closer}').",
                            line=pou_line,
                        )
                    )

                pou = STPOU(
                    kind=POUKind(kind_str),
                    name=name,
                    return_type=return_type,
                    line=pou_line,
                )
                self._extract_pou_contents(pou, inner_content, pou_line)
                self.pous.append(pou)

        is_valid = len([i for i in self.issues if i.severity == IssueSeverity.ERROR]) == 0

        return STValidationResult(
            is_valid=is_valid,
            issues=self.issues,
            pous=self.pous,
            global_variables=self.global_variables,
        )

    def _extract_pou_contents(self, pou: STPOU, inner_content: str, pou_start_line: int) -> None:
        """Extracts VAR blocks and body code from within a POU."""
        var_block_pattern = re.compile(
            r"\b(VAR_INPUT|VAR_OUTPUT|VAR_IN_OUT|VAR_GLOBAL|VAR_TEMP|VAR_EXTERNAL|VAR)\b(?:\s+(RETAIN|CONSTANT))?([\s\S]*?)\bEND_VAR\b",
            re.IGNORECASE,
        )

        for match in var_block_pattern.finditer(inner_content):
            scope_str = match.group(1).upper()
            scope = VarScope(scope_str)
            modifier = match.group(2).upper() if match.group(2) else ""
            is_retain = "RETAIN" in modifier
            is_constant = "CONSTANT" in modifier
            block_content = match.group(3)

            block_start = pou_start_line + inner_content[:match.start()].count("\n")
            parsed_vars = self._parse_var_block(
                block_content, scope, is_retain, is_constant, block_start
            )
            pou.variables.extend(parsed_vars)

        body_text = var_block_pattern.sub("", inner_content).strip()
        pou.body = body_text

        char_pos = inner_content.find(body_text) if body_text else 0
        body_start_line = pou_start_line + inner_content[:char_pos].count("\n")
        self._check_statement_semicolons(pou.body, body_start_line)
        self._check_semantics(pou, body_start_line)

    @classmethod
    def validate(cls, code: str) -> STValidationResult:
        """Convenience validation entry point."""
        parser = cls(code)
        return parser.parse()
