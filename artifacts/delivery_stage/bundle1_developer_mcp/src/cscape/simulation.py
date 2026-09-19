"""Horner Cscape 10.2 Simulation and Offline Runtime Interface.

Provides a robust, pure-software interface to Cscape 10.2 and Straton K5
offline simulation environments.

Key Capabilities:
1. Built-in Simulation Activation:
   - Win32 / MFC Menu Command IDs (ID_STRATON_RUNTIME_DEBUG_SIMULATION = 38367,
     ID_STRATON_RUNTIME_DEBUG_STOP = 38037, ID_STRATON_RUNTIME_DEBUG_EXECUTESINGLE = 38357,
     ID_STRATON_RUNTIME_DEBUG_RESUME = 38365, ID_SIMULATE_LOCAL = 32812).
   - Straton K5 simulator compiler target configuration (Simul=ON, Target=T5SIMUL, .XWS).
   - Pure-software offline simulation runtime engine.
2. Software Execution & Register Memory Model:
   - Complete Horner OCS Register architecture:
     * Word registers (%R1-%R9999, %AI1-%AI512, %AQ1-%AQ512, %SR1-%SR256).
     * Discrete bit registers (%I1-%I2048, %Q1-%Q2048, %M1-%M2048, %T1-%T2048, %S1-%S16).
   - Support for 16-bit INT/UINT, 32-bit DINT/DWORD, and 32-bit IEEE-754 REAL floating-point.
   - Cycle-accurate execution with Horner system bits (%S1 first-scan pulse, %S7 10ms clock,
     %S8 100ms clock, %S9 1000ms clock) and system registers (%SR1 scan rate, %SR2 status).
   - Automatic variable-to-register mapping (AT %... directives and programmatic binding).
3. 100% Software Isolation Guarantee:
   - Zero physical PLC hardware interaction.
   - Hardware port lockout: all COM, CAN, USB, LPT, and /dev/tty ports strictly blocked.
   - All controller download and firmware flash commands strictly intercepted and blocked.
"""

from __future__ import annotations

# Strict taxonomy classification
CLASSIFICATION: str = "TESTED_MOCK [offline/DEV only]"
VERIFICATION_CLASSIFICATION: str = "TESTED_MOCK [offline/DEV only]"

import enum
import logging
import math
import os
from pathlib import Path
import re
import struct
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union

# Safety guard and exception imports
from ..security.exceptions import (
    HardwareLockoutError,
    SecurityError,
    UnauthorizedDownloadError,
)
from ..security.guard import SecurityGuard
from ..security.policy import (
    DEFAULT_BLOCKED_DOWNLOAD_FLAGS,
    DEFAULT_BLOCKED_EXECUTABLES,
    DEFAULT_BLOCKED_FLAGS,
    DEFAULT_BLOCKED_HARDWARE_FLAGS,
    DEFAULT_BLOCKED_INTERFACE_PATTERNS,
    DEFAULT_BLOCKED_PORT_PATTERNS,
    DEFAULT_BLOCKED_PROTOCOLS,
    DEFAULT_BLOCKED_UI_COMMANDS,
    SafetyPolicy,
)
from ..simulation.simulator import STSimulator, CycleSnapshot, SimulationError

logger = logging.getLogger(__name__)


# ============================================================================
# 1. Cscape 10.2 Win32 & Straton K5 Simulation Command IDs & Constants
# ============================================================================

class CscapeCommandID(enum.IntEnum):
    """Win32 MFC Command IDs for Cscape 10.2 and Straton K5 simulation & debug."""

    # Start Enhanced IEC Simulation (Menu 550, ID_STRATON_RUNTIME_DEBUG_SIMULATION)
    START_SIMULATION = 38367          # 0x95DF
    # Stop Debugging / Simulation Programs (ID_STRATON_RUNTIME_DEBUG_STOP)
    STOP_DEBUG_SIMULATION = 38037     # 0x9495
    # Single Cycle Execution Step (ID_STRATON_RUNTIME_DEBUG_EXECUTESINGLE)
    EXECUTE_SINGLE_CYCLE = 38357      # 0x95D5
    # Resume Continuous Cycle-to-Cycle Execution (ID_STRATON_RUNTIME_DEBUG_RESUME)
    RESUME_CYCLE_MODE = 38365         # 0x95DD
    # Step In POU / Function Block (ID_STRATON_RUNTIME_DEBUG_STEPIN)
    STEP_IN = 38358                   # 0x95D6
    # Step Over Statement (ID_STRATON_RUNTIME_DEBUG_STEPOVER)
    STEP_OVER = 38359                 # 0x95D7
    # Step Out of Subroutine / FB (ID_STRATON_RUNTIME_DEBUG_STEPOUT)
    STEP_OUT = 38360                  # 0x95D8
    # Straton Runtime Profiler (ID_STRATON_RUNTIME_DEBUG_PROFILER)
    PROFILER = 38362                  # 0x95DA
    # Enhanced IEC Debug Root Menu
    ENHANCED_IEC_DEBUG = 38411        # 0x960B
    # Simulate Controller Program Locally (Standard Horner Editor)
    SIMULATE_LOCAL = 32812            # 0x802C
    # Debug / Monitor Mode Toggle
    DEBUG_MONITOR = 32838             # 0x8046
    # Debug All Logic Modules
    DEBUG_ALL = 32868                 # 0x8064
    # Stop All Debug
    STOP_ALL_DEBUG = 32869            # 0x8065
    # Offline Engineering Mode
    OFFLINE_MODE = 62660              # 0xF4C4


# Straton K5 Compiler Simulator Target Keys
STRATON_SIMULATION_TARGET = "T5SIMUL"
STRATON_SIMULATION_SUFFIX = ".XWS"
STRATON_RUNTIME_TARGET = "T5RTI"
STRATON_RUNTIME_SUFFIX = ".XTI"

# Default Cscape Installation Paths
DEFAULT_CSCAPE_PATH = Path(r"C:\Program Files (x86)\Cscape 10.2\Cscape.exe")


class SimulationState(str, enum.Enum):
    """Lifecycle state of the simulation session."""
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class SimulationBackend(str, enum.Enum):
    """Underlying simulation execution backend."""
    AUTO = "AUTO"              # Automatically chooses pure-software EMULATED
    EMULATED = "EMULATED"      # Pure-software in-memory IEC 61131-3 + Horner registers
    CSCAPE_UI = "CSCAPE_UI"    # Win32 headless Cscape UI automation (WM_COMMAND)


class RegisterType(str, enum.Enum):
    """Horner OCS Register Memory Types."""
    R = "R"      # General Word / 16-bit Registers (%R1 - %R9999)
    AI = "AI"    # Analog Inputs (%AI1 - %AI512)
    AQ = "AQ"    # Analog Outputs (%AQ1 - %AQ512)
    I = "I"      # Digital / Discrete Inputs (%I1 - %I2048)
    Q = "Q"      # Digital / Discrete Outputs (%Q1 - %Q2048)
    M = "M"      # Marker / Internal Bits (%M1 - %M2048)
    T = "T"      # Temporary Bits (%T1 - %T2048)
    S = "S"      # System Bits (%S1 - %S16)
    SR = "SR"    # System Registers (%SR1 - %SR256)
    D = "D"      # Display Bits (%D1 - %D1024)
    K = "K"      # Keypad Bits (%K1 - %K1024)


# Register limits according to Horner OCS specification
REGISTER_LIMITS: Dict[RegisterType, Tuple[int, int]] = {
    RegisterType.R: (1, 9999),
    RegisterType.AI: (1, 512),
    RegisterType.AQ: (1, 512),
    RegisterType.I: (1, 2048),
    RegisterType.Q: (1, 2048),
    RegisterType.M: (1, 2048),
    RegisterType.T: (1, 2048),
    RegisterType.S: (1, 16),
    RegisterType.SR: (1, 256),
    RegisterType.D: (1, 1024),
    RegisterType.K: (1, 1024),
}

# Register types categorized by word (16-bit) vs discrete (1-bit boolean)
WORD_REGISTER_TYPES = {RegisterType.R, RegisterType.AI, RegisterType.AQ, RegisterType.SR}
BIT_REGISTER_TYPES = {RegisterType.I, RegisterType.Q, RegisterType.M, RegisterType.T, RegisterType.S, RegisterType.D, RegisterType.K}


# ============================================================================
# 2. Register Address & Memory Management
# ============================================================================

@dataclass(frozen=True)
class RegisterAddress:
    """Parsed Horner OCS Register Address (e.g., %R100, %I1, %M5.2)."""
    reg_type: RegisterType
    index: int
    bit_offset: Optional[int] = None  # For bit-of-word indexing like %R100.3

    @property
    def canonical(self) -> str:
        """Return standardized uppercase IEC address string."""
        if self.bit_offset is not None:
            return f"%{self.reg_type.value}{self.index}.{self.bit_offset}"
        return f"%{self.reg_type.value}{self.index}"

    @property
    def is_word(self) -> bool:
        """True if the register is inherently a 16-bit word."""
        return self.reg_type in WORD_REGISTER_TYPES and self.bit_offset is None

    @property
    def is_bit(self) -> bool:
        """True if the register resolves to a boolean bit."""
        return self.reg_type in BIT_REGISTER_TYPES or self.bit_offset is not None

    def __str__(self) -> str:
        return self.canonical


def parse_register_address(addr_str: str) -> RegisterAddress:
    """Parses and validates a Horner register string (e.g. '%R100', '%i1', 'AQ5').

    Raises:
        ValueError: If format is invalid or index is out of bounds.
    """
    clean = addr_str.strip().upper()
    if clean.startswith("%"):
        clean = clean[1:]

    # Match register type prefix, index number, and optional .bit_offset
    m = re.match(r"^([A-Z]+)([0-9]+)(?:\.([0-9]+))?$", clean)
    if not m:
        raise ValueError(f"Invalid Horner register format: '{addr_str}'")

    prefix, idx_str, bit_str = m.group(1), m.group(2), m.group(3)

    try:
        reg_type = RegisterType(prefix)
    except ValueError:
        raise ValueError(
            f"Unknown Horner register type '{prefix}'. Valid: {[e.value for e in RegisterType]}"
        )

    index = int(idx_str)
    min_idx, max_idx = REGISTER_LIMITS[reg_type]
    if index < min_idx or index > max_idx:
        raise ValueError(
            f"Register %{prefix}{index} out of bounds (allowed: {min_idx} to {max_idx})"
        )

    bit_offset = None
    if bit_str is not None:
        bit_offset = int(bit_str)
        if bit_offset < 0 or bit_offset > 15:
            raise ValueError(
                f"Bit offset {bit_offset} out of bounds for word register (0 to 15)"
            )
        if reg_type in BIT_REGISTER_TYPES:
            raise ValueError(
                f"Cannot specify bit offset on discrete bit register %{prefix}{index}"
            )

    return RegisterAddress(reg_type=reg_type, index=index, bit_offset=bit_offset)


class HornerRegisterTable:
    """In-memory Horner OCS Register Table for simulation cycles.

    Stores all 16-bit word registers and discrete boolean bit registers.
    Performs Little-Endian multi-word IEEE 754 float (REAL) and 32-bit int (DINT)
    transformations, and updates system bits (%S) and system registers (%SR)
    synchronously with scan cycles.
    """

    def __init__(self) -> None:
        # 16-bit word registers stored as unsigned uint16 (0 - 65535)
        self._words: Dict[RegisterType, Dict[int, int]] = {
            RegisterType.R: {},
            RegisterType.AI: {},
            RegisterType.AQ: {},
            RegisterType.SR: {},
        }
        # Discrete boolean bits
        self._bits: Dict[RegisterType, Dict[int, bool]] = {
            RegisterType.I: {},
            RegisterType.Q: {},
            RegisterType.M: {},
            RegisterType.T: {},
            RegisterType.S: {},
            RegisterType.D: {},
            RegisterType.K: {},
        }

    def clear(self) -> None:
        """Reset all register banks to zero / false."""
        for w in self._words.values():
            w.clear()
        for b in self._bits.values():
            b.clear()

    # --- 16-bit Word Access ---

    def read_word(self, reg_type: RegisterType, index: int, signed: bool = True) -> int:
        """Read a 16-bit register word. Returns signed (-32768..32767) or unsigned (0..65535)."""
        if reg_type not in WORD_REGISTER_TYPES:
            raise ValueError(f"{reg_type.value} is a bit register, not a word register")
        min_idx, max_idx = REGISTER_LIMITS[reg_type]
        if index < min_idx or index > max_idx:
            raise ValueError(f"Index {index} out of bounds for %{reg_type.value}")
        raw = self._words[reg_type].get(index, 0) & 0xFFFF
        if signed and raw >= 0x8000:
            return raw - 0x10000
        return raw

    def write_word(self, reg_type: RegisterType, index: int, value: int) -> None:
        """Write a 16-bit register word, clipping/masking to 16 bits."""
        if reg_type not in WORD_REGISTER_TYPES:
            raise ValueError(f"{reg_type.value} is a bit register, not a word register")
        min_idx, max_idx = REGISTER_LIMITS[reg_type]
        if index < min_idx or index > max_idx:
            raise ValueError(f"Index {index} out of bounds for %{reg_type.value}")
        self._words[reg_type][index] = int(value) & 0xFFFF

    # --- Discrete Bit Access ---

    def read_bit(self, reg_type: RegisterType, index: int, bit_offset: Optional[int] = None) -> bool:
        """Read a boolean bit from bit table or a specific bit of a word register."""
        if reg_type in BIT_REGISTER_TYPES:
            min_idx, max_idx = REGISTER_LIMITS[reg_type]
            if index < min_idx or index > max_idx:
                raise ValueError(f"Index {index} out of bounds for %{reg_type.value}")
            return bool(self._bits[reg_type].get(index, False))
        elif reg_type in WORD_REGISTER_TYPES:
            if bit_offset is None:
                raise ValueError(f"Must specify bit_offset when reading bit from %{reg_type.value}")
            val = self.read_word(reg_type, index, signed=False)
            return bool((val >> bit_offset) & 1)
        raise ValueError(f"Unsupported register type {reg_type}")

    def write_bit(
        self,
        reg_type: RegisterType,
        index: int,
        value: bool,
        bit_offset: Optional[int] = None,
    ) -> None:
        """Write a boolean bit to bit table or a specific bit of a word register."""
        b_val = bool(value)
        if reg_type in BIT_REGISTER_TYPES:
            min_idx, max_idx = REGISTER_LIMITS[reg_type]
            if index < min_idx or index > max_idx:
                raise ValueError(f"Index {index} out of bounds for %{reg_type.value}")
            self._bits[reg_type][index] = b_val
        elif reg_type in WORD_REGISTER_TYPES:
            if bit_offset is None:
                raise ValueError(f"Must specify bit_offset when writing bit to %{reg_type.value}")
            curr = self.read_word(reg_type, index, signed=False)
            if b_val:
                new_val = curr | (1 << bit_offset)
            else:
                new_val = curr & ~(1 << bit_offset)
            self.write_word(reg_type, index, new_val)
        else:
            raise ValueError(f"Unsupported register type {reg_type}")

    # --- High-Level Address-Based Access ---

    def read(self, address_str: str) -> Union[int, bool]:
        """Read value from address string (e.g. '%R100', '%I1', '%R5.2')."""
        addr = parse_register_address(address_str)
        if addr.is_bit:
            return self.read_bit(addr.reg_type, addr.index, addr.bit_offset)
        return self.read_word(addr.reg_type, addr.index, signed=True)

    def write(self, address_str: str, value: Union[int, bool, float]) -> None:
        """Write value to address string (e.g. '%R100', '%I1', '%R5.2')."""
        addr = parse_register_address(address_str)
        if addr.is_bit:
            self.write_bit(addr.reg_type, addr.index, bool(value), addr.bit_offset)
        else:
            self.write_word(addr.reg_type, addr.index, int(value))

    # --- 32-Bit Types (DINT & REAL) Across Two Registers ---

    def read_dint(self, address_str: str) -> int:
        """Read a 32-bit signed DINT across address and address + 1 (Little-Endian words)."""
        addr = parse_register_address(address_str)
        if addr.reg_type not in WORD_REGISTER_TYPES:
            raise ValueError(f"DINT requires word registers, got {addr.reg_type.value}")
        w0 = self.read_word(addr.reg_type, addr.index, signed=False)
        w1 = self.read_word(addr.reg_type, addr.index + 1, signed=False)
        packed = struct.pack("<HH", w0, w1)
        return struct.unpack("<i", packed)[0]

    def write_dint(self, address_str: str, value: int) -> None:
        """Write a 32-bit signed DINT across address and address + 1 (Little-Endian words)."""
        addr = parse_register_address(address_str)
        if addr.reg_type not in WORD_REGISTER_TYPES:
            raise ValueError(f"DINT requires word registers, got {addr.reg_type.value}")
        packed = struct.pack("<i", int(value))
        w0, w1 = struct.unpack("<HH", packed)
        self.write_word(addr.reg_type, addr.index, w0)
        self.write_word(addr.reg_type, addr.index + 1, w1)

    def read_real(self, address_str: str) -> float:
        """Read a 32-bit IEEE 754 REAL float across address and address + 1."""
        addr = parse_register_address(address_str)
        if addr.reg_type not in WORD_REGISTER_TYPES:
            raise ValueError(f"REAL requires word registers, got {addr.reg_type.value}")
        w0 = self.read_word(addr.reg_type, addr.index, signed=False)
        w1 = self.read_word(addr.reg_type, addr.index + 1, signed=False)
        packed = struct.pack("<HH", w0, w1)
        return struct.unpack("<f", packed)[0]

    def write_real(self, address_str: str, value: float) -> None:
        """Write a 32-bit IEEE 754 REAL float across address and address + 1."""
        addr = parse_register_address(address_str)
        if addr.reg_type not in WORD_REGISTER_TYPES:
            raise ValueError(f"REAL requires word registers, got {addr.reg_type.value}")
        packed = struct.pack("<f", float(value))
        w0, w1 = struct.unpack("<HH", packed)
        self.write_word(addr.reg_type, addr.index, w0)
        self.write_word(addr.reg_type, addr.index + 1, w1)

    # --- Range Operations ---

    def read_range(self, reg_type: RegisterType, start_idx: int, count: int) -> List[Union[int, bool]]:
        """Read a contiguous range of registers."""
        results: List[Union[int, bool]] = []
        for i in range(start_idx, start_idx + count):
            if reg_type in WORD_REGISTER_TYPES:
                results.append(self.read_word(reg_type, i, signed=True))
            else:
                results.append(self.read_bit(reg_type, i))
        return results

    def write_range(
        self,
        reg_type: RegisterType,
        start_idx: int,
        values: Sequence[Union[int, bool]],
    ) -> None:
        """Write a contiguous sequence of values into registers starting at start_idx."""
        for offset, val in enumerate(values):
            idx = start_idx + offset
            if reg_type in WORD_REGISTER_TYPES:
                self.write_word(reg_type, idx, int(val))
            else:
                self.write_bit(reg_type, idx, bool(val))

    # --- System Registers & System Bits per Scan Cycle ---

    def update_system_registers(self, cycle_index: int, dt_ms: float, elapsed_time_ms: float) -> None:
        """Updates standard Horner system bits and system registers for the current cycle.

        Horner OCS System Bits:
        - %S1: First Cycle Pulse (TRUE exclusively on cycle 0, FALSE thereafter)
        - %S7: 10ms System Clock Square Wave (period 20ms, toggles every 10ms)
        - %S8: 100ms System Clock Square Wave (period 200ms, toggles every 100ms)
        - %S9: 1000ms System Clock Square Wave (period 2000ms, toggles every 1s)

        Horner OCS System Registers:
        - %SR1: Scan time of previous cycle (milliseconds)
        - %SR2: System Mode (1 = RUN / SIMULATION)
        - %SR3: Scan counter low word
        - %SR4: Scan counter high word
        """
        # %S1: First cycle scan pulse
        self.write_bit(RegisterType.S, 1, cycle_index == 0)

        # Clock pulse toggles based on accumulated elapsed time (50% duty cycle square wave)
        # %S7: 10ms on, 10ms off (period 20ms)
        # %S8: 100ms on, 100ms off (period 200ms)
        # %S9: 1000ms on, 1000ms off (period 2000ms)
        rounded_time = round(elapsed_time_ms, 3)
        s7_val = bool((int(rounded_time / 10.0)) % 2 == 1)
        s8_val = bool((int(rounded_time / 100.0)) % 2 == 1)
        s9_val = bool((int(rounded_time / 1000.0)) % 2 == 1)

        self.write_bit(RegisterType.S, 7, s7_val)
        self.write_bit(RegisterType.S, 8, s8_val)
        self.write_bit(RegisterType.S, 9, s9_val)

        # %SR1: Scan duration in integer ms
        self.write_word(RegisterType.SR, 1, int(round(dt_ms)))
        # %SR2: Operating mode: 1 indicates RUNNING simulation
        self.write_word(RegisterType.SR, 2, 1)
        # %SR3: Scan count low 16 bits
        self.write_word(RegisterType.SR, 3, cycle_index & 0xFFFF)
        # %SR4: Scan count high 16 bits
        self.write_word(RegisterType.SR, 4, (cycle_index >> 16) & 0xFFFF)

    def snapshot(self) -> Dict[str, Any]:
        """Returns a serializable dictionary snapshot of non-default register values."""
        snap: Dict[str, Any] = {}
        for r_type, bank in self._words.items():
            for idx, val in bank.items():
                if val != 0:
                    snap[f"%{r_type.value}{idx}"] = val
        for r_type, bank in self._bits.items():
            for idx, val in bank.items():
                if val:
                    snap[f"%{r_type.value}{idx}"] = val
        return snap

    def load_snapshot(self, data: Dict[str, Any]) -> None:
        """Restore register states from a snapshot dictionary."""
        self.clear()
        for k, v in data.items():
            self.write(k, v)


# ============================================================================
# 3. Variable-to-Register Mapping & AST Preprocessing
# ============================================================================

@dataclass
class VariableBinding:
    """Represents a symbolic IEC variable mapped to a Horner OCS register."""
    variable_name: str
    register_address: RegisterAddress
    data_type: str = "AUTO"  # BOOL, INT, DINT, REAL, etc.


class VariableRegisterMapping:
    """Manages bidirectional mappings between IEC ST variables and Horner registers."""

    def __init__(self) -> None:
        self._var_to_binding: Dict[str, VariableBinding] = {}
        self._reg_to_var: Dict[str, str] = {}

    def bind(
        self,
        var_name: str,
        reg_addr_str: str,
        data_type: str = "AUTO",
    ) -> VariableBinding:
        """Bind an IEC variable name to a Horner register address."""
        addr = parse_register_address(reg_addr_str)
        v_clean = var_name.strip()
        binding = VariableBinding(
            variable_name=v_clean,
            register_address=addr,
            data_type=data_type.upper(),
        )
        self._var_to_binding[v_clean.upper()] = binding
        self._reg_to_var[addr.canonical] = v_clean
        return binding

    def get_binding(self, var_name: str) -> Optional[VariableBinding]:
        """Get binding for variable name (case-insensitive)."""
        return self._var_to_binding.get(var_name.strip().upper())

    def get_var_for_register(self, reg_addr_str: str) -> Optional[str]:
        """Get variable name bound to register address."""
        addr = parse_register_address(reg_addr_str)
        return self._reg_to_var.get(addr.canonical)

    def extract_from_st(self, st_code: str) -> Tuple[str, List[VariableBinding]]:
        """Extracts AT %... address annotations from ST code, binds them,
        and returns sanitized ST code suitable for AST parsers that do not
        natively parse the % token in AT declarations.
        """
        bindings: List[VariableBinding] = []

        # Regex to locate: identifier [spaces] AT [spaces] %... [spaces] : [spaces] TYPE
        pattern = re.compile(
            r"\b([A-Za-z_][A-Za-z0-9_]*)\s+AT\s+(%[A-Za-z]+[0-9]+(?:\.[0-9]+)?)\s*:\s*([A-Za-z_][A-Za-z0-9_]*)",
            re.IGNORECASE,
        )

        for match in pattern.finditer(st_code):
            v_name = match.group(1)
            r_addr = match.group(2)
            d_type = match.group(3)
            binding = self.bind(v_name, r_addr, d_type)
            bindings.append(binding)

        # Sanitize code by stripping 'AT %...' clause so parser sees 'v_name : TYPE'
        sanitized = pattern.sub(r"\1 : \3", st_code)

        # Also support pragma comments like: (* @%R100 *) or // @%I1
        pragma_pattern = re.compile(
            r"([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s*;\s*(?:\(\*|\/\/)\s*@(%[A-Za-z]+[0-9]+(?:\.[0-9]+)?)\s*(?:\*\))?",
            re.IGNORECASE,
        )
        for match in pragma_pattern.finditer(sanitized):
            v_name = match.group(1)
            d_type = match.group(2)
            r_addr = match.group(3)
            binding = self.bind(v_name, r_addr, d_type)
            bindings.append(binding)

        # Auto-bind direct Horner register references in ST logic (e.g. %S1, %S7, %S8, %S9, %R1, %I1, %Q1)
        direct_pattern = re.compile(r"(%[A-Za-z]+[0-9]+(?:\.[0-9]+)?)\b")
        for match in direct_pattern.finditer(sanitized):
            raw_addr = match.group(1)
            try:
                addr = parse_register_address(raw_addr)
                d_type = "BOOL" if addr.is_bit else "INT"
                if addr.canonical not in self._reg_to_var:
                    binding = self.bind(addr.canonical, addr.canonical, d_type)
                    bindings.append(binding)
            except ValueError:
                pass

        return sanitized, bindings

    def sync_registers_to_variables(
        self,
        reg_table: HornerRegisterTable,
        var_dict: Dict[str, Any],
    ) -> None:
        """Synchronizes input, system, and marker register values into the variable context."""
        for v_upper, binding in self._var_to_binding.items():
            addr = binding.register_address
            # Synchronize inputs (%I, %AI), marker bits (%M), temporary bits (%T),
            # general registers (%R), system bits (%S), system registers (%SR), and outputs (%Q, %AQ)
            if addr.reg_type in {
                RegisterType.I,
                RegisterType.AI,
                RegisterType.M,
                RegisterType.T,
                RegisterType.R,
                RegisterType.S,
                RegisterType.SR,
                RegisterType.Q,
                RegisterType.AQ,
            }:
                if binding.data_type == "REAL":
                    var_dict[binding.variable_name] = reg_table.read_real(addr.canonical)
                elif binding.data_type == "DINT":
                    var_dict[binding.variable_name] = reg_table.read_dint(addr.canonical)
                elif addr.is_bit:
                    var_dict[binding.variable_name] = reg_table.read_bit(
                        addr.reg_type, addr.index, addr.bit_offset
                    )
                else:
                    var_dict[binding.variable_name] = reg_table.read_word(
                        addr.reg_type, addr.index, signed=True
                    )

    def sync_variables_to_registers(
        self,
        reg_table: HornerRegisterTable,
        var_dict: Dict[str, Any],
    ) -> None:
        """Synchronizes variables back into the output and general registers."""
        # Build case-insensitive lookup
        lookup = {k.upper(): v for k, v in var_dict.items()}

        for v_upper, binding in self._var_to_binding.items():
            if v_upper in lookup:
                val = lookup[v_upper]
                addr = binding.register_address
                # Prevent user logic from overwriting read-only system bits and system registers
                if addr.reg_type in {RegisterType.S, RegisterType.SR}:
                    continue
                if binding.data_type == "REAL":
                    reg_table.write_real(addr.canonical, float(val))
                elif binding.data_type == "DINT":
                    reg_table.write_dint(addr.canonical, int(val))
                elif addr.is_bit:
                    reg_table.write_bit(addr.reg_type, addr.index, bool(val), addr.bit_offset)
                else:
                    reg_table.write_word(addr.reg_type, addr.index, int(val))


# ============================================================================
# 4. Strict Software Isolation Enforcement
# ============================================================================

def enforce_software_isolation(target_or_config: Any = None) -> None:
    """Enforces 100% pure software isolation with zero physical PLC hardware interaction.

    Validates that:
    1. Simulation-only mode is unconditionally active.
    2. No hardware communication ports (COM1..COM256, CAN, USB, LPT) are specified.
    3. No download, flash, or hardware connect commands or flags are permitted.
    4. Prohibited flashing binaries are never invoked.

    Raises:
        HardwareLockoutError: If any hardware port, protocol, or controller target is attempted.
        UnauthorizedDownloadError: If download or flash operations are detected.
    """
    policy = SafetyPolicy()

    # Verify global invariants
    if not policy.simulation_only:
        raise HardwareLockoutError("Simulation-only mode has been violated.")
    if policy.allow_hardware_communication:
        raise HardwareLockoutError("Physical hardware communication is strictly prohibited.")
    if policy.allow_controller_download:
        raise UnauthorizedDownloadError("Controller download operations are strictly prohibited.")

    if target_or_config is None:
        return

    # If string or path passed, validate against blocked ports, protocols, and commands
    if isinstance(target_or_config, (str, Path)):
        target_str = str(target_or_config).strip()
        lower = target_str.lower()

        # Check blocked hardware communication ports
        for pat in DEFAULT_BLOCKED_PORT_PATTERNS:
            if re.match(pat, target_str, re.IGNORECASE):
                raise HardwareLockoutError(
                    f"Hardware communication port '{target_str}' is strictly blocked by isolation policy."
                )

        # Check blocked protocols
        if lower in DEFAULT_BLOCKED_PROTOCOLS:
            raise HardwareLockoutError(
                f"Physical protocol '{target_str}' is strictly blocked. Only pure software simulation allowed."
            )

        # Check blocked commands & flags
        if (
            lower in SecurityGuard.BLOCKED_COMMANDS
            or lower in DEFAULT_BLOCKED_FLAGS
            or lower in DEFAULT_BLOCKED_DOWNLOAD_FLAGS
            or lower in DEFAULT_BLOCKED_EXECUTABLES
            or any(exe.lower() in lower for exe in DEFAULT_BLOCKED_EXECUTABLES)
        ):
            raise UnauthorizedDownloadError(
                f"Controller command/flag '{target_str}' is prohibited. Only offline simulation permitted."
            )


# ============================================================================
# 5. Cscape Headless UI Automation Controller
# ============================================================================

class CscapeUIAutomationController:
    """Win32 headless UI automation helper for Cscape 10.2 simulator mode.

    Automates toggling simulation mode, stepping cycles, and stopping simulation
    via Win32 messages (WM_COMMAND) with strictly audited command IDs.
    """

    def __init__(self, hwnd: Optional[int] = None) -> None:
        self.hwnd = hwnd

    def trigger_command(self, command_id: Union[int, CscapeCommandID]) -> bool:
        """Sends a Win32 WM_COMMAND message to the Cscape main window."""
        enforce_software_isolation()
        cmd_int = int(command_id)

        # Audit against blocked UI commands (download, upload, hardware connect)
        if cmd_int in DEFAULT_BLOCKED_UI_COMMANDS:
            raise UnauthorizedDownloadError(
                f"UI Command ID {cmd_int} violates security policy and is strictly blocked."
            )

        if not self.hwnd or sys.platform != "win32":
            logger.debug(
                "Emulating Win32 UI command ID %d (0x%04X) in software mode",
                cmd_int,
                cmd_int,
            )
            return True

        try:
            import win32con
            import win32gui
            win32gui.PostMessage(self.hwnd, win32con.WM_COMMAND, cmd_int, 0)
            return True
        except Exception as e:
            logger.warning("Failed to dispatch Win32 WM_COMMAND: %s", e)
            return False

    def start_simulation(self) -> bool:
        """Activate Enhanced IEC Simulation mode (ID_STRATON_RUNTIME_DEBUG_SIMULATION)."""
        return self.trigger_command(CscapeCommandID.START_SIMULATION)

    def stop_simulation(self) -> bool:
        """Stop simulation and monitor mode (ID_STRATON_RUNTIME_DEBUG_STOP)."""
        return self.trigger_command(CscapeCommandID.STOP_DEBUG_SIMULATION)

    def execute_single_cycle(self) -> bool:
        """Execute a single scan cycle (ID_STRATON_RUNTIME_DEBUG_EXECUTESINGLE)."""
        return self.trigger_command(CscapeCommandID.EXECUTE_SINGLE_CYCLE)

    def resume_cycle_mode(self) -> bool:
        """Resume continuous cycle execution (ID_STRATON_RUNTIME_DEBUG_RESUME)."""
        return self.trigger_command(CscapeCommandID.RESUME_CYCLE_MODE)


# ============================================================================
# 6. Simulation Snapshot Data
# ============================================================================

@dataclass
class SimulationSnapshot:
    """Frozen cycle snapshot combining symbolic variables, register table, and timing."""
    cycle: int
    time_ms: float
    dt_ms: float
    variables: Dict[str, Any] = field(default_factory=dict)
    registers: Dict[str, Any] = field(default_factory=dict)
    system_bits: Dict[str, bool] = field(default_factory=dict)

    def get_var(self, name: str, default: Any = None) -> Any:
        """Case-insensitive variable lookup."""
        n_up = name.upper()
        for k, v in self.variables.items():
            if k.upper() == n_up:
                return v
        return default

    def get_register(self, addr: str) -> Any:
        """Register lookup by address string."""
        return self.registers.get(parse_register_address(addr).canonical)


# ============================================================================
# 7. High-Level Cscape Simulator Engine
# ============================================================================

class CscapeSimulator:
    """Comprehensive Pure-Software Simulator for Horner Cscape 10.2 / Straton K5.

    Combines:
    - Pure software isolation with zero physical PLC hardware interaction.
    - Full Horner OCS register space (%R, %AI, %AQ, %I, %Q, %M, %T, %S, %SR).
    - Cyclic execution of IEC 61131-3 Structured Text logic and function blocks.
    - Synchronous and asynchronous cycle stepping, breakpoints, and snapshots.
    - Cscape 10.2 activation commands and pure software cycle execution.
    """

    def __init__(
        self,
        backend: SimulationBackend = SimulationBackend.AUTO,
        default_dt_ms: float = 10.0,
        enforce_isolation: bool = True,
        mode: Optional[str] = None,
    ) -> None:
        if mode and "LIVE" in str(mode).upper():
            raise ValueError(
                "[ERR_VERIFIED_LIVE_PROHIBITED_ON_SIMULATION] Pure-software simulation is strictly "
                "TESTED_MOCK [offline/DEV only]. Claiming or requesting VERIFIED_LIVE on simulation is strictly prohibited."
            )
        self.default_dt_ms = default_dt_ms
        self.enforce_isolation = enforce_isolation

        if self.enforce_isolation:
            enforce_software_isolation()

        # Components
        self.register_table = HornerRegisterTable()
        self.mapping = VariableRegisterMapping()
        self.ui_controller = CscapeUIAutomationController()
        self._st_sim: Optional[STSimulator] = None

        # Simulation Lifecycle
        self.state: SimulationState = SimulationState.IDLE
        self.cycle_count: int = 0
        self.elapsed_time_ms: float = 0.0
        self.history: List[SimulationSnapshot] = []
        self.breakpoints: List[Callable[[CscapeSimulator], bool]] = []
        self._lock = threading.RLock()

        # Backend Selection
        if backend == SimulationBackend.AUTO:
            self.backend = SimulationBackend.EMULATED
        else:
            self.backend = backend

    # --- Safety & Hardware Lockout Enforcers ---

    def connect_hardware(self, port_or_address: str) -> None:
        """Unconditionally blocked: Attempts to connect to physical PLC hardware."""
        enforce_software_isolation(port_or_address)
        raise HardwareLockoutError(
            f"Zero-hardware policy: Connection to physical hardware '{port_or_address}' is prohibited."
        )

    def download_to_controller(self, *args: Any, **kwargs: Any) -> None:
        """Unconditionally blocked: Attempts to download logic or flash hardware."""
        enforce_software_isolation("download")
        raise UnauthorizedDownloadError(
            "Zero-hardware policy: Controller download is strictly prohibited."
        )

    # --- Program & Variable Management ---

    def load_program(
        self,
        st_code: str,
        register_map: Optional[Dict[str, str]] = None,
    ) -> None:
        """Loads and prepares an IEC 61131-3 Structured Text program for simulation.

        Automatically:
        1. Pre-validates pure Structured Text and rejects ladder logic or syntax errors.
        2. Extracts 'AT %...' register bindings from variable declarations.
        3. Applies any additional programmatic register_map bindings.
        4. Sanitizes code and initializes the AST simulation engine.
        5. Synchronizes initial variable values into the register table.
        """
        if self.enforce_isolation:
            enforce_software_isolation()

        # 0. Pre-validate pure Structured Text
        from ..iec.validator import IECValidator
        val_res = IECValidator.validate(st_code)
        if not val_res.get("valid", False):
            errs = val_res.get("errors", [])
            is_ladder = any("ERR_LADDER_FORBIDDEN" in e or "ladder" in e.lower() for e in errs)
            err_code = "ERR_LADDER_FORBIDDEN" if is_ladder else "ST_SYNTAX_ERROR"
            raise ValueError(f"[{err_code}] Simulation POU validation failed: {'; '.join(errs)}")

        # 1. Extract and sanitize AT %... clauses
        sanitized_code, auto_bindings = self.mapping.extract_from_st(st_code)

        # 2. Add explicit bindings from register_map dict
        if register_map:
            for v_name, r_addr in register_map.items():
                self.mapping.bind(v_name, r_addr)

        # 3. Initialize underlying STSimulator
        self._st_sim = STSimulator(default_dt_ms=self.default_dt_ms)
        self._st_sim.load_program(sanitized_code)

        # 4. Synchronize initial values to register table
        self.mapping.sync_variables_to_registers(
            self.register_table, self._st_sim._variables
        )

        self.reset()

    def bind_variable(self, var_name: str, reg_addr: str, data_type: str = "AUTO") -> None:
        """Programmatically bind a variable name to a Horner register address."""
        self.mapping.bind(var_name, reg_addr, data_type)
        if self._st_sim and (var_name in self._st_sim._variables or var_name.upper() in self._st_sim._variables):
            self.mapping.sync_variables_to_registers(
                self.register_table, self._st_sim._variables
            )

    # --- Simulation Controls ---

    def start_simulation(self) -> None:
        """Start the simulation session (transitions IDLE/STOPPED -> RUNNING)."""
        if self.enforce_isolation:
            enforce_software_isolation()
        self.ui_controller.start_simulation()
        self.state = SimulationState.RUNNING

    def stop_simulation(self) -> None:
        """Stop the simulation session (transitions -> STOPPED)."""
        self.ui_controller.stop_simulation()
        self.state = SimulationState.STOPPED

    def pause_simulation(self) -> None:
        """Pause simulation execution."""
        self.state = SimulationState.PAUSED

    def resume_simulation(self) -> None:
        """Resume simulation execution from paused state."""
        if self.enforce_isolation:
            enforce_software_isolation()
        self.ui_controller.resume_cycle_mode()
        self.state = SimulationState.RUNNING

    def reset(self) -> None:
        """Reset simulation state, cycle counts, elapsed time, and register table."""
        with self._lock:
            self.state = SimulationState.IDLE
            self.cycle_count = 0
            self.elapsed_time_ms = 0.0
            self.history.clear()
            self.register_table.clear()
            if self._st_sim:
                self._st_sim._initialize_declarations()
                self.mapping.sync_variables_to_registers(
                    self.register_table, self._st_sim._variables
                )

    # --- Cycle Execution ---

    def step_cycle(
        self,
        dt_ms: Optional[float] = None,
        inputs: Optional[Dict[str, Any]] = None,
        register_writes: Optional[Dict[str, Any]] = None,
    ) -> SimulationSnapshot:
        """Executes exactly one discrete scan cycle.

        Execution Order (IEC 61131-3 + Horner OCS):
        1. Apply external register writes and variable inputs.
        2. Update Horner system bits (%S1, %S7, %S8, %S9) and system registers (%SR1..%SR4).
        3. Synchronize input registers (%I, %AI) into variable context.
        4. Execute logic for one cycle (via STSimulator AST evaluation).
        5. Synchronize output variables back into registers (%Q, %AQ, %R, %M).
        6. Capture and record SimulationSnapshot.
        """
        if self.enforce_isolation:
            enforce_software_isolation()

        with self._lock:
            step_dt = dt_ms if dt_ms is not None else self.default_dt_ms

            if self.state == SimulationState.IDLE:
                self.state = SimulationState.RUNNING

            # 1. Apply user inputs directly to register table
            if register_writes:
                for addr_str, val in register_writes.items():
                    self.register_table.write(addr_str, val)

            # 2. Update Horner System Bits & Registers for this cycle
            self.register_table.update_system_registers(
                cycle_index=self.cycle_count,
                dt_ms=step_dt,
                elapsed_time_ms=self.elapsed_time_ms,
            )

            # 3. Synchronize input registers into ST simulator variables
            curr_vars: Dict[str, Any] = {}
            if self._st_sim:
                curr_vars = dict(self._st_sim._variables)
                self.mapping.sync_registers_to_variables(self.register_table, curr_vars)
                if inputs:
                    curr_vars.update(inputs)

                for var_name, var_val in curr_vars.items():
                    self._st_sim.set_variable(var_name, var_val)

                # 4. Execute logic via STSimulator
                st_snap = self._st_sim.step(dt_ms=step_dt)
                curr_vars = st_snap.variables

                # 5. Synchronize output variables back into register table
                self.mapping.sync_variables_to_registers(self.register_table, curr_vars)
            else:
                # Pure register mode (no ST code loaded)
                if inputs:
                    for k, v in inputs.items():
                        if k.startswith("%"):
                            self.register_table.write(k, v)
                        else:
                            curr_vars[k] = v

            # Collect system bits for snapshot
            sys_bits = {
                "%S1": self.register_table.read_bit(RegisterType.S, 1),
                "%S7": self.register_table.read_bit(RegisterType.S, 7),
                "%S8": self.register_table.read_bit(RegisterType.S, 8),
                "%S9": self.register_table.read_bit(RegisterType.S, 9),
            }

            # 6. Capture cycle snapshot
            snapshot = SimulationSnapshot(
                cycle=self.cycle_count,
                time_ms=self.elapsed_time_ms,
                dt_ms=step_dt,
                variables=dict(curr_vars),
                registers=self.register_table.snapshot(),
                system_bits=sys_bits,
            )
            self.history.append(snapshot)

            # Advance simulation clocks
            self.cycle_count += 1
            self.elapsed_time_ms += step_dt

            # Check breakpoints
            for bp in self.breakpoints:
                if bp(self):
                    self.state = SimulationState.PAUSED
                    logger.info("Breakpoint hit at cycle %d", self.cycle_count - 1)
                    break

            return snapshot

    # Alias for convenience / compatibility
    step = step_cycle

    def run_cycles(
        self,
        cycles: int = 10,
        dt_ms: Optional[float] = None,
        input_vectors: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> List[SimulationSnapshot]:
        """Runs multiple consecutive simulation cycles."""
        results: List[SimulationSnapshot] = []
        for i in range(cycles):
            inp = None
            if input_vectors and i < len(input_vectors):
                inp = input_vectors[i]
            snap = self.step_cycle(dt_ms=dt_ms, inputs=inp)
            results.append(snap)
            if self.state == SimulationState.PAUSED:
                break
        return results

    def run_until(
        self,
        condition: Callable[[CscapeSimulator], bool],
        max_cycles: int = 1000,
        dt_ms: Optional[float] = None,
    ) -> SimulationSnapshot:
        """Executes cycles until the specified condition returns True or max_cycles is reached."""
        for _ in range(max_cycles):
            snap = self.step_cycle(dt_ms=dt_ms)
            if condition(self):
                return snap
        raise SimulationError(
            f"run_until condition not satisfied after {max_cycles} cycles",
            cycle=self.cycle_count,
            time_ms=self.elapsed_time_ms,
        )

    # --- Breakpoint Management ---

    def add_breakpoint(self, condition: Callable[[CscapeSimulator], bool]) -> None:
        """Registers a breakpoint callback checked after every cycle."""
        self.breakpoints.append(condition)

    def clear_breakpoints(self) -> None:
        """Removes all registered breakpoints."""
        self.breakpoints.clear()

    # --- Register & Variable Access Facades ---

    def read_register(self, address_str: str) -> Union[int, bool]:
        """Read 16-bit register or boolean bit from address (e.g. '%R100', '%I1')."""
        with self._lock:
            return self.register_table.read(address_str)

    def write_register(self, address_str: str, value: Union[int, bool, float]) -> None:
        """Write value into register address (e.g. '%R100', '%I1')."""
        with self._lock:
            self.register_table.write(address_str, value)
            # If bound to an IEC variable, propagate immediately
            bound_var = self.mapping.get_var_for_register(address_str)
            if bound_var and self._st_sim:
                self._st_sim.set_variable(bound_var, value)

    def read_bit(self, address_str: str) -> bool:
        """Read a boolean bit (e.g. '%I1', '%Q1', '%M1', '%R100.0')."""
        with self._lock:
            addr = parse_register_address(address_str)
            return self.register_table.read_bit(addr.reg_type, addr.index, addr.bit_offset)

    def write_bit(self, address_str: str, value: bool) -> None:
        """Write a boolean bit (e.g. '%I1', '%Q1', '%M1', '%R100.0')."""
        with self._lock:
            addr = parse_register_address(address_str)
            self.register_table.write_bit(addr.reg_type, addr.index, bool(value), addr.bit_offset)
            bound_var = self.mapping.get_var_for_register(address_str)
            if bound_var and self._st_sim:
                self._st_sim.set_variable(bound_var, bool(value))

    def read_real(self, address_str: str) -> float:
        """Read a 32-bit REAL float across two word registers."""
        with self._lock:
            return self.register_table.read_real(address_str)

    def write_real(self, address_str: str, value: float) -> None:
        """Write a 32-bit REAL float across two word registers."""
        with self._lock:
            self.register_table.write_real(address_str, value)
            bound_var = self.mapping.get_var_for_register(address_str)
            if bound_var and self._st_sim:
                self._st_sim.set_variable(bound_var, float(value))

    def read_dint(self, address_str: str) -> int:
        """Read a 32-bit signed DINT integer across two word registers."""
        with self._lock:
            return self.register_table.read_dint(address_str)

    def write_dint(self, address_str: str, value: int) -> None:
        """Write a 32-bit signed DINT integer across two word registers."""
        with self._lock:
            self.register_table.write_dint(address_str, value)
            bound_var = self.mapping.get_var_for_register(address_str)
            if bound_var and self._st_sim:
                self._st_sim.set_variable(bound_var, int(value))

    def read_variable(self, name: str) -> Any:
        """Read symbolic variable value from simulation context."""
        with self._lock:
            if self._st_sim:
                return self._st_sim.get_variable(name)
            raise KeyError(f"No ST program loaded to read variable '{name}'")

    def write_variable(self, name: str, value: Any) -> None:
        """Write symbolic variable value into simulation context."""
        with self._lock:
            if self._st_sim:
                self._st_sim.set_variable(name, value)
                binding = self.mapping.get_binding(name)
                if binding:
                    self.mapping.sync_variables_to_registers(
                        self.register_table, {name: value}
                    )
            else:
                raise KeyError(f"No ST program loaded to write variable '{name}'")

    # --- Diagnostics & Status ---

    def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive diagnostic status of the simulation session."""
        return {
            "state": self.state.value,
            "backend": self.backend.value,
            "classification": CLASSIFICATION,
            "verification_classification": VERIFICATION_CLASSIFICATION,
            "cycle_count": self.cycle_count,
            "elapsed_time_ms": self.elapsed_time_ms,
            "default_dt_ms": self.default_dt_ms,
            "software_isolation_enforced": self.enforce_isolation,
            "has_program_loaded": self._st_sim is not None,
            "bound_variables_count": len(self.mapping._var_to_binding),
            "pure_software_execution": True,
            "system_clocks": {
                "%S1": self.register_table.read_bit(RegisterType.S, 1),
                "%S7": self.register_table.read_bit(RegisterType.S, 7),
                "%S8": self.register_table.read_bit(RegisterType.S, 8),
                "%S9": self.register_table.read_bit(RegisterType.S, 9),
            },
            "cscape_ui_commands": {
                "start_simulation_id": CscapeCommandID.START_SIMULATION,
                "stop_simulation_id": CscapeCommandID.STOP_DEBUG_SIMULATION,
                "execute_single_cycle_id": CscapeCommandID.EXECUTE_SINGLE_CYCLE,
                "resume_cycle_mode_id": CscapeCommandID.RESUME_CYCLE_MODE,
            },
        }

    def get_trace(self) -> List[SimulationSnapshot]:
        """Returns recorded execution snapshots."""
        return list(self.history)


# ============================================================================
# 8. Top-Level Facade Functions
# ============================================================================

def create_cscape_simulation(
    st_code: Optional[str] = None,
    register_map: Optional[Dict[str, str]] = None,
    backend: SimulationBackend = SimulationBackend.AUTO,
    default_dt_ms: float = 10.0,
    enforce_isolation: bool = True,
) -> CscapeSimulator:
    """Factory helper to create and optionally initialize a CscapeSimulator instance."""
    sim = CscapeSimulator(
        backend=backend,
        default_dt_ms=default_dt_ms,
        enforce_isolation=enforce_isolation,
    )
    if st_code is not None:
        sim.load_program(st_code=st_code, register_map=register_map)
    return sim


def simulate_pou_with_registers(
    st_code: str,
    inputs: Dict[str, Any],
    steps: int = 5,
    register_map: Optional[Dict[str, str]] = None,
    dt_ms: float = 10.0,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Simulates Structured Text POU execution with register synchronization.

    Guarantees 100% software isolation with zero physical PLC hardware interaction.
    """
    if mode and "LIVE" in str(mode).upper():
        raise ValueError(
            "[ERR_VERIFIED_LIVE_PROHIBITED_ON_SIMULATION] Pure-software simulation is strictly "
            "TESTED_MOCK [offline/DEV only]. Claiming or requesting VERIFIED_LIVE on simulation is strictly prohibited."
        )

    enforce_software_isolation()

    # Pre-validate pure Structured Text and reject ladder artifacts fail-closed
    from ..iec.validator import IECValidator
    val_res = IECValidator.validate(st_code)
    if not val_res.get("valid", False):
        errs = val_res.get("errors", [])
        is_ladder = any("ERR_LADDER_FORBIDDEN" in e or "ladder" in e.lower() for e in errs)
        err_code = "ERR_LADDER_FORBIDDEN" if is_ladder else "ST_SYNTAX_ERROR"
        raise ValueError(f"[{err_code}] Simulation POU validation failed: {'; '.join(errs)}")

    sim = create_cscape_simulation(
        st_code=st_code,
        register_map=register_map,
        default_dt_ms=dt_ms,
        enforce_isolation=True,
    )
    sim.start_simulation()

    trace_records: List[Dict[str, Any]] = []
    for step_i in range(steps):
        # Allow step inputs to be lists or scalar values
        step_in: Dict[str, Any] = {}
        for k, v in inputs.items():
            if isinstance(v, (list, tuple)):
                step_in[k] = v[step_i] if step_i < len(v) else v[-1]
            else:
                step_in[k] = v

        snap = sim.step_cycle(inputs=step_in)
        trace_records.append({
            "cycle": snap.cycle,
            "time_ms": snap.time_ms,
            "variables": snap.variables,
            "registers": snap.registers,
            "system_bits": snap.system_bits,
        })

    last_snap = sim.history[-1] if sim.history else None
    return {
        "success": True,
        "classification": CLASSIFICATION,
        "verification_classification": VERIFICATION_CLASSIFICATION,
        "total_cycles": sim.cycle_count,
        "elapsed_time_ms": sim.elapsed_time_ms,
        "final_variables": last_snap.variables if last_snap else {},
        "final_registers": last_snap.registers if last_snap else {},
        "trace": trace_records,
        "isolation_enforced": True,
    }
