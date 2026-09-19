"""Unit and integration tests for CFBF Project Container Inspection and Verification.

Mandate: Gate G1 CFBF and Simulation Mock Classifier
Classification: TESTED_MOCK [offline/DEV only]
Safety: Zero PLC interaction, hardware download lockout enforced. Zero Straton runtime dependencies.
"""

import struct
from pathlib import Path
import pytest

from src.cscape.cfbf import (
    CFBF_MAGIC,
    CSCAPE_CONTENTS_MAGIC,
    HORNER_MARKERS,
    ProjectFileInfo,
    inspect_project_file,
    extract_cfbf_streams,
    generate_minimal_cfbf_bytes,
    parse_cfbf_pure,
    parse_csp_contents_header,
)
from src.cscape.project_manager import CscapeLiveProjectManager

# Native Horner .csp sample paths
NATIVE_CSP_PATH = Path(r"artifacts/projects/TankLevelClosedLoop/TankLevelClosedLoop.csp")
DIAGNOSTIC_CSP_PATH = Path(r"artifacts/projects/DiagnosticTest/DiagnosticTest.csp")


class TestCfbfMagicConstants:
    """Verifies OLE2 CFBF and Cscape compound document constants."""

    def test_cfbf_magic_constant(self):
        """CFBF magic header must match 0xD0CF11E0A1B11AE1."""
        assert CFBF_MAGIC == bytes.fromhex("d0cf11e0a1b11ae1")
        assert len(CFBF_MAGIC) == 8

    def test_cscape_contents_magic_constant(self):
        """Cscape /Contents stream magic must match 0x78563412."""
        assert CSCAPE_CONTENTS_MAGIC == 0x78563412


class TestCfbfProjectInspection:
    """Verifies inspection of authentic Horner Cscape CFBF project containers."""

    def test_native_sample_cfbf_container(self):
        """Verifies native TankLevelClosedLoop.csp container structure."""
        if not NATIVE_CSP_PATH.exists():
            pytest.skip(f"Sample not found at {NATIVE_CSP_PATH}")

        info = inspect_project_file(NATIVE_CSP_PATH)
        assert isinstance(info, ProjectFileInfo)
        assert info.is_valid_cfbf is True
        assert info.magic_hex == "d0cf11e0a1b11ae1"
        assert info.sector_size in (512, 4096)
        assert info.file_size_bytes > 0
        assert info.has_contents_stream is True
        assert info.cscape_version == "10.2.751.4"

        # Check directory entries
        entry_names = [e["name"] for e in info.stream_entries]
        assert "Root Entry" in entry_names
        assert "Contents" in entry_names

        # Check Horner markers
        for marker in ("HornerOCS", "Allocated", "%AI1", "%AQ1"):
            assert marker in info.horner_markers, f"Missing expected marker: {marker}"

    def test_native_sample_contents_stream_extraction(self):
        """Extracts /Contents stream and verifies header format and markers."""
        if not NATIVE_CSP_PATH.exists():
            pytest.skip(f"Sample not found at {NATIVE_CSP_PATH}")

        streams = extract_cfbf_streams(NATIVE_CSP_PATH)
        assert isinstance(streams, dict)
        assert "Contents" in streams
        contents = streams["Contents"]
        assert len(contents) > 0

        hdr = parse_csp_contents_header(contents)
        assert hdr["valid"] is True
        assert hdr["magic"] == CSCAPE_CONTENTS_MAGIC
        assert hdr["cscape_version"] == "10.2.751.4"
        assert hdr["file_format_version"] == 135

        for marker in ("HornerOCS", "Allocated", "%AI1", "%AQ1"):
            assert marker in hdr["horner_markers"]


class TestSyntheticCfbfProject:
    """Validates synthetic minimal CFBF generation and round-trip inspection."""

    def test_synthetic_minimal_cfbf_generation(self, tmp_path):
        """Generates and inspects synthetic CFBF container."""
        raw = generate_minimal_cfbf_bytes("SynthProj", "10.2.751.4")
        assert raw[:8] == CFBF_MAGIC

        csp_path = tmp_path / "SynthProj.csp"
        csp_path.write_bytes(raw)

        info = inspect_project_file(csp_path)
        assert info.is_valid_cfbf is True
        assert info.sector_size == 512
        assert info.has_contents_stream is True
        assert info.cscape_version == "10.2.751.4"
        assert "HornerOCS" in info.horner_markers
        assert "%AI1" in info.horner_markers
        assert "%AQ1" in info.horner_markers

    def test_synthetic_pure_parser_roundtrip(self):
        """Tests pure Python OLE2 parser on synthetic CFBF."""
        data = generate_minimal_cfbf_bytes("PureParserProj", "10.2.751.4")
        entries, streams = parse_cfbf_pure(data)

        entry_names = [e["name"] for e in entries]
        assert "Root Entry" in entry_names
        assert "Contents" in entry_names
        assert "Contents" in streams
        assert len(streams["Contents"]) == 4096


class TestCfbfFailClosedAndRobustness:
    """Ensures fail-closed security and error handling on corrupted/invalid files."""

    def test_nonexistent_file_handling(self, tmp_path):
        """Inspect non-existent file raises FileNotFoundError."""
        bogus = tmp_path / "nonexistent_project.csp"
        with pytest.raises(FileNotFoundError) as exc_info:
            inspect_project_file(bogus)
        assert "does not exist" in str(exc_info.value).lower()

    def test_empty_file_handling(self, tmp_path):
        """Empty 0-byte file raises ValueError."""
        empty = tmp_path / "empty.csp"
        empty.write_bytes(b"")
        with pytest.raises(ValueError) as exc_info:
            inspect_project_file(empty)
        assert "0 bytes" in str(exc_info.value).lower()

    def test_invalid_magic_handling(self, tmp_path):
        """File with invalid header magic raises ValueError."""
        corrupt = tmp_path / "corrupt.csp"
        corrupt.write_bytes(b"NOT_CFBF_HEADER_DATA_12345678" * 20)
        with pytest.raises(ValueError) as exc_info:
            inspect_project_file(corrupt)
        assert "not a valid cscape compound file" in str(exc_info.value).lower()

    def test_pure_parser_truncated_raises_value_error(self):
        """parse_cfbf_pure raises ValueError on data under 512 bytes."""
        with pytest.raises(ValueError) as exc_info:
            parse_cfbf_pure(bytes.fromhex("d0cf11e0") * 5)
        assert "too short" in str(exc_info.value)


class TestProjectManagerCfbfIntegration:
    """Verifies CscapeLiveProjectManager CFBF inspection integration."""

    def test_project_manager_inspect_native_sample(self):
        """CscapeLiveProjectManager inspects native project file correctly."""
        if not NATIVE_CSP_PATH.exists():
            pytest.skip(f"Sample not found at {NATIVE_CSP_PATH}")

        info = CscapeLiveProjectManager.inspect_project_file(NATIVE_CSP_PATH)
        assert isinstance(info, ProjectFileInfo)
        assert info.is_valid_cfbf is True
        assert info.cscape_version == "10.2.751.4"
        assert "HornerOCS" in info.horner_markers

    def test_zero_straton_runtime_dependencies(self):
        """Ensures zero Straton K5 tools/runtimes are required for CFBF inspection."""
        import psutil
        procs = [p.info["name"] for p in psutil.process_iter(["name"]) if p.info["name"] and any(x in p.info["name"].lower() for x in ["t5simul", "t5rti"])]
        assert len(procs) == 0, f"Forbidden Straton runtime processes running: {procs}"
