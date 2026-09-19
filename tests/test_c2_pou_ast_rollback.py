"""Phase C2 Test Suite: POU AST Engine & Transactional Rollback Rigor.

Mandates Verified:
1. Pure IEC 61131-3 ST syntax pre-insertion validation via IECValidator.
2. Zero disk pollution / mutation when inserting invalid ST or ladder logic.
3. Transactional rollback when updating an existing POU fails (original file preserved byte-for-byte).
4. Accurate line number localization for ladder constructs (ERR_LADDER_FORBIDDEN) without inventing line 1, col 1.
5. Unlocated errors preserve line: None, column: None.
6. Offline / DEV execution only (zero live GUI mutation; Cscape untouched).
"""

import pytest
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict

from src.mcp.tools import (
    cscape_insert_st,
    cscape_add_st_pou,
    cscape_validate_st,
    normalize_tool_result,
    ToolStatus,
)
from src.cscape.st_ld_interop import STLadderInteropGuard, LadderConstructRejectedError
from src.security.exceptions import UnauthorizedDownloadError


@pytest.fixture
def temp_project_dir():
    """Creates a temporary project directory layout with pous/ subfolder."""
    tmp = tempfile.mkdtemp(prefix="c2_test_proj_")
    p_dir = Path(tmp)
    (p_dir / "pous").mkdir(parents=True, exist_ok=True)
    yield p_dir
    shutil.rmtree(tmp, ignore_errors=True)


class TestC2POUASTValidationAndInsertion:
    """Verifies AST parsing, validation, and zero disk mutation on failure."""

    def test_valid_st_pou_inserted_successfully(self, temp_project_dir):
        code = "PROGRAM ValidProg\nVAR\n  count : INT;\nEND_VAR\n  count := count + 1;\nEND_PROGRAM"
        res = cscape_insert_st(
            pou_name="ValidProg",
            pou_type="PROGRAM",
            st_code=code,
            target_project_path=str(temp_project_dir),
        )
        assert res["success"] is True
        assert res["status"] == "success"
        pou_file = temp_project_dir / "pous" / "ValidProg.st"
        assert pou_file.exists()
        assert pou_file.read_text(encoding="utf-8") == code

    def test_invalid_syntax_zero_disk_pollution(self, temp_project_dir):
        bad_code = "PROGRAM BadProg\nVAR\n  x : INT\nEND_VAR\n  x := ;\nEND_PROGRAM"
        res = cscape_insert_st(
            pou_name="BadProg",
            pou_type="PROGRAM",
            st_code=bad_code,
            target_project_path=str(temp_project_dir),
        )
        assert res["success"] is False
        assert res["status"] == "failed"
        pou_file = temp_project_dir / "pous" / "BadProg.st"
        assert not pou_file.exists(), "Invalid POU must NOT be written to disk (zero disk pollution)"

    def test_ladder_logic_zero_disk_pollution(self, temp_project_dir):
        ladder_code = "PROGRAM LadderProg\nVAR\n  b : BOOL;\nEND_VAR\n  ---[ ]---\nEND_PROGRAM"
        res = cscape_insert_st(
            pou_name="LadderProg",
            pou_type="PROGRAM",
            st_code=ladder_code,
            target_project_path=str(temp_project_dir),
        )
        assert res["success"] is False
        assert res["status"] == "failed"
        assert any("ladder" in e.lower() for e in res["errors"])
        pou_file = temp_project_dir / "pous" / "LadderProg.st"
        assert not pou_file.exists(), "Ladder construct POU must NOT be written to disk"


class TestC2TransactionalRollback:
    """Verifies transactional rollback on update failure."""

    def test_update_failure_restores_original_code_byte_for_byte(self, temp_project_dir):
        good_code = "PROGRAM MasterProg\nVAR\n  setpoint : REAL;\nEND_VAR\n  setpoint := 100.0;\nEND_PROGRAM"
        pou_file = temp_project_dir / "pous" / "MasterProg.st"
        pou_file.write_text(good_code, encoding="utf-8")
        original_mtime = pou_file.stat().st_mtime_ns

        broken_update = "PROGRAM MasterProg\nVAR\n  setpoint : REAL;\nEND_VAR\n  setpoint := ---[ ]---;\nEND_PROGRAM"
        res = cscape_insert_st(
            pou_name="MasterProg",
            pou_type="PROGRAM",
            st_code=broken_update,
            target_project_path=str(temp_project_dir),
        )
        assert res["success"] is False
        assert res["status"] == "failed"

        # Verify original file was preserved intact
        current_content = pou_file.read_text(encoding="utf-8")
        assert current_content == good_code, "Original POU content must be preserved upon failed update"


class TestC2AccurateLocationMetrics:
    """Verifies accurate line/column extraction and eliminates fabricated line 1, col 1."""

    def test_ladder_construct_line_number_precision(self):
        code = "PROGRAM TestLadderLine\nVAR\n  a : BOOL;\nEND_VAR\n  ---( )---\nEND_PROGRAM"
        res = cscape_validate_st(code=code)
        assert res["valid"] is False
        assert len(res["failure_locations"]) > 0
        loc = res["failure_locations"][0]
        # Line 5 contains the ladder coil ---( )---
        assert loc["line"] == 5, f"Expected line 5 for ladder coil, got {loc['line']}"
        assert loc["error_code"] == "ERR_LADDER_FORBIDDEN"

    def test_unlocated_error_preserves_none(self):
        norm = normalize_tool_result({
            "success": False,
            "errors": ["General unlocated AST engine anomaly"]
        })
        assert len(norm["failure_locations"]) > 0
        loc = norm["failure_locations"][0]
        assert loc["line"] is None, "Unlocated error must not invent line 1"
        assert loc["column"] is None, "Unlocated error must not invent col 1"


class TestC2LadderVariantsRejection:
    """Tests rejecting diverse ladder artifacts (coils, contacts, mnemonics) while preserving pure ST."""

    def test_c2_n16_ladder_coil_set_reset_rejection(self, temp_project_dir):
        """Reject set/reset coils --- (S) --- and [SET bVar] with ERR_LADDER_FORBIDDEN and zero disk mutation."""
        code = "PROGRAM SetCoilProg\nVAR\n  bAlarm : BOOL;\nEND_VAR\n  ---(S)---\nEND_PROGRAM"
        res = cscape_insert_st("SetCoilProg", "PROGRAM", code, target_project_path=str(temp_project_dir))
        assert res["success"] is False
        assert res["status"] == "failed"
        assert not (temp_project_dir / "pous" / "SetCoilProg.st").exists()
        assert any("ladder" in e.lower() for e in res["errors"])

    def test_c2_n17_ladder_contacts_nc_rejection(self, temp_project_dir):
        """Reject normally closed contacts ---[/]--- with zero disk mutation."""
        code = "PROGRAM NCProg\nVAR\n  bStop : BOOL;\nEND_VAR\n  ---[/]---\nEND_PROGRAM"
        res = cscape_insert_st("NCProg", "PROGRAM", code, target_project_path=str(temp_project_dir))
        assert res["success"] is False
        assert res["status"] == "failed"
        assert not (temp_project_dir / "pous" / "NCProg.st").exists()

    def test_c2_n18_ladder_mnemonic_instructions_rejection(self, temp_project_dir):
        """Reject ladder instruction mnemonics (XIC, XIO, OTE, OTL, OTU)."""
        code = "PROGRAM MnemonicProg\nVAR\n  bStart : BOOL;\nEND_VAR\n  XIC(bStart)\nEND_PROGRAM"
        res = cscape_insert_st("MnemonicProg", "PROGRAM", code, target_project_path=str(temp_project_dir))
        assert res["success"] is False
        assert res["status"] == "failed"
        assert not (temp_project_dir / "pous" / "MnemonicProg.st").exists()

    def test_c2_p04_ladder_in_comments_allowed(self):
        """Comments mentioning ladder constructs must NOT be falsely rejected."""
        code = (
            "PROGRAM CommentDocProg\n"
            "VAR\n"
            "  bStatus : BOOL;\n"
            "END_VAR\n"
            "(* Legacy contact was ---[ ]--- and coil was ---( )--- *)\n"
            "// RUNG 1: legacy XIC(bStart) replaced by ST IF\n"
            "bStatus := TRUE;\n"
            "END_PROGRAM"
        )
        res = cscape_validate_st(code=code)
        assert res["valid"] is True
        assert res["status"] == "success"

    def test_c2_p05_identifier_substring_collision_immunity(self):
        """Variable names with ladder substrings (e.g. network_id, rung_counter, xic_status) must be valid."""
        code = (
            "PROGRAM IdentifierProg\n"
            "VAR\n"
            "  network_id : INT;\n"
            "  rung_counter : INT;\n"
            "  xic_status : BOOL;\n"
            "END_VAR\n"
            "network_id := 1;\n"
            "rung_counter := rung_counter + 1;\n"
            "xic_status := FALSE;\n"
            "END_PROGRAM"
        )
        res = cscape_validate_st(code=code)
        assert res["valid"] is True
        assert res["status"] == "success"


class TestC2SyntaxAndGrammarRejection:
    """Verifies fail-closed behavior for malformed ST grammar, unclosed blocks, and empty code."""

    def test_c2_n19_unmatched_if_block_syntax_rejection(self, temp_project_dir):
        """Unclosed IF statement missing END_IF must fail closed with zero disk mutation."""
        code = "PROGRAM BrokenIf\nVAR\n  x : INT;\nEND_VAR\nIF x > 0 THEN\n  x := 0;\nEND_PROGRAM"
        res = cscape_insert_st("BrokenIf", "PROGRAM", code, target_project_path=str(temp_project_dir))
        assert res["success"] is False
        assert res["status"] == "failed"
        assert not (temp_project_dir / "pous" / "BrokenIf.st").exists()

    def test_c2_n20_unmatched_case_block_syntax_rejection(self, temp_project_dir):
        """Unclosed CASE statement missing END_CASE must fail closed."""
        code = "PROGRAM BrokenCase\nVAR\n  st : INT;\nEND_VAR\nCASE st OF\n1: st := 2;\nEND_PROGRAM"
        res = cscape_insert_st("BrokenCase", "PROGRAM", code, target_project_path=str(temp_project_dir))
        assert res["success"] is False
        assert res["status"] == "failed"
        assert not (temp_project_dir / "pous" / "BrokenCase.st").exists()

    def test_c2_n21_unclosed_comment_rejection(self, temp_project_dir):
        """Unclosed block comment (* ... without *) must fail closed."""
        code = "PROGRAM UnclosedComment\nVAR\n  x : INT;\nEND_VAR\n(* Unclosed comment\nx := 1;\nEND_PROGRAM"
        res = cscape_insert_st("UnclosedComment", "PROGRAM", code, target_project_path=str(temp_project_dir))
        assert res["success"] is False
        assert res["status"] == "failed"
        assert not (temp_project_dir / "pous" / "UnclosedComment.st").exists()

    def test_c2_n22_empty_and_whitespace_code_rejected(self):
        """Empty string or whitespace-only code must fail closed."""
        res1 = cscape_validate_st(code="")
        assert res1["valid"] is False
        assert res1["status"] == "failed"

        res2 = cscape_validate_st(code="   \n\t  \n  ")
        assert res2["valid"] is False
        assert res2["status"] == "failed"


class TestC2TransactionalRollbackRigorous:
    """Verifies that failed updates preserve existing disk assets byte-for-byte with zero residue."""

    def test_c2_n23_rollback_preserves_bytes_on_syntax_error(self, temp_project_dir):
        """When an update introduces a syntax error, original file content is preserved 100% byte-for-byte."""
        good_code = "PROGRAM ExistingTask\nVAR\n  nSpeed : INT;\nEND_VAR\nnSpeed := 1500;\nEND_PROGRAM"
        pou_file = temp_project_dir / "pous" / "ExistingTask.st"
        pou_file.write_text(good_code, encoding="utf-8")
        expected_bytes = pou_file.read_bytes()

        # Attempt to overwrite with broken code
        broken_code = "PROGRAM ExistingTask\nVAR\n  nSpeed : INT\nEND_VAR\nnSpeed := ;\nEND_PROGRAM"
        res = cscape_insert_st("ExistingTask", "PROGRAM", broken_code, target_project_path=str(temp_project_dir))
        assert res["success"] is False
        assert res["status"] == "failed"

        # Byte-for-byte equality assertion
        assert pou_file.read_bytes() == expected_bytes

    def test_c2_n24_rollback_on_add_st_pou_ladder_injection(self, tmp_path: Path):
        """cscape_add_st_pou rolls back cleanly if ladder logic is injected into an existing project POU."""
        proj_name = "RollbackLadderAuditProj"
        proj_dir = Path("artifacts/projects") / proj_name
        pous_dir = proj_dir / "pous"
        pous_dir.mkdir(parents=True, exist_ok=True)
        pou_file = pous_dir / "ExistingControl.st"

        good_code = "PROGRAM ExistingControl\nVAR\n  bRun : BOOL;\nEND_VAR\nbRun := TRUE;\nEND_PROGRAM"
        pou_file.write_text(good_code, encoding="utf-8")
        orig_bytes = pou_file.read_bytes()

        try:
            bad_code = "PROGRAM ExistingControl\nVAR\n  bRun : BOOL;\nEND_VAR\n  ---( )---\nEND_PROGRAM"
            res = cscape_add_st_pou(proj_name, "ExistingControl", "PROGRAM", bad_code)
            assert res["success"] is False
            assert res["status"] == "failed"
            assert pou_file.read_bytes() == orig_bytes
        finally:
            shutil.rmtree(proj_dir, ignore_errors=True)

    def test_c2_n25_add_st_pou_new_pou_failure_leaves_no_orphan_file(self):
        """cscape_add_st_pou for a new POU that fails validation leaves no orphan file on disk."""
        proj_name = "NoOrphanTestProj"
        proj_dir = Path("artifacts/projects") / proj_name
        pous_dir = proj_dir / "pous"
        pous_dir.mkdir(parents=True, exist_ok=True)
        new_pou_file = pous_dir / "BrandNewFailedPOU.st"

        try:
            broken_code = "PROGRAM BrandNewFailedPOU\nVAR\n  val : INT\nEND_VAR\nval := ;\nEND_PROGRAM"
            res = cscape_add_st_pou(proj_name, "BrandNewFailedPOU", "PROGRAM", broken_code)
            assert res["success"] is False
            assert res["status"] == "failed"
            assert not new_pou_file.exists()
        finally:
            shutil.rmtree(proj_dir, ignore_errors=True)
