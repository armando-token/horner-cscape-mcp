#!/usr/bin/env python3
r"""Standalone Verification Script for LabeledTestModbusServer (CORE-08).

Mandate: CORE-08 Offline Modbus Protocol Quality & Fail-Closed Write Lockout
Governing Rules: RULE[C:\Users\ArmandoSilva\AGENTS.md]
Execution Mode: offline/DEV [TESTED_MOCK] (Fail-Closed, Zero PLC Download)

Verification Steps:
1. Instantiates LabeledTestModbusServer on 127.0.0.1:15502 with label [TEST_MODBUS_PV_PROVIDER].
2. Populates registers:
   - Offset 0 = 17600 (55.0% Level)
   - Offset 1 = 16000 (250.0 L/min Inflow Rate)
   - Offset 2 = 16000 (5.0 bar Discharge Pressure)
   - Offset 3 = 1 (Heartbeat Watchdog)
3. Connects and sends FC03 query for offset 0 (1 register), decodes response, verifies raw 17600 and scaled 55.0%.
4. Sends FC03 query for offsets 0..2 (3 registers), decodes [17600, 16000, 16000].
5. Dynamically updates register 0 to 75.0% (raw 24000) using server.set_level_percent(75.0).
   Queries again and verifies raw 24000 and scaled 75.0%.
6. Tests fail-closed write lockout: sends raw FC06 (Write Single Register) packet.
   Verifies response is Modbus Exception 0x01 (ILLEGAL_FUNCTION) with function code 0x86.
7. Tests fail-closed write lockout: sends raw FC16 (Write Multiple Registers) packet.
   Verifies response is Modbus Exception 0x01 (ILLEGAL_FUNCTION) with function code 0x90.
8. Saves execution evidence log to artifacts/logs/core08_labeled_test_server_verification.json.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
from pathlib import Path
import socket
import struct
import sys
import time
from typing import Any, Dict, List

# Configure dual-root python paths
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()

for root in [USER_ROOT, HORNER_ROOT]:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from src.simulation.test_modbus_server import (
    LabeledTestModbusServer,
    SERVER_LABEL,
    query_pv_register,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("verify_core08_modbus")

TEST_HOST = "127.0.0.1"
TEST_PORT = 15502
EXPECTED_LABEL = "[TEST_MODBUS_PV_PROVIDER]"

LOG_RELATIVE_PATH = Path("artifacts") / "logs" / "core08_labeled_test_server_verification.json"


def send_raw_modbus_tcp(
    host: str,
    port: int,
    tx_id: int,
    unit_id: int,
    pdu: bytes,
    timeout_sec: float = 2.0,
) -> tuple[bytes, bytes]:
    """Sends raw PDU over Modbus TCP and returns (resp_mbap, resp_pdu)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout_sec)
    s.connect((host, port))
    try:
        length = 1 + len(pdu)  # unit_id (1) + pdu length
        proto_id = 0
        mbap = struct.pack(">HHHB", tx_id, proto_id, length, unit_id)
        s.sendall(mbap + pdu)

        # Receive 7-byte MBAP
        resp_mbap = b""
        while len(resp_mbap) < 7:
            chunk = s.recv(7 - len(resp_mbap))
            if not chunk:
                raise ConnectionError("Server closed connection during MBAP read")
            resp_mbap += chunk

        r_tx, r_proto, r_len, r_unit = struct.unpack(">HHHB", resp_mbap)
        pdu_len = r_len - 1

        # Receive PDU
        resp_pdu = b""
        while len(resp_pdu) < pdu_len:
            chunk = s.recv(pdu_len - len(resp_pdu))
            if not chunk:
                raise ConnectionError("Server closed connection during PDU read")
            resp_pdu += chunk

        return resp_mbap, resp_pdu
    finally:
        s.close()


def run_verification() -> Dict[str, Any]:
    """Executes all CORE-08 verification steps and returns execution evidence."""
    logger.info("=================================================================")
    logger.info("CORE-08 LabeledTestModbusServer Protocol & Safety Verification")
    logger.info("Target: %s:%d | Expected Label: %s", TEST_HOST, TEST_PORT, EXPECTED_LABEL)
    logger.info("=================================================================")

    start_time_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    steps_evidence: List[Dict[str, Any]] = []

    # Step 1: Instantiate LabeledTestModbusServer
    logger.info("Step 1: Instantiating LabeledTestModbusServer on %s:%d...", TEST_HOST, TEST_PORT)
    initial_regs = {
        0: 17600,  # 55.0 % Level
        1: 16000,  # 250.0 L/min
        2: 16000,  # 5.0 bar
        3: 1,      # Watchdog
    }
    server = LabeledTestModbusServer(
        host=TEST_HOST,
        port=TEST_PORT,
        initial_raw_value=17600,
        label=EXPECTED_LABEL,
        initial_registers=initial_regs,
    )

    try:
        server.start()
        time.sleep(0.2)  # Allow socket listener to initialize

        assert server.is_running, "Server failed to start"
        assert server.label == EXPECTED_LABEL, f"Label mismatch: {server.label}"
        assert server.host == TEST_HOST, f"Host mismatch: {server.host}"
        assert server.port == TEST_PORT, f"Port mismatch: {server.port}"
        logger.info("  [PASS] Server initialized and listening on %s:%d with label '%s'", TEST_HOST, TEST_PORT, EXPECTED_LABEL)
        steps_evidence.append({
            "step": 1,
            "name": "server_initialization",
            "status": "success",
            "host": TEST_HOST,
            "port": TEST_PORT,
            "label": EXPECTED_LABEL,
            "initial_registers": initial_regs,
        })

        # Step 2: FC03 Query for Offset 0 (1 register)
        logger.info("Step 2: Sending FC03 Read Holding Register (Offset 0, Qty 1)...")
        # Direct raw socket check
        pdu_req2 = struct.pack(">BHH", 3, 0, 1)
        resp_mbap2, resp_pdu2 = send_raw_modbus_tcp(TEST_HOST, TEST_PORT, tx_id=1, unit_id=1, pdu=pdu_req2)
        resp_fc2, byte_count2, reg0_val2 = struct.unpack(">BBH", resp_pdu2)
        scaled_pct2 = round(reg0_val2 * 100.0 / 32000.0, 2)

        assert resp_fc2 == 3, f"Unexpected FC in response: {resp_fc2}"
        assert byte_count2 == 2, f"Unexpected byte count: {byte_count2}"
        assert reg0_val2 == 17600, f"Unexpected raw register value: {reg0_val2} (expected 17600)"
        assert scaled_pct2 == 55.0, f"Unexpected scaled percentage: {scaled_pct2} (expected 55.0%)"

        # Also verify via query_pv_register utility
        client_res2 = query_pv_register(host=TEST_HOST, port=TEST_PORT, start_address=0, quantity=1)
        assert client_res2["status"] == "success", f"Client query failed: {client_res2}"
        assert client_res2["raw_pv_value"] == 17600
        assert client_res2["scaled_tank_level_pct"] == 55.0

        logger.info("  [PASS] Offset 0 verified: Raw = %d (0x%04X), Scaled = %.1f%%", reg0_val2, reg0_val2, scaled_pct2)
        steps_evidence.append({
            "step": 2,
            "name": "fc03_query_offset_0",
            "status": "success",
            "start_address": 0,
            "quantity": 1,
            "raw_value": reg0_val2,
            "scaled_tank_level_pct": scaled_pct2,
            "raw_request_hex": (struct.pack(">HHHB", 1, 0, 6, 1) + pdu_req2).hex().upper(),
            "raw_response_hex": (resp_mbap2 + resp_pdu2).hex().upper(),
        })

        # Step 3: FC03 Query for Offsets 0..2 (3 registers)
        logger.info("Step 3: Sending FC03 Read Holding Registers (Offsets 0..2, Qty 3)...")
        pdu_req3 = struct.pack(">BHH", 3, 0, 3)
        resp_mbap3, resp_pdu3 = send_raw_modbus_tcp(TEST_HOST, TEST_PORT, tx_id=2, unit_id=1, pdu=pdu_req3)
        resp_fc3, byte_count3 = struct.unpack_from(">BB", resp_pdu3, 0)
        regs3 = [
            struct.unpack_from(">H", resp_pdu3, 2 + i * 2)[0]
            for i in range(byte_count3 // 2)
        ]

        assert resp_fc3 == 3, f"Unexpected FC in response: {resp_fc3}"
        assert byte_count3 == 6, f"Unexpected byte count: {byte_count3}"
        assert regs3 == [17600, 16000, 16000], f"Unexpected registers decoded: {regs3}"

        client_res3 = query_pv_register(host=TEST_HOST, port=TEST_PORT, start_address=0, quantity=3)
        assert client_res3["status"] == "success"
        assert client_res3["raw_registers"] == [17600, 16000, 16000]

        logger.info("  [PASS] Offsets 0..2 verified: Registers = %s", regs3)
        steps_evidence.append({
            "step": 3,
            "name": "fc03_query_offsets_0_to_2",
            "status": "success",
            "start_address": 0,
            "quantity": 3,
            "raw_registers": regs3,
            "expected_registers": [17600, 16000, 16000],
            "raw_request_hex": (struct.pack(">HHHB", 2, 0, 6, 1) + pdu_req3).hex().upper(),
            "raw_response_hex": (resp_mbap3 + resp_pdu3).hex().upper(),
        })

        # Step 4: Dynamic Update to 75.0% (raw 24000)
        logger.info("Step 4: Dynamically updating register 0 to 75.0%% (raw 24000)...")
        updated_raw = server.set_level_percent(75.0)
        assert updated_raw == 24000, f"set_level_percent returned unexpected raw value: {updated_raw}"
        assert server.get_register(0) == 24000, f"server.get_register(0) returned: {server.get_register(0)}"

        # Query again and verify update
        pdu_req4 = struct.pack(">BHH", 3, 0, 1)
        resp_mbap4, resp_pdu4 = send_raw_modbus_tcp(TEST_HOST, TEST_PORT, tx_id=3, unit_id=1, pdu=pdu_req4)
        resp_fc4, byte_count4, reg0_val4 = struct.unpack(">BBH", resp_pdu4)
        scaled_pct4 = round(reg0_val4 * 100.0 / 32000.0, 2)

        assert resp_fc4 == 3
        assert byte_count4 == 2
        assert reg0_val4 == 24000, f"Expected 24000, got {reg0_val4}"
        assert scaled_pct4 == 75.0, f"Expected 75.0%, got {scaled_pct4}%"

        client_res4 = query_pv_register(host=TEST_HOST, port=TEST_PORT, start_address=0, quantity=1)
        assert client_res4["status"] == "success"
        assert client_res4["raw_pv_value"] == 24000
        assert client_res4["scaled_tank_level_pct"] == 75.0

        logger.info("  [PASS] Dynamic update verified: Raw = %d (0x%04X), Scaled = %.1f%%", reg0_val4, reg0_val4, scaled_pct4)
        steps_evidence.append({
            "step": 4,
            "name": "dynamic_update_register_0",
            "status": "success",
            "set_percentage": 75.0,
            "expected_raw": 24000,
            "actual_raw": reg0_val4,
            "actual_scaled_pct": scaled_pct4,
            "raw_request_hex": (struct.pack(">HHHB", 3, 0, 6, 1) + pdu_req4).hex().upper(),
            "raw_response_hex": (resp_mbap4 + resp_pdu4).hex().upper(),
        })

        # Step 5: Fail-closed write lockout: raw FC06 (Write Single Register)
        logger.info("Step 5: Testing fail-closed write lockout with raw FC06 (Write Single Register)...")
        pdu_fc06 = struct.pack(">BHH", 6, 0, 0x1234)  # FC 0x06, Addr 0x0000, Value 0x1234
        resp_mbap5, resp_pdu5 = send_raw_modbus_tcp(TEST_HOST, TEST_PORT, tx_id=4, unit_id=1, pdu=pdu_fc06)

        assert len(resp_pdu5) == 2, f"Expected 2-byte exception PDU, got {len(resp_pdu5)} bytes"
        resp_fc5 = resp_pdu5[0]
        exc_code5 = resp_pdu5[1]

        assert resp_fc5 == 0x86, f"Expected exception FC 0x86 (0x06 | 0x80), got 0x{resp_fc5:02X}"
        assert exc_code5 == 0x01, f"Expected Exception Code 0x01 (ILLEGAL_FUNCTION), got 0x{exc_code5:02X}"

        logger.info("  [PASS] FC06 rejected fail-closed: Response FC = 0x%02X, Exception Code = 0x%02X (ILLEGAL_FUNCTION)", resp_fc5, exc_code5)
        steps_evidence.append({
            "step": 5,
            "name": "fail_closed_write_lockout_fc06",
            "status": "success",
            "attempted_fc": 6,
            "response_fc": f"0x{resp_fc5:02X}",
            "exception_code": f"0x{exc_code5:02X}",
            "exception_name": "ILLEGAL_FUNCTION",
            "lockout_verified": True,
            "raw_request_hex": (struct.pack(">HHHB", 4, 0, 6, 1) + pdu_fc06).hex().upper(),
            "raw_response_hex": (resp_mbap5 + resp_pdu5).hex().upper(),
        })

        # Step 6: Fail-closed write lockout: raw FC16 (Write Multiple Registers)
        logger.info("Step 6: Testing fail-closed write lockout with raw FC16 (Write Multiple Registers)...")
        # FC 0x10 (16), StartAddr 0x0000, Qty 2, ByteCount 4, Val1 0x1234, Val2 0x5678
        pdu_fc16 = struct.pack(">BHHBHH", 16, 0, 2, 4, 0x1234, 0x5678)
        resp_mbap6, resp_pdu6 = send_raw_modbus_tcp(TEST_HOST, TEST_PORT, tx_id=5, unit_id=1, pdu=pdu_fc16)

        assert len(resp_pdu6) == 2, f"Expected 2-byte exception PDU, got {len(resp_pdu6)} bytes"
        resp_fc6 = resp_pdu6[0]
        exc_code6 = resp_pdu6[1]

        assert resp_fc6 == 0x90, f"Expected exception FC 0x90 (0x10 | 0x80), got 0x{resp_fc6:02X}"
        assert exc_code6 == 0x01, f"Expected Exception Code 0x01 (ILLEGAL_FUNCTION), got 0x{exc_code6:02X}"

        logger.info("  [PASS] FC16 rejected fail-closed: Response FC = 0x%02X, Exception Code = 0x%02X (ILLEGAL_FUNCTION)", resp_fc6, exc_code6)
        steps_evidence.append({
            "step": 6,
            "name": "fail_closed_write_lockout_fc16",
            "status": "success",
            "attempted_fc": 16,
            "response_fc": f"0x{resp_fc6:02X}",
            "exception_code": f"0x{exc_code6:02X}",
            "exception_name": "ILLEGAL_FUNCTION",
            "lockout_verified": True,
            "raw_request_hex": (struct.pack(">HHHB", 5, 0, 1 + len(pdu_fc16), 1) + pdu_fc16).hex().upper(),
            "raw_response_hex": (resp_mbap6 + resp_pdu6).hex().upper(),
        })

        # Step 7: Server Status Inspection
        logger.info("Step 7: Inspecting server status metrics...")
        stat = server.get_status()
        assert stat.label == EXPECTED_LABEL
        assert stat.host == TEST_HOST
        assert stat.port == TEST_PORT
        assert stat.read_only_enforced is True
        assert stat.queries_served >= 3
        assert stat.current_raw_value == 24000
        assert stat.scaled_level_pct == 75.0

        status_dict = {
            "is_running": stat.is_running,
            "label": stat.label,
            "host": stat.host,
            "port": stat.port,
            "active_connections": stat.active_connections,
            "queries_served": stat.queries_served,
            "current_raw_value": stat.current_raw_value,
            "scaled_level_pct": stat.scaled_level_pct,
            "read_only_enforced": stat.read_only_enforced,
        }
        logger.info("  [PASS] Status verified: %s", status_dict)
        steps_evidence.append({
            "step": 7,
            "name": "server_status_inspection",
            "status": "success",
            "server_status": status_dict,
        })

    finally:
        # Step 8: Clean Server Shutdown
        logger.info("Step 8: Stopping LabeledTestModbusServer...")
        server.stop()
        logger.info("  [PASS] Server stopped cleanly.")

    end_time_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    evidence: Dict[str, Any] = {
        "status": "success",
        "error_code": None,
        "details": (
            f"Verification of LabeledTestModbusServer '{EXPECTED_LABEL}' completed successfully on "
            f"{TEST_HOST}:{TEST_PORT}. All 7 protocol and safety checks passed deterministically."
        ),
        "data": {
            "mandate": "CORE-08 Offline Modbus Protocol Quality & Fail-Closed Write Lockout",
            "server_label": EXPECTED_LABEL,
            "host": TEST_HOST,
            "port": TEST_PORT,
            "start_time_utc": start_time_iso,
            "end_time_utc": end_time_iso,
            "total_steps": len(steps_evidence),
            "steps": steps_evidence,
            "protocol_conformance": {
                "fc03_read_single_register": "VERIFIED_PASS",
                "fc03_read_multi_register": "VERIFIED_PASS",
                "dynamic_telemetry_update": "VERIFIED_PASS",
                "fc06_write_single_lockout": "VERIFIED_FAIL_CLOSED (0x86 / 0x01)",
                "fc16_write_multi_lockout": "VERIFIED_FAIL_CLOSED (0x90 / 0x01)",
                "read_only_enforced": True,
            },
            "status_contract_version": "v1.0.0",
        },
    }

    return evidence


def save_evidence_log(evidence: Dict[str, Any]) -> List[Path]:
    """Saves the evidence log to artifacts/logs/ in both workspace roots."""
    saved_paths: List[Path] = []
    serialized = json.dumps(evidence, indent=2)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    evidence["data"]["sha256"] = digest
    serialized_with_hash = json.dumps(evidence, indent=2)

    target_roots = [USER_ROOT, HORNER_ROOT]
    for root in target_roots:
        if root.exists():
            log_file = root / LOG_RELATIVE_PATH
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_file.write_text(serialized_with_hash, encoding="utf-8")
            saved_paths.append(log_file)
            logger.info("Saved evidence log: %s (SHA256: %s)", log_file, digest[:12])

    return saved_paths


def main() -> int:
    try:
        evidence = run_verification()
        saved_paths = save_evidence_log(evidence)
        logger.info("=================================================================")
        logger.info("CORE-08 LabeledTestModbusServer Verification: ALL CHECKS PASSED")
        logger.info("Evidence log files saved to:")
        for p in saved_paths:
            logger.info("  - %s", p)
        logger.info("=================================================================")
        return 0
    except Exception as exc:
        logger.exception("CORE-08 Verification FAILED with exception: %s", exc)
        failure_evidence: Dict[str, Any] = {
            "status": "failed",
            "error_code": "VERIFICATION_ERROR",
            "details": str(exc),
            "data": {
                "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
        }
        try:
            save_evidence_log(failure_evidence)
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
