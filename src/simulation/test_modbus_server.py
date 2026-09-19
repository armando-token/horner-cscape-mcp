"""Labeled TEST Modbus Server Endpoint for Protocol Verification (Phase P5).

Mandate: Plan v3 - Phase P5 Modbus PV Provider Protocol Verification
Governing Rule: RULE[C:\\Users\\ArmandoSilva\\AGENTS.md]
Operational Mode: offline/DEV [TESTED_MOCK] (Fail-Closed, Zero PLC Download)

Stands up an in-process, pure-Python standard-library TCP server:
- Server Label: [TEST_MODBUS_PV_PROVIDER]
- Default Port: 15502 (unprivileged test port; production default is 502)
- Serves 16-bit register telemetry (default 17600 -> 55.0 % scaled level)
- Supports FC03 (Read Holding Registers) and FC04 (Read Input Registers)
- Rejects write functions (FC06, FC16) with Exception Code 0x01 (ILLEGAL_FUNCTION)
- Provides query_pv_register() client method for end-to-end wire protocol checks
"""

from __future__ import annotations

import logging
import socket
import struct
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

SERVER_LABEL = "[TEST_MODBUS_PV_PROVIDER]"
DEFAULT_TEST_HOST = "127.0.0.1"
DEFAULT_TEST_PORT = 15502


@dataclass
class ModbusTestServerStatus:
    """Status record of running test server."""
    is_running: bool
    label: str
    host: str
    port: int
    active_connections: int
    queries_served: int
    current_raw_value: int
    scaled_level_pct: float
    read_only_enforced: bool


class LabeledTestModbusServer:
    """Pure-Python Modbus TCP test server for offline/DEV protocol verification."""

    def __init__(
        self,
        host: str = DEFAULT_TEST_HOST,
        port: int = DEFAULT_TEST_PORT,
        initial_raw_value: int = 17600,  # 17600 / 32000.0 * 100.0 = 55.0 %
        label: str = SERVER_LABEL,
        initial_registers: Optional[Dict[int, int]] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.raw_value = initial_raw_value
        self.label = label
        self.registers: Dict[int, int] = {
            0: initial_raw_value,  # Offset 0 (40001): TankLevelPV (17600 -> 55.0 %)
            1: 16000,              # Offset 1 (40002): InflowRatePV (16000 -> 250.0 L/min)
            2: 16000,              # Offset 2 (40003): DischargePressPV (16000 -> 5.0 bar)
            3: 1,                  # Offset 3 (40004): Heartbeat Watchdog
        }
        if initial_registers:
            self.registers.update(initial_registers)
        self.server_socket: Optional[socket.socket] = None
        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.queries_served = 0
        self.active_connections = 0

    def set_raw_value(self, raw_value: int) -> None:
        """Dynamically update register telemetry value."""
        with self._lock:
            self.raw_value = max(0, min(65535, raw_value))
            self.registers[0] = self.raw_value

    def set_register(self, offset: int, value: int) -> None:
        """Dynamically update register value at specific 0-based offset."""
        with self._lock:
            val = max(0, min(65535, value))
            self.registers[offset] = val
            if offset == 0:
                self.raw_value = val

    def get_register(self, offset: int) -> int:
        """Get current register value at 0-based offset."""
        with self._lock:
            return self.registers.get(offset, 0)

    def set_level_percent(self, pct: float) -> int:
        """Set telemetry from engineering percentage (0..100%)."""
        raw = int(round(pct * 32000.0 / 100.0))
        self.set_raw_value(raw)
        return raw

    def get_status(self) -> ModbusTestServerStatus:
        """Return current status record."""
        with self._lock:
            cur_raw = self.raw_value
            scaled = round(cur_raw * 100.0 / 32000.0, 2)
            return ModbusTestServerStatus(
                is_running=self.is_running,
                label=self.label,
                host=self.host,
                port=self.port,
                active_connections=self.active_connections,
                queries_served=self.queries_served,
                current_raw_value=cur_raw,
                scaled_level_pct=scaled,
                read_only_enforced=True,
            )

    def start(self) -> None:
        """Bind and start server listening in background daemon thread."""
        if self.is_running:
            return

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.server_socket.settimeout(0.5)

        self.is_running = True
        self._thread = threading.Thread(target=self._serve_loop, daemon=True, name="TestModbusServerThread")
        self._thread.start()
        logger.info(f"{self.label} started on {self.host}:{self.port} (Raw={self.raw_value})")

    def stop(self) -> None:
        """Stop server and release socket."""
        self.is_running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info(f"{self.label} stopped cleanly.")

    def _serve_loop(self) -> None:
        while self.is_running:
            try:
                client_sock, client_addr = self.server_socket.accept()
            except (socket.timeout, OSError):
                continue
            except Exception as e:
                if self.is_running:
                    logger.debug(f"Accept error: {e}")
                break

            conn_thread = threading.Thread(
                target=self._handle_client,
                args=(client_sock, client_addr),
                daemon=True,
            )
            conn_thread.start()

    def _handle_client(self, sock: socket.socket, addr: Tuple[str, int]) -> None:
        with self._lock:
            self.active_connections += 1
        sock.settimeout(2.0)

        try:
            while self.is_running:
                # Read 7-byte MBAP Header
                header_data = b""
                while len(header_data) < 7:
                    chunk = sock.recv(7 - len(header_data))
                    if not chunk:
                        return
                    header_data += chunk

                tx_id, proto_id, length, unit_id = struct.unpack(">HHHB", header_data)
                pdu_len = length - 1
                if pdu_len <= 0 or pdu_len > 256:
                    break

                # Read PDU
                pdu_data = b""
                while len(pdu_data) < pdu_len:
                    chunk = sock.recv(pdu_len - len(pdu_data))
                    if not chunk:
                        return
                    pdu_data += chunk

                fc = pdu_data[0]

                # Process Read Holding (0x03) or Read Input (0x04)
                if fc in (3, 4):
                    if len(pdu_data) >= 5:
                        start_addr, qty = struct.unpack(">HH", pdu_data[1:5])
                        with self._lock:
                            cur_val = self.raw_value
                            self.queries_served += 1

                        # Generate response frame
                        # Response PDU: FC, ByteCount (2*qty), RegisterValue(s)
                        resp_bytes_count = 2 * qty
                        resp_pdu = struct.pack(">BB", fc, resp_bytes_count)
                        # Register 0 is cur_val, other registers 0
                        for reg_idx in range(qty):
                            curr_off = start_addr + reg_idx
                            val_to_send = self.registers.get(curr_off, cur_val if curr_off == 0 else 0)
                            resp_pdu += struct.pack(">H", val_to_send)

                        resp_len = 1 + len(resp_pdu)  # Unit ID (1 byte) + PDU
                        resp_mbap = struct.pack(">HHHB", tx_id, proto_id, resp_len, unit_id)
                        sock.sendall(resp_mbap + resp_pdu)
                else:
                    # Reject Write or unsupported function code with Modbus Exception 0x01 (ILLEGAL FUNCTION)
                    err_fc = fc | 0x80
                    exception_code = 1  # ILLEGAL_FUNCTION
                    resp_pdu = struct.pack(">BB", err_fc, exception_code)
                    resp_len = 1 + len(resp_pdu)
                    resp_mbap = struct.pack(">HHHB", tx_id, proto_id, resp_len, unit_id)
                    sock.sendall(resp_mbap + resp_pdu)

        except Exception as e:
            logger.debug(f"Client {addr} disconnected: {e}")
        finally:
            try:
                sock.close()
            except Exception:
                pass
            with self._lock:
                self.active_connections = max(0, self.active_connections - 1)


def query_pv_register(
    host: str = DEFAULT_TEST_HOST,
    port: int = DEFAULT_TEST_PORT,
    unit_id: int = 1,
    function_code: int = 3,
    start_address: int = 0,
    quantity: int = 1,
    timeout_sec: float = 2.0,
) -> Dict[str, Any]:
    """Client utility to perform a native Modbus TCP request and validate response.

    Returns parsed register data, raw hex frames, and scaled engineering units.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout_sec)
    s.connect((host, port))

    try:
        tx_id = 0x1234
        proto_id = 0x0000
        length = 6  # Unit ID (1) + FC (1) + StartAddr (2) + Qty (2)
        req_mbap = struct.pack(">HHHB", tx_id, proto_id, length, unit_id)
        req_pdu = struct.pack(">BHH", function_code, start_address, quantity)
        req_frame = req_mbap + req_pdu

        start_time = time.time()
        s.sendall(req_frame)

        # Read MBAP
        resp_mbap = s.recv(7)
        if len(resp_mbap) < 7:
            raise ValueError(f"Incomplete MBAP header received: {len(resp_mbap)} bytes")

        r_tx, r_proto, r_len, r_unit = struct.unpack(">HHHB", resp_mbap)
        # Read PDU
        pdu_len = r_len - 1
        resp_pdu = s.recv(pdu_len)
        elapsed_ms = round((time.time() - start_time) * 1000, 2)

        resp_fc = resp_pdu[0]
        if resp_fc & 0x80:
            exc_code = resp_pdu[1] if len(resp_pdu) > 1 else 0
            return {
                "status": "failed",
                "error_code": f"MODBUS_EXCEPTION_0x{exc_code:02X}",
                "elapsed_ms": elapsed_ms,
                "raw_request_hex": req_frame.hex().upper(),
                "raw_response_hex": (resp_mbap + resp_pdu).hex().upper(),
            }

        byte_count = resp_pdu[1]
        registers = []
        for i in range(byte_count // 2):
            val = struct.unpack_from(">H", resp_pdu, 2 + i * 2)[0]
            registers.append(val)

        raw_val = registers[0] if registers else 0
        scaled_pct = round(raw_val * 100.0 / 32000.0, 2)

        return {
            "status": "success",
            "host": host,
            "port": port,
            "unit_id": r_unit,
            "function_code": resp_fc,
            "registers_count": len(registers),
            "raw_registers": registers,
            "raw_pv_value": raw_val,
            "raw_pv_hex": f"0x{raw_val:04X}",
            "scaled_tank_level_pct": scaled_pct,
            "engineering_unit": "%",
            "elapsed_ms": elapsed_ms,
            "raw_request_hex": req_frame.hex().upper(),
            "raw_response_hex": (resp_mbap + resp_pdu).hex().upper(),
        }
    finally:
        s.close()
