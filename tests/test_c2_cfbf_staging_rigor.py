"""Test Suite for Phase C2: CFBF Validation Hardening, Staging Separation, and Fallback Dismantling.

Mandate: PLAN_CORRECTIVO v2.0 - Phase C2 Rigor
Invariants:
1. Reject CFBF 512-byte magic+zeros as valid Horner export (is_valid_cfbf / export_project / inspect_project_file).
2. Separate staging vs native insert (storage_mode='staging', is_staged=True, is_native_persisted=False).
3. Remove editor-empty -> aux-file verify fallback in verify_editor_content (empty editor must fail verification).
4. Negative tests for corrupt CFBF + staging confusion.
5. Strictly prohibit claiming native persistence / Gate G2 / Gate G5 closed.
"""

from __future__ import annotations

import struct
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest

from src.cscape.cfbf import (
    CFBF_MAGIC,
    CSCAPE_CONTENTS_MAGIC,
    HORNER_MARKERS,
    ProjectFileInfo,
    generate_minimal_cfbf_bytes,
    inspect_project_file,
    is_valid_cfbf,
    parse_cfbf_pure,
    parse_csp_contents_header,
)
from src.cscape.st_inserter import (
    InsertionMethod,
    POUType,
    STInsertionResult,
    StructuredTextInserter,
)
from src.cscape.project_manager import export_project
from src.mcp.tools import (
    WORKSPACE_ROOT,
    cscape_add_st_pou,
    cscape_create_project,
    cscape_export_project,
    cscape_insert_st,
)


# ==============================================================================
# 1. CFBF 512-Byte Magic+Zeros & Corrupt Container Negative Tests
# ==============================================================================

class TestC2CorruptCFBFRejection:
    """Rigorous negative tests rejecting dummy 512-byte magic+zeros and corrupt CFBF headers."""

    def test_c2_n01_cfbf_512_magic_zeros_rejected_by_is_valid_cfbf(self, tmp_path: Path):
        """is_valid_cfbf must reject a 512-byte file with 8-byte magic followed by 504 zero bytes."""
        corrupt_data = CFBF_MAGIC + (b"\x00" * 504)
        assert len(corrupt_data) == 512
        assert is_valid_cfbf(corrupt_data) is False

        p = tmp_path / "DummyMagicZeros.csp"
        p.write_bytes(corrupt_data)
        assert is_valid_cfbf(p) is False

    def test_c2_n01b_exact_user_expression_false_cfbf_export_rejected(self, tmp_path: Path):
        """bytes.fromhex('d0cf11e0a1b11ae1') + bytes(504) must NOT yield success or is_valid_cfbf acceptance."""
        false_export = bytes.fromhex("d0cf11e0a1b11ae1") + bytes(504)
        assert len(false_export) == 512
        assert is_valid_cfbf(false_export) is False
        p = tmp_path / "FalseExportExact.csp"
        p.write_bytes(false_export)
        assert is_valid_cfbf(p) is False
        with pytest.raises(ValueError, match="512-byte magic\\+zeros"):
            inspect_project_file(p)

    def test_c2_n02_cfbf_512_magic_zeros_rejected_by_inspect_project_file(self, tmp_path: Path):
        """inspect_project_file must raise ValueError when encountering 512-byte magic+zeros dummy container."""
        p = tmp_path / "Dummy512.csp"
        p.write_bytes(CFBF_MAGIC + (b"\x00" * 504))

        with pytest.raises(ValueError, match="512-byte magic\\+zeros"):
            inspect_project_file(p)

    def test_c2_n03_cfbf_bad_byte_order_rejected(self, tmp_path: Path):
        """CFBF with invalid byte order (e.g. 0x0000 or 0xFEFF) must fail closed."""
        raw = bytearray(generate_minimal_cfbf_bytes("BadByteOrderProj"))
        # Corrupt byte order at offset 28
        struct.pack_into("<H", raw, 28, 0x0000)
        p = tmp_path / "BadByteOrder.csp"
        p.write_bytes(raw)

        assert is_valid_cfbf(raw) is False
        assert is_valid_cfbf(p) is False
        with pytest.raises(ValueError, match="unsupported byte order"):
            inspect_project_file(p)

    def test_c2_n04_cfbf_truncated_header_rejected(self, tmp_path: Path):
        """CFBF files smaller than or equal to 512 bytes must be rejected."""
        truncated = CFBF_MAGIC + (b"\x00" * 200)
        assert is_valid_cfbf(truncated) is False

        p = tmp_path / "Truncated.csp"
        p.write_bytes(truncated)
        assert is_valid_cfbf(p) is False
        with pytest.raises(ValueError):
            inspect_project_file(p)

    def test_c2_n05_st_inserter_validate_cfbf_container_rejects_magic_zeros(self, tmp_path: Path):
        """StructuredTextInserter.validate_cfbf_container must reject 512-byte magic+zeros."""
        p = tmp_path / "CorruptContainer.csp"
        p.write_bytes(CFBF_MAGIC + (b"\x00" * 504))
        assert StructuredTextInserter.validate_cfbf_container(p) is False

    def test_c2_n06_cscape_export_project_rejects_512_magic_zeros(self):
        """cscape_export_project must reject exporting a project whose container is 512-byte magic+zeros."""
        import shutil
        proj_dir = WORKSPACE_ROOT / "artifacts" / "projects" / "CorruptExportProj"
        proj_dir.mkdir(parents=True, exist_ok=True)
        csp_file = proj_dir / "CorruptExportProj.csp"
        csp_file.write_bytes(CFBF_MAGIC + (b"\x00" * 504))

        try:
            res = cscape_export_project("CorruptExportProj", output_format="csp")
            assert res["success"] is False
            assert res["status"] == "failed"
            assert any("512-byte magic+zeros" in str(e) or "failed CFBF" in str(e) for e in res.get("errors", []))
        finally:
            shutil.rmtree(proj_dir, ignore_errors=True)

    def test_c2_n07_cscape_pm_export_project_rejects_512_magic_zeros(self, tmp_path: Path):
        """cscape.project_manager.export_project must reject source container with 512-byte magic+zeros."""
        proj_dir = tmp_path / "PMCorruptExportProj"
        proj_dir.mkdir(parents=True, exist_ok=True)
        csp_file = proj_dir / "PMCorruptExportProj.csp"
        csp_file.write_bytes(CFBF_MAGIC + (b"\x00" * 504))

        res = export_project(str(proj_dir), destination_path=str(tmp_path / "out.csp"), output_format="csp")
        assert res["success"] is False
        assert res["status"] == "failed"
        assert any("512-byte magic+zeros" in str(e) or "failed CFBF" in str(e) for e in res.get("errors", []))


# ==============================================================================
# 2. Staging vs Native Insert Separation & Fallback Elimination
# ==============================================================================

class TestC2StagingSeparationAndFallbackElimination:
    """Rigorous tests confirming staging classification and removal of empty-editor fallback."""

    def test_c2_n08_verify_editor_content_empty_editor_fails_closed_no_disk_fallback(self, tmp_path: Path):
        """When editor window buffer is empty, verify_editor_content MUST fail closed even if file exists on disk."""
        sample_code = "PROGRAM Main\nVAR\n    x : INT;\nEND_VAR\nx := 1;\nEND_PROGRAM"
        pou_file = tmp_path / "Main.st"
        pou_file.write_text(sample_code, encoding="utf-8")

        inserter = StructuredTextInserter()
        # Mock editor returning empty string (editor is empty / uninitialized)
        with patch.object(inserter, "read_editor_code", return_value=""):
            res = inserter.verify_editor_content(
                editor_hwnd=0x1234,
                expected_code=sample_code,
                pou_name="Main",
                file_path=pou_file,
            )
            # Must NOT pass using disk fallback
            assert res.verified is False
            assert res.exact_match is False
            assert res.extracted_code == ""
            assert any("Aux-file fallback is strictly prohibited" in d for d in res.diagnostics)

    def test_c2_p01_cscape_insert_st_explicit_staging_classification(self, tmp_path: Path):
        """cscape_insert_st must explicitly return storage_mode='staging', is_staged=True, is_native_persisted=False."""
        code = "PROGRAM StagedTest\nVAR\n    bFlag : BOOL;\nEND_VAR\nbFlag := TRUE;\nEND_PROGRAM"
        res = cscape_insert_st(
            pou_name="StagedTest",
            pou_type="PROGRAM",
            st_code=code,
            target_project_path=str(tmp_path),
        )
        assert res["success"] is True
        assert res["status"] == "success"
        assert res["storage_mode"] == "staging"
        assert res["is_staged"] is True
        assert res["is_native_persisted"] is False
        assert (tmp_path / "pous" / "StagedTest.st").exists()

    def test_c2_p02_cscape_add_st_pou_explicit_staging_classification(self):
        """cscape_add_st_pou must return storage_mode='staging', is_staged=True, is_native_persisted=False."""
        cscape_create_project(project_name="AddStagingAuditProject")
        code = "PROGRAM AddStagingTest\nVAR\n    nVal : INT;\nEND_VAR\nnVal := 42;\nEND_PROGRAM"
        res = cscape_add_st_pou(
            project_name="AddStagingAuditProject",
            pou_name="AddStagingTest",
            pou_type="PROGRAM",
            code=code,
        )
        assert res["success"] is True
        assert res["status"] == "success"
        assert res["storage_mode"] == "staging"
        assert res["is_staged"] is True
        assert res["is_native_persisted"] is False

    def test_c2_p03_st_insertion_result_structure(self):
        """STInsertionResult must contain explicit storage_mode and native persistence flags."""
        result = STInsertionResult(
            success=True,
            pou_name="CheckPOU",
            pou_type=POUType.PROGRAM,
            method_used=InsertionMethod.FILE_SYNC,
            editor_hwnd=None,
            code_length=100,
            code_hash="abcd1234",
            verified=True,
        )
        d = result.to_dict()
        assert d["storage_mode"] == "staging"
        assert d["is_staged"] is True
        assert d["is_native_persisted"] is False

    def test_c2_n09_hash_alone_does_not_claim_native_persistence(self):
        """Mandate: SHA-256 or AST hash presence must NOT be claimed as native container persistence."""
        cscape_create_project(project_name="HashTestProj")
        code = "PROGRAM HashTest\nVAR\n    y : INT;\nEND_VAR\ny := 99;\nEND_PROGRAM"
        res = cscape_add_st_pou("HashTestProj", "HashPOU", "PROGRAM", code)
        assert res["code_hash"] != ""
        # Hash is present, but native persistence is explicitly FALSE
        assert res["is_native_persisted"] is False
        assert res["storage_mode"] == "staging"
        assert res["is_staged"] is True


# ==============================================================================
# 3. Deep Structural CFBF Container Anomalies & Hardening (Phase C2 Continuation)
# ==============================================================================

class TestC2StructuralContainerAnomalies:
    """Rigorous negative tests for structural anomalies, sector shift violations, size deficits, and cycle defense."""

    def test_c2_n10_cfbf_invalid_mini_sector_shift_rejected(self, tmp_path: Path):
        """CFBF with invalid mini sector shift (!= 6) must fail closed."""
        raw = bytearray(generate_minimal_cfbf_bytes("BadMiniShift"))
        # Corrupt mini sector shift at offset 32 to 0
        struct.pack_into("<H", raw, 32, 0)
        p = tmp_path / "BadMiniShift.csp"
        p.write_bytes(raw)

        assert is_valid_cfbf(raw) is False
        assert is_valid_cfbf(p) is False
        with pytest.raises(ValueError, match="invalid mini sector shift"):
            inspect_project_file(p)

    def test_c2_n11_cfbf_truncated_file_sector_deficit_rejected(self, tmp_path: Path):
        """CFBF files with fewer than 3 sectors (< 1536 bytes) cannot hold required FAT + Directory sectors."""
        # 1024 bytes = Header + only 1 sector
        raw = bytearray(1024)
        raw[0:8] = CFBF_MAGIC
        struct.pack_into("<H", raw, 28, 0xFFFE)
        struct.pack_into("<H", raw, 30, 9)
        struct.pack_into("<H", raw, 32, 6)
        p = tmp_path / "DeficitSectors.csp"
        p.write_bytes(raw)

        assert is_valid_cfbf(raw) is False
        assert is_valid_cfbf(p) is False
        with pytest.raises(ValueError, match="smaller than minimum CFBF container"):
            inspect_project_file(p)

    def test_c2_n12_cfbf_unaligned_file_size_rejected(self, tmp_path: Path):
        """CFBF files whose size is not an integer multiple of the sector size must be rejected."""
        raw = bytearray(generate_minimal_cfbf_bytes("UnalignedProj"))
        raw.append(0x55)  # 5633 bytes (unaligned)
        p = tmp_path / "Unaligned.csp"
        p.write_bytes(raw)

        assert is_valid_cfbf(raw) is False
        assert is_valid_cfbf(p) is False
        with pytest.raises(ValueError, match="not sector-aligned"):
            inspect_project_file(p)

    def test_c2_n13_cfbf_circular_difat_chain_defense(self):
        """parse_cfbf_pure must terminate safely and break out if a circular DIFAT loop is present."""
        raw = bytearray(generate_minimal_cfbf_bytes("CircularDifat"))
        # Set num_fat_sec = 200 (trigger DIFAT chain traversal)
        struct.pack_into("<I", raw, 44, 200)
        # Set first_difat to sector 0
        struct.pack_into("<I", raw, 68, 0)
        # In sector 0 (offset 512), set the last pointer (DIFAT next pointer) to point back to sector 0
        cnt = (512 // 4) - 1
        struct.pack_into("<I", raw, 512 + cnt * 4, 0)

        # Must parse or fail without hanging / infinite loop
        entries, streams = parse_cfbf_pure(bytes(raw))
        # Safely executed without hanging
        assert isinstance(entries, list)
        assert isinstance(streams, dict)

    def test_c2_n14_cfbf_corrupt_contents_stream_magic(self, tmp_path: Path):
        """When /Contents stream header does not match 0x78563412, parser reports invalid header honestly."""
        raw = bytearray(generate_minimal_cfbf_bytes("CorruptContentsHdr"))
        # Contents stream starts at sector 2 (offset (2+1)*512 = 1536)
        struct.pack_into("<I", raw, 1536, 0x00000000)
        p = tmp_path / "CorruptContents.csp"
        p.write_bytes(raw)

        # Container itself is structurally valid CFBF
        assert is_valid_cfbf(raw) is True
        info = inspect_project_file(p)
        assert info.is_valid_cfbf is True
        # But contents stream magic is corrupt, so cscape_version is None
        assert info.cscape_version is None

    def test_c2_n15_st_inserter_validate_cfbf_rejects_unaligned_and_mini_shift_anomalies(self, tmp_path: Path):
        """StructuredTextInserter.validate_cfbf_container must reject unaligned and corrupt mini shift containers."""
        raw = bytearray(generate_minimal_cfbf_bytes("InserterAnomaly"))
        struct.pack_into("<H", raw, 32, 0)  # Bad mini shift
        p = tmp_path / "BadMiniInserter.csp"
        p.write_bytes(raw)
        assert StructuredTextInserter.validate_cfbf_container(p) is False

        raw2 = bytearray(generate_minimal_cfbf_bytes("InserterUnaligned"))
        raw2.append(0xAA)  # Unaligned
        p2 = tmp_path / "UnalignedInserter.csp"
        p2.write_bytes(raw2)
        assert StructuredTextInserter.validate_cfbf_container(p2) is False
