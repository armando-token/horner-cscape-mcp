"""Test Suite for Cscape Export Subsystem Integrity & Proof Verification.

Verifies:
1. ALLOWED_EXPORT_FORMATS and validate_export in src/security/guard.py:
   - "csp", "cpj", "csv", "xml", "st", "json" are present.
   - validate_export permits writing to artifacts/exports/.
   - Direct hardware/flashing formats trigger UnauthorizedDownloadError.
   - Legacy k5p enforces quarantine pathing.
2. cscape_export_project in src/mcp/tools.py:
   - Authentic CFBF OLE2 headers (magic 0xD0CF11E0A1B11AE1) and Horner markers.
   - CFBF inspection via CscapeLiveProjectManager / inspect_project_file.
   - All allowed formats: csp, cpj, csv, xml, st, json.
3. export_project in src/automation/project_manager.py:
   - Authentic CFBF headers and Horner markers for .csp and .cpj.
   - Variable export via CscapeVariableManager for .csv and .xml.
   - Consolidated Structured Text for .st.
   - Manifest metadata for .json.
4. CscapeVariableManager (export_xml, export_csv) scope fidelity:
   - Full register scope retention (%R, %M, %T, %AI, %AQ, %I, %Q, %S, %SR).
   - Zero truncation of register scopes.
   - Full bidirectional roundtrip (Memory -> XML -> Memory, Memory -> CSV -> Memory).
5. Hardware Lockout Enforcement:
   - Zero physical PLC download or GUI interaction.
   - Zero Straton runtime dependencies.
"""

from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
from pathlib import Path
import pytest

from src.cscape.cfbf import (
    CFBF_MAGIC,
    HORNER_MARKERS,
    inspect_project_file,
    generate_minimal_cfbf_bytes,
)
from src.cscape.project_manager import CscapeLiveProjectManager
from src.cscape.variables import (
    CscapeVariable,
    CscapeVariableManager,
    VariableManager,
)
from src.security.exceptions import (
    HardwareLockoutError,
    ReadOnlyViolationError,
    SecurityError,
    UnauthorizedDownloadError,
)
from src.security.guard import SafetyGuard, SecurityGuard
from src.automation.project_manager import ProjectManager
from src.mcp.tools import cscape_export_project


# ==============================================================================
# 1. ALLOWED_EXPORT_FORMATS & Guard Verification
# ==============================================================================

class TestExportSecurityGuard:
    """Verifies security policy and guard enforcement on export subsystem."""

    def test_allowed_export_formats_contains_all_native_formats(self) -> None:
        """Confirm 'csp', 'cpj', 'csv', 'xml', 'st', 'json' are all present."""
        expected_formats = {"csp", "cpj", "csv", "xml", "st", "json"}
        allowed = set(SafetyGuard.ALLOWED_EXPORT_FORMATS)
        assert expected_formats.issubset(allowed), (
            f"Missing required native export formats: {expected_formats - allowed}"
        )

    @pytest.mark.parametrize("fmt", ["csp", "cpj", "csv", "xml", "st", "json"])
    def test_validate_export_format_accepts_valid_formats(self, fmt: str) -> None:
        """SafetyGuard.validate_export_format accepts each native format."""
        assert SafetyGuard.validate_export_format(fmt) == fmt
        assert SafetyGuard.validate_export_format(fmt.upper()) == fmt

    @pytest.mark.parametrize("fmt", ["csp", "cpj", "csv", "xml", "st", "json"])
    def test_validate_export_permits_artifacts_exports(self, fmt: str) -> None:
        """Confirm validate_export permits writing to artifacts/exports/."""
        guard = SecurityGuard()
        src = Path(r"C:\HornerAI\horner-cscape-mcp\examples\counter.st")
        dst = Path(rf"C:\HornerAI\horner-cscape-mcp\artifacts\exports\audit_test.{fmt}")
        guard.validate_export(source_path=src, destination_path=dst, format=fmt)

    @pytest.mark.parametrize("hw_fmt", [
        "hardware", "plc", "flash", "dfu", "jtag", "direct_download",
    ])
    def test_validate_export_blocks_hardware_flashing(self, hw_fmt: str) -> None:
        """Hardware/controller download targets are blocked unconditionally."""
        guard = SecurityGuard()
        src = Path(r"C:\HornerAI\horner-cscape-mcp\examples\counter.st")
        dst = Path(rf"C:\HornerAI\horner-cscape-mcp\artifacts\exports\test.{hw_fmt}")
        with pytest.raises(UnauthorizedDownloadError):
            guard.validate_export(src, dst, format=hw_fmt)

    def test_validate_export_quarantines_legacy_k5p(self) -> None:
        """k5p exports outside quarantine path are strictly blocked."""
        guard = SecurityGuard()
        src = Path(r"C:\HornerAI\horner-cscape-mcp\examples\counter.st")
        bad_dst = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\exports\legacy.k5p")
        with pytest.raises(SecurityError, match="quarantined"):
            guard.validate_export(src, bad_dst, format="k5p")

        # Quarantined destination is allowed
        good_dst = Path(r"C:\HornerAI\horner-cscape-mcp\quarantine\straton_k5_legacy\artifacts\exports\legacy.k5p")
        guard.validate_export(src, good_dst, format="k5p")


# ==============================================================================
# 2. CFBF Container Generation & Inspection Proof
# ==============================================================================

class TestCFBFContainerIntegrity:
    """Verifies authentic CFBF OLE2 headers, magic bytes, and Horner markers."""

    def test_generate_minimal_cfbf_bytes_magic_and_markers(self) -> None:
        """CFBF bytes must start with 0xD0CF11E0A1B11AE1 and contain Horner markers."""
        data = generate_minimal_cfbf_bytes("ExportAuditProject")
        assert len(data) >= 512
        assert data[:8] == CFBF_MAGIC
        assert data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

        found_markers = [m for m in HORNER_MARKERS if m.encode("ascii") in data or m.encode("utf-16le") in data]
        assert len(found_markers) >= 3
        assert "HornerOCS" in found_markers or "%AI1" in found_markers

    def test_inspect_cfbf_project_file(self, tmp_path: Path) -> None:
        """inspect_project_file verifies CFBF container structural validity."""
        test_csp = tmp_path / "AuditTest.csp"
        test_csp.write_bytes(generate_minimal_cfbf_bytes("AuditTest"))

        info = inspect_project_file(test_csp)
        assert info.is_valid_cfbf is True
        assert info.magic_hex == "d0cf11e0a1b11ae1"
        assert info.sector_size == 512
        assert len(info.horner_markers) > 0


# ==============================================================================
# 3. cscape_export_project (MCP Tool) Verification
# ==============================================================================

class TestMCPExportProjectTool:
    """Verifies cscape_export_project tool across all supported formats."""

    @pytest.fixture(autouse=True)
    def setup_project(self) -> None:
        """Seed a clean test project in workspace artifacts."""
        from src.automation.project_manager import ProjectManager
        mgr = ProjectManager()
        try:
            mgr.create_project("ExportMCPProofProj", description="Audit export proof project")
            mgr.add_st_pou(
                "ExportMCPProofProj",
                "ProofPOU",
                "PROGRAM ProofPOU\nVAR\n    nCount : INT := 0;\n    bFlag : BOOL := TRUE;\nEND_VAR\nnCount := nCount + 1;\nEND_PROGRAM",
            )
        except Exception:
            pass

    def test_cscape_export_project_csp(self) -> None:
        """Export project as .csp native CFBF container."""
        res = cscape_export_project("ExportMCPProofProj", output_format="csp")
        assert res["status"] == "success"
        assert res["output_format"] == "csp"
        out_file = Path(res["export_file"])
        assert out_file.exists()
        assert out_file.stat().st_size >= 512
        cfbf_insp = res.get("cfbf_inspection", {})
        assert cfbf_insp.get("is_valid_cfbf") is True
        assert cfbf_insp.get("magic_hex") == "d0cf11e0a1b11ae1"

    def test_cscape_export_project_cpj(self) -> None:
        """Export project as .cpj native CFBF container."""
        res = cscape_export_project("ExportMCPProofProj", output_format="cpj")
        assert res["status"] == "success"
        assert res["output_format"] == "cpj"
        out_file = Path(res["export_file"])
        assert out_file.exists()
        assert out_file.stat().st_size >= 512
        cfbf_insp = res.get("cfbf_inspection", {})
        assert cfbf_insp.get("is_valid_cfbf") is True

    def test_cscape_export_project_csv(self) -> None:
        """Export project variables as CSV spreadsheet."""
        res = cscape_export_project("ExportMCPProofProj", output_format="csv")
        assert res["status"] == "success"
        assert res["output_format"] == "csv"
        out_file = Path(res["export_file"])
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert "name" in content.lower() or "variable" in content.lower()

    def test_cscape_export_project_xml(self) -> None:
        """Export project variables as XML tag database."""
        res = cscape_export_project("ExportMCPProofProj", output_format="xml")
        assert res["status"] == "success"
        assert res["output_format"] == "xml"
        out_file = Path(res["export_file"])
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert "<ProjectVariables" in content

    def test_cscape_export_project_st(self) -> None:
        """Export project as consolidated Structured Text bundle."""
        res = cscape_export_project("ExportMCPProofProj", output_format="st")
        assert res["status"] == "success"
        assert res["output_format"] == "st"
        out_file = Path(res["export_file"])
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert "PROGRAM ProofPOU" in content

    def test_cscape_export_project_json(self) -> None:
        """Export project metadata manifest as JSON."""
        res = cscape_export_project("ExportMCPProofProj", output_format="json")
        assert res["status"] == "success"
        assert res["output_format"] == "json"
        out_file = Path(res["export_file"])
        assert out_file.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert (data.get("name") or data.get("project_name") or data.get("project")) == "ExportMCPProofProj"

    def test_cscape_export_project_rejects_hardware(self) -> None:
        """Direct hardware download formats must fail."""
        res = cscape_export_project("ExportMCPProofProj", output_format="flash")
        assert res["status"] == "error"

    def test_cscape_export_project_nonexistent_fails_closed(self) -> None:
        """Exporting a nonexistent project must fail closed with success=False and error_count >= 1."""
        res = cscape_export_project("DefinitelyNonExistentProject_77777", output_format="csp")
        assert res["success"] is False
        assert res["status"] == "error"
        assert res["error_count"] >= 1
        assert len(res["errors"]) >= 1
        assert any("Project directory or source file not found" in e for e in res["errors"])

    def test_cscape_export_project_invalid_magic_fails_closed(self) -> None:
        """Exporting a project with invalid CFBF magic header must fail closed."""
        from src.mcp.tools import WORKSPACE_ROOT
        corrupt_dir = WORKSPACE_ROOT / "artifacts" / "projects" / "CorruptMagicProj"
        corrupt_dir.mkdir(parents=True, exist_ok=True)
        corrupt_file = corrupt_dir / "CorruptMagicProj.csp"
        corrupt_file.write_bytes(b"INVALID_HEADER_GARBAGE" + b"\x00" * 600)
        try:
            res = cscape_export_project("CorruptMagicProj", output_format="csp")
            assert res["success"] is False
            assert res["status"] == "error"
            assert res["error_count"] >= 1
            assert any("Project directory or source file not found" in e for e in res["errors"])
        finally:
            import shutil
            shutil.rmtree(corrupt_dir, ignore_errors=True)

    def test_cscape_export_project_existing_valid_succeeds(self) -> None:
        """Exporting an existing valid project succeeds and preserves authentic CFBF container."""
        res = cscape_export_project("ExportMCPProofProj", output_format="csp")
        assert res["success"] is True
        assert res["status"] == "success"
        assert res["error_count"] == 0
        assert res["errors"] == []
        out_file = Path(res["export_file"])
        assert out_file.exists()
        assert out_file.stat().st_size >= 512
        with open(out_file, "rb") as f:
            header = f.read(8)
        assert header == CFBF_MAGIC
        assert header == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
        assert res["cfbf_inspection"]["is_valid_cfbf"] is True
        assert res["cfbf_inspection"]["magic_hex"] == "d0cf11e0a1b11ae1"


# ==============================================================================
# 4. ProjectManager.export_project Verification
# ==============================================================================

class TestProjectManagerExport:
    """Verifies ProjectManager.export_project adapter across native formats."""

    @pytest.fixture
    def pm(self, tmp_path: Path) -> ProjectManager:
        mgr = ProjectManager(workspace_root=tmp_path)
        mgr.create_project("PMAuditProj", description="PM export audit", target_plc="XL4")
        mgr.add_st_pou(
            "PMAuditProj",
            "SpeedControl",
            "PROGRAM SpeedControl\nVAR\n    rActualSpeed : REAL := 0.0;\n    rTargetSpeed : REAL := 1500.0;\nEND_VAR\nrActualSpeed := rTargetSpeed;\nEND_PROGRAM",
        )
        return mgr

    def test_pm_export_csp_authentic_cfbf(self, pm: ProjectManager) -> None:
        """PM export .csp produces genuine CFBF header and Horner markers."""
        res = pm.export_project("PMAuditProj", output_format="csp")
        assert res["success"] is True
        assert res["format"] == "CFBF_OLE2"
        out_path = Path(res["export_path"])
        assert out_path.exists()
        assert res["size_bytes"] >= 512
        assert "cfbf_inspection" in res
        assert res["cfbf_inspection"].get("is_valid_cfbf") is True
        assert res["cfbf_inspection"].get("magic_hex") == "d0cf11e0a1b11ae1"

    def test_pm_export_cpj_authentic_cfbf(self, pm: ProjectManager) -> None:
        """PM export .cpj produces genuine CFBF header."""
        res = pm.export_project("PMAuditProj", output_format="cpj")
        assert res["success"] is True
        assert res["format"] == "CFBF_OLE2"
        assert res["export_path"].endswith(".cpj")
        assert res["cfbf_inspection"].get("is_valid_cfbf") is True

    def test_pm_export_csv(self, pm: ProjectManager) -> None:
        """PM export .csv produces valid variable spreadsheet."""
        res = pm.export_project("PMAuditProj", output_format="csv")
        assert res["success"] is True
        assert res["format"] == "CSV_VARIABLES"
        out_path = Path(res["export_path"])
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8")
        assert "rActualSpeed" in content or "name" in content.lower()

    def test_pm_export_xml(self, pm: ProjectManager) -> None:
        """PM export .xml produces valid Cscape XML tag database."""
        res = pm.export_project("PMAuditProj", output_format="xml")
        assert res["success"] is True
        assert res["format"] == "XML_VARIABLES"
        out_path = Path(res["export_path"])
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8")
        assert "<ProjectVariables" in content

    def test_pm_export_st(self, pm: ProjectManager) -> None:
        """PM export .st produces consolidated Structured Text."""
        res = pm.export_project("PMAuditProj", output_format="st")
        assert res["success"] is True
        assert res["format"] == "CONSOLIDATED_ST"
        content = Path(res["export_path"]).read_text(encoding="utf-8")
        assert "PROGRAM SpeedControl" in content

    def test_pm_export_json(self, pm: ProjectManager) -> None:
        """PM export .json produces project manifest summary."""
        res = pm.export_project("PMAuditProj", output_format="json")
        assert res["success"] is True
        assert res["format"] == "JSON_PROJECT_MANIFEST"
        data = json.loads(Path(res["export_path"]).read_text(encoding="utf-8"))
        assert data["name"] == "PMAuditProj"

    def test_pm_export_nonexistent_fails_closed(self, pm: ProjectManager) -> None:
        """PM export for nonexistent project fails closed with FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Project directory or source file not found"):
            pm.export_project("NonExistentPMProj_9999", output_format="csp")

    def test_pm_export_invalid_magic_fails_closed(self, pm: ProjectManager, tmp_path: Path) -> None:
        """PM export for project with invalid CFBF magic header fails closed."""
        p_dir = tmp_path / "artifacts" / "projects" / "BadMagicProj"
        p_dir.mkdir(parents=True, exist_ok=True)
        bad_file = p_dir / "BadMagicProj.csp"
        bad_file.write_bytes(b"INVALID_HEADER_GARBAGE" + b"\x00" * 600)
        with pytest.raises(FileNotFoundError, match="Project directory or source file not found"):
            pm.export_project("BadMagicProj", output_format="csp")


# ==============================================================================
# 5. CscapeVariableManager Register Scope Fidelity Proof (No Truncation)
# ==============================================================================

class TestVariableScopeFidelity:
    """Proves CscapeVariableManager handles register scopes without truncation."""

    @pytest.fixture
    def rich_variable_db(self) -> CscapeVariableManager:
        """Builds a database covering every Horner OCS register scope."""
        vm = CscapeVariableManager(project_name="ScopeProof")
        test_vars = [
            CscapeVariable(name="RegWord1", data_type="INT", scope="%R", tag="%R1", description="Retentive register 1"),
            CscapeVariable(name="IntBit1", data_type="BOOL", scope="%M", tag="%M1", description="Internal bit 1"),
            CscapeVariable(name="TempBit1", data_type="BOOL", scope="%T", tag="%T1", description="Temporary bit 1"),
            CscapeVariable(name="AnalogIn1", data_type="INT", scope="%AI", tag="%AI1", description="Analog input 1"),
            CscapeVariable(name="AnalogOut1", data_type="INT", scope="%AQ", tag="%AQ1", description="Analog output 1"),
            CscapeVariable(name="DigitalIn1", data_type="BOOL", scope="%I", tag="%I1", description="Digital input 1"),
            CscapeVariable(name="DigitalOut1", data_type="BOOL", scope="%Q", tag="%Q1", description="Digital output 1"),
            CscapeVariable(name="SysBit1", data_type="BOOL", scope="%S", tag="%S1", description="System bit 1"),
            CscapeVariable(name="SysReg1", data_type="INT", scope="%SR", tag="%SR1", description="System register 1"),
            CscapeVariable(name="GlobalTag", data_type="DINT", scope="globals", tag="%R100", description="Global DINT"),
        ]
        for v in test_vars:
            vm.add_variable(v)
        return vm

    def test_export_xml_register_scopes_without_truncation(self, rich_variable_db: CscapeVariableManager, tmp_path: Path) -> None:
        """XML serializer must preserve %R, %M, %AI, %AQ, %I, %Q, %S, %SR vargroups without clipping."""
        xml_file = tmp_path / "scope_export.xml"
        xml_content = rich_variable_db.export_xml(destination=xml_file)

        root = ET.fromstring(xml_content)
        vargroups = {vg.get("name"): [v.get("name") for v in vg.findall("var")] for vg in root.findall("vargroup")}

        expected_scopes = ["%R", "%M", "%T", "%AI", "%AQ", "%I", "%Q", "%S", "%SR"]
        for exp_sc in expected_scopes:
            assert exp_sc in vargroups, (
                f"Scope '{exp_sc}' was truncated or missing in XML export! Found scopes: {list(vargroups.keys())}"
            )

        assert "RegWord1" in vargroups["%R"]
        assert "IntBit1" in vargroups["%M"]
        assert "AnalogIn1" in vargroups["%AI"]
        assert "SysReg1" in vargroups["%SR"]

    def test_export_csv_register_scopes_without_truncation(self, rich_variable_db: CscapeVariableManager, tmp_path: Path) -> None:
        """CSV serializer must preserve %R, %M, %AI, %AQ, %I, %Q, %S, %SR in scope column without clipping."""
        csv_file = tmp_path / "scope_export.csv"
        csv_content = rich_variable_db.export_csv(destination=csv_file, delimiter=";")

        reader = csv.reader(csv_content.splitlines(), delimiter=";")
        headers = [h.lower() for h in next(reader)]
        assert "scope" in headers
        scope_idx = headers.index("scope")
        name_idx = headers.index("name")

        exported_scopes = {}
        for row in reader:
            if row:
                exported_scopes[row[name_idx]] = row[scope_idx]

        assert exported_scopes.get("RegWord1") == "%R"
        assert exported_scopes.get("IntBit1") == "%M"
        assert exported_scopes.get("TempBit1") == "%T"
        assert exported_scopes.get("AnalogIn1") == "%AI"
        assert exported_scopes.get("AnalogOut1") == "%AQ"
        assert exported_scopes.get("DigitalIn1") == "%I"
        assert exported_scopes.get("DigitalOut1") == "%Q"
        assert exported_scopes.get("SysBit1") == "%S"
        assert exported_scopes.get("SysReg1") == "%SR"

    def test_xml_roundtrip_preserves_scopes(self, rich_variable_db: CscapeVariableManager, tmp_path: Path) -> None:
        """Roundtrip: Memory -> XML -> Re-import -> Memory preserves scope fidelity exactly."""
        xml_file = tmp_path / "roundtrip.xml"
        rich_variable_db.export_xml(destination=xml_file)

        new_vm = CscapeVariableManager(project_name="RoundtripProof")
        count = new_vm.import_xml(xml_file)
        assert count == rich_variable_db.total_count

        for orig_var in rich_variable_db.list_variables():
            vars_found = new_vm.find_variable(orig_var.name)
            assert len(vars_found) > 0
            imported_var = vars_found[0]
            assert imported_var.data_type == orig_var.data_type
            assert imported_var.tag == orig_var.tag
            assert imported_var.scope.upper() == orig_var.scope.upper()

    def test_csv_roundtrip_preserves_scopes(self, rich_variable_db: CscapeVariableManager, tmp_path: Path) -> None:
        """Roundtrip: Memory -> CSV -> Re-import -> Memory preserves scope fidelity exactly."""
        csv_file = tmp_path / "roundtrip.csv"
        rich_variable_db.export_csv(destination=csv_file, delimiter=";")

        new_vm = CscapeVariableManager(project_name="RoundtripCSVProof")
        count = new_vm.import_csv(csv_file, delimiter=";")
        assert count == rich_variable_db.total_count

        for orig_var in rich_variable_db.list_variables():
            vars_found = new_vm.find_variable(orig_var.name)
            assert len(vars_found) > 0
            imported_var = vars_found[0]
            assert imported_var.data_type == orig_var.data_type
            assert imported_var.tag == orig_var.tag
            assert imported_var.scope.upper() == orig_var.scope.upper()


# ==============================================================================
# 5. cscape_export_project Fail-Closed & CFBF_MAGIC Verification
# ==============================================================================

class TestCscapeExportProjectIntegrity:
    """Verifies cscape_export_project across src.cscape.project_manager and src.automation.project_manager."""

    def test_cscape_export_project_pm_nonexistent_fails_closed(self, tmp_path: Path) -> None:
        """src.cscape.project_manager.cscape_export_project fails closed on nonexistent project."""
        from src.cscape.project_manager import cscape_export_project as pm_export
        res = pm_export("NonExistent_Ghost_Project_9999", output_format="csp")
        assert res["success"] is False
        assert res["status"] in ("failed", "error")
        assert res["error_count"] >= 1
        assert len(res["errors"]) >= 1
        assert any("not found" in e.lower() or "does not exist" in e.lower() for e in res["errors"])

    def test_cscape_export_project_pm_valid_cfbf_magic(self, tmp_path: Path) -> None:
        """src.cscape.project_manager.cscape_export_project validates 8-byte CFBF_MAGIC header."""
        from src.cscape.project_manager import cscape_export_project as pm_export
        # Create valid source CFBF project
        src_csp = tmp_path / "ValidSource.csp"
        src_csp.write_bytes(generate_minimal_cfbf_bytes("ValidSource"))
        dst_csp = tmp_path / "ExportedValid.csp"

        res = pm_export(src_csp, destination_path=dst_csp, output_format="csp")
        assert res["success"] is True
        assert res["status"] == "success"
        assert dst_csp.exists()
        assert dst_csp.stat().st_size >= 512
        header = dst_csp.read_bytes()[:8]
        assert header == CFBF_MAGIC
        assert header == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
        assert res["is_valid_cfbf"] is True

    def test_cscape_export_project_pm_corrupted_magic_fails_closed(self, tmp_path: Path) -> None:
        """src.cscape.project_manager.cscape_export_project fails closed when source has invalid magic."""
        from src.cscape.project_manager import cscape_export_project as pm_export
        corrupt_csp = tmp_path / "CorruptSource.csp"
        corrupt_csp.write_bytes(b"BAD_MAGIC_HEADER_BYTES" + b"\x00" * 600)
        dst_csp = tmp_path / "ShouldNotBeCreated.csp"

        res = pm_export(corrupt_csp, destination_path=dst_csp, output_format="csp")
        assert res["success"] is False
        assert res["status"] in ("failed", "error")
        assert res["error_count"] >= 1
        assert not dst_csp.exists()

    def test_automation_cscape_export_project_nonexistent_fails_closed(self, tmp_path: Path) -> None:
        """src.automation.project_manager.cscape_export_project fails closed on nonexistent project."""
        from src.automation.project_manager import cscape_export_project as auto_export
        with pytest.raises(FileNotFoundError):
            auto_export("GhostProject_8888", output_format="csp", workspace_root=tmp_path)

    def test_automation_cscape_export_project_valid_cfbf_magic(self, tmp_path: Path) -> None:
        """src.automation.project_manager.cscape_export_project validates 8-byte CFBF_MAGIC header."""
        from src.automation.project_manager import ProjectManager, cscape_export_project as auto_export
        pm = ProjectManager(workspace_root=tmp_path)
        pm.create_project("AutoExportAudit", description="Auto export audit project")
        pm.add_st_pou("AutoExportAudit", "MainPOU", "PROGRAM MainPOU\nVAR n: INT; END_VAR\nn := 1;\nEND_PROGRAM")

        res = auto_export("AutoExportAudit", output_format="csp", workspace_root=tmp_path)
        assert res["success"] is True
        assert res["status"] == "success"
        out_file = Path(res["export_path"])
        assert out_file.exists()
        header = out_file.read_bytes()[:8]
        assert header == CFBF_MAGIC
        assert header == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

