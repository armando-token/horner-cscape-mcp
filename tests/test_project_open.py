"""Verification test suite for open_project and cscape_open_project in src.cscape.project_manager.

Verifies:
1. When Cscape is not running, does NOT fake live GUI open: returns
   offline_validated=True, live_gui_opened=False, open_mode="offline_validated".
2. ProjectOpenResult data model and to_dict() contract including offline/live fields.
3. Fail-closed rejection of nonexistent, corrupted, empty, or unsupported files.
4. Fail-closed behavior on require_live_gui=True when Cscape GUI is offline.
5. Accurate CFBF OLE2 compound file inspection on authentic .csp files.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
import pytest

from src.cscape.project_manager import (
    CscapeLiveProjectManager,
    ProjectOpenResult,
    open_project,
    cscape_open_project,
    CscapeProjectError,
    CscapeAutomationError,
)
from src.cscape.cfbf import generate_minimal_cfbf_bytes

SCRATCH_DIR = Path(r"C:\HornerAI\horner-cscape-mcp\scratch")


@pytest.fixture
def temp_project_dir():
    """Provides a temporary project directory inside scratch."""
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    p = SCRATCH_DIR / f"test_open_{uuid.uuid4().hex[:8]}"
    p.mkdir(parents=True, exist_ok=True)
    yield p
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)


class TestProjectOpenEngine:
    """Tests for project opening and verification."""

    def test_open_project_offline_validation_when_cscape_not_running(self, temp_project_dir, monkeypatch):
        """Mandate: When Cscape is not running, do not fake live GUI open. Verify offline_validated=True, live_gui_opened=False."""
        monkeypatch.setattr("src.cscape.project_manager.resolve_cscape_pid", lambda *a, **kw: None)
        monkeypatch.setattr(CscapeLiveProjectManager, "find_running_cscape_pid", lambda *a, **kw: None)

        csp_file = temp_project_dir / "OfflineProject.csp"
        csp_file.write_bytes(generate_minimal_cfbf_bytes(cscape_version="10.2.751.4"))

        # Test high-level open_project (returns ProjectOpenResult)
        result = open_project(csp_file, read_only=True)
        assert isinstance(result, ProjectOpenResult)
        assert result.success is True
        assert result.offline_validated is True
        assert result.live_gui_opened is False
        assert result.open_mode == "offline_validated"
        assert result.cscape_pid is None
        assert result.main_hwnd is None

        # Test to_dict representation
        d = result.to_dict()
        assert d["success"] is True
        assert d["offline_validated"] is True
        assert d["live_gui_opened"] is False
        assert d["open_mode"] == "offline_validated"

        # Test cscape_open_project (returns dict)
        dict_res = cscape_open_project(csp_file, read_only=True)
        assert dict_res["success"] is True
        assert dict_res["is_valid_cfbf"] is True
        assert dict_res["offline_validated"] is True
        assert dict_res["live_gui_opened"] is False
        assert dict_res["open_mode"] == "offline_validated"
        assert "offline" in dict_res["message"].lower()

    def test_open_project_require_live_gui_fails_closed_when_offline(self, temp_project_dir, monkeypatch):
        """Mandate: If require_live_gui=True and live Cscape is not running, must fail closed."""
        monkeypatch.setattr("src.cscape.project_manager.resolve_cscape_pid", lambda *a, **kw: None)
        monkeypatch.setattr(CscapeLiveProjectManager, "find_running_cscape_pid", lambda *a, **kw: None)

        csp_file = temp_project_dir / "LiveReqProject.csp"
        csp_file.write_bytes(generate_minimal_cfbf_bytes(cscape_version="10.2.751.4"))

        # open_project raises CscapeAutomationError
        with pytest.raises(CscapeAutomationError, match="FAIL-CLOSED: Live Cscape GUI is not running"):
            open_project(csp_file, require_live_gui=True)

        # cscape_open_project returns failure dict
        res = cscape_open_project(csp_file, require_live_gui=True)
        assert res["success"] is False
        assert res["offline_validated"] is False
        assert res["live_gui_opened"] is False
        assert "FAIL-CLOSED" in res["message"]

    def test_open_project_when_cscape_running_but_project_not_active(self, temp_project_dir, monkeypatch):
        """When Cscape is running but project is not loaded in GUI, do not fake live GUI open."""
        monkeypatch.setattr("src.cscape.project_manager.resolve_cscape_pid", lambda *a, **kw: 99999)
        monkeypatch.setattr(CscapeLiveProjectManager, "find_running_cscape_pid", lambda *a, **kw: 99999)
        monkeypatch.setattr(CscapeLiveProjectManager, "is_project_open", lambda *a, **kw: False)

        csp_file = temp_project_dir / "InactiveInGui.csp"
        csp_file.write_bytes(generate_minimal_cfbf_bytes(cscape_version="10.2.751.4"))

        result = open_project(csp_file, read_only=True)
        assert result.success is True
        assert result.offline_validated is True
        assert result.live_gui_opened is False
        assert result.open_mode == "offline_validated"

        # If require_live_gui=True, fails closed because it's not active in GUI
        with pytest.raises(CscapeAutomationError, match="FAIL-CLOSED: Project .* is not active in live Cscape GUI"):
            open_project(csp_file, require_live_gui=True)

        res = cscape_open_project(csp_file, require_live_gui=True)
        assert res["success"] is False
        assert "FAIL-CLOSED" in res["message"]

    def test_open_project_rejects_nonexistent_file(self, temp_project_dir):
        """Nonexistent file must raise FileNotFoundError in open_project and return success=False in cscape_open_project."""
        nonexistent = temp_project_dir / "GhostProject.csp"

        with pytest.raises(FileNotFoundError):
            open_project(nonexistent)

        res = cscape_open_project(nonexistent)
        assert res["success"] is False
        assert res["is_valid_cfbf"] is False
        assert "does not exist" in res["message"]

    def test_open_project_rejects_corrupted_cfbf(self, temp_project_dir):
        """File with invalid CFBF magic header must fail closed."""
        corrupt = temp_project_dir / "Corrupted.csp"
        corrupt.write_bytes(b"INVALID_MAGIC_HEADER_BYTES_NOT_CFBF_CONTENT")

        with pytest.raises(CscapeProjectError, match="not a valid CFBF"):
            open_project(corrupt)

        res = cscape_open_project(corrupt)
        assert res["success"] is False
        assert res["is_valid_cfbf"] is False

    def test_open_project_rejects_empty_file(self, temp_project_dir):
        """0-byte file must fail closed."""
        empty = temp_project_dir / "Empty.csp"
        empty.write_bytes(b"")

        with pytest.raises(CscapeProjectError):
            open_project(empty)

        res = cscape_open_project(empty)
        assert res["success"] is False
        assert res["is_valid_cfbf"] is False

    def test_open_project_rejects_unsupported_extensions(self, temp_project_dir):
        """Unsupported extensions (e.g. .k5p, .txt) must fail closed."""
        k5p = temp_project_dir / "Legacy.k5p"
        k5p.write_bytes(b"dummy")

        with pytest.raises(CscapeProjectError, match="Unsupported file extension"):
            open_project(k5p)

        res = cscape_open_project(k5p)
        assert res["success"] is False
        assert res["status"] in ("failed", "error")
        assert "Unsupported extension" in res["message"]

    def test_cscape_open_project_reports_honest_status_and_modes(self, temp_project_dir, monkeypatch):
        """Verify cscape_open_project explicitly returns status='success', offline_validated=True, live_gui_opened=False."""
        monkeypatch.setattr("src.cscape.project_manager.resolve_cscape_pid", lambda *a, **kw: None)

        csp_file = temp_project_dir / "HonestOffline.csp"
        csp_file.write_bytes(generate_minimal_cfbf_bytes(cscape_version="10.2.751.4"))

        res = cscape_open_project(csp_file, read_only=True)
        assert res["success"] is True
        assert res["status"] == "success"
        assert res["offline_validated"] is True
        assert res["live_gui_opened"] is False
        assert res["open_mode"] == "offline_validated"
        assert res["error_count"] == 0
        assert res["errors"] == []

    def test_cscape_open_project_require_live_gui_status_blocked(self, temp_project_dir, monkeypatch):
        """Verify require_live_gui=True when offline returns status='blocked' (or 'failed'), never fakes live success."""
        monkeypatch.setattr("src.cscape.project_manager.resolve_cscape_pid", lambda *a, **kw: None)

        csp_file = temp_project_dir / "BlockedLiveReq.csp"
        csp_file.write_bytes(generate_minimal_cfbf_bytes(cscape_version="10.2.751.4"))

        res = cscape_open_project(csp_file, require_live_gui=True)
        assert res["success"] is False
        assert res["status"] in ("blocked", "failed")
        assert res["offline_validated"] is False
        assert res["live_gui_opened"] is False
        assert res["error_count"] >= 1
        assert len(res["errors"]) >= 1
        assert "FAIL-CLOSED" in res["message"]

    def test_cscape_open_project_nonexistent_status_failed(self, temp_project_dir):
        """Nonexistent project file returns status='failed' or 'error' and error_count >= 1."""
        ghost = temp_project_dir / "NonExistentGhost.csp"
        res = cscape_open_project(ghost)
        assert res["success"] is False
        assert res["status"] in ("failed", "error")
        assert res["error_count"] >= 1
        assert len(res["errors"]) >= 1
        assert "does not exist" in res["message"]

    def test_mcp_cscape_open_project_tool(self, temp_project_dir, monkeypatch):
        """Verify cscape_open_project in src.mcp.tools satisfies fail-closed status contract."""
        from src.mcp.tools import cscape_open_project as mcp_open
        monkeypatch.setattr("src.cscape.project_manager.resolve_cscape_pid", lambda *a, **kw: None)

        # 1. Nonexistent file fails-closed
        res_ghost = mcp_open(str(temp_project_dir / "Ghost_404.csp"))
        assert res_ghost["success"] is False
        assert res_ghost["status"] in ("failed", "error")
        assert len(res_ghost["errors"]) >= 1

        # 2. Valid file offline succeeds
        csp_file = temp_project_dir / "MCPOffline.csp"
        csp_file.write_bytes(generate_minimal_cfbf_bytes(cscape_version="10.2.751.4"))
        res_valid = mcp_open(str(csp_file))
        assert res_valid["success"] is True
        assert res_valid["status"] == "success"
        assert res_valid["offline_validated"] is True
        assert res_valid["live_gui_opened"] is False

        # 3. require_live_gui=True when offline fails-closed
        res_live_req = mcp_open(str(csp_file), require_live_gui=True)
        assert res_live_req["success"] is False
        assert res_live_req["status"] in ("blocked", "failed", "error")
        assert res_live_req["offline_validated"] is False
        assert res_live_req["live_gui_opened"] is False

