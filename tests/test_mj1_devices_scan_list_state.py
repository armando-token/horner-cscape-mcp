"""Contract Test Suite for MJ1 Devices and Scan List State Documentation.

Task: OFFLINE_MJ1_DEVICES_AND_SCAN_LIST_STATE_DOCUMENTATION
Target: TankLevel_P5_Dedicated.csp / Port MJ1 / Protocol CT RTU Modbus CMP v5.05
Directives:
- Offline environment only (offline/DEV [PRODUCT_EVIDENCE]).
- Zero PLC download: plc_download must strictly be False.
- Zero live verification: verified_live must strictly be False.
- Scan list baseline: scan_list_status == 'empty', native_fill_status == 'blocked_offline'.
- Planned inventory: 3 devices (DEV_LT01, DEV_FT01, DEV_PT01), 3 scan transactions.
- Reconciliation discrepancy delta = -3 (pending Phase P7 commissioning).
- Dual-root artifact evidence verification.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
import pytest

from src.mcp.tools import (
    cscape_inspect_scan_list,
    cscape_reconcile_scan_list,
    cscape_validate_scan_list_evidence,
)
from src.security.guard import SecurityGuard, SecurityError


DEDICATED_PROJECT = "artifacts/projects/TankLevel_P5_Dedicated/TankLevel_P5_Dedicated.csp"
DEDICATED_INVENTORY = "artifacts/projects/TankLevel_P5_Dedicated/modbus_protocol_inventory.json"
DOWNLOADS_DIR = Path(r"C:\Users\ArmandoSilva\Downloads")
OPS_ARTIFACTS_SILVA = Path(r"C:\Users\ArmandoSilva\ops\artifacts")
OPS_ARTIFACTS_HORNER = Path(r"C:\HornerAI\horner-cscape-mcp\ops\artifacts")


# =============================================================================
# 1. Native MJ1 Scan List Inspection (Empty Baseline & Offline Blocker)
# =============================================================================

def test_mj1_scan_list_empty_baseline():
    """Verify native inspection of MJ1 confirms empty scan list and blocked_offline fill status."""
    res = cscape_inspect_scan_list(
        project_path=DEDICATED_PROJECT,
        port="MJ1",
        protocol="CT RTU Modbus CMP v5.05",
        require_populated=False,
    )
    assert res["status"] == "success"
    assert res["success"] is True
    assert res["project"] == "TankLevel_P5_Dedicated.csp"
    assert res["port"] == "MJ1"
    assert res["protocol"] == "CT RTU Modbus CMP v5.05"
    assert res["count"] == 0
    assert res["scan_list"] == []
    assert res["scan_list_status"] == "empty"
    assert res["native_fill_status"] == "blocked_offline"
    assert "no PLC connection or download was permitted" in res["blocker"]
    assert res["pending_gate"] == "P7_PHYSICAL_PLC_DOWNLOAD_AND_COMMISSIONING"
    assert res["offline_safety_enforced"] is True
    assert res["zero_download_enforced"] is True
    assert res["verified_live"] is False
    assert res["plc_download"] is False


# =============================================================================
# 2. Planned Protocol Inventory Inspection (Devices & Channel Config)
# =============================================================================

def test_mj1_planned_channel_and_devices_inventory():
    """Verify sidecar protocol inventory defines MJ1 channel and 3 planned devices."""
    inv_path = Path(DEDICATED_INVENTORY)
    assert inv_path.exists(), f"Inventory missing at {inv_path}"

    data = json.loads(inv_path.read_text(encoding="utf-8"))
    assert data["project_name"] == "TankLevel_P5_Dedicated"
    assert data["devices_count"] == 3

    # Channel MJ1 configuration
    channels = {c["channel_id"]: c for c in data["channels"]}
    assert "CH_MJ1_RTU" in channels
    ch_mj1 = channels["CH_MJ1_RTU"]
    assert ch_mj1["transport"] == "MODBUS_RTU"
    assert ch_mj1["role"] == "CLIENT_MASTER_READ_ONLY"

    rtu = ch_mj1["rtu_endpoint"]
    assert rtu["serial_port"] == "MJ1_RS485"
    assert rtu["baud_rate"] == 19200
    assert rtu["data_bits"] == 8
    assert rtu["parity"] == "NONE"
    assert rtu["stop_bits"] == 1
    assert rtu["mode"] == "RS-485"
    assert "CT RTU Modbus CMP" in rtu["driver_label"]

    # Devices
    devices = {d["device_id"]: d for d in data["devices"]}
    assert len(devices) == 3
    assert "DEV_LT01" in devices
    assert "DEV_FT01" in devices
    assert "DEV_PT01" in devices

    dev1 = devices["DEV_LT01"]
    assert dev1["unit_id"] == 1
    assert "Tank Level" in dev1["device_name"]

    dev2 = devices["DEV_FT01"]
    assert dev2["unit_id"] == 2
    assert "Inflow" in dev2["device_name"]

    dev3 = devices["DEV_PT01"]
    assert dev3["unit_id"] == 3
    assert "Pressure" in dev3["device_name"]


# =============================================================================
# 3. Planned Scan List Transactions
# =============================================================================

def test_mj1_planned_scan_list_transactions():
    """Verify sidecar inventory defines 3 planned scan list transactions mapped to %AI1..%AI3."""
    inv_path = Path(DEDICATED_INVENTORY)
    data = json.loads(inv_path.read_text(encoding="utf-8"))

    tx_map = {tx["transaction_id"]: tx for tx in data["scan_list"]}
    assert len(tx_map) == 3
    assert "TX01_LEVEL_PV" in tx_map
    assert "TX02_INFLOW_RATE" in tx_map
    assert "TX03_DISCHARGE_PRESS" in tx_map

    tx1 = tx_map["TX01_LEVEL_PV"]
    assert tx1["device_id"] == "DEV_LT01"
    assert tx1["unit_id"] == 1
    assert tx1["function_code"] == 3
    assert tx1["modicon_address"] == 40001
    assert tx1["target_ocs_register"] == "%AI1"
    assert tx1["variable_name"] == "TankLevelPV"
    assert tx1["engineering_unit"] == "%"

    tx2 = tx_map["TX02_INFLOW_RATE"]
    assert tx2["device_id"] == "DEV_FT01"
    assert tx2["unit_id"] == 2
    assert tx2["function_code"] == 3
    assert tx2["modicon_address"] == 40002
    assert tx2["target_ocs_register"] == "%AI2"
    assert tx2["variable_name"] == "InflowRatePV"
    assert tx2["engineering_unit"] == "L/min"

    tx3 = tx_map["TX03_DISCHARGE_PRESS"]
    assert tx3["device_id"] == "DEV_PT01"
    assert tx3["unit_id"] == 3
    assert tx3["function_code"] == 3
    assert tx3["modicon_address"] == 40003
    assert tx3["target_ocs_register"] == "%AI3"
    assert tx3["variable_name"] == "DischargePressPV"
    assert tx3["engineering_unit"] == "bar"


# =============================================================================
# 4. Planned vs. Native Reconciliation
# =============================================================================

def test_mj1_reconciliation_discrepancy_delta():
    """Verify reconciliation reports discrepancy delta of -3 pending Phase P7."""
    res = cscape_reconcile_scan_list(
        project_path=DEDICATED_PROJECT,
        inventory_path=DEDICATED_INVENTORY,
        port="MJ1",
        fail_on_discrepancy=False,
    )
    assert res["status"] == "success"
    assert res["native_count"] == 0
    assert res["planned_count"] == 3
    assert res["discrepancy_count"] == 3
    assert res["reconciled"] is False
    assert res["reconciliation_status"] in ("discrepancy_detected", "pending_p7")
    assert res["pending_gate"] == "P7_PHYSICAL_PLC_DOWNLOAD_AND_COMMISSIONING"
    assert res["zero_download_enforced"] is True
    assert res["verified_live"] is False


# =============================================================================
# 5. Downloads Evidence Files Validation
# =============================================================================

def test_downloads_mj1_devices_scan_evidence_json_valid():
    """Verify Downloads/mj1_devices_scan_evidence.json exists and passes schema validation."""
    p = DOWNLOADS_DIR / "mj1_devices_scan_evidence.json"
    assert p.exists(), f"Missing {p}"

    res = cscape_validate_scan_list_evidence(evidence_path=str(p))
    assert res["status"] == "success"
    assert res["project"] == "TankLevel_P5_Dedicated.csp"
    assert res["port"] == "MJ1"
    assert res["protocol"] == "CT RTU Modbus CMP v5.05"
    assert res["scan_list_status"] == "empty"
    assert res["native_fill_status"] == "blocked_offline"
    assert res["plc_download"] is False
    assert res["verified_live"] is False


def test_downloads_mj1_devices_scan_evidence_md_content():
    """Verify Downloads/mj1_devices_scan_evidence.md contains thorough documentation."""
    p = DOWNLOADS_DIR / "mj1_devices_scan_evidence.md"
    assert p.exists(), f"Missing {p}"

    content = p.read_text(encoding="utf-8")
    assert "TankLevel_P5_Dedicated.csp" in content
    assert "MJ1" in content
    assert "CT RTU Modbus CMP v5.05" in content
    assert "DEV_LT01" in content
    assert "DEV_FT01" in content
    assert "DEV_PT01" in content
    assert "TX01_LEVEL_PV" in content
    assert "blocked_offline" in content or "Blocked offline" in content or "BLOCKED_FAIL_CLOSED" in content
    assert "verified_live: false" in content
    assert "zero_plc_download: true" in content
    assert "PHASE P7" in content or "Phase P7" in content


def test_downloads_mj1_devices_scan_list_state_evidence_json():
    """Verify Downloads/mj1_devices_scan_list_state_evidence.json structure and assertions."""
    p = DOWNLOADS_DIR / "mj1_devices_scan_list_state_evidence.json"
    assert p.exists(), f"Missing {p}"

    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["status"] == "success"
    assert data["verified_live"] is False
    assert data["zero_plc_download"] is True
    assert data["target_project"]["project_name"] == "TankLevel_P5_Dedicated.csp"
    assert data["channel_configuration"]["port"] == "MJ1"
    assert data["channel_configuration"]["protocol"] == "CT RTU Modbus CMP v5.05"
    assert data["channel_configuration"]["baud_rate"] == 19200
    assert data["native_scan_list_state"]["count"] == 0
    assert data["native_scan_list_state"]["scan_list_status"] == "empty"
    assert data["native_scan_list_state"]["native_fill_status"] == "blocked_offline"
    assert len(data["planned_devices_inventory"]) == 3
    assert len(data["planned_scan_list_transactions"]) == 3
    assert data["reconciliation_summary"]["discrepancy_count"] == 3
    assert data["reconciliation_summary"]["reconciled"] is False
    assert data["phase_p7_deferral_declaration"]["status"] == "DEFERRED_MANUAL_ENGINEER_LOAD"


def test_downloads_mj1_devices_scan_list_state_evidence_md():
    """Verify Downloads/mj1_devices_scan_list_state_evidence.md exists and contains full documentation."""
    p = DOWNLOADS_DIR / "mj1_devices_scan_list_state_evidence.md"
    assert p.exists(), f"Missing {p}"

    content = p.read_text(encoding="utf-8")
    assert "TankLevel_P5_Dedicated.csp" in content
    assert "MJ1" in content
    assert "CT RTU Modbus CMP v5.05" in content
    assert "DEV_LT01" in content
    assert "TX01_LEVEL_PV" in content
    assert "discrepancy_detected" in content


# =============================================================================
# 6. Dual-Root Parity Checks
# =============================================================================

def test_dual_root_parity_mj1_evidence():
    """Verify evidence files are synchronized across Silva and Horner dual roots."""
    silva_json = OPS_ARTIFACTS_SILVA / "mj1_devices_scan_evidence.json"
    horner_json = OPS_ARTIFACTS_HORNER / "mj1_devices_scan_evidence.json"
    assert silva_json.exists()
    assert horner_json.exists()
    assert silva_json.read_text(encoding="utf-8") == horner_json.read_text(encoding="utf-8")

    silva_md = OPS_ARTIFACTS_SILVA / "mj1_devices_scan_evidence.md"
    horner_md = OPS_ARTIFACTS_HORNER / "mj1_devices_scan_evidence.md"
    assert silva_md.exists()
    assert horner_md.exists()
    assert silva_md.read_text(encoding="utf-8") == horner_md.read_text(encoding="utf-8")

    silva_state_json = OPS_ARTIFACTS_SILVA / "mj1_devices_scan_list_state_evidence.json"
    horner_state_json = OPS_ARTIFACTS_HORNER / "mj1_devices_scan_list_state_evidence.json"
    assert silva_state_json.exists()
    assert horner_state_json.exists()
    assert silva_state_json.read_text(encoding="utf-8") == horner_state_json.read_text(encoding="utf-8")


# =============================================================================
# 7. Fail-Closed Hardware Lockout Invariants
# =============================================================================

def test_fail_closed_hardware_lockout_on_com_ports():
    """Verify physical COM ports COM1-COM256 trigger fail-closed lockout."""
    guard = SecurityGuard()
    for port in ("COM1", "COM2", "COM16", "COM256"):
        # 1. FastMCP inspection tool returns status: blocked
        res = cscape_inspect_scan_list(project_path=DEDICATED_PROJECT, port=port)
        assert res["status"] == "blocked"
        assert res["error_code"] in ("PHYSICAL_PORT_LOCKOUT", "SECURITY_BLOCKED")

        # 2. SecurityGuard directly raises HardwareLockoutError
        with pytest.raises(SecurityError):
            guard.validate_hardware_connection(port=port)


def test_no_live_claims_and_no_plc_download():
    """Assert zero live verification and zero PLC download invariants."""
    res_inspect = cscape_inspect_scan_list(project_path=DEDICATED_PROJECT, port="MJ1")
    assert res_inspect["verified_live"] is False
    assert res_inspect["plc_download"] is False

    res_reconcile = cscape_reconcile_scan_list(
        project_path=DEDICATED_PROJECT, inventory_path=DEDICATED_INVENTORY, port="MJ1"
    )
    assert res_reconcile["verified_live"] is False
    assert res_reconcile["plc_download"] is False
