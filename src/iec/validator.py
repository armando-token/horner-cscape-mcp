"""IEC 61131-3 Structured Text (ST) Validator for Horner Cscape.

Enforces pure Structured Text grammar, verifies POU structure,
validates variable declarations across all IEC scopes (VAR, VAR_INPUT, VAR_OUTPUT,
VAR_IN_OUT, VAR_GLOBAL, VAR_TEMP, VAR_EXTERNAL, VAR_STAT, VAR_CONFIG),
detects and rejects ladder logic artifacts, checks block nesting consistency,
and executes full AST validation in pure Python.
"""

import re
from typing import Any, Dict, List, Optional, Tuple, Union
from .parser import Parser, ParseError
from ..security.exceptions import UnauthorizedDownloadError

ID_CONTROLLER_DOWNLOAD: int = 32827
ID_PROGRAM_DOWNLOADOPTIONS: int = 33149


class IECValidator:
    """Validates IEC 61131-3 Structured Text source code."""

    ID_CONTROLLER_DOWNLOAD: int = 32827
    ID_PROGRAM_DOWNLOADOPTIONS: int = 33149

    STANDARD_TYPES = {
        "BOOL", "BYTE", "WORD", "DWORD", "LWORD",
        "SINT", "USINT", "INT", "UINT", "DINT", "UDINT", "LINT", "ULINT",
        "REAL", "LREAL",
        "TIME", "DATE", "TIME_OF_DAY", "TOD", "DATE_AND_TIME", "DT",
        "STRING", "WSTRING",
    }

    VAR_SCOPES = [
        "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT",
        "VAR_GLOBAL", "VAR_TEMP", "VAR_EXTERNAL",
        "VAR_STAT", "VAR_CONFIG", "VAR"
    ]

    LADDER_PATTERNS = [
        r"---\[\s*\]---",          # Normally open contact
        r"---\[\s*/\s*\]---",      # Normally closed contact
        r"---\(\s*\)---",          # Normal coil
        r"---\(\s*[SLR]\s*\)---",  # Set / Reset / Latch coil
        r"---\s*[SLRU]\s*---",     # Set / Reset coil shorthand (---S---, ---R---)
        r"\bRUNG\b",               # Rung marker
        r"\bEND_RUNG\b",           # End rung marker
        r"\bLADDER\b",             # Ladder marker
        r"\bNETWORK\s+\d+",        # Network section (ladder)
        r"\bCONTACT\b",            # Ladder contact
        r"\bCOIL\b",               # Ladder coil
        r"\b(XIC|XIO|OTE|OTL|OTU|OSR|OSF)\s*\(", # Ladder instruction mnemonics
    ]

    FORBIDDEN_HARDWARE_PATTERNS = [
        r"\bPGMUpdateUtility\b",
        r"\bDfuSeCommand\b",
        r"\bSTMFlashLoader\b",
        r"\bWinJTAG\b",
        r"\bDIRECT_IO\b",
        r"\bCAN_SEND\b",
        r"\bCAN_RECEIVE\b",
        r"\bSERIAL_PORT_WRITE\b",
        r"\bFLASH_ERASE\b",
        r"\bFLASH_WRITE\b",
        r"\bCONTROLLER_DOWNLOAD\b",
    ]

    @classmethod
    def check_download_lockout(cls, command_id: Union[int, str]) -> None:
        """Unconditionally raises UnauthorizedDownloadError if command matches download commands."""
        cmd_str = str(command_id).strip().upper()
        if (
            command_id in (cls.ID_CONTROLLER_DOWNLOAD, cls.ID_PROGRAM_DOWNLOADOPTIONS, 32827, 33149)
            or cmd_str in ("32827", "33149", "ID_CONTROLLER_DOWNLOAD", "ID_PROGRAM_DOWNLOADOPTIONS")
            or "DOWNLOAD" in cmd_str
        ):
            raise UnauthorizedDownloadError(
                f"Hardware lockout: Physical controller download command '{command_id}' (ID_CONTROLLER_DOWNLOAD = 32827 / ID_PROGRAM_DOWNLOADOPTIONS = 33149) is strictly blocked."
            )

    @classmethod
    def check_hardware_safety(cls, code: str) -> List[str]:
        """Detects and rejects forbidden physical hardware and download operations."""
        errors = []
        for pattern in cls.FORBIDDEN_HARDWARE_PATTERNS:
            match = re.search(pattern, code, re.IGNORECASE)
            if match:
                line_no = code[:match.start()].count("\n") + 1
                col_no = match.start() - max(0, code.rfind("\n", 0, match.start()))
                errors.append(
                    f"ERR_HARDWARE_LOCKOUT: Safety violation at line {line_no}, col {col_no}: Forbidden hardware operation '{match.group(0)}' detected."
                )
        return errors

    @classmethod
    def strip_comments(cls, code: str) -> str:
        """Removes IEC 61131-3 comments (* ... *), // ..., and /* ... */ while preserving newlines."""
        def replacer_iec(match):
            return "\n" * match.group(0).count("\n")

        code = re.sub(r"\(\*[\s\S]*?\*\)", replacer_iec, code)
        code = re.sub(r"/\*[\s\S]*?\*/", replacer_iec, code)
        code = re.sub(r"//.*$", "", code, flags=re.MULTILINE)
        return code

    @classmethod
    def check_ladder_artifacts(cls, code: str) -> List[str]:
        """Detects and rejects Advanced Ladder logic artifacts to enforce pure Structured Text."""
        errors = []
        clean = cls.strip_comments(code)
        for pattern in cls.LADDER_PATTERNS:
            match = re.search(pattern, clean, re.IGNORECASE)
            if match:
                line_no = clean[:match.start()].count("\n") + 1
                col_no = match.start() - max(0, clean.rfind("\n", 0, match.start()))
                errors.append(
                    f"ERR_LADDER_FORBIDDEN: Ladder logic artifact detected at line {line_no}, col {col_no} matching pattern '{pattern}'. Only pure IEC 61131-3 Structured Text is permitted."
                )
        return errors

    @classmethod
    def parse_variables(cls, code: str) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Extracts variable declarations across all VAR ... END_VAR blocks."""
        variables: List[Dict[str, Any]] = []
        errors: List[str] = []
        clean_code = cls.strip_comments(code)

        var_block_pattern = re.compile(
            r"\b(VAR_INPUT|VAR_OUTPUT|VAR_IN_OUT|VAR_GLOBAL|VAR_TEMP|VAR_EXTERNAL|VAR_STAT|VAR_CONFIG|VAR)\b(?:\s+(RETAIN|NON_RETAIN|CONSTANT))?([\s\S]*?)\bEND_VAR\b",
            re.IGNORECASE,
        )

        for match in var_block_pattern.finditer(clean_code):
            scope = match.group(1).upper()
            modifier = match.group(2).upper() if match.group(2) else None
            block_content = match.group(3)
            block_start_pos = match.start(3)

            for raw_decl in block_content.split(";"):
                line_str = raw_decl.strip()
                if not line_str:
                    continue

                line_pos = block_start_pos + block_content.find(raw_decl)
                line_no = clean_code[:line_pos].count("\n") + 1

                if ":" not in line_str:
                    errors.append(f"Invalid variable declaration at line {line_no} in {scope}: '{line_str}' (missing ':')")
                    continue

                parts = line_str.split(":", 1)
                names_part = parts[0].strip()
                type_part = parts[1].strip()

                address = None
                if re.search(r"\bAT\b", names_part, re.IGNORECASE):
                    at_parts = re.split(r"\bAT\b", names_part, flags=re.IGNORECASE)
                    names_part = at_parts[0].strip()
                    address = at_parts[1].strip()

                init_val = None
                if ":=" in type_part:
                    t_parts = type_part.split(":=", 1)
                    var_type = t_parts[0].strip()
                    init_val = t_parts[1].strip()
                else:
                    var_type = type_part

                var_names = [n.strip() for n in names_part.split(",") if n.strip()]
                for v_name in var_names:
                    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", v_name):
                        errors.append(f"Invalid variable identifier '{v_name}' at line {line_no} in {scope}.")
                        continue

                    # Validate Horner OCS register bounds and memory footprint
                    if address:
                        try:
                            from ..cscape.variables import HornerRegister, IEC_TYPE_WORD_SIZE, HORNER_REGISTER_LIMITS
                            reg = HornerRegister.parse(address)
                            base_type_upper = var_type.strip().upper()
                            word_span = IEC_TYPE_WORD_SIZE.get(base_type_upper, 1)
                            if reg.prefix in HORNER_REGISTER_LIMITS and word_span > 1:
                                min_idx, max_idx = HORNER_REGISTER_LIMITS[reg.prefix]
                                end_idx = reg.index + word_span - 1
                                if end_idx > max_idx:
                                    errors.append(
                                        f"ERR_REGISTER_OUT_OF_BOUNDS: Variable '{v_name}' of type '{var_type}' at line {line_no} spans {reg.raw}..{reg.prefix}{end_idx}, exceeding {reg.prefix} maximum limit {max_idx}."
                                    )
                        except ValueError as ve:
                            errors.append(
                                f"ERR_REGISTER_OUT_OF_BOUNDS: Invalid register address '{address}' for variable '{v_name}' at line {line_no}: {ve}"
                            )

                    variables.append({
                        "name": v_name,
                        "type": var_type,
                        "scope": scope,
                        "modifier": modifier,
                        "address": address,
                        "initial_value": init_val,
                    })

        return variables, errors

    @classmethod
    def check_block_nesting(cls, code: str) -> List[str]:
        """Verifies that control structures (IF, CASE, FOR, WHILE, REPEAT) are properly closed."""
        errors = []
        clean = cls.strip_comments(code)

        matches = list(re.finditer(
            r"\b(IF|END_IF|CASE|END_CASE|FOR|END_FOR|WHILE|END_WHILE|REPEAT|UNTIL|END_REPEAT|PROGRAM|END_PROGRAM|FUNCTION_BLOCK|END_FUNCTION_BLOCK|FUNCTION|END_FUNCTION|TYPE|END_TYPE|STRUCT|END_STRUCT)\b",
            clean,
            re.IGNORECASE,
        ))

        stack: List[Tuple[str, int]] = []
        pairs = {
            "END_IF": "IF",
            "END_CASE": "CASE",
            "END_FOR": "FOR",
            "END_WHILE": "WHILE",
            "UNTIL": "REPEAT",
            "END_REPEAT": "REPEAT",
            "END_PROGRAM": "PROGRAM",
            "END_FUNCTION_BLOCK": "FUNCTION_BLOCK",
            "END_FUNCTION": "FUNCTION",
            "END_TYPE": "TYPE",
            "END_STRUCT": "STRUCT",
        }

        openers = {"IF", "CASE", "FOR", "WHILE", "REPEAT", "PROGRAM", "FUNCTION_BLOCK", "FUNCTION", "TYPE", "STRUCT"}

        for m in matches:
            kw = m.group(1)
            line_no = clean[:m.start()].count("\n") + 1
            col_no = m.start() - max(0, clean.rfind("\n", 0, m.start()))
            ukw = kw.upper()
            if ukw in openers:
                stack.append((ukw, line_no, col_no))
            elif ukw in pairs:
                expected = pairs[ukw]
                if not stack:
                    errors.append(f"Unexpected '{ukw}' at line {line_no}, col {col_no} without matching '{expected}'.")
                else:
                    actual, open_line, open_col = stack[-1]
                    if actual == expected:
                        stack.pop()
                    elif ukw == "END_REPEAT" and actual != "REPEAT":
                        pass
                    else:
                        actual, open_line, open_col = stack.pop()
                        errors.append(f"Mismatched closing block at line {line_no}, col {col_no}: got '{ukw}', expected closing for '{actual}' (opened at line {open_line}, col {open_col}).")

        while stack:
            unclosed, open_line, open_col = stack.pop()
            errors.append(f"ERR_UNCLOSED_{unclosed}: Unclosed '{unclosed}' block (opened at line {open_line}, col {open_col}) missing terminating keyword.")

        return errors

    @classmethod
    def validate(cls, code: str) -> Dict[str, Any]:
        """Performs full validation of IEC 61131-3 Structured Text code."""
        if not code or not code.strip():
            return {
                "valid": False,
                "pou_name": "",
                "pou_type": "UNKNOWN",
                "return_type": None,
                "variables": [],
                "errors": ["Source code is empty."],
                "warnings": [],
                "metrics": {"total_lines": 0, "code_lines": 0, "comment_lines": 0, "variable_count": 0},
            }

        raw_lines = code.splitlines()
        total_lines = len(raw_lines)
        comment_lines = sum(1 for line in raw_lines if line.strip().startswith(("//", "(*", "/*", "*")))
        code_lines = total_lines - comment_lines

        errors: List[str] = []
        warnings: List[str] = []

        # 1. Check for forbidden ladder logic
        ladder_errors = cls.check_ladder_artifacts(code)
        errors.extend(ladder_errors)

        # 2. Check for forbidden physical hardware and download operations
        hardware_errors = cls.check_hardware_safety(code)
        errors.extend(hardware_errors)

        # 3. Check block nesting
        nesting_errors = cls.check_block_nesting(code)
        errors.extend(nesting_errors)

        # 4. Detect POU type and name
        pou_type = "STATEMENT_LIST"
        pou_name = "Anonymous"
        return_type = None

        prog_match = re.search(r"\bPROGRAM\s+([a-zA-Z_][a-zA-Z0-9_]*)\b", code, re.IGNORECASE)
        fb_match = re.search(r"\bFUNCTION_BLOCK\s+([a-zA-Z_][a-zA-Z0-9_]*)\b", code, re.IGNORECASE)
        fn_match = re.search(r"\bFUNCTION\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*([a-zA-Z0-9_]+)\b", code, re.IGNORECASE)
        type_match = re.search(r"\bTYPE\b", code, re.IGNORECASE)

        if prog_match:
            pou_type = "PROGRAM"
            pou_name = prog_match.group(1)
        elif fb_match:
            pou_type = "FUNCTION_BLOCK"
            pou_name = fb_match.group(1)
        elif fn_match:
            pou_type = "FUNCTION"
            pou_name = fn_match.group(1)
            return_type = fn_match.group(2).upper()
        elif type_match:
            pou_type = "TYPE"
            pou_name = "UserTypes"
        else:
            warnings.append("No explicit PROGRAM, FUNCTION_BLOCK, or FUNCTION declaration found; treated as raw statement sequence.")

        # 5. Parse variables
        variables, var_errors = cls.parse_variables(code)
        errors.extend(var_errors)

        # 6. Check variable types against known standard types or custom identifiers
        for v in variables:
            base_type = v["type"].split("[")[0].strip().upper()
            if base_type not in cls.STANDARD_TYPES and not re.match(r"^[A-Z_][A-Z0-9_]*$", base_type):
                warnings.append(f"Variable '{v['name']}' uses non-standard or user-defined type '{v['type']}'.")

        # 7. Full AST syntax validation via pure-Python IEC Recursive Descent Parser
        try:
            parser = Parser.from_source(code)
            parser.parse()
        except ParseError as pe:
            err_msg = str(pe)
            if not any(err_msg in e for e in errors):
                errors.append(err_msg)
        except Exception as ex:
            if not any(str(ex) in e for e in errors):
                errors.append(f"Syntax parsing exception: {str(ex)}")

        # 8. Semantic and undeclared variable validation via STParser
        try:
            from .st_parser import STParser, IssueSeverity
            st_result = STParser.validate(code)
            for issue in st_result.issues:
                if issue.severity == IssueSeverity.ERROR:
                    if pou_type == "TYPE" and issue.code == "ERR_NO_POU_FOUND":
                        continue
                    msg = f"{issue.code} at line {issue.line}, col {issue.column}: {issue.message}"
                    if not any(issue.message in e for e in errors):
                        errors.append(msg)
                elif issue.severity == IssueSeverity.WARNING:
                    if not any(issue.message in w for w in warnings):
                        warnings.append(f"Line {issue.line}, col {issue.column}: {issue.message}")
        except Exception as ex:
            errors.append(f"Semantic parser error: {ex}")

        # 9. Honest AST-derived metrics
        ast_metrics = {
            "ast_statement_count": 0,
            "ast_variable_count": len(variables),
            "ast_expression_count": 0,
            "source_bytes_total": len(code.encode("utf-8")),
        }
        try:
            from ..cscape.compilation import compute_honest_ast_metrics
            ast_metrics = compute_honest_ast_metrics(code)
        except Exception:
            pass

        valid = len(errors) == 0

        return {
            "valid": valid,
            "pou_name": pou_name,
            "pou_type": pou_type,
            "return_type": return_type,
            "variables": variables,
            "errors": errors,
            "warnings": warnings,
            "metrics": {
                "total_lines": total_lines,
                "code_lines": code_lines,
                "comment_lines": comment_lines,
                "variable_count": len(variables),
                "ast_statement_count": ast_metrics.get("ast_statement_count", 0),
                "ast_variable_count": ast_metrics.get("ast_variable_count", len(variables)),
                "ast_expression_count": ast_metrics.get("ast_expression_count", 0),
                "source_bytes_total": ast_metrics.get("source_bytes_total", len(code.encode("utf-8"))),
                "estimated_ast_footprint": ast_metrics,
            },
        }
