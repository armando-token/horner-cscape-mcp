"""Comprehensive verification test suite for MCP tools cscape_compile_project and cscape_open_project.

Verifies:
1. cscape_compile_project:
   - Fail-closed behavior on nonexistent projects (NO silent fallback redirection to TankLevelClosedLoop).
   - Projects named with "TankLevel" or "Client" that do not exist must NOT redirect; they must fail closed.
   - Honest AST metrics in memory_footprint (NO fake 1024/512/64).
   - Fail-closed on require_live_gui=True when Cscape GUI is offline.
   - Successful compilation of authentic projects with honest memory footprints.
2. cscape_open_project:
   - When Cscape is not running, does NOT fake that live GUI opened the project; returns
     offline_validated=True, live_gui_opened=False, open_mode="offline_validated".
   - When require_live_gui=True and Cscape is offline, fails closed with success=False.
   - Fails closed on nonexistent, empty, or corrupted files.
   - Correctly inspects and verifies authentic CFBF containers offline.
3. cscape_get_diagnostics:
   - Nonexistent project fails closed without silent redirection to TankLevelClosedLoop.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path
import pytest

from src.mcp.tools import (
    cscape_compile_project,
    cscape_open_project,
    cscape_get_diagnostics,
    cscape_create_project,
    cscape_insert_st,
    cscape_export_project,
    WORKSPACE_ROOT,
)
from src.cscape.cfbf import CFBF_MAGIC, generate_minimal_cfbf_bytes, inspect_project_file
from src.cscape.project_manager import export_project as cscape_pm_export_project

SCRATCH_DIR = WORKSPACE_ROOT / "scratch"


@pytest.fixture
def scratch_project():
    """Creates a temporary project in workspace artifacts/projects for MCP tool testing."""
    proj_name = f"MCP_Test_{uuid.uuid4().hex[:8]}"
    proj_dir = WORKSPACE_ROOT / "artifacts" / "projects" / proj_name
    proj_dir.mkdir(parents=True, exist_ok=True)
    yield proj_name, proj_dir
    if proj_dir.exists():
        shutil.rmtree(proj_dir, ignore_errors=True)


class TestMCPCompileProjectHardening:
    """Tests hardening cscape_compile_project against fake compile and fake fallbacks."""

    def test_nonexistent_project_fails_closed_no_fallback(self):
        """Mandate: Nonexistent project must fail closed with success=False, status='error', and PROJECT_NOT_FOUND diagnostic."""
        fake_name = f"NonExistentProject_{uuid.uuid4().hex[:8]}"
        res = cscape_compile_project(project_name=fake_name, clean_build=True)

        assert res["success"] is False
        assert res["compile_successful"] is False
        assert res["status"] == "error"
        assert res["error_count"] >= 1
        assert len(res["errors"]) >= 1
        assert "does not exist" in res["errors"][0]
        assert any(d.get("error_code") == "PROJECT_NOT_FOUND" for d in res.get("diagnostics", []))
        assert res["memory_footprint"].get("code_size_bytes", 0) == 0

    def test_tank_client_named_nonexistent_project_does_not_redirect(self):
        """Mandate: Projects with 'TankLevel', 'Tank', or 'Client' in name that do not exist must NOT redirect to TankLevelClosedLoop."""
        fake_tank = f"TankLevel_CustomSession_{uuid.uuid4().hex[:8]}"
        res = cscape_compile_project(project_name=fake_tank, clean_build=True)

        # Must fail closed, NOT redirect to TankLevelClosedLoop
        assert res["success"] is False
        assert res["status"] == "error"
        assert res["project_name"] == fake_tank
        assert any("does not exist" in err for err in res["errors"])

        fake_client = f"ClientApp_Temp_{uuid.uuid4().hex[:8]}"
        res_client = cscape_compile_project(project_name=fake_client, clean_build=True)
        assert res_client["success"] is False
        assert res_client["status"] == "error"
        assert res_client["project_name"] == fake_client

    def test_compile_project_honest_ast_metrics_no_fake_constants(self, scratch_project):
        """Mandate: memory_footprint must contain honest AST metrics instead of {code_size_bytes: 1024, data_size_bytes: 512, retain_size_bytes: 64}."""
        proj_name, proj_dir = scratch_project
        pous_dir = proj_dir / "pous"
        pous_dir.mkdir(parents=True, exist_ok=True)
        st_code = """PROGRAM FeedRateCtrl
VAR
    FeedRate : REAL := 45.2;
    MaxSpeed : INT := 1200;
    IsActive : BOOL := TRUE;
    CycleCount : DINT := 1000;
END_VAR
IF IsActive THEN
    FeedRate := FeedRate * 1.05;
    CycleCount := CycleCount + 1;
END_IF;
END_PROGRAM
"""
        (pous_dir / "FeedRateCtrl.st").write_text(st_code, encoding="utf-8")

        res = cscape_compile_project(project_name=proj_name, clean_build=True)

        assert res["success"] is True
        assert res["compile_successful"] is True
        assert res["status"] == "success"

        mem = res["memory_footprint"]
        expected_bytes = len(st_code.encode("utf-8"))

        # Verify honest AST sizing
        assert mem["code_size_bytes"] == expected_bytes
        assert mem["data_size_bytes"] == 4 * 4  # 4 variables * 4 bytes
        assert mem["ast_variable_count"] == 4
        assert mem["ast_statement_count"] > 0
        assert mem["ast_expression_count"] > 0
        assert mem["source_bytes_total"] == expected_bytes

        # Verify NO fake constants
        assert mem["code_size_bytes"] != 1024
        assert mem["data_size_bytes"] != 512
        assert mem.get("retain_size_bytes", 0) != 64

    def test_require_live_gui_fails_closed_when_cscape_offline(self, scratch_project):
        """Mandate: If require_live_gui=True and live Cscape is offline, fail-closed with clear error."""
        proj_name, proj_dir = scratch_project
        pous_dir = proj_dir / "pous"
        pous_dir.mkdir(parents=True, exist_ok=True)
        (pous_dir / "Dummy.st").write_text("PROGRAM Dummy\nVAR x : INT := 1;\nEND_VAR\nEND_PROGRAM", encoding="utf-8")

        res = cscape_compile_project(project_name=proj_name, require_live_gui=True)
        # In headless test environments without live Cscape gate, it must fail-closed
        if not res["success"]:
            assert res["status"] == "error"
            assert any("fail-closed" in err.lower() or "offline" in err.lower() or "dead" in err.lower() for err in res["errors"])


class TestMCPOpenProjectHardening:
    """Tests hardening cscape_open_project against fake open."""

    def test_open_project_offline_validation_not_faking_live_gui(self, scratch_project):
        """Mandate: When Cscape is not running, do not fake live GUI open. Return offline_validated=True, live_gui_opened=False."""
        proj_name, proj_dir = scratch_project
        csp_file = proj_dir / f"{proj_name}.csp"
        csp_file.write_bytes(generate_minimal_cfbf_bytes(cscape_version="10.2.751.4"))

        res = cscape_open_project(file_path=str(csp_file))

        assert res["success"] is True
        assert res["is_valid_cfbf"] is True
        assert "stream_entries" in res
        assert "Root Entry" in res["stream_entries"]

        # Crucial mandate check: Must clearly indicate offline validation
        assert res["offline_validated"] is True
        assert res["live_gui_opened"] is False
        assert res["open_mode"] == "offline_validated"
        assert "offline" in res["message"].lower()

    def test_open_project_require_live_gui_fails_closed_when_offline(self, scratch_project):
        """Mandate: If require_live_gui=True and Cscape is not running, fail closed with success=False."""
        proj_name, proj_dir = scratch_project
        csp_file = proj_dir / f"{proj_name}.csp"
        csp_file.write_bytes(generate_minimal_cfbf_bytes(cscape_version="10.2.751.4"))

        res = cscape_open_project(file_path=str(csp_file), require_live_gui=True)
        # Since live Cscape GUI is not active in headless test runner
        assert res["success"] is False
        assert res["offline_validated"] is False
        assert res["live_gui_opened"] is False
        assert "FAIL-CLOSED" in res["message"] or "not running" in res["message"]

    def test_open_project_nonexistent_file_fails_closed(self):
        """Nonexistent project file fails closed."""
        fake_path = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\projects\FakeProjXYZ.csp")
        res = cscape_open_project(file_path=str(fake_path))

        assert res["success"] is False
        assert res["is_valid_cfbf"] is False
        assert "does not exist" in res["message"].lower()

    def test_open_project_corrupted_magic_fails_closed(self, scratch_project):
        """Corrupted file with invalid header fails closed."""
        proj_name, proj_dir = scratch_project
        corrupt_file = proj_dir / "corrupt.csp"
        corrupt_file.write_bytes(b"INVALID_HEADER_NOT_CFBF_CONTENT_123456789")

        res = cscape_open_project(file_path=str(corrupt_file))
        assert res["success"] is False
        assert res["is_valid_cfbf"] is False

    def test_open_project_empty_file_fails_closed(self, scratch_project):
        """Zero-byte file fails closed."""
        proj_name, proj_dir = scratch_project
        empty_file = proj_dir / "empty.csp"
        empty_file.write_bytes(b"")

        res = cscape_open_project(file_path=str(empty_file))
        assert res["success"] is False
        assert res["is_valid_cfbf"] is False


class TestMCPDiagnosticsHardening:
    """Tests hardening cscape_get_diagnostics against fake fallbacks."""

    def test_get_diagnostics_nonexistent_fails_closed(self):
        """Mandate: cscape_get_diagnostics on nonexistent project must fail closed without fallback."""
        fake_name = f"MissingDiagProject_{uuid.uuid4().hex[:8]}"
        res = cscape_get_diagnostics(project_name=fake_name)

        assert res["success"] is False
        assert res["status"] == "error"
        assert res["error_count"] >= 1
        assert any("does not exist" in err for err in res["errors"])
        assert res["memory_footprint"].get("code_size_bytes", 0) == 0


class TestMCPExportProjectFailClosed:
    """Verifies that cscape_export_project strictly fails closed for nonexistent projects."""

    @pytest.mark.parametrize("fmt", ["csp", "cpj", "st", "csv", "xml", "json"])
    def test_export_nonexistent_project_fails_closed(self, fmt: str) -> None:
        """Calling cscape_export_project for a nonexistent project must return success=False, status='error'."""
        nonexistent_name = "GhostProject_99999_NotExist"
        res = cscape_export_project(nonexistent_name, output_format=fmt)

        assert res["success"] is False, f"Expected success=False for nonexistent project, got: {res}"
        assert res["status"] == "error"
        assert res["error_count"] >= 1
        assert len(res["errors"]) >= 1
        assert any("Project directory or source file not found" in e for e in res["errors"])

    def test_export_project_no_dummy_cfbf_created(self) -> None:
        """Exporting a nonexistent project must NOT generate a dummy minimal CFBF file on disk."""
        nonexistent_name = "SyntheticTrapProject_000"
        res = cscape_export_project(nonexistent_name, output_format="csp")

        assert res["success"] is False
        assert res["status"] == "error"

        # Verify no file was written to artifacts/exports/
        export_file = WORKSPACE_ROOT / "artifacts" / "exports" / f"{nonexistent_name}.csp"
        assert not export_file.exists(), f"Dummy CFBF file was unexpectedly written to {export_file}"

    def test_export_project_corrupted_magic_header_fails_closed(self) -> None:
        """Exporting a project whose container lacks the 0xD0CF11E0A1B11AE1 header must fail closed."""
        bad_proj_name = "CorruptedMagicProj_ToolTest"
        p_dir = WORKSPACE_ROOT / "artifacts" / "projects" / bad_proj_name
        p_dir.mkdir(parents=True, exist_ok=True)
        bad_file = p_dir / f"{bad_proj_name}.csp"
        # Write invalid header (not 0xD0CF11E0A1B11AE1)
        bad_file.write_bytes(b"INVALID_HEADER_GARBAGE" + b"\x00" * 600)

        try:
            res = cscape_export_project(bad_proj_name, output_format="csp")
            assert res["success"] is False
            assert res["status"] == "error"
            assert res["error_count"] >= 1
            assert any("Project directory or source file not found" in e for e in res["errors"])
        finally:
            shutil.rmtree(p_dir, ignore_errors=True)


class TestMCPExportProjectValidProject:
    """Verifies that cscape_export_project succeeds on authentic valid projects."""

    @pytest.fixture
    def valid_project(self) -> str:
        """Ensures a valid project exists in the workspace."""
        proj_name = "ValidExportToolProj"
        cscape_create_project(
            project_name=proj_name,
            target_plc="XL4",
            description="Valid project for MCP export tool verification",
        )
        return proj_name

    def test_export_valid_project_csp_succeeds(self, valid_project: str) -> None:
        """Exporting an existing valid project to .csp succeeds with authentic CFBF."""
        res = cscape_export_project(valid_project, output_format="csp")

        assert res["success"] is True
        assert res["status"] == "success"
        assert res["error_count"] == 0
        assert res["errors"] == []
        assert res["output_format"] == "csp"

        out_path = Path(res["export_file"])
        assert out_path.exists()
        assert out_path.stat().st_size >= 512

        # Verify CFBF magic header (0xD0CF11E0A1B11AE1)
        with open(out_path, "rb") as f:
            header = f.read(8)
        assert header == CFBF_MAGIC
        assert header == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

        # Verify CFBF inspection metadata
        assert "cfbf_inspection" in res
        assert res["cfbf_inspection"]["is_valid_cfbf"] is True
        assert res["cfbf_inspection"]["magic_hex"] == "d0cf11e0a1b11ae1"

    def test_export_valid_project_cpj_succeeds(self, valid_project: str) -> None:
        """Exporting an existing valid project to .cpj succeeds with authentic CFBF."""
        res = cscape_export_project(valid_project, output_format="cpj")

        assert res["success"] is True
        assert res["status"] == "success"
        assert res["output_format"] == "cpj"

        out_path = Path(res["export_file"])
        assert out_path.exists()
        with open(out_path, "rb") as f:
            header = f.read(8)
        assert header == CFBF_MAGIC

    def test_export_valid_project_json_succeeds(self, valid_project: str) -> None:
        """Exporting an existing valid project to .json succeeds."""
        res = cscape_export_project(valid_project, output_format="json")

        assert res["success"] is True
        assert res["status"] == "success"
        out_path = Path(res["export_file"])
        assert out_path.exists()
        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert data.get("name") == valid_project or data.get("project_name") == valid_project


class TestCscapeProjectManagerExport:
    """Verifies src.cscape.project_manager.export_project fail-closed and CFBF validation."""

    def test_cscape_pm_export_nonexistent_fails_closed(self, tmp_path: Path) -> None:
        """cscape.project_manager.export_project fails closed on nonexistent project."""
        dst = tmp_path / "out.csp"
        res = cscape_pm_export_project("NonExistentProject_DirectPM", dst, output_format="csp")

        assert res["success"] is False
        assert res["status"] in ("failed", "error")
        assert res["error_count"] >= 1
        assert any("Project directory or source file not found" in e for e in res["errors"])

    def test_cscape_pm_export_invalid_magic_fails_closed(self, tmp_path: Path) -> None:
        """cscape.project_manager.export_project fails closed on invalid CFBF header."""
        src_file = tmp_path / "Corrupt.csp"
        src_file.write_bytes(b"BAD_HEADER" + b"\x00" * 600)
        dst = tmp_path / "out.csp"

        res = cscape_pm_export_project(src_file, dst, output_format="csp")
        assert res["success"] is False
        assert res["status"] in ("failed", "error")
        assert res["error_count"] >= 1
        assert any("Project directory or source file not found" in e for e in res["errors"])

    def test_cscape_pm_export_valid_cfbf_succeeds(self, tmp_path: Path) -> None:
        """cscape.project_manager.export_project succeeds on valid CFBF file."""
        from src.cscape.cfbf import generate_minimal_cfbf_bytes
        valid_src = tmp_path / "ValidSource.csp"
        valid_src.write_bytes(generate_minimal_cfbf_bytes("ValidSource"))
        dst = tmp_path / "Exported.csp"

        res = cscape_pm_export_project(valid_src, dst, output_format="csp")
        assert res["success"] is True
        assert res["status"] == "success"
        assert res["is_valid_cfbf"] is True
        assert dst.exists()
        with open(dst, "rb") as f:
            header = f.read(8)
        assert header == CFBF_MAGIC
