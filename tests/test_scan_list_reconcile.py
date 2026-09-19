"""Contract Test Suite for FastMCP Scan-List Reconciliation Tool (cscape_reconcile_scan_list).

Verifies:
- Default reconciliation on TankLevel_P5_Dedicated (native: 0, planned: 3, discrepancy: 3, reconciled: False).
- fail_on_discrepancy=True returning status: failed with DISCREPANCY_DETECTED.
- Fail-closed safety lockouts (plc_download=True, verified_live=True, COM1-COM256).
- Negative handling for nonexistent project, missing inventory file, corrupted inventory, and invalid containers.
- Pydantic v2 extra='forbid' parameter injection protection.
- FastMCP server registration and 43-tool schema parity.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
import pytest
from pydantic import ValidationError

from src.mcp.schemas import (
    CscapeReconcileScanListInput,
    CscapeReconcileScanListOutput,
    TOOL_SCHEMAS,
)
from src.mcp.tools import cscape_reconcile_scan_list
from src.mcp.server import create_mcp_server


DEDICATED_PROJECT = "artifacts/projects/TankLevel_P5_Dedicated/TankLevel_P5_Dedicated.csp"
DEDICATED_INVENTORY = "artifacts/projects/TankLevel_P5_Dedicated/modbus_protocol_inventory.json"


# =============================================================================
# 1. Default Reconciliation Baseline on TankLevel_P5_Dedicated
# =============================================================================

def test_default_reconciliation_tank_level_p5():
    """Verify default offline reconciliation reports native: 0, planned: 3, discrepancy: 3, reconciled: False."""
    res = cscape_reconcile_scan_list(
        project_path=DEDICATED_PROJECT,
        inventory_path=DEDICATED_INVENTORY,
        port="MJ1",
        fail_on_discrepancy=False,
    )
    assert res["status"] == "success"
    assert res["success"] is True
    assert res["native_count"] == 0
    assert res["planned_count"] == 3
    assert res["discrepancy_count"] == 3
    assert res["reconciled"] is False
    assert res["reconciliation_status"] in ("discrepancy_detected", "pending_p7")

    # Verify exact discrepancy transactions
    tx_ids = [item["transaction_id"] for item in res["discrepancies"]]
    assert "TX01_LEVEL_PV" in tx_ids
    assert "TX02_INFLOW_RATE" in tx_ids
    assert "TX03_DISCHARGE_PRESS" in tx_ids

    target_regs = [item["target_ocs_register"] for item in res["discrepancies"]]
    assert "%AI1" in target_regs
    assert "%AI2" in target_regs
    assert "%AI3" in target_regs

    # Safety assertions
    assert res["offline_safety_enforced"] is True
    assert res["zero_download_enforced"] is True
    assert res["verified_live"] is False
    assert res["plc_download"] is False
    assert res["pending_gate"] == "P7_PHYSICAL_PLC_DOWNLOAD_AND_COMMISSIONING"


def test_reconciliation_transaction_fidelity():
    """Verify deep transaction fields in the discrepancy report."""
    res = cscape_reconcile_scan_list(
        project_path=DEDICATED_PROJECT,
        inventory_path=DEDICATED_INVENTORY,
        port="MJ1",
    )
    assert res["status"] == "success"
    discrepancies = {d["transaction_id"]: d for d in res["discrepancies"]}

    tx1 = discrepancies["TX01_LEVEL_PV"]
    assert tx1["unit_id"] == 1
    assert tx1["modicon_address"] == 40001
    assert tx1["wire_offset"] == 0
    assert tx1["target_ocs_register"] == "%AI1"
    assert tx1["variable_name"] == "TankLevelPV"
    assert tx1["engineering_unit"] == "%"

    tx2 = discrepancies["TX02_INFLOW_RATE"]
    assert tx2["unit_id"] == 2
    assert tx2["modicon_address"] == 40002
    assert tx2["wire_offset"] == 1
    assert tx2["target_ocs_register"] == "%AI2"
    assert tx2["variable_name"] == "InflowRatePV"
    assert tx2["engineering_unit"] == "L/min"

    tx3 = discrepancies["TX03_DISCHARGE_PRESS"]
    assert tx3["unit_id"] == 3
    assert tx3["modicon_address"] == 40003
    assert tx3["wire_offset"] == 2
    assert tx3["target_ocs_register"] == "%AI3"
    assert tx3["variable_name"] == "DischargePressPV"
    assert tx3["engineering_unit"] == "bar"


# =============================================================================
# 2. Fail-Closed Discrepancy Assertion
# =============================================================================

def test_fail_on_discrepancy_returns_failed_status():
    """Verify fail_on_discrepancy=True triggers status: failed with DISCREPANCY_DETECTED."""
    res = cscape_reconcile_scan_list(
        project_path=DEDICATED_PROJECT,
        fail_on_discrepancy=True,
    )
    assert res["status"] == "failed"
    assert res["success"] is False
    assert res["error_code"] == "DISCREPANCY_DETECTED"
    assert res["discrepancy_count"] == 3
    assert res["reconciled"] is False
    assert "unsynchronized transaction(s)" in res["message"] or "discrepancy detected" in res["message"].lower()


# =============================================================================
# 3. Fail-Closed Safety Lockouts
# =============================================================================

def test_hardware_lockout_when_plc_download_true():
    """Verify plc_download=True triggers fail-closed security lockout."""
    res = cscape_reconcile_scan_list(
        project_path=DEDICATED_PROJECT,
        plc_download=True,
    )
    assert res["status"] == "blocked"
    assert res["success"] is False
    assert res["error_code"] in ("SECURITY_BLOCKED", "PLC_DOWNLOAD_SAFETY_LOCKOUT")
    assert res["plc_download"] is True
    assert res["zero_download_enforced"] is False


def test_gate_invariant_when_verified_live_true():
    """Verify verified_live=True triggers fail-closed gate policy lockout."""
    res = cscape_reconcile_scan_list(
        project_path=DEDICATED_PROJECT,
        verified_live=True,
    )
    assert res["status"] == "blocked"
    assert res["success"] is False
    assert res["error_code"] in ("SECURITY_BLOCKED", "VERIFIED_LIVE_SAFETY_LOCKOUT")
    assert res["verified_live"] is True


def test_physical_serial_port_lockout():
    """Verify physical COM ports (e.g. COM1, COM24) are blocked fail-closed."""
    for com_port in ("COM1", "com1", "COM24", "\\\\.\\COM5"):
        res = cscape_reconcile_scan_list(
            project_path=DEDICATED_PROJECT,
            port=com_port,
        )
        assert res["status"] == "blocked"
        assert res["success"] is False
        assert res["error_code"] in ("SECURITY_BLOCKED", "PHYSICAL_PORT_LOCKOUT")


# =============================================================================
# 4. Negative File & Container Boundary Tests
# =============================================================================

def test_nonexistent_project_returns_failed():
    """Verify querying a nonexistent project returns status 'failed'."""
    res = cscape_reconcile_scan_list(
        project_path="artifacts/projects/nonexistent_container_xyz.csp"
    )
    assert res["status"] == "failed"
    assert res["success"] is False
    assert res["error_code"] in ("PROJECT_NOT_FOUND", "RECONCILE_ERROR")


def test_missing_inventory_file_returns_failed():
    """Verify querying a nonexistent inventory file returns status 'failed'."""
    res = cscape_reconcile_scan_list(
        project_path=DEDICATED_PROJECT,
        inventory_path="artifacts/projects/TankLevel_P5_Dedicated/missing_inventory_xyz.json",
    )
    assert res["status"] == "failed"
    assert res["success"] is False
    assert res["error_code"] in ("INVENTORY_FILE_NOT_FOUND", "INVENTORY_NOT_FOUND", "RECONCILE_ERROR")


def test_invalid_cfbf_container_returns_failed(tmp_path: Path):
    """Verify non-CFBF file returns status 'failed' with INVALID_CFBF_CONTAINER."""
    corrupt_file = tmp_path / "corrupt.csp"
    corrupt_file.write_text("NOT_A_VALID_CFBF_FILE", encoding="utf-8")

    res = cscape_reconcile_scan_list(project_path=str(corrupt_file))
    assert res["status"] == "failed"
    assert res["success"] is False
    assert res["error_code"] in ("INVALID_CFBF_CONTAINER", "RECONCILE_ERROR")


def test_corrupted_inventory_json_returns_failed(tmp_path: Path):
    """Verify corrupted inventory JSON returns status 'failed'."""
    corrupt_inv = tmp_path / "corrupt_inv.json"
    corrupt_inv.write_text("{ unclosed json structure", encoding="utf-8")

    res = cscape_reconcile_scan_list(
        project_path=DEDICATED_PROJECT,
        inventory_path=str(corrupt_inv),
    )
    assert res["status"] == "failed"
    assert res["success"] is False
    assert res["error_code"] in ("INVENTORY_JSON_DECODE_ERROR", "RECONCILE_ERROR")


# =============================================================================
# 5. Pydantic v2 Schema Strictness (extra='forbid')
# =============================================================================

def test_pydantic_schema_extra_forbid():
    """Verify extra fields are strictly forbidden in CscapeReconcileScanListInput."""
    with pytest.raises(ValidationError) as exc:
        CscapeReconcileScanListInput(
            project_path=DEDICATED_PROJECT,
            unauthorized_field="malicious_payload",
        )
    assert "extra_forbidden" in str(exc.value) or "Extra inputs are not permitted" in str(exc.value)


def test_pydantic_schema_direct_validators():
    """Verify direct Pydantic validators reject prohibited parameters."""
    with pytest.raises(ValidationError):
        CscapeReconcileScanListInput(plc_download=True)

    with pytest.raises(ValidationError):
        CscapeReconcileScanListInput(verified_live=True)

    with pytest.raises(ValidationError):
        CscapeReconcileScanListInput(port="COM1")


# =============================================================================
# 6. Positive Reconciled Match Scenario
# =============================================================================

def test_fully_reconciled_when_inventory_matches_native(tmp_path: Path):
    """Verify clean reconciliation when planned matches native (0 planned vs 0 native)."""
    empty_inventory = tmp_path / "empty_inventory.json"
    empty_inventory.write_text(json.dumps({
        "inventory_id": "Empty_Mock_Inventory",
        "channels": [
            {
                "channel_id": "CH_MJ1_RTU",
                "rtu_endpoint": {"serial_port": "MJ1_RS485", "driver_label": "CT RTU Modbus CMP v 5.05"},
            }
        ],
        "devices": [],
        "scan_list": [],
        "scan_list_count": 0,
    }), encoding="utf-8")

    res = cscape_reconcile_scan_list(
        project_path=DEDICATED_PROJECT,
        inventory_path=str(empty_inventory),
        fail_on_discrepancy=True,
    )
    assert res["status"] == "success"
    assert res["success"] is True
    assert res["native_count"] == 0
    assert res["planned_count"] == 0
    assert res["discrepancy_count"] == 0
    assert res["reconciled"] is True
    assert res["reconciliation_status"] == "reconciled"


# =============================================================================
# 7. FastMCP Server Registration & 43-Tool Parity
# =============================================================================

@pytest.mark.asyncio
async def test_fastmcp_server_announces_tool_and_schema_parity():
    """Verify cscape_reconcile_scan_list is announced by FastMCP server (43 tools)."""
    srv = create_mcp_server()
    tools = await srv.list_tools()
    tool_map = {t.name: t for t in tools}

    assert "cscape_reconcile_scan_list" in tool_map
    assert "cscape_reconcile_scan_list" in TOOL_SCHEMAS
    assert len(tools) == 43
    assert len(TOOL_SCHEMAS) == 43

    schema_info = TOOL_SCHEMAS["cscape_reconcile_scan_list"]
    assert schema_info["input"] is CscapeReconcileScanListInput
    assert schema_info["output"] is CscapeReconcileScanListOutput
