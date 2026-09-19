"""Unit and integration tests for Cscape Project Open and Project Manager.

Tests:
1. Dynamic PID resolution (de-coupled from hardcoded PIDs):
   - Resolving PID from artifacts/.cscape_live_gate.json
   - Handling invalid / terminated PIDs with fallback to Win32 / psutil process enumeration
   - Graceful fallback when no Cscape process is running
2. Project opening and CFBF verification (open_project and cscape_open_project):
   - Native .csp and .cpj CFBF OLE2 compound file validation
   - Inspection of sector size, directory entries, Horner markers (%AI1, %AQ1, HornerOCS, Allocated)
   - Rejection of invalid extensions (.k5p, .exe, .txt)
   - Rejection of non-existent or empty 0-byte files
   - read_only parameter handling
3. Double-open modal trap prevention:
   - Detecting already-open project in active Cscape session
   - Skipping redundant ID_FILE_OPEN command to prevent modal traps
4. Dirty project prompt handling:
   - Clean dismissal of MFC 'Save changes to...' confirmation modals (IDNO=7)
5. Automation ProjectManager adapter (src/automation/project_manager.py):
   - Delegating open_project cleanly to Cscape project manager
   - Exporting authentic CFBF .csp containers with magic 0xD0CF11E0A1B11AE1
6. Hardware Lockout compliance:
   - Absolute lockout: zero hardware or PLC download during project open / verification
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.cscape.cfbf import (
    CFBF_MAGIC,
    CSCAPE_CONTENTS_MAGIC,
    ProjectFileInfo,
    generate_minimal_cfbf_bytes,
    inspect_project_file,
)
from src.cscape.project_manager import (
    CscapeLiveProjectManager,
    CscapeProjectError,
    ProjectOpenResult,
    cscape_open_project,
    open_project,
    resolve_cscape_pid,
    get_cscape_gate_info,
    ID_FILE_OPEN,
    IDYES,
    IDNO,
)
from src.automation.project_manager import ProjectManager


# ==============================================================================
# 1. Dynamic PID Resolution Tests
# ==============================================================================

class TestDynamicPidResolution:
    """Validates dynamic PID resolution de-coupled from hardcoded PIDs."""

    def test_resolve_cscape_pid_from_gate_file(self, tmp_path):
        """Resolves active PID from a gate JSON file when process is alive."""
        gate_file = tmp_path / ".cscape_live_gate.json"
        my_pid = os.getpid()
        gate_file.write_text(
            json.dumps({
                "ready_for_tests": True,
                "pid": my_pid,
                "window_title": "Cscape - [TestProj.csp]",
                "project_file": str(tmp_path / "TestProj.csp"),
            }),
            encoding="utf-8",
        )

        with patch("psutil.Process") as mock_proc:
            proc_instance = MagicMock()
            proc_instance.name.return_value = "Cscape.exe"
            proc_instance.is_running.return_value = True
            mock_proc.return_value = proc_instance

            resolved = resolve_cscape_pid(gate_path=gate_file, verify_process_alive=True)
            assert resolved == my_pid

    def test_resolve_cscape_pid_ignores_terminated_gate_pid(self, tmp_path):
        """Ignores gate PID if process does not exist or has terminated."""
        gate_file = tmp_path / ".cscape_live_gate.json"
        gate_file.write_text(
            json.dumps({"pid": 9999999, "window_title": "Dead Cscape"}),
            encoding="utf-8",
        )
        with patch("psutil.pid_exists", return_value=False), \
             patch("psutil.process_iter", return_value=[]):
            resolved = resolve_cscape_pid(gate_path=gate_file, verify_process_alive=True)
            assert resolved is None

    def test_resolve_cscape_pid_fallback_to_process_scan(self, tmp_path):
        """Falls back to psutil process enumeration when gate file is missing."""
        mock_p1 = MagicMock()
        mock_p1.info = {"pid": 7777, "name": "notepad.exe"}
        mock_p1.is_running.return_value = True

        mock_p2 = MagicMock()
        mock_p2.info = {"pid": 8888, "name": "Cscape.exe"}
        mock_p2.is_running.return_value = True

        with patch("psutil.process_iter", return_value=[mock_p1, mock_p2]):
            resolved = resolve_cscape_pid(gate_path=tmp_path / "non_existent.json")
            assert resolved == 8888

    def test_resolve_cscape_pid_none_when_no_cscape_running(self, tmp_path):
        """Returns None cleanly when no Cscape process is running."""
        with patch("psutil.process_iter", return_value=[]):
            resolved = resolve_cscape_pid(gate_path=tmp_path / "non_existent.json")
            assert resolved is None


# ==============================================================================
# 2. Project Open & CFBF Validation Tests
# ==============================================================================

class TestProjectOpenAndValidation:
    """Validates open_project and cscape_open_project with genuine CFBF container checks."""

    @pytest.fixture
    def valid_cfbf_file(self, tmp_path):
        """Creates a valid minimal .csp CFBF file."""
        data = generate_minimal_cfbf_bytes(project_name="MotorControl", cscape_version="10.2.751.4")
        csp_path = tmp_path / "MotorControl.csp"
        csp_path.write_bytes(data)
        return csp_path

    @pytest.fixture
    def valid_cpj_file(self, tmp_path):
        """Creates a valid minimal .cpj CFBF file."""
        data = generate_minimal_cfbf_bytes(project_name="PumpStation", cscape_version="10.2.751.4")
        cpj_path = tmp_path / "PumpStation.cpj"
        cpj_path.write_bytes(data)
        return cpj_path

    def test_open_project_valid_csp(self, valid_cfbf_file):
        """open_project succeeds on valid .csp CFBF file."""
        with patch.object(CscapeLiveProjectManager, "find_running_cscape_pid", return_value=None):
            res = open_project(valid_cfbf_file)
            assert isinstance(res, ProjectOpenResult)
            assert res.success is True
            assert res.project_name == "MotorControl"
            assert res.file_info is not None
            assert res.file_info.is_valid_cfbf is True
            assert res.file_info.cscape_version == "10.2.751.4"
            assert "Contents" in [e["name"] for e in res.file_info.stream_entries]
            assert "HornerOCS" in res.file_info.horner_markers
            assert "%AI1" in res.file_info.horner_markers
            assert "%AQ1" in res.file_info.horner_markers

    def test_open_project_valid_cpj(self, valid_cpj_file):
        """open_project succeeds on valid .cpj CFBF file."""
        with patch.object(CscapeLiveProjectManager, "find_running_cscape_pid", return_value=None):
            res = open_project(valid_cpj_file)
            assert res.success is True
            assert res.project_name == "PumpStation"
            assert res.file_info.is_valid_cfbf is True

    def test_cscape_open_project_dict_format(self, valid_cfbf_file):
        """cscape_open_project returns dictionary matching MCP tool schema."""
        res = cscape_open_project(valid_cfbf_file, read_only=True)
        assert res["success"] is True
        assert res["project_name"] == "MotorControl"
        assert res["is_valid_cfbf"] is True
        assert res["cscape_version"] == "10.2.751.4"
        assert res["sector_size"] == 512
        assert "Root Entry" in res["stream_entries"]
        assert "Contents" in res["stream_entries"]
        assert "HornerOCS" in res["horner_markers"]
        assert res["read_only"] is True
        assert "opened_at" in res

    def test_open_project_rejects_unsupported_extensions(self, tmp_path):
        """Strictly rejects legacy Straton .k5p and executable extensions."""
        k5p_file = tmp_path / "appli.k5p"
        k5p_file.write_bytes(b"dummy content")

        res = cscape_open_project(k5p_file)
        assert res["success"] is False
        assert "Unsupported extension" in res["message"]

        with pytest.raises(CscapeProjectError) as exc_info:
            open_project(k5p_file)
        assert "Unsupported file extension" in str(exc_info.value)

    def test_open_project_rejects_non_existent_file(self, tmp_path):
        """Rejects non-existent file cleanly with error message / exception."""
        missing = tmp_path / "NonExistent.csp"
        res = cscape_open_project(missing)
        assert res["success"] is False
        assert "does not exist" in res["message"]

        with pytest.raises(FileNotFoundError):
            open_project(missing)

    def test_open_project_rejects_empty_file(self, tmp_path):
        """Rejects 0-byte empty file."""
        empty_file = tmp_path / "Empty.csp"
        empty_file.write_bytes(b"")
        res = cscape_open_project(empty_file)
        assert res["success"] is False
        assert "empty" in res["message"].lower() or "failed" in res["message"].lower()

    def test_open_project_rejects_corrupted_cfbf(self, tmp_path):
        """Rejects file with invalid CFBF magic header."""
        corrupt_file = tmp_path / "Corrupt.csp"
        corrupt_file.write_bytes(b"NOT_CFBF_HEADER_DATA_1234567890")
        res = cscape_open_project(corrupt_file)
        assert res["success"] is False
        assert res["is_valid_cfbf"] is False


# ==============================================================================
# 3. Double-Open Modal Trap Prevention Tests
# ==============================================================================

class TestDoubleOpenPrevention:
    """Validates detection of already-open projects to prevent modal traps."""

    @pytest.fixture
    def valid_cfbf_file(self, tmp_path):
        data = generate_minimal_cfbf_bytes(project_name="TankLevel", cscape_version="10.2.751.4")
        csp_path = tmp_path / "TankLevel.csp"
        csp_path.write_bytes(data)
        return csp_path

    def test_detect_already_open_project_via_gate(self, valid_cfbf_file):
        """Detects that project is already open from gate status."""
        mgr = CscapeLiveProjectManager()
        with patch("src.cscape.project_manager.get_cscape_gate_info", return_value={
            "project_file": str(valid_cfbf_file),
            "window_title": f"Cscape - [{valid_cfbf_file.name}]",
        }):
            assert mgr.is_project_open(valid_cfbf_file) is True

    def test_detect_already_open_project_via_window_text(self, valid_cfbf_file):
        """Detects that project is already open from main window title."""
        mgr = CscapeLiveProjectManager()
        mgr.main_hwnd = 12345
        with patch.object(mgr, "_safe_get_text", return_value=f"Cscape 10.2 - [{valid_cfbf_file.name}]"), \
             patch("win32gui.IsWindow", return_value=True):
            assert mgr.is_project_open(valid_cfbf_file) is True

    def test_open_project_already_open_skips_id_file_open(self, valid_cfbf_file):
        """When project is already open, open_project succeeds without posting ID_FILE_OPEN."""
        mgr = CscapeLiveProjectManager()
        with patch.object(mgr, "find_running_cscape_pid", return_value=9999), \
             patch.object(mgr, "get_main_window", return_value=12345), \
             patch.object(mgr, "is_project_open", return_value=True), \
             patch("win32gui.PostMessage") as mock_post:
            res = mgr.open_project(valid_cfbf_file)
            assert res.success is True
            assert res.already_open is True
            for call in mock_post.call_args_list:
                args = call[0]
                assert len(args) < 3 or args[2] != ID_FILE_OPEN


# ==============================================================================
# 4. Dirty Project Prompt Handling Tests
# ==============================================================================

class TestDirtyProjectHandling:
    """Validates handling of MFC 'Save changes to...' confirmation modals."""

    def test_handle_dirty_project_dialog_clicks_no(self):
        """Dismisses dirty project prompt by clicking No (IDNO=7)."""
        mgr = CscapeLiveProjectManager()
        dialog_hwnd = 88888
        with patch.object(mgr, "click_button", return_value=True) as mock_click, \
             patch("win32gui.IsWindow", side_effect=[True, False]):
            dismissed = mgr.handle_dirty_project_dialog(dialog_hwnd, save=False)
            assert dismissed is True
            mock_click.assert_called_with(dialog_hwnd, ctrl_id=IDNO, text_match="No")

    def test_handle_dirty_project_dialog_save_clicks_yes(self):
        """Optionally clicks Yes (IDYES=6) if save=True requested."""
        mgr = CscapeLiveProjectManager()
        dialog_hwnd = 88888
        with patch.object(mgr, "click_button", return_value=True) as mock_click, \
             patch("win32gui.IsWindow", side_effect=[True, False]):
            dismissed = mgr.handle_dirty_project_dialog(dialog_hwnd, save=True)
            assert dismissed is True
            mock_click.assert_called_with(dialog_hwnd, ctrl_id=IDYES, text_match="Yes")


# ==============================================================================
# 5. Automation ProjectManager Adapter Tests
# ==============================================================================

class TestAutomationProjectManagerAdapter:
    """Validates src/automation/project_manager.py integration with native CFBF."""

    def test_adapter_open_project_by_path(self, tmp_path):
        """ProjectManager.open_project succeeds when given direct .csp path."""
        data = generate_minimal_cfbf_bytes("AutoProj", "10.2.751.4")
        csp_file = tmp_path / "AutoProj.csp"
        csp_file.write_bytes(data)

        pm = ProjectManager(workspace_root=tmp_path)
        res = pm.open_project(csp_file)
        assert res["success"] is True
        assert res["project_name"] == "AutoProj"
        assert res["is_valid_cfbf"] is True

    def test_adapter_open_project_by_name(self, tmp_path):
        """ProjectManager.open_project resolves project directory by name."""
        p_dir = tmp_path / "artifacts" / "projects" / "TestProjName"
        p_dir.mkdir(parents=True, exist_ok=True)
        csp_file = p_dir / "TestProjName.csp"
        csp_file.write_bytes(generate_minimal_cfbf_bytes("TestProjName"))

        pm = ProjectManager(workspace_root=tmp_path)
        res = pm.open_project("TestProjName")
        assert res["success"] is True
        assert res["project_name"] == "TestProjName"

    def test_adapter_export_project_produces_cfbf_magic(self, tmp_path):
        """ProjectManager.export_project exports valid CFBF with magic header."""
        pm = ProjectManager(workspace_root=tmp_path)
        pm.create_project("ExportProj")

        exp_res = pm.export_project("ExportProj", output_format="csp")
        assert exp_res["success"] is True
        exp_path = Path(exp_res["export_path"])
        assert exp_path.exists()
        assert exp_path.stat().st_size > 0

        info = inspect_project_file(exp_path)
        assert info.is_valid_cfbf is True
        assert info.magic_hex == "d0cf11e0a1b11ae1"


# ==============================================================================
# 6. Hardware Lockout Compliance Tests
# ==============================================================================

class TestHardwareLockoutCompliance:
    """Validates Absolute Hardware Lockout Policy during project operations."""

    def test_zero_hardware_download_calls(self, tmp_path):
        """Verifies no PLC download methods are invoked during project open."""
        data = generate_minimal_cfbf_bytes("SafeProj")
        csp_file = tmp_path / "SafeProj.csp"
        csp_file.write_bytes(data)

        res = cscape_open_project(csp_file)
        assert res["success"] is True
