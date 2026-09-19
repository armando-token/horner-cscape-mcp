"""Verification Suite for Plan v3 Phase P5: Native Cscape Modbus PV Provider Configuration.

Mandate: Plan v3 - Phase P5 Native Modbus PV Provider Config & Durability
Governing Rule: RULE[C:\\Users\\ArmandoSilva\\AGENTS.md]
Operational Mode: offline/DEV [FAIL_CLOSED_NATIVE_EVIDENCE] (Zero PLC Download, Read-Only PV Provider)

Verifies:
1. Modbus PV Provider Configuration schema & inventory completeness (TCP/RTU, role, endpoint, unit ID, function, addresses, type, endianness, scale, poll, timeout, stale).
2. Read-only safety policy enforcement (rejection of write commands).
3. Labeled TEST Modbus server protocol checks (MBAP framing, FC03/FC04 query, register decoding, scaling).
4. Container persistence & sidecar synchronization.
5. Re-read durability verification after simulated or native save/close/reopen.
6. Formal mathematical and byte-level conversion documentation.
7. Status contract adherence (success | failed | blocked | inconclusive).
8. Physical runtime verification deferred to Phase P7 declaration.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
import pytest

from src.cscape.modbus_config import (
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
    QualityState,
)
from src.simulation.test_modbus_server import (
    LabeledTestModbusServer,
    query_pv_register,
    SERVER_LABEL,
)
from src.iec.validator import IECValidator


def test_modbus_config_full_inventory() -> None:
    """Verify that ModbusPVProviderConfig satisfies the full inventory requirements."""
    cfg = ModbusPVProviderConfig(
        config_id="Test_Inventory_Config",
        transport=ModbusTransport.TCP,
        role=ModbusRole.CLIENT_MASTER_READ_ONLY,
        unit_id=1,
        function_code=ModbusFunctionCode.READ_HOLDING_REGISTERS,
    )
    d = cfg.to_dict()

    # Required inventory fields:
    # TCP/RTU
    assert d["transport"] == "MODBUS_TCP"
    assert "tcp_endpoint" in d
    assert "rtu_endpoint" in d
    # role
    assert d["role"] == "CLIENT_MASTER_READ_ONLY"
    # endpoint
    assert d["tcp_endpoint"]["ip_address"] == "127.0.0.1"
    assert d["tcp_endpoint"]["port"] == 15502
    assert d["rtu_endpoint"]["serial_port"] in ("MJ1_RS485", "MJ2_RS485")
    assert d["rtu_endpoint"]["baud_rate"] == 19200
    # unit ID
    assert d["unit_id"] == 1
    # function
    assert d["function_code"] == 3
    assert "0x03" in d["function_name"]
    # addresses both conventions
    assert d["address_mapping"]["modicon_1based"] == 40001
    assert d["address_mapping"]["wire_offset_0based"] == 0
    assert d["address_mapping"]["horner_ocs_register"] == "%AI1"
    assert d["address_mapping"]["variable_name"] == "TankLevelPV"
    # type
    assert d["raw_data_type"] == "UINT16"
    # byte/word order
    assert d["endianness"] == "BIG_ENDIAN_AB"
    # scale
    assert d["scaling"]["raw_min"] == 0.0
    assert d["scaling"]["raw_max"] == 32000.0
    assert d["scaling"]["eu_min"] == 0.0
    assert d["scaling"]["eu_max"] == 100.0
    assert d["scaling"]["engineering_unit"] == "%"
    # poll
    assert d["policy"]["poll_interval_ms"] == 100
    # timeout
    assert d["policy"]["response_timeout_ms"] == 1000
    assert d["policy"]["retry_count"] == 3
    # stale
    assert d["policy"]["stale_timeout_ms"] == 2000
    assert d["policy"]["comm_failure_alarm_reg"] == "%M10"
    assert d["policy"]["stale_quality_bit_reg"] == "%M11"

    # read-only preference and safety declaration
    assert d["read_only_enforced"] is True
    assert "PENDING_P7" in d["physical_runtime_verification"]


def test_scaling_calculations() -> None:
    """Verify engineering unit conversion formula and inverse calculation."""
    scaling = ScalingConfiguration(raw_min=0.0, raw_max=32000.0, eu_min=0.0, eu_max=100.0)

    # 55.0% level -> 17600 counts
    raw = scaling.compute_raw_from_eu(55.0)
    assert raw == 17600

    eu, quality = scaling.compute_scaled_pv(17600)
    assert eu == 55.0
    assert quality == QualityState.GOOD

    # 35.0% level -> 11200 counts
    raw_35 = scaling.compute_raw_from_eu(35.0)
    assert raw_35 == 11200
    eu_35, _ = scaling.compute_scaled_pv(11200)
    assert eu_35 == 35.0

    # 75.0% level -> 24000 counts
    raw_75 = scaling.compute_raw_from_eu(75.0)
    assert raw_75 == 24000
    eu_75, _ = scaling.compute_scaled_pv(24000)
    assert eu_75 == 75.0


def test_labeled_test_modbus_server_protocol_check() -> None:
    """Verify the labeled TEST Modbus server handles FC03 queries and rejects writes."""
    test_port = 15509
    server = LabeledTestModbusServer(port=test_port, initial_raw_value=17600)
    server.start()

    try:
        status = server.get_status()
        assert status.is_running is True
        assert status.label == SERVER_LABEL
        assert status.current_raw_value == 17600
        assert status.scaled_level_pct == 55.0

        # Query FC03
        res = query_pv_register(port=test_port, function_code=3, start_address=0, quantity=1)
        assert res["status"] == "success"
        assert res["raw_pv_value"] == 17600
        assert res["raw_pv_hex"] == "0x44C0"
        assert res["scaled_tank_level_pct"] == 55.0

        # Dynamic update to 75.0% -> 24000
        server.set_level_percent(75.0)
        res_75 = query_pv_register(port=test_port, function_code=3, start_address=0, quantity=1)
        assert res_75["raw_pv_value"] == 24000
        assert res_75["scaled_tank_level_pct"] == 75.0

        # Test write rejection (FC06: Write Single Register) -> expect Modbus exception
        res_write = query_pv_register(port=test_port, function_code=6, start_address=0, quantity=1)
        assert res_write["status"] == "failed"
        assert "MODBUS_EXCEPTION" in res_write["error_code"]

    finally:
        server.stop()


def test_config_persistence_and_reread(tmp_path: Path) -> None:
    """Verify sidecar persistence, SHA-256 integrity, and durability re-reading."""
    cfg = ModbusPVProviderConfig(
        config_id="Durability_Test_Config",
        unit_id=1,
    )
    sidecar_path, sha = ModbusConfigPersistenceManager.persist_config(tmp_path, cfg)
    assert sidecar_path.exists()
    assert len(sha) == 64

    # Re-read
    reread_cfg = ModbusConfigPersistenceManager.read_config(tmp_path)
    assert reread_cfg is not None
    assert reread_cfg.config_id == "Durability_Test_Config"
    assert reread_cfg.compute_config_hash() == sha


def test_conversion_walkthrough_document() -> None:
    """Verify complete 5-step conversion walkthrough generation."""
    doc = generate_modbus_conversion_walkthrough(level_pct=55.0)
    assert "step1_mathematical_conversion" in doc
    assert "step2_protocol_request_frame" in doc
    assert "step3_protocol_response_frame" in doc
    assert "step4_horner_memory_and_st_scaling" in doc
    assert "step5_stale_and_timeout_behavior" in doc

    assert doc["step1_mathematical_conversion"]["raw_integer_value"] == 17600
    assert "00 01 00 00 00 06 01 03 00 00 00 01" in doc["step2_protocol_request_frame"]["complete_frame_hex"]
    assert "44 C0" in doc["step3_protocol_response_frame"]["complete_frame_hex"]
    assert "PENDING_P7" in doc["safety_declaration"]


def test_st_code_iec_syntax_valid() -> None:
    """Verify that the generated Modbus POU passes IEC 61131-3 pure ST validation."""
    from src.mcp.tools import cscape_modbus_persist_config
    temp_proj = "Test_Modbus_ST_Proj"
    proj_dir = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\projects") / temp_proj

    try:
        persist_res = cscape_modbus_persist_config(project_name=temp_proj)
        assert persist_res["status"] == "success"

        pou_path = Path(persist_res["pou_file"])
        assert pou_path.exists()
        st_content = pou_path.read_text(encoding="utf-8")

        validator = IECValidator()
        v_res = validator.validate(st_content)
        assert v_res.get("valid") is True
        assert len(v_res.get("errors", [])) == 0
    finally:
        if proj_dir.exists():
            shutil.rmtree(proj_dir, ignore_errors=True)
