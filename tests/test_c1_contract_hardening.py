"""Phase C1 FastMCP Status Contract and Fail-Closed Safety Hardening Test Suite.

Mandates Verified:
1. Strict adherence to canonical 4-state ontology: 'success', 'failed', 'blocked', 'inconclusive'.
2. Distinction between safety policy lockouts ('blocked') vs syntax/semantic failures ('failed').
3. Hardware port access (COM1-256, CAN, USB, JTAG) returns status: 'blocked'.
4. Download commands (32827, 33149) and companion flashing binaries return status: 'blocked'.
5. Ladder logic constructs (ERR_LADDER_FORBIDDEN) return status: 'failed'.
6. In-GUI ST-to-LD conversion is BLOCKED_NATIVE: DOCUMENT_ONLY (status: 'blocked').
7. All failure locations strictly populated with line, column, error_code, severity, message, file_path.
8. Zero GUI automation execution (offline DEV only; leave live Cscape untouched).
"""

import pytest
from pathlib import Path
from typing import Any, Dict

from src.mcp.tools import (
    ToolStatus,
    normalize_tool_result,
    enforce_mcp_status_contract,
    cscape_read_register,
    cscape_write_register,
    cscape_validate_st,
    cscape_insert_st,
    cscape_create_project,
    cscape_compile_project,
    cscape_export_project,
)
from src.security.guard import SafetyGuard, SecurityGuard
from src.security.exceptions import (
    HardwareLockoutError,
    UnauthorizedDownloadError,
    BlockedExecutableError,
    DangerousArgumentError,
    SecurityError,
)
from src.cscape.st_ld_interop import STLadderInteropGuard


class TestC1CanonicalStatusOntology:
    """Verifies the 4-state status contract ontology."""

    def test_canonical_statuses(self):
        for s in ["success", "failed", "blocked", "inconclusive"]:
            status = ToolStatus(s)
            assert str(status) == s
            assert status == s

    def test_legacy_aliases_normalization(self):
        assert str(ToolStatus("error")) == "failed"
        assert str(ToolStatus("failure")) == "failed"
        assert str(ToolStatus("err")) == "failed"
        assert str(ToolStatus("ok")) == "success"
        assert str(ToolStatus("passed")) == "success"

    def test_ban_verified_and_100_percent(self):
        assert "VERIFIED" not in str(ToolStatus("VERIFIED"))
        assert "100%" not in str(ToolStatus("100%"))
        assert "VERIFIED" not in str(ToolStatus("VERIFIED_LIVE"))

    def test_normalizer_preserves_canonical_contract(self):
        norm = normalize_tool_result({"status": "blocked", "errors": ["Hardware port locked"]})
        assert norm["status"] == "blocked"
        assert norm["success"] is False
        assert len(norm["errors"]) > 0
        assert len(norm["failure_locations"]) > 0


class TestC1FailClosedSafetyLockout:
    """Verifies that physical hardware operations return status: 'blocked'."""

    @pytest.mark.parametrize("port", ["COM1", "COM4", r"\\.\COM1", "/dev/ttyUSB0", "CAN0", "USB1"])
    def test_read_register_port_lockout_returns_blocked(self, port):
        res = cscape_read_register(address=port)
        assert res["success"] is False
        assert res["status"] == "blocked"
        assert res["status"] != "failed"
        assert any("blocked" in e.lower() or "port" in e.lower() for e in res["errors"])
        assert len(res["failure_locations"]) > 0
        loc = res["failure_locations"][0]
        # Invariant: Unlocated errors must NOT invent line: 1, column: 1
        assert loc["line"] is None
        assert loc["column"] is None
        assert loc["severity"] == "ERROR"

    @pytest.mark.parametrize("port", ["COM2", "COM10", r"\\.\COM2"])
    def test_write_register_port_lockout_returns_blocked(self, port):
        res = cscape_write_register(address=port, value=123)
        assert res["success"] is False
        assert res["status"] == "blocked"
        assert res["status"] != "failed"
        assert any("blocked" in e.lower() or "port" in e.lower() for e in res["errors"])

    def test_unconditional_download_lockout(self):
        guard = SecurityGuard()
        with pytest.raises(UnauthorizedDownloadError):
            guard.validate_download(target="XL4", binary_path="test.hex")

    def test_unconditional_hardware_connection_lockout(self):
        guard = SecurityGuard()
        with pytest.raises(HardwareLockoutError):
            guard.validate_hardware_connection(port="COM1", protocol="CsCAN")

    def test_companion_flasher_lockout(self):
        guard = SecurityGuard()
        for flasher in ["PGMUpdateUtility.exe", "DfuSeCommand.exe", "STMFlashLoader.exe", "WinJTAG.exe"]:
            with pytest.raises(BlockedExecutableError):
                guard.validate_execution(flasher)

    def test_download_cli_flags_lockout(self):
        guard = SecurityGuard()
        for flag in ["/d", "/download", "/flash", "/burn", "/write-flash"]:
            with pytest.raises(DangerousArgumentError):
                guard.validate_command(f"Cscape.exe {flag}")


class TestC1PureSTVsLadderLockout:
    """Verifies that ladder logic is rejected with 'failed' (ERR_LADDER_FORBIDDEN) and ST->LD is 'blocked'."""

    def test_pure_st_validates_successfully(self):
        code = "PROGRAM CleanP\nVAR\n  y : INT;\nEND_VAR\n  y := 10;\nEND_PROGRAM"
        res = cscape_validate_st(code=code)
        assert res["success"] is True
        assert res["status"] == "success"

    @pytest.mark.parametrize("ladder_str", [
        "---[ ]---",
        "---[/]---",
        "---( )---",
        "---(S)---",
        "---(R)---",
        "RUNG 1",
        "NETWORK 1",
        "XIC LocalBit",
        "OTE OutBit",
    ])
    def test_ladder_logic_rejection_returns_failed_not_blocked(self, ladder_str):
        res = cscape_validate_st(code=ladder_str)
        assert res["success"] is False
        assert res["status"] == "failed"
        assert any("ladder" in e.lower() for e in res["errors"])

    def test_native_st_to_ld_conversion_blocked(self):
        assert STLadderInteropGuard.IN_GUI_CONVERSION_BLOCKED is True
        assert STLadderInteropGuard.NATIVE_CONVERSION_STATUS == "BLOCKED_NATIVE: DOCUMENT_ONLY"


class TestC1StructuredFailureLocations:
    """Verifies that all failure locations adhere strictly to schema."""

    def test_all_failure_location_fields_populated_with_explicit_location(self):
        raw = {
            "success": False,
            "status": "failed",
            "errors": ["Syntax error at line 5, col 12: unexpected token"],
        }
        norm = normalize_tool_result(raw, default_source="MyPOU")
        assert len(norm["failure_locations"]) > 0
        for loc in norm["failure_locations"]:
            assert "line" in loc and loc["line"] == 5
            assert "column" in loc and loc["column"] == 12
            assert "error_code" in loc and isinstance(loc["error_code"], str)
            assert "severity" in loc and isinstance(loc["severity"], str)
            assert "message" in loc and isinstance(loc["message"], str)
            assert "file_path" in loc and isinstance(loc["file_path"], str)


class TestC1NegativeAndPositiveMandates:
    """Rigorous verification of C1-N01 through C1-N06 negative tests and C1-P01 positive test."""

    def test_c1_n01_empty_dict_rejected(self):
        """C1-N01: Empty dict must NOT be accepted as success; must be inconclusive with INVALID_RESULT_CONTRACT."""
        norm = normalize_tool_result({})
        assert norm["success"] is False
        assert norm["status"] == "inconclusive"
        assert norm["error_code"] == "INVALID_RESULT_CONTRACT"
        assert len(norm["errors"]) > 0
        assert any("INVALID_RESULT_CONTRACT" in e for e in norm["errors"])
        assert len(norm["failure_locations"]) > 0
        assert norm["failure_locations"][0]["line"] is None
        assert norm["failure_locations"][0]["column"] is None

    def test_c1_n02_verified_status_rejected(self):
        """C1-N02: Status with 'VERIFIED' must NOT be normalized to success; must be inconclusive."""
        norm = normalize_tool_result({"status": "VERIFIED", "message": "Operation claimed verified"})
        assert norm["success"] is False
        assert norm["status"] == "inconclusive"
        assert norm["error_code"] == "INVALID_RESULT_CONTRACT"
        assert len(norm["errors"]) > 0
        assert "VERIFIED" not in str(norm["status"])

    def test_c1_n03_100_percent_status_rejected(self):
        """C1-N03: Status with '100%' must NOT be normalized to success; must be inconclusive."""
        norm = normalize_tool_result({"status": "100%", "message": "Work 100% complete"})
        assert norm["success"] is False
        assert norm["status"] == "inconclusive"
        assert norm["error_code"] == "INVALID_RESULT_CONTRACT"
        assert len(norm["errors"]) > 0
        assert "100%" not in str(norm["status"])

    def test_c1_n04_unknown_status_rejected(self):
        """C1-N04: Unknown status candidate (e.g. banana, BOGUS_STATUS) must NOT default to success; must be inconclusive."""
        for unknown in ["banana", "BOGUS_STATUS"]:
            norm = normalize_tool_result({"status": unknown, "message": f"Arbitrary invented status {unknown}"})
            assert norm["success"] is False
            assert norm["status"] == "inconclusive"
            assert norm["error_code"] == "INVALID_RESULT_CONTRACT"
            assert len(norm["errors"]) > 0

    def test_c1_n05_decorated_none_rejected(self):
        """C1-N05: Tool returning None must NOT be decorated as success=True; must fail closed with inconclusive."""
        @enforce_mcp_status_contract(default_source="TestFunction", default_error_code="TEST_ERROR")
        def dummy_returning_none():
            return None

        res = dummy_returning_none()
        assert res["success"] is False
        assert res["status"] == "inconclusive"
        assert res["error_code"] == "INVALID_RESULT_CONTRACT"
        assert len(res["errors"]) > 0
        assert any("returned invalid result" in e for e in res["errors"])

    def test_c1_n06_success_error_diagnostic_contradiction_rejected(self):
        """C1-N06: Contradiction between success=True and ERROR severity diagnostic must force status='failed'."""
        raw = {
            "success": True,
            "status": "success",
            "diagnostics": [
                {
                    "severity": "ERROR",
                    "level": "ERROR",
                    "message": "Fatal syntax anomaly in compilation stream",
                }
            ],
        }
        norm = normalize_tool_result(raw, default_source="ContradictionProbe")
        assert norm["success"] is False
        assert norm["status"] == "failed"
        assert norm["error_code"] == "INVALID_RESULT_CONTRACT"
        assert any("contradiction" in e.lower() for e in norm["errors"])

    def test_c1_no_invented_line_col_1(self):
        """Unlocated errors must preserve line=None, column=None instead of fabricating line 1, col 1."""
        raw = {
            "success": False,
            "errors": ["General unlocated communication failure"],
        }
        norm = normalize_tool_result(raw, default_source="UnlocatedProbe")
        assert len(norm["failure_locations"]) > 0
        loc = norm["failure_locations"][0]
        assert loc["line"] is None
        assert loc["column"] is None
        assert loc["error_code"] == "GENERIC_ERROR"

    def test_c1_p01_positive_contract_preservation(self):
        """C1-P01: Valid successful and blocked payloads preserve canonical contract without corruption."""
        # 1. Valid success
        valid_success = {
            "success": True,
            "status": "success",
            "project_name": "ValidProject",
            "variables": [{"name": "StartPb", "address": "%I1"}],
        }
        norm_s = normalize_tool_result(valid_success, default_source="ValidTool")
        assert norm_s["success"] is True
        assert norm_s["status"] == "success"
        assert len(norm_s["errors"]) == 0
        assert norm_s["project_name"] == "ValidProject"

        # 2. Valid blocked (safety lockout preserved)
        valid_blocked = {
            "status": "blocked",
            "error_code": "HARDWARE_LOCKOUT",
            "errors": ["Hardware communication port COM3 is locked out by safety policy"],
        }
        norm_b = normalize_tool_result(valid_blocked, default_source="SafetyTool")
        assert norm_b["success"] is False
        assert norm_b["status"] == "blocked"
        assert norm_b["status"] != "failed"
        assert norm_b["status"] != "inconclusive"
        assert len(norm_b["errors"]) > 0


class TestC1NormalizerFalseSuccessExtendedContracts:
    """Comprehensive verification of C1-N07 through C1-N17 false success elimination in normalize_tool_result."""

    def test_c1_n07_error_count_contradiction_rejected(self):
        """C1-N07: Claims success=True but error_count > 0 must be rejected fail-closed as failed with INVALID_RESULT_CONTRACT."""
        raw = {"success": True, "error_count": 1, "status": "success"}
        norm = normalize_tool_result(raw, default_source="ErrCountProbe")
        assert norm["success"] is False
        assert norm["status"] == "failed"
        assert norm["error_code"] == "INVALID_RESULT_CONTRACT"
        assert any("error_count" in e for e in norm["errors"])

    def test_c1_n08_error_count_without_status_fails_closed(self):
        """C1-N08: Dictionary with error_count > 0 and no status must fail closed with non-empty errors."""
        raw = {"error_count": 3}
        norm = normalize_tool_result(raw, default_source="ErrCountOnlyProbe")
        assert norm["success"] is False
        assert norm["status"] == "failed"
        assert len(norm["errors"]) > 0
        assert any("error_count" in e for e in norm["errors"])

    def test_c1_n09_errors_list_contradiction_rejected(self):
        """C1-N09: Claims status='success' or 'passed' but contains non-empty errors list must fail closed."""
        for passed_status in ["success", "passed", "ok"]:
            raw = {"status": passed_status, "errors": ["Syntax verification failed at rung 3"]}
            norm = normalize_tool_result(raw, default_source="ErrorListProbe")
            assert norm["success"] is False
            assert norm["status"] == "failed"
            assert len(norm["errors"]) == 1
            assert len(norm["failure_locations"]) == 1

    def test_c1_n10_is_clean_false_rejected(self):
        """C1-N10: Result with is_clean=False must never be success."""
        raw = {"status": "success", "is_clean": False}
        norm = normalize_tool_result(raw, default_source="CleanProbe")
        assert norm["success"] is False
        assert norm["status"] == "failed"
        assert norm["error_code"] == "INVALID_RESULT_CONTRACT"

        raw2 = {"is_clean": False}
        norm2 = normalize_tool_result(raw2, default_source="CleanProbe2")
        assert norm2["success"] is False
        assert norm2["status"] == "failed"

    def test_c1_n11_compile_and_build_successful_false_contradiction(self):
        """C1-N11: Result claiming success but compile_successful=False or build_successful=False must fail closed."""
        raw1 = {"status": "success", "compile_successful": False}
        norm1 = normalize_tool_result(raw1, default_source="CompileSuccessfulProbe")
        assert norm1["success"] is False
        assert norm1["status"] == "failed"
        assert norm1["error_code"] == "INVALID_RESULT_CONTRACT"

        raw2 = {"status": "success", "build_successful": False}
        norm2 = normalize_tool_result(raw2, default_source="BuildSuccessfulProbe")
        assert norm2["success"] is False
        assert norm2["status"] == "failed"
        assert norm2["error_code"] == "INVALID_RESULT_CONTRACT"

    def test_c1_n12_valid_false_contradiction(self):
        """C1-N12: Result claiming success but valid=False must fail closed."""
        raw = {"status": "success", "valid": False}
        norm = normalize_tool_result(raw, default_source="ValidProbe")
        assert norm["success"] is False
        assert norm["status"] == "failed"
        assert norm["error_code"] == "INVALID_RESULT_CONTRACT"

    def test_c1_n13_ready_for_tests_false_rejected(self):
        """C1-N13: Gate result with ready_for_tests=False must be inconclusive."""
        raw1 = {"status": "success", "ready_for_tests": False}
        norm1 = normalize_tool_result(raw1, default_source="GateReadyProbe")
        assert norm1["success"] is False
        assert norm1["status"] == "inconclusive"
        assert norm1["error_code"] == "INVALID_RESULT_CONTRACT"

        raw2 = {"ready_for_tests": False}
        norm2 = normalize_tool_result(raw2, default_source="GateReadyProbe2")
        assert norm2["success"] is False
        assert norm2["status"] == "inconclusive"

    def test_c1_n14_failed_flag_true_rejected(self):
        """C1-N14: Result with failed=True must fail closed."""
        raw1 = {"status": "success", "failed": True}
        norm1 = normalize_tool_result(raw1, default_source="FailedFlagProbe")
        assert norm1["success"] is False
        assert norm1["status"] == "failed"
        assert norm1["error_code"] == "INVALID_RESULT_CONTRACT"

        raw2 = {"failed": True}
        norm2 = normalize_tool_result(raw2, default_source="FailedFlagProbe2")
        assert norm2["success"] is False
        assert norm2["status"] == "failed"

    def test_c1_n15_non_zero_exit_code_rejected(self):
        """C1-N15: Process exit_code != 0 or returncode != 0 must fail closed."""
        raw1 = {"status": "success", "exit_code": 1}
        norm1 = normalize_tool_result(raw1, default_source="ExitCodeProbe")
        assert norm1["success"] is False
        assert norm1["status"] == "failed"
        assert norm1["error_code"] == "INVALID_RESULT_CONTRACT"

        raw2 = {"returncode": 127}
        norm2 = normalize_tool_result(raw2, default_source="ReturnCodeProbe")
        assert norm2["success"] is False
        assert norm2["status"] == "failed"

    def test_c1_n16_timeout_rejected(self):
        """C1-N16: Result with timed_out=True must fail closed."""
        raw1 = {"status": "success", "timed_out": True}
        norm1 = normalize_tool_result(raw1, default_source="TimeoutProbe")
        assert norm1["success"] is False
        assert norm1["status"] == "failed"
        assert norm1["error_code"] == "INVALID_RESULT_CONTRACT"

        raw2 = {"timed_out": True}
        norm2 = normalize_tool_result(raw2, default_source="TimeoutProbe2")
        assert norm2["success"] is False
        assert norm2["status"] == "failed"

    def test_c1_n17_failure_locations_with_error_rejected(self):
        """C1-N17: Claims success=True but failure_locations contains ERROR severity must fail closed."""
        raw = {
            "success": True,
            "status": "success",
            "failure_locations": [
                {
                    "severity": "ERROR",
                    "file_path": "Main.st",
                    "line": 4,
                    "column": 1,
                    "message": "Undeclared identifier",
                }
            ],
        }
        norm = normalize_tool_result(raw, default_source="LocErrorProbe")
        assert norm["success"] is False
        assert norm["status"] == "failed"
        assert norm["error_code"] == "INVALID_RESULT_CONTRACT"


