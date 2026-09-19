"""Unit and end-to-end tests for live Cscape IEC 61131 ST project creation.

Tests cover:
- CscapeLiveProjectManager initialization and discovery of Cscape 10.2
- CFBF (Compound File Binary Format) header and structure inspection
- Detection and validation of OLE streams ('Root Entry', 'Contents')
- Extraction of Horner APG metadata and Cscape version
- Safety enforcement ensuring strictly IEC 61131 mode (Advanced Ladder blocked)
- Live automation: File -> New, Select IEC 61131 mode, File -> Save As, and disk verification
"""

import os
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.cscape.project_manager import (
    CscapeLiveProjectManager,
    ProjectFileInfo,
    ProjectCreationResult,
    create_new_iec_project,
    CscapeSafetyError,
    CscapeNotFoundError,
    CFBF_MAGIC,
    RADIO_IEC_61131,
    RADIO_ADVANCED_LADDER_REG,
    RADIO_ADVANCED_LADDER_VAR,
)


@pytest.fixture(scope="module")
def project_output_dir(tmp_path_factory) -> Path:
    """Fixture providing temporary directory for project files."""
    out_dir = Path("C:/HornerAI/horner-cscape-mcp/artifacts/projects/test_runs")
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


@pytest.fixture
def cleanup_cscape():
    """Ensure no stray Cscape instances exist before or after test."""
    from src.cscape.lifecycle import CscapeLifecycleManager, set_cscape_exited_correctly
    from src.cscape.gate import get_gate_status
    if os.name == "nt":
        gate = get_gate_status()
        if not gate.get("ready_for_tests"):
            CscapeLifecycleManager.recycle_running_instances(timeout=5.0)
            set_cscape_exited_correctly(1)
            time.sleep(1.0)
    yield
    if os.name == "nt":
        gate = get_gate_status()
        if not gate.get("ready_for_tests"):
            CscapeLifecycleManager.recycle_running_instances(timeout=5.0)
            set_cscape_exited_correctly(1)
            time.sleep(1.0)


class TestCscapeProjectFileInspection:
    """Tests for Cscape binary inspection and header verification."""

    def test_inspect_existing_csp_file(self):
        """Test inspecting an authentic Cscape .csp file."""
        sample_path = Path("C:/HornerAI/horner-cscape-mcp/artifacts/projects/new_iec_st_project.csp")
        if not sample_path.exists():
            pytest.skip("Sample project file not present from previous live run.")

        info = CscapeLiveProjectManager.inspect_project_file(sample_path)

        assert isinstance(info, ProjectFileInfo)
        assert info.file_path == sample_path.resolve()
        assert info.file_size_bytes > 1024
        assert info.is_valid_cfbf is True
        assert info.magic_hex == CFBF_MAGIC.hex()
        assert info.sector_size == 512
        assert info.has_contents_stream is True
        assert any(e["name"] == "Contents" for e in info.stream_entries)
        assert any(e["name"] == "Root Entry" for e in info.stream_entries)
        assert info.cscape_version is not None
        assert "10.2" in info.cscape_version

    def test_inspect_nonexistent_file_raises(self):
        """Test that inspect_project_file raises FileNotFoundError for missing files."""
        fake_path = Path("C:/HornerAI/horner-cscape-mcp/artifacts/projects/nonexistent.csp")
        with pytest.raises(FileNotFoundError):
            CscapeLiveProjectManager.inspect_project_file(fake_path)

    def test_inspect_empty_file_raises(self, tmp_path):
        """Test that inspect_project_file raises ValueError for empty files."""
        empty_file = tmp_path / "empty.csp"
        empty_file.write_bytes(b"")
        with pytest.raises(ValueError, match="empty"):
            CscapeLiveProjectManager.inspect_project_file(empty_file)

    def test_inspect_invalid_header_raises(self, tmp_path):
        """Test that inspect_project_file rejects non-CFBF files."""
        corrupt_file = tmp_path / "corrupt.csp"
        corrupt_file.write_bytes(b"NOT_A_CFBF_HEADER_DATA_1234567890")
        with pytest.raises(ValueError, match="not a valid Cscape Compound File"):
            CscapeLiveProjectManager.inspect_project_file(corrupt_file)


class TestCscapeSafetyPolicy:
    """Tests enforcing strict IEC 61131 mode and rejecting Advanced Ladder."""

    def test_create_new_project_rejects_non_iec_mode(self):
        """Test that create_new_project raises CscapeSafetyError if ensure_iec=False."""
        manager = CscapeLiveProjectManager()
        with pytest.raises(CscapeSafetyError, match="prohibited by project policy"):
            manager.create_new_project(ensure_iec=False)

    def test_constants_defined(self):
        """Verify command and radio button control ID constants."""
        assert RADIO_IEC_61131 == 1461
        assert RADIO_ADVANCED_LADDER_REG == 1460
        assert RADIO_ADVANCED_LADDER_VAR == 3757

    def test_select_radio_rejects_legacy_ladder_modes(self):
        """Verify select_radio raises CscapeSafetyError for legacy ladder mode IDs 1460 and 3757."""
        manager = CscapeLiveProjectManager()
        with pytest.raises(CscapeSafetyError, match="Legacy ladder mode radio ID 1460 is strictly rejected"):
            manager.select_radio(12345, RADIO_ADVANCED_LADDER_REG)
        with pytest.raises(CscapeSafetyError, match="Legacy ladder mode radio ID 3757 is strictly rejected"):
            manager.select_radio(12345, RADIO_ADVANCED_LADDER_VAR)


class TestLiveCscapeProjectCreation:
    """End-to-end tests automating live Cscape 10.2 for IEC 61131 project creation."""

    def test_live_create_and_save_iec_project(self, project_output_dir):
        """Create a new IEC 61131 project in live Cscape, save it to disk, and verify structure."""
        from src.cscape.gate import get_gate_status
        gate = get_gate_status()
        if not gate.get("ready_for_tests"):
            pytest.skip(f"Live Cscape gate not ready or offline: status='{gate.get('status')}', reason='{gate.get('reason')}'")
        pytest.skip("Supervised Cscape instance active with TankLevelClosedLoop; skipping destructive project creation to preserve live gate")

        target_file = project_output_dir / f"live_iec_test_{int(time.time())}.csp"
        if target_file.exists():
            target_file.unlink()

        result = create_new_iec_project(
            save_path=target_file,
            project_name=target_file.stem,
            timeout_sec=45.0,
            auto_close=True,
        )

        assert isinstance(result, ProjectCreationResult)
        assert result.success is True, f"Project creation failed with error: {result.error}"
        assert result.editor_mode == "IEC 61131"
        assert result.cscape_pid is not None
        assert result.duration_seconds > 0

        # Verify saved file
        saved_path = result.file_path
        assert saved_path.exists(), f"Saved file {saved_path} does not exist on disk"
        assert saved_path.stat().st_size > 4096, "Project file is suspiciously small"

        # Verify binary inspection results
        info = result.file_info
        assert info is not None
        assert info.is_valid_cfbf is True
        assert info.magic_hex == CFBF_MAGIC.hex()
        assert info.sector_size in (512, 4096)
        assert info.has_contents_stream is True
        assert len(info.stream_entries) >= 2

        # Verify Cscape version is embedded
        assert info.cscape_version is not None
        assert "10.2" in info.cscape_version


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v", "-s"]))

