"""Horner Cscape 10.2 Compiler Diagnostics & Error Parsing Engine.

Provides structured parsing of Cscape build outputs, compiler error logs,
and AST validation errors into CompilerDiagnostic objects.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


@dataclass
class CompilerDiagnostic:
    """Represents a single compiler error, warning, or informational message."""

    level: str  # 'ERROR', 'WARNING', 'INFO'
    message: str
    line: Optional[int] = None
    column: Optional[int] = None
    file_path: Optional[str] = None
    pou_name: Optional[str] = None
    error_code: Optional[str] = None
    subsystem: Optional[str] = None  # e.g., 'IEC_ST', 'HMI_GRAPHICS', 'COMPILER'
    screen_name: Optional[str] = None
    x_coord: Optional[int] = None
    y_coord: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "level": self.level,
            "message": self.message,
            "line": self.line,
            "column": self.column,
            "file_path": self.file_path,
            "pou_name": self.pou_name,
            "error_code": self.error_code,
        }
        if self.subsystem:
            d["subsystem"] = self.subsystem
        if self.screen_name:
            d["screen_name"] = self.screen_name
        if self.x_coord is not None and self.y_coord is not None:
            d["coordinates"] = {"x": self.x_coord, "y": self.y_coord}
        if self.level.upper() == "ERROR":
            fname = Path(self.file_path).name if self.file_path else (f"{self.pou_name}.st" if self.pou_name else "Unknown.st")
            d["failure_location"] = {
                "file_path": fname,
                "full_path": self.file_path,
                "line": self.line or 1,
                "column": self.column or 1,
                "error_code": self.error_code or "ST_SYNTAX_ERROR",
                "severity": "ERROR",
                "message": self.message,
            }
        return d


@dataclass
class CleanBuildProof:
    """Encapsulates cryptographic and structural proof of a 0-error clean build."""

    is_clean: bool
    error_count: int
    warning_count: int
    status_text: str
    proof_lines: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_clean": self.is_clean,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "status_text": self.status_text,
            "proof_lines": self.proof_lines,
        }


class CscapeLogParser:
    """Parses Cscape 10.2 and Straton K5 build logs and error strings."""

    # 1. Matches prefix location format:
    #    Line 8 Col 21: error: msg
    #    Line 8, Col 21: error K51001: msg
    #    (Line 8 Col 21): error: msg
    PATTERN_LINE_COL_FIRST = re.compile(
        r"^(?:(?:Line\s*(?P<line>\d+)(?:,\s*|\s+)(?:Col\s*(?P<col>\d+))?)|(?:\((?:Line\s*)?(?P<line2>\d+)(?:,\s*(?:Col\s*)?(?P<col2>\d+)|\s+Col\s+(?P<col3>\d+))?\)))\s*:\s*(?P<level>error|warning|info)\s*(?:\[?(?P<code>K5\d+|\w+)\]?)?:\s*(?P<msg>.+)$",
        re.IGNORECASE,
    )

    # 2. Matches generic bracketed or line-based format:
    #    ERROR [ST001]: Line 15: msg
    #    ERROR [ST001]: Line 8 Col 21: msg
    #    ERROR: Line 8: msg
    PATTERN_GENERIC_LINE = re.compile(
        r"^(?P<level>ERROR|WARNING|INFO)\s*(?:\[(?P<code>\w+)\])?:\s*(?:(?:Line\s*(?P<line>\d+)(?:,\s*Col\s*(?P<col>\d+)|\s+Col\s*(?P<col2>\d+))?):\s*)?(?P<msg>.+)$",
        re.IGNORECASE,
    )

    # 3. Matches Cscape/Straton standard format with file path:
    #    file(line,col): level [code]: msg
    #    or file(line): level [code]: msg
    #    or file(Line 8 Col 21): level [code]: msg
    #    Note: negative lookahead prevents 'Line X...' or 'ERROR...' from matching as file
    PATTERN_CSCAPE_LOCATION = re.compile(
        r"^(?!(?:Line\s*\d+|ERROR|WARNING|INFO) )(?P<file>(?:[a-zA-Z]:[\\/])?[^:()]+?)(?:\((?:Line\s*)?(?P<line>\d+)(?:,\s*(?:Col\s*)?(?P<col>\d+)|\s+Col\s+(?P<col2>\d+))?\))?:\s*(?P<level>error|warning|info)\s*(?P<code>K5\d+|\w+)?:\s*(?P<msg>.+)$",
        re.IGNORECASE,
    )

    # 4. Matches native Cscape ST compiler error:
    #    STBlock1: (1): PROGRAM: New statement expected
    #    STBlock1: (7): Kp: Unknown identifier
    PATTERN_CSCAPE_ST_LINE = re.compile(
        r"^(?P<pou>[\w\.]+):\s*\((?P<line>\d+)\):\s*(?P<msg>.+)$"
    )

    # 5. Matches native Cscape HMI graphics fatal compile error:
    #    Fatal: Data Source - Invalid I/O assignment.Screen 1 at ( 24 , 12 )
    PATTERN_CSCAPE_HMI_FATAL = re.compile(
        r"^Fatal:\s*(?P<msg>.+?)\.(?P<screen>Screen\s*\d+)\s+at\s*\(\s*(?P<x>\d+)\s*,\s*(?P<y>\d+)\s*\)",
        re.IGNORECASE,
    )

    # 6. Matches native Cscape HMI graphics warning:
    #    Warn : Screen set as first screen is empty.Screen 1
    PATTERN_CSCAPE_HMI_WARN = re.compile(
        r"^Warn\s*:\s*(?P<msg>.+?)(?:\.(?P<screen>Screen\s*\d+))?$",
        re.IGNORECASE,
    )

    # Patterns for clean build verification
    PATTERN_COMPILE_ACTIVITY = re.compile(
        r"(?:compil(?:ing|e|ation\s+succeeded)|clean\s+build|build\s+result|parsed\s+and\s+validated|\.st|\.csp|\.cpj|statements:|estimated\s+ast)",
        re.IGNORECASE,
    )
    PATTERN_CLEAN_BUILD_SUMMARY = re.compile(
        r"(?:0\s+errors?,\s*0\s+warnings?|0\s+error\(s\),\s*0\s+warning\(s\)|Errors:\s*0,\s*Warnings:\s*0|No\s+errors?\s+(?:detected|found))",
        re.IGNORECASE,
    )
    PATTERN_SUCCESS_RESULT = re.compile(
        r"(?:Build\s+Result:\s*SUCCESS|Compilation\s+succeeded)",
        re.IGNORECASE,
    )
    PATTERN_FAILED_RESULT = re.compile(
        r"(?:Build\s+Result:\s*FAILED|Compilation\s+failed|FAIL-CLOSED)",
        re.IGNORECASE,
    )
    PATTERN_SUMMARY_ERRORS = re.compile(
        r"(?:Errors?:\s*(\d+)|(\d+)\s+error\(?s?\)?|Error Count:\s*(\d+))",
        re.IGNORECASE,
    )
    PATTERN_SUMMARY_WARNINGS = re.compile(
        r"(?:Warnings?:\s*(\d+)|(\d+)\s+warning\(?s?\)?|Warning Count:\s*(\d+))",
        re.IGNORECASE,
    )

    @classmethod
    def parse_log(cls, raw_log: str, default_pou: Optional[str] = None) -> List[CompilerDiagnostic]:
        """Parses raw text log lines into structured CompilerDiagnostic instances."""
        if not raw_log or not isinstance(raw_log, str):
            return []
        diagnostics: List[CompilerDiagnostic] = []
        for line in raw_log.splitlines():
            line_str = line.strip()
            if not line_str or line_str.startswith("---") or line_str.startswith("==="):
                continue

            # Check Pattern 1: Line X Col Y: level: msg (evaluated first to avoid 'Line 8' as filename)
            m1 = cls.PATTERN_LINE_COL_FIRST.match(line_str)
            if m1:
                level_str = m1.group("level").upper()
                line_val = m1.group("line") or m1.group("line2")
                line_no = int(line_val) if line_val else None
                col_val = m1.group("col") or m1.group("col2") or m1.group("col3")
                col_no = int(col_val) if col_val else None
                code = m1.group("code")
                msg = m1.group("msg").strip()
                diagnostics.append(CompilerDiagnostic(
                    level=level_str,
                    message=msg,
                    line=line_no,
                    column=col_no,
                    pou_name=default_pou,
                    error_code=code,
                ))
                continue

            # Check Pattern 2: Generic ERROR [code]: Line X: msg
            m2 = cls.PATTERN_GENERIC_LINE.match(line_str)
            if m2:
                level_str = m2.group("level").upper()
                line_no = int(m2.group("line")) if m2.group("line") else None
                col_val = m2.group("col") or m2.group("col2")
                col_no = int(col_val) if col_val else None
                code = m2.group("code")
                msg = m2.group("msg").strip()
                diagnostics.append(CompilerDiagnostic(
                    level=level_str,
                    message=msg,
                    line=line_no,
                    column=col_no,
                    pou_name=default_pou,
                    error_code=code,
                ))
                continue

            # Check Pattern 3: Standard Cscape file(line,col): level: msg
            m3 = cls.PATTERN_CSCAPE_LOCATION.match(line_str)
            if m3:
                level_str = m3.group("level").upper()
                line_no = int(m3.group("line")) if m3.group("line") else None
                col_val = m3.group("col") or m3.group("col2")
                col_no = int(col_val) if col_val else None
                code = m3.group("code")
                msg = m3.group("msg").strip()
                fpath = m3.group("file").strip()
                diagnostics.append(CompilerDiagnostic(
                    level=level_str,
                    message=msg,
                    line=line_no,
                    column=col_no,
                    file_path=fpath,
                    pou_name=Path(fpath).stem if fpath else default_pou,
                    error_code=code,
                ))
                continue

            # Check Pattern 4: Native Cscape HMI Fatal error:
            # Fatal: Data Source - Invalid I/O assignment.Screen 1 at ( 24 , 12 )
            m_hmi_f = cls.PATTERN_CSCAPE_HMI_FATAL.match(line_str)
            if m_hmi_f:
                msg = m_hmi_f.group("msg").strip()
                screen = m_hmi_f.group("screen").strip()
                x_coord = int(m_hmi_f.group("x"))
                y_coord = int(m_hmi_f.group("y"))
                diagnostics.append(CompilerDiagnostic(
                    level="ERROR",
                    message=f"Fatal: {msg}.{screen} at ( {x_coord} , {y_coord} )",
                    file_path=f"{screen}.screen",
                    pou_name=screen,
                    subsystem="HMI_GRAPHICS",
                    screen_name=screen,
                    x_coord=x_coord,
                    y_coord=y_coord,
                    error_code="ERR_HMI_IO_ASSIGNMENT",
                ))
                continue

            # Check Pattern 5: Native Cscape HMI Warning:
            # Warn : Screen set as first screen is empty.Screen 1
            m_hmi_w = cls.PATTERN_CSCAPE_HMI_WARN.match(line_str)
            if m_hmi_w:
                msg = m_hmi_w.group("msg").strip()
                screen = m_hmi_w.group("screen")
                screen_str = screen.strip() if screen else None
                diagnostics.append(CompilerDiagnostic(
                    level="WARNING",
                    message=line_str,
                    file_path=f"{screen_str}.screen" if screen_str else None,
                    pou_name=screen_str,
                    subsystem="HMI_GRAPHICS",
                    screen_name=screen_str,
                    error_code="WARN_HMI_SCREEN_EMPTY" if "empty" in msg.lower() else "WARN_HMI",
                ))
                continue

            # Check Pattern 6: Native Cscape ST POU syntax/compile error:
            # STBlock1: (1): PROGRAM: New statement expected
            m_st = cls.PATTERN_CSCAPE_ST_LINE.match(line_str)
            if m_st:
                pou = m_st.group("pou").strip()
                line_no = int(m_st.group("line"))
                msg = m_st.group("msg").strip()
                diagnostics.append(CompilerDiagnostic(
                    level="ERROR",
                    message=f"{pou}: ({line_no}): {msg}",
                    line=line_no,
                    file_path=f"{pou}.st",
                    pou_name=pou,
                    subsystem="IEC_ST",
                    error_code="ST_SYNTAX_ERROR",
                ))
                continue

            # Fallback for unformatted error / warning lines
            lower = line_str.lower()
            if "error:" in lower or "fatal error" in lower or "compile error" in lower or lower.startswith("fatal:") or "fatal compilation errors" in lower:
                line_no, col_no = cls._extract_embedded_line_col(line_str)
                diagnostics.append(CompilerDiagnostic(
                    level="ERROR",
                    message=line_str,
                    line=line_no,
                    column=col_no,
                    pou_name=default_pou,
                    error_code="FATAL_COMPILATION_ERROR" if "fatal" in lower else "COMPILE_ERROR",
                ))
            elif "warning:" in lower or "warning :" in lower or lower.startswith("warn :") or "warn :" in lower:
                line_no, col_no = cls._extract_embedded_line_col(line_str)
                diagnostics.append(CompilerDiagnostic(
                    level="WARNING",
                    message=line_str,
                    line=line_no,
                    column=col_no,
                    pou_name=default_pou,
                ))
            elif "error(s) detected" in lower or "build failed" in lower:
                diagnostics.append(CompilerDiagnostic(
                    level="ERROR",
                    message=line_str,
                    pou_name=default_pou,
                    error_code="BUILD_FAILED",
                ))

        return diagnostics

    @classmethod
    def _extract_embedded_line_col(cls, text: str) -> Tuple[Optional[int], Optional[int]]:
        """Extracts embedded line and column numbers from unstructured error messages."""
        line_no: Optional[int] = None
        col_no: Optional[int] = None

        m_line = re.search(r"\bline\s*(\d+)\b", text, re.IGNORECASE)
        if m_line:
            line_no = int(m_line.group(1))

        m_col = re.search(r"\bcol(?:umn)?\s*(\d+)\b", text, re.IGNORECASE)
        if m_col:
            col_no = int(m_col.group(1))

        return line_no, col_no

    @classmethod
    def extract_clean_build_proof(cls, raw_log: str) -> CleanBuildProof:
        """Evaluates raw compiler log to verify clean build proof (0 errors, 0 warnings)."""
        if not raw_log or not isinstance(raw_log, str):
            return CleanBuildProof(
                is_clean=False,
                error_count=0,
                warning_count=0,
                status_text="FAILED",
                proof_lines=[],
            )
        proof_lines: List[str] = []
        has_clean_summary = False
        has_success_status = False
        has_failure = False

        diagnostics = cls.parse_log(raw_log)
        diag_errors = sum(1 for d in diagnostics if d.level == "ERROR")
        diag_warnings = sum(1 for d in diagnostics if d.level == "WARNING")

        found_error_counts: List[int] = []
        found_warning_counts: List[int] = []

        for line in raw_log.splitlines():
            line_str = line.strip()
            if not line_str:
                continue

            if cls.PATTERN_FAILED_RESULT.search(line_str):
                has_failure = True
                proof_lines.append(line_str)

            m_err = cls.PATTERN_SUMMARY_ERRORS.search(line_str)
            if m_err:
                for grp in m_err.groups():
                    if grp is not None:
                        found_error_counts.append(int(grp))
                        break

            m_warn = cls.PATTERN_SUMMARY_WARNINGS.search(line_str)
            if m_warn:
                for grp in m_warn.groups():
                    if grp is not None:
                        found_warning_counts.append(int(grp))
                        break

            if cls.PATTERN_CLEAN_BUILD_SUMMARY.search(line_str):
                has_clean_summary = True
                proof_lines.append(line_str)
            if cls.PATTERN_SUCCESS_RESULT.search(line_str):
                has_success_status = True
                proof_lines.append(line_str)

        summary_errors = max(found_error_counts) if found_error_counts else 0
        summary_warnings = max(found_warning_counts) if found_warning_counts else 0

        error_count = max(diag_errors, summary_errors)
        warning_count = max(diag_warnings, summary_warnings)

        if has_failure and error_count == 0:
            error_count = 1

        has_compile_activity = bool(cls.PATTERN_COMPILE_ACTIVITY.search(raw_log))

        is_clean = (
            bool(raw_log.strip())
            and has_compile_activity
            and error_count == 0
            and warning_count == 0
            and not has_failure
            and has_clean_summary
        )
        status_text = "SUCCESS" if (is_clean and warning_count == 0) else ("WARNINGS" if (error_count == 0 and not has_failure and warning_count > 0) else "FAILED")

        return CleanBuildProof(
            is_clean=is_clean,
            error_count=error_count,
            warning_count=warning_count,
            status_text=status_text,
            proof_lines=proof_lines,
        )


def parse_diagnostics(raw_log: str, default_pou: Optional[str] = None) -> List[CompilerDiagnostic]:
    """Convenience helper to parse diagnostics from raw compiler log."""
    return CscapeLogParser.parse_log(raw_log, default_pou=default_pou)


def verify_clean_build(raw_log: str) -> CleanBuildProof:
    """Convenience helper to verify clean build proof from raw compiler log."""
    return CscapeLogParser.extract_clean_build_proof(raw_log)


class AstDiagnostics:
    """AST-driven local diagnostics engine for IEC 61131-3 Structured Text.

    Extracts structured syntax and semantic compiler diagnostics from source code
    or compiler error logs, isolating exact line, column, error code, and error messages.
    """

    @classmethod
    def extract_diagnostics(
        cls,
        code_or_log: str,
        default_pou: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> List[CompilerDiagnostic]:
        """Extracts syntax/semantic diagnostics from source code or compiler log."""
        diagnostics: List[CompilerDiagnostic] = []

        # 1. If it contains Structured Text syntax keywords, run IECValidator AST validation
        is_st_code = any(
            marker in code_or_log
            for marker in ("PROGRAM", "FUNCTION", "FUNCTION_BLOCK", "VAR", ":=", "END_PROGRAM", "END_FUNCTION")
        )
        if is_st_code:
            try:
                from ..iec.validator import IECValidator
                val_res = IECValidator.validate(code_or_log)
                if not val_res.get("valid", False):
                    for err in val_res.get("errors", []):
                        line_match = re.search(r"line\s+(\d+)", err, re.IGNORECASE)
                        col_match = re.search(r"col\s+(\d+)", err, re.IGNORECASE)
                        code_match = re.search(r"\b(ERR_[A-Z_]+|K5\d+|ST_SYNTAX_ERROR)\b", err)
                        line_num = int(line_match.group(1)) if line_match else 1
                        col_num = int(col_match.group(1)) if col_match else 1
                        err_code = code_match.group(1) if code_match else "ST_SYNTAX_ERROR"
                        clean_err = re.sub(r"^(?:ERR_[A-Z_]+|ST_SYNTAX_ERROR)\s*(?:at\s+line\s+\d+,\s*col\s+\d+:\s*)?", "", err).strip()
                        diagnostics.append(
                            CompilerDiagnostic(
                                level="ERROR",
                                message=clean_err or err,
                                line=line_num,
                                column=col_num,
                                file_path=file_path,
                                pou_name=default_pou,
                                error_code=err_code,
                            )
                        )
                    for warn in val_res.get("warnings", []):
                        diagnostics.append(
                            CompilerDiagnostic(
                                level="WARNING",
                                message=warn,
                                line=1,
                                column=1,
                                file_path=file_path,
                                pou_name=default_pou,
                                error_code="ST_WARNING",
                            )
                        )
            except Exception as exc:
                logger.warning("IECValidator extraction error: %s", exc)

        # 2. Also parse formatted compiler logs via CscapeLogParser
        log_diags = CscapeLogParser.parse_log(code_or_log, default_pou=default_pou)
        for ld in log_diags:
            if not any(d.message == ld.message and d.line == ld.line for d in diagnostics):
                if file_path and not ld.file_path:
                    ld.file_path = file_path
                diagnostics.append(ld)

        return diagnostics

    @classmethod
    def parse_log(cls, raw_log: str, default_pou: Optional[str] = None) -> List[CompilerDiagnostic]:
        """Direct alias for CscapeLogParser.parse_log."""
        return CscapeLogParser.parse_log(raw_log, default_pou=default_pou)


__all__ = [
    "CompilerDiagnostic",
    "CleanBuildProof",
    "CscapeLogParser",
    "AstDiagnostics",
    "parse_diagnostics",
    "verify_clean_build",
]
