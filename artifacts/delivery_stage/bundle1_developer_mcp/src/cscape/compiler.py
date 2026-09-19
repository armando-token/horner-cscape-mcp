"""Horner Cscape 10.2 Compiler & Error Diagnostics Engine.

Provides multi-tier compilation automation for IEC 61131-3 Structured Text:
1. Live Cscape.exe Automation (Win32 accelerator / WM_COMMAND dispatch)
2. Scrapes build output from Cscape Output Window (ListBox ID 372, Window ID 45011)
3. AST-Driven Diagnostics Engine with structured line and column error parsing
4. Zero PLC controller download safety lockout
"""

from __future__ import annotations

# Re-export diagnostics engine
from .diagnostics import (
    CompilerDiagnostic,
    CleanBuildProof,
    CscapeLogParser,
    AstDiagnostics,
    parse_diagnostics,
    verify_clean_build,
)

# Re-export compilation engine
from .compilation import (
    CscapeCompiler,
    CscapeBuildResult,
    BuildStatus,
    compute_honest_ast_metrics,
    cscape_compile_project,
    ID_PROGRAM_ERRORCHECK,
    ID_PROGRAM_DOWNLOAD,
    ID_PROGRAM_DOWNLOADOPTIONS,
    ID_CONTROLLER_DOWNLOAD,
    ID_CONTROLLER_DOWNLOAD_ALT,
    ID_OUTPUT_WINDOW,
    ID_OUTPUT_LISTBOX,
    VK_F7_COMMAND,
)

__all__ = [
    "CompilerDiagnostic",
    "CleanBuildProof",
    "CscapeLogParser",
    "AstDiagnostics",
    "parse_diagnostics",
    "verify_clean_build",
    "CscapeCompiler",
    "CscapeBuildResult",
    "BuildStatus",
    "compute_honest_ast_metrics",
    "cscape_compile_project",
    "ID_PROGRAM_ERRORCHECK",
    "ID_PROGRAM_DOWNLOAD",
    "ID_PROGRAM_DOWNLOADOPTIONS",
    "ID_CONTROLLER_DOWNLOAD",
    "ID_CONTROLLER_DOWNLOAD_ALT",
    "ID_OUTPUT_WINDOW",
    "ID_OUTPUT_LISTBOX",
    "VK_F7_COMMAND",
]
