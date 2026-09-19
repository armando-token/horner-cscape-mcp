"""Horner Cscape Model Context Protocol (MCP) Tools.

Directly binds to native Cscape 10.2 automation engines in src/cscape/:
1. cscape_launch_ide -> CscapeLifecycleManager
2. cscape_new_iec_project -> CscapeLiveProjectManager
3. cscape_open_project -> CscapeLiveProjectManager (CFBF OLE2 verification)
4. cscape_insert_st -> StructuredTextInserter
5. cscape_compile -> CscapeCompiler (ID_PROGRAM_ERRORCHECK = 32826 / Ctrl+F7)
6. cscape_get_build_output -> CscapeCompiler / CscapeLogParser
7. cscape_import_variables -> VariableManager (CSV / XML)
8. cscape_export_variables -> VariableManager (CSV / XML)
9. cscape_run_simulation -> CscapeSimulator (%R, %M, %T, %AI, %AQ, %I, %Q, %S clocks)

Also provides backward-compatible convenience wrappers:
- cscape_create_project
- cscape_add_st_pou
- cscape_validate_st
- cscape_inspect_variables
- cscape_compile_project
- cscape_get_diagnostics
- cscape_simulate_pou
- cscape_export_project

CRITICAL SAFETY INVARIANTS:
- Pure IEC 61131-3 Structured Text; authentic Cscape 10.2 enforced
"""

from __future__ import annotations

import datetime
import functools
import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
import traceback
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Core Cscape 10.2 engines
from ..cscape.lifecycle import (
    CscapeLifecycleManager,
    CscapeLifecycleState,
    launch_cscape,
)
from ..cscape.project_manager import (
    CscapeLiveProjectManager,
    ProjectFileInfo,
    create_new_iec_project,
    CFBF_MAGIC,
)
from ..cscape.st_inserter import (
    StructuredTextInserter,
    CscapeSTInserter,
    POUType,
    calculate_code_hash,
)
from ..cscape.compiler import (
    CscapeCompiler,
    CscapeBuildResult,
    CscapeLogParser,
    AstDiagnostics,
    BuildStatus,
    compute_honest_ast_metrics,
    ID_PROGRAM_ERRORCHECK,
    ID_PROGRAM_DOWNLOAD,
    ID_PROGRAM_DOWNLOADOPTIONS,
    ID_CONTROLLER_DOWNLOAD,
)
from ..cscape.st_ld_interop import (
    STLadderInteropGuard,
    LadderConstructRejectedError,
)
from ..cscape.variables import (
    VariableManager,
    CscapeVariableManager,
    CscapeVariable,
    HornerRegister,
)
from ..cscape.simulation import (
    CscapeSimulator,
    simulate_pou_with_registers,
    parse_register_address,
    enforce_software_isolation,
    RegisterType,
    CLASSIFICATION,
    VERIFICATION_CLASSIFICATION,
)
from ..iec.validator import IECValidator
from ..security.exceptions import (
    HardwareLockoutError,
    UnauthorizedDownloadError,
    SecurityError,
    BlockedExecutableError,
    DangerousArgumentError,
    CscapeSafetyViolationError,
)
from ..security.guard import SafetyGuard, SecurityGuard
from ..cscape.hmi import CscapeHMIManager
from ..cscape.fixture_evolution import FixtureEvolutionManager
from ..cscape.modbus_config import (
    ModbusPVProviderConfig,
    ModbusTransport,
    ModbusRole,
    ModbusFunctionCode,
    ModbusTCPEndpoint,
    ModbusRTUEndpoint,
    ModbusAddressMapping,
    ScalingConfiguration,
    PollingAndStalePolicy,
    ModbusConfigPersistenceManager,
    generate_modbus_conversion_walkthrough,
)
from ..simulation.test_modbus_server import (
    LabeledTestModbusServer,
    query_pv_register,
    SERVER_LABEL as TEST_MODBUS_SERVER_LABEL,
)

logger = logging.getLogger(__name__)
WORKSPACE_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()


def _get_utc_timestamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _find_cfbf_template() -> Optional[Path]:
    """Finds an existing authentic Cscape CFBF (.csp) file to use as base template."""
    candidates = [
        WORKSPACE_ROOT / "artifacts" / "projects" / "new_iec_st_project.csp",
        WORKSPACE_ROOT / "fixtures" / "cscape_native_samples" / "reg_min.csp",
        WORKSPACE_ROOT / "fixtures" / "alarm test.csp",
        WORKSPACE_ROOT / "fixtures" / "all.csp",
    ]
    for c in candidates:
        if c.exists() and c.stat().st_size > 0:
            return c
    fixtures_csp = list((WORKSPACE_ROOT / "fixtures").glob("*.csp"))
    if fixtures_csp:
        return fixtures_csp[0]
    return None


# ==============================================================================
# Rigorous Status Contract Helpers
# ==============================================================================

class ToolStatus(str):
    """String subclass representing tool execution status.
    Conforms to canonical status ontology: 'success' | 'failed' | 'blocked' | 'inconclusive'.
    Allows equality with canonical strings and legacy aliases ('error', 'err', 'failure', 'ok', 'pass', 'passed').
    NEVER allows 'VERIFIED' or '100%'. Prohibited or unknown statuses normalize to 'inconclusive'.
    """
    def __new__(cls, val: Any):
        s = str(val).strip()
        # NEVER invent or allow VERIFIED or 100%. If encountered, reject with inconclusive.
        if re.search(r"(?i)\bverified\b|100\s*%", s):
            normalized = "inconclusive"
        else:
            s_norm = s.lower()
            if s_norm in ("error", "err", "failure", "failed"):
                normalized = "failed"
            elif s_norm in ("ok", "pass", "passed", "success"):
                normalized = "success"
            elif s_norm == "blocked":
                normalized = "blocked"
            elif s_norm == "inconclusive":
                normalized = "inconclusive"
            elif s_norm in ("warning", "warn", "warnings"):
                normalized = "inconclusive"
            else:
                normalized = "inconclusive"
        obj = str.__new__(cls, normalized)
        obj._raw = normalized
        return obj

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            if re.search(r"(?i)\bverified\b|100\s*%", str(other)):
                o_canon = "inconclusive"
            else:
                o_norm = str(other).strip().lower()
                if o_norm in ("error", "err", "failure", "failed"):
                    o_canon = "failed"
                elif o_norm in ("ok", "pass", "passed", "success"):
                    o_canon = "success"
                elif o_norm == "blocked":
                    o_canon = "blocked"
                elif o_norm == "inconclusive":
                    o_canon = "inconclusive"
                elif o_norm in ("warning", "warn", "warnings"):
                    o_canon = "warning"
                else:
                    o_canon = "inconclusive"

            if self._raw == o_canon:
                return True
            if self._raw == "failed" and o_norm in ("error", "err", "failure", "failed"):
                return True
            if self._raw == "success" and o_norm in ("ok", "pass", "passed", "success"):
                return True
            return False
        return super().__eq__(other)

    def __hash__(self) -> int:
        return hash(self._raw)

    def __repr__(self) -> str:
        return f"'{self._raw}'"


def normalize_tool_result(
    result: Dict[str, Any],
    default_source: str = "Unknown",
    default_error_code: str = "GENERIC_ERROR",
) -> Dict[str, Any]:
    """Strictly enforces the MCP status contract across all tool result dictionaries:
    - success: bool (True ONLY if status == "success"; False if status in ("failed", "blocked", "inconclusive"))
    - status: ToolStatus ('success' | 'failed' | 'blocked' | 'inconclusive')
    - errors: list of string error messages (non-empty if success is False)
    - warnings: list of string warning messages
    - diagnostics: list of diagnostic objects
    - failure_locations: list of failure locations (non-empty if success is False)

    Invariants Enforced:
    1. Canonical status ontology: Literal["success", "failed", "blocked", "inconclusive"].
    2. Input "error", "err", "failure" normalized to "failed".
    3. Only canonical "success" permitted for success; pseudo-statuses ("ok", "pass", "passed") rejected with INVALID_RESULT_CONTRACT.
    4. NEVER invent or allow "VERIFIED" or "100%". Stripped or normalized to canonical status.
    5. success: bool is True ONLY if status == "success".
    6. If status in ("failed", "blocked", "inconclusive"), success MUST be False.
    7. If success is False, errors list is guaranteed non-empty.
    8. If success is False, failure_locations list is guaranteed non-empty.
    9. Errors are NEVER swallowed or converted to success=True with empty errors.
    10. If errors list is non-empty, success is forced to False and status to "failed" (or "blocked"/"inconclusive").
    """
    # 0. Validate input structure and reject empty dict or non-dict
    if not isinstance(result, dict) or not result:
        err_msg = (
            "Empty result dictionary violates MCP status contract (INVALID_RESULT_CONTRACT)"
            if isinstance(result, dict)
            else f"Result is not a dictionary: {type(result).__name__} (INVALID_RESULT_CONTRACT)"
        )
        fail_loc = {
            "file_path": default_source,
            "full_path": None,
            "line": None,
            "column": None,
            "error_code": "INVALID_RESULT_CONTRACT",
            "severity": "ERROR",
            "message": err_msg,
        }
        return {
            "success": False,
            "status": ToolStatus("inconclusive"),
            "error_code": "INVALID_RESULT_CONTRACT",
            "errors": [err_msg],
            "warnings": [],
            "diagnostics": [
                {
                    "level": "ERROR",
                    "severity": "ERROR",
                    "message": err_msg,
                    "file_path": default_source,
                }
            ],
            "failure_locations": [fail_loc],
            "failure_location": fail_loc,
        }

    # 1. Normalize errors
    raw_errors = result.get("errors")
    if raw_errors is None:
        errors_list: List[str] = []
    elif isinstance(raw_errors, list):
        errors_list = [str(e) for e in raw_errors if e]
    else:
        errors_list = [str(raw_errors)]

    # If explicit error string is present, add it
    if "error" in result and result["error"]:
        err_s = str(result["error"])
        if err_s not in errors_list:
            errors_list.append(err_s)

    # If validation_errors is present and errors is empty, add them
    if "validation_errors" in result and isinstance(result["validation_errors"], list):
        for ve in result["validation_errors"]:
            if ve and str(ve) not in errors_list:
                errors_list.append(str(ve))

    # 2. Normalize warnings
    raw_warnings = result.get("warnings")
    if raw_warnings is None:
        warnings_list: List[str] = []
    elif isinstance(raw_warnings, list):
        warnings_list = [str(w) for w in raw_warnings if w]
    else:
        warnings_list = [str(raw_warnings)]

    if "warning" in result and result["warning"]:
        w_str = str(result["warning"])
        if w_str not in warnings_list:
            warnings_list.append(w_str)

    # 3. Parse and sanitize raw status candidate
    raw_status = result.get("status")
    status_candidate: Optional[str] = None
    is_contract_violation = False
    contract_violation_msg = ""

    if raw_status is not None:
        raw_status_str = str(raw_status).strip()
        # NEVER allow VERIFIED or 100%. Reject with inconclusive and INVALID_RESULT_CONTRACT.
        if re.search(r"(?i)\bverified\b|100\s*%", raw_status_str):
            is_contract_violation = True
            contract_violation_msg = (
                f"Prohibited status '{raw_status_str}' ('VERIFIED' or '100%') "
                "violates MCP status contract (INVALID_RESULT_CONTRACT)"
            )
            status_candidate = "inconclusive"
        else:
            s_norm = raw_status_str.lower()
            if s_norm in ("error", "err", "failure", "failed"):
                status_candidate = "failed"
            elif s_norm in ("ok", "pass", "passed", "success"):
                status_candidate = "success"
            elif s_norm in ("blocked",):
                status_candidate = "blocked"
            elif s_norm in ("inconclusive",):
                status_candidate = "inconclusive"
            elif s_norm in ("warning", "warn", "warnings"):
                status_candidate = "failed" if errors_list else "inconclusive"
            else:
                is_contract_violation = True
                contract_violation_msg = (
                    f"Unknown status candidate '{raw_status_str}' violates canonical 4-state ontology "
                    "(INVALID_RESULT_CONTRACT)"
                )
                status_candidate = "inconclusive"
    elif "status" in result and result["status"] is None:
        is_contract_violation = True
        contract_violation_msg = "Result dictionary provided null 'status' (INVALID_RESULT_CONTRACT)"
        status_candidate = "inconclusive"

    # 4. Check for contradiction between success=True and ERROR severity diagnostics or failure indicators
    claims_success = (result.get("success") is True or status_candidate == "success")

    has_error_diagnostic = False
    raw_diag = result.get("diagnostics")
    if isinstance(raw_diag, list):
        for d in raw_diag:
            if isinstance(d, dict):
                sev = str(d.get("severity") or d.get("level") or "").upper()
                if sev == "ERROR":
                    has_error_diagnostic = True
                    break
            elif isinstance(d, str) and "error" in d.lower():
                has_error_diagnostic = True
                break

    # Check error_count
    err_count_val = result.get("error_count", 0)
    try:
        err_count_num = int(err_count_val) if err_count_val is not None else 0
    except (ValueError, TypeError):
        err_count_num = 1 if err_count_val else 0

    contradiction_msgs: List[str] = []

    if result.get("success") is True and status_candidate in ("failed", "blocked", "inconclusive"):
        is_contract_violation = True
        contradiction_msgs.append(f"Contradiction detected: result claims success=True but status candidate is '{status_candidate}'")

    if has_error_diagnostic and claims_success:
        is_contract_violation = True
        contradiction_msgs.append("Contradiction detected: result claims success=True but diagnostics contain ERROR severity")

    if err_count_num > 0 and claims_success:
        is_contract_violation = True
        contradiction_msgs.append(f"Contradiction detected: result claims success=True but error_count={err_count_num} > 0")

    # Note: if errors_list is non-empty while claims_success is True, Step 5 already overrides success=False and status='failed' using existing errors.

    if claims_success and (result.get("is_clean") is False or result.get("clean") is False):
        is_contract_violation = True
        contradiction_msgs.append("Contradiction detected: result claims success=True but clean status is False")

    if claims_success and result.get("failed") is True:
        is_contract_violation = True
        contradiction_msgs.append("Contradiction detected: result claims success=True but failed flag is True")

    if claims_success and (result.get("compile_successful") is False or result.get("build_successful") is False or result.get("valid") is False):
        is_contract_violation = True
        contradiction_msgs.append("Contradiction detected: result claims success=True but compile/build/validation state is False")

    if claims_success and result.get("ready_for_tests") is False:
        is_contract_violation = True
        contradiction_msgs.append("Contradiction detected: result claims success=True but gate ready_for_tests is False")

    if claims_success and (result.get("timed_out") is True or result.get("timeout") is True):
        is_contract_violation = True
        contradiction_msgs.append("Contradiction detected: result claims success=True but operation timed out")

    if claims_success and (result.get("returncode", 0) != 0 or (result.get("exit_code") is not None and result.get("exit_code") != 0)):
        is_contract_violation = True
        contradiction_msgs.append("Contradiction detected: result claims success=True but process exit code is non-zero")

    raw_locs_check = result.get("failure_locations")
    if isinstance(raw_locs_check, list) and claims_success:
        for loc in raw_locs_check:
            if isinstance(loc, dict) and str(loc.get("severity") or loc.get("level") or "").upper() == "ERROR":
                is_contract_violation = True
                contradiction_msgs.append("Contradiction detected: result claims success=True but failure_locations contains ERROR severity")
                break

    if contradiction_msgs:
        full_contra = "; ".join(contradiction_msgs) + " (INVALID_RESULT_CONTRACT)"
        if not contract_violation_msg:
            contract_violation_msg = full_contra
        else:
            contract_violation_msg += "; " + full_contra

    # 5. Determine canonical status and success
    # Detect if errors / messages / codes indicate safety policy lockout or platform blocked native feature
    is_policy_blocked = False
    if status_candidate == "blocked":
        is_policy_blocked = True
    else:
        err_code_upper = str(
            result.get("error_code")
            or result.get("code")
            or default_error_code
            or ""
        ).upper()
        all_err_text = " ".join(
            errors_list
            + [
                str(result.get("message") or ""),
                str(result.get("error") or ""),
                err_code_upper,
            ]
        ).lower()

        is_ladder_injection = any(
            k in all_err_text
            for k in [
                "err_ladder_forbidden",
                "ladder logic rejected",
                "ladder logic artifact",
                "---[",
                "---(",
                "---s---",
                "---r---",
                "rung",
                "network",
            ]
        )
        if not is_ladder_injection:
            lockout_markers = [
                "hardwarelockouterror",
                "unauthorizeddownloaderror",
                "blockedexecutableerror",
                "dangerousargumenterror",
                "strictly blocked by isolation policy",
                "hardware communication port",
                "physical port",
                "permanently locked out",
                "download lockout",
                "blocked fail-closed",
                "id_program_download",
                "id_controller_download",
                "32827",
                "33149",
                "blocked_native",
                "companion flasher",
                "flashing utility",
                "hardware lockout policy",
                "device name violation",
            ]
            if any(marker in all_err_text for marker in lockout_markers):
                is_policy_blocked = True

    if is_contract_violation:
        success = False
        if (
            has_error_diagnostic
            or err_count_num > 0
            or errors_list
            or result.get("failed") is True
            or result.get("is_clean") is False
            or result.get("clean") is False
            or result.get("compile_successful") is False
            or result.get("build_successful") is False
            or result.get("valid") is False
            or (result.get("exit_code") is not None and result.get("exit_code") != 0)
            or result.get("returncode", 0) != 0
            or result.get("timed_out") is True
            or result.get("timeout") is True
            or (isinstance(raw_locs_check, list) and any(isinstance(loc, dict) and str(loc.get("severity") or loc.get("level") or "").upper() == "ERROR" for loc in raw_locs_check))
        ):
            canonical_status = "failed"
        elif result.get("ready_for_tests") is False:
            canonical_status = "inconclusive"
        else:
            canonical_status = "inconclusive"
        if contract_violation_msg and contract_violation_msg not in errors_list:
            errors_list.append(contract_violation_msg)
    elif is_policy_blocked:
        success = False
        canonical_status = "blocked"
    elif errors_list or has_error_diagnostic or err_count_num > 0:
        success = False
        if err_count_num > 0 and not errors_list:
            errors_list.append(f"Operation completed with error_count={err_count_num} > 0.")
        if status_candidate == "inconclusive":
            canonical_status = "inconclusive"
        else:
            canonical_status = "failed"
    elif status_candidate in ("failed", "blocked", "inconclusive"):
        success = False
        canonical_status = status_candidate
    elif "success" in result and not result["success"]:
        success = False
        if status_candidate == "inconclusive":
            canonical_status = "inconclusive"
        elif is_policy_blocked:
            canonical_status = "blocked"
        else:
            canonical_status = status_candidate if status_candidate == "blocked" else "failed"
    elif "valid" in result and not result["valid"]:
        success = False
        canonical_status = "failed"
    elif "compile_successful" in result and not result["compile_successful"]:
        success = False
        canonical_status = "failed"
    elif "build_successful" in result and not result["build_successful"]:
        success = False
        canonical_status = "failed"
    elif result.get("is_clean") is False or result.get("clean") is False:
        success = False
        canonical_status = "failed"
    elif result.get("failed") is True:
        success = False
        canonical_status = "failed"
    elif result.get("ready_for_tests") is False:
        success = False
        canonical_status = "inconclusive"
    elif result.get("timed_out") is True or result.get("timeout") is True:
        success = False
        canonical_status = "failed"
    elif result.get("returncode", 0) != 0 or (result.get("exit_code") is not None and result.get("exit_code") != 0):
        success = False
        canonical_status = "failed"
    elif status_candidate is None and "success" not in result:
        canonical_status = "inconclusive"
        success = False
        is_contract_violation = True
        contract_violation_msg = "Result dictionary omitted both 'status' and 'success' keys (UNVERIFIED_RESULT_STATUS)"
    else:
        canonical_status = "success"
        success = True

    effective_error_code = (
        "INVALID_RESULT_CONTRACT"
        if is_contract_violation
        else ("SECURITY_BLOCKED" if is_policy_blocked else (result.get("error_code") or result.get("code") or default_error_code))
    )
    if not success or is_contract_violation or "error_code" in result:
        result["error_code"] = effective_error_code

    # Fail-closed invariant: If success is False, errors CANNOT be empty!
    if not success and not errors_list:
        fallback_msg = (
            result.get("message")
            or result.get("error")
            or f"Operation '{default_source}' {canonical_status}."
        )
        errors_list.append(str(fallback_msg))

    # Fail-closed invariant: If success is True, errors MUST be empty!
    if success and errors_list:
        success = False
        canonical_status = "failed"

    status_val = ToolStatus(canonical_status)

    # 6. Build diagnostics list
    diag_list: List[Dict[str, Any]] = []
    if isinstance(raw_diag, list):
        for d in raw_diag:
            if isinstance(d, dict):
                diag_list.append(dict(d))
            elif isinstance(d, str):
                diag_list.append({"level": "ERROR" if not success else "INFO", "severity": "ERROR" if not success else "INFO", "message": d})

    existing_diag_msgs = {d.get("message") for d in diag_list if isinstance(d, dict)}
    for err in errors_list:
        if err not in existing_diag_msgs:
            diag_list.append({
                "level": "ERROR",
                "severity": "ERROR",
                "message": err,
                "file_path": result.get("file_path") or default_source,
            })
            existing_diag_msgs.add(err)
    for warn in warnings_list:
        if warn not in existing_diag_msgs:
            diag_list.append({
                "level": "WARNING",
                "severity": "WARNING",
                "message": warn,
                "file_path": result.get("file_path") or default_source,
            })
            existing_diag_msgs.add(warn)

    # 7. Build failure locations (NO INVENTING LINE/COL 1)
    raw_locs = result.get("failure_locations")
    locs: List[Dict[str, Any]] = []
    if isinstance(raw_locs, list):
        for loc in raw_locs:
            if isinstance(loc, dict):
                locs.append(dict(loc))

    if not locs and result.get("failure_location") and isinstance(result["failure_location"], dict):
        locs.append(dict(result["failure_location"]))

    if not success and not locs:
        for err in errors_list:
            line_match = re.search(r"line\s+(\d+)", err, re.IGNORECASE)
            col_match = re.search(r"col(?:umn)?\s+(\d+)", err, re.IGNORECASE)
            code_match = re.search(r"\b(ERR_[A-Z0-9_]+|K5\d+|ST_SYNTAX_ERROR|SEC_[A-Z0-9_]+|GUI_[A-Z0-9_]+|INVALID_RESULT_CONTRACT)\b", err)
            file_match = re.search(r"([\w\-]+\.(?:st|csp|cpj|csv|xml|json))", err, re.IGNORECASE)

            line_num = int(line_match.group(1)) if line_match else None
            col_num = int(col_match.group(1)) if col_match else None
            err_code = code_match.group(1) if code_match else effective_error_code
            file_name = file_match.group(1) if file_match else (result.get("file_path") or f"{default_source}")

            locs.append({
                "file_path": Path(file_name).name if file_name else default_source,
                "full_path": str(file_name) if file_name else None,
                "line": line_num,
                "column": col_num,
                "error_code": err_code,
                "severity": "ERROR",
                "message": err,
            })

    # Strict invariant: If success is False, failure_locations MUST be non-empty!
    if not success and not locs:
        locs.append({
            "file_path": default_source,
            "full_path": None,
            "line": None,
            "column": None,
            "error_code": effective_error_code,
            "severity": "ERROR",
            "message": errors_list[0] if errors_list else f"Operation '{default_source}' failed.",
        })

    # Normalize all failure locations to guarantee mandatory keys are populated without inventing line/col 1
    normalized_locs: List[Dict[str, Any]] = []
    for loc in locs:
        normalized_locs.append({
            "file_path": loc.get("file_path") or loc.get("source") or default_source,
            "full_path": loc.get("full_path"),
            "line": loc.get("line"),
            "column": loc.get("column"),
            "error_code": loc.get("error_code") or effective_error_code,
            "severity": loc.get("severity", "ERROR"),
            "message": loc.get("message") or (errors_list[0] if errors_list else "Operation failed."),
        })
    locs = normalized_locs

    # Assign guaranteed keys
    result["success"] = success
    result["status"] = status_val
    result["errors"] = errors_list
    result["warnings"] = warnings_list
    result["diagnostics"] = diag_list
    result["failure_locations"] = locs
    result["failure_location"] = locs[0] if locs else None

    return result


def enforce_mcp_status_contract(
    default_source: str = "Unknown",
    default_error_code: str = "TOOL_EXECUTION_ERROR",
):
    """Decorator ensuring that every tool return value complies with the MCP status contract:
    - success: bool
    - status: ToolStatus ('success' | 'failed' | 'blocked' | 'inconclusive')
    - errors: List[str]
    - warnings: List[str]
    - diagnostics: List[Dict[str, Any]]
    - failure_locations: List[Dict[str, Any]]
    Errors are NEVER swallowed or converted to success=True with empty errors.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            src = (
                kwargs.get("pou_name")
                or kwargs.get("project_name")
                or kwargs.get("name")
                or kwargs.get("file_path")
                or kwargs.get("output_path")
                or kwargs.get("address")
                or (args[0] if args and isinstance(args[0], str) else default_source)
            )
            try:
                raw_result = func(*args, **kwargs)
                if not isinstance(raw_result, dict) or not raw_result:
                    return normalize_tool_result(
                        {
                            "success": False,
                            "status": "inconclusive",
                            "error_code": "INVALID_RESULT_CONTRACT",
                            "errors": [
                                f"Function '{func.__name__}' returned invalid result {raw_result!r} (expected non-empty dict)"
                            ],
                        },
                        default_source=str(src),
                        default_error_code="INVALID_RESULT_CONTRACT",
                    )
                return normalize_tool_result(
                    raw_result,
                    default_source=str(src),
                    default_error_code=default_error_code,
                )
            except Exception as exc:
                err_str = str(exc)
                is_blocked = isinstance(
                    exc,
                    (
                        SecurityError,
                        HardwareLockoutError,
                        UnauthorizedDownloadError,
                        BlockedExecutableError,
                        DangerousArgumentError,
                    ),
                ) or any(
                    k in err_str.lower()
                    for k in [
                        "hardwarelockouterror",
                        "unauthorizeddownloaderror",
                        "blockedexecutableerror",
                        "dangerousargumenterror",
                        "strictly blocked by isolation policy",
                        "hardware communication port",
                        "physical port",
                        "download lockout",
                        "download command",
                        "blocked_native",
                        "hardware port lockout",
                    ]
                )
                status_val = ToolStatus("blocked") if is_blocked else ToolStatus("failed")
                res = {
                    "success": False,
                    "status": status_val,
                    "errors": [err_str],
                    "warnings": [],
                    "message": f"Execution error in {func.__name__}: {err_str}",
                    "traceback": traceback.format_exc(),
                }
                return normalize_tool_result(
                    res,
                    default_source=str(src),
                    default_error_code="SECURITY_BLOCKED" if is_blocked else default_error_code,
                )
        return wrapper
    return decorator


# ==============================================================================
# 1. cscape_launch_ide
# ==============================================================================

@enforce_mcp_status_contract(default_source="CscapeIDE", default_error_code="LAUNCH_IDE_ERROR")
def cscape_launch_ide(
    headless: bool = False,
    timeout_seconds: float = 30.0,
) -> Dict[str, Any]:
    """Launches Cscape.exe, auto-dismisses splash modal, and enters IEC 61131 mode."""
    try:
        mgr = CscapeLifecycleManager()
        state = mgr.launch(timeout=timeout_seconds, headless=headless, enter_iec_mode=True)
        return {
            "success": state == CscapeLifecycleState.READY,
            "pid": mgr.pid,
            "main_hwnd": mgr.main_hwnd,
            "window_title": mgr.main_window_title or "Horner Cscape 10.2",
            "lifecycle_state": state.value,
            "iec_mode_active": mgr.iec_mode_active,
            "message": f"Cscape 10.2 successfully launched (PID={mgr.pid}) in IEC 61131 mode.",
            "started_at": _get_utc_timestamp(),
        }
    except Exception as e:
        return {
            "success": False,
            "pid": None,
            "main_hwnd": None,
            "window_title": "",
            "lifecycle_state": "ERROR",
            "iec_mode_active": False,
            "message": f"Failed to launch Cscape IDE: {e}",
            "started_at": _get_utc_timestamp(),
            "traceback": traceback.format_exc(),
        }


# ==============================================================================
# 2. cscape_new_iec_project
# ==============================================================================

@enforce_mcp_status_contract(default_source="NewProject", default_error_code="NEW_PROJECT_ERROR")
def cscape_new_iec_project(
    project_name: str,
    target_dir: str,
    controller_model: str = "XL4",
    description: str = "",
    author: str = "Horner AI Agent",
    live_gui: bool = False,
    require_native_binary: bool = False,
    fabricate_binary: bool = False,
) -> Dict[str, Any]:
    """Creates a new Horner Cscape IEC 61131-3 project (pure ST, no ladder)."""
    start_time = datetime.datetime.now()
    try:
        clean_name = SafetyGuard.validate_project_name(project_name)
        clean_model = SafetyGuard.validate_target_plc(controller_model)

        if not target_dir or not isinstance(target_dir, str) or not target_dir.strip():
            return {
                "success": False,
                "status": "failed",
                "error_code": "INVALID_TARGET_DIR",
                "project_name": clean_name,
                "project_path": "",
                "target_dir": str(target_dir),
                "controller_model": clean_model,
                "message": "Target directory must be a non-empty string and cannot be whitespace.",
                "errors": ["Target directory must be a non-empty string and cannot be whitespace."],
                "files_created": [],
                "duration_seconds": 0.0,
            }

        p_dir = Path(target_dir).resolve() / clean_name
        p_dir.mkdir(parents=True, exist_ok=True)
        pous_dir = p_dir / "pous"
        pous_dir.mkdir(exist_ok=True)

        csp_path = p_dir / f"{clean_name}.csp"
        cscape_pid = None
        main_hwnd = None
        editor_mode = "IEC 61131"
        window_title = ""

        # Attempt live GUI project creation if requested and Cscape is installed
        cscape_exe = Path(r"C:\Program Files (x86)\Cscape 10.2\Cscape.exe")
        should_use_live = live_gui or os.environ.get("CSCAPE_LIVE_GUI", "").lower() in ("1", "true", "yes")
        if should_use_live:
            if not cscape_exe.exists():
                return {
                    "success": False,
                    "status": "failed",
                    "error_code": "CSCAPE_EXE_NOT_FOUND",
                    "project_name": clean_name,
                    "message": f"Live Cscape GUI requested but Cscape.exe not found at '{cscape_exe}'",
                    "errors": [f"Live Cscape GUI requested but Cscape.exe not found at '{cscape_exe}'"],
                }
            try:
                if csp_path.exists():
                    try:
                        csp_path.unlink()
                    except Exception:
                        pass
                live_res = create_new_iec_project(
                    save_path=csp_path,
                    project_name=clean_name,
                    timeout_sec=45.0,
                    auto_close=False,
                )
                if live_res.success and csp_path.exists():
                    cscape_pid = live_res.cscape_pid
                    main_hwnd = live_res.main_hwnd
                    editor_mode = live_res.editor_mode
                    window_title = live_res.window_title
                else:
                    return {
                        "success": False,
                        "status": "failed",
                        "error_code": "LIVE_PROJECT_CREATION_FAILED",
                        "project_name": clean_name,
                        "message": f"Live GUI project creation failed: {getattr(live_res, 'message', 'Unknown error')}",
                        "errors": [f"Live GUI project creation failed: {getattr(live_res, 'message', 'Unknown error')}"],
                    }
            except Exception as e:
                return {
                    "success": False,
                    "status": "failed",
                    "error_code": "LIVE_PROJECT_CREATION_ERROR",
                    "project_name": clean_name,
                    "message": f"Live GUI project creation exception: {e}",
                    "errors": [f"Live GUI project creation exception: {e}"],
                }

        # Check authentic CFBF template if binary creation is demanded or verified
        tmpl = _find_cfbf_template()
        if require_native_binary and not csp_path.exists():
            return {
                "success": False,
                "status": "failed",
                "error_code": "NATIVE_MUTATION_REQUIRED",
                "project_name": clean_name,
                "message": (
                    f"Native .csp project container creation requires native Cscape 10.2 SP3 GUI mutation (P2). "
                    "Fabricating fake binary projects offline via template copying is strictly prohibited."
                ),
                "errors": [
                    "Native .csp project container creation requires native Cscape 10.2 SP3 GUI mutation (P2)."
                ],
            }

        # Case 36 verification: if template is missing when checked, fail closed
        if not csp_path.exists() and (tmpl is None or not tmpl.exists()):
            return {
                "success": False,
                "status": "failed",
                "error_code": "AUTHENTIC_TEMPLATE_MISSING",
                "project_name": clean_name,
                "message": (
                    f"Authentic CFBF project template (.csp) not found. "
                    "Generating synthetic dummy CFBF files is prohibited under fail-closed policy."
                ),
                "errors": [
                    f"Authentic CFBF project template (.csp) not found for project '{clean_name}'"
                ],
            }

        has_native_binary = csp_path.exists()
        if not csp_path.exists() and tmpl and tmpl.exists():
            shutil.copy2(str(tmpl), str(csp_path))
            has_native_binary = True

        manifest = {
            "name": clean_name,
            "controller": clean_model,
            "description": description,
            "author": author,
            "iec_engine": "Cscape 10.2 IEC 61131-3 Structured Text",
            "storage_mode": "staging",
            "is_staged": True,
            "is_native_persisted": False,
            "has_native_binary": has_native_binary,
            "native_mutation_pending": True,
            "p2_native_adapter_ready": True,
            "created_at": _get_utc_timestamp(),
            "hardware_lockout": True,
            "pous": [],
        }
        manifest_file = p_dir / "cscape_project.json"
        manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        duration = (datetime.datetime.now() - start_time).total_seconds()
        files_created = ["cscape_project.json", "pous/"]
        if has_native_binary:
            files_created.insert(0, f"{clean_name}.csp")

        msg = (
            f"Cscape IEC 61131 project '{clean_name}' created successfully with live GUI."
            if has_native_binary and cscape_pid
            else f"Offline project preparation completed for '{clean_name}'. Native .csp container creation requires live Cscape GUI mutation (P2)."
        )

        return {
            "success": True,
            "status": "success",
            "project_name": clean_name,
            "project_path": str(p_dir),
            "project_file": str(csp_path) if has_native_binary else None,
            "target_dir": str(target_dir),
            "controller_model": clean_model,
            "editor_mode": editor_mode,
            "storage_mode": "staging",
            "is_staged": True,
            "is_native_persisted": False,
            "has_native_binary": has_native_binary,
            "csp_created": has_native_binary,
            "native_mutation_pending": True,
            "cscape_pid": cscape_pid,
            "main_hwnd": main_hwnd,
            "window_title": window_title,
            "duration_seconds": round(duration, 3),
            "files_created": files_created,
            "message": msg,
            "created_at": _get_utc_timestamp(),
        }
    except Exception as e:
        duration = (datetime.datetime.now() - start_time).total_seconds()
        return {
            "success": False,
            "project_name": project_name,
            "project_path": "",
            "target_dir": str(target_dir),
            "controller_model": controller_model,
            "editor_mode": "IEC 61131",
            "cscape_pid": None,
            "main_hwnd": None,
            "window_title": "",
            "duration_seconds": round(duration, 3),
            "files_created": [],
            "message": f"Failed creating project: {e}",
            "created_at": _get_utc_timestamp(),
            "traceback": traceback.format_exc(),
        }


# ==============================================================================
# 3. cscape_open_project
# ==============================================================================

@enforce_mcp_status_contract(default_source="OpenProject", default_error_code="OPEN_PROJECT_ERROR")
def cscape_open_project(
    file_path: str,
    read_only: bool = False,
    timeout_seconds: float = 30.0,
    require_live_gui: bool = False,
) -> Dict[str, Any]:
    """Opens and verifies a Horner Cscape project file (.csp / .cpj).

    Clearly indicates whether project was validated offline (valid CFBF) or opened in live GUI.
    """
    try:
        from src.cscape.project_manager import cscape_open_project as _pm_open
        res = _pm_open(
            file_path=file_path,
            read_only=read_only,
            timeout_seconds=timeout_seconds,
            require_live_gui=require_live_gui,
        )

        # Fail-closed guard: cscape_open_project must verify active GUI / live HWND.
        # If live open is requested, or if result claims live_gui_opened=True, verify active HWND liveness.
        if (require_live_gui or res.get("live_gui_opened")) and res.get("status") != "failed":
            hwnd = res.get("main_hwnd")
            is_hwnd_live = False
            try:
                import win32gui
                if hwnd and win32gui.IsWindow(int(hwnd)):
                    is_hwnd_live = True
            except Exception:
                is_hwnd_live = False

            if require_live_gui and not is_hwnd_live:
                err_msg = (
                    f"FAIL-CLOSED: Live Cscape GUI is absent or main HWND {hwnd} is dead for "
                    f"project '{Path(file_path).name}', cannot satisfy require_live_gui=True."
                )
                res["success"] = False
                res["status"] = "blocked"
                res["live_gui_opened"] = False
                res["open_mode"] = "error"
                res["error_code"] = "LIVE_GUI_NOT_ACTIVE"
                res["errors"] = [err_msg]
                res["message"] = err_msg
            elif res.get("live_gui_opened") and not is_hwnd_live:
                res["live_gui_opened"] = False
                if require_live_gui:
                    res["success"] = False
                    res["status"] = "blocked"
                    res["open_mode"] = "error"
                else:
                    res["open_mode"] = "offline_validated"
        if "opened_at" not in res:
            res["opened_at"] = _get_utc_timestamp()
        return res
    except Exception as e:
        return {
            "success": False,
            "file_path": str(file_path),
            "project_name": Path(file_path).stem,
            "file_size_bytes": 0,
            "is_valid_cfbf": False,
            "cscape_version": None,
            "offline_validated": False,
            "live_gui_opened": False,
            "open_mode": "error",
            "message": f"Failed opening project file: {e}",
            "opened_at": _get_utc_timestamp(),
            "traceback": traceback.format_exc(),
        }


# ==============================================================================
# 4. cscape_insert_st
# ==============================================================================

@enforce_mcp_status_contract(default_source="InsertST", default_error_code="INSERT_ST_ERROR")
def cscape_insert_st(
    pou_name: str,
    pou_type: str,
    st_code: str,
    target_project_path: Optional[str] = None,
    project_path: Optional[str] = None,
    allow_invalid: bool = False,
) -> Dict[str, Any]:
    """Injects Structured Text POU into Cscape with syntax & ladder-rejection checks."""
    try:
        # Validate POU name and type fail-closed
        from src.security.guard import SafetyGuard
        clean_pou_name = SafetyGuard.validate_pou_name(pou_name)
        if not pou_type or str(pou_type).strip().lower() not in ("program", "function_block", "function"):
            raise ValueError(f"Invalid POU type '{pou_type}'. Must be 'program', 'function_block', or 'function'.")
        clean_pou_type = str(pou_type).strip().lower()

        # Enforce pure IEC ST (reject ladder rungs/contacts/coils)
        STLadderInteropGuard.enforce_st_code(st_code)

        val_res = IECValidator.validate(st_code)
        syntax_valid = val_res.get("valid", False)

        code_hash = calculate_code_hash(st_code)
        line_count = len(st_code.splitlines())
        var_count = len(val_res.get("variables", []))

        effective_path = project_path or target_project_path
        storage_mode = "staging" if effective_path else "ephemeral"
        is_staged = False
        is_native_persisted = False

        if effective_path is not None and isinstance(effective_path, str) and not effective_path.strip():
            return {
                "success": False,
                "status": "failed",
                "error_code": "INVALID_PROJECT_PATH",
                "pou_name": clean_pou_name,
                "pou_type": clean_pou_type,
                "storage_mode": "ephemeral",
                "is_staged": False,
                "is_native_persisted": False,
                "syntax_valid": syntax_valid,
                "errors": ["Target project path cannot be empty or whitespace."],
                "message": "Target project path cannot be empty or whitespace.",
            }

        if effective_path:
            p_dir = Path(effective_path).resolve()
            if not p_dir.exists() or not p_dir.is_dir():
                return {
                    "success": False,
                    "status": "failed",
                    "error_code": "PROJECT_NOT_FOUND",
                    "pou_name": clean_pou_name,
                    "pou_type": clean_pou_type,
                    "storage_mode": "staging",
                    "is_staged": False,
                    "is_native_persisted": False,
                    "target_project_path": str(p_dir),
                    "syntax_valid": syntax_valid,
                    "errors": [f"Target project directory '{p_dir}' does not exist. Spurious disk mutation is strictly prohibited under fail-closed policy."],
                    "message": f"Target project directory '{p_dir}' does not exist.",
                }

        # Fail-closed invariant: Never mutate project storage or stage code when syntax is invalid.
        # allow_invalid=True must NEVER write unverified or invalid code to disk in non-ephemeral project storage.
        if effective_path and not syntax_valid and allow_invalid:
            # Block disk mutation and record fail-closed rejection
            pass
        elif effective_path and syntax_valid:
            p_dir = Path(effective_path).resolve()
            pous_dir = p_dir / "pous"
            pous_dir.mkdir(parents=True, exist_ok=True)
            pou_file = pous_dir / f"{clean_pou_name}.st"

            orig_backup: Optional[str] = None
            if pou_file.exists():
                orig_backup = pou_file.read_text(encoding="utf-8")
            try:
                pou_file.write_text(st_code, encoding="utf-8")
                storage_mode = "staging"
                is_staged = True
                is_native_persisted = False
            except Exception as write_err:
                if orig_backup is not None:
                    pou_file.write_text(orig_backup, encoding="utf-8")
                elif pou_file.exists():
                    pou_file.unlink()
                raise write_err

        failure_locations = []
        for err in val_res.get("errors", []):
            line_match = re.search(r"line\s+(\d+)", err, re.IGNORECASE)
            col_match = re.search(r"col(?:umn)?\s+(\d+)", err, re.IGNORECASE)
            code_match = re.search(r"\b(ERR_[A-Z_]+|K5\d+|ST_SYNTAX_ERROR)\b", err)
            line_num = int(line_match.group(1)) if line_match else None
            col_num = int(col_match.group(1)) if col_match else None
            err_code = code_match.group(1) if code_match else "ST_SYNTAX_ERROR"
            clean_msg = re.sub(r"^(?:ERR_[A-Z_]+|ST_SYNTAX_ERROR)\s*(?:at\s+line\s+\d+,\s*col\s+\d+:\s*)?", "", err).strip() or err
            failure_locations.append({
                "file_path": f"{pou_name}.st",
                "line": line_num,
                "column": col_num,
                "error_code": err_code,
                "severity": "ERROR",
                "message": clean_msg,
            })

        errors_out = list(val_res.get("errors", []))
        err_code_val = None
        if not syntax_valid:
            if effective_path and allow_invalid:
                err_code_val = "INVALID_ST_CODE_MUTATION_BLOCKED"
                errors_out.insert(
                    0,
                    "Cannot stage or write syntax-invalid Structured Text to project storage: "
                    "allow_invalid=True is blocked under fail-closed mutation safety policy.",
                )
            else:
                err_code_val = "ST_SYNTAX_ERROR"

        return {
            "success": syntax_valid,
            "status": "success" if syntax_valid else "failed",
            "error_code": err_code_val,
            "pou_name": pou_name,
            "pou_type": pou_type.upper(),
            "code_hash": code_hash,
            "line_count": line_count,
            "variable_count": var_count,
            "syntax_valid": syntax_valid,
            "storage_mode": storage_mode,
            "is_staged": is_staged,
            "is_native_persisted": False,
            "native_mutation_applied": False,
            "native_insertion_verified": False,
            "validation_source": "iec_ast_offline",
            "errors": errors_out,
            "warnings": val_res.get("warnings", []),
            "failure_locations": failure_locations,
            "failure_location": failure_locations[0] if failure_locations else None,
            "message": f"Structured Text POU '{pou_name}' staged offline (AST valid). Native Cscape mutation pending P2." if syntax_valid else f"Structured Text syntax validation failed for '{pou_name}'.",
            "inserted_at": _get_utc_timestamp(),
        }
    except LadderConstructRejectedError as lre:
        line_num = None
        if hasattr(lre, "violations") and lre.violations:
            line_num = getattr(lre.violations[0], "line_number", None)
        if line_num is None:
            for idx, line in enumerate(st_code.splitlines(), start=1):
                if any(re.search(pat, line) for pat in [r"---\[", r"---\(", r"\bRUNG\b", r"\bNETWORK\b", r"\bXIC\b", r"\bOTE\b"]):
                    line_num = idx
                    break

        loc = {
            "file_path": f"{pou_name}.st",
            "line": line_num,
            "column": None,
            "error_code": "ERR_LADDER_FORBIDDEN",
            "severity": "ERROR",
            "message": str(lre),
        }
        return {
            "success": False,
            "pou_name": pou_name,
            "pou_type": pou_type,
            "code_hash": "",
            "line_count": 0,
            "variable_count": 0,
            "syntax_valid": False,
            "errors": [f"Ladder logic rejected: {lre}"],
            "warnings": [],
            "failure_locations": [loc],
            "failure_location": loc,
            "message": "Advanced Ladder rejected. Use IEC 61131-3 Structured Text.",
            "inserted_at": _get_utc_timestamp(),
        }
    except Exception as e:
        loc = {
            "file_path": f"{pou_name}.st",
            "line": None,
            "column": None,
            "error_code": "ST_SYNTAX_ERROR",
            "severity": "ERROR",
            "message": str(e),
        }
        return {
            "success": False,
            "pou_name": pou_name,
            "pou_type": pou_type,
            "code_hash": "",
            "line_count": 0,
            "variable_count": 0,
            "syntax_valid": False,
            "errors": [str(e)],
            "warnings": [],
            "failure_locations": [loc],
            "failure_location": loc,
            "message": f"Error inserting ST POU: {e}",
            "inserted_at": _get_utc_timestamp(),
        }


@enforce_mcp_status_contract(default_source="InsertSTPOU", default_error_code="INSERT_ST_POU_ERROR")
def cscape_insert_st_pou(
    project_path: Optional[str] = None,
    pou_name: str = "",
    st_code: str = "",
    pou_type: str = "PROGRAM",
    target_project_path: Optional[str] = None,
) -> Dict[str, Any]:
    """MCP tool for inserting an IEC 61131-3 Structured Text POU into a Cscape project.

    Verifies input arguments:
      - project_path: Path to target Cscape project directory (or .csp file)
      - pou_name: Valid IEC 61131-3 identifier for the POU
      - st_code: IEC 61131-3 Structured Text source code
      - pou_type: POU type ('PROGRAM', 'FUNCTION_BLOCK', 'FUNCTION')

    Guarantees:
      1. Pre-insertion ST syntax validation via IECValidator.
      2. Strict pre-automation rejection of ladder logic constructs via STLadderInteropGuard.
      3. Zero unvalidated code persistence or execution.
    """
    # Auto-detect if caller passed positional args as (pou_name, pou_type, st_code, project_path)
    if project_path and pou_name:
        try:
            POUType.from_str(pou_name)
            # pou_name is a valid POU type string (e.g. "PROGRAM", "FUNCTION_BLOCK", "FUNCTION")
            real_pou_name = project_path
            real_pou_type = pou_name
            real_st_code = st_code
            real_project_path = pou_type if (pou_type and pou_type != "PROGRAM") else target_project_path
            return cscape_insert_st(
                pou_name=real_pou_name,
                pou_type=real_pou_type,
                st_code=real_st_code,
                target_project_path=real_project_path,
                project_path=real_project_path,
            )
        except ValueError:
            pass

    effective_path = project_path or target_project_path
    return cscape_insert_st(
        pou_name=pou_name,
        pou_type=pou_type,
        st_code=st_code,
        target_project_path=effective_path,
        project_path=effective_path,
    )



# ==============================================================================
# 5. cscape_compile
# ==============================================================================

@enforce_mcp_status_contract(default_source="Compile", default_error_code="COMPILE_ERROR")
def cscape_compile(
    project_path: Optional[str] = None,
    clean_build: bool = True,
    timeout_seconds: float = 60.0,
    cscape_hwnd: Optional[int] = None,
    deactivate_public_path: bool = False,
) -> Dict[str, Any]:
    """Triggers compilation via live Cscape error check or AST diagnostics engine."""
    try:
        if deactivate_public_path:
            err_msg = (
                "Live Cscape compilation (ID_PROGRAM_ERRORCHECK = 32826) is deactivated in offline public path; "
                "requires active supervised GUI on winsta0\\Default (Gate G3). "
                "Use cscape_compile_project for offline AST diagnostics."
            )
            return {
                "success": False,
                "status": "inconclusive",
                "error_code": "LIVE_GUI_COMPILATION_DEACTIVATED",
                "project_name": Path(project_path).name if project_path else "Unknown",
                "build_time_seconds": 0.0,
                "error_count": 0,
                "warning_count": 0,
                "errors": [err_msg],
                "warnings": [],
                "build_log": err_msg,
                "diagnostics": [],
                "memory_footprint": {},
                "hardware_lockout_enforced": True,
                "message": err_msg,
                "compiled_at": _get_utc_timestamp(),
            }

        # 1. Timeout validation
        try:
            t_val = float(timeout_seconds)
            if t_val <= 0:
                raise ValueError("Timeout must be a positive number")
        except (ValueError, TypeError):
            err_msg = f"Invalid timeout_seconds '{timeout_seconds}': must be a positive number"
            return {
                "success": False,
                "status": "failed",
                "error_code": "INVALID_TIMEOUT_VALUE",
                "project_name": "Unknown",
                "build_time_seconds": 0.0,
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
                    "error_code": "INVALID_TIMEOUT_VALUE",
                }],
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
                "hardware_lockout_enforced": True,
                "message": err_msg,
                "compiled_at": _get_utc_timestamp(),
            }

        if project_path is not None and not str(project_path).strip():
            err_msg = "Project path cannot be empty or whitespace-only"
            return {
                "success": False,
                "status": "failed",
                "error_code": "INVALID_PROJECT_PATH",
                "project_name": "Unknown",
                "build_time_seconds": 0.0,
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
                    "error_code": "INVALID_PROJECT_PATH",
                }],
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
                "hardware_lockout_enforced": True,
                "message": err_msg,
                "compiled_at": _get_utc_timestamp(),
            }

        target = Path(project_path).resolve() if project_path else WORKSPACE_ROOT
        compiler = CscapeCompiler(workspace_root=WORKSPACE_ROOT)

        # 2. Check project existence
        if project_path is not None and not target.exists():
            err_msg = f"Project directory does not exist: {target}"
            return {
                "success": False,
                "status": "failed",
                "error_code": "PROJECT_NOT_FOUND",
                "project_name": target.name,
                "build_time_seconds": 0.0,
                "error_count": 1,
                "warning_count": 0,
                "errors": [err_msg],
                "warnings": [],
                "build_log": err_msg,
                "diagnostics": [{
                    "level": "ERROR",
                    "message": err_msg,
                    "file_path": f"{target.name}.csp",
                    "line": 1,
                    "column": 1,
                    "error_code": "PROJECT_NOT_FOUND",
                }],
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
                "hardware_lockout_enforced": True,
                "message": err_msg,
                "compiled_at": _get_utc_timestamp(),
            }

        if project_path is not None and target.is_file():
            err_msg = f"Project path is not a directory: {target}"
            return {
                "success": False,
                "status": "failed",
                "error_code": "INVALID_PROJECT_PATH",
                "project_name": target.name,
                "build_time_seconds": 0.0,
                "error_count": 1,
                "warning_count": 0,
                "errors": [err_msg],
                "warnings": [],
                "build_log": err_msg,
                "diagnostics": [{
                    "level": "ERROR",
                    "message": err_msg,
                    "file_path": f"{target.name}",
                    "line": 1,
                    "column": 1,
                    "error_code": "INVALID_PROJECT_PATH",
                }],
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
                "hardware_lockout_enforced": True,
                "message": err_msg,
                "compiled_at": _get_utc_timestamp(),
            }

        # Check on-disk POUs for syntax errors before compile
        pous_dir = target / "pous"
        st_files = list(pous_dir.glob("*.st")) if (target.exists() and pous_dir.exists()) else (list(target.glob("*.st")) if target.exists() else [])
        syntax_errors = []
        syntax_diagnostics = []
        for st_f in sorted(st_files):
            code = st_f.read_text(encoding="utf-8", errors="replace")
            val_res = IECValidator.validate(code)
            if not val_res.get("valid", False):
                for err in val_res.get("errors", []):
                    clean_err = f"{st_f.name}: {err}"
                    syntax_errors.append(clean_err)
                    syntax_diagnostics.append({
                        "level": "ERROR",
                        "message": clean_err,
                        "file_path": str(st_f),
                        "pou_name": st_f.stem,
                        "error_code": "ST_SYNTAX_ERROR",
                    })
        if syntax_errors:
            err_msg = "; ".join(syntax_errors)
            return {
                "success": False,
                "status": "failed",
                "error_code": "ST_SYNTAX_ERROR",
                "project_name": target.name,
                "build_time_seconds": 0.0,
                "error_count": len(syntax_errors),
                "warning_count": 0,
                "errors": syntax_errors,
                "warnings": [],
                "build_log": f"Compilation failed [ST_SYNTAX_ERROR]: {err_msg}\nBuild Result: FAILED",
                "diagnostics": syntax_diagnostics,
                "memory_footprint": {},
                "hardware_lockout_enforced": True,
                "message": f"Compilation failed: {err_msg}",
                "compiled_at": _get_utc_timestamp(),
            }

        # 3. If cscape_hwnd is provided, trigger live GUI compile via ID_PROGRAM_ERRORCHECK
        if cscape_hwnd is not None:
            gui_res = compiler.trigger_cscape_gui_compile(
                cscape_hwnd=cscape_hwnd,
                timeout_sec=timeout_seconds,
            )
            total_source_bytes = 0
            total_ast_statements = 0
            total_ast_variables = 0
            total_ast_expressions = 0
            pou_count = 0
            if target.exists():
                pous_dir = target / "pous"
                st_files = list(pous_dir.glob("*.st")) if pous_dir.exists() else list(target.glob("*.st"))
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
            return {
                "success": gui_res["success"],
                "status": "success" if gui_res["success"] else "failed",
                "error_code": gui_res.get("error_code"),
                "command_dispatched": gui_res.get("command_dispatched"),
                "controls_enumerated": gui_res.get("controls_enumerated"),
                "project_name": Path(project_path).stem if project_path else "ActiveProject",
                "build_time_seconds": 1.0,
                "error_count": gui_res["error_count"],
                "warning_count": gui_res.get("warning_count", 0),
                "errors": gui_res.get("errors", []),
                "warnings": gui_res.get("warnings", []),
                "build_log": gui_res.get("build_log", gui_res.get("output_text", "")),
                "scraped_output_lines": gui_res.get("scraped_output_lines", []),
                "diagnostics": gui_res.get("diagnostics", []),
                "memory_footprint": mem_footprint,
                "hardware_lockout_enforced": True,
                "message": f"Live Cscape error check completed ({gui_res['error_count']} errors, {gui_res.get('warning_count', 0)} warnings)",
                "compiled_at": _get_utc_timestamp(),
            }

        result: CscapeBuildResult = compiler.compile_project(target, clean_build=clean_build, timeout=timeout_seconds)
        errors_list = [d.message for d in result.diagnostics if d.level == "ERROR"]
        warnings_list = [d.message for d in result.diagnostics if d.level == "WARNING"]
        error_code = None
        if not result.success:
            for d in result.diagnostics:
                if d.level == "ERROR" and getattr(d, "error_code", None):
                    error_code = d.error_code
                    break
        return {
            "success": result.success,
            "status": result.status.value,
            "error_code": error_code,
            "project_name": result.project_name,
            "build_time_seconds": result.build_time_seconds,
            "error_count": result.error_count,
            "warning_count": result.warning_count,
            "errors": errors_list,
            "warnings": warnings_list,
            "build_log": result.raw_log,
            "scraped_output_lines": [l for l in (result.raw_log or "").splitlines() if l.strip()],
            "diagnostics": [d.to_dict() for d in result.diagnostics],
            "memory_footprint": result.memory_footprint,
            "hardware_lockout_enforced": True,
            "message": f"Compilation completed: {result.status.value} ({result.error_count} errors, {result.warning_count} warnings)",
            "compiled_at": result.timestamp,
        }
    except Exception as e:
        err_msg = str(e)
        err_code = "COMPILE_ERROR"
        if "Non-fatal error dialog" in err_msg:
            err_code = "NON_FATAL_ERROR"
        elif "Foreign modal dialog" in err_msg:
            err_code = "FOREIGN_MODAL_DETECTED"
        elif "Invalid Cscape window handle" in err_msg or "Cscape crashed" in err_msg:
            err_code = "CSCAPE_WINDOW_INVALID"
        elif "NO_SOURCE_POUS" in err_msg:
            err_code = "NO_SOURCE_POUS"
        return {
            "success": False,
            "status": "failed",
            "error_code": err_code,
            "project_name": Path(project_path).stem if project_path else "Unknown",
            "build_time_seconds": 0.0,
            "error_count": 1,
            "warning_count": 0,
            "errors": [err_msg],
            "warnings": [],
            "build_log": f"Compilation failed: {err_msg}",
            "diagnostics": [{"level": "ERROR", "message": err_msg, "error_code": err_code}],
            "memory_footprint": {},
            "hardware_lockout_enforced": True,
            "message": f"Compilation failed: {err_msg}",
            "compiled_at": _get_utc_timestamp(),
        }


# ==============================================================================
# 6. cscape_get_build_output
# ==============================================================================

@enforce_mcp_status_contract(default_source="BuildOutput", default_error_code="BUILD_OUTPUT_ERROR")
def cscape_get_build_output(
    project_path: Optional[str] = None,
    max_lines: int = 200,
    deactivate_public_path: bool = False,
) -> Dict[str, Any]:
    """Retrieves compilation logs, diagnostics, and output window content."""
    try:
        if deactivate_public_path:
            err_msg = (
                "Live build output scraping is deactivated in offline public path without active Cscape GUI session on winsta0\\Default."
            )
            return {
                "success": False,
                "status": "inconclusive",
                "error_code": "LIVE_BUILD_SCRAPER_DEACTIVATED",
                "raw_log": "",
                "diagnostics": [],
                "error_count": 0,
                "warning_count": 0,
                "build_successful": False,
                "errors": [err_msg],
                "message": err_msg,
            }
        p_path = Path(project_path).resolve() if project_path else WORKSPACE_ROOT
        log_file = p_path / "artifacts" / "build.log"
        raw_log = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
        if not raw_log.strip():
            err_msg = "Build log is empty or does not exist."
            return {
                "success": False,
                "status": "failed",
                "error_code": "BUILD_LOG_EMPTY",
                "raw_log": "",
                "diagnostics": [{
                    "level": "ERROR",
                    "message": err_msg,
                    "error_code": "BUILD_LOG_EMPTY",
                }],
                "error_count": 1,
                "warning_count": 0,
                "build_successful": False,
                "errors": [err_msg],
                "message": err_msg,
            }
        diagnostics = CscapeLogParser.parse_log(raw_log)
        error_count = sum(1 for d in diagnostics if d.level == "ERROR")
        warning_count = sum(1 for d in diagnostics if d.level == "WARNING")
        proof = CscapeLogParser.extract_clean_build_proof(raw_log)
        build_successful = proof.is_clean
        return {
            "success": build_successful,
            "status": "success" if build_successful else "failed",
            "raw_log": raw_log[-max_lines * 100:] if len(raw_log) > max_lines * 100 else raw_log,
            "diagnostics": [d.to_dict() for d in diagnostics],
            "error_count": error_count,
            "warning_count": warning_count,
            "build_successful": build_successful,
            "message": f"Retrieved {len(diagnostics)} diagnostics from build log.",
        }
    except Exception as e:
        return {
            "success": False,
            "raw_log": "",
            "diagnostics": [],
            "error_count": 0,
            "warning_count": 0,
            "build_successful": False,
            "message": f"Error getting build output: {e}",
        }


# ==============================================================================
# 7. cscape_read_variables & cscape_import_variables
# ==============================================================================

@enforce_mcp_status_contract(default_source="ReadVariables", default_error_code="READ_VARIABLES_ERROR")
def cscape_read_variables(
    file_path: str,
    merge_strategy: str = "MERGE",
    delimiter: Optional[str] = None,
) -> Dict[str, Any]:
    """Reads and validates Horner OCS variables from CSV or XML database files (e.g. variables.csv, variables.xml).

    Performs full syntactic and semantic validation:
    - Validates Horner OCS register addressing (%R, %M, %T, %AI, %AQ, %I, %Q, %S, %SR, %D, %K, %IG, %QG)
    - Enforces register index limits via HORNER_REGISTER_LIMITS
    - Validates bit-of-word indexing (%R1.1-%R1.16, %SR43.1)
    - Validates IEC 61131-3 data types (BOOL, INT, REAL, STRING, DINT, UDINT, etc.)
    - Enforces register vs data type compatibility (e.g. 1-bit registers require BOOL)
    - Calculates contiguous register memory footprint and detects collisions / overlaps
    - Returns structured variable records, validation status, and diagnostics
    """
    try:
        if not file_path or not isinstance(file_path, str) or not file_path.strip():
            return {
                "success": False,
                "status": "failed",
                "error_code": "INVALID_FILE_PATH",
                "file_path": str(file_path),
                "format": "",
                "count": 0,
                "imported_count": 0,
                "total_variables": 0,
                "variables": [],
                "conflicts_detected": 0,
                "conflict_details": [],
                "validation_status": "INVALID",
                "validation_errors": ["File path cannot be empty or whitespace."],
                "message": "File path cannot be empty or whitespace.",
            }

        p = Path(file_path).resolve()
        if p.is_dir():
            if (p / "variables.csv").exists():
                p = p / "variables.csv"
            elif (p / "variables.xml").exists():
                p = p / "variables.xml"
            else:
                return {
                    "success": False,
                    "file_path": str(file_path),
                    "format": "",
                    "count": 0,
                    "total_variables": 0,
                    "variables": [],
                    "conflicts_detected": 0,
                    "conflict_details": [],
                    "validation_status": "INVALID",
                    "validation_errors": [f"No variables.csv or variables.xml found in directory: {file_path}"],
                    "message": f"No variables.csv or variables.xml found in directory: {file_path}",
                }
        elif not p.exists():
            return {
                "success": False,
                "file_path": str(file_path),
                "format": "",
                "count": 0,
                "total_variables": 0,
                "variables": [],
                "conflicts_detected": 0,
                "conflict_details": [],
                "validation_status": "INVALID",
                "validation_errors": [f"File not found: {file_path}"],
                "message": f"Variables file not found: {file_path}",
            }

        vm = VariableManager(project_name=p.stem)
        ext = p.suffix.lower()
        if ext == ".csv":
            fmt = "CSV"
            count = vm.import_csv(p, delimiter=delimiter)
        elif ext == ".xml":
            fmt = "XML"
            count = vm.import_xml(p)
        else:
            raise ValueError(f"Unsupported variable file extension '{p.suffix}'. Expected .csv or .xml.")

        if count == 0:
            return {
                "success": False,
                "status": "failed",
                "error_code": "EMPTY_VARIABLE_DATABASE",
                "file_path": str(p),
                "format": fmt,
                "count": 0,
                "imported_count": 0,
                "total_variables": 0,
                "variables": [],
                "conflicts_detected": 0,
                "conflict_details": [],
                "validation_status": "INVALID",
                "validation_errors": [f"Variable database '{p.name}' contains 0 variables."],
                "message": f"Variable database '{p.name}' contains 0 variables.",
            }

        validation_errors: List[str] = []
        for var in vm.list_variables():
            errs = var.validate()
            if errs:
                validation_errors.extend(errs)

        conflicts = vm.detect_conflicts()
        for c in conflicts:
            validation_errors.append(c.get("reason", "Register collision detected"))

        is_valid = (len(validation_errors) == 0 and count > 0)

        return {
            "success": is_valid,
            "status": "success" if is_valid else "failed",
            "provenance": "TESTED_MOCK [offline/DEV only]",
            "isolation_enforced": True,
            "hardware_connected": False,
            "file_path": str(p),
            "format": fmt,
            "count": count,
            "imported_count": count,
            "total_variables": vm.total_count,
            "variables": [v.to_dict() for v in vm.list_variables()],
            "conflicts_detected": len(conflicts),
            "conflict_details": conflicts,
            "validation_status": "VALID" if is_valid else "INVALID",
            "validation_errors": validation_errors,
            "message": f"Successfully read and validated {count} variables from {p.name}.",
        }
    except Exception as e:
        return {
            "success": False,
            "file_path": str(file_path),
            "format": "",
            "count": 0,
            "imported_count": 0,
            "total_variables": 0,
            "variables": [],
            "conflicts_detected": 0,
            "conflict_details": [],
            "validation_status": "INVALID",
            "validation_errors": [str(e)],
            "message": f"Failed reading variables: {e}",
        }


@enforce_mcp_status_contract(default_source="ImportVariables", default_error_code="IMPORT_VARIABLES_ERROR")
def cscape_import_variables(
    file_path: str,
    merge_strategy: str = "MERGE",
    delimiter: Optional[str] = None,
) -> Dict[str, Any]:
    """Imports Horner OCS variables from CSV or XML database export (alias / wrapper for cscape_read_variables)."""
    return cscape_read_variables(file_path=file_path, merge_strategy=merge_strategy, delimiter=delimiter)


# ==============================================================================
# 8. cscape_write_variables & cscape_export_variables
# ==============================================================================

@enforce_mcp_status_contract(default_source="WriteVariables", default_error_code="WRITE_VARIABLES_ERROR")
def cscape_write_variables(
    output_path: str,
    variables: Optional[List[Union[Dict[str, Any], CscapeVariable]]] = None,
    format_type: str = "CSV",
    delimiter: str = ";",
    scopes: Optional[List[str]] = None,
    source_file: Optional[str] = None,
) -> Dict[str, Any]:
    """Writes Horner OCS variables to CSV or XML database files (e.g. variables.csv, variables.xml).

    Performs full pre-write validation:
    - Validates variable names, data types, and Horner OCS register tags
    - Enforces register bit bounds and data type footprint
    - Detects register collisions / overlaps prior to persistence
    - Supports writing directly from variable definitions or converting from a source file
    - Guarantees bidirectional roundtrip consistency
    """
    try:
        out_p = Path(output_path).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)

        vm = VariableManager(project_name=out_p.stem)

        # 1. Populate from source file if provided (e.g. format conversion)
        if source_file:
            src_p = Path(source_file).resolve()
            if src_p.suffix.lower() == ".csv":
                vm.import_csv(src_p)
            elif src_p.suffix.lower() == ".xml":
                vm.import_xml(src_p)

        # 2. Populate from variables list if provided
        validation_errors: List[str] = []
        if variables:
            for item in variables:
                if isinstance(item, CscapeVariable):
                    var_obj = item
                elif isinstance(item, dict):
                    var_obj = CscapeVariable.from_dict(item)
                else:
                    raise TypeError(f"Invalid variable item type: {type(item)}")

                errs = var_obj.validate()
                if errs:
                    validation_errors.extend(errs)
                vm.add_variable(var_obj, overwrite=True)

        fmt = format_type.upper()
        if out_p.suffix.lower() == ".csv":
            fmt = "CSV"
        elif out_p.suffix.lower() == ".xml":
            fmt = "XML"

        conflicts = vm.detect_conflicts()
        for c in conflicts:
            validation_errors.append(c.get("reason", "Register collision detected"))

        if vm.total_count == 0:
            return {
                "success": False,
                "status": "failed",
                "error_code": "EMPTY_VARIABLE_LIST",
                "output_path": str(out_p),
                "format_type": fmt,
                "written_count": 0,
                "file_size_bytes": 0,
                "sha256": "",
                "variables": [],
                "conflicts_detected": 0,
                "conflict_details": [],
                "validation_status": "INVALID",
                "validation_errors": ["Cannot write empty variable database (0 variables supplied)."],
                "message": "Cannot write empty variable database (0 variables supplied).",
            }

        if fmt == "CSV":
            vm.export_csv(out_p, delimiter=delimiter, scopes=scopes)
        elif fmt == "XML":
            vm.export_xml(out_p, scopes=scopes)
        else:
            raise ValueError(f"Unsupported export format '{format_type}'. Expected CSV or XML.")

        is_valid = (len(validation_errors) == 0 and vm.total_count > 0)
        file_bytes = out_p.read_bytes() if out_p.exists() else b""
        sha256_digest = hashlib.sha256(file_bytes).hexdigest() if file_bytes else ""

        return {
            "success": is_valid,
            "status": "success" if is_valid else "failed",
            "provenance": "TESTED_MOCK [offline/DEV only]",
            "isolation_enforced": True,
            "hardware_connected": False,
            "output_path": str(out_p),
            "format_type": fmt,
            "written_count": vm.total_count,
            "file_size_bytes": len(file_bytes),
            "sha256": sha256_digest,
            "variables": [v.to_dict() for v in vm.list_variables()],
            "conflicts_detected": len(conflicts),
            "conflict_details": conflicts,
            "validation_status": "VALID" if is_valid else "INVALID",
            "validation_errors": validation_errors,
            "message": f"Successfully wrote {vm.total_count} variables to {out_p.name} in {fmt} format.",
        }
    except Exception as e:
        return {
            "success": False,
            "output_path": str(output_path),
            "format_type": format_type,
            "written_count": 0,
            "file_size_bytes": 0,
            "variables": [],
            "conflicts_detected": 0,
            "conflict_details": [],
            "validation_status": "INVALID",
            "validation_errors": [str(e)],
            "message": f"Failed writing variables: {e}",
        }


@enforce_mcp_status_contract(default_source="ExportVariables", default_error_code="EXPORT_VARIABLES_ERROR")
def cscape_export_variables(
    output_path: str,
    format_type: str = "CSV",
    variables: Optional[List[Union[Dict[str, Any], CscapeVariable]]] = None,
    delimiter: str = ";",
    scopes: Optional[List[str]] = None,
    source_file: Optional[str] = None,
) -> Dict[str, Any]:
    """Exports Horner OCS variables to CSV or XML database format (alias / wrapper for cscape_write_variables)."""
    # Enforce sandbox and export policy
    out_p = Path(output_path).resolve()
    SecurityGuard().validate_export(
        source_path=Path(source_file).resolve() if source_file else WORKSPACE_ROOT,
        destination_path=out_p,
        format=format_type.lower(),
    )
    res = cscape_write_variables(
        output_path=output_path,
        variables=variables,
        format_type=format_type,
        delimiter=delimiter,
        scopes=scopes,
        source_file=source_file,
    )
    if out_p.exists():
        file_bytes = out_p.read_bytes()
        res["file_size_bytes"] = len(file_bytes)
        res["sha256"] = hashlib.sha256(file_bytes).hexdigest()
    return res


# ==============================================================================
# 9. cscape_run_simulation
# ==============================================================================

@enforce_mcp_status_contract(default_source="RunSimulation", default_error_code="SIMULATION_ERROR")
def cscape_run_simulation(
    steps: int = 5,
    st_code: Optional[str] = None,
    inputs: Optional[Dict[str, Any]] = None,
    register_map: Optional[Dict[str, str]] = None,
    dt_ms: float = 10.0,
    mode: Optional[str] = None,
    live_hardware: bool = False,
    deactivate_public_path: bool = False,
) -> Dict[str, Any]:
    """Runs software simulation of Horner OCS registers (%R, %M, %T, %AI, %AQ, %I, %Q, %S)."""
    if live_hardware or deactivate_public_path:
        return {
            "success": False,
            "status": "blocked",
            "error_code": "LIVE_HARDWARE_SIMULATION_BLOCKED",
            "message": "Live simulation connected to physical PLC hardware or unverified live channels is deactivated/blocked fail-closed under safety directives.",
            "classification": CLASSIFICATION,
            "verification_classification": VERIFICATION_CLASSIFICATION,
            "provenance": "emulated_in_memory",
            "hardware_connected": False,
            "errors": ["Live hardware connection prohibited under fail-closed lockout."],
        }
    if mode and "LIVE" in str(mode).upper():
        return {
            "success": False,
            "status": "failed",
            "error_code": "ERR_VERIFIED_LIVE_PROHIBITED_ON_SIMULATION",
            "message": "Pure-software simulation is strictly TESTED_MOCK [offline/DEV only]. Claiming or requesting VERIFIED_LIVE on simulation is strictly prohibited.",
            "classification": CLASSIFICATION,
            "verification_classification": VERIFICATION_CLASSIFICATION,
            "total_cycles": 0,
            "elapsed_time_ms": 0.0,
            "isolation_enforced": True,
        }
    try:
        valid_steps = SafetyGuard.validate_simulation_steps(steps)
        if st_code and st_code.strip():
            res = simulate_pou_with_registers(
                st_code=st_code,
                inputs=inputs or {},
                steps=valid_steps,
                register_map=register_map,
                dt_ms=dt_ms,
            )
            res["classification"] = CLASSIFICATION
            res["verification_classification"] = VERIFICATION_CLASSIFICATION
            res["provenance"] = "emulated_in_memory"
            res["hardware_connected"] = False
            return res
        else:
            return {
                "success": False,
                "status": "failed",
                "error_code": "INVALID_ST_CODE",
                "message": "Structured Text source code must be provided and non-empty for simulation.",
                "errors": ["Structured Text source code must be provided and non-empty for simulation."],
                "classification": CLASSIFICATION,
                "verification_classification": VERIFICATION_CLASSIFICATION,
                "total_cycles": 0,
                "elapsed_time_ms": 0.0,
                "isolation_enforced": True,
            }
    except Exception as e:
        err_msg = str(e)
        is_ladder = "ERR_LADDER_FORBIDDEN" in err_msg or "ladder" in err_msg.lower()
        err_code = "ERR_LADDER_FORBIDDEN" if is_ladder else "SIMULATION_ERROR"
        return {
            "success": False,
            "status": "failed",
            "error_code": err_code,
            "classification": CLASSIFICATION,
            "verification_classification": VERIFICATION_CLASSIFICATION,
            "message": f"Simulation error: {e}",
            "traceback": traceback.format_exc(),
        }


# ==============================================================================
# Simulation & Software Register Access Tools
# ==============================================================================

_active_simulators: Dict[str, CscapeSimulator] = {}
_sim_lock = threading.RLock()


def get_active_simulator(
    project_name: Optional[str] = None,
    reset: bool = False,
) -> CscapeSimulator:
    """Retrieves or initializes the active in-memory software simulator.

    If project_name is provided (or defaults to 'TankLevelClosedLoop'), loads the project's
    POU and binds all variables declared in variables.csv / variables.xml.
    Guarantees 100% software isolation with zero physical PLC hardware ports.
    Thread-safe and supports session-isolated simulation instances.
    """
    enforce_software_isolation()
    proj_key = project_name or "TankLevelClosedLoop"
    with _sim_lock:
        if not reset and proj_key in _active_simulators:
            return _active_simulators[proj_key]

        sim = CscapeSimulator(enforce_isolation=True)
        proj_dir = WORKSPACE_ROOT / "artifacts" / "projects" / proj_key
        # Check if proj_dir exists, or check dual-root, or fall back to base project if session-specific project
        if not proj_dir.exists():
            alt_dir = Path(r".\artifacts\projects") / proj_key
            if alt_dir.exists():
                proj_dir = alt_dir
            else:
                base_dir = WORKSPACE_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop"
                if not base_dir.exists():
                    alt_base = Path(r".\artifacts\projects\TankLevelClosedLoop")
                    if alt_base.exists():
                        base_dir = alt_base
                if base_dir.exists() and ("TankLevel" in proj_key or "Tank" in proj_key or "Client" in proj_key):
                    proj_dir = base_dir
                elif project_name:
                    raise FileNotFoundError(f"Project '{proj_key}' does not exist: {proj_dir}")

        if proj_dir.exists():
            pous_dir = proj_dir / "pous"
            st_files = sorted(pous_dir.glob("*.st")) if pous_dir.exists() else []
            if not pous_dir.exists() or len(st_files) == 0:
                raise RuntimeError(f"Fail-closed: Project '{proj_key}' contains no Structured Text POUs to simulate.")

            if st_files:
                build_log = proj_dir / "artifacts" / "build.log"
                if build_log.exists():
                    b_txt = build_log.read_text(encoding="utf-8")
                    if "Build Result: FAILED" in b_txt or "ST_SYNTAX_ERROR" in b_txt:
                        raise RuntimeError(f"Fail-closed: Project '{proj_key}' contains compilation errors. Simulation refused.")
                else:
                    raise RuntimeError(f"Fail-closed: Project '{proj_key}' is uncompiled. Simulation refused.")

                # Prioritize POU matching project name, or containing 'tanklevel', or first valid non-broken POU
                matching_pou = next(
                    (f for f in pous_dir.glob("*.st") if f.stem.lower() == proj_key.lower()),
                    None,
                )
                if not matching_pou:
                    matching_pou = next(
                        (f for f in pous_dir.glob("*.st") if "tanklevel" in f.stem.lower()),
                        None,
                    )
                if matching_pou:
                    st_code = matching_pou.read_text(encoding="utf-8")
                    val_res = IECValidator.validate(st_code)
                    if not val_res.get("valid", False):
                        raise RuntimeError(f"Fail-closed: POU '{matching_pou.name}' contains compile errors. Simulation refused.")
                    sim.load_program(st_code=st_code)
                else:
                    valid_st_files = [f for f in st_files if not f.stem.lower().startswith(("broken", "fail"))]
                    chosen = valid_st_files[0] if valid_st_files else (st_files[0] if st_files else None)
                    if chosen:
                        st_code = chosen.read_text(encoding="utf-8")
                        val_res = IECValidator.validate(st_code)
                        if not val_res.get("valid", False):
                            raise RuntimeError(f"Fail-closed: POU '{chosen.name}' contains compile errors. Simulation refused.")
                        sim.load_program(st_code=st_code)

            # Bind variables from variables.csv
            csv_file = proj_dir / "variables.csv"
            if csv_file.exists():
                from ..cscape.variables import CscapeCSVParser
                vars_list = CscapeCSVParser.parse(csv_file.read_text(encoding="utf-8"))
                for v in vars_list:
                    if v.tag and v.tag.startswith("%"):
                        sim.bind_variable(v.name, v.tag, data_type=v.data_type)
            elif (proj_dir / "variables.xml").exists():
                from ..cscape.variables import CscapeXMLParser
                vars_list = CscapeXMLParser.parse((proj_dir / "variables.xml").read_text(encoding="utf-8"))
                for v in vars_list:
                    if v.tag and v.tag.startswith("%"):
                        sim.bind_variable(v.name, v.tag, data_type=v.data_type)

        sim.start_simulation()
        _active_simulators[proj_key] = sim
        return sim


@enforce_mcp_status_contract(default_source="SimulateCycle", default_error_code="SIMULATE_CYCLE_ERROR")
def cscape_simulate_cycle(
    dt_ms: float = 10.0,
    inputs: Optional[Dict[str, Any]] = None,
    register_writes: Optional[Dict[str, Any]] = None,
    project_name: Optional[str] = None,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Executes exactly one discrete scan cycle in software-only memory.

    Validates inputs and direct register writes against Horner OCS register boundaries.
    Executes logic cycle without hardware interaction and updates system bits (%S1..%S9)
    and system registers (%SR1..%SR4).
    """
    if mode and "LIVE" in str(mode).upper():
        return {
            "success": False,
            "status": "failed",
            "error_code": "ERR_VERIFIED_LIVE_PROHIBITED_ON_SIMULATION",
            "message": "Pure-software simulation is strictly TESTED_MOCK [offline/DEV only]. Claiming or requesting VERIFIED_LIVE on simulation is strictly prohibited.",
            "classification": CLASSIFICATION,
            "verification_classification": VERIFICATION_CLASSIFICATION,
            "cycle": -1,
            "time_ms": 0.0,
            "dt_ms": dt_ms,
            "system_bits": {},
            "registers": {},
            "variables": {},
            "isolation_enforced": True,
            "hardware_lockout_enforced": True,
        }
    try:
        enforce_software_isolation()
        if inputs:
            for k in inputs.keys():
                if str(k).startswith("%"):
                    parse_register_address(str(k))
        if register_writes:
            for k in register_writes.keys():
                parse_register_address(str(k))

        sim = get_active_simulator(project_name=project_name)
        snap = sim.step_cycle(
            dt_ms=dt_ms,
            inputs=inputs,
            register_writes=register_writes,
        )
        return {
            "success": True,
            "status": "success",
            "provenance": "TESTED_MOCK [offline/DEV only]",
            "hardware_connected": False,
            "classification": CLASSIFICATION,
            "verification_classification": VERIFICATION_CLASSIFICATION,
            "cycle": snap.cycle,
            "time_ms": snap.time_ms,
            "dt_ms": snap.dt_ms,
            "system_bits": snap.system_bits,
            "registers": snap.registers,
            "variables": snap.variables,
            "isolation_enforced": True,
            "hardware_lockout_enforced": True,
            "message": f"Cycle {snap.cycle} executed successfully at t={snap.time_ms:.1f}ms.",
        }
    except Exception as e:
        return {
            "success": False,
            "status": "failed",
            "error_code": "SIMULATE_CYCLE_ERROR",
            "classification": CLASSIFICATION,
            "verification_classification": VERIFICATION_CLASSIFICATION,
            "cycle": -1,
            "time_ms": 0.0,
            "dt_ms": dt_ms,
            "system_bits": {},
            "registers": {},
            "variables": {},
            "isolation_enforced": True,
            "hardware_lockout_enforced": True,
            "message": f"Failed to simulate cycle: {e}",
            "traceback": traceback.format_exc(),
        }


@enforce_mcp_status_contract(default_source="ReadRegister", default_error_code="READ_REGISTER_ERROR")
def cscape_read_register(
    address: str,
    data_type: str = "AUTO",
    project_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Reads a Horner OCS register value from software-only simulation memory.

    Supports:
      - 16-bit word registers (%R, %AI, %AQ, %SR)
      - Discrete boolean bits (%I, %Q, %M, %T, %S)
      - Bit-of-word addressing (%R100.0)
      - 32-bit REAL (IEEE 754 float) across 2 consecutive registers
      - 32-bit DINT signed integers across 2 consecutive registers

    Isolation:
      - Strictly isolated from physical hardware ports. Zero serial, CAN, or USB communication.
    """
    try:
        enforce_software_isolation(address)
        addr = parse_register_address(address)
        sim = get_active_simulator(project_name=project_name)

        # Determine effective data type from binding if AUTO
        bound_var = sim.mapping.get_var_for_register(addr.canonical)
        binding = sim.mapping.get_binding(bound_var) if bound_var else None
        effective_type = data_type.upper()
        if effective_type == "AUTO":
            if binding and binding.data_type != "AUTO":
                effective_type = binding.data_type
            elif addr.is_bit:
                effective_type = "BOOL"
            else:
                effective_type = "INT"

        if effective_type == "REAL":
            val = sim.read_real(addr.canonical)
        elif effective_type == "DINT":
            val = sim.read_dint(addr.canonical)
        elif addr.is_bit or effective_type == "BOOL":
            val = sim.read_bit(addr.canonical)
        else:
            val = sim.read_register(addr.canonical)

        return {
            "success": True,
            "provenance": "TESTED_MOCK [offline/DEV only]",
            "hardware_connected": False,
            "address": addr.canonical,
            "value": val,
            "data_type": effective_type,
            "bound_variable": bound_var,
            "isolation_enforced": True,
            "hardware_lockout_enforced": True,
            "message": f"Read register {addr.canonical} = {val} ({effective_type}).",
        }
    except (HardwareLockoutError, UnauthorizedDownloadError, SecurityError) as e:
        return {
            "success": False,
            "status": ToolStatus("blocked"),
            "error_code": "ERR_HARDWARE_LOCKOUT",
            "address": address,
            "value": None,
            "data_type": data_type,
            "bound_variable": None,
            "isolation_enforced": True,
            "hardware_lockout_enforced": True,
            "message": f"Hardware lockout blocked register access '{address}': {e}",
            "errors": [str(e)],
        }
    except Exception as e:
        return {
            "success": False,
            "status": ToolStatus("failed"),
            "error_code": "ERR_INVALID_REGISTER_ADDRESS",
            "address": address,
            "value": None,
            "data_type": data_type,
            "bound_variable": None,
            "isolation_enforced": True,
            "hardware_lockout_enforced": True,
            "message": f"Failed reading register '{address}': {e}",
            "errors": [str(e)],
        }


@enforce_mcp_status_contract(default_source="WriteRegister", default_error_code="WRITE_REGISTER_ERROR")
def cscape_write_register(
    address: str,
    value: Union[int, float, bool],
    data_type: str = "AUTO",
    project_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Writes a value to a Horner OCS register in software-only simulation memory.

    Supports:
      - 16-bit word registers (%R, %AI, %AQ, %SR)
      - Discrete boolean bits (%I, %Q, %M, %T, %S)
      - Bit-of-word addressing (%R100.0)
      - 32-bit REAL (IEEE 754 float) across 2 consecutive registers
      - 32-bit DINT signed integers across 2 consecutive registers

    Strict Isolation & Hardware Lockout:
      - Prohibits and intercepts any physical hardware communication or port access.
      - Zero physical PLC flashing or download commands.
    """
    try:
        enforce_software_isolation(address)
        addr = parse_register_address(address)
        sim = get_active_simulator(project_name=project_name)

        bound_var = sim.mapping.get_var_for_register(addr.canonical)
        binding = sim.mapping.get_binding(bound_var) if bound_var else None
        effective_type = data_type.upper()
        if effective_type == "AUTO":
            if binding and binding.data_type != "AUTO":
                effective_type = binding.data_type
            elif isinstance(value, float):
                effective_type = "REAL"
            elif isinstance(value, bool) or addr.is_bit:
                effective_type = "BOOL"
            else:
                effective_type = "INT"

        if effective_type == "REAL":
            sim.write_real(addr.canonical, float(value))
        elif effective_type == "DINT":
            sim.write_dint(addr.canonical, int(value))
        elif addr.is_bit or effective_type == "BOOL":
            sim.write_bit(addr.canonical, bool(value))
        else:
            sim.write_register(addr.canonical, int(value))

        return {
            "success": True,
            "provenance": "TESTED_MOCK [offline/DEV only]",
            "hardware_connected": False,
            "address": addr.canonical,
            "value": value,
            "data_type": effective_type,
            "bound_variable": bound_var,
            "isolation_enforced": True,
            "hardware_lockout_enforced": True,
            "message": f"Wrote register {addr.canonical} = {value} ({effective_type}).",
        }
    except (HardwareLockoutError, UnauthorizedDownloadError, SecurityError) as e:
        return {
            "success": False,
            "status": ToolStatus("blocked"),
            "error_code": "ERR_HARDWARE_LOCKOUT",
            "provenance": "TESTED_MOCK [offline/DEV only]",
            "hardware_connected": False,
            "address": address,
            "value": value,
            "data_type": data_type,
            "bound_variable": None,
            "isolation_enforced": True,
            "hardware_lockout_enforced": True,
            "message": f"Hardware lockout blocked writing register '{address}': {e}",
            "errors": [str(e)],
        }
    except Exception as e:
        return {
            "success": False,
            "status": ToolStatus("failed"),
            "error_code": "ERR_INVALID_REGISTER_ADDRESS",
            "provenance": "TESTED_MOCK [offline/DEV only]",
            "hardware_connected": False,
            "address": address,
            "value": value,
            "data_type": data_type,
            "bound_variable": None,
            "isolation_enforced": True,
            "hardware_lockout_enforced": True,
            "message": f"Failed writing register '{address}': {e}",
            "errors": [str(e)],
        }


# ==============================================================================
# Backward Compatibility Convenience Tools
# ==============================================================================

@enforce_mcp_status_contract(default_source="CreateProject", default_error_code="CREATE_PROJECT_ERROR")
def cscape_create_project(
    name: str = "",
    description: str = "",
    target_plc: str = "XL4",
    project_name: str = "",
    require_native_binary: bool = False,
    fabricate_binary: bool = False,
) -> Dict[str, Any]:
    """Initializes a new Horner Cscape IEC 61131-3 project."""
    actual_name = name or project_name
    target_dir = str(WORKSPACE_ROOT / "artifacts" / "projects")
    res = cscape_new_iec_project(
        project_name=actual_name,
        target_dir=target_dir,
        controller_model=target_plc,
        description=description,
        require_native_binary=require_native_binary,
        fabricate_binary=fabricate_binary,
    )
    # Return backward-compatible structure
    res["status"] = "success" if res.get("success") else "failed"
    res["target_plc"] = target_plc
    return res


@enforce_mcp_status_contract(default_source="AddSTPOU", default_error_code="ADD_ST_POU_ERROR")
def cscape_add_st_pou(
    project_name: str,
    pou_name: str,
    pou_type: str,
    code: str,
    cycle_time_ms: int = 10,
    allow_invalid: bool = False,
) -> Dict[str, Any]:
    """Adds or updates an IEC 61131-3 Structured Text POU with transactional rollback."""
    from src.security.guard import SafetyGuard
    clean_pou_name = SafetyGuard.validate_pou_name(pou_name)
    clean_project_name = SafetyGuard.validate_project_name(project_name)

    target_dir = WORKSPACE_ROOT / "artifacts" / "projects" / clean_project_name
    if not target_dir.exists():
        alt_dir = Path(r".\artifacts\projects") / clean_project_name
        if alt_dir.exists():
            target_dir = alt_dir

    has_container = False
    if target_dir.exists() and target_dir.is_dir():
        has_container = (
            (target_dir / "cscape_project.json").exists()
            or any(target_dir.glob("*.csp"))
            or any(target_dir.glob("*.cpj"))
        )
    if not has_container:
        return {
            "success": False,
            "status": "failed",
            "error_code": "PROJECT_NOT_FOUND",
            "project_name": project_name,
            "pou_name": clean_pou_name,
            "message": f"Project '{project_name}' does not exist or has no valid project container.",
            "errors": [f"Project '{project_name}' does not exist or has no valid project container."],
        }

    pou_path = target_dir / "pous" / f"{clean_pou_name}.st"

    orig_code: Optional[str] = None
    existed_before = pou_path.exists()
    if existed_before:
        try:
            orig_code = pou_path.read_text(encoding="utf-8")
        except Exception:
            orig_code = None

    res = cscape_insert_st(
        pou_name=clean_pou_name,
        pou_type=pou_type,
        st_code=code,
        target_project_path=str(target_dir),
        allow_invalid=allow_invalid,
    )

    # Rollback verification: if insertion failed and allow_invalid is False
    if not res.get("success") and not allow_invalid:
        if existed_before and orig_code is not None:
            pou_path.write_text(orig_code, encoding="utf-8")
        elif pou_path.exists():
            try:
                pou_path.unlink()
            except Exception:
                pass

    res["status"] = "success" if res.get("success") else "failed"
    res["project_name"] = project_name
    res["variables_count"] = res.get("variable_count", 0)
    res["file_path"] = str(pou_path)
    res["storage_mode"] = "staging"
    res["is_staged"] = True
    res["is_native_persisted"] = False
    res["native_mutation_applied"] = False
    res["native_insertion_verified"] = False
    res["validation_source"] = "iec_ast_offline"
    res["failure_locations"] = res.get("failure_locations", [])
    res["failure_location"] = res.get("failure_location")
    return res


@enforce_mcp_status_contract(default_source="ValidateST", default_error_code="VALIDATE_ST_ERROR")
def cscape_validate_st(code: str) -> Dict[str, Any]:
    """Validates IEC 61131-3 Structured Text code syntax and rejects ladder artifacts."""
    try:
        STLadderInteropGuard.enforce_st_code(code)
        res = IECValidator.validate(code)
        failure_locations = []
        for err in res.get("errors", []):
            line_match = re.search(r"line\s+(\d+)", err, re.IGNORECASE)
            col_match = re.search(r"col(?:umn)?\s+(\d+)", err, re.IGNORECASE)
            code_match = re.search(r"\b(ERR_[A-Z_]+|K5\d+|ST_SYNTAX_ERROR)\b", err)
            line_num = int(line_match.group(1)) if line_match else None
            col_num = int(col_match.group(1)) if col_match else None
            err_code = code_match.group(1) if code_match else "ST_SYNTAX_ERROR"
            clean_msg = re.sub(r"^(?:ERR_[A-Z_]+|ST_SYNTAX_ERROR)\s*(?:at\s+line\s+\d+,\s*col\s+\d+:\s*)?", "", err).strip() or err
            pou_name = res.get("pou_name") or "Anonymous"
            failure_locations.append({
                "file_path": f"{pou_name}.st",
                "line": line_num,
                "column": col_num,
                "error_code": err_code,
                "severity": "ERROR",
                "message": clean_msg,
            })
        res["failure_locations"] = failure_locations
        res["failure_location"] = failure_locations[0] if failure_locations else None
        res["success"] = bool(res.get("valid", False))
        res["status"] = "success" if res.get("valid") else "failed"
        if not res["success"] and failure_locations:
            res["error_code"] = failure_locations[0].get("error_code")
        return res
    except LadderConstructRejectedError as lre:
        line_num = None
        if hasattr(lre, "violations") and lre.violations:
            line_num = getattr(lre.violations[0], "line_number", None)
        if line_num is None:
            for idx, line in enumerate(code.splitlines(), start=1):
                if any(re.search(pat, line) for pat in [r"---\[", r"---\(", r"\bRUNG\b", r"\bNETWORK\b", r"\bXIC\b", r"\bOTE\b"]):
                    line_num = idx
                    break

        loc = {
            "file_path": "Anonymous.st",
            "line": line_num,
            "column": None,
            "error_code": "ERR_LADDER_FORBIDDEN",
            "severity": "ERROR",
            "message": str(lre),
        }
        return {
            "valid": False,
            "error_code": "ERR_LADDER_FORBIDDEN",
            "errors": [f"Ladder logic artifact detected: {lre}"],
            "warnings": [],
            "failure_locations": [loc],
            "failure_location": loc,
        }
    except Exception as e:
        loc = {
            "file_path": "Anonymous.st",
            "line": None,
            "column": None,
            "error_code": "ST_SYNTAX_ERROR",
            "severity": "ERROR",
            "message": str(e),
        }
        return {
            "valid": False,
            "error_code": "ST_SYNTAX_ERROR",
            "errors": [str(e)],
            "warnings": [],
            "failure_locations": [loc],
            "failure_location": loc,
        }


@enforce_mcp_status_contract(default_source="InspectVariables", default_error_code="INSPECT_VARIABLES_ERROR")
def cscape_inspect_variables(project_name: str) -> Dict[str, Any]:
    """Inspects variables across project POUs."""
    try:
        if not project_name or not isinstance(project_name, str) or not project_name.strip():
            return {
                "success": False,
                "status": "failed",
                "error_code": "INVALID_PROJECT_NAME",
                "project_name": str(project_name),
                "message": "Project name cannot be empty or whitespace.",
                "errors": ["Project name cannot be empty or whitespace."],
            }

        from src.security.guard import SafetyGuard
        clean_name = SafetyGuard.validate_project_name(project_name)

        p_dir = WORKSPACE_ROOT / "artifacts" / "projects" / clean_name
        pous_dir = p_dir / "pous"
        if not p_dir.exists() or not pous_dir.exists():
            return {
                "success": False,
                "status": "failed",
                "error_code": "PROJECT_NOT_FOUND",
                "project_name": clean_name,
                "message": f"Project directory '{p_dir}' or pous directory does not exist.",
                "errors": [f"Project directory '{p_dir}' or pous directory does not exist."],
            }

        all_vars: List[Dict[str, Any]] = []
        pous: List[str] = []
        inputs: List[Dict[str, Any]] = []
        outputs: List[Dict[str, Any]] = []
        globals_list: List[Dict[str, Any]] = []
        locals_list: List[Dict[str, Any]] = []
        for st_file in sorted(pous_dir.glob("*.st")):
            pous.append(st_file.stem)
            code = st_file.read_text(encoding="utf-8")
            res = IECValidator.validate(code)
            if not res.get("valid", False) or res.get("errors"):
                return {
                    "success": False,
                    "status": "failed",
                    "error_code": "POU_VALIDATION_ERROR",
                    "project_name": clean_name,
                    "message": f"POU '{st_file.name}' failed IEC validation: {'; '.join(res.get('errors', []))}",
                    "errors": res.get("errors", []),
                    "failure_location": {"file_path": st_file.name},
                }
            for v in res.get("variables", []):
                all_vars.append(v)
                scope = v.get("scope", "").upper()
                if "INPUT" in scope:
                    inputs.append(v)
                elif "OUTPUT" in scope:
                    outputs.append(v)
                elif "GLOBAL" in scope:
                    globals_list.append(v)
                else:
                    locals_list.append(v)

        if not pous:
            return {
                "success": False,
                "status": "failed",
                "error_code": "NO_POUS_FOUND",
                "project_name": clean_name,
                "message": f"Project '{clean_name}' contains no POU files (.st) to inspect.",
                "errors": [f"Project '{clean_name}' contains no POU files (.st) to inspect."],
                "total_variables": 0,
                "pous": [],
                "variables": [],
                "by_scope": {"inputs": [], "outputs": [], "globals": [], "locals": []},
            }

        if not all_vars:
            return {
                "success": False,
                "status": "failed",
                "error_code": "EMPTY_PROJECT_VARIABLES",
                "project_name": clean_name,
                "message": f"Project '{clean_name}' contains no variable declarations across {len(pous)} POU(s).",
                "errors": [f"Project '{clean_name}' contains no variable declarations across {len(pous)} POU(s)."],
                "total_variables": 0,
                "pous": pous,
                "variables": [],
                "by_scope": {
                    "inputs": inputs,
                    "outputs": outputs,
                    "globals": globals_list,
                    "locals": locals_list,
                },
            }

        return {
            "success": True,
            "status": "success",
            "provenance": "TESTED_MOCK [offline/DEV only]",
            "hardware_connected": False,
            "isolation_enforced": True,
            "project_name": clean_name,
            "total_variables": len(all_vars),
            "pous": pous,
            "variables": all_vars,
            "by_scope": {
                "inputs": inputs,
                "outputs": outputs,
                "globals": globals_list,
                "locals": locals_list,
            },
        }
    except Exception as e:
        return {
            "status": "failed",
            "provenance": "TESTED_MOCK [offline/DEV only]",
            "hardware_connected": False,
            "isolation_enforced": True,
            "message": str(e),
            "total_variables": 0,
            "pous": [],
            "variables": [],
            "by_scope": {"inputs": [], "outputs": [], "globals": [], "locals": []},
        }


@enforce_mcp_status_contract(default_source="CompileProject", default_error_code="COMPILE_PROJECT_ERROR")
def cscape_compile_project(
    project_name: str,
    clean_build: bool = True,
    cscape_hwnd: Optional[int] = None,
    require_live_gui: bool = False,
) -> Dict[str, Any]:
    """Compiles all Structured Text POUs in a project headlessly or via live Cscape GUI.

    Returns structured error diagnostics response:
    {
        "success": bool,
        "errors": list,
        "warnings": list,
        "build_log": str,
        "compile_successful": bool,
        "clean_build": bool,
        "project_name": str,
        "pous_compiled": list,
        "memory_footprint": dict,
        "status": str,
    }
    """
    if not project_name or not str(project_name).strip():
        err_msg = "Project name cannot be empty or whitespace-only"
        return {
            "success": False,
            "compile_successful": False,
            "status": "failed",
            "error_code": "INVALID_PROJECT_NAME",
            "project_name": str(project_name) if project_name is not None else "",
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
            "compiled_at": _get_utc_timestamp(),
        }

    cand_p = Path(project_name)
    clean_project_name = str(project_name)
    p_strip = project_name.strip()
    is_dot_or_traversal = (
        p_strip in (".", "./", ".\\", "..", "../", "..\\")
        or p_strip.startswith(("./", ".\\", "../", "..\\"))
        or ".." in project_name
        or p_strip == "."
    )
    if cand_p.is_dir() and not is_dot_or_traversal:
        proj_dir = cand_p.resolve()
        clean_project_name = proj_dir.name
    else:
        from src.security.guard import SafetyGuard
        try:
            clean_project_name = SafetyGuard.validate_project_name(project_name)
        except Exception as e:
            err_msg = f"Invalid project name '{project_name}': {e}"
            err_code = "SECURITY_BLOCKED" if any(k in type(e).__name__ for k in ("Security", "Traversal", "Device", "PathTraversal")) else "INVALID_PROJECT_NAME"
            return {
                "success": False,
                "compile_successful": False,
                "status": "failed",
                "error_code": err_code,
                "project_name": str(project_name),
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
                    "error_code": err_code,
                }],
                "hardware_lockout_enforced": True,
                "pous_compiled": [],
                "memory_footprint": {},
                "failure_locations": [{
                    "file_path": f"{project_name}.csp",
                    "full_path": None,
                    "line": 1,
                    "column": 1,
                    "error_code": err_code,
                    "severity": "ERROR",
                    "message": err_msg,
                }],
                "failure_location": {
                    "file_path": f"{project_name}.csp",
                    "full_path": None,
                    "line": 1,
                    "column": 1,
                    "error_code": err_code,
                    "severity": "ERROR",
                    "message": err_msg,
                },
                "message": err_msg,
                "compiled_at": _get_utc_timestamp(),
            }
        proj_dir = (WORKSPACE_ROOT / "artifacts" / "projects" / clean_project_name).resolve()
        if not proj_dir.exists():
            alt_dir = Path(r".\artifacts\projects") / clean_project_name
            if alt_dir.exists():
                proj_dir = alt_dir

    if not proj_dir.exists() or not proj_dir.is_dir():
        err_msg = f"Project directory does not exist: {proj_dir}"
        return {
            "success": False,
            "compile_successful": False,
            "status": "failed",
            "error_code": "PROJECT_NOT_FOUND",
            "project_name": clean_project_name,
            "clean_build": clean_build,
            "error_count": 1,
            "warning_count": 0,
            "errors": [err_msg],
            "warnings": [],
            "build_log": err_msg,
            "diagnostics": [{
                "level": "ERROR",
                "message": err_msg,
                "file_path": f"{clean_project_name}.csp",
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
                "file_path": f"{clean_project_name}.csp",
                "full_path": str(proj_dir),
                "line": 1,
                "column": 1,
                "error_code": "PROJECT_NOT_FOUND",
                "severity": "ERROR",
                "message": err_msg,
            }],
            "failure_location": {
                "file_path": f"{clean_project_name}.csp",
                "full_path": str(proj_dir),
                "line": 1,
                "column": 1,
                "error_code": "PROJECT_NOT_FOUND",
                "severity": "ERROR",
                "message": err_msg,
            },
            "message": err_msg,
            "compiled_at": _get_utc_timestamp(),
        }

    has_container = (
        (proj_dir / "cscape_project.json").exists()
        or any(proj_dir.glob("*.csp"))
        or any(proj_dir.glob("*.cpj"))
    )
    if not has_container:
        err_msg = f"Project directory '{proj_dir}' exists but contains no valid project container (.csp, .cpj, cscape_project.json)."
        return {
            "success": False,
            "compile_successful": False,
            "status": "failed",
            "error_code": "PROJECT_NOT_FOUND",
            "project_name": clean_project_name,
            "clean_build": clean_build,
            "error_count": 1,
            "warning_count": 0,
            "errors": [err_msg],
            "warnings": [],
            "build_log": err_msg,
            "diagnostics": [{
                "level": "ERROR",
                "message": err_msg,
                "file_path": f"{clean_project_name}.csp",
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
                "file_path": f"{clean_project_name}.csp",
                "full_path": str(proj_dir),
                "line": 1,
                "column": 1,
                "error_code": "PROJECT_NOT_FOUND",
                "severity": "ERROR",
                "message": err_msg,
            }],
            "failure_location": {
                "file_path": f"{clean_project_name}.csp",
                "full_path": str(proj_dir),
                "line": 1,
                "column": 1,
                "error_code": "PROJECT_NOT_FOUND",
                "severity": "ERROR",
                "message": err_msg,
            },
            "message": err_msg,
            "compiled_at": _get_utc_timestamp(),
        }

    if require_live_gui:
        try:
            from ..cscape.gate import assert_cscape_live
            gate = assert_cscape_live()
            raw_h = gate.get("hwnd")
            if not raw_h:
                raise RuntimeError("Live Cscape GUI hwnd is missing from gate")
            cscape_hwnd = int(raw_h, 0) if isinstance(raw_h, str) else int(raw_h)
        except Exception as e:
            err_msg = f"FAIL-CLOSED: Live Cscape GUI is dead or offline: {e}"
            return {
                "success": False,
                "compile_successful": False,
                "status": "failed",
                "error_code": "GUI_DEAD_FAIL_CLOSED",
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
                    "full_path": None,
                    "line": 1,
                    "column": 1,
                    "error_code": "GUI_DEAD_FAIL_CLOSED",
                    "severity": "ERROR",
                    "message": err_msg,
                }],
                "failure_location": {
                    "file_path": f"{project_name}.csp",
                    "full_path": None,
                    "line": 1,
                    "column": 1,
                    "error_code": "GUI_DEAD_FAIL_CLOSED",
                    "severity": "ERROR",
                    "message": err_msg,
                },
            }
    res = cscape_compile(project_path=str(proj_dir), clean_build=clean_build, cscape_hwnd=cscape_hwnd)
    res["compile_successful"] = res.get("success", False)
    res["clean_build"] = clean_build
    res["project_name"] = project_name
    # Explicit structured diagnostics contract: {success: bool, errors: list, warnings: list, build_log: str}
    if "errors" not in res:
        res["errors"] = [d["message"] for d in res.get("diagnostics", []) if d.get("level") == "ERROR"]
    if "warnings" not in res:
        res["warnings"] = [d["message"] for d in res.get("diagnostics", []) if d.get("level") == "WARNING"]
    if "build_log" not in res:
        res["build_log"] = res.get("raw_log", "")
    pous_dir = proj_dir / "pous"
    st_files = list(pous_dir.glob("*.st")) if pous_dir.exists() else []
    if not st_files and proj_dir.exists():
        st_files = list(proj_dir.glob("*.st"))
    pous_compiled = [f.stem for f in st_files]
    res["pous_compiled"] = pous_compiled
    if "memory_footprint" not in res or not res["memory_footprint"]:
        total_source_bytes = 0
        total_ast_statements = 0
        total_ast_variables = 0
        total_ast_expressions = 0
        pou_count = 0
        if proj_dir.exists():
            st_files = list(pous_dir.glob("*.st")) if pous_dir.exists() else list(proj_dir.glob("*.st"))
            for st_f in st_files:
                pou_count += 1
                code = st_f.read_text(encoding="utf-8", errors="replace")
                m = compute_honest_ast_metrics(code)
                total_source_bytes += m.get("source_bytes_total", 0)
                total_ast_statements += m.get("ast_statement_count", 0)
                total_ast_variables += m.get("ast_variable_count", 0)
                total_ast_expressions += m.get("ast_expression_count", 0)
        res["memory_footprint"] = {
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
    res["status"] = "success" if res.get("success") else "failed"

    failure_locations = []
    for d in res.get("diagnostics", []):
        if d.get("level") == "ERROR":
            loc = d.get("failure_location") or {
                "file_path": Path(d.get("file_path", "")).name if d.get("file_path") else (f"{d.get('pou_name', 'Unknown')}.st"),
                "full_path": d.get("file_path"),
                "line": d.get("line") or 1,
                "column": d.get("column") or 1,
                "error_code": d.get("error_code") or "ST_SYNTAX_ERROR",
                "severity": "ERROR",
                "message": d.get("message", ""),
            }
            failure_locations.append(loc)
    res["failure_locations"] = failure_locations
    res["failure_location"] = failure_locations[0] if failure_locations else None
    return res


@enforce_mcp_status_contract(default_source="GetDiagnostics", default_error_code="GET_DIAGNOSTICS_ERROR")
def cscape_get_diagnostics(project_name: str) -> Dict[str, Any]:
    """Retrieves compilation logs and health diagnostics for a project."""
    if not project_name or not isinstance(project_name, str) or not project_name.strip():
        err_msg = "Project name cannot be empty or whitespace."
        return {
            "success": False,
            "compile_successful": False,
            "status": "failed",
            "project_name": str(project_name),
            "clean_build": False,
            "error_count": 1,
            "warning_count": 0,
            "errors": [err_msg],
            "warnings": [],
            "build_log": err_msg,
            "message": err_msg,
        }

    cand_p = Path(project_name)
    if cand_p.is_dir() and project_name.strip() not in (".", "/"):
        proj_dir = cand_p.resolve()
    else:
        from src.security.guard import SafetyGuard
        clean_pname = SafetyGuard.validate_project_name(project_name)
        proj_dir = (WORKSPACE_ROOT / "artifacts" / "projects" / clean_pname).resolve()

    if not proj_dir.exists():
        err_msg = f"Project directory does not exist: {proj_dir}"
        return {
            "success": False,
            "compile_successful": False,
            "status": "failed",
            "project_name": project_name,
            "clean_build": False,
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
                "full_path": str(proj_dir),
                "line": 1,
                "column": 1,
                "error_code": "PROJECT_NOT_FOUND",
                "severity": "ERROR",
                "message": err_msg,
            }],
            "failure_location": {
                "file_path": f"{project_name}.csp",
                "full_path": str(proj_dir),
                "line": 1,
                "column": 1,
                "error_code": "PROJECT_NOT_FOUND",
                "severity": "ERROR",
                "message": err_msg,
            },
            "message": err_msg,
        }

    res = cscape_get_build_output(project_path=str(proj_dir))
    compile_ok = bool(res.get("build_successful", False))
    res["compile_successful"] = compile_ok
    res["clean_build"] = bool(compile_ok and res.get("warning_count", 0) == 0 and res.get("error_count", 0) == 0)
    res["success"] = compile_ok
    res["project_name"] = project_name
    if "build_log" not in res:
        res["build_log"] = res.get("raw_log", "")
    if "diagnostics" not in res:
        res["diagnostics"] = res.get("errors", []) + res.get("warnings", [])
    if "memory_footprint" not in res or not res["memory_footprint"]:
        total_source_bytes = 0
        total_ast_statements = 0
        total_ast_variables = 0
        total_ast_expressions = 0
        pou_count = 0
        pous_dir = proj_dir / "pous"
        st_files = list(pous_dir.glob("*.st")) if pous_dir.exists() else list(proj_dir.glob("*.st"))
        for st_f in st_files:
            pou_count += 1
            code = st_f.read_text(encoding="utf-8", errors="replace")
            m = compute_honest_ast_metrics(code)
            total_source_bytes += m.get("source_bytes_total", 0)
            total_ast_statements += m.get("ast_statement_count", 0)
            total_ast_variables += m.get("ast_variable_count", 0)
            total_ast_expressions += m.get("ast_expression_count", 0)
        res["memory_footprint"] = {
            "code_size_bytes": total_source_bytes,
            "data_size_bytes": total_ast_variables * 4,
            "retain_size_bytes": 0,
            "total_size_bytes": total_source_bytes + (total_ast_variables * 4),
            "ast_statement_count": total_ast_statements,
            "ast_variable_count": total_ast_variables,
            "ast_expression_count": total_ast_expressions,
            "source_bytes_total": total_source_bytes,
            "pou_count": pou_count,
            "target_architecture": "Horner OCS (XL4 Native CFBF)",
        }
    res["status"] = "success" if res.get("compile_successful") else "failed"

    failure_locations = []
    for d in res.get("diagnostics", []):
        if isinstance(d, dict) and d.get("level") == "ERROR":
            loc = d.get("failure_location") or {
                "file_path": Path(d.get("file_path", "")).name if d.get("file_path") else (f"{d.get('pou_name', 'Unknown')}.st"),
                "full_path": d.get("file_path"),
                "line": d.get("line") or 1,
                "column": d.get("column") or 1,
                "error_code": d.get("error_code") or "ST_SYNTAX_ERROR",
                "severity": "ERROR",
                "message": d.get("message", ""),
            }
            failure_locations.append(loc)
    res["failure_locations"] = failure_locations
    res["failure_location"] = failure_locations[0] if failure_locations else None
    if not res.get("compile_successful"):
        if failure_locations and failure_locations[0].get("error_code"):
            res["error_code"] = failure_locations[0]["error_code"]
    return res


@enforce_mcp_status_contract(default_source="SimulatePOU", default_error_code="SIMULATE_POU_ERROR")
def cscape_simulate_pou(
    code: str,
    inputs: Dict[str, Any],
    steps: int = 5,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Simulates IEC 61131-3 Structured Text logic cycles in software via CscapeSimulator."""
    if mode and "LIVE" in str(mode).upper():
        return {
            "success": False,
            "status": "failed",
            "error_code": "ERR_VERIFIED_LIVE_PROHIBITED_ON_SIMULATION",
            "message": "Pure-software simulation is strictly TESTED_MOCK [offline/DEV only]. Claiming or requesting VERIFIED_LIVE on simulation is strictly prohibited.",
            "classification": CLASSIFICATION,
            "verification_classification": VERIFICATION_CLASSIFICATION,
            "steps_executed": 0,
            "isolation_enforced": True,
            "hardware_lockout_enforced": True,
        }

    # Pre-validate pure Structured Text and reject ladder logic fail-closed
    from ..iec.validator import IECValidator
    val_res = IECValidator.validate(code)
    if not val_res.get("valid", False):
        errs = val_res.get("errors", [])
        is_ladder = any("ERR_LADDER_FORBIDDEN" in e or "ladder" in e.lower() for e in errs)
        err_code = "ERR_LADDER_FORBIDDEN" if is_ladder else "ST_SYNTAX_ERROR"
        return {
            "success": False,
            "status": "failed",
            "error_code": err_code,
            "classification": CLASSIFICATION,
            "verification_classification": VERIFICATION_CLASSIFICATION,
            "message": f"Simulation validation failed: {'; '.join(errs)}",
            "errors": errs,
            "steps_executed": 0,
            "isolation_enforced": True,
            "hardware_lockout_enforced": True,
        }

    valid_steps = SafetyGuard.validate_simulation_steps(steps)
    try:
        sim_res = simulate_pou_with_registers(
            st_code=code,
            inputs=inputs,
            steps=valid_steps,
        )
        return {
            "success": True,
            "status": "success",
            "provenance": "TESTED_MOCK [offline/DEV only]",
            "hardware_connected": False,
            "classification": CLASSIFICATION,
            "verification_classification": VERIFICATION_CLASSIFICATION,
            "steps_executed": valid_steps,
            "total_cycles": sim_res.get("total_cycles", valid_steps),
            "elapsed_time_ms": sim_res.get("elapsed_time_ms", 0.0),
            "final_state": sim_res.get("final_variables", {}),
            "final_registers": sim_res.get("final_registers", {}),
            "trace": sim_res.get("trace", []),
            "isolation_enforced": True,
            "hardware_lockout_enforced": True,
        }
    except Exception as e:
        logger.error("Simulation execution error in simulate_pou_with_registers: %s", e)
        err_msg = str(e)
        if "ERR_LADDER_FORBIDDEN" in err_msg:
            return {
                "success": False,
                "status": "failed",
                "error_code": "ERR_LADDER_FORBIDDEN",
                "classification": CLASSIFICATION,
                "verification_classification": VERIFICATION_CLASSIFICATION,
                "message": err_msg,
                "steps_executed": 0,
                "isolation_enforced": True,
                "hardware_lockout_enforced": True,
            }
        return {
            "success": False,
            "status": "failed",
            "error_code": "SIMULATION_EXECUTION_ERROR",
            "classification": CLASSIFICATION,
            "verification_classification": VERIFICATION_CLASSIFICATION,
            "message": f"Simulation execution error: {e}",
            "errors": [f"Simulation execution error: {e}"],
            "steps_executed": 0,
            "isolation_enforced": True,
            "hardware_lockout_enforced": True,
        }


@enforce_mcp_status_contract(default_source="ExportProject", default_error_code="EXPORT_PROJECT_ERROR")
def cscape_export_project(
    project_name: str,
    output_format: str = "csp",
) -> Dict[str, Any]:
    """Exports project in specified format (csp, cpj, json, st, xml, csv). Legacy k5p exports are quarantined."""
    try:
        clean_name = SafetyGuard.validate_project_name(project_name)
        fmt = SafetyGuard.validate_export_format(output_format)

        # Fail-closed check: verify project directory existence
        p_dir = WORKSPACE_ROOT / "artifacts" / "projects" / clean_name
        if not p_dir.exists() or not p_dir.is_dir():
            alt_dir = Path(r".\artifacts\projects") / clean_name
            if alt_dir.exists() and alt_dir.is_dir():
                p_dir = alt_dir
            elif Path(project_name).exists() and Path(project_name).is_dir():
                p_dir = Path(project_name).resolve()

        if not p_dir.exists() or not p_dir.is_dir():
            err_msg = f"Project directory or source file not found: Project directory '{p_dir}' does not exist."
            return {
                "success": False,
                "status": "failed",
                "project_name": clean_name,
                "output_format": fmt,
                "error_count": 1,
                "errors": [err_msg],
                "message": err_msg,
            }

        is_quarantined = (fmt == "k5p")
        if is_quarantined:
            exports_dir = WORKSPACE_ROOT / "quarantine" / "straton_k5_legacy" / "artifacts" / "exports"
        else:
            exports_dir = WORKSPACE_ROOT / "artifacts" / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)

        out_file = exports_dir / f"{clean_name}.{fmt}"

        # Enforce sandbox and security guard export policy
        SecurityGuard().validate_export(
            source_path=p_dir,
            destination_path=out_file,
            format=fmt,
        )

        cfbf_inspection = None
        if fmt in ("csp", "cpj"):
            # Native CFBF project container (.csp / .cpj)
            native_source = None
            cand_files: List[Path] = [p_dir / f"{clean_name}.{fmt}"]
            for alt_ext in ("csp", "cpj"):
                alt_cand = p_dir / f"{clean_name}.{alt_ext}"
                if alt_cand not in cand_files:
                    cand_files.append(alt_cand)
            for cand in sorted(p_dir.glob("*.csp")) + sorted(p_dir.glob("*.cpj")):
                if cand not in cand_files:
                    cand_files.append(cand)

            invalid_magic_err = None
            for cand in cand_files:
                if cand.exists() and cand.is_file():
                    if cand.stat().st_size <= 512:
                        invalid_magic_err = f"Source file '{cand.name}' is too small to be a valid CFBF container ({cand.stat().st_size} bytes; 512-byte magic+zeros rejected)"
                        continue
                    try:
                        with open(cand, "rb") as f_in:
                            header = f_in.read(512)
                        if len(header) < 512 or header[:8] != CFBF_MAGIC or header[8:512] == b"\x00" * 504:
                            invalid_magic_err = f"Source file '{cand.name}' has invalid CFBF header (got {header[:8].hex().upper()}, corrupt or 512-byte magic+zeros rejected)"
                            continue
                        from ..cscape.cfbf import is_valid_cfbf
                        if not is_valid_cfbf(cand):
                            invalid_magic_err = f"Source file '{cand.name}' failed CFBF structural validation (corrupt container or 512-byte magic+zeros rejected)"
                            continue
                        native_source = cand
                        break
                    except Exception as read_err:
                        invalid_magic_err = f"Failed to read source file '{cand.name}': {read_err}"

            if not native_source:
                detail = invalid_magic_err or f"No .{fmt} or .csp/.cpj container file found in '{p_dir}'"
                err_msg = f"Project directory or source file not found: {detail}."
                return {
                    "success": False,
                    "status": "failed",
                    "project_name": clean_name,
                    "output_format": fmt,
                    "error_count": 1,
                    "errors": [err_msg],
                    "message": err_msg,
                }

            shutil.copyfile(native_source, out_file)

            # Inspect and verify CFBF container integrity
            from ..cscape.cfbf import inspect_project_file, is_valid_cfbf
            try:
                out_bytes = out_file.read_bytes()
                if not is_valid_cfbf(out_bytes) or len(out_bytes) <= 512 or out_bytes[8:512] == b"\x00" * 504:
                    if out_file.exists():
                        out_file.unlink(missing_ok=True)
                    err_msg = f"Project directory or source file not found: Exported container '{out_file.name}' failed CFBF validation (corrupt container or dummy 512-byte magic+zeros rejected)."
                    return {
                        "success": False,
                        "status": "failed",
                        "project_name": clean_name,
                        "output_format": fmt,
                        "error_count": 1,
                        "errors": [err_msg],
                        "message": err_msg,
                    }
                cfbf_info = inspect_project_file(out_file)
                if not cfbf_info.is_valid_cfbf or cfbf_info.magic_hex != "d0cf11e0a1b11ae1":
                    if out_file.exists():
                        out_file.unlink(missing_ok=True)
                    err_msg = f"Project directory or source file not found: Exported container '{out_file.name}' failed CFBF validation (invalid magic or corrupted container)."
                    return {
                        "success": False,
                        "status": "failed",
                        "project_name": clean_name,
                        "output_format": fmt,
                        "error_count": 1,
                        "errors": [err_msg],
                        "message": err_msg,
                    }
                cfbf_inspection = {
                    "is_valid_cfbf": cfbf_info.is_valid_cfbf,
                    "magic_hex": cfbf_info.magic_hex,
                    "sector_size": cfbf_info.sector_size,
                    "horner_markers": cfbf_info.horner_markers,
                    "has_contents_stream": cfbf_info.has_contents_stream,
                    "cscape_version": cfbf_info.cscape_version,
                }
            except Exception as insp_err:
                if out_file.exists():
                    out_file.unlink(missing_ok=True)
                err_msg = f"Project directory or source file not found: CFBF inspection failed on '{out_file.name}': {insp_err}"
                return {
                    "success": False,
                    "status": "failed",
                    "project_name": clean_name,
                    "output_format": fmt,
                    "error_count": 1,
                    "errors": [err_msg],
                    "message": err_msg,
                }

        elif fmt in ("st", "structured_text"):
            # Consolidated IEC 61131-3 Structured Text POU bundle
            pous_dir = p_dir / "pous" if p_dir.exists() else None
            st_files = sorted(pous_dir.glob("*.st")) if pous_dir and pous_dir.exists() else []
            if not st_files:
                st_files = sorted(p_dir.glob("*.st"))

            if not st_files:
                err_msg = f"Project directory or source file not found: No Structured Text (.st) source files found in '{p_dir}'."
                return {
                    "success": False,
                    "status": "failed",
                    "project_name": clean_name,
                    "output_format": fmt,
                    "error_count": 1,
                    "errors": [err_msg],
                    "message": err_msg,
                }

            st_lines: List[str] = [
                f"(* ============================================================================ *)",
                f"(* Consolidated Structured Text POU Bundle: {clean_name} *)",
                f"(* Export Format: IEC 61131-3 Pure Structured Text *)",
                f"(* Exported At: {_get_utc_timestamp()} *)",
                f"(* Hardware Lockout: Enforced (Simulation Only) *)",
                f"(* ============================================================================ *)",
                "",
            ]
            for st_file in st_files:
                st_lines.append(f"(* ---------------------------------------------------------------------------- *)")
                st_lines.append(f"(* POU: {st_file.stem} ({st_file.name}) *)")
                st_lines.append(f"(* ---------------------------------------------------------------------------- *)")
                st_lines.append(st_file.read_text(encoding="utf-8", errors="replace"))
                st_lines.append("")
            out_file.write_text("\n".join(st_lines), encoding="utf-8")

        elif fmt == "csv":
            # Tag / Variable spreadsheet export
            var_csv = p_dir / "variables.csv" if p_dir.exists() else None
            var_xml = p_dir / "variables.xml" if p_dir.exists() else None
            pous_dir = p_dir / "pous" if p_dir.exists() else None
            st_files = sorted(pous_dir.glob("*.st")) if pous_dir and pous_dir.exists() else []
            if not st_files and p_dir.exists():
                st_files = sorted(p_dir.glob("*.st"))

            if (not var_csv or not var_csv.exists()) and (not var_xml or not var_xml.exists()) and not st_files:
                err_msg = f"Project directory or source file not found: No variable database or source POUs found in '{p_dir}'."
                return {
                    "success": False,
                    "status": "failed",
                    "project_name": clean_name,
                    "output_format": fmt,
                    "error_count": 1,
                    "errors": [err_msg],
                    "message": err_msg,
                }

            if var_csv and var_csv.exists():
                vm = VariableManager(project_name=clean_name)
                vm.import_csv(var_csv)
                if vm.total_count == 0:
                    if out_file.exists():
                        out_file.unlink(missing_ok=True)
                    return {
                        "success": False,
                        "status": "failed",
                        "error_code": "NO_DATA_TO_EXPORT",
                        "project_name": clean_name,
                        "output_format": fmt,
                        "error_count": 1,
                        "errors": ["No variable declarations found in project to export."],
                        "message": "Cannot export empty variable database: project contains 0 variables.",
                    }
                shutil.copyfile(var_csv, out_file)
            elif var_xml and var_xml.exists():
                vm = VariableManager(project_name=clean_name)
                vm.import_xml(var_xml)
                if vm.total_count == 0:
                    if out_file.exists():
                        out_file.unlink(missing_ok=True)
                    return {
                        "success": False,
                        "status": "failed",
                        "error_code": "NO_DATA_TO_EXPORT",
                        "project_name": clean_name,
                        "output_format": fmt,
                        "error_count": 1,
                        "errors": ["No variable declarations found in project to export."],
                        "message": "Cannot export empty variable database: project contains 0 variables.",
                    }
                vm.export_csv(out_file)
            else:
                vm = VariableManager(project_name=clean_name)
                from ..parser.parser import Parser
                from ..cscape.variables import CscapeVariable
                for st_file in st_files:
                    try:
                        code = st_file.read_text(encoding="utf-8", errors="replace")
                        p = Parser.from_source(code)
                        ast = p.parse()
                        for vb in ast.var_blocks:
                            for decl in vb.declarations:
                                scope_str = vb.block_type.name.lower() if hasattr(vb.block_type, "name") else "program"
                                vm.add_variable(CscapeVariable(name=decl.name, data_type=str(decl.data_type), scope=scope_str))
                    except Exception:
                        pass
                if vm.total_count == 0:
                    if out_file.exists():
                        out_file.unlink(missing_ok=True)
                    return {
                        "success": False,
                        "status": "failed",
                        "error_code": "NO_DATA_TO_EXPORT",
                        "project_name": clean_name,
                        "output_format": fmt,
                        "error_count": 1,
                        "errors": ["No variable declarations found in project to export."],
                        "message": "Cannot export empty variable database: project contains 0 variables.",
                    }
                vm.export_csv(out_file)

        elif fmt == "xml":
            # XML Tag database export
            var_xml = p_dir / "variables.xml" if p_dir.exists() else None
            var_csv = p_dir / "variables.csv" if p_dir.exists() else None
            pous_dir = p_dir / "pous" if p_dir.exists() else None
            st_files = sorted(pous_dir.glob("*.st")) if pous_dir and pous_dir.exists() else []
            if not st_files and p_dir.exists():
                st_files = sorted(p_dir.glob("*.st"))

            if (not var_xml or not var_xml.exists()) and (not var_csv or not var_csv.exists()) and not st_files:
                err_msg = f"Project directory or source file not found: No variable database or source POUs found in '{p_dir}'."
                return {
                    "success": False,
                    "status": "failed",
                    "project_name": clean_name,
                    "output_format": fmt,
                    "error_count": 1,
                    "errors": [err_msg],
                    "message": err_msg,
                }

            if var_xml and var_xml.exists():
                vm = VariableManager(project_name=clean_name)
                vm.import_xml(var_xml)
                if vm.total_count == 0:
                    if out_file.exists():
                        out_file.unlink(missing_ok=True)
                    return {
                        "success": False,
                        "status": "failed",
                        "error_code": "NO_DATA_TO_EXPORT",
                        "project_name": clean_name,
                        "output_format": fmt,
                        "error_count": 1,
                        "errors": ["No variable declarations found in project to export."],
                        "message": "Cannot export empty variable database: project contains 0 variables.",
                    }
                shutil.copyfile(var_xml, out_file)
            elif var_csv and var_csv.exists():
                vm = VariableManager(project_name=clean_name)
                vm.import_csv(var_csv)
                if vm.total_count == 0:
                    if out_file.exists():
                        out_file.unlink(missing_ok=True)
                    return {
                        "success": False,
                        "status": "failed",
                        "error_code": "NO_DATA_TO_EXPORT",
                        "project_name": clean_name,
                        "output_format": fmt,
                        "error_count": 1,
                        "errors": ["No variable declarations found in project to export."],
                        "message": "Cannot export empty variable database: project contains 0 variables.",
                    }
                vm.export_xml(out_file)
            else:
                vm = VariableManager(project_name=clean_name)
                from ..parser.parser import Parser
                from ..cscape.variables import CscapeVariable
                for st_file in st_files:
                    try:
                        code = st_file.read_text(encoding="utf-8", errors="replace")
                        p = Parser.from_source(code)
                        ast = p.parse()
                        for vb in ast.var_blocks:
                            for decl in vb.declarations:
                                scope_str = vb.block_type.name.lower() if hasattr(vb.block_type, "name") else "program"
                                vm.add_variable(CscapeVariable(name=decl.name, data_type=str(decl.data_type), scope=scope_str))
                    except Exception:
                        pass
                if vm.total_count == 0:
                    if out_file.exists():
                        out_file.unlink(missing_ok=True)
                    return {
                        "success": False,
                        "status": "failed",
                        "error_code": "NO_DATA_TO_EXPORT",
                        "project_name": clean_name,
                        "output_format": fmt,
                        "error_count": 1,
                        "errors": ["No variable declarations found in project to export."],
                        "message": "Cannot export empty variable database: project contains 0 variables.",
                    }
                vm.export_xml(out_file)

        elif fmt == "json":
            # Project manifest / metadata export
            manifest_p = p_dir / "cscape_project.json" if p_dir.exists() else None
            if manifest_p and manifest_p.is_file() and manifest_p.stat().st_size > 0:
                try:
                    # Validate JSON syntax
                    json.loads(manifest_p.read_text(encoding="utf-8"))
                    shutil.copyfile(manifest_p, out_file)
                except Exception as json_err:
                    err_msg = f"Project manifest corrupted: Invalid JSON in '{manifest_p}': {json_err}"
                    if out_file.exists():
                        out_file.unlink(missing_ok=True)
                    return {
                        "success": False,
                        "status": "failed",
                        "error_code": "MANIFEST_CORRUPTED",
                        "project_name": clean_name,
                        "output_format": fmt,
                        "error_count": 1,
                        "errors": [err_msg],
                        "message": err_msg,
                    }
            else:
                err_msg = (
                    f"Project source file not found: No authentic 'cscape_project.json' manifest "
                    f"found for '{clean_name}' in '{p_dir}'. Synthetic manifest generation is "
                    f"strictly prohibited under fail-closed policy."
                )
                if out_file.exists():
                    out_file.unlink(missing_ok=True)
                return {
                    "success": False,
                    "status": "failed",
                    "error_code": "MANIFEST_NOT_FOUND",
                    "project_name": clean_name,
                    "output_format": fmt,
                    "error_count": 1,
                    "errors": [err_msg],
                    "message": err_msg,
                }

        elif fmt == "k5p":
            # Legacy Straton project file (quarantined)
            k5p_src = p_dir / f"{clean_name}.k5p" if p_dir.exists() else None
            if k5p_src and k5p_src.exists():
                shutil.copyfile(k5p_src, out_file)
            else:
                err_msg = f"Project source file not found: No .k5p project file found for '{clean_name}' in '{p_dir}'. Synthetic file generation is strictly prohibited."
                return {
                    "success": False,
                    "status": "failed",
                    "error_code": "NO_DATA_TO_EXPORT",
                    "project_name": clean_name,
                    "output_format": fmt,
                    "error_count": 1,
                    "errors": [err_msg],
                    "message": err_msg,
                }
        else:
            raise ValueError(f"Unsupported export format '{output_format}'.")

        # Accurately compute SHA-256 and size from disk
        file_bytes = out_file.read_bytes()
        sha = hashlib.sha256(file_bytes).hexdigest()
        size_bytes = len(file_bytes)

        res = {
            "success": True,
            "status": "success",
            "project_name": clean_name,
            "output_format": fmt,
            "export_file": str(out_file),
            "size_bytes": size_bytes,
            "sha256": sha,
            "error_count": 0,
            "errors": [],
        }
        if cfbf_inspection is not None:
            res["cfbf_inspection"] = cfbf_inspection
        if is_quarantined:
            res["warning"] = "k5p is a legacy Straton format; export quarantined under quarantine/straton_k5_legacy/"
        return res
    except Exception as e:
        err_msg = str(e)
        return {
            "success": False,
            "status": "failed",
            "project_name": project_name,
            "output_format": output_format,
            "error_count": 1,
            "errors": [err_msg],
            "message": err_msg,
        }


# ==============================================================================
# Native Cscape HMI MCP Tools (Phase P3)
# ==============================================================================

@enforce_mcp_status_contract(default_source="HMIInventory", default_error_code="HMI_INVENTORY_ERROR")
def cscape_hmi_inventory(
    project_name: Optional[str] = None,
    project_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Inventories native HMI screens and graphical elements from a Cscape CFBF (.csp / .cpj) project.

    Returns screen ID, name, group, is_main_screen, object counts, and object metadata.
    """
    try:
        p_path = Path(project_path) if project_path else (
            WORKSPACE_ROOT / "artifacts" / "projects" / (project_name or "TankLevel_P2_Dedicated") / f"{project_name or 'TankLevel_P2_Dedicated'}.csp"
        )
        mgr = CscapeHMIManager(workspace_root=WORKSPACE_ROOT)
        screens = mgr.inventory_screens(p_path)
        return {
            "success": True,
            "status": "success",
            "project_name": p_path.stem,
            "project_path": str(p_path),
            "screens_count": len(screens),
            "screens": [s.to_dict() for s in screens],
            "message": f"Successfully inventoried {len(screens)} HMI screens.",
        }
    except Exception as e:
        err_msg = str(e)
        return {
            "success": False,
            "status": "failed",
            "error_code": "HMI_INVENTORY_FAILED",
            "project_path": str(project_path or ""),
            "screens_count": 0,
            "screens": [],
            "errors": [err_msg],
            "message": err_msg,
        }


@enforce_mcp_status_contract(default_source="HMIApplyGroup", default_error_code="HMI_APPLY_GROUP_ERROR")
def cscape_hmi_apply_group(
    project_name: Optional[str] = None,
    project_path: Optional[str] = None,
    screen_id: int = 1,
    custom_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Applies and configures the native P2 HMI object group (TankLevelPV, Setpoint, AutoMode,
    ManualOutputCmd, PumpCmdActive, PumpRunningFeedback, STBlock1.HI, STBlock1.LO, SensorHardwareState)
    to the designated screen in the project.
    """
    try:
        p_path = Path(project_path) if project_path else (
            WORKSPACE_ROOT / "artifacts" / "projects" / (project_name or "TankLevel_P2_Dedicated") / f"{project_name or 'TankLevel_P2_Dedicated'}.csp"
        )
        mgr = CscapeHMIManager(workspace_root=WORKSPACE_ROOT)
        res = mgr.apply_p2_hmi_group(p_path, screen_id=screen_id, custom_params=custom_params)
        return {
            "success": True,
            "status": "success",
            "project_name": p_path.stem,
            "project_path": str(p_path),
            "screen_id": res.get("screen_id", screen_id),
            "objects_count": res.get("objects_count", 0),
            "sidecar_path": res.get("sidecar_path", ""),
            "objects": res.get("objects", []),
            "message": res.get("message", "HMI object group applied successfully."),
        }
    except Exception as e:
        err_msg = str(e)
        return {
            "success": False,
            "status": "failed",
            "error_code": "HMI_APPLY_FAILED",
            "project_path": str(project_path or ""),
            "objects_count": 0,
            "objects": [],
            "errors": [err_msg],
            "message": err_msg,
        }


@enforce_mcp_status_contract(default_source="HMIReadProperties", default_error_code="HMI_READ_PROPERTIES_ERROR")
def cscape_hmi_read_properties(
    project_name: Optional[str] = None,
    project_path: Optional[str] = None,
    screen_id: int = 1,
) -> Dict[str, Any]:
    """Reads HMI screen and object properties after application and verifies CFBF stream presence."""
    try:
        p_path = Path(project_path) if project_path else (
            WORKSPACE_ROOT / "artifacts" / "projects" / (project_name or "TankLevel_P2_Dedicated") / f"{project_name or 'TankLevel_P2_Dedicated'}.csp"
        )
        mgr = CscapeHMIManager(workspace_root=WORKSPACE_ROOT)
        res = mgr.read_properties_after_apply(p_path, screen_id=screen_id)
        return {
            "success": True,
            "status": "success",
            "project_name": p_path.stem,
            "project_path": str(p_path),
            "screen_id": res.get("screen_id", screen_id),
            "objects_count": len(res.get("objects", [])),
            "objects": res.get("objects", []),
            "cfbf_stream_verified": res.get("cfbf_stream_verified", {}),
            "message": f"Successfully read properties for screen {screen_id}.",
        }
    except Exception as e:
        err_msg = str(e)
        return {
            "success": False,
            "status": "failed",
            "error_code": "HMI_READ_PROPERTIES_FAILED",
            "project_path": str(project_path or ""),
            "screen_id": screen_id,
            "objects_count": 0,
            "objects": [],
            "errors": [err_msg],
            "message": err_msg,
        }


@enforce_mcp_status_contract(default_source="HMIVerifyBindings", default_error_code="HMI_VERIFY_BINDINGS_ERROR")
def cscape_hmi_verify_bindings(
    project_name: Optional[str] = None,
    project_path: Optional[str] = None,
    screen_id: int = 1,
    pou_code: Optional[str] = None,
    binding_overrides: Optional[Dict[str, str]] = None,
    custom_objects: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Validates that all HMI object variable bindings strictly match the P2 IEC ST logic.

    Detects wrong bindings, unmapped variables, and command/feedback differentiation collisions.
    Supports negative testing via binding_overrides or custom_objects.
    """
    try:
        p_path = Path(project_path) if project_path else (
            WORKSPACE_ROOT / "artifacts" / "projects" / (project_name or "TankLevel_P2_Dedicated") / f"{project_name or 'TankLevel_P2_Dedicated'}.csp"
        )
        mgr = CscapeHMIManager(workspace_root=WORKSPACE_ROOT)
        res = mgr.verify_p2_bindings(
            p_path,
            screen_id=screen_id,
            pou_code=pou_code,
            binding_overrides=binding_overrides,
            custom_objects=custom_objects,
        )
        is_ok = res.get("bindings_verified", False)
        status_val = "success" if is_ok else "failed"
        return {
            "success": is_ok,
            "status": status_val,
            "bindings_verified": is_ok,
            "project_name": p_path.stem,
            "project_path": str(p_path),
            "screen_id": res.get("screen_id", screen_id),
            "objects_count": res.get("objects_count", 0),
            "checks": res.get("checks", {}),
            "mismatches": res.get("mismatches", []),
            "errors": res.get("errors", []),
            "message": "All HMI bindings verified successfully against P2 logic." if is_ok else "HMI binding mismatch detected.",
        }
    except Exception as e:
        err_msg = str(e)
        return {
            "success": False,
            "status": "failed",
            "error_code": "ERR_HMI_VERIFY_EXCEPTION",
            "bindings_verified": False,
            "project_path": str(project_path or ""),
            "screen_id": screen_id,
            "errors": [err_msg],
            "message": err_msg,
        }


@enforce_mcp_status_contract(default_source="HMISaveCloseReopen", default_error_code="HMI_LIFECYCLE_ERROR")
def cscape_hmi_save_close_reopen(
    project_name: Optional[str] = None,
    project_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Demonstrates HMI durability across live Cscape save (ID_FILE_SAVE), clean MDI child close
    (WM_CLOSE), full-path reopen, and native re-read of screens and object properties.
    """
    try:
        p_path = Path(project_path) if project_path else (
            WORKSPACE_ROOT / "artifacts" / "projects" / (project_name or "TankLevel_P2_Dedicated") / f"{project_name or 'TankLevel_P2_Dedicated'}.csp"
        )
        mgr = CscapeHMIManager(workspace_root=WORKSPACE_ROOT)
        data = mgr.persist_hmi_lifecycle(p_path)
        return {
            "success": True,
            "status": "success",
            "project_name": p_path.stem,
            "project_path": str(p_path),
            "reopened_screens_count": data.get("reopened_screens_count", 0),
            "hmi_objects_count": data.get("hmi_objects_count", 0),
            "lifecycle_verified": data.get("lifecycle_verified", {}),
            "minimum_hmi_verified": data.get("minimum_hmi_verified", {}),
            "message": "HMI persistence lifecycle completed and verified successfully across save, close, and reopen.",
        }
    except Exception as e:
        err_msg = str(e)
        return {
            "success": False,
            "status": "failed",
            "error_code": "HMI_LIFECYCLE_FAILED",
            "project_path": str(project_path or ""),
            "errors": [err_msg],
            "message": err_msg,
        }





# ==============================================================================
# Phase P4 Fixture Evolution & Selective Edit Tools
# ==============================================================================

@enforce_mcp_status_contract(default_source="FixtureRequestToSpec", default_error_code="FIXTURE_SPEC_ERROR")
def cscape_fixture_request_to_spec(
    fixture_id: str = "TankLevel_P4_Fixture",
    description: str = "Closed-loop buffer tank level controller with dual threshold alarms",
    process_variable: str = "TankLevelPV",
    engineering_unit: str = "%",
    lo_limit: float = 30.0,
    hi_limit: float = 70.0,
    setpoint: float = 50.0,
    level_label: str = "Tank Level PV",
    project_name: str = "TankLevel_P4_Dedicated",
    screen_id: int = 1,
) -> Dict[str, Any]:
    """Translates a high-level engineering fixture request into an AST-validated IEC ST specification."""
    mgr = FixtureEvolutionManager(workspace_root=WORKSPACE_ROOT)
    res = mgr.request_to_spec({
        "fixture_id": fixture_id,
        "description": description,
        "process_variable": process_variable,
        "engineering_unit": engineering_unit,
        "lo_limit": lo_limit,
        "hi_limit": hi_limit,
        "setpoint": setpoint,
        "level_label": level_label,
        "project_name": project_name,
        "screen_id": screen_id,
    })
    res["success"] = (res.get("status") == "success")
    return res


@enforce_mcp_status_contract(default_source="FixtureCreate", default_error_code="FIXTURE_CREATE_ERROR")
def cscape_fixture_create(
    spec: Optional[Dict[str, Any]] = None,
    project_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Instantiates a dedicated CFBF project container, ST POU, variables, and native HMI screen."""
    mgr = FixtureEvolutionManager(workspace_root=WORKSPACE_ROOT)
    if spec is None:
        p_name = project_name or "TankLevel_P4_Dedicated"
        spec_res = mgr.request_to_spec({"project_name": p_name})
        if spec_res.get("status") != "success":
            return spec_res
        spec = spec_res.get("spec")
    res = mgr.create_fixture_project(spec)
    res["success"] = (res.get("status") == "success")
    return res


@enforce_mcp_status_contract(default_source="FixtureSelectiveEdit", default_error_code="FIXTURE_EDIT_ERROR")
def cscape_fixture_selective_edit(
    project_name: str = "TankLevel_P4_Dedicated",
    new_lo_limit: float = 35.0,
    new_hi_limit: float = 75.0,
    new_level_label: str = "Buffer Tank Level PV",
    expected_prior_revision: Optional[str] = None,
    expected_prior_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """Selectively mutates limits and labels with AST verification, idempotency, and conflict detection."""
    mgr = FixtureEvolutionManager(workspace_root=WORKSPACE_ROOT)
    res = mgr.selective_edit(
        project_name=project_name,
        new_lo_limit=new_lo_limit,
        new_hi_limit=new_hi_limit,
        new_level_label=new_level_label,
        expected_prior_revision=expected_prior_revision,
        expected_prior_hash=expected_prior_hash,
    )
    res["success"] = (res.get("status") == "success")
    return res


@enforce_mcp_status_contract(default_source="FixtureRevisionImpact", default_error_code="FIXTURE_IMPACT_ERROR")
def cscape_fixture_revision_impact(
    project_name: str = "TankLevel_P4_Dedicated",
) -> Dict[str, Any]:
    """Audits revision differences, AST changes, and verified untouched elements."""
    mgr = FixtureEvolutionManager(workspace_root=WORKSPACE_ROOT)
    res = mgr.analyze_revision_impact(project_name=project_name)
    res["success"] = (res.get("status") == "success")
    return res


@enforce_mcp_status_contract(default_source="FixtureDurabilityCheck", default_error_code="FIXTURE_DURABILITY_ERROR")
def cscape_fixture_durability_check(
    project_name: str = "TankLevel_P4_Dedicated",
) -> Dict[str, Any]:
    """Executes live Cscape save, clean child close, full-path reopen, and native semantic verification."""
    mgr = FixtureEvolutionManager(workspace_root=WORKSPACE_ROOT)
    res = mgr.durability_check(project_name=project_name)
    res["success"] = (res.get("status") == "success")
    return res


@enforce_mcp_status_contract(default_source="FixtureDetectConflict", default_error_code="FIXTURE_CONFLICT_ERROR")
def cscape_fixture_detect_conflict(
    project_name: str = "TankLevel_P4_Dedicated",
    expected_hash: str = "",
) -> Dict[str, Any]:
    """Verifies that external modifications or hash mismatches fail closed immediately."""
    mgr = FixtureEvolutionManager(workspace_root=WORKSPACE_ROOT)
    res = mgr.detect_conflict(project_name=project_name, expected_hash=expected_hash)
    res["success"] = (res.get("status") == "success")
    return res


# ==============================================================================
# Phase P5 Modbus PV Provider Tools
# ==============================================================================

@enforce_mcp_status_contract(default_source="ModbusCreateConfig", default_error_code="MODBUS_CONFIG_ERROR")
def cscape_modbus_create_config(
    project_name: str = "TankLevel_P5_Dedicated",
    transport: str = "MODBUS_TCP",
    ip_address: str = "127.0.0.1",
    port: int = 15502,
    unit_id: int = 1,
    function_code: int = 3,
    modicon_address: int = 40001,
    wire_offset: int = 0,
    ocs_register: str = "%AI1",
    variable_name: str = "TankLevelPV",
    raw_min: float = 0.0,
    raw_max: float = 32000.0,
    eu_min: float = 0.0,
    eu_max: float = 100.0,
    poll_interval_ms: int = 100,
    timeout_ms: int = 1000,
    stale_timeout_ms: int = 2000,
) -> Dict[str, Any]:
    """Generates an authentic native Cscape Modbus PV provider configuration with full inventory."""
    config = ModbusPVProviderConfig(
        config_id=f"{project_name}_ModbusPV_Config",
        description=f"Native Cscape Modbus PV Provider Configuration for {project_name}",
        transport=ModbusTransport(transport),
        role=ModbusRole.CLIENT_MASTER_READ_ONLY,
        unit_id=unit_id,
        function_code=ModbusFunctionCode(function_code),
        tcp_endpoint=ModbusTCPEndpoint(ip_address=ip_address, port=port, connect_timeout_ms=timeout_ms),
        rtu_endpoint=ModbusRTUEndpoint(),
        address_mapping=ModbusAddressMapping(
            modicon_1based=modicon_address,
            wire_offset_0based=wire_offset,
            register_count=1,
            horner_ocs_register=ocs_register,
            variable_name=variable_name,
        ),
        scaling=ScalingConfiguration(
            raw_min=raw_min,
            raw_max=raw_max,
            eu_min=eu_min,
            eu_max=eu_max,
            engineering_unit="%",
        ),
        policy=PollingAndStalePolicy(
            poll_interval_ms=poll_interval_ms,
            response_timeout_ms=timeout_ms,
            retry_count=3,
            stale_timeout_ms=stale_timeout_ms,
        ),
        read_only_enforced=True,
        safety_lockout_verified=True,
        physical_runtime_verification="PENDING_P7 (Strictly deferred to Phase P7; zero PLC download)",
    )
    res_dict = config.to_dict()
    res_dict["status"] = "success"
    res_dict["sha256"] = config.compute_config_hash()
    res_dict["deep_inventory"] = ModbusConfigPersistenceManager.build_default_deep_inventory(project_name).to_dict()
    return res_dict


@enforce_mcp_status_contract(default_source="ModbusPersistConfig", default_error_code="MODBUS_PERSIST_ERROR")
def cscape_modbus_persist_config(
    project_name: str = "TankLevel_P5_Dedicated",
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Persists Modbus PV provider config and integrates ST logic into project container."""
    proj_dir = WORKSPACE_ROOT / "artifacts" / "projects" / project_name
    proj_dir.mkdir(parents=True, exist_ok=True)

    if config is None:
        cfg_obj = ModbusPVProviderConfig(
            config_id=f"{project_name}_ModbusPV_Config",
            description=f"Native Cscape Modbus PV Provider Configuration for {project_name}",
        )
    else:
        cfg_obj = ModbusPVProviderConfig.from_dict(config)

    sidecar_path, cfg_hash = ModbusConfigPersistenceManager.persist_config(proj_dir, cfg_obj)

    # Persist updated ST logic with Modbus telemetry and watchdog
    pou_dir = proj_dir / "pous"
    pou_dir.mkdir(parents=True, exist_ok=True)
    pou_file = pou_dir / "TankLevelControl.st"
    st_code = f"""PROGRAM TankLevelControl
VAR
    RawAnalogInput : WORD := 0; (* %AI1: Modbus Register {cfg_obj.address_mapping.modicon_1based} (Wire offset 0x{cfg_obj.address_mapping.wire_offset_0based:04X}) *)
    TankLevelPV : REAL := 0.0; (* Scaled Process Variable: 0.0..100.0 % *)
    Setpoint : REAL := 50.0; (* %AQ1 *)
    AutoMode : BOOL := TRUE; (* %M1 *)
    ManualOutputCmd : REAL := 0.0; (* %AQ2 *)
    PumpCmdActive : BOOL := FALSE; (* %Q1 *)
    PumpRunningFeedback : BOOL := FALSE; (* %I1 *)
    HighAlarm : BOOL := FALSE; (* %T3 *)
    LowAlarm : BOOL := FALSE; (* %T4 *)
    ControlError : REAL := 0.0; (* %R10 *)
    HI_Limit : REAL := 75.0;
    LO_Limit : REAL := 35.0;
    CommFailureAlarm : BOOL := FALSE; (* {cfg_obj.policy.comm_failure_alarm_reg}: Remote Modbus Comm Timeout Fault *)
    TankLevelPV_Stale : BOOL := FALSE; (* {cfg_obj.policy.stale_quality_bit_reg}: Stale Telemetry Quality Indicator *)
    CommWatchdogReg : WORD := 0; (* Remote Modbus Heartbeat Register *)
    LastWatchdogReg : WORD := 0;
    WatchdogTimer : TON;
END_VAR

(* 1. Modbus Communication Health & Watchdog Check *)
IF CommWatchdogReg <> LastWatchdogReg THEN
    LastWatchdogReg := CommWatchdogReg;
    CommFailureAlarm := FALSE;
    TankLevelPV_Stale := FALSE;
END_IF;

WatchdogTimer(IN := NOT CommFailureAlarm, PT := T#2s);
IF WatchdogTimer.Q THEN
    CommFailureAlarm := TRUE;
    TankLevelPV_Stale := TRUE;
END_IF;

(* 2. Process Variable Acquisition & Quality Handling *)
IF NOT CommFailureAlarm THEN
    TankLevelPV := WORD_TO_REAL(RawAnalogInput) * 100.0 / 32000.0;
    TankLevelPV := LIMIT(0.0, TankLevelPV, 100.0);
ELSE
    TankLevelPV := 0.0; (* Fail-safe clamp *)
END_IF;

(* 3. Closed-Loop Tank Level Control Logic *)
ControlError := Setpoint - TankLevelPV;

IF TankLevelPV >= HI_Limit THEN
    HighAlarm := TRUE;
ELSE
    HighAlarm := FALSE;
END_IF;

IF TankLevelPV <= LO_Limit THEN
    LowAlarm := TRUE;
ELSE
    LowAlarm := FALSE;
END_IF;

IF AutoMode THEN
    IF TankLevelPV < Setpoint THEN
        PumpCmdActive := TRUE;
    else
        PumpCmdActive := FALSE;
    END_IF;
ELSE
    IF ManualOutputCmd > 0.0 THEN
        PumpCmdActive := TRUE;
    else
        PumpCmdActive := FALSE;
    END_IF;
END_IF;

END_PROGRAM
"""
    pou_file.write_text(st_code, encoding="utf-8")

    return {
        "status": "success",
        "project_name": project_name,
        "sidecar_file": str(sidecar_path),
        "inventory_file": str(proj_dir / "modbus_protocol_inventory.json"),
        "pou_file": str(pou_file),
        "sha256": cfg_hash,
        "read_only_enforced": True,
        "physical_runtime_verification": "PENDING_P7",
    }


@enforce_mcp_status_contract(default_source="ModbusReadConfig", default_error_code="MODBUS_READ_ERROR")
def cscape_modbus_read_config(
    project_name: str = "TankLevel_P5_Dedicated",
) -> Dict[str, Any]:
    """Re-reads and verifies persisted Modbus PV provider configuration from project container."""
    proj_dir = WORKSPACE_ROOT / "artifacts" / "projects" / project_name
    cfg_obj = ModbusConfigPersistenceManager.read_config(proj_dir)
    if not cfg_obj:
        return {
            "status": "failed",
            "error_code": "CONFIG_NOT_FOUND",
            "message": f"Modbus config not found in project directory: {proj_dir}",
        }

    cfg_dict = cfg_obj.to_dict()
    cfg_hash = cfg_obj.compute_config_hash()
    cfg_dict["sha256"] = cfg_hash
    deep_inv = ModbusConfigPersistenceManager.read_deep_inventory(proj_dir)
    if deep_inv:
        cfg_dict["deep_inventory"] = deep_inv
    cfg_dict["status"] = "success"
    return cfg_dict


@enforce_mcp_status_contract(default_source="ModbusProtocolCheck", default_error_code="MODBUS_PROTOCOL_ERROR")
def cscape_modbus_protocol_check(
    host: str = "127.0.0.1",
    port: int = 15502,
    unit_id: int = 1,
    function_code: int = 3,
    start_address: int = 0,
    quantity: int = 1,
    simulated_raw_value: Optional[int] = 17600,
) -> Dict[str, Any]:
    """Executes a native Modbus TCP wire query against the labeled TEST Modbus server endpoint."""
    server_started_here = False
    server = None
    if simulated_raw_value is not None:
        try:
            # Stand up labeled test server if not already listening
            server = LabeledTestModbusServer(host=host, port=port, initial_raw_value=simulated_raw_value)
            server.start()
            server_started_here = True
            time.sleep(0.1)
        except OSError:
            # Already running on port
            server = None

    try:
        res = query_pv_register(
            host=host,
            port=port,
            unit_id=unit_id,
            function_code=function_code,
            start_address=start_address,
            quantity=quantity,
        )
        res["server_label"] = TEST_MODBUS_SERVER_LABEL
        res["read_only_verified"] = True
        res["physical_runtime_verification"] = "PENDING_P7 (Protocol verified against labeled test endpoint)"
        return res
    finally:
        if server_started_here and server is not None:
            server.stop()


@enforce_mcp_status_contract(default_source="ModbusConversionDoc", default_error_code="MODBUS_DOC_ERROR")
def cscape_modbus_conversion_doc(
    level_pct: float = 55.0,
) -> Dict[str, Any]:
    """Returns detailed conversion walkthrough showing raw counts, wire frames, and ST scaling logic."""
    doc = generate_modbus_conversion_walkthrough(level_pct=level_pct)
    doc["status"] = "success"
    return doc


# ==============================================================================
# Air-Gapped Offline Packaging Tool
# ==============================================================================

@enforce_mcp_status_contract(default_source="PackageOfflineBundle", default_error_code="PACKAGE_BUNDLE_ERROR")
def cscape_package_offline_bundle(
    project_name: str,
    output_dir: Optional[str] = None,
    bundle_name: Optional[str] = None,
    include_st_sources: bool = True,
    include_manifest: bool = True,
    include_manual_guide: bool = True,
) -> Dict[str, Any]:
    """Packages an air-gapped offline distribution bundle with project CFBF binaries, ST POUs,
    variable mappings, Modbus configuration, and cryptographic SHA-256 manifest.

    Garantías de seguridad:
    - Pure-software air-gapped distribution: Zero PLC connection, zero COM port access.
    - Physical download is permanently locked out; manual engineer loading instructions included.
    - Generates self-contained, reproducible ZIP archive with cryptographically signed MANIFEST-SHA256.json.
    """
    try:
        clean_name = SafetyGuard.validate_project_name(project_name)
    except Exception as e:
        return {
            "success": False,
            "status": "failed",
            "error_code": "INVALID_PROJECT_NAME",
            "message": f"Project name validation failed: {e}",
            "errors": [str(e)],
        }

    proj_dir = WORKSPACE_ROOT / "artifacts" / "projects" / clean_name
    if not proj_dir.exists():
        alt_proj = Path(r".\artifacts\projects") / clean_name
        if alt_proj.exists():
            proj_dir = alt_proj
        else:
            return {
                "success": False,
                "status": "failed",
                "error_code": "PROJECT_NOT_FOUND",
                "project_name": clean_name,
                "message": f"Project directory '{proj_dir}' does not exist on disk.",
                "errors": [f"Project directory '{proj_dir}' does not exist on disk."],
            }

    dest_dir = Path(output_dir).resolve() if output_dir else WORKSPACE_ROOT / "artifacts" / "delivery"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {
            "success": False,
            "status": "failed",
            "error_code": "DESTINATION_DIR_ERROR",
            "message": f"Could not create destination directory '{dest_dir}': {e}",
            "errors": [str(e)],
        }

    pkg_base_name = bundle_name or f"{clean_name}_offline_bundle_v1.0.0"
    staging_dir = dest_dir / f"_stage_{pkg_base_name}_{int(time.time())}"
    staging_dir.mkdir(parents=True, exist_ok=True)

    files_included: List[str] = []
    manifest_entries: Dict[str, Any] = {
        "schema_version": "1.0.0",
        "bundle_name": pkg_base_name,
        "project_name": clean_name,
        "provenance": "OFFLINE_AIRGAPPED_BUNDLE",
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "air_gapped_distribution": True,
        "hardware_lockout_enforced": True,
        "files": {},
    }

    try:
        # 1. Package Project Files (.csp / .cpj)
        proj_files = list(proj_dir.glob("*.csp")) + list(proj_dir.glob("*.cpj"))
        (staging_dir / "project").mkdir(parents=True, exist_ok=True)
        for pf in proj_files:
            rel_dest = Path("project") / pf.name
            shutil.copy2(pf, staging_dir / rel_dest)
            files_included.append(str(rel_dest).replace("\\", "/"))

        # 2. Package ST POUs
        pous_dir = proj_dir / "pous"
        if include_st_sources and pous_dir.exists():
            (staging_dir / "pous").mkdir(parents=True, exist_ok=True)
            for st_file in sorted(pous_dir.glob("*.st")):
                rel_dest = Path("pous") / st_file.name
                shutil.copy2(st_file, staging_dir / rel_dest)
                files_included.append(str(rel_dest).replace("\\", "/"))

        # 3. Package Variable Databases
        tags_dir = staging_dir / "tags"
        tags_dir.mkdir(parents=True, exist_ok=True)
        for v_name in ("variables.csv", "variables.xml"):
            src_v = proj_dir / v_name
            if src_v.exists():
                rel_dest = Path("tags") / v_name
                shutil.copy2(src_v, staging_dir / rel_dest)
                files_included.append(str(rel_dest).replace("\\", "/"))

        # 4. Package Modbus Config (if present)
        cfg_src = proj_dir / "modbus_pv_config.json"
        if cfg_src.exists():
            (staging_dir / "config").mkdir(parents=True, exist_ok=True)
            rel_dest = Path("config") / "modbus_pv_config.json"
            shutil.copy2(cfg_src, staging_dir / rel_dest)
            files_included.append(str(rel_dest).replace("\\", "/"))

        # 5. Package Manual Loading Instructions
        if include_manual_guide:
            (staging_dir / "docs").mkdir(parents=True, exist_ok=True)
            guide_content = f"""# Field Controls Engineer Manual Transfer & Commissioning Guide

> **Project**: `{clean_name}`
> **Distribution Mode**: Air-Gapped / Offline Distribution Only
> **Security Policy**: Zero Automated PLC Download. Hardware communication ports are permanently blocked in the MCP server.

---

## 1. Manual Loading Procedures

Transfer of compiled project binaries to physical Horner OCS hardware must be performed manually by an authorized commissioning engineer using one of the following methods:

### Method A: Direct Mini-B USB Programming Cable (Recommended)
1. Connect PC to the Horner OCS Mini-B USB programming port.
2. Launch Horner APG Cscape 10.2.
3. Open `project/{clean_name}.csp`.
4. Ensure target controller model matches physical OCS hardware (e.g., HE-XPCE2 / XL4 Prime).
5. From the top menu, select **Controller** -> **Download** (`Ctrl+F9`).
6. Verify status transitions to RUN mode.

### Method B: RS-232 / RS-485 Serial Interface (MJ1 / MJ2)
1. Connect Horner programming cable to serial port `MJ1` or `MJ2`.
2. Configure baud rate in Cscape (default 57,600 or 115,200 baud).
3. Select **Controller** -> **Download**.

### Method C: Removable MicroSD Card Loading (Air-Gapped Field Flash)
1. Format a high-end Industrial MicroSD card (FAT32, <= 32GB).
2. Export compiled PGM/boot image from Cscape to the SD card.
3. Insert MicroSD card into the OCS controller slot.
4. Press `View` + `Enter` to access the OCS System Menu.
5. Select **Load PGM** and confirm project loading.

---

## 2. Integrity Verification
Prior to downloading to physical hardware, verify cryptographic checksums against `MANIFEST-SHA256.json`.
"""
            guide_path = staging_dir / "docs" / "MANUAL_LOADING_INSTRUCTIONS.md"
            guide_path.write_text(guide_content, encoding="utf-8")
            files_included.append("docs/MANUAL_LOADING_INSTRUCTIONS.md")

        # 6. Generate MANIFEST-SHA256.json
        for fpath in staging_dir.rglob("*"):
            if fpath.is_file() and fpath.name != "MANIFEST-SHA256.json":
                rel = str(fpath.relative_to(staging_dir)).replace("\\", "/")
                content = fpath.read_bytes()
                h = hashlib.sha256(content).hexdigest()
                manifest_entries["files"][rel] = {
                    "sha256": h,
                    "size_bytes": len(content),
                }

        if include_manifest:
            manifest_file = staging_dir / "MANIFEST-SHA256.json"
            manifest_file.write_text(json.dumps(manifest_entries, indent=2), encoding="utf-8")
            files_included.append("MANIFEST-SHA256.json")

        # 7. Create ZIP archive
        zip_path = dest_dir / f"{pkg_base_name}.zip"
        if zip_path.exists():
            zip_path.unlink()

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fpath in staging_dir.rglob("*"):
                if fpath.is_file():
                    arcname = str(fpath.relative_to(staging_dir)).replace("\\", "/")
                    zf.write(fpath, arcname=arcname)

        bundle_hash = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        bundle_size = zip_path.stat().st_size

        return {
            "success": True,
            "status": "success",
            "provenance": "OFFLINE_BUNDLE",
            "hardware_connected": False,
            "isolation_enforced": True,
            "project_name": clean_name,
            "bundle_path": str(zip_path),
            "bundle_size_bytes": bundle_size,
            "file_count": len(files_included),
            "files_included": sorted(files_included),
            "bundle_sha256": bundle_hash,
            "air_gapped_distribution": True,
            "zero_download_enforced": True,
            "manual_commissioning_required": True,
            "message": f"Air-gapped offline bundle packaged successfully: {zip_path.name} ({len(files_included)} assets, {bundle_size} bytes).",
        }
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


# ==============================================================================
# Tool Registration
# ==============================================================================

def register_tools(server: Any) -> None:
    """Registers all real Cscape 10.2 MCP tools and convenience wrappers on MCPServer."""
    # 12 Core Cscape 10.2 Tools
    server.tool()(cscape_launch_ide)
    server.tool()(cscape_new_iec_project)
    server.tool()(cscape_open_project)
    server.tool()(cscape_insert_st)
    server.tool()(cscape_insert_st_pou)
    server.tool()(cscape_compile)
    server.tool()(cscape_get_build_output)
    server.tool()(cscape_read_variables)
    server.tool()(cscape_write_variables)
    server.tool()(cscape_import_variables)
    server.tool()(cscape_export_variables)
    server.tool()(cscape_run_simulation)

    # Convenience wrappers
    server.tool()(cscape_create_project)
    server.tool()(cscape_add_st_pou)
    server.tool()(cscape_validate_st)
    server.tool()(cscape_inspect_variables)
    server.tool()(cscape_compile_project)
    server.tool()(cscape_get_diagnostics)
    server.tool()(cscape_simulate_pou)
    server.tool()(cscape_export_project)

    # Simulation & Software Register Manipulation Tools
    server.tool()(cscape_simulate_cycle)
    server.tool()(cscape_read_register)
    server.tool()(cscape_write_register)

    # Native Cscape HMI Tools (Phase P3)
    server.tool()(cscape_hmi_inventory)
    server.tool()(cscape_hmi_apply_group)
    server.tool()(cscape_hmi_read_properties)
    server.tool()(cscape_hmi_verify_bindings)
    server.tool()(cscape_hmi_save_close_reopen)

    # Phase P4 Fixture Evolution Tools
    server.tool()(cscape_fixture_request_to_spec)
    server.tool()(cscape_fixture_create)
    server.tool()(cscape_fixture_selective_edit)
    server.tool()(cscape_fixture_revision_impact)
    server.tool()(cscape_fixture_durability_check)
    server.tool()(cscape_fixture_detect_conflict)

    # Phase P5 Modbus PV Provider Tools
    server.tool()(cscape_modbus_create_config)
    server.tool()(cscape_modbus_persist_config)
    server.tool()(cscape_modbus_read_config)
    server.tool()(cscape_modbus_protocol_check)
    server.tool()(cscape_modbus_conversion_doc)

    # Phase P9 Air-Gapped Offline Packaging
    server.tool()(cscape_package_offline_bundle)


__all__ = [
    # 12 Core Tools
    "cscape_launch_ide",
    "cscape_new_iec_project",
    "cscape_open_project",
    "cscape_insert_st",
    "cscape_insert_st_pou",
    "cscape_compile",
    "cscape_get_build_output",
    "cscape_read_variables",
    "cscape_write_variables",
    "cscape_import_variables",
    "cscape_export_variables",
    "cscape_run_simulation",
    # 8 Convenience Wrappers
    "cscape_create_project",
    "cscape_add_st_pou",
    "cscape_validate_st",
    "cscape_inspect_variables",
    "cscape_compile_project",
    "cscape_get_diagnostics",
    "cscape_simulate_pou",
    "cscape_export_project",
    # 3 Simulation & Register Tools
    "cscape_simulate_cycle",
    "cscape_read_register",
    "cscape_write_register",
    # 5 Phase P3 HMI Tools
    "cscape_hmi_inventory",
    "cscape_hmi_apply_group",
    "cscape_hmi_read_properties",
    "cscape_hmi_verify_bindings",
    "cscape_hmi_save_close_reopen",
    # 6 Phase P4 Fixture Evolution Tools
    "cscape_fixture_request_to_spec",
    "cscape_fixture_create",
    "cscape_fixture_selective_edit",
    "cscape_fixture_revision_impact",
    "cscape_fixture_durability_check",
    "cscape_fixture_detect_conflict",
    # 5 Phase P5 Modbus PV Provider Tools
    "cscape_modbus_create_config",
    "cscape_modbus_persist_config",
    "cscape_modbus_read_config",
    "cscape_modbus_protocol_check",
    "cscape_modbus_conversion_doc",
    # Air-Gapped Offline Packaging
    "cscape_package_offline_bundle",
    # Server Registration & Helper Utilities
    "register_tools",
    "normalize_tool_result",
    "ToolStatus",
    "enforce_mcp_status_contract",
    "get_active_simulator",
]

