"""Cscape Variable and Tag Database Management.

Provides comprehensive variable management for Horner APG Cscape 10.2:
- Horner OCS register addressing (%R, %M, %T, %AI, %AQ, %I, %Q, %S, %SR, %D, %K, %IG, %QG, etc.)
- Bit-of-word indexing (%R1.1-%R1.16, %SR43.1)
- Contiguous register footprint and overlap/conflict detection
- Automatic register allocator for unassigned tags
- Bidirectional Cscape XML parser and serializer (<ProjectVariables>)
- Bidirectional Cscape CSV parser and serializer (semicolon and comma delimited)
- IEC 61131-3 text variable declaration parser/serializer with (*$tag=...*) directives
- High-level VariableManager / TagDatabase with project synchronization
"""

from __future__ import annotations

import csv
import io
import math
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set, Tuple, Union


# ---------------------------------------------------------------------------
# Horner OCS Register Addressing Architecture
# ---------------------------------------------------------------------------

class RegisterType(str, Enum):
    """Horner OCS and standard IEC memory register types."""
    R = "%R"       # Retentive 16-bit register (general purpose)
    M = "%M"       # Retentive internal bit
    T = "%T"       # Temporary / non-retentive bit
    I = "%I"       # Discrete / digital hardware input bit
    Q = "%Q"       # Discrete / digital hardware output bit
    AI = "%AI"     # Analog 16-bit input register
    AQ = "%AQ"     # Analog 16-bit output register
    D = "%D"       # Display bit (screen trigger)
    K = "%K"       # Key bit (function keypad)
    S = "%S"       # System status bit (read-only for most bits)
    SR = "%SR"     # System register 16-bit (clock, status, network)
    IG = "%IG"     # Global network discrete input bit (CsCAN)
    QG = "%QG"     # Global network discrete output bit (CsCAN)
    AIG = "%AIG"   # Global network analog input register (CsCAN)
    AQG = "%AQG"   # Global network analog output register (CsCAN)

    # Standard IEC 61131-3 address prefixes
    IX = "%IX"     # IEC input bit
    QX = "%QX"     # IEC output bit
    MX = "%MX"     # IEC memory bit
    IW = "%IW"     # IEC input word
    QW = "%QW"     # IEC output word
    MW = "%MW"     # IEC memory word
    ID = "%ID"     # IEC input double-word
    QD = "%QD"     # IEC output double-word
    MD = "%MD"     # IEC memory double-word


# Register type characteristics
BIT_REGISTERS: Set[str] = {
    "%M", "%T", "%I", "%Q", "%D", "%K", "%S", "%IG", "%QG",
    "%IX", "%QX", "%MX"
}

WORD_REGISTERS: Set[str] = {
    "%R", "%AI", "%AQ", "%SR", "%AIG", "%AQG",
    "%IW", "%QW", "%MW"
}

DWORD_REGISTERS: Set[str] = {
    "%ID", "%QD", "%MD"
}

READ_ONLY_REGISTERS: Set[str] = {
    "%I", "%AI", "%S", "%SR", "%IG", "%AIG",
    "%IX", "%IW", "%ID"
}

RETENTIVE_REGISTERS: Set[str] = {
    "%R", "%M", "%SR", "%MW", "%MD"
}

# Standard word footprint per IEC data type
IEC_TYPE_WORD_SIZE: Dict[str, int] = {
    "BOOL": 1,        # 1 bit in bit register, or 1 word in word register
    "BYTE": 1,        # 8-bit
    "SINT": 1,        # 8-bit signed
    "USINT": 1,       # 8-bit unsigned
    "INT": 1,         # 16-bit signed
    "UINT": 1,        # 16-bit unsigned
    "WORD": 1,        # 16-bit bitstring
    "DINT": 2,        # 32-bit signed (2 words)
    "UDINT": 2,       # 32-bit unsigned (2 words)
    "DWORD": 2,       # 32-bit bitstring (2 words)
    "REAL": 2,        # 32-bit IEEE float (2 words)
    "TIME": 2,        # 32-bit duration (2 words)
    "LINT": 4,        # 64-bit signed (4 words)
    "ULINT": 4,       # 64-bit unsigned (4 words)
    "LWORD": 4,       # 64-bit bitstring (4 words)
    "LREAL": 4,       # 64-bit IEEE double (4 words)
    "DATE": 2,        # 32-bit
    "TOD": 2,         # 32-bit
    "DT": 2,          # 32-bit
}

# Standard supported IEC 61131-3 and Horner data types
SUPPORTED_DATA_TYPES: Set[str] = set(IEC_TYPE_WORD_SIZE.keys()) | {"STRING"}

# Standard index ranges for Horner OCS controller registers
HORNER_REGISTER_LIMITS: Dict[str, Tuple[int, int]] = {
    "%R": (1, 9999),      # Retentive 16-bit general holding registers
    "%M": (1, 2048),      # Retentive internal bits
    "%T": (1, 2048),      # Temporary non-retentive bits
    "%I": (1, 2048),      # Discrete digital inputs
    "%Q": (1, 2048),      # Discrete digital outputs
    "%AI": (1, 512),      # Analog inputs (16-bit)
    "%AQ": (1, 512),      # Analog outputs (16-bit)
    "%D": (1, 1024),      # Display bits
    "%K": (1, 1024),      # Keypad bits
    "%S": (1, 128),       # System status bits
    "%SR": (1, 256),      # System registers (16-bit)
    "%IG": (1, 2048),     # Global network discrete inputs (CsCAN)
    "%QG": (1, 2048),     # Global network discrete outputs (CsCAN)
    "%AIG": (1, 2048),    # Global network analog inputs (CsCAN)
    "%AQG": (1, 2048),    # Global network analog outputs (CsCAN)
    "%IX": (0, 65535),    # IEC input bits
    "%QX": (0, 65535),    # IEC output bits
    "%MX": (0, 65535),    # IEC memory bits
    "%IW": (0, 65535),    # IEC input words
    "%QW": (0, 65535),    # IEC output words
    "%MW": (0, 65535),    # IEC memory words
    "%ID": (0, 65535),    # IEC input double-words
    "%QD": (0, 65535),    # IEC output double-words
    "%MD": (0, 65535),    # IEC memory double-words
}

# Regex pattern for Horner OCS addresses
# Matches: %R100, %m5, %SR043.1, %R100.16, %AI1, %AQ2, %AIG10, %IX1.0, %MW50
REGISTER_PATTERN = re.compile(
    r"^%(?P<prefix>AIG|AQG|IG|QG|AI|AQ|SR|IX|QX|MX|IW|QW|MW|ID|QD|MD|R|M|T|I|Q|D|K|S)"
    r"(?P<index>\d+)"
    r"(?:\.(?P<bit>\d+))?$",
    re.IGNORECASE
)


@dataclass(frozen=True)
class HornerRegister:
    """Represents a validated Horner OCS register or standard IEC memory address."""
    prefix: str
    index: int
    bit_offset: Optional[int] = None
    raw: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "prefix", self.prefix.upper())
        if not self.raw:
            norm = f"{self.prefix}{self.index}"
            if self.bit_offset is not None:
                norm += f".{self.bit_offset}"
            object.__setattr__(self, "raw", norm)

    @classmethod
    def parse(cls, addr_str: str) -> HornerRegister:
        """Parses and validates a Horner OCS register string.

        Args:
            addr_str: Address string, e.g. '%R100', '%m1', '%SR043.1', '%AI5'.

        Returns:
            Validated HornerRegister instance.

        Raises:
            ValueError: If the address syntax or bounds are invalid.
        """
        if not addr_str or not isinstance(addr_str, str):
            raise ValueError(f"Invalid register address: {addr_str!r} (must be a non-empty string)")

        cleaned = addr_str.strip()
        if not cleaned.startswith("%"):
            cleaned = "%" + cleaned

        match = REGISTER_PATTERN.match(cleaned)
        if not match:
            raise ValueError(
                f"Invalid Horner OCS register format: '{addr_str}'. "
                f"Expected format: %<Type><Index>[.<Bit>], e.g. %R100, %M1, %SR43.1, %AI5"
            )

        prefix = "%" + match.group("prefix").upper()
        index = int(match.group("index"))

        if prefix in HORNER_REGISTER_LIMITS:
            min_idx, max_idx = HORNER_REGISTER_LIMITS[prefix]
            if not (min_idx <= index <= max_idx):
                raise ValueError(
                    f"Register index {index} out of bounds for {prefix} (valid: {min_idx}..{max_idx}) in '{addr_str}'"
                )
        elif index < 1 and prefix not in {"%IX", "%QX", "%MX", "%IW", "%QW", "%MW"}:
            raise ValueError(f"Register index must be >= 1, got: {index} in '{addr_str}'")

        bit_val: Optional[int] = None
        if match.group("bit") is not None:
            bit_val = int(match.group("bit"))
            if prefix in BIT_REGISTERS:
                raise ValueError(
                    f"Bit offset not allowed on discrete bit register '{prefix}' in '{addr_str}'"
                )
            # Horner bit of word is typically 1..16 or 0..15 (both within 0..16)
            if not (0 <= bit_val <= 16):
                raise ValueError(
                    f"Bit offset in register '{addr_str}' out of range (0..16): {bit_val}"
                )

        return cls(prefix=prefix, index=index, bit_offset=bit_val, raw=cleaned)

    @classmethod
    def is_valid(cls, addr_str: str) -> bool:
        """Checks if a string represents a valid Horner OCS register without raising exceptions."""
        try:
            cls.parse(addr_str)
            return True
        except (ValueError, TypeError):
            return False

    @classmethod
    def normalize(cls, addr_str: str, pad_zeros: int = 0) -> str:
        """Normalizes a register string into standard canonical format.

        Args:
            addr_str: Raw register address.
            pad_zeros: Optional zero-padding length for the index (e.g. 3 -> %S001).

        Returns:
            Normalized uppercase string.
        """
        reg = cls.parse(addr_str)
        idx_str = f"{reg.index:0{pad_zeros}d}" if pad_zeros > 0 else str(reg.index)
        res = f"{reg.prefix}{idx_str}"
        if reg.bit_offset is not None:
            res += f".{reg.bit_offset}"
        return res

    @property
    def is_bit(self) -> bool:
        """True if this address represents a single bit (either native bit register or bit-of-word)."""
        return self.bit_offset is not None or self.prefix in BIT_REGISTERS

    @property
    def is_word(self) -> bool:
        """True if this address addresses a 16-bit word register."""
        return self.bit_offset is None and self.prefix in WORD_REGISTERS

    @property
    def is_read_only(self) -> bool:
        """True if this register is generally read-only hardware or system telemetry."""
        return self.prefix in READ_ONLY_REGISTERS

    def is_within_bounds(self) -> bool:
        """Returns True if this register's index is within valid controller bounds."""
        if self.prefix in HORNER_REGISTER_LIMITS:
            min_idx, max_idx = HORNER_REGISTER_LIMITS[self.prefix]
            return min_idx <= self.index <= max_idx
        return self.index >= 1

    def spans_within_bounds(self, data_type: str = "INT") -> bool:
        """Returns True if the memory footprint of data_type starting at this register fits within bounds."""
        if not self.is_within_bounds():
            return False
        word_span = IEC_TYPE_WORD_SIZE.get(data_type.upper(), 1)
        if self.prefix in HORNER_REGISTER_LIMITS and word_span > 1:
            min_idx, max_idx = HORNER_REGISTER_LIMITS[self.prefix]
            end_idx = self.index + word_span - 1
            return end_idx <= max_idx
        return True


    @property
    def is_retentive(self) -> bool:
        """True if register retains its value through controller power cycle."""
        return self.prefix in RETENTIVE_REGISTERS

    @property
    def is_system(self) -> bool:
        """True if register is a Horner system register or system bit."""
        return self.prefix in {"%S", "%SR"}

    @property
    def is_analog(self) -> bool:
        """True if register is an analog input/output register."""
        return self.prefix in {"%AI", "%AQ", "%AIG", "%AQG"}

    def get_word_span(
        self,
        data_type: str,
        string_len: Optional[int] = None,
        dim_count: int = 1,
    ) -> int:
        """Calculates total 16-bit words spanned by this register assignment.

        Args:
            data_type: IEC data type (e.g. BOOL, INT, REAL, STRING).
            string_len: Maximum length for STRING variables.
            dim_count: Total array elements count.

        Returns:
            Number of consecutive 16-bit words spanned.
        """
        if self.is_bit:
            return 1

        dt = data_type.strip().upper()
        if dt == "STRING":
            length = string_len if string_len and string_len > 0 else 80
            # Horner stores 2 ASCII characters per 16-bit word + null terminator
            words_per_str = math.ceil((length + 1) / 2)
            return words_per_str * max(1, dim_count)

        words_per_elem = IEC_TYPE_WORD_SIZE.get(dt, 1)
        return words_per_elem * max(1, dim_count)

    def get_occupied_registers(
        self,
        data_type: str,
        string_len: Optional[int] = None,
        dim_count: int = 1,
    ) -> List[str]:
        """Returns the list of all individual canonical register strings occupied by this variable."""
        if self.is_bit:
            return [self.raw.upper()]

        span = self.get_word_span(data_type, string_len, dim_count)
        return [f"{self.prefix}{self.index + i}" for i in range(span)]

    def overlaps_with(
        self,
        other: HornerRegister,
        self_type: str = "INT",
        other_type: str = "INT",
        self_len: Optional[int] = None,
        other_len: Optional[int] = None,
        self_dims: int = 1,
        other_dims: int = 1,
    ) -> bool:
        """Checks if two register allocations collide or overlap in controller memory."""
        if self.prefix != other.prefix:
            return False

        # If both are bit addresses
        if self.is_bit and other.is_bit:
            if self.index != other.index:
                return False
            return self.bit_offset == other.bit_offset

        # If one is bit-of-word and the other is word on the same index
        if self.is_bit and other.is_word:
            other_span = other.get_word_span(other_type, other_len, other_dims)
            return other.index <= self.index < (other.index + other_span)

        if self.is_word and other.is_bit:
            self_span = self.get_word_span(self_type, self_len, self_dims)
            return self.index <= other.index < (self.index + self_span)

        # Both are word registers: check index intervals
        self_span = self.get_word_span(self_type, self_len, self_dims)
        other_span = other.get_word_span(other_type, other_len, other_dims)

        self_end = self.index + self_span - 1
        other_end = other.index + other_span - 1

        return not (self_end < other.index or other_end < self.index)


# ---------------------------------------------------------------------------
# Cscape Variable / Tag Data Model
# ---------------------------------------------------------------------------

@dataclass
class CscapeVariable:
    """Represents a Cscape variable / tag entry."""
    name: str
    data_type: str
    scope: str = "globals"
    tag: Optional[str] = None
    description: Optional[str] = None
    usergroup: Optional[str] = None
    initial_value: Optional[str] = None
    string_length: Optional[int] = None
    dimensions: Optional[str] = None
    attributes: List[str] = field(default_factory=list)
    read_only: bool = False

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        self.data_type = self.data_type.strip().upper()
        self.scope = self.scope.strip().lower()

        if self.tag:
            self.tag = self.tag.strip()
            if not self.tag.startswith("%"):
                self.tag = "%" + self.tag

        if self.description is not None:
            self.description = self.description.strip()
        if self.usergroup is not None:
            self.usergroup = self.usergroup.strip()
        if self.initial_value is not None:
            self.initial_value = self.initial_value.strip()

        # Handle STRING length inference if embedded in data_type e.g. STRING(80)
        str_match = re.match(r"^STRING\s*\(\s*(\d+)\s*\)$", self.data_type, re.IGNORECASE)
        if str_match:
            self.data_type = "STRING"
            if not self.string_length:
                self.string_length = int(str_match.group(1))

        # Check attributes for constant/RO
        attr_upper = [a.strip().upper() for a in self.attributes]
        if "CONSTANT" in attr_upper or "READ ONLY" in attr_upper or "READONLY" in attr_upper:
            self.read_only = True
        elif self.read_only:
            self.attributes.append("constant")

    @property
    def register(self) -> Optional[HornerRegister]:
        """Parsed HornerRegister instance if tag is assigned, else None."""
        if not self.tag:
            return None
        try:
            return HornerRegister.parse(self.tag)
        except Exception:
            return None

    @property
    def is_array(self) -> bool:
        """True if variable has dimension(s)."""
        return bool(self.dimensions and self.dimensions.strip() and self.dimensions.strip() != "1")

    @property
    def array_element_count(self) -> int:
        """Calculates total element count across all dimensions."""
        if not self.is_array or not self.dimensions:
            return 1
        parts = [p.strip() for p in self.dimensions.split(",") if p.strip()]
        total = 1
        for p in parts:
            if ".." in p:
                low_s, high_s = p.split("..", 1)
                try:
                    low = int(low_s.strip())
                    high = int(high_s.strip())
                    total *= max(1, high - low + 1)
                except ValueError:
                    total *= 1
            else:
                try:
                    total *= max(1, int(p))
                except ValueError:
                    total *= 1
        return total

    def occupied_registers(self) -> List[str]:
        """Returns all individual register addresses spanned by this variable."""
        reg = self.register
        if not reg:
            return []
        return reg.get_occupied_registers(
            data_type=self.data_type,
            string_len=self.string_length,
            dim_count=self.array_element_count,
        )

    def validate(self) -> List[str]:
        """Validates variable according to Cscape rules."""
        errors: List[str] = []
        if not self.name:
            errors.append("Variable name cannot be empty.")
            return errors

        # Name syntax: begins with letter or underscore, no consecutive underscores
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", self.name):
            errors.append(
                f"Variable name '{self.name}' has invalid characters. Must start with a letter "
                f"or underscore and contain only alphanumeric characters or underscores."
            )
        if "__" in self.name:
            errors.append(f"Variable name '{self.name}' contains consecutive underscores ('__').")

        # Data type check
        if not self.data_type:
            errors.append(f"Variable '{self.name}' has no data type specified.")
        elif self.data_type not in SUPPORTED_DATA_TYPES and not self.data_type.startswith("ARRAY"):
            errors.append(f"Variable '{self.name}' has unsupported data type: '{self.data_type}'.")

        # Tag validation
        if self.tag:
            if not HornerRegister.is_valid(self.tag):
                errors.append(f"Variable '{self.name}' has invalid register tag: '{self.tag}'.")
            elif self.register:
                reg = self.register
                if reg.is_bit and self.data_type not in ("BOOL",):
                    errors.append(
                        f"Variable '{self.name}' data type '{self.data_type}' is incompatible with 1-bit register '{self.tag}'. Expected BOOL."
                    )
                elif reg.is_word:
                    if reg.prefix in HORNER_REGISTER_LIMITS:
                        max_bound = HORNER_REGISTER_LIMITS[reg.prefix][1]
                        span = reg.get_word_span(self.data_type, self.string_length, self.array_element_count)
                        last_idx = reg.index + span - 1
                        if last_idx > max_bound:
                            errors.append(
                                f"Variable '{self.name}' ({self.data_type}) spans registers up to {reg.prefix}{last_idx}, "
                                f"exceeding max limit of {max_bound}."
                            )

        # STRING length check
        if self.data_type == "STRING":
            if self.string_length is not None and not (1 <= self.string_length <= 255):
                errors.append(
                    f"STRING variable '{self.name}' length {self.string_length} out of range (1..255)."
                )

        return errors

    def to_dict(self) -> Dict[str, Any]:
        """Serializes variable to dictionary."""
        return {
            "name": self.name,
            "data_type": self.data_type,
            "scope": self.scope,
            "tag": self.tag,
            "description": self.description or "",
            "usergroup": self.usergroup or "",
            "initial_value": self.initial_value or "",
            "string_length": self.string_length,
            "dimensions": self.dimensions or "",
            "attributes": list(self.attributes),
            "read_only": self.read_only,
            "is_array": self.is_array,
            "occupied_registers": self.occupied_registers(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CscapeVariable:
        """Constructs a CscapeVariable from a dictionary."""
        return cls(
            name=data.get("name", ""),
            data_type=data.get("data_type", "INT"),
            scope=data.get("scope", "globals"),
            tag=data.get("tag") or data.get("address") or None,
            description=data.get("description") or None,
            usergroup=data.get("usergroup") or None,
            initial_value=data.get("initial_value") or None,
            string_length=data.get("string_length"),
            dimensions=data.get("dimensions") or None,
            attributes=data.get("attributes") or [],
            read_only=bool(data.get("read_only", False)),
        )

    def to_iec_declaration(self, indent: str = "    ") -> str:
        """Formats variable declaration for IEC 61131-3 text mode with Cscape directives."""
        prefix = "CONSTANT " if self.read_only else ""
        type_str = self.data_type
        if self.data_type == "STRING" and self.string_length:
            type_str = f"STRING({self.string_length})"
        elif self.is_array and self.dimensions:
            type_str = f"ARRAY [{self.dimensions}] OF {self.data_type}"

        decl = f"{indent}{prefix}{self.name} : {type_str}"
        if self.initial_value:
            decl += f" := {self.initial_value}"
        decl += ";"

        directives: List[str] = []
        if self.tag:
            directives.append(f"(*$tag={self.tag}*)")
        if self.description:
            directives.append(f"(*$desc={self.description}*)")

        if directives:
            decl += " " + " ".join(directives)

        return decl


# ---------------------------------------------------------------------------
# Bidirectional Cscape XML Parser & Serializer
# ---------------------------------------------------------------------------

def _matches_target_scopes(v: CscapeVariable, target_scopes: Optional[Set[str]]) -> bool:
    """Checks if variable matches any of the target scopes (supporting named and register scopes %R, %M, etc.)."""
    if not target_scopes:
        return True

    # 1. Direct scope check
    v_scope = v.scope.strip().lower()
    if v_scope in target_scopes or v_scope.lstrip("%") in target_scopes or f"%{v_scope.lstrip('%')}" in target_scopes:
        return True

    # 2. Register prefix check (%R, %M, %AI, %AQ, %I, %Q, %S, %SR, etc.)
    reg = v.register
    if reg:
        pfx = reg.prefix.strip().lower()
        if pfx in target_scopes or pfx.lstrip("%") in target_scopes or f"%{pfx.lstrip('%')}" in target_scopes:
            return True
    elif v.tag and v.tag.startswith("%"):
        match = re.match(r"^%[a-zA-Z]+", v.tag)
        if match:
            pfx = match.group(0).lower()
            if pfx in target_scopes or pfx.lstrip("%") in target_scopes or f"%{pfx.lstrip('%')}" in target_scopes:
                return True

    return False


class CscapeXMLSerializer:
    """Serializes Cscape variable database into official Cscape 10.2 XML exchange format."""

    @classmethod
    def serialize(
        cls,
        variables: Sequence[CscapeVariable],
        root_tag: str = "ProjectVariables",
        version: str = "1.0",
        scopes: Optional[Sequence[str]] = None,
    ) -> str:
        """Generates standard Cscape XML string.

        Args:
            variables: Sequence of CscapeVariable objects.
            root_tag: XML root element name ('ProjectVariables' or 'K5Project').
            version: Schema version ('1.0').
            scopes: Optional subset of scopes to export. If None, exports all.

        Returns:
            Well-formatted XML string.
        """
        # Group variables by scope
        grouped: Dict[str, List[CscapeVariable]] = {}
        target_scopes = set(s.strip().lower() for s in scopes) if scopes else None

        for v in variables:
            if target_scopes and not _matches_target_scopes(v, target_scopes):
                continue
            sc = v.scope.lower()
            grouped.setdefault(sc, []).append(v)

        root = ET.Element(root_tag, {"version": version})

        # Ensure globals and retain are ordered first if present
        ordered_scopes = sorted(
            grouped.keys(),
            key=lambda k: 0 if k == "globals" else (1 if k == "retain" else 2)
        )

        for sc_name in ordered_scopes:
            vars_in_group = grouped[sc_name]
            # Cleanly format register scopes (%R, %M, %AI, %AQ, %I, %Q, %S, %SR) without schema truncation
            if sc_name.startswith("%") or sc_name.upper() in {"R", "M", "AI", "AQ", "I", "Q", "S", "SR", "T", "D", "K", "IG", "QG", "AIG", "AQG"}:
                display_scope = sc_name.upper() if sc_name.startswith("%") else f"%{sc_name.upper()}"
            else:
                display_scope = sc_name
            vargroup = ET.SubElement(root, "vargroup", {"name": display_scope})

            for v in vars_in_group:
                var_attrs: Dict[str, str] = {
                    "name": v.name,
                    "type": v.data_type,
                }
                if v.data_type == "STRING" and v.string_length:
                    var_attrs["len"] = str(v.string_length)
                if v.dimensions:
                    var_attrs["dim"] = str(v.dimensions)
                attrs_list = list(v.attributes)
                if v.read_only and not any(a.lower() in {"constant", "ro", "readonly"} for a in attrs_list):
                    attrs_list.append("constant")
                if attrs_list:
                    var_attrs["attr"] = ",".join(attrs_list)
                if v.initial_value:
                    var_attrs["init"] = str(v.initial_value)

                var_elem = ET.SubElement(vargroup, "var", var_attrs)

                # Add varinfo children
                if v.tag:
                    ET.SubElement(var_elem, "varinfo", {"type": "tag", "data": v.tag})
                if v.description:
                    ET.SubElement(var_elem, "varinfo", {"type": "desc", "data": v.description})
                if v.usergroup:
                    ET.SubElement(var_elem, "varinfo", {"type": "usergroup", "data": v.usergroup})

        # Indent XML and serialize to string
        ET.indent(root, space="   ")
        xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        return xml_bytes.decode("utf-8")


class CscapeXMLParser:
    """Parses official Cscape 10.2 XML variable exchange files into CscapeVariable instances."""

    @classmethod
    def parse(cls, xml_content: Union[str, bytes, Path]) -> List[CscapeVariable]:
        """Parses Cscape XML variable definitions.

        Args:
            xml_content: XML string, bytes, or file path.

        Returns:
            List of parsed CscapeVariable instances.
        """
        if isinstance(xml_content, Path) or (isinstance(xml_content, str) and os.path.exists(xml_content)):
            raw_text = Path(xml_content).read_text(encoding="utf-8", errors="replace")
        elif isinstance(xml_content, bytes):
            raw_text = xml_content.decode("utf-8", errors="replace")
        elif isinstance(xml_content, str):
            raw_text = xml_content
        else:
            raise TypeError(f"Unsupported XML source: {type(xml_content)}")

        try:
            root = ET.fromstring(raw_text)
        except ET.ParseError:
            # Handle Cscape sample template files that prefix XML lines with ;; or ;
            cleaned_lines = []
            for line in raw_text.splitlines():
                stripped = line.strip()
                if stripped.startswith(";;"):
                    cleaned_lines.append(stripped[2:].lstrip())
                elif stripped.startswith(";") and not stripped.startswith("<!--"):
                    cleaned_lines.append(stripped[1:].lstrip())
                else:
                    cleaned_lines.append(line)
            cleaned_text = "\n".join(cleaned_lines)
            root = ET.fromstring(cleaned_text)


        variables: List[CscapeVariable] = []

        # Find all vargroups
        vargroups = root.findall(".//vargroup")
        if not vargroups:
            # Handle root without vargroup
            var_nodes = root.findall(".//var")
            for vn in var_nodes:
                variables.append(cls._parse_var_node(vn, default_scope="globals"))
            return variables

        for vg in vargroups:
            scope_name = vg.get("name", "globals").strip().lower()
            for vn in vg.findall("var"):
                var_obj = cls._parse_var_node(vn, default_scope=scope_name)
                variables.append(var_obj)

        return variables

    @classmethod
    def _parse_var_node(cls, node: ET.Element, default_scope: str = "globals") -> CscapeVariable:
        """Parses a single <var> element."""
        name = node.get("name", "").strip()
        data_type = node.get("type", "INT").strip().upper()
        init_val = node.get("init")
        dim_val = node.get("dim")
        len_val = node.get("len")
        attr_val = node.get("attr")

        string_len: Optional[int] = None
        if len_val:
            try:
                string_len = int(len_val.strip())
            except ValueError:
                pass

        attributes: List[str] = []
        is_ro = False
        if attr_val:
            for item in attr_val.split(","):
                item_clean = item.strip()
                if item_clean:
                    attributes.append(item_clean)
                    if item_clean.lower() in {"constant", "ro", "readonly"}:
                        is_ro = True

        tag_val: Optional[str] = None
        desc_val: Optional[str] = None
        usergroup_val: Optional[str] = None

        # Parse <varinfo> children
        for info in node.findall("varinfo"):
            itype = info.get("type", "").strip().lower()
            idata = info.get("data", "").strip()
            if itype == "tag":
                tag_val = idata
            elif itype == "desc":
                desc_val = idata
            elif itype == "usergroup":
                usergroup_val = idata
            elif itype == "attr" and idata:
                attributes.append(idata)
                if idata.lower() in {"constant", "ro", "readonly"}:
                    is_ro = True

        return CscapeVariable(
            name=name,
            data_type=data_type,
            scope=default_scope,
            tag=tag_val,
            description=desc_val,
            usergroup=usergroup_val,
            initial_value=init_val,
            string_length=string_len,
            dimensions=dim_val,
            attributes=attributes,
            read_only=is_ro,
        )


# ---------------------------------------------------------------------------
# Bidirectional Cscape CSV Parser & Serializer
# ---------------------------------------------------------------------------

DEFAULT_CSV_HEADERS: List[str] = [
    "name", "type", "len", "dim", "attr", "RO", "init", "tag", "desc"
]


class CscapeCSVSerializer:
    """Serializes Cscape variable database into Cscape CSV Mode Variables Editor format."""

    @classmethod
    def serialize(
        cls,
        variables: Sequence[CscapeVariable],
        delimiter: str = ";",
        headers: Optional[Sequence[str]] = None,
        scopes: Optional[Sequence[str]] = None,
        include_scope_col: bool = False,
    ) -> str:
        """Serializes variables to CSV string.

        Args:
            variables: Sequence of CscapeVariable objects.
            delimiter: Column delimiter (';' for native Cscape, or ',').
            headers: Specific columns to include. Defaults to Cscape standard columns.
            scopes: Optional filter for scopes.
            include_scope_col: If True, adds 'scope' column for multi-group exchange.

        Returns:
            CSV formatted string with double-quoted fields.
        """
        target_headers = list(headers or DEFAULT_CSV_HEADERS)
        if include_scope_col and "scope" not in target_headers:
            target_headers.append("scope")

        target_scopes = set(s.strip().lower() for s in scopes) if scopes else None
        output = io.StringIO()
        writer = csv.writer(
            output,
            delimiter=delimiter,
            quoting=csv.QUOTE_ALL,
            lineterminator="\r\n"
        )

        # Write header
        writer.writerow(target_headers)

        for v in variables:
            if target_scopes and not _matches_target_scopes(v, target_scopes):
                continue

            row = []
            for col in target_headers:
                c = col.lower()
                if c == "name":
                    row.append(v.name)
                elif c == "type":
                    row.append(v.data_type)
                elif c == "len":
                    row.append(str(v.string_length) if v.data_type == "STRING" and v.string_length else "")
                elif c == "dim":
                    row.append(v.dimensions or "")
                elif c == "attr":
                    attrs_list = list(v.attributes)
                    if v.read_only and not any(a.lower() in {"constant", "ro", "readonly"} for a in attrs_list):
                        attrs_list.append("constant")
                    row.append(",".join(attrs_list) if attrs_list else "")
                elif c == "ro":
                    row.append("YES" if v.read_only else "NO")
                elif c == "init":
                    row.append(v.initial_value or "")
                elif c in {"tag", "address"}:
                    row.append(v.tag or "")
                elif c in {"desc", "description", "comment"}:
                    row.append(v.description or "")
                elif c == "scope":
                    if v.scope.startswith("%") or v.scope.upper() in {"R", "M", "AI", "AQ", "I", "Q", "S", "SR", "T", "D", "K", "IG", "QG", "AIG", "AQG"}:
                        display_sc = v.scope.upper() if v.scope.startswith("%") else f"%{v.scope.upper()}"
                    else:
                        display_sc = v.scope
                    row.append(display_sc)
                elif c in {"usergroup", "user_group"}:
                    row.append(v.usergroup or "")
                else:
                    row.append("")
            writer.writerow(row)

        return output.getvalue()


class CscapeCSVParser:
    """Parses Cscape CSV Mode Variables Editor files into CscapeVariable instances."""

    @classmethod
    def parse(
        cls,
        csv_content: Union[str, bytes, Path],
        delimiter: Optional[str] = None,
        default_scope: str = "globals",
    ) -> List[CscapeVariable]:
        """Parses CSV content into CscapeVariable instances.

        Args:
            csv_content: CSV string, bytes, or file path.
            delimiter: Expected delimiter. If None, auto-detected (';' or ',').
            default_scope: Default scope if not specified in CSV.

        Returns:
            List of parsed CscapeVariable instances.
        """
        if isinstance(csv_content, Path) or (isinstance(csv_content, str) and os.path.exists(csv_content)):
            raw_text = Path(csv_content).read_text(encoding="utf-8", errors="replace")
        elif isinstance(csv_content, bytes):
            raw_text = csv_content.decode("utf-8", errors="replace")
        elif isinstance(csv_content, str):
            raw_text = csv_content
        else:
            raise TypeError(f"Unsupported CSV input type: {type(csv_content)}")

        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        if not lines:
            return []

        # Auto-detect delimiter if not specified
        first_line = lines[0]
        if delimiter is None:
            semis = first_line.count(";")
            commas = first_line.count(",")
            delimiter = ";" if semis >= commas else ","

        reader = csv.reader(io.StringIO(raw_text), delimiter=delimiter)
        raw_headers = next(reader, None)
        if not raw_headers:
            return []

        # Normalize header indices
        header_map: Dict[str, int] = {}
        for idx, h in enumerate(raw_headers):
            clean_h = h.strip().strip('"').strip("'").lower()
            header_map[clean_h] = idx

        variables: List[CscapeVariable] = []

        for row_idx, row in enumerate(reader, start=2):
            if not row or not any(field.strip() for field in row):
                continue

            def get_col(*aliases: str) -> str:
                for alias in aliases:
                    if alias in header_map and header_map[alias] < len(row):
                        return row[header_map[alias]].strip()
                return ""

            name = get_col("name", "variable", "symbol")
            if not name:
                continue

            dtype = get_col("type", "datatype", "data_type") or "INT"
            len_str = get_col("len", "length")
            dim_str = get_col("dim", "dimension", "dimensions")
            attr_str = get_col("attr", "attribute", "attributes")
            ro_str = get_col("ro", "readonly", "read_only")
            init_str = get_col("init", "initial", "initial_value")
            tag_str = get_col("tag", "address")
            desc_str = get_col("desc", "description", "comment")
            scope_str = get_col("scope", "group") or default_scope
            usergroup_str = get_col("usergroup", "user_group")

            string_len: Optional[int] = None
            if len_str:
                try:
                    string_len = int(len_str)
                except ValueError:
                    pass

            is_ro = ro_str.upper() in {"YES", "TRUE", "1"}
            attributes = [a.strip() for a in attr_str.split(",") if a.strip()]
            if is_ro and "constant" not in [a.lower() for a in attributes]:
                attributes.append("constant")

            var_obj = CscapeVariable(
                name=name,
                data_type=dtype,
                scope=scope_str,
                tag=tag_str if tag_str else None,
                description=desc_str if desc_str else None,
                usergroup=usergroup_str if usergroup_str else None,
                initial_value=init_str if init_str else None,
                string_length=string_len,
                dimensions=dim_str if dim_str else None,
                attributes=attributes,
                read_only=is_ro,
            )
            variables.append(var_obj)

        return variables


# ---------------------------------------------------------------------------
# IEC 61131-3 Text Mode Parser & Serializer
# ---------------------------------------------------------------------------

class CscapeIECSerializer:
    """Serializes Cscape variables into standard IEC 61131-3 structured declaration blocks."""

    @classmethod
    def serialize_block(
        cls,
        variables: Sequence[CscapeVariable],
        scope_header: str = "VAR_GLOBAL",
    ) -> str:
        """Serializes variables into a VAR...END_VAR block with (*$tag*) directives."""
        lines = [scope_header]
        for v in variables:
            lines.append(v.to_iec_declaration(indent="    "))
        lines.append("END_VAR")
        return "\n".join(lines)


class CscapeIECParser:
    """Parses IEC 61131-3 variable blocks with Cscape directives into CscapeVariable instances."""

    # Matches: Name : TYPE [:= init] ; [directives]
    DECL_PATTERN = re.compile(
        r"^(?P<ro>CONSTANT\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*"
        r"(?P<type>(?:ARRAY\s*\[[^\]]+\]\s*OF\s+)?[A-Za-z0-9_]+(?:\s*\(\s*\d+\s*\))?)"
        r"(?:\s*:=\s*(?P<init>[^;]+))?\s*;",
        re.IGNORECASE
    )

    TAG_DIRECTIVE_PATTERN = re.compile(r"(?:\(\*\$tag=|//\$tag=)(?P<tag>[^)*\r\n]+)", re.IGNORECASE)
    DESC_DIRECTIVE_PATTERN = re.compile(r"(?:\(\*\$desc=|//\$desc=)(?P<desc>[^)*\r\n]+)", re.IGNORECASE)

    @classmethod
    def parse(cls, text: str, default_scope: str = "globals") -> List[CscapeVariable]:
        """Parses IEC declaration text into CscapeVariable instances."""
        variables: List[CscapeVariable] = []
        current_scope = default_scope

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("(*") and not line.startswith("(*$"):
                continue

            upper_line = line.upper()
            if upper_line.startswith("VAR_GLOBAL"):
                current_scope = "globals"
                continue
            elif upper_line.startswith("VAR") and "RETAIN" in upper_line:
                current_scope = "retain"
                continue
            elif upper_line.startswith("VAR_INPUT") or upper_line.startswith("VAR_OUTPUT") or upper_line.startswith("VAR"):
                # Program or local variables
                continue
            elif upper_line.startswith("END_VAR"):
                continue

            match = cls.DECL_PATTERN.search(line)
            if not match:
                continue

            name = match.group("name")
            raw_type = match.group("type").strip()
            init_val = match.group("init")
            is_ro = bool(match.group("ro"))

            # Extract directives
            tag_match = cls.TAG_DIRECTIVE_PATTERN.search(line)
            desc_match = cls.DESC_DIRECTIVE_PATTERN.search(line)

            tag_val = tag_match.group("tag").strip() if tag_match else None
            desc_val = desc_match.group("desc").strip() if desc_match else None

            # Check array bounds
            dim_val: Optional[str] = None
            data_type = raw_type
            if raw_type.upper().startswith("ARRAY"):
                arr_match = re.match(r"ARRAY\s*\[([^\]]+)\]\s*OF\s*(.+)", raw_type, re.IGNORECASE)
                if arr_match:
                    dim_val = arr_match.group(1).strip()
                    data_type = arr_match.group(2).strip()

            str_len: Optional[int] = None
            if data_type.upper().startswith("STRING"):
                str_match = re.match(r"STRING\s*\(\s*(\d+)\s*\)", data_type, re.IGNORECASE)
                if str_match:
                    data_type = "STRING"
                    str_len = int(str_match.group(1))

            var_obj = CscapeVariable(
                name=name,
                data_type=data_type,
                scope=current_scope,
                tag=tag_val,
                description=desc_val,
                initial_value=init_val.strip() if init_val else None,
                dimensions=dim_val,
                string_length=str_len,
                read_only=is_ro,
            )
            variables.append(var_obj)

        return variables


# ---------------------------------------------------------------------------
# High-Level Cscape Variable Manager / Tag Database
# ---------------------------------------------------------------------------

class VariableManager:
    """Manages the complete Horner Cscape variable / tag database."""

    def __init__(self, project_name: str = "Project") -> None:
        self.project_name = project_name
        self._variables: Dict[str, CscapeVariable] = {}  # key: (scope, name.upper())

    def _make_key(self, name: str, scope: str = "globals") -> Tuple[str, str]:
        return (scope.strip().lower(), name.strip().upper())

    # ------------------------------------------------------------------------
    # CRUD Operations
    # ------------------------------------------------------------------------

    def add_variable(
        self,
        var: CscapeVariable,
        overwrite: bool = True,
    ) -> CscapeVariable:
        """Adds a variable to the database.

        Args:
            var: CscapeVariable to register.
            overwrite: If True, replaces existing variable with same name in scope.

        Returns:
            The registered CscapeVariable.

        Raises:
            ValueError: If validation fails or duplicate exists and overwrite is False.
        """
        errs = var.validate()
        if errs:
            raise ValueError(f"Variable validation failed: {'; '.join(errs)}")

        key = self._make_key(var.name, var.scope)
        if key in self._variables and not overwrite:
            raise ValueError(f"Variable '{var.name}' already exists in scope '{var.scope}'.")

        self._variables[key] = var
        return var

    def get_variable(self, name: str, scope: str = "globals") -> Optional[CscapeVariable]:
        """Retrieves a variable by name and scope."""
        key = self._make_key(name, scope)
        return self._variables.get(key)

    def find_variable(self, name: str) -> List[CscapeVariable]:
        """Finds all occurrences of a variable name across all scopes."""
        target = name.strip().upper()
        return [v for (sc, n), v in self._variables.items() if n == target]

    def remove_variable(self, name: str, scope: str = "globals") -> bool:
        """Removes a variable from the database. Returns True if removed."""
        key = self._make_key(name, scope)
        return self._variables.pop(key, None) is not None

    def update_variable(
        self,
        name: str,
        scope: str = "globals",
        **updates: Any,
    ) -> CscapeVariable:
        """Updates fields of an existing variable."""
        var = self.get_variable(name, scope)
        if not var:
            raise KeyError(f"Variable '{name}' not found in scope '{scope}'.")

        for k, v in updates.items():
            if hasattr(var, k):
                setattr(var, k, v)

        var.__post_init__()
        errs = var.validate()
        if errs:
            raise ValueError(f"Updated variable validation failed: {'; '.join(errs)}")

        return var

    def list_variables(
        self,
        scope: Optional[str] = None,
        data_type: Optional[str] = None,
        has_tag: Optional[bool] = None,
    ) -> List[CscapeVariable]:
        """Returns filtered list of variables."""
        results: List[CscapeVariable] = []
        target_scope = scope.strip().lower() if scope else None
        target_type = data_type.strip().upper() if data_type else None

        for v in self._variables.values():
            if target_scope:
                matches = (v.scope.lower() == target_scope)
                if not matches:
                    pfx = target_scope if target_scope.startswith("%") else ("%" + target_scope)
                    if v.register and v.register.prefix.lower() == pfx:
                        matches = True
                if not matches:
                    continue
            if target_type and v.data_type.upper() != target_type:
                continue
            if has_tag is not None:
                if has_tag and not v.tag:
                    continue
                if not has_tag and v.tag:
                    continue
            results.append(v)

        return sorted(results, key=lambda x: (x.scope, x.name))

    def clear(self) -> None:
        """Clears all variables from the database."""
        self._variables.clear()

    @property
    def total_count(self) -> int:
        """Total number of variables across all scopes."""
        return len(self._variables)

    # ------------------------------------------------------------------------
    # Horner Register Management, Allocation & Conflict Detection
    # ------------------------------------------------------------------------

    def detect_conflicts(self) -> List[Dict[str, Any]]:
        """Scans database for overlapping Horner register allocations.

        Returns:
            List of conflict details. Empty if no collisions exist.
        """
        conflicts: List[Dict[str, Any]] = []
        tagged_vars = [v for v in self._variables.values() if v.tag and v.register]

        # Check all pairs
        for i in range(len(tagged_vars)):
            for j in range(i + 1, len(tagged_vars)):
                v1 = tagged_vars[i]
                v2 = tagged_vars[j]
                r1 = v1.register
                r2 = v2.register
                if not r1 or not r2:
                    continue

                if r1.overlaps_with(
                    other=r2,
                    self_type=v1.data_type,
                    other_type=v2.data_type,
                    self_len=v1.string_length,
                    other_len=v2.string_length,
                    self_dims=v1.array_element_count,
                    other_dims=v2.array_element_count,
                ):
                    spanned1 = v1.occupied_registers()
                    spanned2 = v2.occupied_registers()
                    overlapping = sorted(set(spanned1) & set(spanned2))
                    overlap_info = f" on {', '.join(overlapping)}" if overlapping else ""
                    conflicts.append({
                        "variable1": v1.name,
                        "scope1": v1.scope,
                        "register1": v1.tag,
                        "type1": v1.data_type,
                        "spanned1": spanned1,
                        "variable2": v2.name,
                        "scope2": v2.scope,
                        "register2": v2.tag,
                        "type2": v2.data_type,
                        "spanned2": spanned2,
                        "overlapping_registers": overlapping,
                        "reason": f"Memory overlap between {v1.name} ({v1.tag}) and {v2.name} ({v2.tag}){overlap_info}",
                    })

        return conflicts

    def allocate_register(
        self,
        data_type: str,
        prefix: str = "%R",
        start_index: int = 1,
        string_length: Optional[int] = None,
        array_elements: int = 1,
    ) -> str:
        """Finds the next contiguous available Horner register for an untagged variable.

        Args:
            data_type: IEC data type.
            prefix: Target register prefix (%R, %M, %T, %AI, %AQ, %I, %Q).
            start_index: Minimum register index to search from (default 1).
            string_length: Length for STRING types.
            array_elements: Array elements count.

        Returns:
            Formatted register string (e.g. '%R105').
        """
        norm_prefix = "%" + prefix.strip().lstrip("%").upper()

        # Build set of occupied indexes for this prefix
        occupied_indices: Set[int] = set()
        occupied_bits: Set[Tuple[int, int]] = set()

        for v in self._variables.values():
            reg = v.register
            if not reg or reg.prefix != norm_prefix:
                continue

            if reg.bit_offset is not None:
                occupied_bits.add((reg.index, reg.bit_offset))
                occupied_indices.add(reg.index)
            else:
                span = reg.get_word_span(v.data_type, v.string_length, v.array_element_count)
                for off in range(span):
                    occupied_indices.add(reg.index + off)

        # Candidate span needed
        dt_upper = data_type.strip().upper()
        is_bit_target = norm_prefix in BIT_REGISTERS
        needed_words = 1
        if not is_bit_target:
            dummy_reg = HornerRegister(prefix=norm_prefix, index=1)
            needed_words = dummy_reg.get_word_span(dt_upper, string_length, array_elements)

        candidate = max(1, start_index)
        max_bound = HORNER_REGISTER_LIMITS.get(norm_prefix, (1, 65535))[1]

        while candidate + needed_words - 1 <= max_bound:
            # Check if candidate .. candidate + needed_words - 1 are free
            collision = False
            for step in range(needed_words):
                if (candidate + step) in occupied_indices:
                    collision = True
                    break

            if not collision:
                return f"{norm_prefix}{candidate}"

            candidate += 1

        raise ValueError(
            f"Cannot allocate {needed_words} words for '{data_type}' in {norm_prefix}: "
            f"memory space exhausted (max index is {max_bound})."
        )

    # ------------------------------------------------------------------------
    # Bidirectional Import & Export
    # ------------------------------------------------------------------------

    def import_xml(
        self,
        xml_source: Union[str, bytes, Path],
        merge: bool = True,
    ) -> int:
        """Imports variables from Cscape XML. Returns number of variables imported."""
        parsed = CscapeXMLParser.parse(xml_source)
        if not merge:
            self.clear()
        count = 0
        for v in parsed:
            self.add_variable(v, overwrite=True)
            count += 1
        return count

    def export_xml(
        self,
        destination: Optional[Union[str, Path]] = None,
        scopes: Optional[Sequence[str]] = None,
    ) -> str:
        """Exports database to Cscape XML. Writes to file if destination is provided."""
        xml_str = CscapeXMLSerializer.serialize(
            variables=list(self._variables.values()),
            scopes=scopes,
        )
        if destination:
            p = Path(destination).resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(xml_str, encoding="utf-8")
        return xml_str

    def import_csv(
        self,
        csv_source: Union[str, bytes, Path],
        delimiter: Optional[str] = None,
        default_scope: str = "globals",
        merge: bool = True,
    ) -> int:
        """Imports variables from Cscape CSV. Returns number of variables imported."""
        parsed = CscapeCSVParser.parse(csv_source, delimiter=delimiter, default_scope=default_scope)
        if not merge:
            self.clear()
        count = 0
        for v in parsed:
            self.add_variable(v, overwrite=True)
            count += 1
        return count

    def export_csv(
        self,
        destination: Optional[Union[str, Path]] = None,
        delimiter: str = ";",
        scopes: Optional[Sequence[str]] = None,
    ) -> str:
        """Exports database to Cscape CSV. Writes to file if destination is provided."""
        csv_str = CscapeCSVSerializer.serialize(
            variables=list(self._variables.values()),
            delimiter=delimiter,
            scopes=scopes,
            include_scope_col=True,
        )
        if destination:
            p = Path(destination).resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(csv_str, encoding="utf-8")
        return csv_str

    def import_iec_text(
        self,
        text: str,
        default_scope: str = "globals",
        merge: bool = True,
    ) -> int:
        """Imports variables from IEC Structured Text declaration blocks."""
        parsed = CscapeIECParser.parse(text, default_scope=default_scope)
        if not merge:
            self.clear()
        count = 0
        for v in parsed:
            self.add_variable(v, overwrite=True)
            count += 1
        return count

    def export_iec_text(self, scope: str = "globals") -> str:
        """Exports variables in a given scope to an IEC 61131-3 declaration block."""
        vars_in_scope = self.list_variables(scope=scope)
        header = "VAR RETAIN" if scope.lower() == "retain" else "VAR_GLOBAL"
        return CscapeIECSerializer.serialize_block(vars_in_scope, scope_header=header)

    # Convenient aliases
    to_xml = export_xml
    from_xml = import_xml
    to_csv = export_csv
    from_csv = import_csv

    # ------------------------------------------------------------------------
    # Project Synchronization
    # ------------------------------------------------------------------------

    def sync_to_project(self, project_dir: Union[str, Path]) -> Dict[str, Any]:
        """Synchronizes current variable database into a Cscape project folder:

        - Writes variables.xml (Cscape Variable Manager XML exchange)
        - Writes variables.csv (Cscape CSV backup)
        - Updates project_manifest.json if present
        """
        proj_p = Path(project_dir).resolve()
        if not proj_p.exists():
            raise FileNotFoundError(f"Project directory does not exist: {proj_p}")

        # 1. Export variables.xml
        xml_path = proj_p / "variables.xml"
        self.export_xml(xml_path)

        # 2. Export variables.csv
        csv_path = proj_p / "variables.csv"
        self.export_csv(csv_path)

        return {
            "project_name": self.project_name,
            "variables_count": self.total_count,
            "xml_export": str(xml_path),
            "csv_export": str(csv_path),
            "conflicts": self.detect_conflicts(),
        }

    def load_from_project(self, project_dir: Union[str, Path]) -> int:
        """Loads variables from an existing Cscape project folder."""
        proj_p = Path(project_dir).resolve()
        xml_file = proj_p / "variables.xml"
        if xml_file.exists():
            return self.import_xml(xml_file, merge=True)

        csv_file = proj_p / "variables.csv"
        if csv_file.exists():
            return self.import_csv(csv_file, merge=True)

        return 0


# Alias TagDatabase and CscapeVariableManager to VariableManager for convenience
TagDatabase = VariableManager
CscapeVariableManager = VariableManager

__all__ = [
    "RegisterType",
    "BIT_REGISTERS",
    "WORD_REGISTERS",
    "DWORD_REGISTERS",
    "READ_ONLY_REGISTERS",
    "RETENTIVE_REGISTERS",
    "IEC_TYPE_WORD_SIZE",
    "SUPPORTED_DATA_TYPES",
    "HORNER_REGISTER_LIMITS",
    "REGISTER_PATTERN",
    "HornerRegister",
    "CscapeVariable",
    "CscapeXMLSerializer",
    "CscapeXMLParser",
    "CscapeCSVSerializer",
    "CscapeCSVParser",
    "CscapeIECSerializer",
    "CscapeIECParser",
    "VariableManager",
    "TagDatabase",
    "CscapeVariableManager",
]
