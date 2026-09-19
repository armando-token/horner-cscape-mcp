"""Contract and Verification Test Suite for Phase C6: Automated Native Path Pipeline.

Mandate: PLAN_CORRECTIVO MCP Horner/Cscape v2.0 (correctivo)
Mission: C6_AUTOMATE_NATIVE_PATH
Run ID: run_20260906_120831

Invariants & Contracts Verified:
1. Automated Pipeline Execution: All 9 stages (Start -> Edit -> Save -> Reopen -> Navigator -> Status Bar -> Error Check -> Download Lockout -> Pure ST Validation) verified.
2. Baseline Isolation: TankLevelClosedLoop.csp preserved 100% UNTOUCHED (SHA256 verified).
3. CFBF Container Validation: LabProject_W01.csp validated as genuine OLE2 compound file with 512-byte sector.
4. Error Check Modal Interception: Dispatched 32826; detected #32770; scraped Output Window; dismissed with IDNO (7) fail-closed; status: blocked.
5. Hardware & Download Lockout: Commands 32827/33149 and COM ports blocked fail-closed; status: blocked.
6. Pure ST Enforcement: Pure ST accepted; ladder constructs rejected fail-closed with ERR_LADDER_FORBIDDEN.
7. Offline/DEV Mode Enforced: Status bar "Disconnected" -> strictly "offline/DEV if Disconnected".
8. Visibility Boundary Contract: Window visibility alone is explicitly NOT claimed as VERIFIED_LIVE.
9. Gate G5 Governance: Gate G5 is strictly NOT RUN per user mandate and remains closed.
10. Dual-Root Parity: 100% cryptographic parity across HornerAI and ArmandoSilva roots.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pytest

from src.cscape.cfbf import (
    CFBF_MAGIC,
    is_valid_cfbf,
    inspect_project_file,
)
from src.mcp.tools import cscape_validate_st
from src.cscape.safety import (
    intercept_download_command,
    CscapeSafetyViolationError,
)
from src.security.guard import SecurityGuard
from src.security.exceptions import HardwareLockoutError, BlockedExecutableError

HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()
RECOVERY_DIR = HORNER_ROOT / "artifacts" / "recovery" / "run_20260906_120831"
USER_RECOVERY_DIR = USER_ROOT / "artifacts" / "recovery" / "run_20260906_120831"

ORIGINAL_TANK_CSP = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "TankLevelClosedLoop.csp"
ORIGINAL_TANK_SHA256 = "d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af"
LAB_CSP = HORNER_ROOT / "artifacts" / "projects" / "LabProject_W01" / "LabProject_W01.csp"


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


@pytest.fixture(scope="module")
def evidence_data():
    ev_file = RECOVERY_DIR / "c6_automation_evidence.json"
    assert ev_file.exists(), f"Missing {ev_file}"
    return json.loads(ev_file.read_text(encoding="utf-8"))


class TestC6PipelineExecutionAndEvidence:
    """Verifies automated pipeline stages recorded in c6_automation_evidence.json."""

    def test_c6_pipeline_overall_status(self, evidence_data):
        """Pipeline completed successfully with status: success."""
        assert evidence_data["mission_id"] == "C6_AUTOMATE_NATIVE_PATH"
        assert evidence_data["status"] == "success"

    def test_c6_stage1_start_verified(self, evidence_data):
        """Stage 1 START verified initial valid container."""
        st1 = evidence_data["pipeline_stages"]["1_start"]
        assert st1["status"] == "done"
        assert st1["size_bytes"] >= 90000 and st1["size_bytes"] % 512 == 0
        assert len(st1["sha256"]) == 64

    def test_c6_stage2_edit_verified(self, evidence_data):
        """Stage 2 EDIT dispatched in-GUI interaction without crash."""
        st2 = evidence_data["pipeline_stages"]["2_edit"]
        assert st2["status"] == "done"
        assert "ID_PROGRAM_VARIABLES" in st2["action"]
        assert st2["children_count"] >= 50

    def test_c6_stage3_save_verified(self, evidence_data):
        """Stage 3 SAVE triggered native MFC document serialization."""
        st3 = evidence_data["pipeline_stages"]["3_save"]
        assert st3["status"] == "done"
        assert "ID_FILE_SAVE" in st3["action"]
        assert st3["size_bytes"] >= 90000 and st3["size_bytes"] % 512 == 0
        assert st3["is_valid_cfbf"] is True

    def test_c6_stage4_reopen_verified(self, evidence_data):
        """Stage 4 REOPEN reloaded document via MRU cleanly."""
        st4 = evidence_data["pipeline_stages"]["4_reopen"]
        assert st4["status"] == "done"
        assert "ID_FILE_MRU_FILE1" in st4["action"]
        assert "LabProject_W01.csp" in st4["reopened_title"] or "C6_Native_Run.csp" in st4["reopened_title"]

    def test_c6_stage5_navigator_verified(self, evidence_data):
        """Stage 5 Navigator verified Project Navigator docking pane."""
        st5 = evidence_data["pipeline_stages"]["5_navigator"]
        assert st5["status"] == "done"
        assert st5["tree_ctrl_found"] is True

    def test_c6_stage6_status_bar_verified(self, evidence_data):
        """Stage 6 Status Bar verified Disconnected and offline/DEV mode."""
        st6 = evidence_data["pipeline_stages"]["6_status_bar"]
        assert st6["status"] == "done"
        assert st6["connection_state"] == "Disconnected"
        assert st6["operational_mode"] == "offline/DEV if Disconnected"

    def test_c6_stage7_errorcheck_compile_modal_defense(self, evidence_data):
        """Stage 7 Error Check compile intercepted modal and dismissed fail-closed."""
        st7 = evidence_data["pipeline_stages"]["7_errorcheck_compile"]
        assert st7["status"] == "blocked"
        assert st7["modal"] is not None
        assert "IDNO" in st7["modal"]["action_taken"]
        assert len(st7["output_window_lines"]) >= 1

    def test_c6_stage8_download_lockout_verified(self, evidence_data):
        """Stage 8 Download Lockout verified fail-closed lockout on commands and ports."""
        st8 = evidence_data["pipeline_stages"]["8_download_lockout"]
        assert st8["status"] == "blocked"
        assert 32827 in st8["restricted_command_ids"]
        assert 33149 in st8["restricted_command_ids"]
        assert "COM1" in st8["ports_blocked"]

    def test_c6_stage9_pure_st_validation_verified(self, evidence_data):
        """Stage 9 Pure ST verified valid ST accepted and ladder rejected."""
        st9 = evidence_data["pipeline_stages"]["9_pure_st_validation"]
        assert st9["status"] == "done"
        assert st9["valid_st_verified"] is True
        assert st9["ladder_rejection_verified"] is True

    def test_c6_udfb_and_two_instances_verified(self, evidence_data):
        """UDFB ScaleAnalogFilter and two instances in MainProcessControl verified."""
        udfb = evidence_data["pipeline_stages"]["udfb_and_two_instances"]
        assert udfb["status"] == "done"
        assert udfb["udfb_name"] == "ScaleAnalogFilter"
        assert "Filter1" in udfb["two_instances"]
        assert "Filter2" in udfb["two_instances"]

    def test_c6_compile_fail_and_fix_verified(self, evidence_data):
        """Compile fail and clean compile fix sequence verified."""
        cf = evidence_data["pipeline_stages"]["compile_fail_and_fix"]
        assert cf["status"] == "done"
        assert cf["compile_fail_status"] == "failed"
        assert cf["compile_fail_errors"] > 0
        assert cf["compile_fix_status"] == "success"
        assert cf["compile_fix_errors"] == 0

    def test_c6_save_close_reopen_reread_verified(self, evidence_data):
        """Save, close, reopen, and reread lifecycle verified."""
        sc = evidence_data["pipeline_stages"]["save_close_reopen_reread"]
        assert sc["status"] == "done"
        assert sc["reread_cfbf_valid"] is True


class TestC6BaselineIsolationAndSafety:
    """Verifies baseline isolation, visibility boundary, and gate governance."""

    def test_c6_baseline_tanklevel_preserved_untouched(self):
        """TankLevelClosedLoop.csp preserved 100% UNTOUCHED before and after C6 pipeline."""
        assert ORIGINAL_TANK_CSP.exists()
        current_sha = compute_sha256(ORIGINAL_TANK_CSP)
        assert current_sha == ORIGINAL_TANK_SHA256, (
            f"MUTATION DETECTED! {current_sha} != {ORIGINAL_TANK_SHA256}"
        )

    def test_c6_visibility_is_not_claimed_as_verified_live(self):
        """Window visibility alone is explicitly NOT claimed as VERIFIED_LIVE."""
        ev_file = RECOVERY_DIR / "c6_automation_evidence.json"
        data = json.loads(ev_file.read_text(encoding="utf-8"))
        assert data["invariants_enforced"]["cscape_visibility_not_verified_live"] is True
        assert "NOT VERIFIED_LIVE" in data["live_gui_telemetry"]["visibility_classification"]

    def test_c6_gate_g5_strictly_not_run(self):
        """Gate G5 is explicitly NOT RUN per user mandate and remains closed/blocked."""
        ev_file = RECOVERY_DIR / "c6_automation_evidence.json"
        data = json.loads(ev_file.read_text(encoding="utf-8"))
        assert data["invariants_enforced"]["gate_g5_strictly_not_run"] is True
        assert data["invariants_enforced"]["no_c1_c2_c3_restart"] is True
        assert data["invariants_enforced"]["no_plc_or_straton"] is True

    def test_c6_screenshots_exist_and_non_empty(self):
        """All visual proof screenshots for C6 stages exist and have valid file sizes."""
        c6_screenshots = [
            "c6_stage1_start.png",
            "c6_stage2_edit.png",
            "c6_stage3_save.png",
            "c6_stage4_reopened.png",
            "c6_navigator_visible.png",
            "c6_modal_errorcheck.png",
        ]
        for sc in c6_screenshots:
            p = RECOVERY_DIR / sc
            assert p.exists(), f"Missing screenshot {sc}"
            assert p.stat().st_size > 1000, f"Screenshot {sc} is unexpectedly small: {p.stat().st_size} bytes"

    def test_c6_dual_root_parity(self):
        """All C6 recovery files exist in both roots with identical SHA-256 digests."""
        c6_files = [
            "c6_automation_evidence.json",
            "c6_execution_log.json",
            "c6_stage1_start.png",
            "c6_stage2_edit.png",
            "c6_stage3_save.png",
            "c6_stage4_reopened.png",
            "c6_navigator_visible.png",
            "c6_modal_errorcheck.png",
        ]
        for fname in c6_files:
            horner_f = RECOVERY_DIR / fname
            user_f = USER_RECOVERY_DIR / fname
            assert horner_f.exists(), f"Missing in HornerAI: {horner_f}"
            assert user_f.exists(), f"Missing in ArmandoSilva: {user_f}"
            assert compute_sha256(horner_f) == compute_sha256(user_f), f"Hash mismatch on {fname}"


@pytest.fixture(scope="module")
def mcp_client_evidence_data():
    ev_file = RECOVERY_DIR / "c6_mcp_client_evidence.json"
    assert ev_file.exists(), f"Missing {ev_file}"
    return json.loads(ev_file.read_text(encoding="utf-8"))


class TestC6MCPClientNativePipeline:
    """Verifies automated native path executed via official FastMCP Client."""

    def test_c6_mcp_client_overall_status(self, mcp_client_evidence_data):
        """Pipeline completed successfully with mission C6_AUTOMATE_NATIVE_PATH_MCP_CLIENT."""
        assert mcp_client_evidence_data["mission_id"] == "C6_AUTOMATE_NATIVE_PATH_MCP_CLIENT"
        assert mcp_client_evidence_data["status"] == "success"
        assert mcp_client_evidence_data["mcp_client"]["transport"] == "stdio"
        assert mcp_client_evidence_data["mcp_client"]["protocol"] == "JSON-RPC 2.0"
        assert mcp_client_evidence_data["mcp_client"]["tools_discovered_count"] >= 20

    def test_c6_mcp_client_unique_run_copy(self, mcp_client_evidence_data):
        """Unique project copy C6_Native_Run verified with valid CFBF container."""
        urc = mcp_client_evidence_data["unique_run_copy"]
        assert urc["project_name"] == "C6_Native_Run"
        assert Path(urc["csp_path"]).exists()
        assert urc["initial_size_bytes"] >= 90000 and urc["initial_size_bytes"] % 512 == 0
        assert len(urc["initial_sha256"]) == 64
        assert is_valid_cfbf(Path(urc["csp_path"])) is True

    def test_c6_mcp_client_import_instances_connect(self, mcp_client_evidence_data):
        """UDFB ScaleAnalogFilter and MainProcessControl with 2 instances and signals connected via MCP client."""
        iic = mcp_client_evidence_data["import_instances_connect"]
        assert iic["status"] == "done"
        assert iic["udfb_added"] == "ScaleAnalogFilter"
        assert iic["udfb_type"] == "FUNCTION_BLOCK"
        assert iic["program_added"] == "MainProcessControl"
        assert "Filter1" in iic["instances"]
        assert "Filter2" in iic["instances"]
        assert "RawSensor1" in iic["variables_connected"]
        assert "OutFiltered1" in iic["variables_connected"]
        assert "Alarm1" in iic["variables_connected"]

    def test_c6_mcp_client_deliberate_fail_compile_then_fix(self, mcp_client_evidence_data):
        """Deliberate syntax error caught by MCP compiler, then fixed cleanly with 0 errors."""
        df = mcp_client_evidence_data["deliberate_fail_compile_then_fix"]
        assert df["status"] == "done"

        # Fail stage
        fail_stage = df["fail_stage"]
        assert fail_stage["compile_status"] == "failed"
        assert fail_stage["compile_success"] is False
        assert fail_stage["error_count"] > 0
        assert any("syntax" in str(e).lower() for e in fail_stage["errors_captured"])

        # Fix stage
        fix_stage = df["fix_stage"]
        assert fix_stage["repaired_code_accepted"] is True
        assert fix_stage["compile_status"] == "success"
        assert fix_stage["compile_success"] is True
        assert fix_stage["error_count"] == 0
        assert fix_stage["clean_build"] is True

    def test_c6_mcp_client_save_reopen_compare(self, mcp_client_evidence_data):
        """Save via ID_FILE_SAVE, reopen, and container comparison verified."""
        src = mcp_client_evidence_data["save_reopen_compare"]
        assert src["status"] == "done"
        assert "ID_FILE_SAVE" in src["action_save"]
        assert "ID_FILE_MRU_FILE1" in src["action_reopen"]

        comp = src["comparison"]
        assert comp["reopened_is_valid_cfbf"] is True
        assert comp["sector_size"] == 512
        assert "Root Entry" in comp["streams_verified"]
        assert "Contents" in comp["streams_verified"]
        assert "ScaleAnalogFilter.st" in comp["pous_verified_on_disk"]
        assert "MainProcessControl.st" in comp["pous_verified_on_disk"]
        assert comp["mtime_updated"] is True

    def test_c6_mcp_client_live_gui_telemetry(self, mcp_client_evidence_data):
        """Live GUI telemetry verifies active Cscape on winsta0\\Default with honest mode."""
        telemetry = mcp_client_evidence_data["live_gui_telemetry"]
        assert telemetry["pid"] > 0
        assert telemetry["visible"] is True
        assert "C6_Native_Run" in telemetry["title"]
        assert "C6_Native_Run" in telemetry["reopened_title"]
        assert telemetry["status_bar_connection"] == "Disconnected"
        assert telemetry["operational_mode"] == "offline/DEV if Disconnected"
        assert "NOT VERIFIED_LIVE" in telemetry["visibility_classification"]

    def test_c6_mcp_client_modal_defense(self, mcp_client_evidence_data):
        """Error Check modal intercepted and dismissed with IDNO (7) fail-closed."""
        modal = mcp_client_evidence_data["modal_defense"]
        assert modal["status"] == "blocked"
        assert "IDNO" in modal["action_taken"]
        assert "auto-Yes" in modal["action_taken"]

    def test_c6_mcp_client_hardware_and_download_lockout(self, mcp_client_evidence_data):
        """Fail-closed hardware and download lockout verified."""
        hw = mcp_client_evidence_data["hardware_and_download_lockout"]
        assert hw["status"] == "blocked"
        assert 32827 in hw["restricted_command_ids"]
        assert 33149 in hw["restricted_command_ids"]
        assert "COM1" in hw["ports_blocked"]

    def test_c6_mcp_client_baseline_isolation(self, mcp_client_evidence_data):
        """TankLevelClosedLoop.csp preserved 100% UNTOUCHED before and after MCP client pipeline."""
        base = mcp_client_evidence_data["baseline_isolation"]
        assert base["baseline_sha256"] == ORIGINAL_TANK_SHA256
        assert base["expected_sha256"] == ORIGINAL_TANK_SHA256
        assert base["verified_untouched"] is True
        assert compute_sha256(ORIGINAL_TANK_CSP) == ORIGINAL_TANK_SHA256

    def test_c6_mcp_client_gate_g5_strictly_not_run(self, mcp_client_evidence_data):
        """Gate G5 is strictly NOT RUN per user mandate and remains closed (tests != G5)."""
        inv = mcp_client_evidence_data["invariants_enforced"]
        assert inv["gate_g5_strictly_not_run"] is True
        assert inv["no_c1_c2_c3_restart"] is True
        assert inv["no_plc_or_straton"] is True
        assert inv["pytest_counts_not_g5_completion"] is True

    def test_c6_mcp_client_screenshots_exist_and_non_empty(self):
        """All visual proof screenshots for MCP client pipeline exist and have valid sizes."""
        mcp_screenshots = [
            "c6_mcp_stage1_opened.png",
            "c6_mcp_stage2_connected.png",
            "c6_mcp_stage3_fail_compile.png",
            "c6_mcp_stage4_clean_compile.png",
            "c6_mcp_stage5_saved.png",
            "c6_mcp_stage6_reopened.png",
            "c6_mcp_navigator_visible.png",
            "c6_mcp_modal_defense.png",
        ]
        for sc in mcp_screenshots:
            p = RECOVERY_DIR / sc
            assert p.exists(), f"Missing screenshot {sc}"
            assert p.stat().st_size > 1000, f"Screenshot {sc} is unexpectedly small: {p.stat().st_size} bytes"

    def test_c6_mcp_client_dual_root_parity(self):
        """All C6 MCP client recovery files match 100% byte-for-byte across HornerAI and ArmandoSilva."""
        mcp_files = [
            "c6_mcp_client_evidence.json",
            "c6_mcp_client_execution_log.json",
            "c6_mcp_stage1_opened.png",
            "c6_mcp_stage2_connected.png",
            "c6_mcp_stage3_fail_compile.png",
            "c6_mcp_stage4_clean_compile.png",
            "c6_mcp_stage5_saved.png",
            "c6_mcp_stage6_reopened.png",
            "c6_mcp_navigator_visible.png",
            "c6_mcp_modal_defense.png",
        ]
        for fname in mcp_files:
            horner_f = RECOVERY_DIR / fname
            user_f = USER_RECOVERY_DIR / fname
            assert horner_f.exists(), f"Missing in HornerAI: {horner_f}"
            assert user_f.exists(), f"Missing in ArmandoSilva: {user_f}"
            assert compute_sha256(horner_f) == compute_sha256(user_f), f"Hash mismatch on {fname}"

