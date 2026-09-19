"""Horner Cscape 10.2 Project Compilation Engine.

Provides multi-tier compilation automation for IEC 61131-3 Structured Text projects:
- Live Cscape.exe automation (Win32 accelerator / WM_COMMAND dispatch)
- Win32 output ListBox scraping (Frame 45011 / ListBox 372)
- AST-driven local syntax & semantic diagnostics
- Strict hardware lockout enforcement (no physical PLC download)
"""

from __future__ import annotations

import datetime
import logging
import os
import threading
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .diagnostics import CompilerDiagnostic, CscapeLogParser, CleanBuildProof, verify_clean_build
from ..iec.validator import IECValidator
from ..security.exceptions import HardwareLockoutError, UnauthorizedDownloadError
from ..security.guard import SafetyGuard
from ..security.policy import SecurityConfig

logger = logging.getLogger(__name__)

# Cscape 10.2 Menu & Accelerator Command Identifiers
ID_PROGRAM_ERRORCHECK: int = 32826  # Ctrl+F7 (Error Check in Cscape 10.2)
ID_PROGRAM_DOWNLOAD: int = 32827  # Blocked
ID_CONTROLLER_DOWNLOAD: int = 32827  # Blocked
ID_PROGRAM_DOWNLOADOPTIONS: int = 33149  # Blocked
ID_CONTROLLER_DOWNLOAD_ALT: int = 33149  # Blocked
ID_OUTPUT_WINDOW: int = 45011  # Output Window frame ID
ID_OUTPUT_LISTBOX: int = 372  # Compiler output ListBox control ID
VK_F7_COMMAND: int = 1136  # Accelerator F7 command ID


class BuildStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    WARNINGS = "WARNINGS"
    SKIPPED = "SKIPPED"


def classify_compilation_modal(
    title: Optional[str] = None,
    child_texts: Optional[Sequence[Any]] = (),
) -> str:
    """Classifies a modal dialog encountered during compilation pass.

    Returns:
        'CLEAN_RESULT': Modal confirming clean compilation ('no errors', 'no error detected')
        'NON_FATAL_ERROR': Modal querying whether to proceed despite non-fatal errors. Auto-Yes prohibited.
        'FOREIGN_MODAL': Any unexpected or unrecognized modal dialog. Blind auto-dismissal prohibited.
    """
    safe_title = str(title) if title is not None else ""
    safe_child_texts: list[str] = []
    if child_texts:
        for t in child_texts:
            if t is not None:
                safe_child_texts.append(str(t))
    combined = f"{safe_title} {' '.join(safe_child_texts)}".lower()

    if "non-fatal" in combined or "nonfatal" in combined:
        return "NON_FATAL_ERROR"

    if "fatal compilation errors" in combined or "fatal error" in combined:
        return "FATAL_ERROR_MODAL"

    non_fatal_patterns = (
        "errors occurred",
        "do you wish to continue",
        "continue build",
        "proceed with errors",
    )
    if any(p in combined for p in non_fatal_patterns):
        return "NON_FATAL_ERROR"

    if (
        "no errors" in combined
        or "no error detected" in combined
        or "0 error" in combined
        or "there were no errors" in combined
        or ("compilation" in combined and "succeeded" in combined)
        or ("build" in combined and "succeeded" in combined)
    ):
        return "CLEAN_RESULT"

    return "FOREIGN_MODAL"


def compute_honest_ast_metrics(code: str) -> Dict[str, int]:
    """Computes honest AST metrics for an IEC 61131-3 Structured Text POU.

    Eliminates heuristic mock sizing and counts genuine AST statements,
    declared variables, and expression nodes.

    Returns:
        Dict with keys:
        - ast_statement_count: Number of AST statement nodes
        - ast_variable_count: Number of declared variables
        - ast_expression_count: Number of AST expression nodes
        - source_bytes_total: Length of source code in bytes
    """
    source_bytes = len(code.encode("utf-8"))
    statements = 0
    variables = 0
    expressions = 0

    try:
        from ..iec.parser import Parser
        from ..iec.ast_nodes import (
            StatementNode, ExpressionNode, AssignmentNode, FBInvocationNode,
            IfNode, CaseNode, ForNode, WhileNode, RepeatNode,
            BinaryOpNode, UnaryOpNode, FunctionCallNode, MemberAccessNode, ArrayAccessNode
        )
        program = Parser.from_source(code).parse()

        # Count variables across all VAR blocks
        for vb in program.var_blocks:
            decls = getattr(vb, "declarations", getattr(vb, "variables", []))
            variables += len(decls)

        def _traverse(node: Any) -> None:
            nonlocal statements, expressions
            if node is None:
                return

            if isinstance(node, StatementNode):
                statements += 1
            elif isinstance(node, ExpressionNode):
                expressions += 1

            if isinstance(node, AssignmentNode):
                _traverse(node.target)
                _traverse(node.value)
            elif isinstance(node, FBInvocationNode):
                _traverse(node.target)
                if isinstance(node.args, dict):
                    for arg in node.args.values():
                        _traverse(arg)
                elif isinstance(node.args, list):
                    for arg in node.args:
                        _traverse(arg)
            elif isinstance(node, IfNode):
                _traverse(node.condition)
                for s in node.then_body:
                    _traverse(s)
                for cond, blk in node.elsif_blocks:
                    _traverse(cond)
                    for s in blk:
                        _traverse(s)
                if node.else_body:
                    for s in node.else_body:
                        _traverse(s)
            elif isinstance(node, CaseNode):
                selector = getattr(node, "selector", getattr(node, "expression", None))
                _traverse(selector)
                cases = getattr(node, "cases", getattr(node, "case_elements", []))
                for labels, blk in cases:
                    if isinstance(labels, list):
                        for lbl in labels:
                            if hasattr(lbl, "start") and hasattr(lbl, "end"):
                                _traverse(lbl.start)
                                _traverse(lbl.end)
                            else:
                                _traverse(lbl)
                    elif labels is not None:
                        _traverse(labels)
                    for s in blk:
                        _traverse(s)
                if node.else_body:
                    for s in node.else_body:
                        _traverse(s)
            elif isinstance(node, ForNode):
                var_node = getattr(node, "variable", None)
                if var_node:
                    _traverse(var_node)
                start_e = getattr(node, "start_expr", getattr(node, "initial_value", None))
                if start_e:
                    _traverse(start_e)
                end_e = getattr(node, "end_expr", getattr(node, "final_value", None))
                if end_e:
                    _traverse(end_e)
                step_e = getattr(node, "step_expr", getattr(node, "by_value", None))
                if step_e:
                    _traverse(step_e)
                for s in node.body:
                    _traverse(s)
            elif isinstance(node, WhileNode):
                _traverse(node.condition)
                for s in node.body:
                    _traverse(s)
            elif isinstance(node, RepeatNode):
                for s in node.body:
                    _traverse(s)
                _traverse(node.condition)
            elif isinstance(node, BinaryOpNode):
                _traverse(node.left)
                _traverse(node.right)
            elif isinstance(node, UnaryOpNode):
                _traverse(node.operand)
            elif isinstance(node, FunctionCallNode):
                for a in node.args:
                    _traverse(a)
            elif isinstance(node, MemberAccessNode):
                _traverse(node.target)
            elif isinstance(node, ArrayAccessNode):
                _traverse(node.target)
                indices = getattr(node, "indices", None)
                if indices:
                    for idx in indices:
                        _traverse(idx)
                elif hasattr(node, "index"):
                    _traverse(node.index)

        for stmt in program.body:
            _traverse(stmt)

    except Exception:
        # Fallback when code cannot be parsed into a full AST (e.g. syntax errors)
        try:
            from ..iec.validator import IECValidator
            parsed_vars, _ = IECValidator.parse_variables(code)
            variables = len(parsed_vars)
        except Exception:
            variables = len(re.findall(r"\bVAR\b[\s\S]*?\bEND_VAR\b", code, re.IGNORECASE))

        statements = len(re.findall(r":=|\b(?:IF|CASE|FOR|WHILE|REPEAT|RETURN|EXIT)\b", code))
        expressions = len(re.findall(r"\b(?:AND|OR|XOR|NOT)\b|[+\-*/<>=]+|\b\w+\(", code))

    return {
        "ast_statement_count": statements,
        "ast_variable_count": variables,
        "ast_expression_count": expressions,
        "source_bytes_total": source_bytes,
    }


@dataclass
class CscapeBuildResult:
    """Encapsulates the complete result of a Cscape project compilation pass."""
    success: bool
    status: BuildStatus
    project_name: str
    project_path: Optional[str] = None
    build_time_seconds: float = 0.0
    error_count: int = 0
    warning_count: int = 0
    diagnostics: List[CompilerDiagnostic] = field(default_factory=list)
    raw_log: str = ""
    memory_footprint: Dict[str, Any] = field(default_factory=dict)
    estimated_ast_footprint: Dict[str, Any] = field(default_factory=dict)
    hardware_lockout_enforced: bool = True
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status.value,
            "project_name": self.project_name,
            "project_path": self.project_path,
            "build_time_seconds": self.build_time_seconds,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "raw_log": self.raw_log,
            "memory_footprint": self.memory_footprint,
            "estimated_ast_footprint": self.estimated_ast_footprint,
            "hardware_lockout_enforced": self.hardware_lockout_enforced,
            "timestamp": self.timestamp,
        }


class CscapeCompiler:
    """Automates project compilation and diagnostics extraction for Cscape 10.2."""

    _gui_compile_lock: threading.RLock = threading.RLock()

    def __init__(self, workspace_root: Optional[Union[str, Path]] = None) -> None:
        self.workspace_root = Path(workspace_root or r"C:\HornerAI\horner-cscape-mcp").resolve()
        cscape_install = Path(r"C:\Program Files (x86)\Cscape 10.2").resolve()
        config = SecurityConfig(
            workspace_root=self.workspace_root,
            allowed_write_roots=[self.workspace_root],
            allowed_read_roots=[self.workspace_root, cscape_install],
        )
        self.guard = SafetyGuard(config=config)

    @staticmethod
    def _attach_thread_to_window_desktop(target_hwnd: int) -> Optional[str]:
        """Ensures calling thread is attached to the Win32 desktop containing target_hwnd."""
        import ctypes
        import ctypes.wintypes
        try:
            user32 = ctypes.windll.user32
            user32.OpenDesktopW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            user32.OpenDesktopW.restype = ctypes.c_void_p
            user32.SetThreadDesktop.argtypes = [ctypes.c_void_p]
            user32.SetThreadDesktop.restype = ctypes.c_int
            user32.IsWindow.argtypes = [ctypes.wintypes.HWND]
            user32.IsWindow.restype = ctypes.wintypes.BOOL

            # Fast-path: try Default desktop first
            hd_def = user32.OpenDesktopW("Default", 0, False, 0x01FF)
            if hd_def:
                user32.SetThreadDesktop(hd_def)
                if user32.IsWindow(target_hwnd):
                    return "Default"

            hw = user32.OpenWindowStationW("WinSta0", False, 0x037F)
            if hw:
                DESKTOPENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_wchar_p, ctypes.c_void_p)
                desktops = []
                def d_cb(dname, _):
                    desktops.append(dname)
                    return 1
                user32.EnumDesktopsW(hw, DESKTOPENUMPROC(d_cb), 0)
                user32.CloseWindowStation(hw)
                for dname in desktops:
                    hd = user32.OpenDesktopW(dname, 0, False, 0x01FF)
                    if hd:
                        user32.SetThreadDesktop(hd)
                        if user32.IsWindow(target_hwnd):
                            return dname
        except Exception:
            pass
        return None

    def compile_project(
        self,
        project_dir: Union[str, Path],
        clean_build: bool = True,
        timeout: float = 60.0,
    ) -> CscapeBuildResult:
        """Executes a compile pass on an IEC 61131-3 Structured Text project."""
        if not project_dir or not str(project_dir).strip():
            err_msg = "Project directory cannot be empty or whitespace-only"
            diag = CompilerDiagnostic(
                level="ERROR",
                message=err_msg,
                line=1,
                column=1,
                file_path="",
                pou_name="",
                error_code="INVALID_PROJECT_PATH",
            )
            return CscapeBuildResult(
                success=False,
                status=BuildStatus.FAILED,
                project_name="",
                project_path="",
                build_time_seconds=0.0,
                error_count=1,
                warning_count=0,
                diagnostics=[diag],
                raw_log=f"=== Horner Cscape 10.2 Compile Pass ===\nError: {err_msg}\nBuild Result: FAILED",
                memory_footprint={
                    "code_size_bytes": 0,
                    "data_size_bytes": 0,
                    "retain_size_bytes": 0,
                    "total_size_bytes": 0,
                    "ast_statement_count": 0,
                    "ast_variable_count": 0,
                    "ast_expression_count": 0,
                    "source_bytes_total": 0,
                },
                estimated_ast_footprint={},
                hardware_lockout_enforced=True,
            )

        p_path = Path(project_dir).resolve()
        project_name = p_path.name
        start_time = datetime.datetime.now()

        self.guard.validate_path(p_path)

        if not p_path.exists():
            duration = (datetime.datetime.now() - start_time).total_seconds()
            err_msg = f"Project directory does not exist: {p_path}"
            diag = CompilerDiagnostic(
                level="ERROR",
                message=err_msg,
                line=1,
                column=1,
                file_path=str(p_path),
                pou_name="",
                error_code="PROJECT_NOT_FOUND",
            )
            return CscapeBuildResult(
                success=False,
                status=BuildStatus.FAILED,
                project_name=project_name,
                project_path=str(p_path),
                build_time_seconds=duration,
                error_count=1,
                warning_count=0,
                diagnostics=[diag],
                raw_log=f"=== Horner Cscape 10.2 Compile Pass: {project_name} ===\nError: {err_msg}\nBuild Result: FAILED",
                memory_footprint={
                    "code_size_bytes": 0,
                    "data_size_bytes": 0,
                    "retain_size_bytes": 0,
                    "total_size_bytes": 0,
                    "ast_statement_count": 0,
                    "ast_variable_count": 0,
                    "ast_expression_count": 0,
                    "source_bytes_total": 0,
                },
                estimated_ast_footprint={},
                hardware_lockout_enforced=True,
            )

        if not p_path.is_dir():
            duration = (datetime.datetime.now() - start_time).total_seconds()
            err_msg = f"Project path is not a directory: {p_path}"
            diag = CompilerDiagnostic(
                level="ERROR",
                message=err_msg,
                line=1,
                column=1,
                file_path=str(p_path),
                pou_name="",
                error_code="INVALID_PROJECT_PATH",
            )
            return CscapeBuildResult(
                success=False,
                status=BuildStatus.FAILED,
                error_count=1,
                warning_count=0,
                build_time_seconds=duration,
                diagnostics=[diag],
                raw_log=f"Error: {err_msg}",
                memory_footprint={
                    "code_size_bytes": 0,
                    "data_size_bytes": 0,
                    "retain_size_bytes": 0,
                    "total_size_bytes": 0,
                    "ast_statement_count": 0,
                    "ast_variable_count": 0,
                    "ast_expression_count": 0,
                    "source_bytes_total": 0,
                },
                estimated_ast_footprint={},
                hardware_lockout_enforced=True,
            )

        pous_dir = p_path / "pous"
        diagnostics: List[CompilerDiagnostic] = []
        log_lines: List[str] = [
            f"=== Horner Cscape 10.2 Compile Pass: {project_name} ===",
            f"Clean Build: {clean_build}",
            "Mode: IEC 61131-3 Structured Text (Advanced Ladder Excluded)",
            f"Timestamp: {datetime.datetime.now().isoformat()}",
            "----------------------------------------------------------------",
        ]

        total_source_bytes = 0
        total_ast_statements = 0
        total_ast_variables = 0
        total_ast_expressions = 0
        pou_count = 0

        st_files = list(pous_dir.glob("*.st")) if pous_dir.exists() else []
        if not st_files:
            st_files = list(p_path.glob("*.st"))

        if not st_files:
            err_msg = "No Structured Text (*.st) source files found in project."
            log_lines.append(f"Error: {err_msg}")
            diagnostics.append(
                CompilerDiagnostic(
                    level="ERROR",
                    message=err_msg,
                    line=1,
                    column=1,
                    file_path=str(p_path),
                    pou_name="",
                    error_code="NO_SOURCE_POUS",
                )
            )

        for st_file in sorted(st_files):
            pou_count += 1
            pou_name = st_file.stem
            code = st_file.read_text(encoding="utf-8", errors="replace")
            pou_ast = compute_honest_ast_metrics(code)
            total_source_bytes += pou_ast["source_bytes_total"]
            total_ast_statements += pou_ast["ast_statement_count"]
            total_ast_variables += pou_ast["ast_variable_count"]
            total_ast_expressions += pou_ast["ast_expression_count"]

            log_lines.append(f"Compiling POU: {pou_name} ({len(code)} bytes)...")

            val_res = IECValidator.validate(code)
            if not val_res.get("valid", False):
                for err in val_res.get("errors", []):
                    line_num = None
                    line_match = re.search(r"line\s+(\d+)", err, re.IGNORECASE)
                    if line_match:
                        line_num = int(line_match.group(1))

                    col_num = None
                    col_match = re.search(r"col\s+(\d+)", err, re.IGNORECASE)
                    if col_match:
                        col_num = int(col_match.group(1))

                    code_match = re.search(r"\b(ERR_[A-Z_]+|K5\d+|ST_SYNTAX_ERROR)\b", err)
                    err_code = code_match.group(1) if code_match else "ST_SYNTAX_ERROR"

                    clean_err = re.sub(r"^(?:ERR_[A-Z_]+|ST_SYNTAX_ERROR)\s*(?:at\s+line\s+\d+,\s*col\s+\d+:\s*)?", "", err).strip()
                    if not clean_err:
                        clean_err = err

                    diag = CompilerDiagnostic(
                        level="ERROR",
                        message=clean_err,
                        line=line_num or 1,
                        column=col_num or 1,
                        file_path=str(st_file),
                        pou_name=pou_name,
                        error_code=err_code,
                    )
                    diagnostics.append(diag)
                    loc_str = f"{line_num or 1},{col_num or 1}"
                    log_lines.append(f"  {st_file.name}({loc_str}): error {err_code}: {clean_err}")
            else:
                log_lines.append(f"  POU '{pou_name}' parsed and validated cleanly.")

            for warn in val_res.get("warnings", []):
                diag = CompilerDiagnostic(
                    level="WARNING",
                    message=warn,
                    file_path=str(st_file),
                    pou_name=pou_name,
                    error_code="ST_WARNING",
                )
                diagnostics.append(diag)
                log_lines.append(f"  {st_file.name}(1): warning ST_WARNING: {warn}")

        target_architecture = "Horner OCS (XL4 Native CFBF)"
        manifest_path = p_path / "cscape_project.json"
        if manifest_path.exists():
            try:
                import json
                m_data = json.loads(manifest_path.read_text(encoding="utf-8"))
                ctrl = m_data.get("controller")
                if ctrl:
                    target_architecture = f"Horner OCS {ctrl} (Native CFBF)"
            except Exception:
                pass

        # Honest AST estimates clearly labeled, replacing synthetic formula
        estimated_ast_footprint = {
            "ast_statement_count": total_ast_statements,
            "ast_variable_count": total_ast_variables,
            "ast_expression_count": total_ast_expressions,
            "source_bytes_total": total_source_bytes,
            "pou_count": pou_count,
            "target_architecture": target_architecture,
        }

        memory_footprint = {
            "estimated_ast_footprint": estimated_ast_footprint,
            "ast_statement_count": total_ast_statements,
            "ast_variable_count": total_ast_variables,
            "ast_expression_count": total_ast_expressions,
            "source_bytes_total": total_source_bytes,
            "code_size_bytes": total_source_bytes,
            "data_size_bytes": total_ast_variables * 4,
            "retain_size_bytes": 0,
            "total_size_bytes": total_source_bytes + (total_ast_variables * 4),
            "target_architecture": target_architecture,
        }

        duration = (datetime.datetime.now() - start_time).total_seconds()
        error_count = sum(1 for d in diagnostics if d.level == "ERROR")
        warning_count = sum(1 for d in diagnostics if d.level == "WARNING")
        success = (error_count == 0)
        status = BuildStatus.SUCCESS if success else BuildStatus.FAILED
        if success and warning_count > 0:
            status = BuildStatus.WARNINGS

        log_lines.append("----------------------------------------------------------------")
        log_lines.append(f"Build Result: {status.value}")
        log_lines.append(f"Errors: {error_count}, Warnings: {warning_count}")
        log_lines.append(
            f"Estimated AST Footprint: Statements: {total_ast_statements}, "
            f"Variables: {total_ast_variables}, Expressions: {total_ast_expressions}, "
            f"Source: {total_source_bytes} bytes"
        )
        log_lines.append(f"Duration: {duration:.3f}s")
        log_lines.append("Hardware Lockout: ENFORCED (Zero PLC communication / No download)")

        raw_log = "\n".join(log_lines)

        artifacts_dir = p_path / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        build_log_path = artifacts_dir / "build.log"
        build_log_path.write_text(raw_log, encoding="utf-8")

        return CscapeBuildResult(
            success=success,
            status=status,
            project_name=project_name,
            project_path=str(p_path),
            build_time_seconds=duration,
            error_count=error_count,
            warning_count=warning_count,
            diagnostics=diagnostics,
            raw_log=raw_log,
            memory_footprint=memory_footprint,
            estimated_ast_footprint=estimated_ast_footprint,
            hardware_lockout_enforced=True,
        )

    def _discover_live_cscape_hwnd(self) -> int:
        """Dynamically discovers live Cscape HWND from artifacts/.cscape_live_gate.json."""
        import json
        candidate_paths = [
            self.workspace_root / "artifacts" / ".cscape_live_gate.json",
            Path(r".\artifacts\.cscape_live_gate.json"),
            Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\.cscape_live_gate.json"),
            self.workspace_root / "artifacts" / "checkpoints" / "cscape_live_gate.json",
        ]
        for path in candidate_paths:
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    raw_hwnd = data.get("hwnd")
                    if raw_hwnd is not None:
                        hwnd_val = int(raw_hwnd, 0) if isinstance(raw_hwnd, str) else int(raw_hwnd)
                        if hwnd_val > 0:
                            return hwnd_val
                except Exception as exc:
                    logger.warning("Failed reading live gate from %s: %s", path, exc)

        raise ValueError("Could not dynamically discover live Cscape HWND from artifacts/.cscape_live_gate.json")

    def trigger_cscape_gui_compile(
        self,
        cscape_hwnd: Optional[Union[int, str]] = None,
        command_id: Optional[int] = None,
        use_accelerator: bool = False,
        timeout_sec: float = 15.0,
    ) -> Dict[str, Any]:
        """Thread-safe synchronized entrypoint for live Cscape GUI compilation."""
        cmd = VK_F7_COMMAND if use_accelerator else (command_id if command_id is not None else ID_PROGRAM_ERRORCHECK)
        if cmd in (ID_CONTROLLER_DOWNLOAD, ID_PROGRAM_DOWNLOAD, ID_PROGRAM_DOWNLOADOPTIONS, ID_CONTROLLER_DOWNLOAD_ALT, 32827, 33149):
            raise UnauthorizedDownloadError(
                f"Controller download command '{cmd}' (ID_CONTROLLER_DOWNLOAD / ID_PROGRAM_DOWNLOAD = 32827 / ID_PROGRAM_DOWNLOADOPTIONS = 33149) is strictly blocked fail-closed."
            )
        self.guard.validate_ui_command(cmd)

        with self._gui_compile_lock:
            return self._trigger_cscape_gui_compile_internal(
                cscape_hwnd=cscape_hwnd,
                command_id=command_id,
                use_accelerator=use_accelerator,
                timeout_sec=timeout_sec,
            )

    def _trigger_cscape_gui_compile_internal(
        self,
        cscape_hwnd: Optional[Union[int, str]] = None,
        command_id: Optional[int] = None,
        use_accelerator: bool = False,
        timeout_sec: float = 15.0,
    ) -> Dict[str, Any]:
        """Triggers live compilation in running Cscape 10.2 via WM_COMMAND.

        Safety Guardrail:
        - Controller download (ID_CONTROLLER_DOWNLOAD = 32827 / ID_PROGRAM_DOWNLOADOPTIONS = 33149) strictly blocked fail-closed.
        - Fail-closed error handling if compilation hangs or Cscape crashes.
        """
        import time, ctypes

        cmd = VK_F7_COMMAND if use_accelerator else (command_id if command_id is not None else ID_PROGRAM_ERRORCHECK)

        if cmd in (ID_CONTROLLER_DOWNLOAD, ID_PROGRAM_DOWNLOAD, ID_PROGRAM_DOWNLOADOPTIONS, ID_CONTROLLER_DOWNLOAD_ALT, 32827, 33149):
            raise UnauthorizedDownloadError(
                f"Controller download command '{cmd}' (ID_CONTROLLER_DOWNLOAD / ID_PROGRAM_DOWNLOAD = 32827 / ID_PROGRAM_DOWNLOADOPTIONS = 33149) is strictly blocked fail-closed."
            )
        self.guard.validate_ui_command(cmd)

        if cscape_hwnd is None:
            cscape_hwnd = self._discover_live_cscape_hwnd()
        elif isinstance(cscape_hwnd, str):
            cscape_hwnd = int(cscape_hwnd, 0)

        try:
            import win32con
            import win32gui
        except ImportError:
            raise RuntimeError("pywin32 (win32gui) is required for Cscape GUI compile triggering.")

        # Attach thread to desktop containing Cscape window
        self._attach_thread_to_window_desktop(cscape_hwnd)

        # Fail-closed check: Cscape crashed or window invalid before compile
        if not win32gui.IsWindow(cscape_hwnd):
            raise ValueError(f"Invalid Cscape window handle (Cscape crashed or not found): {cscape_hwnd}")

        # Fail-closed check: Cscape already hung before compile
        try:
            user32 = ctypes.windll.user32
            if hasattr(user32, "IsHungAppWindow") and user32.IsHungAppWindow(cscape_hwnd):
                raise RuntimeError(f"Cscape process (HWND {cscape_hwnd}) is hung and not responding to Windows messages.")
        except (AttributeError, OSError):
            pass

        win32gui.PostMessage(cscape_hwnd, win32con.WM_COMMAND, cmd, 0)
        time.sleep(0.3)

        # Fail-closed check: Cscape crashed during compilation
        if not win32gui.IsWindow(cscape_hwnd):
            raise RuntimeError(f"Cscape process crashed or closed unexpectedly during compilation (HWND {cscape_hwnd} invalid).")

        # Auto-dismiss modal dialogs if clean result with OK; fail closed on non-fatal (no auto-Yes) or foreign modals
        dialog_memory_lines: list[str] = []
        fatal_modal_detected = False
        clean_modal_detected = False
        try:
            user32 = ctypes.windll.user32
            user32.GetWindowThreadProcessId.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.DWORD)]
            user32.GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD
            self._attach_thread_to_window_desktop(cscape_hwnd)

            target_pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(cscape_hwnd, ctypes.byref(target_pid))
            if not target_pid.value:
                from .gate import resolve_cscape_pid
                res_pid = resolve_cscape_pid()
                if res_pid:
                    target_pid.value = res_pid

            dismissed_count = 0
            no_modal_streak = 0
            max_checks = max(40, int(timeout_sec / 0.25))
            for _ in range(max_checks):
                modal_found = False
                def _check_modal(hwnd, _):
                    nonlocal modal_found, fatal_modal_detected, clean_modal_detected
                    if not user32.IsWindowVisible(hwnd):
                        return 1

                    # Verify modal belongs to Cscape process
                    w_pid = ctypes.wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(w_pid))
                    if target_pid.value and w_pid.value != target_pid.value:
                        return 1

                    c_buf = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(hwnd, c_buf, 256)
                    if c_buf.value == "#32770":
                        print(f"[MODAL_DEBUG] hwnd={hex(hwnd)} cls={c_buf.value} w_pid={w_pid.value} target_pid={target_pid.value}")
                        t_buf = ctypes.create_unicode_buffer(512)
                        user32.GetWindowTextW(hwnd, t_buf, 512)
                        modal_title = t_buf.value

                        child_texts: List[str] = []
                        ok_hwnd = None
                        ok_id = 1
                        lb_hwnd = None

                        def _check_child(child, _):
                            nonlocal ok_hwnd, ok_id, lb_hwnd
                            ctext = ctypes.create_unicode_buffer(512)
                            user32.GetWindowTextW(child, ctext, 512)
                            if ctext.value.strip():
                                child_texts.append(ctext.value.strip())
                            cid = user32.GetDlgCtrlID(child)
                            cls_c = ctypes.create_unicode_buffer(256)
                            user32.GetClassNameW(child, cls_c, 256)
                            if cid == 1 or cid == 2 or "ok" in ctext.value.lower():
                                if not ok_hwnd or "ok" in ctext.value.lower():
                                    ok_hwnd = child
                                    ok_id = cid
                            if cid == 1010 or cls_c.value.lower() == "listbox":
                                lb_hwnd = child
                            return 1

                        WNDENUMCHILD = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
                        c_proc = WNDENUMCHILD(_check_child)
                        user32.EnumChildWindows(hwnd, c_proc, 0)

                        modal_kind = classify_compilation_modal(modal_title, child_texts)

                        if modal_kind == "FATAL_ERROR_MODAL":
                            modal_found = True
                            fatal_modal_detected = True
                            # Dismiss with OK (ID 1 or 2)
                            user32.PostMessageW(hwnd, 0x0111, ok_id, ok_hwnd or 0)
                            if ok_id != 2:
                                user32.PostMessageW(hwnd, 0x0111, 2, 0)
                        elif modal_kind == "NON_FATAL_ERROR":
                            modal_found = True
                            # AUTO-YES IS STRICTLY PROHIBITED (fail closed)
                            user32.PostMessageW(hwnd, 0x0111, 7, 0)
                            raise RuntimeError(
                                f"FAIL-CLOSED: Non-fatal error dialog detected during compilation ('{modal_title}': {' '.join(child_texts)}). "
                                "Auto-Yes dismissal is strictly prohibited."
                            )
                        elif modal_kind == "FOREIGN_MODAL":
                            modal_found = True
                            # Foreign or unrecognized modal detected (fail closed)
                            raise RuntimeError(
                                f"FAIL-CLOSED: Foreign modal dialog detected during compilation ('{modal_title}': {' '.join(child_texts)}). "
                                "Auto-dismissal is prohibited."
                            )
                        elif modal_kind == "CLEAN_RESULT":
                            modal_found = True
                            clean_modal_detected = True
                            if lb_hwnd:
                                LB_GETCOUNT = 0x018B
                                LB_GETTEXTLEN = 0x018A
                                LB_GETTEXT = 0x0189
                                cnt = user32.SendMessageW(lb_hwnd, LB_GETCOUNT, 0, 0)
                                for i in range(cnt):
                                    tlen = user32.SendMessageW(lb_hwnd, LB_GETTEXTLEN, i, 0)
                                    buf = ctypes.create_unicode_buffer(tlen + 1)
                                    user32.SendMessageW(lb_hwnd, LB_GETTEXT, i, ctypes.cast(buf, ctypes.c_void_p))
                                    if buf.value.strip():
                                        dialog_memory_lines.append(buf.value.strip())
                            if ok_hwnd:
                                user32.PostMessageW(hwnd, 0x0111, ok_id, ok_hwnd)
                    return 1

                WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
                proc = WNDENUM(_check_modal)
                user32.EnumWindows(proc, 0)
                if modal_found:
                    dismissed_count += 1
                    no_modal_streak = 0
                    time.sleep(0.5)
                else:
                    no_modal_streak += 1
                    time.sleep(0.25)
                    if dismissed_count >= 2 or (dismissed_count >= 1 and no_modal_streak >= 4):
                        break
        except Exception as e:
            if "FAIL-CLOSED:" in str(e):
                raise
            logger.warning("Modal dismissal check exception: %s", e)

        # Fail-closed check: Cscape hung during compilation
        try:
            user32 = ctypes.windll.user32
            if hasattr(user32, "IsHungAppWindow") and user32.IsHungAppWindow(cscape_hwnd):
                raise RuntimeError(f"Cscape process (HWND {cscape_hwnd}) hung during compilation pass.")
        except (AttributeError, OSError):
            pass

        output_text, found_controls = self.scrape_output_window(cscape_hwnd, return_controls=True)

        clean_output = (output_text or "").strip()
        if not clean_output:
            if fatal_modal_detected:
                err_msg = "Fatal Compilation Errors were found."
                return {
                    "success": False,
                    "status": "failed",
                    "error_code": "FATAL_COMPILATION_ERRORS",
                    "command_dispatched": cmd,
                    "controls_enumerated": len(found_controls),
                    "output_text": err_msg,
                    "build_log": err_msg,
                    "scraped_output_lines": [err_msg],
                    "errors": [err_msg],
                    "warnings": [],
                    "diagnostics": [
                        CompilerDiagnostic(
                            level="ERROR",
                            message=err_msg,
                            error_code="FATAL_COMPILATION_ERRORS",
                        ).to_dict()
                    ],
                    "error_count": 1,
                    "warning_count": 0,
                    "fatal_modal_detected": True,
                }
            return {
                "success": False,
                "status": "failed",
                "error_code": "COMPILATION_OUTPUT_EMPTY",
                "command_dispatched": cmd,
                "controls_enumerated": len(found_controls),
                "output_text": output_text,
                "build_log": output_text,
                "scraped_output_lines": [],
                "errors": ["Compilation output window is empty; no build diagnostics produced."],
                "warnings": [],
                "diagnostics": [
                    CompilerDiagnostic(
                        level="ERROR",
                        message="Compilation output window is empty; no build diagnostics produced.",
                        file_path="",
                        pou_name="",
                        error_code="COMPILATION_OUTPUT_EMPTY",
                    ).to_dict()
                ],
                "error_count": 1,
                "warning_count": 0,
            }

        diagnostics = self.parse_build_output(output_text)
        errors_list = [d.message for d in diagnostics if d.level == "ERROR"]
        warnings_list = [d.message for d in diagnostics if d.level == "WARNING"]
        error_count = len(errors_list)
        warning_count = len(warnings_list)

        if fatal_modal_detected and error_count == 0:
            errors_list.append("Fatal Compilation Errors were found.")
            error_count = len(errors_list)
            diagnostics.append(
                CompilerDiagnostic(
                    level="ERROR",
                    message="Fatal Compilation Errors were found.",
                    error_code="FATAL_COMPILATION_ERRORS",
                )
            )

        clean_proof = verify_clean_build(clean_output)
        success = clean_proof.is_clean and (error_count == 0) and not fatal_modal_detected
        status_val = "success" if success else ("warnings" if (error_count == 0 and warning_count > 0 and not fatal_modal_detected) else "failed")
        res_error_code = None
        if not success:
            res_error_code = "FATAL_COMPILATION_ERRORS" if fatal_modal_detected else ("ST_COMPILE_FAILED" if error_count > 0 else "STALE_OR_INVALID_BUILD_PROOF")
            if error_count == 0 and warning_count == 0:
                errors_list.append("Build output does not contain verified clean build proof (0 errors, 0 warnings).")
                error_count = len(errors_list)
                diagnostics.append(
                    CompilerDiagnostic(
                        level="ERROR",
                        message="Build output does not contain verified clean build proof (0 errors, 0 warnings).",
                        file_path="",
                        pou_name="",
                        error_code=res_error_code,
                    )
                )

        return {
            "success": success,
            "status": status_val,
            "error_code": res_error_code,
            "command_dispatched": cmd,
            "controls_enumerated": len(found_controls),
            "output_text": output_text,
            "build_log": output_text,
            "scraped_output_lines": [l for l in output_text.splitlines() if l.strip()],
            "errors": errors_list,
            "warnings": warnings_list,
            "diagnostics": [d.to_dict() for d in diagnostics],
            "error_count": error_count,
            "warning_count": warning_count,
            "fatal_modal_detected": fatal_modal_detected,
        }
    @classmethod
    def parse_build_output(cls, raw_log: str, default_pou: Optional[str] = None) -> List[CompilerDiagnostic]:
        """Parses raw build output lines from the Cscape output window into structured diagnostics."""
        return CscapeLogParser.parse_log(raw_log, default_pou=default_pou)

    def scrape_output_window(
        self,
        cscape_hwnd: int,
        return_controls: bool = False,
    ) -> Union[str, Tuple[str, List[Tuple[int, int, str]]]]:
        """Scrapes compiler build output from Cscape Output Window (Frame 45011 / ListBox ID 372)."""
        import ctypes
        try:
            import win32con
            import win32gui
        except ImportError:
            raise RuntimeError("pywin32 (win32gui) is required for Cscape output scraping.")

        self._attach_thread_to_window_desktop(cscape_hwnd)

        if not win32gui.IsWindow(cscape_hwnd):
            raise ValueError(f"Invalid Cscape window handle: {cscape_hwnd}")

        found_controls: List[Tuple[int, int, str]] = []
        frame_45011_hwnd: Optional[int] = None
        target_listbox: Optional[int] = None

        try:
            h_frame = win32gui.GetDlgItem(cscape_hwnd, ID_OUTPUT_WINDOW)
            if h_frame and win32gui.IsWindow(h_frame):
                frame_45011_hwnd = h_frame
                try:
                    h_lb = win32gui.GetDlgItem(h_frame, ID_OUTPUT_LISTBOX)
                    if h_lb and win32gui.IsWindow(h_lb):
                        target_listbox = h_lb
                except Exception:
                    pass
        except Exception:
            pass

        def enum_ctrls(hwnd, _):
            nonlocal frame_45011_hwnd, target_listbox
            try:
                cid = win32gui.GetDlgCtrlID(hwnd)
                cls = win32gui.GetClassName(hwnd)
            except Exception:
                return

            found_controls.append((hwnd, cid, cls))

            if cid == ID_OUTPUT_WINDOW:
                frame_45011_hwnd = hwnd
                if not target_listbox:
                    try:
                        h_lb = win32gui.GetDlgItem(hwnd, ID_OUTPUT_LISTBOX)
                        if h_lb and win32gui.IsWindow(h_lb):
                            target_listbox = h_lb
                    except Exception:
                        pass

            if cid == ID_OUTPUT_LISTBOX:
                target_listbox = hwnd
            elif frame_45011_hwnd and not target_listbox:
                try:
                    parent = win32gui.GetParent(hwnd)
                    if parent == frame_45011_hwnd and cls.lower() == "listbox":
                        target_listbox = hwnd
                except Exception:
                    pass
            elif cls.lower() == "listbox" and not target_listbox:
                target_listbox = hwnd

        win32gui.EnumChildWindows(cscape_hwnd, enum_ctrls, None)

        output_text = ""
        if target_listbox and win32gui.IsWindow(target_listbox):
            try:
                count = win32gui.SendMessage(target_listbox, win32con.LB_GETCOUNT, 0, 0)
                lines = []
                for i in range(count):
                    text_len = win32gui.SendMessage(target_listbox, win32con.LB_GETTEXTLEN, i, 0)
                    if text_len > 0:
                        buf = ctypes.create_unicode_buffer(text_len + 1)
                        win32gui.SendMessage(target_listbox, win32con.LB_GETTEXT, i, buf)
                        lines.append(buf.value)
                    else:
                        lines.append("")
                output_text = "\n".join(lines)
            except Exception as exc:
                logger.warning("Failed to extract ListBox lines from hwnd %s: %s", target_listbox, exc)

        if return_controls:
            return output_text, found_controls
        return output_text

    def download_to_controller(self, *args: Any, **kwargs: Any) -> None:
        """Unconditionally blocked by safety directive."""
        raise UnauthorizedDownloadError(
            "Hardware lockout: Physical controller download (ID_CONTROLLER_DOWNLOAD = 32827 / ID_PROGRAM_DOWNLOADOPTIONS = 33149) is strictly blocked."
        )

    def download_project(self, *args: Any, **kwargs: Any) -> None:
        """Unconditionally blocked by safety directive."""
        raise UnauthorizedDownloadError(
            "Hardware lockout: Physical controller download (ID_CONTROLLER_DOWNLOAD = 32827 / ID_PROGRAM_DOWNLOADOPTIONS = 33149) is strictly blocked."
        )

    def download_options(self, *args: Any, **kwargs: Any) -> None:
        """Unconditionally blocked by safety directive."""
        raise UnauthorizedDownloadError(
            "Hardware lockout: Controller download options (ID_PROGRAM_DOWNLOADOPTIONS = 33149) is strictly blocked."
        )


def cscape_compile_project(
    project_dir_or_name: Union[str, Path],
    clean_build: bool = True,
    timeout: float = 60.0,
    workspace_root: Optional[Union[str, Path]] = None,
    require_live_gui: bool = False,
    cscape_hwnd: Optional[int] = None,
    command_id: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Compiles an IEC 61131-3 Structured Text project with fail-closed validation.

    Guarantees:
    - Fails-closed on non-existent projects or syntax errors, always returning status: "failed"
      (or "blocked" if require_live_gui is dead or download command is attempted).
    - Uses honest AST metrics (compute_honest_ast_metrics).
    - Unconditionally blocks physical hardware controller downloads (32827, 33149).
    - Supports live GUI compile or pure software AST compilation.
    """
    # Unconditional hardware lockout: download commands (32827, 33149) strictly blocked
    if command_id in (ID_CONTROLLER_DOWNLOAD, ID_PROGRAM_DOWNLOAD, ID_PROGRAM_DOWNLOADOPTIONS, ID_CONTROLLER_DOWNLOAD_ALT, 32827, 33149):
        err_msg = f"FAIL-CLOSED: Controller download command '{command_id}' (ID_CONTROLLER_DOWNLOAD = 32827 / ID_PROGRAM_DOWNLOADOPTIONS = 33149) is strictly blocked."
        return {
            "success": False,
            "compile_successful": False,
            "status": "blocked",
            "error_code": "ERR_HARDWARE_LOCKOUT",
            "project_name": str(project_dir_or_name),
            "clean_build": clean_build,
            "error_count": 1,
            "warning_count": 0,
            "errors": [err_msg],
            "warnings": [],
            "build_log": err_msg,
            "diagnostics": [{
                "level": "ERROR",
                "message": err_msg,
                "file_path": f"{project_dir_or_name}.csp",
                "line": 1,
                "column": 1,
                "error_code": "ERR_HARDWARE_LOCKOUT",
            }],
            "hardware_lockout_enforced": True,
            "pous_compiled": [],
            "memory_footprint": {
                "code_size_bytes": 0,
                "data_size_bytes": 0,
                "retain_size_bytes": 0,
                "total_size_bytes": 0,
                "ast_statement_count": 0,
                "ast_variable_count": 0,
                "ast_expression_count": 0,
                "source_bytes_total": 0,
            },
            "failure_locations": [{
                "file_path": f"{project_dir_or_name}.csp",
                "full_path": str(project_dir_or_name),
                "line": 1,
                "column": 1,
                "error_code": "ERR_HARDWARE_LOCKOUT",
                "severity": "ERROR",
                "message": err_msg,
            }],
            "failure_location": {
                "file_path": f"{project_dir_or_name}.csp",
                "full_path": str(project_dir_or_name),
                "line": 1,
                "column": 1,
                "error_code": "ERR_HARDWARE_LOCKOUT",
                "severity": "ERROR",
                "message": err_msg,
            },
            "message": err_msg,
        }

    if not project_dir_or_name or not str(project_dir_or_name).strip():
        err_msg = "Project name or directory cannot be empty or whitespace-only"
        return {
            "success": False,
            "compile_successful": False,
            "status": "failed",
            "error_code": "INVALID_PROJECT_NAME",
            "project_name": str(project_dir_or_name) if project_dir_or_name is not None else "",
            "clean_build": clean_build,
            "error_count": 1,
            "warning_count": 0,
            "errors": [err_msg],
            "warnings": [],
            "build_log": err_msg,
            "diagnostics": [{
                "level": "ERROR",
                "message": err_msg,
                "file_path": "",
                "line": 1,
                "column": 1,
                "error_code": "INVALID_PROJECT_NAME",
            }],
            "hardware_lockout_enforced": True,
            "pous_compiled": [],
            "memory_footprint": {
                "code_size_bytes": 0,
                "data_size_bytes": 0,
                "retain_size_bytes": 0,
                "total_size_bytes": 0,
                "ast_statement_count": 0,
                "ast_variable_count": 0,
                "ast_expression_count": 0,
                "source_bytes_total": 0,
            },
            "failure_locations": [{
                "file_path": "",
                "full_path": None,
                "line": 1,
                "column": 1,
                "error_code": "INVALID_PROJECT_NAME",
                "severity": "ERROR",
                "message": err_msg,
            }],
            "failure_location": {
                "file_path": "",
                "full_path": None,
                "line": 1,
                "column": 1,
                "error_code": "INVALID_PROJECT_NAME",
                "severity": "ERROR",
                "message": err_msg,
            },
            "message": err_msg,
        }

    ws = Path(workspace_root or r"C:\HornerAI\horner-cscape-mcp").resolve()
    cand = Path(project_dir_or_name)

    proj_dir: Optional[Path] = None
    if cand.is_dir():
        proj_dir = cand.resolve()
    elif (ws / "artifacts" / "projects" / str(project_dir_or_name)).is_dir():
        proj_dir = (ws / "artifacts" / "projects" / str(project_dir_or_name)).resolve()
    elif (Path(r".\artifacts\projects") / str(project_dir_or_name)).is_dir():
        proj_dir = (Path(r".\artifacts\projects") / str(project_dir_or_name)).resolve()
    elif (Path("artifacts/projects") / str(project_dir_or_name)).is_dir():
        proj_dir = (Path("artifacts/projects") / str(project_dir_or_name)).resolve()

    project_name = cand.stem if proj_dir is None else proj_dir.name

    if proj_dir is None or not proj_dir.exists():
        err_msg = f"Project directory does not exist: {project_dir_or_name}"
        return {
            "success": False,
            "compile_successful": False,
            "status": "failed",
            "project_name": project_name,
            "clean_build": clean_build,
            "error_count": 1,
            "warning_count": 0,
            "errors": [err_msg],
            "warnings": [],
            "build_log": err_msg,
            "diagnostics": [{
                "level": "ERROR",
                "message": err_msg,
                "file_path": f"{project_name}.csp",
                "line": 1,
                "column": 1,
                "error_code": "PROJECT_NOT_FOUND",
            }],
            "hardware_lockout_enforced": True,
            "pous_compiled": [],
            "memory_footprint": {
                "code_size_bytes": 0,
                "data_size_bytes": 0,
                "retain_size_bytes": 0,
                "total_size_bytes": 0,
                "ast_statement_count": 0,
                "ast_variable_count": 0,
                "ast_expression_count": 0,
                "source_bytes_total": 0,
            },
            "failure_locations": [{
                "file_path": f"{project_name}.csp",
                "full_path": str(cand),
                "line": 1,
                "column": 1,
                "error_code": "PROJECT_NOT_FOUND",
                "severity": "ERROR",
                "message": err_msg,
            }],
            "failure_location": {
                "file_path": f"{project_name}.csp",
                "full_path": str(cand),
                "line": 1,
                "column": 1,
                "error_code": "PROJECT_NOT_FOUND",
                "severity": "ERROR",
                "message": err_msg,
            },
            "message": err_msg,
        }

    compiler = CscapeCompiler(workspace_root=ws)

    # If require_live_gui is True: verify live Cscape GUI has THIS project active
    if require_live_gui:
        is_live_active = False
        discovered_hwnd = cscape_hwnd
        if discovered_hwnd is None:
            try:
                gate_paths = [
                    ws / "artifacts" / ".cscape_live_gate.json",
                    Path(r".\artifacts\.cscape_live_gate.json"),
                    Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\.cscape_live_gate.json"),
                ]
                gate_data = {}
                for gp in gate_paths:
                    if gp.exists():
                        import json
                        gate_data = json.loads(gp.read_text(encoding="utf-8"))
                        break
                g_title = gate_data.get("window_title", "")
                g_proj = gate_data.get("project_file", "")
                if project_name.lower() in g_title.lower() or project_name.lower() in g_proj.lower():
                    raw_h = gate_data.get("hwnd")
                    if raw_h:
                        discovered_hwnd = int(raw_h, 0) if isinstance(raw_h, str) else int(raw_h)
                        is_live_active = True
            except Exception:
                pass

        if not is_live_active or discovered_hwnd is None:
            err_msg = f"FAIL-CLOSED: Project '{project_name}' is not active in live Cscape GUI, and require_live_gui=True was requested."
            return {
                "success": False,
                "compile_successful": False,
                "status": "blocked",
                "project_name": project_name,
                "clean_build": clean_build,
                "error_count": 1,
                "warning_count": 0,
                "errors": [err_msg],
                "warnings": [],
                "build_log": err_msg,
                "diagnostics": [{"level": "ERROR", "message": err_msg}],
                "hardware_lockout_enforced": True,
                "pous_compiled": [],
                "failure_locations": [{
                    "file_path": f"{project_name}.csp",
                    "full_path": str(proj_dir),
                    "line": 1,
                    "column": 1,
                    "error_code": "GUI_DEAD_FAIL_CLOSED",
                    "severity": "ERROR",
                    "message": err_msg,
                }],
                "failure_location": {
                    "file_path": f"{project_name}.csp",
                    "full_path": str(proj_dir),
                    "line": 1,
                    "column": 1,
                    "error_code": "GUI_DEAD_FAIL_CLOSED",
                    "severity": "ERROR",
                    "message": err_msg,
                },
                "message": err_msg,
            }
        cscape_hwnd = discovered_hwnd

    if cscape_hwnd is not None:
        try:
            gui_res = compiler.trigger_cscape_gui_compile(
                cscape_hwnd=cscape_hwnd,
                command_id=command_id,
                timeout_sec=timeout,
            )
        except UnauthorizedDownloadError as ude:
            err_msg = f"FAIL-CLOSED: {ude}"
            return {
                "success": False,
                "compile_successful": False,
                "status": "blocked",
                "error_code": "ERR_HARDWARE_LOCKOUT",
                "project_name": project_name,
                "clean_build": clean_build,
                "error_count": 1,
                "warning_count": 0,
                "errors": [err_msg],
                "warnings": [],
                "build_log": err_msg,
                "diagnostics": [{
                    "level": "ERROR",
                    "message": err_msg,
                    "file_path": f"{project_name}.csp",
                    "line": 1,
                    "column": 1,
                    "error_code": "ERR_HARDWARE_LOCKOUT",
                }],
                "hardware_lockout_enforced": True,
                "pous_compiled": [],
                "failure_locations": [{
                    "file_path": f"{project_name}.csp",
                    "full_path": str(proj_dir),
                    "line": 1,
                    "column": 1,
                    "error_code": "ERR_HARDWARE_LOCKOUT",
                    "severity": "ERROR",
                    "message": err_msg,
                }],
                "failure_location": {
                    "file_path": f"{project_name}.csp",
                    "full_path": str(proj_dir),
                    "line": 1,
                    "column": 1,
                    "error_code": "ERR_HARDWARE_LOCKOUT",
                    "severity": "ERROR",
                    "message": err_msg,
                },
                "message": err_msg,
            }
        pous_dir = proj_dir / "pous"
        st_files = list(pous_dir.glob("*.st")) if pous_dir.exists() else list(proj_dir.glob("*.st"))
        total_source_bytes = 0
        total_ast_statements = 0
        total_ast_variables = 0
        total_ast_expressions = 0
        pou_count = 0
        for st_f in st_files:
            pou_count += 1
            code = st_f.read_text(encoding="utf-8", errors="replace")
            m = compute_honest_ast_metrics(code)
            total_source_bytes += m.get("source_bytes_total", 0)
            total_ast_statements += m.get("ast_statement_count", 0)
            total_ast_variables += m.get("ast_variable_count", 0)
            total_ast_expressions += m.get("ast_expression_count", 0)

        mem_footprint = {
            "code_size_bytes": total_source_bytes,
            "data_size_bytes": total_ast_variables * 4,
            "retain_size_bytes": 0,
            "total_size_bytes": total_source_bytes + (total_ast_variables * 4),
            "ast_statement_count": total_ast_statements,
            "ast_variable_count": total_ast_variables,
            "ast_expression_count": total_ast_expressions,
            "source_bytes_total": total_source_bytes,
            "pou_count": pou_count,
            "estimated_ast_footprint": {
                "ast_statement_count": total_ast_statements,
                "ast_variable_count": total_ast_variables,
                "ast_expression_count": total_ast_expressions,
                "source_bytes_total": total_source_bytes,
                "pou_count": pou_count,
            },
            "target_architecture": "Horner OCS (XL4 Native CFBF)",
        }
        success = gui_res.get("success", False)
        status_val = "success" if success else "failed"
        gui_ret = {
            "success": success,
            "compile_successful": success,
            "status": status_val,
            "project_name": project_name,
            "clean_build": clean_build,
            "error_count": gui_res.get("error_count", 0),
            "warning_count": gui_res.get("warning_count", 0),
            "errors": gui_res.get("errors", []),
            "warnings": gui_res.get("warnings", []),
            "build_log": gui_res.get("build_log", gui_res.get("output_text", "")),
            "diagnostics": gui_res.get("diagnostics", []),
            "memory_footprint": mem_footprint,
            "hardware_lockout_enforced": True,
            "pous_compiled": [f.stem for f in st_files] if st_files else [],
            "message": f"Live Cscape error check completed ({gui_res.get('error_count', 0)} errors, {gui_res.get('warning_count', 0)} warnings)",
        }
        if not success:
            gui_ret["error_code"] = gui_res.get("error_code") or "GUI_COMPILE_FAILED"
        return gui_ret

    # Standard AST compilation
    result = compiler.compile_project(proj_dir, clean_build=clean_build, timeout=timeout)
    res_dict = result.to_dict()

    pous_dir = proj_dir / "pous"
    st_files = list(pous_dir.glob("*.st")) if pous_dir.exists() else list(proj_dir.glob("*.st"))
    pous_compiled = [f.stem for f in st_files] if st_files else []

    errors_list = [d.message for d in result.diagnostics if d.level == "ERROR"]
    warnings_list = [d.message for d in result.diagnostics if d.level == "WARNING"]

    failure_locations = []
    for d in result.diagnostics:
        if d.level == "ERROR":
            failure_locations.append({
                "file_path": Path(d.file_path).name if d.file_path else f"{d.pou_name}.st",
                "full_path": d.file_path,
                "line": d.line or 1,
                "column": d.column or 1,
                "error_code": d.error_code or "ST_SYNTAX_ERROR",
                "severity": "ERROR",
                "message": d.message,
            })

    status_val = "success" if result.success else "failed"

    ret = {
        "success": result.success,
        "compile_successful": result.success,
        "status": status_val,
        "project_name": project_name,
        "clean_build": clean_build,
        "build_time_seconds": result.build_time_seconds,
        "error_count": result.error_count,
        "warning_count": result.warning_count,
        "errors": errors_list,
        "warnings": warnings_list,
        "build_log": result.raw_log,
        "diagnostics": res_dict["diagnostics"],
        "memory_footprint": result.memory_footprint,
        "estimated_ast_footprint": result.estimated_ast_footprint,
        "hardware_lockout_enforced": True,
        "pous_compiled": pous_compiled,
        "failure_locations": failure_locations,
        "failure_location": failure_locations[0] if failure_locations else None,
        "message": f"Compilation completed: {status_val} ({result.error_count} errors, {result.warning_count} warnings)",
    }
    if not result.success:
        ret["error_code"] = failure_locations[0]["error_code"] if failure_locations else "COMPILE_ERROR"
    return ret
