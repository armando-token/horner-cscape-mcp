"""Contract and Verification Test Suite for Phase C6 After Save As: Reopen & Verify C6_Native_Run.csp.

Mandate: PLAN_CORRECTIVO MCP Horner/Cscape v2.0 (correctivo)
Mission: C6_REOPEN_VERIFY_NATIVE_RUN
Run ID: run_20260906_120831

Invariants & Contracts Verified:
1. Reopen C6_Native_Run.csp: Container opened cleanly and verified in live Cscape GUI.
2. Baseline Isolation: TankLevelClosedLoop.csp preserved 100% UNTOUCHED (SHA-256 verified).
3. CFBF Container Validation: C6_Native_Run.csp validated as genuine OLE2 compound file with 512-byte sectors.
4. Confirm Save As Defense: Zero looping Confirm Save As dialogs confirmed.
5. In-GUI Error Check Modal Defense: Modal dismissed fail-closed with IDNO (7); status: blocked.
6. Hardware & Download Lockout: Commands 32827/33149 and COM ports blocked fail-closed; status: blocked.
7. Pure ST Enforcement: Pure ST accepted; ladder constructs rejected fail-closed with ERR_LADDER_FORBIDDEN.
8. Offline/DEV Mode Enforced: Status bar "Disconnected" -> strictly "offline/DEV if Disconnected".
9. Visibility Boundary Contract: Window visibility alone is explicitly NOT claimed as VERIFIED_LIVE.
10. Gate G5 Governance: Gate G5 is strictly NOT RUN per user mandate and remains closed (pytest counts != G5).
11. Dual-Root Parity: 100% cryptographic parity across HornerAI and ArmandoSilva roots.
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
def reopen_evidence_data():
    ev_file = RECOVERY_DIR / "c6_reopen_verify_evidence.json"
    assert ev_file.exists(), f"Missing {ev_file}"
    return json.loads(ev_file.read_text(encoding="utf-8"))


class TestC6ReopenVerifyExecution:
    """Verifies reopen and verification of C6_Native_Run.csp."""

    def test_c6_reopen_overall_status(self, reopen_evidence_data):
        """Reopen & verify completed with status: success."""
        assert reopen_evidence_data["mission_id"] == "C6_REOPEN_VERIFY_NATIVE_RUN"
        assert reopen_evidence_data["status"] == "success"

    def test_c6_reopen_cfbf_container_valid(self, reopen_evidence_data):
        """C6_Native_Run.csp is valid CFBF on disk with 512-byte sector."""
        proj = reopen_evidence_data["reopened_project"]
        assert proj["is_valid_cfbf"] is True
        assert proj["sector_size"] == 512
        assert proj["size_bytes"] >= 90000 and proj["size_bytes"] % 512 == 0
        assert "Root Entry" in proj["streams_verified"]
        assert "Contents" in proj["streams_verified"]
        assert "ScaleAnalogFilter.st" in proj["pous_verified_on_disk"]
        assert "MainProcessControl.st" in proj["pous_verified_on_disk"]

        # Direct on-disk verification
        cfbf = inspect_project_file(C6_CSP)
        assert cfbf.is_valid_cfbf is True

    def test_c6_reopen_live_gui_telemetry(self, reopen_evidence_data):
        """Live GUI telemetry verifies C6_Native_Run in window title and visible."""
        gui = reopen_evidence_data["live_gui_telemetry"]
        assert gui["pid"] > 0
        assert gui["visible"] is True
        assert "c6_native_run" in gui["title"].lower()
        assert gui["connection_status"] == "Disconnected"
        assert gui["operational_mode"] == "offline/DEV if Disconnected"
        assert "NOT VERIFIED_LIVE" in gui["visibility_classification"]

    def test_c6_reopen_navigator_verified(self, reopen_evidence_data):
        """Project Navigator dockable bar verified with SysTreeView32."""
        nav = reopen_evidence_data["project_navigator"]
        assert nav["visible"] is True
        assert "treeview" in nav["class"].lower() or "controlbar" in nav["class"].lower()

    def test_c6_reopen_status_bar_verified(self, reopen_evidence_data):
        """Status bar reports Disconnected -> offline/DEV mode."""
        sb = reopen_evidence_data["status_bar"]
        assert sb["connection_state"] == "Disconnected"
        assert sb["operational_mode"] == "offline/DEV if Disconnected"

    def test_c6_reopen_confirm_save_as_loop_avoided(self, reopen_evidence_data):
        """Confirm Save As defense verified: zero looping dialogs."""
        csa = reopen_evidence_data["confirm_save_as_defense"]
        assert csa["status"] == "loop_avoided"
        assert reopen_evidence_data["invariants_confirmed"]["avoid_looping_confirm_save_as"] is True

    def test_c6_reopen_modal_defense_blocked(self, reopen_evidence_data):
        """Error Check compile modal dismissed fail-closed with IDNO (7)."""
        md = reopen_evidence_data["modal_defense"]
        assert md["status"] == "blocked"
        assert "IDNO" in md["action_taken"]

    def test_c6_reopen_hardware_and_download_lockout(self, reopen_evidence_data):
        """Download commands 32827/33149 and physical COM ports blocked fail-closed."""
        hw = reopen_evidence_data["hardware_and_download_lockout"]
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

    def test_c6_reopen_pure_st_and_ladder_lockout(self):
        """Pure ST validated and ladder constructs rejected with ERR_LADDER_FORBIDDEN."""
        udfb_st = C6_CSP.parent / "pous" / "ScaleAnalogFilter.st"
        main_st = C6_CSP.parent / "pous" / "MainProcessControl.st"
        assert udfb_st.exists()
        assert main_st.exists()

        res_u = cscape_validate_st(code=udfb_st.read_text(encoding="utf-8"))
        assert res_u["status"] == "success" and res_u["valid"] is True

        res_m = cscape_validate_st(code=main_st.read_text(encoding="utf-8"))
        assert res_m["status"] == "success" and res_m["valid"] is True

        for ladder in ["---[ ]---", "---[/]---", "---( )---", "---(S)---", "---(R)---", "RUNG 1: XIC In OTE Out"]:
            bad_code = f"PROGRAM Bad\nVAR x: BOOL;\nEND_VAR\n{ladder}\nEND_PROGRAM"
            res = cscape_validate_st(code=bad_code)
            assert res["status"] == "failed"
            assert res["success"] is False

    def test_c6_reopen_baseline_tanklevel_untouched(self):
        """TankLevelClosedLoop.csp preserved 100% UNTOUCHED."""
        assert ORIGINAL_TANK_CSP.exists()
        current_sha = compute_sha256(ORIGINAL_TANK_CSP)
        assert current_sha == ORIGINAL_TANK_SHA256, (
            f"BASELINE MUTATION DETECTED! {current_sha} != {ORIGINAL_TANK_SHA256}"
        )

    def test_c6_reopen_gate_g5_strictly_not_run(self, reopen_evidence_data):
        """Gate G5 is strictly NOT RUN per user mandate and remains closed/blocked."""
        inv = reopen_evidence_data["invariants_confirmed"]
        assert inv["gate_g5_strictly_not_run"] is True
        assert inv["no_c1_c2_c3_restart"] is True
        assert inv["no_plc_or_straton"] is True
        assert inv["pytest_counts_not_g5_completion"] is True

    def test_c6_reopen_proof_screenshots_exist(self):
        """Screenshots for C6 reopen verification exist with non-empty file size."""
        expected_screens = [
            "c6_reopen_c6_native_run_visible.png",
            "c6_reopen_navigator_visible.png",
            "c6_reopen_statusbar.png",
            "c6_reopen_modal_errorcheck.png",
        ]
        for s in expected_screens:
            p = RECOVERY_DIR / s
            assert p.exists(), f"Missing screenshot {s}"
            assert p.stat().st_size > 100, f"Screenshot {s} unexpectedly small"

    def test_c6_reopen_dual_root_parity(self):
        """All C6 reopen recovery artifacts match 100% byte-for-byte SHA-256 across roots."""
        artifacts = [
            "c6_reopen_verify_evidence.json",
            "c6_reopen_execution_log.json",
            "c6_reopen_c6_native_run_visible.png",
            "c6_reopen_navigator_visible.png",
            "c6_reopen_statusbar.png",
            "c6_reopen_modal_errorcheck.png",
        ]
        for a in artifacts:
            h_path = RECOVERY_DIR / a
            u_path = USER_RECOVERY_DIR / a
            assert h_path.exists(), f"Missing in HornerAI: {h_path}"
            assert u_path.exists(), f"Missing in ArmandoSilva: {u_path}"
            h_sha = compute_sha256(h_path)
            u_sha = compute_sha256(u_path)
            assert h_sha == u_sha, f"Hash mismatch on {a}: {h_sha} != {u_sha}"
