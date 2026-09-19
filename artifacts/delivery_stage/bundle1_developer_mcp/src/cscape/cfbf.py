"""Horner Cscape Native Compound File Binary Format (CFBF / OLE2) Module.

Provides deep structural parsing, verification, stream extraction, and synthetic
generation for authentic Horner Cscape native project files (.csp and .cpj).

Native Horner Cscape project specifications:
- Container Format: Microsoft Compound File Binary Format (CFBF / OLE2)
- 8-byte CFBF Magic Header: 0xD0CF11E0A1B11AE1 (\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1)
- Standard Sector Shift: 9 (512-byte sectors) or 12 (4096-byte sectors)
- Mandatory Root Entry: Directory root storage object
- Primary Stream: '/Contents' (Horner Cscape serialized workspace & logic)
- Cscape Contents Header Magic: 0x78563412 (12 34 56 78 in Little-Endian)
- Cscape Serialization Versions:
  - Legacy (v2.x - v9.x): File format versions 20 - 99, 12-byte header struct <IIBBH
  - Modern (v10.x+): File format versions 100+, UTF-16LE CString version descriptor
"""

from __future__ import annotations

import logging
import os
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import olefile
    OLEFILE_AVAILABLE = True
except ImportError:
    olefile = None
    OLEFILE_AVAILABLE = False

logger = logging.getLogger(__name__)

CFBF_MAGIC: bytes = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
CSCAPE_CONTENTS_MAGIC: int = 0x78563412

HORNER_MARKERS: tuple[str, ...] = (
    "HornerOCS",
    "main3",
    "Allocated",
    "<END_RETAIN>",
    "%AI1",
    "%AQ1",
    "PLC Type",
)


@dataclass
class ProjectFileInfo:
    """Detailed structural and header metadata of a Cscape project file (.csp / .cpj)."""
    file_path: Path
    file_size_bytes: int
    is_valid_cfbf: bool
    magic_hex: str
    sector_size: int
    dir_sector: int
    stream_entries: list[dict[str, Any]] = field(default_factory=list)
    cscape_version: Optional[str] = None
    horner_markers: list[str] = field(default_factory=list)
    has_contents_stream: bool = False
    has_iec_configuration: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": str(self.file_path),
            "file_size_bytes": self.file_size_bytes,
            "is_valid_cfbf": self.is_valid_cfbf,
            "magic_hex": self.magic_hex,
            "sector_size": self.sector_size,
            "dir_sector": self.dir_sector,
            "stream_entries": self.stream_entries,
            "cscape_version": self.cscape_version,
            "horner_markers": self.horner_markers,
            "has_contents_stream": self.has_contents_stream,
            "has_iec_configuration": self.has_iec_configuration,
        }


def parse_cfbf_pure(data: bytes) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    """Pure Python parser for Microsoft Compound File Binary Format (CFBF / OLE2).

    Inspects directory entries and extracts all streams without requiring external libraries.
    Supports both standard FAT sector streams and Mini FAT / Mini Stream sectors.
    """
    if len(data) < 512:
        raise ValueError(f"File data too short for CFBF header ({len(data)} bytes < 512 bytes)")

    if data[:8] != CFBF_MAGIC:
        raise ValueError(
            f"Invalid CFBF magic header: expected {CFBF_MAGIC.hex()}, got {data[:8].hex()}"
        )

    byte_order = struct.unpack_from("<H", data, 28)[0]
    if byte_order != 0xFFFE:
        raise ValueError(f"Unsupported byte order in CFBF: 0x{byte_order:04X} (expected 0xFFFE)")

    sec_shift = struct.unpack_from("<H", data, 30)[0]
    sec_size = 1 << sec_shift
    mini_sec_shift = struct.unpack_from("<H", data, 32)[0]
    mini_sec_size = 1 << mini_sec_shift
    num_fat_sec = struct.unpack_from("<I", data, 44)[0]
    first_dir_sec = struct.unpack_from("<I", data, 48)[0]
    mini_cutoff = struct.unpack_from("<I", data, 56)[0]
    first_mini_fat = struct.unpack_from("<I", data, 60)[0]
    num_mini_fat = struct.unpack_from("<I", data, 64)[0]
    first_difat = struct.unpack_from("<I", data, 68)[0]

    # Collect FAT sector IDs from header DIFAT (109 entries)
    fat_sec_ids: list[int] = [s for s in struct.unpack_from("<109I", data, 76) if s < 0xFFFFFFFD]

    # Follow chained DIFAT sectors if FAT is larger than 109 sectors
    cur_difat = first_difat
    difat_visited: set[int] = set()
    while cur_difat < 0xFFFFFFFD and len(fat_sec_ids) < num_fat_sec:
        if cur_difat in difat_visited:
            break
        difat_visited.add(cur_difat)
        d_off = (cur_difat + 1) * sec_size
        if d_off + sec_size > len(data):
            break
        cnt = (sec_size // 4) - 1
        fat_sec_ids.extend([s for s in struct.unpack_from(f"<{cnt}I", data, d_off) if s < 0xFFFFFFFD])
        cur_difat = struct.unpack_from("<I", data, d_off + cnt * 4)[0]

    # Build the FAT table
    fat: list[int] = []
    for f_sec in fat_sec_ids:
        f_off = (f_sec + 1) * sec_size
        if f_off + sec_size <= len(data):
            fat.extend(struct.unpack_from(f"<{sec_size // 4}I", data, f_off))

    def get_chain(start_sec: int, max_sectors: int = 65536) -> list[int]:
        chain: list[int] = []
        cur = start_sec
        visited: set[int] = set()
        while cur < 0xFFFFFFFD and len(chain) < max_sectors:
            if cur in visited or cur >= len(fat):
                break
            visited.add(cur)
            chain.append(cur)
            cur = fat[cur]
        return chain

    # Read directory sectors
    dir_chain = get_chain(first_dir_sec)
    dir_data = b"".join(data[(s + 1) * sec_size : (s + 2) * sec_size] for s in dir_chain)

    entries: list[dict[str, Any]] = []
    for off in range(0, len(dir_data), 128):
        block = dir_data[off : off + 128]
        if len(block) < 128:
            break
        etype = block[66]
        if etype in (1, 2, 5):
            nlen = struct.unpack_from("<H", block, 64)[0]
            name = ""
            if 2 <= nlen <= 64:
                try:
                    name = block[:nlen - 2].decode("utf-16le", errors="ignore").rstrip("\x00")
                except Exception:
                    name = ""
            if not name:
                raw_n = block[:64]
                if b"\x00\x00" in raw_n:
                    raw_n = raw_n[:raw_n.index(b"\x00\x00") + 1]
                name = raw_n.decode("utf-16le", errors="ignore").rstrip("\x00")

            start_sec = struct.unpack_from("<I", block, 116)[0]
            size = struct.unpack_from("<Q", block, 120)[0] if etype == 2 else struct.unpack_from("<I", block, 120)[0]
            type_str = {1: "Storage", 2: "Stream", 5: "Root"}.get(etype, f"Type_{etype}")
            entries.append({
                "name": name,
                "type": type_str,
                "type_id": etype,
                "start_sec": start_sec,
                "size": size,
                "is_stream": etype == 2,
            })

    root_entry = next((e for e in entries if e["type_id"] == 5), None)
    mini_stream_data = b""
    if root_entry and root_entry["start_sec"] < 0xFFFFFFFD and root_entry["size"] > 0:
        m_chain = get_chain(root_entry["start_sec"])
        mini_stream_data = b"".join(data[(s + 1) * sec_size : (s + 2) * sec_size] for s in m_chain)[:root_entry["size"]]

    mini_fat: list[int] = []
    if first_mini_fat < 0xFFFFFFFD and num_mini_fat > 0:
        mf_chain = get_chain(first_mini_fat)
        mf_data = b"".join(data[(s + 1) * sec_size : (s + 2) * sec_size] for s in mf_chain)
        mini_fat = list(struct.unpack_from(f"<{len(mf_data) // 4}I", mf_data))

    streams: dict[str, bytes] = {}
    for entry in entries:
        if entry["is_stream"] and entry["name"]:
            size = entry["size"]
            if size >= mini_cutoff or not mini_stream_data:
                chain = get_chain(entry["start_sec"])
                sdata = b"".join(data[(s + 1) * sec_size : (s + 2) * sec_size] for s in chain)[:size]
                streams[entry["name"]] = sdata
            else:
                def get_mini_chain(start_msec: int, max_mini: int = 65536) -> list[int]:
                    mchain: list[int] = []
                    mcur = start_msec
                    mvisited: set[int] = set()
                    while mcur < 0xFFFFFFFD and len(mchain) < max_mini:
                        if mcur in mvisited or mcur >= len(mini_fat):
                            break
                        mvisited.add(mcur)
                        mchain.append(mcur)
                        mcur = mini_fat[mcur]
                    return mchain

                m_chain = get_mini_chain(entry["start_sec"])
                sdata = b"".join(mini_stream_data[m * mini_sec_size : (m + 1) * mini_sec_size] for m in m_chain)[:size]
                streams[entry["name"]] = sdata

    return entries, streams


def parse_csp_contents_header(stream_bytes: bytes) -> dict[str, Any]:
    """Parse the 12+ byte header of the 'Contents' stream in a Horner .csp file."""
    if len(stream_bytes) < 12:
        return {"valid": False, "error": f"Stream too short ({len(stream_bytes)} bytes < 12 bytes)"}

    cmagic, file_format_ver = struct.unpack_from("<II", stream_bytes, 0)
    if cmagic != CSCAPE_CONTENTS_MAGIC:
        return {
            "valid": False,
            "error": f"Invalid Cscape contents magic: 0x{cmagic:08X} (expected 0x{CSCAPE_CONTENTS_MAGIC:08X})",
            "magic": cmagic,
        }

    cscape_version = None
    cscape_build = None
    header_type = "unknown"

    if stream_bytes[8:10] == b"\xff\xfe":
        header_type = "modern_unicode"
        str_len = stream_bytes[11] if len(stream_bytes) > 11 else 0
        end_idx = 12 + str_len * 2
        if len(stream_bytes) >= end_idx and str_len > 0:
            cscape_version = stream_bytes[12:end_idx].decode("utf-16le", errors="ignore").rstrip("\x00")
    else:
        header_type = "legacy_binary"
        c_maj, c_min, c_bld = struct.unpack_from("<BBH", stream_bytes, 8)
        cscape_version = f"{c_maj}.{c_min:02d} (build {c_bld})"
        cscape_build = c_bld

    # Fallback to pattern search in first 512 bytes of stream if version not cleanly resolved
    if not cscape_version or not cscape_version.strip():
        for m in re.finditer(rb"(?:[\x20-\x7E]\x00){3,}", stream_bytes[:512]):
            try:
                u_str = m.group(0).decode("utf-16le", errors="ignore").rstrip("\x00")
                if re.match(r"^\d{1,2}\.\d{1,2}\b", u_str):
                    cscape_version = u_str.split("\x00")[0]
                    break
            except Exception:
                pass

    # Detect Horner markers in stream bytes
    horner_markers: list[str] = []
    for marker in HORNER_MARKERS:
        if marker.encode("ascii") in stream_bytes or marker.encode("utf-16le") in stream_bytes:
            horner_markers.append(marker)

    return {
        "valid": True,
        "magic": cmagic,
        "file_format_version": file_format_ver,
        "header_type": header_type,
        "cscape_version": cscape_version,
        "cscape_build": cscape_build,
        "horner_markers": horner_markers,
    }


def extract_cfbf_streams(file_path: Union[str, Path]) -> dict[str, bytes]:
    """Extract all stream contents from a CFBF file into a mapping of name -> bytes.

    Uses pure Python OLE2 parser by default with zero external dependencies,
    falling back to olefile if present.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    data = path.read_bytes()
    try:
        _, streams = parse_cfbf_pure(data)
        if streams:
            return streams
    except Exception as pure_err:
        logger.debug("Pure Python CFBF extraction error on '%s': %s", path, pure_err)

    # Fallback to olefile if available
    streams = {}
    if OLEFILE_AVAILABLE and olefile is not None:
        try:
            ole = olefile.OleFileIO(str(path))
            for entry in ole.direntries:
                if entry is not None and entry.entry_type == 2:
                    try:
                        streams[entry.name] = ole.openstream(entry.name).read()
                    except Exception as err:
                        logger.debug("Failed reading stream '%s': %s", entry.name, err)
            ole.close()
        except Exception as err:
            logger.warning("Error opening OLE file '%s' via olefile: %s", path, err)

    return streams


def is_valid_cfbf(target: Union[str, Path, bytes, bytearray]) -> bool:
    """Validate whether target is an authentic, non-corrupt CFBF container.

    Rejects:
    - Non-existent files or 0-byte files
    - Truncated files (<= 512 bytes)
    - Files with invalid magic header (must be 0xD0CF11E0A1B11AE1)
    - 512-byte magic+zeros dummy files
    - Header with corrupted byte order (must be 0xFFFE at offset 28)
    - Invalid sector shift (must be 9 or 12 at offset 30)
    """
    try:
        if isinstance(target, (str, Path)):
            p = Path(target)
            if not p.exists() or not p.is_file():
                return False
            data = p.read_bytes()
        elif isinstance(target, (bytes, bytearray)):
            data = bytes(target)
        else:
            return False

        if len(data) <= 512:
            return False
        if data[:8] != CFBF_MAGIC:
            return False
        if data[8:512] == b"\x00" * 504:
            return False
        byte_order = struct.unpack_from("<H", data, 28)[0]
        if byte_order != 0xFFFE:
            return False
        sector_shift = struct.unpack_from("<H", data, 30)[0]
        if sector_shift not in (9, 12):
            return False
        mini_sec_shift = struct.unpack_from("<H", data, 32)[0]
        if mini_sec_shift != 6:
            return False
        sec_size = 1 << sector_shift
        # A valid CFBF container must contain at least Header + 1 FAT sector + 1 Directory sector = 3 sectors
        if len(data) < sec_size * 3:
            return False
        if len(data) % sec_size != 0:
            return False
        return True
    except Exception:
        return False


def inspect_project_file(file_path: Union[str, Path]) -> ProjectFileInfo:
    """Inspect and parse an authentic Cscape project file (.csp / .cpj).

    Validates:
    - File existence and non-zero size
    - Microsoft Compound File Binary Format (CFBF) 8-byte magic header (0xD0CF11E0A1B11AE1)
    - Sector size (512 or 4096 bytes)
    - Mini sector size (64 bytes, shift 6)
    - Sector alignment and minimum container size (>= 3 sectors)
    - OLE directory streams (Root Entry, Contents)
    - Embedded Cscape version strings (e.g. 10.2.751.4)
    - Horner APG controller markers and tags (%AI1, %AQ1, HornerOCS, Allocated, etc.)
    """
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Project file does not exist: {path}")

    file_size = path.stat().st_size
    if file_size == 0:
        raise ValueError(f"Project file is 0 bytes (empty): {path}")

    data = path.read_bytes()
    magic = data[:8]
    if magic != CFBF_MAGIC:
        raise ValueError(
            f"File '{path.name}' is not a valid Cscape Compound File (CFBF). "
            f"Expected magic {CFBF_MAGIC.hex()}, got {magic.hex()}"
        )

    # Fail-closed check: reject 512-byte magic+zeros or dummy/corrupt CFBF headers
    if len(data) <= 512 or data[8:512] == b"\x00" * 504:
        raise ValueError(
            f"File '{path.name}' is not a valid Cscape Compound File (CFBF): "
            f"dummy or corrupt container with 512-byte magic+zeros rejected."
        )

    # Check little-endian byte order at offset 28
    byte_order = struct.unpack_from("<H", data, 28)[0]
    if byte_order != 0xFFFE:
        raise ValueError(
            f"File '{path.name}' is not a valid Cscape Compound File (CFBF): "
            f"unsupported byte order 0x{byte_order:04X} (expected 0xFFFE)."
        )

    sector_shift = struct.unpack_from("<H", data, 30)[0]
    if sector_shift not in (9, 12):
        raise ValueError(
            f"File '{path.name}' is not a valid Cscape Compound File (CFBF): "
            f"invalid sector shift {sector_shift} (expected 9 or 12)."
        )

    mini_sec_shift = struct.unpack_from("<H", data, 32)[0]
    if mini_sec_shift != 6:
        raise ValueError(
            f"File '{path.name}' is not a valid Cscape Compound File (CFBF): "
            f"invalid mini sector shift {mini_sec_shift} (expected 6)."
        )

    sector_size = 1 << sector_shift
    if file_size < sector_size * 3:
        raise ValueError(
            f"File '{path.name}' is not a valid Cscape Compound File (CFBF): "
            f"file size {file_size} bytes is smaller than minimum CFBF container ({sector_size * 3} bytes)."
        )

    if file_size % sector_size != 0:
        raise ValueError(
            f"File '{path.name}' is not a valid Cscape Compound File (CFBF): "
            f"file size {file_size} bytes is not sector-aligned (sector size {sector_size} bytes)."
        )

    is_valid_cfbf_flag = True

    dir_sector = struct.unpack_from("<I", data, 48)[0]

    stream_entries: list[dict[str, Any]] = []
    streams: dict[str, bytes] = {}

    # Pure Python CFBF parse
    try:
        entries, streams = parse_cfbf_pure(data)
        for e in entries:
            stream_entries.append({
                "name": e["name"],
                "type": e["type"],
                "size": e["size"],
                "is_stream": e["is_stream"],
            })
    except Exception as p_err:
        logger.debug("Pure Python CFBF parse error on %s: %s", path, p_err)

    # Fallback / augment with olefile if available and pure parse failed
    if not stream_entries and OLEFILE_AVAILABLE and olefile is not None:
        try:
            ole = olefile.OleFileIO(str(path))
            for entry in ole.direntries:
                if entry is not None and entry.entry_type in (1, 2, 5):
                    type_str = {1: "Storage", 2: "Stream", 5: "Root"}.get(entry.entry_type, f"Type_{entry.entry_type}")
                    stream_entries.append({
                        "name": entry.name,
                        "type": type_str,
                        "size": entry.size,
                        "is_stream": entry.entry_type == 2,
                    })
                    if entry.entry_type == 2 and entry.name not in streams:
                        try:
                            streams[entry.name] = ole.openstream(entry.name).read()
                        except Exception:
                            pass
            ole.close()
        except Exception as err:
            logger.debug("olefile directory parse error on %s: %s", path, err)

    has_contents = any(e["name"].lower() == "contents" for e in stream_entries) or ("Contents" in streams)

    # Parse /Contents header and extract version and markers
    cscape_version = None
    contents_data = streams.get("Contents") or streams.get("contents")
    contents_hdr_failed = False
    if contents_data:
        hdr_info = parse_csp_contents_header(contents_data)
        if hdr_info.get("valid"):
            cscape_version = hdr_info.get("cscape_version")
        else:
            contents_hdr_failed = True

    # If version not found in /Contents header, scan Unicode & ASCII strings in raw file
    # Only perform heuristic string scan if /Contents stream was absent, NOT when /Contents header failed validation
    if not cscape_version and not contents_hdr_failed:
        for m in re.finditer(rb"(?:[\x20-\x7E]\x00){3,}", data):
            try:
                u_str = m.group(0).decode("utf-16le", errors="ignore")
                if re.match(r"^\d{1,2}\.\d{1,2}\b", u_str):
                    cscape_version = u_str.split("\x00")[0]
                    break
            except Exception:
                pass

    # Extract Horner markers from both stream data and raw file data
    search_haystack = data
    if contents_data:
        search_haystack = search_haystack + contents_data

    horner_markers: list[str] = []
    for marker in HORNER_MARKERS:
        if marker.encode("ascii") in search_haystack or marker.encode("utf-16le") in search_haystack:
            horner_markers.append(marker)

    has_iec = (
        "<END_RETAIN>" in horner_markers
        or "Allocated" in horner_markers
        or has_contents
    )

    return ProjectFileInfo(
        file_path=path,
        file_size_bytes=file_size,
        is_valid_cfbf=is_valid_cfbf_flag,
        magic_hex=magic.hex(),
        sector_size=sector_size,
        dir_sector=dir_sector,
        stream_entries=stream_entries,
        cscape_version=cscape_version,
        horner_markers=horner_markers,
        has_contents_stream=has_contents,
        has_iec_configuration=has_iec,
    )


def generate_minimal_cfbf_bytes(project_name: str = "IEC_Project", cscape_version: str = "10.2.751.4") -> bytes:
    """Synthesize a valid OLE Compound File (CFBF) binary with Horner Cscape markers.

    Guaranteed to pass CscapeLiveProjectManager.inspect_project_file():
    - CFBF 8-byte magic: 0xD0CF11E0A1B11AE1 (\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1)
    - Sector size: 512 bytes
    - OLE Directory streams: Root Entry, Contents
    - /Contents header with Cscape contents magic: 0x78563412
    - Embedded Cscape version (e.g. 10.2.751.4)
    - Horner OCS markers: HornerOCS, main3, Allocated, <END_RETAIN>, %AI1, %AQ1, PLC Type
    """
    header = bytearray(512)
    header[0:8] = CFBF_MAGIC
    struct.pack_into("<H", header, 28, 0xFFFE)  # Little-Endian
    struct.pack_into("<H", header, 30, 9)       # Sector shift (512 bytes)
    struct.pack_into("<H", header, 32, 6)       # Mini sector shift (64 bytes)
    struct.pack_into("<I", header, 44, 1)       # 1 FAT sector
    struct.pack_into("<I", header, 48, 1)       # Directory starts at sector 1
    struct.pack_into("<I", header, 56, 4096)    # Mini stream cutoff size
    struct.pack_into("<I", header, 60, 0xFFFFFFFE)  # No Mini FAT
    struct.pack_into("<I", header, 64, 0)
    struct.pack_into("<I", header, 68, 0xFFFFFFFE)  # No DIFAT sectors
    struct.pack_into("<I", header, 72, 0)
    struct.pack_into("<I", header, 76, 0)       # FAT sector at sector 0
    for i in range(1, 109):
        struct.pack_into("<I", header, 76 + i * 4, 0xFFFFFFFF)

    # Sector 0: FAT (8 sectors for Contents stream: sectors 2..9 = 4096 bytes)
    fat = bytearray(512)
    struct.pack_into("<I", fat, 0, 0xFFFFFFFD)  # Sector 0 is FAT itself
    struct.pack_into("<I", fat, 4, 0xFFFFFFFE)  # Sector 1 is Directory
    for s in range(2, 9):
        struct.pack_into("<I", fat, s * 4, s + 1)
    struct.pack_into("<I", fat, 9 * 4, 0xFFFFFFFE)  # Sector 9 is ENDOFCHAIN for Contents stream
    for i in range(10, 128):
        struct.pack_into("<I", fat, i * 4, 0xFFFFFFFF)

    # Sector 1: Directory
    directory = bytearray(512)
    root_name = "Root Entry\x00".encode("utf-16le")
    directory[0:len(root_name)] = root_name
    struct.pack_into("<H", directory, 64, len(root_name))
    directory[66] = 5  # Root
    struct.pack_into("<I", directory, 68, 0xFFFFFFFF)
    struct.pack_into("<I", directory, 72, 0xFFFFFFFF)
    struct.pack_into("<I", directory, 76, 1)    # Child = Entry 1 (Contents)
    struct.pack_into("<I", directory, 116, 0xFFFFFFFE)
    struct.pack_into("<I", directory, 120, 0)

    # Entry 1: Contents
    contents_name = "Contents\x00".encode("utf-16le")
    e1_off = 128
    directory[e1_off:e1_off + len(contents_name)] = contents_name
    struct.pack_into("<H", directory, e1_off + 64, len(contents_name))
    directory[e1_off + 66] = 2  # Stream
    struct.pack_into("<I", directory, e1_off + 68, 0xFFFFFFFF)
    struct.pack_into("<I", directory, e1_off + 72, 0xFFFFFFFF)
    struct.pack_into("<I", directory, e1_off + 76, 0xFFFFFFFF)
    struct.pack_into("<I", directory, e1_off + 116, 2)     # Starting sector 2
    struct.pack_into("<I", directory, e1_off + 120, 4096)  # Stream size 4096 bytes

    # Sectors 2..9: Contents stream (4096 bytes)
    contents_data = bytearray(4096)
    struct.pack_into("<I", contents_data, 0, CSCAPE_CONTENTS_MAGIC)  # 0x78563412
    struct.pack_into("<I", contents_data, 4, 135)                    # File format version 135
    contents_data[8:10] = b"\xff\xfe"                                # Modern Unicode marker
    ver_u16 = cscape_version.encode("utf-16le")
    contents_data[10:12] = bytes([0xFF, len(cscape_version)])
    contents_data[12:12 + len(ver_u16)] = ver_u16

    # Embed Horner markers & tags
    markers = b"HornerOCS main3 Allocated <END_RETAIN> %AI1 %AQ1 PLC Type " + project_name.encode("ascii", errors="replace")
    contents_data[64:64 + len(markers)] = markers

    return bytes(header + fat + directory + contents_data)


__all__ = [
    "CFBF_MAGIC",
    "CSCAPE_CONTENTS_MAGIC",
    "HORNER_MARKERS",
    "ProjectFileInfo",
    "is_valid_cfbf",
    "inspect_project_file",
    "parse_cfbf_pure",
    "parse_csp_contents_header",
    "extract_cfbf_streams",
    "generate_minimal_cfbf_bytes",
]

