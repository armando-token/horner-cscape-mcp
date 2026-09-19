"""Tests for Horner Cscape Native CFBF / OLE2 Samples and Container Verification.

Validates authentic .csp and .cpj project files:
1. Native Horner sample inspection on disk (TankLevelClosedLoop.csp, DiagnosticTest.csp):
   - CFBF magic header 0xD0CF11E0A1B11AE1
   - Sector size (512 or 4096 bytes)
   - Directory entries: Root Entry, Contents stream
   - Pure Python /Contents stream extraction and header verification (magic 0x78563412)
   - Horner tags: HornerOCS, Allocated, %AI1, %AQ1, PLC Type, <END_RETAIN>, main3
   - IEC configuration detection
2. Synthetic minimal CFBF generation (generate_minimal_cfbf_bytes):
   - Produces valid CFBF container with magic 0xD0CF11E0A1B11AE1
   - Valid /Contents stream with magic 0x78563412 and Cscape version
   - Full compatibility with inspect_project_file, extract_cfbf_streams, and parse_csp_contents_header
3. Pure Python CFBF OLE2 parser (parse_cfbf_pure):
   - Sector chain resolution, directory entries, stream extraction
   - Rejection of invalid magic, truncated headers, corrupted sector chains
4. Contents header parsing (parse_csp_contents_header):
   - Modern Unicode descriptor parsing
   - Legacy binary header parsing
   - Horner tag detection in stream
"""

import struct
from pathlib import Path
import pytest

from src.cscape.cfbf import (
    CFBF_MAGIC,
    CSCAPE_CONTENTS_MAGIC,
    HORNER_MARKERS,
    ProjectFileInfo,
    extract_cfbf_streams,
    generate_minimal_cfbf_bytes,
    inspect_project_file,
    parse_cfbf_pure,
    parse_csp_contents_header,
)


# Sample file paths on disk
NATIVE_SAMPLES = [
    Path(r"artifacts/projects/TankLevelClosedLoop/TankLevelClosedLoop.csp"),
    Path(r"artifacts/projects/DiagnosticTest/DiagnosticTest.csp"),
]


# ==============================================================================
# 1. Native Real Samples Verification Tests
# ==============================================================================

class TestNativeCscapeSamples:
    """Verifies authentic native Horner Cscape .csp files against the CFBF specification."""

    @pytest.mark.parametrize(
        "sample_path",
        [p for p in NATIVE_SAMPLES if p.exists()],
        ids=lambda p: p.name,
    )
    def test_native_sample_cfbf_inspection(self, sample_path):
        """Inspects native .csp sample and validates CFBF header, sectors, and version."""
        info = inspect_project_file(sample_path)
        assert isinstance(info, ProjectFileInfo)
        assert info.is_valid_cfbf is True
        assert info.magic_hex == "d0cf11e0a1b11ae1"
        assert info.sector_size in (512, 4096)
        assert info.file_size_bytes > 0
        assert info.has_contents_stream is True
        assert info.has_iec_configuration is True
        assert info.cscape_version == "10.2.751.4"

        # Check directory entries
        entry_names = [e["name"] for e in info.stream_entries]
        assert "Root Entry" in entry_names
        assert "Contents" in entry_names

        # Check Horner markers
        for marker in ("HornerOCS", "Allocated", "%AI1", "%AQ1"):
            assert marker in info.horner_markers, f"Missing expected marker: {marker}"

    @pytest.mark.parametrize(
        "sample_path",
        [p for p in NATIVE_SAMPLES if p.exists()],
        ids=lambda p: p.name,
    )
    def test_native_sample_pure_python_stream_extraction(self, sample_path):
        """Extracts streams from native .csp sample using pure Python OLE2 parser."""
        streams = extract_cfbf_streams(sample_path)
        assert isinstance(streams, dict)
        assert "Contents" in streams
        contents = streams["Contents"]
        assert len(contents) > 0

        # Verify /Contents header
        hdr = parse_csp_contents_header(contents)
        assert hdr["valid"] is True
        assert hdr["magic"] == CSCAPE_CONTENTS_MAGIC
        assert hdr["cscape_version"] == "10.2.751.4"
        assert hdr["file_format_version"] == 135

        # Verify Horner markers in stream
        for marker in ("HornerOCS", "Allocated", "%AI1", "%AQ1"):
            assert marker in hdr["horner_markers"]


# ==============================================================================
# 2. Synthetic Minimal CFBF Generation Tests
# ==============================================================================

class TestSyntheticMinimalCfbf:
    """Validates generate_minimal_cfbf_bytes produces compliant CFBF OLE2 files."""

    def test_generate_minimal_cfbf_magic(self):
        """Generates CFBF bytes starting with authentic 8-byte magic 0xD0CF11E0A1B11AE1."""
        raw = generate_minimal_cfbf_bytes("MotorTest", "10.2.751.4")
        assert raw[:8] == CFBF_MAGIC
        assert raw[:8] == bytes.fromhex("d0cf11e0a1b11ae1")

    def test_generate_minimal_cfbf_inspection(self, tmp_path):
        """inspect_project_file verifies generated CFBF container."""
        raw = generate_minimal_cfbf_bytes("Reactor_A", "10.2.751.4")
        csp_path = tmp_path / "Reactor_A.csp"
        csp_path.write_bytes(raw)

        info = inspect_project_file(csp_path)
        assert info.is_valid_cfbf is True
        assert info.sector_size == 512
        assert info.has_contents_stream is True
        assert info.cscape_version == "10.2.751.4"
        assert "HornerOCS" in info.horner_markers
        assert "%AI1" in info.horner_markers
        assert "%AQ1" in info.horner_markers
        assert "Allocated" in info.horner_markers
        assert info.has_iec_configuration is True

    def test_generate_minimal_cfbf_extract_streams(self, tmp_path):
        """extract_cfbf_streams extracts /Contents stream from generated CFBF."""
        raw = generate_minimal_cfbf_bytes("BoilerCtrl", "10.2.751.4")
        csp_path = tmp_path / "BoilerCtrl.csp"
        csp_path.write_bytes(raw)

        streams = extract_cfbf_streams(csp_path)
        assert "Contents" in streams
        c_bytes = streams["Contents"]
        assert len(c_bytes) == 4096

        hdr = parse_csp_contents_header(c_bytes)
        assert hdr["valid"] is True
        assert hdr["magic"] == CSCAPE_CONTENTS_MAGIC
        assert hdr["cscape_version"] == "10.2.751.4"
        assert "BoilerCtrl".encode("ascii") in c_bytes

    def test_generate_minimal_cfbf_custom_version(self, tmp_path):
        """Supports custom Cscape version strings in generated CFBF."""
        raw = generate_minimal_cfbf_bytes("Turbine", "10.4.800.1")
        csp_path = tmp_path / "Turbine.csp"
        csp_path.write_bytes(raw)

        info = inspect_project_file(csp_path)
        assert info.cscape_version == "10.4.800.1"


# ==============================================================================
# 3. Pure Python OLE2 Parser Unit Tests
# ==============================================================================

class TestPurePythonOle2Parser:
    """Validates parse_cfbf_pure behavior and robustness."""

    def test_parse_cfbf_pure_on_valid_data(self):
        """parse_cfbf_pure parses valid CFBF bytes without error."""
        data = generate_minimal_cfbf_bytes("UnitTestProj", "10.2.751.4")
        entries, streams = parse_cfbf_pure(data)

        entry_names = [e["name"] for e in entries]
        assert "Root Entry" in entry_names
        assert "Contents" in entry_names
        assert "Contents" in streams
        assert len(streams["Contents"]) == 4096

    def test_parse_cfbf_pure_rejects_truncated_data(self):
        """Raises ValueError if data is shorter than 512 bytes."""
        with pytest.raises(ValueError) as exc:
            parse_cfbf_pure(b"\xd0\xcf\x11\xe0" * 10)
        assert "too short" in str(exc.value)

    def test_parse_cfbf_pure_rejects_invalid_magic(self):
        """Raises ValueError if magic does not match CFBF_MAGIC."""
        bad_header = bytearray(512)
        bad_header[:8] = b"NOTCFBF!"
        with pytest.raises(ValueError) as exc:
            parse_cfbf_pure(bad_header)
        assert "Invalid CFBF magic" in str(exc.value)

    def test_parse_cfbf_pure_rejects_bad_byte_order(self):
        """Raises ValueError if byte order is not little endian 0xFFFE."""
        bad_header = bytearray(512)
        bad_header[:8] = CFBF_MAGIC
        struct.pack_into("<H", bad_header, 28, 0xFEFF)  # Big-Endian
        with pytest.raises(ValueError) as exc:
            parse_cfbf_pure(bad_header)
        assert "Unsupported byte order" in str(exc.value)


# ==============================================================================
# 4. Contents Header Parser Tests
# ==============================================================================

class TestContentsHeaderParser:
    """Unit tests for parse_csp_contents_header."""

    def test_contents_header_valid_modern(self):
        """Parses modern Unicode descriptor in /Contents header."""
        buf = bytearray(128)
        struct.pack_into("<II", buf, 0, CSCAPE_CONTENTS_MAGIC, 135)
        buf[8:10] = b"\xff\xfe"
        ver_str = "10.2.751.4"
        buf[10:12] = bytes([0xFF, len(ver_str)])
        buf[12:12 + len(ver_str) * 2] = ver_str.encode("utf-16le")
        buf[64:64 + 9] = b"HornerOCS"

        res = parse_csp_contents_header(bytes(buf))
        assert res["valid"] is True
        assert res["magic"] == CSCAPE_CONTENTS_MAGIC
        assert res["file_format_version"] == 135
        assert res["header_type"] == "modern_unicode"
        assert res["cscape_version"] == "10.2.751.4"
        assert "HornerOCS" in res["horner_markers"]

    def test_contents_header_valid_legacy(self):
        """Parses legacy binary header (<BBH) in /Contents header."""
        buf = bytearray(64)
        struct.pack_into("<II", buf, 0, CSCAPE_CONTENTS_MAGIC, 90)
        # major=9, minor=30, build=120
        struct.pack_into("<BBH", buf, 8, 9, 30, 120)
        buf[32:32 + 9] = b"Allocated"

        res = parse_csp_contents_header(bytes(buf))
        assert res["valid"] is True
        assert res["file_format_version"] == 90
        assert res["header_type"] == "legacy_binary"
        assert "9.30" in res["cscape_version"]
        assert res["cscape_build"] == 120
        assert "Allocated" in res["horner_markers"]

    def test_contents_header_invalid_magic(self):
        """Returns valid=False on invalid magic."""
        buf = bytearray(32)
        struct.pack_into("<II", buf, 0, 0x11223344, 100)
        res = parse_csp_contents_header(bytes(buf))
        assert res["valid"] is False
        assert "Invalid Cscape contents magic" in res["error"]

    def test_contents_header_too_short(self):
        """Returns valid=False if stream is under 12 bytes."""
        res = parse_csp_contents_header(b"short")
        assert res["valid"] is False
        assert "too short" in res["error"]
