"""Test Suite for Priority 3 (CORE-08 Offline): Deep Native Modbus Inventory & Protocol Quality.

Mandate: Plan v3 CORE-08 Offline Deepening
- Deep native Modbus inventory (devices, scan list, channels, register bindings).
- Labeled TEST Modbus server protocol checks (FC03/FC04, multi-register, write lockout FC06/16).
- Quality gates: fail-closed safety, stale quality handling, PENDING_P7 declaration.
"""

from __future__ import annotations

import json
import socket
import struct
import tempfile
import time
from pathlib import Path
import pytest

from src.cscape.modbus_config import (
    ModbusTransport,
    ModbusRole,
    ModbusFunctionCode,
    ModbusTCPEndpoint,
    ModbusRTUEndpoint,
    ModbusDevice,
    ModbusScanTransaction,
    ModbusChannelConfig,
    ModbusDeepProtocolInventory,
    ModbusConfigPersistenceManager,
    ModbusPVProviderConfig,
)
from src.simulation.test_modbus_server import (
    LabeledTestModbusServer,
    query_pv_register,
    SERVER_LABEL,
)
from src.security.guard import SecurityGuard, SecurityError


def test_core08_deep_inventory_structure():
    """Verify deep Modbus inventory contains complete devices, scan list, and channels."""
    inv = ModbusConfigPersistenceManager.build_default_deep_inventory("TankLevel_P5_Dedicated")
    d = inv.to_dict()

    assert d["project_name"] == "TankLevel_P5_Dedicated"
    assert d["devices_count"] == 3
    assert d["scan_list_count"] == 3
    assert d["channels_count"] == 3
    assert d["read_only_enforced"] is True

    # Channels
    ch_ids = [c["channel_id"] for c in d["channels"]]
    assert "CH_LAN1_TCP" in ch_ids
    assert "CH_MJ1_RTU" in ch_ids
    assert "CH_MJ2_RTU" in ch_ids

    # CH_MJ1_RTU channel and endpoint properties
    ch_mj1 = next(c for c in d["channels"] if c["channel_id"] == "CH_MJ1_RTU")
    assert ch_mj1["transport"] == "MODBUS_RTU"
    assert ch_mj1["rtu_endpoint"]["serial_port"] == "MJ1_RS485"
    assert ch_mj1["rtu_endpoint"]["baud_rate"] == 19200
    assert ch_mj1["rtu_endpoint"]["data_bits"] == 8
    assert ch_mj1["rtu_endpoint"]["parity"] == "NONE"
    assert ch_mj1["rtu_endpoint"]["stop_bits"] == 1
    assert ch_mj1["rtu_endpoint"]["mode"] == "RS-485"
    assert ch_mj1["rtu_endpoint"]["driver_label"] == "CT RTU Modbus CMP v 5.05 / Modbus Master v 5.07"

    # Devices
    dev_ids = [dev["device_id"] for dev in d["devices"]]
    assert "DEV_LT01" in dev_ids
    assert "DEV_FT01" in dev_ids
    assert "DEV_PT01" in dev_ids

    # Scan List
    tx_ids = [tx["transaction_id"] for tx in d["scan_list"]]
    assert "TX01_LEVEL_PV" in tx_ids
    assert "TX02_INFLOW_RATE" in tx_ids
    assert "TX03_DISCHARGE_PRESS" in tx_ids

    # Scan list register mappings
    tx1 = next(t for t in d["scan_list"] if t["transaction_id"] == "TX01_LEVEL_PV")
    assert tx1["unit_id"] == 1
    assert tx1["modicon_address"] == 40001
    assert tx1["wire_offset"] == 0
    assert tx1["target_ocs_register"] == "%AI1"
    assert tx1["variable_name"] == "TankLevelPV"
    assert tx1["comm_alarm_register"] == "%M10"
    assert tx1["stale_quality_register"] == "%M11"

    tx2 = next(t for t in d["scan_list"] if t["transaction_id"] == "TX02_INFLOW_RATE")
    assert tx2["unit_id"] == 2
    assert tx2["modicon_address"] == 40002
    assert tx2["wire_offset"] == 1
    assert tx2["target_ocs_register"] == "%AI2"
    assert tx2["variable_name"] == "InflowRatePV"

    tx3 = next(t for t in d["scan_list"] if t["transaction_id"] == "TX03_DISCHARGE_PRESS")
    assert tx3["unit_id"] == 3
    assert tx3["modicon_address"] == 40003
    assert tx3["wire_offset"] == 2
    assert tx3["target_ocs_register"] == "%AI3"
    assert tx3["variable_name"] == "DischargePressPV"


def test_core08_deep_inventory_persistence_and_reread():
    """Verify deep inventory serialization and re-read from disk."""
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        inv = ModbusConfigPersistenceManager.build_default_deep_inventory("TestProject")
        inv_path, inv_hash = ModbusConfigPersistenceManager.persist_deep_inventory(td, inv)

        assert inv_path.exists()
        assert len(inv_hash) == 64

        reread = ModbusConfigPersistenceManager.read_deep_inventory(td)
        assert reread is not None
        assert reread["project_name"] == "TestProject"
        assert len(reread["channels"]) == 3
        assert reread["channels_count"] == 3
        assert len(reread["devices"]) == 3
        assert len(reread["scan_list"]) == 3
        assert reread["sha256"] == inv_hash


def test_core08_labeled_test_server_multi_register_protocol():
    """Verify labeled test server handles multi-register queries and dynamic updates."""
    port = 15598
    server = LabeledTestModbusServer(
        port=port,
        initial_raw_value=17600,
        initial_registers={
            0: 17600,  # 55.0 % Level
            1: 16000,  # 250.0 L/min Flow
            2: 16000,  # 5.0 bar Pressure
            3: 1,      # Watchdog
        }
    )
    server.start()
    time.sleep(0.15)

    try:
        # Query 1: Read Level PV (Offset 0, 1 register)
        res_level = query_pv_register(port=port, start_address=0, quantity=1)
        assert res_level["status"] == "success"
        assert res_level["raw_pv_value"] == 17600
        assert res_level["scaled_tank_level_pct"] == 55.0

        # Query 2: Read 3 consecutive registers (Offsets 0, 1, 2)
        res_multi = query_pv_register(port=port, start_address=0, quantity=3)
        assert res_multi["status"] == "success"
        assert res_multi["registers_count"] == 3
        assert res_multi["raw_registers"] == [17600, 16000, 16000]

        # Dynamic update of register 0 to 75.0 % (24000 counts)
        server.set_level_percent(75.0)
        res_updated = query_pv_register(port=port, start_address=0, quantity=1)
        assert res_updated["status"] == "success"
        assert res_updated["raw_pv_value"] == 24000
        assert res_updated["scaled_tank_level_pct"] == 75.0

        # Check server status
        stat = server.get_status()
        assert stat.label == SERVER_LABEL
        assert stat.read_only_enforced is True
        assert stat.queries_served >= 3
    finally:
        server.stop()


def test_core08_write_lockout_fail_closed():
    """Verify fail-closed rejection of write commands with Modbus Exception 0x01."""
    port = 15599
    server = LabeledTestModbusServer(port=port)
    server.start()
    time.sleep(0.15)

    try:
        # Send illegal Write Single Register (FC06) frame:
        # MBAP: TxID=1, Proto=0, Len=6, UnitID=1
        # PDU: FC=0x06, RegAddr=0x0000, RegVal=0x1234
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect(("127.0.0.1", port))

        req_mbap = struct.pack(">HHHB", 1, 0, 6, 1)
        req_pdu = struct.pack(">BHH", 6, 0, 0x1234)
        s.sendall(req_mbap + req_pdu)

        resp_mbap = s.recv(7)
        resp_pdu = s.recv(2)
        s.close()

        # Check response: FC should be 0x86 (0x06 | 0x80) and exception code 0x01
        assert resp_pdu[0] == 0x86
        assert resp_pdu[1] == 0x01  # ILLEGAL_FUNCTION
    finally:
        server.stop()


def test_core08_quality_and_fail_closed_declarations():
    """Verify quality states, hardware port bans, and explicit PENDING_P7 declarations."""
    inv = ModbusConfigPersistenceManager.build_default_deep_inventory("TankLevel_P5_Dedicated")
    d = inv.to_dict()

    assert "PENDING_P7" in d["safety_lockout"]["physical_runtime_verification"]
    assert "COM1-COM256" in d["safety_lockout"]["physical_ports"]
    assert "32827" in d["safety_lockout"]["download_commands"]

    # SecurityGuard hardware port lockout
    guard = SecurityGuard()
    with pytest.raises(SecurityError):
        guard.validate_command("cscape COM1")

    # Command and port policies
    assert guard.policy.is_port_blocked("COM1") is True
    assert guard.policy.is_ui_command_blocked(32827) is True
    assert guard.policy.is_ui_command_blocked(33149) is True
