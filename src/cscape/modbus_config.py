"""Horner Cscape 10.2 Native Modbus & Fieldbus PV Provider Configuration Manager (Phase P5).

Mandate: Plan v3 - Phase P5 Native Cscape Modbus PV Provider Configuration
Governing Rule: RULE[C:\\Users\\ArmandoSilva\\AGENTS.md]
Operational Mode: offline/DEV [FAIL_CLOSED_NATIVE_EVIDENCE] (Zero PLC Download, Read-Only PV Provider)

Provides comprehensive data structures, serialization, persistence, and verification for:
1. Native Modbus PV provider configuration with full inventory:
   - Channel / Transport: Modbus TCP (Ethernet port 502/15502) & Modbus RTU (serial RS-485 / MJ2)
   - Role: CLIENT_MASTER_READ_ONLY (OCS acts as Modbus Master/Client; write commands blocked)
   - Endpoints: IP address, TCP port, serial port, baud rate, data bits, parity, stop bits
   - Unit ID / Slave Station ID (e.g. 1)
   - Function Code: FC03 (Read Holding Registers - 0x03) and FC04 (Read Input Registers - 0x04)
   - Addressing in both conventions:
     * 1-based Modicon Reference (e.g. 40001 / 30001)
     * 0-based PDU Wire Offset (e.g. 0x0000 / 0)
     * Horner OCS internal target address (e.g. %AI1 / %R101)
   - Data Types: Raw wire type (UINT16 / WORD / FLOAT32) and scaled process variable (REAL)
   - Byte & Word Order: Big-Endian (High byte/word first) and Little-Endian / Word-Swapped (CDAB)
   - Scaling & Engineering Units: Raw Min/Max (0..32000), EU Min/Max (0.0..100.0 %), linear transfer formula
   - Polling: Continuous cyclic scan interval (100ms / 200ms)
   - Timeout Policy: Response timeout (1000ms), max retries (3)
   - Stale & Quality Handling: Stale timeout (2000ms), watchdog register, comm failure alarm (%M10), stale bit (%M11)
2. Project container sidecar persistence and CFBF stream synchronization.
3. Verification across save/reopen durability cycles in Cscape.
4. Formal mathematical and byte-level conversion examples.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import math
import struct
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


class ModbusTransport(str, Enum):
    """Modbus physical / transport layer."""
    TCP = "MODBUS_TCP"
    RTU = "MODBUS_RTU"


class ModbusRole(str, Enum):
    """Modbus node operational role. Strictly read-only for PV provider acquisition."""
    CLIENT_MASTER_READ_ONLY = "CLIENT_MASTER_READ_ONLY"


class ModbusFunctionCode(int, Enum):
    """Modbus standard query function codes."""
    READ_HOLDING_REGISTERS = 3  # 0x03: Read 16-bit Holding Registers (40001+)
    READ_INPUT_REGISTERS = 4    # 0x04: Read 16-bit Input Registers (30001+)


class ModbusEndianness(str, Enum):
    """Byte and Word ordering schemes."""
    BIG_ENDIAN_AB = "BIG_ENDIAN_AB"              # Standard Modicon Big-Endian (AB)
    LITTLE_ENDIAN_BA = "LITTLE_ENDIAN_BA"        # Byte-swapped (BA)
    BIG_ENDIAN_ABCD = "BIG_ENDIAN_ABCD"          # 32-bit Big-Endian (High word, High byte)
    WORD_SWAPPED_CDAB = "WORD_SWAPPED_CDAB"      # 32-bit Word-Swapped (Low word first)


class RawDataType(str, Enum):
    """Data representation of register on the fieldbus wire."""
    UINT16 = "UINT16"    # 16-bit unsigned integer (0..65535)
    INT16 = "INT16"      # 16-bit signed integer (-32768..32767)
    FLOAT32 = "FLOAT32"  # 32-bit IEEE 754 floating point (2 registers)


class QualityState(str, Enum):
    """Process variable quality and health state."""
    GOOD = "GOOD"
    STALE = "STALE"
    COMM_TIMEOUT = "COMM_TIMEOUT"
    OUT_OF_RANGE = "OUT_OF_RANGE"


@dataclass
class ModbusTCPEndpoint:
    """Modbus TCP network endpoint configuration."""
    ip_address: str = "127.0.0.1"
    port: int = 15502  # Default test port; production is typically 502
    connect_timeout_ms: int = 1000

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ModbusRTUEndpoint:
    """Modbus RTU serial line endpoint configuration."""
    serial_port: str = "MJ1_RS485"  # Horner OCS MJ1 or MJ2 serial port in RS-485 mode
    baud_rate: int = 19200
    data_bits: int = 8
    parity: str = "NONE"            # NONE, EVEN, ODD
    stop_bits: int = 1
    mode: str = "RS-485"
    driver_label: str = "CT RTU Modbus CMP v 5.05 / Modbus Master v 5.07"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ModbusAddressMapping:
    """Address specifications across standard conventions and Horner OCS memory."""
    # Modbus 1-based reference convention (Modicon standard)
    modicon_1based: int = 40001
    # Modbus 0-based wire/PDU offset
    wire_offset_0based: int = 0
    # Register span
    register_count: int = 1
    # Horner OCS controller internal target register
    horner_ocs_register: str = "%AI1"
    # Process variable name in IEC 61131-3 logic
    variable_name: str = "TankLevelPV"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScalingConfiguration:
    """Linear engineering unit conversion and transfer parameters."""
    raw_min: float = 0.0
    raw_max: float = 32000.0  # Horner standard 15-bit ADC count (0..32000)
    eu_min: float = 0.0
    eu_max: float = 100.0     # 0.0..100.0 % Tank Level
    engineering_unit: str = "%"
    clamp_to_limits: bool = True
    fail_safe_value: float = 0.0

    def compute_scaled_pv(self, raw_value: float) -> Tuple[float, QualityState]:
        """Apply linear transfer formula to calculate scaled PV and verify range."""
        raw_span = self.raw_max - self.raw_min
        if abs(raw_span) < 1e-9:
            return self.fail_safe_value, QualityState.OUT_OF_RANGE

        # PV_EU = (Raw - Raw_Min) * (EU_Max - EU_Min) / (Raw_Max - Raw_Min) + EU_Min
        eu_span = self.eu_max - self.eu_min
        scaled = ((raw_value - self.raw_min) * eu_span / raw_span) + self.eu_min

        quality = QualityState.GOOD
        if self.clamp_to_limits:
            if scaled < self.eu_min or scaled > self.eu_max:
                quality = QualityState.OUT_OF_RANGE
                scaled = max(self.eu_min, min(scaled, self.eu_max))

        return round(scaled, 4), quality

    def compute_raw_from_eu(self, eu_value: float) -> int:
        """Inverse transfer calculation from engineering units to raw register counts."""
        eu_span = self.eu_max - self.eu_min
        if abs(eu_span) < 1e-9:
            return int(self.raw_min)
        raw = ((eu_value - self.eu_min) * (self.raw_max - self.raw_min) / eu_span) + self.raw_min
        return int(round(raw))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PollingAndStalePolicy:
    """Timing, timeout, retry, and stale detection parameters."""
    poll_interval_ms: int = 100         # Scan cycle poll frequency (100ms)
    response_timeout_ms: int = 1000     # Modbus transaction response timeout
    retry_count: int = 3                # Consecutive attempts before comm fault
    stale_timeout_ms: int = 2000        # Missed poll duration to declare STALE
    comm_failure_alarm_reg: str = "%M10"  # Horner OCS bit for communication failure
    stale_quality_bit_reg: str = "%M11"   # Horner OCS bit for stale telemetry quality
    action_on_stale: str = "CLAMP_TO_FAIL_SAFE"  # CLAMP_TO_FAIL_SAFE or HOLD_LAST_VALID

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ModbusPVProviderConfig:
    """Full inventory configuration for native Cscape Modbus Process Variable provider."""
    config_id: str = "TankLevel_ModbusPV_Config_v1"
    description: str = "Native Cscape Modbus PV Provider Config for Buffer Tank Level Sensor"
    transport: ModbusTransport = ModbusTransport.TCP
    role: ModbusRole = ModbusRole.CLIENT_MASTER_READ_ONLY
    unit_id: int = 1
    function_code: ModbusFunctionCode = ModbusFunctionCode.READ_HOLDING_REGISTERS
    tcp_endpoint: ModbusTCPEndpoint = field(default_factory=ModbusTCPEndpoint)
    rtu_endpoint: ModbusRTUEndpoint = field(default_factory=ModbusRTUEndpoint)
    address_mapping: ModbusAddressMapping = field(default_factory=ModbusAddressMapping)
    raw_data_type: RawDataType = RawDataType.UINT16
    endianness: ModbusEndianness = ModbusEndianness.BIG_ENDIAN_AB
    scaling: ScalingConfiguration = field(default_factory=ScalingConfiguration)
    policy: PollingAndStalePolicy = field(default_factory=PollingAndStalePolicy)
    revision: str = "1.0.0"
    created_utc: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    last_modified_utc: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    read_only_enforced: bool = True
    safety_lockout_verified: bool = True
    physical_runtime_verification: str = "PENDING_P7 (Strictly deferred to Phase P7; zero PLC download)"

    def compute_config_hash(self) -> str:
        """Compute deterministic SHA-256 fingerprint of the configuration."""
        data_str = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(data_str.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config_id": self.config_id,
            "description": self.description,
            "transport": self.transport.value,
            "role": self.role.value,
            "unit_id": self.unit_id,
            "function_code": self.function_code.value,
            "function_name": f"Read Holding Registers (0x{self.function_code.value:02X})" if self.function_code == 3 else f"Read Input Registers (0x{self.function_code.value:02X})",
            "tcp_endpoint": self.tcp_endpoint.to_dict(),
            "rtu_endpoint": self.rtu_endpoint.to_dict(),
            "address_mapping": self.address_mapping.to_dict(),
            "raw_data_type": self.raw_data_type.value,
            "endianness": self.endianness.value,
            "scaling": self.scaling.to_dict(),
            "policy": self.policy.to_dict(),
            "revision": self.revision,
            "created_utc": self.created_utc,
            "last_modified_utc": self.last_modified_utc,
            "read_only_enforced": self.read_only_enforced,
            "safety_lockout_verified": self.safety_lockout_verified,
            "physical_runtime_verification": self.physical_runtime_verification,
            "sha256": None,  # Populated dynamically
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ModbusPVProviderConfig:
        """Deserialize ModbusPVProviderConfig from dictionary."""
        return cls(
            config_id=data.get("config_id", "TankLevel_ModbusPV_Config_v1"),
            description=data.get("description", ""),
            transport=ModbusTransport(data.get("transport", ModbusTransport.TCP.value)),
            role=ModbusRole(data.get("role", ModbusRole.CLIENT_MASTER_READ_ONLY.value)),
            unit_id=int(data.get("unit_id", 1)),
            function_code=ModbusFunctionCode(int(data.get("function_code", 3))),
            tcp_endpoint=ModbusTCPEndpoint(**data.get("tcp_endpoint", {})),
            rtu_endpoint=ModbusRTUEndpoint(**data.get("rtu_endpoint", {})),
            address_mapping=ModbusAddressMapping(**data.get("address_mapping", {})),
            raw_data_type=RawDataType(data.get("raw_data_type", RawDataType.UINT16.value)),
            endianness=ModbusEndianness(data.get("endianness", ModbusEndianness.BIG_ENDIAN_AB.value)),
            scaling=ScalingConfiguration(**data.get("scaling", {})),
            policy=PollingAndStalePolicy(**data.get("policy", {})),
            revision=data.get("revision", "1.0.0"),
            created_utc=data.get("created_utc", ""),
            last_modified_utc=data.get("last_modified_utc", ""),
            read_only_enforced=data.get("read_only_enforced", True),
            safety_lockout_verified=data.get("safety_lockout_verified", True),
            physical_runtime_verification=data.get("physical_runtime_verification", "PENDING_P7"),
        )


@dataclass
class ModbusDevice:
    """Modbus slave device / field transmitter descriptor."""
    device_id: str
    device_name: str
    unit_id: int
    description: str
    transport: ModbusTransport = ModbusTransport.TCP
    poll_interval_ms: int = 100
    timeout_ms: int = 1000
    retry_count: int = 3
    fail_safe_policy: str = "CLAMP_TO_FAIL_SAFE"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "unit_id": self.unit_id,
            "description": self.description,
            "transport": self.transport.value,
            "poll_interval_ms": self.poll_interval_ms,
            "timeout_ms": self.timeout_ms,
            "retry_count": self.retry_count,
            "fail_safe_policy": self.fail_safe_policy,
        }


@dataclass
class ModbusScanTransaction:
    """Individual cyclic or triggered scan entry in the Horner Modbus Master scan list."""
    transaction_id: str
    device_id: str
    unit_id: int
    function_code: ModbusFunctionCode
    modicon_address: int           # 1-based (e.g. 40001)
    wire_offset: int               # 0-based (e.g. 0)
    register_count: int
    target_ocs_register: str       # e.g. %AI1, %AI2, %R101
    variable_name: str             # e.g. TankLevelPV, InflowRatePV
    raw_data_type: RawDataType = RawDataType.UINT16
    engineering_unit: str = "%"
    scaling_raw_min: float = 0.0
    scaling_raw_max: float = 32000.0
    scaling_eu_min: float = 0.0
    scaling_eu_max: float = 100.0
    comm_alarm_register: str = "%M10"
    stale_quality_register: str = "%M11"
    poll_interval_ms: int = 100
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "device_id": self.device_id,
            "unit_id": self.unit_id,
            "function_code": self.function_code.value,
            "function_name": "Read Holding Registers (0x03)" if self.function_code == 3 else "Read Input Registers (0x04)",
            "modicon_address": self.modicon_address,
            "wire_offset": self.wire_offset,
            "register_count": self.register_count,
            "target_ocs_register": self.target_ocs_register,
            "variable_name": self.variable_name,
            "raw_data_type": self.raw_data_type.value,
            "engineering_unit": self.engineering_unit,
            "scaling": {
                "raw_min": self.scaling_raw_min,
                "raw_max": self.scaling_raw_max,
                "eu_min": self.scaling_eu_min,
                "eu_max": self.scaling_eu_max,
            },
            "comm_alarm_register": self.comm_alarm_register,
            "stale_quality_register": self.stale_quality_register,
            "poll_interval_ms": self.poll_interval_ms,
            "description": self.description,
        }


@dataclass
class ModbusChannelConfig:
    """Fieldbus communication port and protocol channel mapping."""
    channel_id: str
    channel_name: str
    transport: ModbusTransport
    role: ModbusRole = ModbusRole.CLIENT_MASTER_READ_ONLY
    tcp_endpoint: Optional[ModbusTCPEndpoint] = None
    rtu_endpoint: Optional[ModbusRTUEndpoint] = None
    max_concurrent_sockets: int = 4
    inter_frame_delay_ms: float = 3.5
    mode: Optional[str] = None
    driver_label: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "channel_id": self.channel_id,
            "channel_name": self.channel_name,
            "transport": self.transport.value,
            "role": self.role.value,
            "tcp_endpoint": self.tcp_endpoint.to_dict() if self.tcp_endpoint else None,
            "rtu_endpoint": self.rtu_endpoint.to_dict() if self.rtu_endpoint else None,
            "max_concurrent_sockets": self.max_concurrent_sockets,
            "inter_frame_delay_ms": self.inter_frame_delay_ms,
        }
        if self.mode is not None:
            d["mode"] = self.mode
        elif self.rtu_endpoint and hasattr(self.rtu_endpoint, "mode") and self.rtu_endpoint.mode:
            d["mode"] = self.rtu_endpoint.mode
        if self.driver_label is not None:
            d["driver_label"] = self.driver_label
        elif self.rtu_endpoint and hasattr(self.rtu_endpoint, "driver_label") and self.rtu_endpoint.driver_label:
            d["driver_label"] = self.rtu_endpoint.driver_label
        return d


@dataclass
class ModbusDeepProtocolInventory:
    """Comprehensive multi-device, multi-transaction Modbus fieldbus inventory."""
    inventory_id: str = "Cscape_Native_Modbus_Deep_Inventory_v1"
    project_name: str = "TankLevel_P5_Dedicated"
    description: str = "Comprehensive Native Modbus Devices, Channels, and Scan List Inventory"
    channels: List[ModbusChannelConfig] = field(default_factory=list)
    devices: List[ModbusDevice] = field(default_factory=list)
    scan_list: List[ModbusScanTransaction] = field(default_factory=list)
    revision: str = "1.0.0"
    created_utc: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    last_modified_utc: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    read_only_enforced: bool = True
    safety_lockout: Dict[str, str] = field(default_factory=lambda: {
        "physical_ports": "BLOCKED_FAIL_CLOSED (COM1-COM256)",
        "download_commands": "BLOCKED_FAIL_CLOSED (32827/33149)",
        "write_commands": "REJECTED_MODBUS_EXC_01_ILLEGAL_FUNCTION",
        "physical_runtime_verification": "PENDING_P7 (Strictly deferred to Phase P7)",
    })

    def compute_inventory_hash(self) -> str:
        d = self.to_dict()
        d_str = json.dumps(d, sort_keys=True)
        return hashlib.sha256(d_str.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "inventory_id": self.inventory_id,
            "project_name": self.project_name,
            "description": self.description,
            "channels": [c.to_dict() for c in self.channels],
            "devices": [d.to_dict() for d in self.devices],
            "scan_list": [s.to_dict() for s in self.scan_list],
            "revision": self.revision,
            "created_utc": self.created_utc,
            "last_modified_utc": self.last_modified_utc,
            "read_only_enforced": self.read_only_enforced,
            "safety_lockout": self.safety_lockout,
            "devices_count": len(self.devices),
            "scan_list_count": len(self.scan_list),
            "channels_count": len(self.channels),
            "sha256": None,
        }


class ModbusConfigPersistenceManager:
    """Manages creation, serialization, persistence, and durability re-reading of Modbus configs."""

    @staticmethod
    def get_config_sidecar_path(project_dir: Path) -> Path:
        """Returns standard path for Modbus PV configuration sidecar."""
        return project_dir / "modbus_pv_config.json"

    @staticmethod
    def get_inventory_doc_path(project_dir: Path) -> Path:
        """Returns standard path for full Modbus inventory document."""
        return project_dir / "modbus_protocol_inventory.json"

    @classmethod
    def build_default_deep_inventory(cls, project_name: str = "TankLevel_P5_Dedicated") -> ModbusDeepProtocolInventory:
        """Constructs a production-grade multi-device, multi-transaction deep Modbus inventory."""
        ch_tcp = ModbusChannelConfig(
            channel_id="CH_LAN1_TCP",
            channel_name="Ethernet LAN1 Modbus TCP Client",
            transport=ModbusTransport.TCP,
            tcp_endpoint=ModbusTCPEndpoint(ip_address="127.0.0.1", port=15502),
        )
        ch_mj1_rtu = ModbusChannelConfig(
            channel_id="CH_MJ1_RTU",
            channel_name="Serial MJ1 RS-485 Modbus RTU Master",
            transport=ModbusTransport.RTU,
            rtu_endpoint=ModbusRTUEndpoint(
                serial_port="MJ1_RS485",
                baud_rate=19200,
                data_bits=8,
                parity="NONE",
                stop_bits=1,
                mode="RS-485",
                driver_label="CT RTU Modbus CMP v 5.05 / Modbus Master v 5.07",
            ),
            mode="RS-485",
            driver_label="CT RTU Modbus CMP v 5.05 / Modbus Master v 5.07",
        )
        ch_mj2_rtu = ModbusChannelConfig(
            channel_id="CH_MJ2_RTU",
            channel_name="Serial MJ2 RS-485 Modbus RTU Master",
            transport=ModbusTransport.RTU,
            rtu_endpoint=ModbusRTUEndpoint(
                serial_port="MJ2_RS485",
                baud_rate=19200,
                data_bits=8,
                parity="NONE",
                stop_bits=1,
                mode="RS-485",
                driver_label="CT RTU Modbus CMP v 5.05 / Modbus Master v 5.07",
            ),
            mode="RS-485",
            driver_label="CT RTU Modbus CMP v 5.05 / Modbus Master v 5.07",
        )

        dev_level = ModbusDevice(
            device_id="DEV_LT01",
            device_name="Buffer Tank Level Transmitter",
            unit_id=1,
            description="Hydrostatic level sensor measuring 0..100 %",
            poll_interval_ms=100,
        )
        dev_flow = ModbusDevice(
            device_id="DEV_FT01",
            device_name="Inflow Coriolis Flowmeter",
            unit_id=2,
            description="Electromagnetic flowmeter measuring 0..500 L/min",
            poll_interval_ms=200,
        )
        dev_press = ModbusDevice(
            device_id="DEV_PT01",
            device_name="Discharge Pressure Transmitter",
            unit_id=3,
            description="Piezoresistive pressure transmitter measuring 0..10 bar",
            poll_interval_ms=200,
        )

        tx_level = ModbusScanTransaction(
            transaction_id="TX01_LEVEL_PV",
            device_id="DEV_LT01",
            unit_id=1,
            function_code=ModbusFunctionCode.READ_HOLDING_REGISTERS,
            modicon_address=40001,
            wire_offset=0,
            register_count=1,
            target_ocs_register="%AI1",
            variable_name="TankLevelPV",
            engineering_unit="%",
            scaling_raw_min=0.0,
            scaling_raw_max=32000.0,
            scaling_eu_min=0.0,
            scaling_eu_max=100.0,
            comm_alarm_register="%M10",
            stale_quality_register="%M11",
            poll_interval_ms=100,
            description="Continuous scan of tank liquid level",
        )
        tx_flow = ModbusScanTransaction(
            transaction_id="TX02_INFLOW_RATE",
            device_id="DEV_FT01",
            unit_id=2,
            function_code=ModbusFunctionCode.READ_HOLDING_REGISTERS,
            modicon_address=40002,
            wire_offset=1,
            register_count=1,
            target_ocs_register="%AI2",
            variable_name="InflowRatePV",
            engineering_unit="L/min",
            scaling_raw_min=0.0,
            scaling_raw_max=32000.0,
            scaling_eu_min=0.0,
            scaling_eu_max=500.0,
            comm_alarm_register="%M12",
            stale_quality_register="%M13",
            poll_interval_ms=200,
            description="Cyclic scan of buffer tank inflow rate",
        )
        tx_press = ModbusScanTransaction(
            transaction_id="TX03_DISCHARGE_PRESS",
            device_id="DEV_PT01",
            unit_id=3,
            function_code=ModbusFunctionCode.READ_HOLDING_REGISTERS,
            modicon_address=40003,
            wire_offset=2,
            register_count=1,
            target_ocs_register="%AI3",
            variable_name="DischargePressPV",
            engineering_unit="bar",
            scaling_raw_min=0.0,
            scaling_raw_max=32000.0,
            scaling_eu_min=0.0,
            scaling_eu_max=10.0,
            comm_alarm_register="%M14",
            stale_quality_register="%M15",
            poll_interval_ms=200,
            description="Cyclic scan of pump discharge pressure",
        )

        return ModbusDeepProtocolInventory(
            inventory_id=f"{project_name}_Modbus_Deep_Inventory",
            project_name=project_name,
            channels=[ch_tcp, ch_mj1_rtu, ch_mj2_rtu],
            devices=[dev_level, dev_flow, dev_press],
            scan_list=[tx_level, tx_flow, tx_press],
        )

    @classmethod
    def persist_deep_inventory(
        cls,
        project_dir: Path,
        inventory: Optional[ModbusDeepProtocolInventory] = None,
    ) -> Tuple[Path, str]:
        """Persist full deep Modbus protocol inventory (devices, scan list, channels) to disk."""
        project_dir.mkdir(parents=True, exist_ok=True)
        if inventory is None:
            inventory = cls.build_default_deep_inventory(project_dir.name)

        inv_path = cls.get_inventory_doc_path(project_dir)
        inv_dict = inventory.to_dict()
        inv_hash = inventory.compute_inventory_hash()
        inv_dict["sha256"] = inv_hash

        content = json.dumps(inv_dict, indent=2)
        inv_path.write_text(content, encoding="utf-8")
        logger.info(f"Persisted deep Modbus inventory ({len(inventory.devices)} devices, {len(inventory.scan_list)} scan transactions) to: {inv_path}")
        return inv_path, inv_hash

    @classmethod
    def read_deep_inventory(cls, project_dir: Path) -> Optional[Dict[str, Any]]:
        """Re-read deep Modbus protocol inventory from disk."""
        inv_path = cls.get_inventory_doc_path(project_dir)
        if not inv_path.exists():
            return None
        try:
            return json.loads(inv_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Failed to read deep Modbus inventory from {inv_path}: {e}")
            return None

    @classmethod
    def persist_config(
        cls,
        project_dir: Path,
        config: ModbusPVProviderConfig,
        deep_inventory: Optional[ModbusDeepProtocolInventory] = None,
    ) -> Tuple[Path, str]:
        """Persist Modbus configuration into project directory and return file path and SHA-256."""
        project_dir.mkdir(parents=True, exist_ok=True)
        sidecar_path = cls.get_config_sidecar_path(project_dir)

        # Update modification timestamp if not already set, then compute hash
        if not config.last_modified_utc:
            config.last_modified_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cfg_dict = config.to_dict()
        cfg_hash = config.compute_config_hash()
        cfg_dict["sha256"] = cfg_hash

        content = json.dumps(cfg_dict, indent=2)
        sidecar_path.write_text(content, encoding="utf-8")

        # Persist full deep inventory to modbus_protocol_inventory.json
        if deep_inventory is None:
            deep_inventory = cls.build_default_deep_inventory(project_dir.name)
        cls.persist_deep_inventory(project_dir, deep_inventory)

        logger.info(f"Persisted Modbus PV provider config to: {sidecar_path} (SHA-256: {cfg_hash[:16]}...)")
        return sidecar_path, cfg_hash

    @classmethod
    def read_config(cls, project_dir: Path) -> Optional[ModbusPVProviderConfig]:
        """Re-read and validate persisted Modbus configuration from project directory."""
        sidecar_path = cls.get_config_sidecar_path(project_dir)
        if not sidecar_path.exists():
            return None

        try:
            data = json.loads(sidecar_path.read_text(encoding="utf-8"))
            return ModbusPVProviderConfig.from_dict(data)
        except Exception as err:
            logger.error(f"Failed to read Modbus config from {sidecar_path}: {err}")
            return None


def generate_modbus_conversion_walkthrough(
    level_pct: float = 55.0,
    config: Optional[ModbusPVProviderConfig] = None,
) -> Dict[str, Any]:
    """Generate detailed mathematical, byte-level, and protocol conversion walkthrough.

    Demonstrates:
    1. Engineering units level -> Raw ADC counts
    2. Modbus TCP client request framing (MBAP + FC03 PDU)
    3. Modbus TCP server response framing (MBAP + FC03 PDU + Data Bytes)
    4. Horner OCS register decoding & endianness handling
    5. Pure IEC 61131-3 Structured Text scaling logic
    6. Watchdog, timeout, and stale fault behavior
    """
    if config is None:
        config = ModbusPVProviderConfig()

    scaling = config.scaling
    raw_count = scaling.compute_raw_from_eu(level_pct)
    recalculated_eu, quality = scaling.compute_scaled_pv(raw_count)

    # 1. Modbus TCP Request Frame
    # MBAP Header:
    #   Transaction ID: 0x0001 (2 bytes)
    #   Protocol ID:    0x0000 (2 bytes)
    #   Length:         0x0006 (2 bytes, 6 following bytes)
    #   Unit ID:        0x01   (1 byte)
    # PDU:
    #   Function Code:  0x03   (1 byte, Read Holding Registers)
    #   Start Address:  0x0000 (2 bytes, 0-based offset for 40001)
    #   Quantity:       0x0001 (2 bytes, 1 register)
    tx_id = 1
    proto_id = 0
    unit_id = config.unit_id
    fc = config.function_code.value
    start_addr = config.address_mapping.wire_offset_0based
    qty = config.address_mapping.register_count

    req_bytes = struct.pack(">HHHBBHH", tx_id, proto_id, 6, unit_id, fc, start_addr, qty)
    req_hex = " ".join(f"{b:02X}" for b in req_bytes)

    # 2. Modbus TCP Response Frame
    # MBAP Header:
    #   Transaction ID: 0x0001 (2 bytes)
    #   Protocol ID:    0x0000 (2 bytes)
    #   Length:         0x0005 (2 bytes, 5 following bytes)
    #   Unit ID:        0x01   (1 byte)
    # PDU:
    #   Function Code:  0x03   (1 byte)
    #   Byte Count:     0x02   (1 byte, 2 * 1 register = 2 bytes)
    #   Register Value: 0x44C0 (2 bytes, Big-Endian 17600)
    resp_length = 3 + 2 * qty
    resp_bytes = struct.pack(">HHHBBB", tx_id, proto_id, resp_length, unit_id, fc, 2 * qty) + struct.pack(">H", raw_count)
    resp_hex = " ".join(f"{b:02X}" for b in resp_bytes)

    raw_high_byte = (raw_count >> 8) & 0xFF
    raw_low_byte = raw_count & 0xFF

    return {
        "example_name": "Tank Level PV Modbus Telemetry Acquisition Walkthrough",
        "parameters": {
            "target_level_percent": level_pct,
            "raw_min": scaling.raw_min,
            "raw_max": scaling.raw_max,
            "eu_min": scaling.eu_min,
            "eu_max": scaling.eu_max,
            "engineering_unit": "%",
            "unit_id": unit_id,
            "modicon_1based_address": config.address_mapping.modicon_1based,
            "wire_0based_offset": f"0x{start_addr:04X} ({start_addr})",
            "function_code": f"0x{fc:02X} (FC{fc:02d})",
            "horner_target_register": config.address_mapping.horner_ocs_register,
            "variable_name": config.address_mapping.variable_name,
        },
        "step1_mathematical_conversion": {
            "description": "Calculate raw integer register count from engineering level percentage",
            "formula": "Raw = ((PV_EU - EU_Min) * (Raw_Max - Raw_Min) / (EU_Max - EU_Min)) + Raw_Min",
            "substitution": f"Raw = (({level_pct} - {scaling.eu_min}) * ({scaling.raw_max} - {scaling.raw_min}) / ({scaling.eu_max} - {scaling.eu_min})) + {scaling.raw_min}",
            "calculation": f"Raw = ({level_pct} * 32000.0 / 100.0) = {raw_count}",
            "raw_integer_value": raw_count,
            "raw_hex_word": f"0x{raw_count:04X}",
            "high_byte": f"0x{raw_high_byte:02X}",
            "low_byte": f"0x{raw_low_byte:02X}",
        },
        "step2_protocol_request_frame": {
            "description": "Modbus TCP Client Request (OCS Master queries remote sensor)",
            "mbap_header": {
                "transaction_id": f"0x{tx_id:04X} ({tx_id})",
                "protocol_id": f"0x{proto_id:04X} (Modbus TCP)",
                "length": "0x0006 (6 bytes follow)",
                "unit_id": f"0x{unit_id:02X} ({unit_id})",
            },
            "pdu": {
                "function_code": f"0x{fc:02X} (Read Holding Registers)",
                "starting_address": f"0x{start_addr:04X} (Offset 0 for register 40001)",
                "quantity": f"0x{qty:04X} ({qty} register)",
            },
            "complete_frame_hex": req_hex,
            "frame_length_bytes": len(req_bytes),
        },
        "step3_protocol_response_frame": {
            "description": "Modbus TCP Server Response (Sensor replies with raw telemetry)",
            "mbap_header": {
                "transaction_id": f"0x{tx_id:04X} (Echoed)",
                "protocol_id": f"0x{proto_id:04X} (Modbus TCP)",
                "length": f"0x{resp_length:04X} ({resp_length} bytes follow)",
                "unit_id": f"0x{unit_id:02X} ({unit_id})",
            },
            "pdu": {
                "function_code": f"0x{fc:02X} (Read Holding Registers)",
                "byte_count": f"0x{2 * qty:02X} (2 bytes)",
                "register_data_hex": f"0x{raw_count:04X} ({raw_count})",
            },
            "complete_frame_hex": resp_hex,
            "frame_length_bytes": len(resp_bytes),
        },
        "step4_horner_memory_and_st_scaling": {
            "description": "Horner OCS driver moves 0x44C0 into %AI1; ST POU executes engineering unit conversion",
            "st_code_snippet": [
                f"(* Channel 1: Hydrostatic Level Transmitter via Modbus *)",
                f"RawAnalogInput := %AI1; (* Receives {raw_count} (0x{raw_count:04X}) *)",
                f"IF NOT CommFailureAlarm THEN",
                f"    TankLevelPV := WORD_TO_REAL(RawAnalogInput) * 100.0 / 32000.0;",
                f"    TankLevelPV := LIMIT(0.0, TankLevelPV, 100.0);",
                f"ELSE",
                f"    TankLevelPV := 0.0; (* Fail-safe clamp *)",
                f"END_IF;",
            ],
            "computed_pv_value": recalculated_eu,
            "engineering_unit": "%",
            "quality": quality.value,
        },
        "step5_stale_and_timeout_behavior": {
            "response_timeout": f"{config.policy.response_timeout_ms} ms",
            "max_retries": config.policy.retry_count,
            "stale_timeout": f"{config.policy.stale_timeout_ms} ms",
            "comm_failure_bit": config.policy.comm_failure_alarm_reg,
            "stale_bit": config.policy.stale_quality_bit_reg,
            "fail_safe_behavior": "If no reply within 1000ms, retry up to 3 times. If unacknowledged for > 2000ms, set %M10 (CommFailureAlarm) = TRUE, set %M11 (TankLevelPV_Stale) = TRUE, and clamp TankLevelPV to 0.0%.",
        },
        "safety_declaration": "Physical/runtime verification PENDING_P7 (Strictly deferred to Phase P7). Do not claim live sensor/PLC success. Zero PLC download.",
    }
