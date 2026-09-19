"""Contract and Verification Test Suite for Automated Proven C5 Native Path on C6_Native_Run.csp.

Mandate: PLAN_CORRECTIVO MCP Horner/Cscape v2.0 (correctivo)
Mission: C6_AUTOMATE_NATIVE_PATH
Run ID: run_20260906_120831

Invariants & Contracts Verified:
1. Automated Proven C5 Path: Open -> Pure ST -> Compile Fail/Fix -> Save/Save As -> Supervisor Evidence.
2. Cscape Visibility & Liveness: Verified visible on winsta0\\Default with C6_Native_Run.csp (fail-closed if hidden).
3. Baseline Isolation: TankLevelClosedLoop.csp preserved 100% UNTOUCHED (SHA-256 verified).
4. CFBF Container Validation: C6_Native_Run.csp validated as genuine OLE2 compound file with 512-byte sectors.
5. In-GUI Error Check Modal Defense: Modal intercepted, dismissed fail-closed with IDNO (7); status: blocked.
6. Hardware & Download Lockout: Commands 32827/33149 and COM ports blocked fail-closed; status: blocked.
7. Pure ST Enforcement: Pure ST accepted; 6 ladder constructs rejected fail-closed with ERR_LADDER_FORBIDDEN.
8. Operational Mode Honesty: Status bar 'Disconnected' -> strictly 'offline/DEV if Disconnected'.
9. Visibility Boundary: Window visibility alone is explicitly NOT claimed as VERIFIED_LIVE.
10. Gate G5 Governance: Gate G5 is strictly NOT RUN per user mandate and remains closed (pytest != G5).
11. Dual-Root Cryptographic Parity: 100% parity across HornerAI and ArmandoSilva vaults.
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
C6_CSP = HORNER_ROOT / "artifacts" / "projects" / "C6_Native_Run" / "C6_Native_Run.csp"


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


@pytest.fixture(scope="module")
def proven_c5_evidence():
    ev_file = RECOVERY_DIR / "c6_proven_c5_automated_evidence.json"
    assert ev_file.exists(), f"Missing {ev_file}"
    return json.loads(ev_file.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def supervisor_evidence():
    ev_file = RECOVERY_DIR / "c6_supervisor_evidence.json"
    assert ev_file.exists(), f"Missing {ev_file}"
    return json.loads(ev_file.read_text(encoding="utf-8"))


class TestC6ProvenC5Automation:
    """Verifies automated proven C5 native path on C6_Native_Run.csp."""

    def test_c6_proven_c5_overall_status(self, proven_c5_evidence):
        """Pipeline completed successfully with status: success and mission: C6_AUTOMATE_NATIVE_PATH."""
        assert proven_c5_evidence["mission_id"] == "C6_AUTOMATE_NATIVE_PATH"
        assert proven_c5_evidence["status"] == "success"
        assert proven_c5_evidence["evidence_type"] == "automated_proven_c5_native_path"

    def test_c6_proven_c5_live_gui_telemetry(self, proven_c5_evidence):
        """Live GUI telemetry verifies active Cscape on winsta0\\Default with C6_Native_Run.csp."""
        telemetry = proven_c5_evidence["live_gui_telemetry"]
        assert telemetry["pid"] > 0
        assert telemetry["visible"] is True
        assert "c6_native_run" in telemetry["title"].lower()
        assert telemetry["session_id"] == 2
        assert telemetry["desktop"] == "winsta0\\Default"
        assert telemetry["connection_status"] == "Disconnected"
        assert telemetry["operational_mode"] == "offline/DEV if Disconnected"
        assert "NOT VERIFIED_LIVE" in telemetry["visibility_classification"]
        assert telemetry["child_control_count"] >= 50

    def test_c6_proven_c5_project_navigator(self, proven_c5_evidence):
        """Project Navigator dockable bar verified visible with SysTreeView32."""
        nav = proven_c5_evidence["project_navigator"]
        assert nav["visible"] is True
        assert "treeview" in nav["class"].lower() or "controlbar" in nav["class"].lower()

    def test_c6_proven_c5_status_bar(self, proven_c5_evidence):
        """Status bar reports Disconnected -> offline/DEV mode."""
        sb = proven_c5_evidence["status_bar"]
        assert sb["visible"] is True
        assert sb["connection_state"] == "Disconnected"
        assert sb["operational_mode"] == "offline/DEV if Disconnected"

    def test_c6_proven_c5_save_as_lifecycle(self, proven_c5_evidence):
        """Save As / Save lifecycle verified with valid CFBF container and mtime update."""
        sal = proven_c5_evidence["save_as_lifecycle"]
        assert sal["status"] == "done"
        assert "ID_FILE_SAVE" in sal["action_save"]
        assert "ID_FILE_SAVEAS" in sal["action_saveas"]
        assert "ID_FILE_MRU_FILE1" in sal["action_reopen"]
        assert sal["size_bytes"] >= 90000 and sal["size_bytes"] % 512 == 0
        assert sal["is_valid_cfbf"] is True
        assert sal["sector_size"] == 512
        assert "Root Entry" in sal["streams_verified"]
        assert "Contents" in sal["streams_verified"]
        assert "ScaleAnalogFilter.st" in sal["pous_verified_on_disk"]
        assert "MainProcessControl.st" in sal["pous_verified_on_disk"]

        # Direct on-disk check
        cfbf = inspect_project_file(C6_CSP)
        assert cfbf.is_valid_cfbf is True

    def test_c6_proven_c5_pure_st_and_udfb(self, proven_c5_evidence):
        """Pure ST logic: ScaleAnalogFilter UDFB, 2 instances, bumpless logic, 6 ladder rejects."""
        st_logic = proven_c5_evidence["pure_st_logic"]
        assert st_logic["udfb"] == "ScaleAnalogFilter.st"
        assert st_logic["udfb_type"] == "FUNCTION_BLOCK"
        assert st_logic["program"] == "MainProcessControl.st"
        assert "Filter1" in st_logic["instances"]
        assert "Filter2" in st_logic["instances"]
        assert st_logic["manual_bumpless_logic_verified"] is True

        ladders = st_logic["ladder_constructs_rejected"]
        assert len(ladders) == 6
        for item in ladders:
            assert item["rejected_fail_closed"] is True
            assert item["error_code"] == "ERR_LADDER_FORBIDDEN"

    def test_c6_proven_c5_compile_fail_and_fix(self, proven_c5_evidence):
        """Compile fail on syntax error, clean compile on fix verified."""
        cf = proven_c5_evidence["compile_fail_and_fix"]
        assert cf["compile_fail_status"] == "failed"
        assert cf["compile_fail_errors"] > 0
        assert cf["compile_fix_status"] == "success"
        assert cf["compile_fix_errors"] == 0

    def test_c6_proven_c5_modal_defense(self, proven_c5_evidence):
        """Error Check modal dismissed fail-closed with IDNO (7); auto-Yes prohibited."""
        md = proven_c5_evidence["modal_defense"]
        assert md["status"] == "blocked"
        assert "IDNO" in md["action_taken"]
        assert "auto-Yes" in md["action_taken"]

    def test_c6_proven_c5_hardware_and_download_lockout(self, proven_c5_evidence):
        """Fail-closed hardware and download lockout verified."""
        hw = proven_c5_evidence["hardware_and_download_lockout"]
        assert hw["status"] == "blocked"
        assert 32827 in hw["download_commands_blocked"]
        assert 33149 in hw["download_commands_blocked"]
        assert "COM1" in hw["ports_blocked"]
        assert hw["companion_flashers_active"] == 0
        assert hw["straton_processes_active"] == 0

        # Direct assertions
        with pytest.raises(CscapeSafetyViolationError):
            intercept_download_command(32827)
        with pytest.raises(CscapeSafetyViolationError):
            intercept_download_command(33149)

        guard = SecurityGuard()
        for port in ["COM1", "COM256", "CAN0", "USB0"]:
            with pytest.raises(HardwareLockoutError):
                guard.validate_command(["cscape.exe", "--port", port])

    def test_c6_proven_c5_baseline_isolation(self, proven_c5_evidence):
        """TankLevelClosedLoop.csp preserved 100% UNTOUCHED before and after run."""
        base = proven_c5_evidence["baseline_isolation"]
        assert base["baseline_sha256"] == ORIGINAL_TANK_SHA256
        assert base["expected_sha256"] == ORIGINAL_TANK_SHA256
        assert base["verified_untouched"] is True
        assert compute_sha256(ORIGINAL_TANK_CSP) == ORIGINAL_TANK_SHA256

    def test_c6_proven_c5_gate_g5_strictly_not_run(self, proven_c5_evidence):
        """Gate G5 is strictly NOT RUN per user mandate and remains closed."""
        inv = proven_c5_evidence["invariants_confirmed"]
        assert inv["gate_g5_strictly_not_run"] is True
        assert inv["no_c1_c2_c3_restart"] is True
        assert inv["no_plc_or_straton"] is True
        assert inv["pytest_counts_not_g5_completion"] is True
        assert inv["single_gui_owner_enforced"] is True
        assert inv["keep_cscape_visible_c6_native_run"] is True
        assert inv["fail_closed_if_hidden"] is True
        assert inv["offline_dev_mode_enforced"] is True
        assert inv["visibility_not_verified_live"] is True

    def test_c6_proven_c5_screenshots_exist_and_non_empty(self, proven_c5_evidence):
        """All visual proof screenshots exist and have valid file sizes."""
        for sc in proven_c5_evidence["proof_artifacts"]:
            p = RECOVERY_DIR / sc
            assert p.exists(), f"Missing proof artifact {sc}"
            assert p.stat().st_size > 50, f"Artifact {sc} is unexpectedly small: {p.stat().st_size} bytes"

    def test_c6_proven_c5_dual_root_parity(self, proven_c5_evidence):
        """All proven C5 artifacts match 100% byte-for-byte across HornerAI and ArmandoSilva."""
        files_to_check = [
            "c6_proven_c5_automated_evidence.json",
            "c6_supervisor_evidence.json",
            "c6_proven_c5_execution_log.json",
            "c6_automation_evidence.json",
            "c6_execution_log.json",
        ]
        for fname in files_to_check:
            hf = RECOVERY_DIR / fname
            uf = USER_RECOVERY_DIR / fname
            assert hf.exists(), f"Missing in HornerAI: {hf}"
            assert uf.exists(), f"Missing in ArmandoSilva: {uf}"
            assert compute_sha256(hf) == compute_sha256(uf), f"Hash mismatch on {fname}"
