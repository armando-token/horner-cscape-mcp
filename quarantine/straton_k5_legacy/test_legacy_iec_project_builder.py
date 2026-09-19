"""
Quarantined unit tests for legacy Straton K5 IEC Project Builder.
Isolated completely from active src/ and tests/ suites.
"""
import zipfile
import pytest
from pathlib import Path

from src.iec.st_generator import STGenerator
from quarantine.straton_k5_legacy.legacy_iec_project_builder import ProjectBuilder


class TestQuarantinedLegacyProjectBuilder:
    """Verifies quarantined Straton K5 project directory creation and assembly."""

    def test_create_project_files(self, tmp_path):
        pb = ProjectBuilder()
        proj_dir = tmp_path / "TestK5Project"
        pb.create_project(proj_dir, "TestK5Project", "Automated test project")

        assert (proj_dir / "appli.k5p").exists()
        assert (proj_dir / "appli.CPO").exists()
        assert (proj_dir / "appli.lge").exists()
        assert (proj_dir / "K5DBXS.INI").exists()
        assert (proj_dir / "Default" / "appli.txt").exists()
        assert (proj_dir / "project_manifest.json").exists()

        k5p_text = (proj_dir / "appli.k5p").read_text(encoding="utf-8")
        assert ";K5 project" in k5p_text
        assert "/G,GLOBAL" in k5p_text

    def test_add_program_and_synchronize_k5p(self, tmp_path):
        pb = ProjectBuilder()
        proj_dir = tmp_path / "K5SyncProj"
        pb.create_project(proj_dir, "K5SyncProj")

        motor_code = STGenerator.generate_motor_controller("FB_MotorA")
        st_file = pb.add_program(proj_dir, "FB_MotorA", motor_code)

        assert st_file.exists()
        assert st_file.name == "FB_MotorA.st"

        # Check /P registration in appli.k5p
        k5p_text = (proj_dir / "appli.k5p").read_text(encoding="utf-8")
        assert "/P,0,FB_MotorA" in k5p_text

        # Check variable registration in appli.txt
        appli_txt = (proj_dir / "Default" / "appli.txt").read_text(encoding="utf-8")
        assert "V-MotorRun=" in appli_txt
        assert "MotorRun:BOOL:=FALSE" in appli_txt

    def test_add_invalid_program_raises_error(self, tmp_path):
        pb = ProjectBuilder()
        proj_dir = tmp_path / "InvalidProj"
        pb.create_project(proj_dir, "InvalidProj")

        broken_code = "PROGRAM Broken VAR x : INT END_VAR x := 10; END_PROGRAM"
        with pytest.raises(ValueError, match="IEC ST validation failed"):
            pb.add_program(proj_dir, "Broken", broken_code, validate_first=True)

    def test_validate_and_summarize_project(self, tmp_path):
        pb = ProjectBuilder()
        proj_dir = tmp_path / "SummaryProj"
        pb.create_project(proj_dir, "SummaryProj")

        pb.add_program(proj_dir, "SM", STGenerator.generate_state_machine("Prog_SM", ["S1", "S2"]))
        pb.add_program(proj_dir, "PID", STGenerator.generate_pid_controller("FB_PID"))

        summary = pb.get_project_summary(proj_dir)
        assert summary["st_programs_count"] == 2
        assert summary["total_variables"] > 0
        assert summary["k5p_exists"] is True

        val_res = pb.validate_project(proj_dir)
        assert val_res["is_valid"] is True
        assert val_res["checked_files_count"] == 2

    def test_export_project_zip(self, tmp_path):
        pb = ProjectBuilder()
        proj_dir = tmp_path / "ZipProj"
        pb.create_project(proj_dir, "ZipProj")
        pb.add_program(proj_dir, "M1", STGenerator.generate_motor_controller("FB_M1"))

        zip_out = tmp_path / "ExportedProject.zip"
        pb.export_zip(proj_dir, zip_out)

        assert zip_out.exists()
        assert zip_out.stat().st_size > 0

        # Verify zip contents
        with zipfile.ZipFile(zip_out, "r") as zf:
            names = zf.namelist()
            assert any("appli.k5p" in n for n in names)
            assert any("FB_M1.st" in n or "M1.st" in n for n in names)
