"""Contract Test Suite for FastMCP MJ1 Scan-List Evidence Schema Validation.

Mandate:
- Offline FastMCP validation for MJ1 / Modbus scan-list evidence schema.
- Enforce canonical 4-state contract: status in ("success", "failed", "blocked", "inconclusive").
- Zero PLC download: plc_download must strictly be False (fail-closed hardware lockout).
- Zero live verification: verified_live must strictly be False (anti-false-victory invariant).
- Scan list baseline: scan_list_status == 'empty', native_fill_status == 'blocked_offline'.
- Pydantic v2 extra='forbid' parameter injection protection.
- FastMCP stdio server tool registration and schema parity.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
import pytest

from src.mcp.schemas import (
    ScanListEvidencePayload,
    CscapeValidateScanListEvidenceInput,
    CscapeValidateScanListEvidenceOutput,
    TOOL_SCHEMAS,
)
from src.mcp.tools import cscape_validate_scan_list_evidence
from src.mcp.server import create_mcp_server


@pytest.fixture
def valid_evidence_dict() -> Dict[str, Any]:
    """Authentic MJ1 scan list evidence dictionary payload."""
    return {
        "project": "TankLevel_P5_Dedicated.csp",
        "port": "MJ1",
        "protocol": "CT RTU Modbus CMP v5.05",
        "scan_list_status": "empty",
        "native_fill_status": "blocked_offline",
        "blocker": "Native add requires a configured target node/device and/or live PLC context.",
        "plc_download": False,
        "verified_live": False,
        "scope": "offline_product_documentation",
    }


# =============================================================================
# 1. Authentic Artifact File Validation
# =============================================================================

def test_validate_authentic_downloads_artifact_file():
    """Verify authentic Downloads/mj1_devices_scan_evidence.json passes validation."""
    downloads_path = Path(r"C:\Users\ArmandoSilva\Downloads\mj1_devices_scan_evidence.json")
    if not downloads_path.exists():
        pytest.skip(f"Downloads artifact not found at {downloads_path}")

    res = cscape_validate_scan_list_evidence(evidence_path=str(downloads_path))

    assert res["status"] == "success"
    assert res["success"] is True
    assert res["project"] == "TankLevel_P5_Dedicated.csp"
    assert res["port"] == "MJ1"
    assert res["protocol"] == "CT RTU Modbus CMP v5.05"
    assert res["scan_list_status"] == "empty"
    assert res["native_fill_status"] == "blocked_offline"
    assert res["plc_download"] is False
    assert res["verified_live"] is False
    assert res["offline_safety_enforced"] is True
    assert res["zero_download_enforced"] is True


def test_validate_authentic_ops_artifacts_file():
    """Verify mirrored ops/artifacts/mj1_devices_scan_evidence.json passes validation."""
    ops_path = Path(r"C:\Users\ArmandoSilva\ops\artifacts\mj1_devices_scan_evidence.json")
    if not ops_path.exists():
        ops_path = Path(r"C:\HornerAI\horner-cscape-mcp\ops\artifacts\mj1_devices_scan_evidence.json")
    if not ops_path.exists():
        pytest.skip(f"Ops artifact not found at {ops_path}")

    res = cscape_validate_scan_list_evidence(evidence_path=str(ops_path))

    assert res["status"] == "success"
    assert res["success"] is True
    assert res["scan_list_status"] == "empty"
    assert res["native_fill_status"] == "blocked_offline"
    assert res["plc_download"] is False
    assert res["verified_live"] is False


def test_validate_temp_file_with_valid_payload(tmp_path: Path, valid_evidence_dict: Dict[str, Any]):
    """Verify valid JSON file created dynamically passes tool validation."""
    test_file = tmp_path / "valid_test_evidence.json"
    test_file.write_text(json.dumps(valid_evidence_dict, indent=2), encoding="utf-8")

    res = cscape_validate_scan_list_evidence(evidence_path=str(test_file))

    assert res["status"] == "success"
    assert res["success"] is True
    assert res["project"] == "TankLevel_P5_Dedicated.csp"
    assert res["port"] == "MJ1"
    assert res["evidence_valid"] is True


# =============================================================================
# 2. In-Memory Raw Dictionary Validation
# =============================================================================

def test_validate_in_memory_dictionary(valid_evidence_dict: Dict[str, Any]):
    """Verify direct raw dictionary execution without disk I/O."""
    res = cscape_validate_scan_list_evidence(evidence_data=valid_evidence_dict)

    assert res["status"] == "success"
    assert res["success"] is True
    assert res["project"] == "TankLevel_P5_Dedicated.csp"
    assert res["validated_evidence"]["port"] == "MJ1"
    assert res["validated_evidence"]["scan_list_status"] == "empty"
    assert res["validated_evidence"]["plc_download"] is False
    assert res["validated_evidence"]["verified_live"] is False


def test_validate_pydantic_schema_direct(valid_evidence_dict: Dict[str, Any]):
    """Verify direct Pydantic model instantiation and parsing."""
    model = ScanListEvidencePayload(**valid_evidence_dict)

    assert model.project == "TankLevel_P5_Dedicated.csp"
    assert model.port == "MJ1"
    assert model.scan_list_status == "empty"
    assert model.native_fill_status == "blocked_offline"
    assert model.plc_download is False
    assert model.verified_live is False


# =============================================================================
# 3. Offline Baseline Invariants (Empty Scan List & Blocked Native Fill)
# =============================================================================

def test_rejection_when_scan_list_status_not_empty(valid_evidence_dict: Dict[str, Any]):
    """Assert error when scan_list_status is 'populated' in offline mode."""
    tampered = dict(valid_evidence_dict)
    tampered["scan_list_status"] = "populated"

    res = cscape_validate_scan_list_evidence(evidence_data=tampered)

    assert res["status"] == "failed"
    assert res["success"] is False
    assert res["error_code"] == "SCAN_LIST_STATUS_MISMATCH"
    assert "Expected scan_list_status == 'empty'" in res["errors"][0]


def test_rejection_when_native_fill_status_not_blocked(valid_evidence_dict: Dict[str, Any]):
    """Assert error when native_fill_status claims 'success' in offline mode."""
    tampered = dict(valid_evidence_dict)
    tampered["native_fill_status"] = "success"

    res = cscape_validate_scan_list_evidence(evidence_data=tampered)

    assert res["status"] == "failed"
    assert res["success"] is False
    assert res["error_code"] == "NATIVE_FILL_STATUS_MISMATCH"
    assert "Expected native_fill_status == 'blocked_offline'" in res["errors"][0]


# =============================================================================
# 4. Fail-Closed Hardware & Live Verification Bans
# =============================================================================

def test_hardware_lockout_when_plc_download_true_in_data(valid_evidence_dict: Dict[str, Any]):
    """Assert fail-closed status='blocked' when plc_download is True in evidence."""
    tampered = dict(valid_evidence_dict)
    tampered["plc_download"] = True

    res = cscape_validate_scan_list_evidence(evidence_data=tampered)

    assert res["status"] == "blocked"
    assert res["success"] is False
    assert res["error_code"] in ("SECURITY_BLOCKED", "PLC_DOWNLOAD_SAFETY_LOCKOUT")
    assert res["offline_safety_enforced"] is False
    assert res["zero_download_enforced"] is False


def test_hardware_lockout_when_plc_download_true_in_tool_argument():
    """Assert fail-closed status='blocked' when plc_download argument is passed as True."""
    res = cscape_validate_scan_list_evidence(evidence_path="any.json", plc_download=True)

    assert res["status"] == "blocked"
    assert res["success"] is False
    assert res["error_code"] in ("SECURITY_BLOCKED", "PLC_DOWNLOAD_SAFETY_LOCKOUT")


def test_gate_invariant_when_verified_live_true_in_data(valid_evidence_dict: Dict[str, Any]):
    """Assert fail-closed status='blocked' when verified_live is True in evidence."""
    tampered = dict(valid_evidence_dict)
    tampered["verified_live"] = True

    res = cscape_validate_scan_list_evidence(evidence_data=tampered)

    assert res["status"] == "blocked"
    assert res["success"] is False
    assert res["error_code"] in ("SECURITY_BLOCKED", "VERIFIED_LIVE_SAFETY_LOCKOUT")
    assert res["offline_safety_enforced"] is False


def test_gate_invariant_when_verified_live_true_in_tool_argument():
    """Assert fail-closed status='blocked' when verified_live argument is passed as True."""
    res = cscape_validate_scan_list_evidence(evidence_path="any.json", verified_live=True)

    assert res["status"] == "blocked"
    assert res["success"] is False
    assert res["error_code"] in ("SECURITY_BLOCKED", "VERIFIED_LIVE_SAFETY_LOCKOUT")


# =============================================================================
# 5. Boundary & Negative Inputs (Missing Fields, Extra Fields, Bad Extensions)
# =============================================================================

def test_missing_both_inputs_returns_inconclusive():
    """Assert status='inconclusive' when neither evidence_path nor evidence_data provided."""
    res = cscape_validate_scan_list_evidence()

    assert res["status"] == "inconclusive"
    assert res["success"] is False
    assert res["error_code"] == "MISSING_EVIDENCE_INPUT"


def test_nonexistent_evidence_file_returns_failed():
    """Assert status='failed' when evidence file does not exist."""
    res = cscape_validate_scan_list_evidence(evidence_path="nonexistent_file_xyz123.json")

    assert res["status"] == "failed"
    assert res["success"] is False
    assert res["error_code"] == "EVIDENCE_FILE_NOT_FOUND"


def test_extra_parameters_forbidden_in_pydantic_payload(valid_evidence_dict: Dict[str, Any]):
    """Assert extra fields rejected fail-closed under extra='forbid'."""
    tampered = dict(valid_evidence_dict)
    tampered["unauthorized_download_flag"] = "dangerous"

    res = cscape_validate_scan_list_evidence(evidence_data=tampered)

    assert res["status"] == "failed"
    assert res["success"] is False
    assert res["error_code"] == "SCHEMA_VALIDATION_ERROR"
    assert any("extra" in err.lower() for err in res["errors"])


def test_invalid_container_extension_rejected(valid_evidence_dict: Dict[str, Any]):
    """Assert project filename must end with .csp or .cpj."""
    tampered = dict(valid_evidence_dict)
    tampered["project"] = "TankLevel_P5_Dedicated.txt"

    res = cscape_validate_scan_list_evidence(evidence_data=tampered)

    assert res["status"] == "failed"
    assert res["success"] is False
    assert res["error_code"] == "SCHEMA_VALIDATION_ERROR"


# =============================================================================
# 6. FastMCP Server Registration & 41-Tool Parity
# =============================================================================

@pytest.mark.asyncio
async def test_fastmcp_server_registers_scan_list_evidence_tool():
    """Verify tool is registered on MCPServer and parity is maintained (43 tools)."""
    server = create_mcp_server()
    tools = await server.list_tools()
    tool_map = {t.name: t for t in tools}

    assert "cscape_validate_scan_list_evidence" in tool_map
    assert len(tools) == 43
    assert len(TOOL_SCHEMAS) == 43

    tool = tool_map["cscape_validate_scan_list_evidence"]
    assert "Modbus scan list evidence" in tool.description
