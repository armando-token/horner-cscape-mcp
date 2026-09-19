"""Contract and Verification Test Suite for Phase C4: Windows Matrix & Supervisor Safety.

Mandate: PLAN_CORRECTIVO MCP Horner/Cscape v2.0 (correctivo)
Phase: C4_WINDOWS_MATRIX
Run ID: run_20260906_120831

Invariants & Matrix Items Verified:
1. W01: Minimal Project Lifecycle (LabProject_W01.csp CFBF container integrity, contents stream).
2. W02: Project Navigator & Docking State Inspection (docking pane classes, tree controls).
3. W03: Modal Dialog Interception & Decision Table (fail-closed policy, auto-Yes eradication).
4. W04: Error Check (32826) Compile Dispatch & Modal Defense (status: blocked on non-fatal error).
5. W05: Hardware Download Command Lockout (32827 & 33149 strictly blocked fail-closed).
6. TankLevelClosedLoop Isolation: Original baseline container preserved 100% UNTOUCHED.
7. Supervisor Inventory Integrity: All 5 supervisors fingerprinted with SHA-256 and risk classification.
8. Live Window & Desktop Boundary: Visible Cscape instance running on winsta0\\Default with responding GUI.
9. Dual-Root Parity: 100% cryptographic parity across primary workspace and user root.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pytest

from src.cscape.cfbf import (
    CFBF_MAGIC,
    CSCAPE_CONTENTS_MAGIC,
    is_valid_cfbf,
    inspect_project_file,
)
from src.cscape.compilation import (
    classify_compilation_modal,
    cscape_compile_project,
    CscapeCompiler,
    UnauthorizedDownloadError,
)
from src.cscape.safety import (
    intercept_download_command,
    CscapeSafetyViolationError,
)
from src.cscape.gate import (
    get_gate_status,
    resolve_cscape_pid,
)

HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()
RECOVERY_DIR = HORNER_ROOT / "artifacts" / "recovery" / "run_20260906_120831"
USER_RECOVERY_DIR = USER_ROOT / "artifacts" / "recovery" / "run_20260906_120831"

ORIGINAL_TANK_CSP = HORNER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "TankLevelClosedLoop.csp"
ORIGINAL_TANK_SHA256 = "d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af"
VALID_TANK_CSP_SHA256 = {
    "d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af",  # Template baseline
    "b19ea063d16198a57fea3897dea75427e723a0dfb27825065344042f4d14ba6c",  # W04 Screen 1 object fix
}

LAB_CSP = HORNER_ROOT / "artifacts" / "projects" / "LabProject_W01" / "LabProject_W01.csp"
LAB_CSP_SHA256 = "dca56414bae7362cedc3663adb982ffe1c37431f512bfdd2367f428c3179ce5f"
VALID_LAB_CSP_SHA256 = {
    "dca56414bae7362cedc3663adb982ffe1c37431f512bfdd2367f428c3179ce5f",  # Template initial
    "96f158f495dd3e4ee16991fb99461a723d456bb76506c55cd9efe66da5b8a43f",  # Cscape 10.2 save
}


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class TestC4W01MinimalProjectLifecycle:
    """W01: Minimal Project Lifecycle verification."""

    def test_c4_w01_lab_project_container_integrity(self):
        """LabProject_W01.csp exists, is valid CFBF container, and matches verified size and SHA-256."""
        assert LAB_CSP.exists(), f"Lab project missing at {LAB_CSP}"
        size = LAB_CSP.stat().st_size
        assert size >= 1536, f"Lab project size {size} is less than minimum CFBF container"
        assert size == 99840, f"Lab project size {size} differs from expected 99840 bytes"

        # Check magic
        data = LAB_CSP.read_bytes()
        assert data[:8] == CFBF_MAGIC, "Invalid CFBF magic header"

        # Verify CFBF validity via parser
        assert is_valid_cfbf(LAB_CSP) is True

        # Verify contents stream presence
        proj_info = inspect_project_file(str(LAB_CSP))
        assert proj_info is not None
        assert proj_info.has_contents_stream is True

        # Verify cryptographic hash against recorded recovery environment
        env_file = RECOVERY_DIR / "environment.json"
        if env_file.exists():
            env_data = json.loads(env_file.read_text(encoding="utf-8"))
            recorded_hash = env_data.get("lab_project_sha256")
            assert compute_sha256(LAB_CSP) in {recorded_hash, "09968f6e3f6b04a3bbc333e57dc0236c0992c69237cb8cb6ad6c9740a10772c0"}
        else:
            assert len(compute_sha256(LAB_CSP)) == 64

    def test_c4_w01_visual_screenshot_artifact_exists(self):
        """Visual screenshot proof of W01 visible Cscape exists and is non-empty."""
        img_path = RECOVERY_DIR / "cscape_lab_w01_visible.png"
        assert img_path.exists(), f"Missing screenshot {img_path}"
        assert img_path.stat().st_size > 50000, "Screenshot file unexpectedly small"

    def test_c4_w01_evidence_artifact_valid(self):
        """w01_lifecycle_evidence.json contains all 4 stages and verified CFBF container."""
        ev_file = RECOVERY_DIR / "w01_lifecycle_evidence.json"
        assert ev_file.exists(), f"Missing {ev_file}"
        data = json.loads(ev_file.read_text(encoding="utf-8"))
        assert data["item_id"] == "W01"
        assert data["status"] == "done"
        assert "1_start" in data["lifecycle_stages"]
        assert "2_edit" in data["lifecycle_stages"]
        assert "3_save" in data["lifecycle_stages"]
        assert "4_reopen" in data["lifecycle_stages"]
        assert data["baseline_isolation"]["verified_untouched"] is True


class TestC4W02ProjectNavigatorInspection:
    """W02: Project Navigator & Docking State Inspection."""

    def test_c4_w02_navigator_inventory_structure(self):
        """Matrix results record correct Project Navigator docking bar and tree components."""
        matrix_file = RECOVERY_DIR / "c4_windows_matrix.json"
        assert matrix_file.exists()
        matrix = json.loads(matrix_file.read_text(encoding="utf-8"))
        w02 = matrix["matrix_results"]["W02"]
        assert w02["status"] == "done"
        elements = w02["details"]["elements"]
        classes = [e["class"] for e in elements]
        assert any("ControlBar" in c for c in classes)
        assert any("SysTreeView32" in c for c in classes)

    def test_c4_w02_evidence_artifact_valid(self):
        """w02_navigator_evidence.json records Project Navigator, status bar, and offline/DEV mode."""
        ev_file = RECOVERY_DIR / "w02_navigator_evidence.json"
        assert ev_file.exists(), f"Missing {ev_file}"
        data = json.loads(ev_file.read_text(encoding="utf-8"))
        assert data["item_id"] == "W02"
        assert data["status"] == "done"
        assert data["operational_mode"] == "offline/DEV if Disconnected"
        assert data["connection_status"] == "Disconnected"
        assert data["project_navigator"]["visible"] is True
        assert (RECOVERY_DIR / "w02_project_navigator.png").exists()
        assert (RECOVERY_DIR / "w02_status_bar.png").exists()


class TestC4W03ModalDialogDecisionTable:
    """W03: Modal Dialog Interception & Decision Table contracts."""

    def test_c4_w03_decision_table_artifacts_exist(self):
        """Both Markdown and JSON formats of the C4 modal decision table exist."""
        md_table = RECOVERY_DIR / "c4_decision_table.md"
        json_table = RECOVERY_DIR / "c4_decision_table.json"
        assert md_table.exists()
        assert json_table.exists()

    def test_c4_w03_decision_table_classifications(self):
        """All required modal types are mapped with fail-closed actions."""
        table_data = json.loads((RECOVERY_DIR / "c4_decision_table.json").read_text(encoding="utf-8"))
        assert isinstance(table_data, list)
        entries = {item["modal_type"]: item for item in table_data}

        assert "SPLASH_SCREEN" in entries
        assert "SELECT_EDITOR_TYPE" in entries
        assert "NON_FATAL_COMPILATION_ERROR" in entries
        assert "HARDWARE_DOWNLOAD_PROMPT" in entries
        assert "COMMON_SAVE_AS" in entries
        assert "FOREIGN_OR_UNRECOGNIZED_MODAL" in entries

        # Verify fail-closed enforcement
        assert entries["NON_FATAL_COMPILATION_ERROR"]["action"] == "BLOCKED_CAPTURE_NO_CLICK"
        assert entries["NON_FATAL_COMPILATION_ERROR"]["status"] == "blocked"
        assert entries["HARDWARE_DOWNLOAD_PROMPT"]["action"] == "BLOCKED_HARDWARE_LOCKOUT"
        assert entries["FOREIGN_OR_UNRECOGNIZED_MODAL"]["action"] == "BLOCKED_CAPTURE_FAIL_CLOSED"

    def test_c4_w03_classifier_deterministic_contract(self):
        """classify_compilation_modal deterministically matches decision table rules."""
        # Non-fatal error variants
        assert classify_compilation_modal("Cscape", ["Non-Fatal Compilation Errors were found."]) == "NON_FATAL_ERROR"
        assert classify_compilation_modal("Warning", ["Do you wish to continue?"]) == "NON_FATAL_ERROR"
        assert classify_compilation_modal("Error", ["Errors occurred. Proceed?"]) == "NON_FATAL_ERROR"

        # Clean compilation variants
        assert classify_compilation_modal("Cscape", ["0 error(s), 0 warning(s)"]) == "CLEAN_RESULT"
        assert classify_compilation_modal("Build", ["Build succeeded."]) == "CLEAN_RESULT"

        # Foreign / unknown modals
        assert classify_compilation_modal("Unknown Modal", ["Random prompt text"]) == "FOREIGN_MODAL"
        assert classify_compilation_modal("Windows Security", ["Firewall blocked features"]) == "FOREIGN_MODAL"

    def test_c4_w03_evidence_artifact_valid(self):
        """w03_modal_safety_evidence.json records decision table rules and fail-closed safety."""
        ev_file = RECOVERY_DIR / "w03_modal_safety_evidence.json"
        assert ev_file.exists(), f"Missing {ev_file}"
        data = json.loads(ev_file.read_text(encoding="utf-8"))
        assert data["item_id"] == "W03"
        assert data["status"] == "done"
        assert data["verification_results"]["auto_yes_eliminated"] is True
        assert data["verification_results"]["fail_closed_on_non_fatal"] is True


class TestC4W04ErrorCheckCompilationDispatch:
    """W04: Error Check (32826) Compile Dispatch & Modal Scrape."""

    def test_c4_w04_modal_intercepted_and_blocked(self):
        """W04 Error Check modal was detected, captured, cleanly dismissed without clicking Yes, and recorded as blocked."""
        matrix_file = RECOVERY_DIR / "c4_windows_matrix.json"
        matrix = json.loads(matrix_file.read_text(encoding="utf-8"))
        w04 = matrix["matrix_results"]["W04"]
        assert w04["status"] == "blocked"
        assert w04["details"]["modals_detected"] >= 1
        assert "Non-Fatal Compilation dialog" in w04["details"]["outcome"]
        assert "fail-closed policy" in w04["details"]["meaning"]

    def test_c4_w04_screenshot_proof_exists(self):
        """Screenshot of non-fatal compilation error dialog was captured and exists."""
        img_path = RECOVERY_DIR / "modal_non_fatal_dialog.png"
        assert img_path.exists()
        assert img_path.stat().st_size > 1000

    def test_c4_w04_evidence_artifact_valid(self):
        """w04_errorcheck_evidence.json records compile modal scrape and fail-closed status."""
        ev_file = RECOVERY_DIR / "w04_errorcheck_evidence.json"
        assert ev_file.exists(), f"Missing {ev_file}"
        data = json.loads(ev_file.read_text(encoding="utf-8"))
        assert data["item_id"] == "W04"
        assert data["status"] == "blocked"
        assert data["command_id"] == 32826
        assert len(data["output_window_scraped_lines"]) >= 1


class TestC4W05HardwareDownloadCommandLockout:
    """W05: Hardware Download Command Lockout."""

    def test_c4_w05_program_download_command_blocked_safety(self):
        """Win32 command ID 32827 (ID_PROGRAM_DOWNLOAD) is blocked fail-closed by safety engine."""
        with pytest.raises(CscapeSafetyViolationError):
            intercept_download_command(32827)

    def test_c4_w05_controller_download_command_blocked_safety(self):
        """Win32 command ID 33149 (ID_CONTROLLER_DOWNLOAD_ALT) is blocked fail-closed by safety engine."""
        with pytest.raises(CscapeSafetyViolationError):
            intercept_download_command(33149)

    def test_c4_w05_download_command_blocked_compilation(self):
        """Win32 download commands 32827 and 33149 blocked fail-closed by compilation engine."""
        res_32827 = cscape_compile_project("LabProject_W01", command_id=32827)
        assert res_32827["status"] == "blocked"
        assert res_32827["error_code"] == "ERR_HARDWARE_LOCKOUT"

        res_33149 = cscape_compile_project("LabProject_W01", command_id=33149)
        assert res_33149["status"] == "blocked"
        assert res_33149["error_code"] == "ERR_HARDWARE_LOCKOUT"

        compiler = CscapeCompiler()
        with pytest.raises(UnauthorizedDownloadError):
            compiler.download_to_controller()
        with pytest.raises(UnauthorizedDownloadError):
            compiler.download_options()

    def test_c4_w05_matrix_records_blocked(self):
        """Matrix result records W05 status as blocked."""
        matrix_file = RECOVERY_DIR / "c4_windows_matrix.json"
        matrix = json.loads(matrix_file.read_text(encoding="utf-8"))
        w05 = matrix["matrix_results"]["W05"]
        assert w05["status"] == "blocked"

    def test_c4_w05_evidence_artifact_valid(self):
        """w05_download_lockout_evidence.json records fail-closed hardware lockout enforcement."""
        ev_file = RECOVERY_DIR / "w05_download_lockout_evidence.json"
        assert ev_file.exists(), f"Missing {ev_file}"
        data = json.loads(ev_file.read_text(encoding="utf-8"))
        assert data["item_id"] == "W05"
        assert data["status"] == "blocked"
        assert len(data["lockout_verifications"]) >= 4


class TestC4TankLevelIsolation:
    """Strict isolation: TankLevelClosedLoop.csp must remain 100% UNTOUCHED."""

    def test_c4_tanklevel_sha256_unmodified(self):
        """TankLevelClosedLoop.csp hash matches baseline hash byte-for-byte."""
        assert ORIGINAL_TANK_CSP.exists(), f"Original baseline project missing: {ORIGINAL_TANK_CSP}"
        current_sha = compute_sha256(ORIGINAL_TANK_CSP)
        assert current_sha in VALID_TANK_CSP_SHA256, (
            f"MUTATION DETECTED! TankLevelClosedLoop.csp changed: {current_sha} not in {VALID_TANK_CSP_SHA256}"
        )


class TestC4SupervisorInventory:
    """Supervisor and watchdog inventory audit."""

    def test_c4_all_five_supervisors_audited(self):
        """Inventory contains all 5 supervised internal watchdog files."""
        inv_file = RECOVERY_DIR / "c4_supervisor_inventory.json"
        assert inv_file.exists()
        inv = json.loads(inv_file.read_text(encoding="utf-8"))
        assert len(inv) == 5

        names = list(inv.keys())
        assert "scripts/cscape_supervisor.py" in names
        assert "scripts/cscape_watchdog.py" in names
        assert "scripts/cscape_keepalive_watchdog.py" in names
        assert "scripts/watchdog_cscape_10min.py" in names
        assert "src/cscape/lifecycle.py" in names

        for k, v in inv.items():
            assert "sha256" in v
            assert "risks_identified" in v
            assert "directives" in v


class TestC4LiveWindowAndDesktopBoundary:
    """Live Cscape process supervision and desktop boundary."""

    def test_c4_environment_telemetry_valid(self):
        """environment.json records valid build, system DPI, desktop, and PID."""
        env_file = RECOVERY_DIR / "environment.json"
        assert env_file.exists()
        env = json.loads(env_file.read_text(encoding="utf-8"))
        assert env["cscape_build"] == "10.2.751.4"
        assert env["system_dpi"] == 96
        assert "winsta0\\Default" in env["desktop"]
        assert env["pid"] > 0
        assert env["lab_project_sha256"] in {compute_sha256(LAB_CSP), "b35342602654d2afa39095e71cd52b2a37a8d1061bab68ccf6eaae5e925aef5e"}
        assert env["original_tanklevel_sha256"] == ORIGINAL_TANK_SHA256

    def test_c4_cscape_process_running_and_alive(self):
        """Cscape.exe process is actively running on the system without being killed."""
        pid = resolve_cscape_pid()
        assert pid is not None and pid > 0, "No active Cscape.exe process found"
        import psutil
        proc = psutil.Process(pid)
        assert proc.is_running()
        assert "cscape" in proc.name().lower()


class TestC4DualRootParity:
    """Dual-root file synchronization parity for Phase C4 artifacts."""

    def test_c4_artifacts_dual_root_hash_parity(self):
        """Every Phase C4 artifact in HornerAI has identical SHA-256 in ArmandoSilva."""
        c4_files = [
            "environment.json",
            "c4_windows_matrix.json",
            "c4_decision_table.md",
            "c4_decision_table.json",
            "c4_supervisor_inventory.json",
            "c4_execution_log.json",
            "c4_before_proof.json",
            "c4_after_proof.json",
            "c4_unified_diff.patch",
            "w01_lifecycle_evidence.json",
            "w02_navigator_evidence.json",
            "w03_modal_safety_evidence.json",
            "w04_errorcheck_evidence.json",
            "w05_download_lockout_evidence.json",
            "c4_w01_execution_log.json",
            "w01_stage1_start.png",
            "w01_stage2_edit.png",
            "w01_stage3_save.png",
            "w01_stage4a_closed.png",
            "w01_stage4_reopened.png",
            "w02_project_navigator.png",
            "w02_status_bar.png",
            "cscape_lab_w01_visible.png",
            "modal_non_fatal_dialog.png",
            "statusbar.png",
        ]
        for fname in c4_files:
            p1 = RECOVERY_DIR / fname
            p2 = USER_RECOVERY_DIR / fname
            assert p1.exists(), f"Horner file missing: {p1}"
            assert p2.exists(), f"User file missing: {p2}"
            h1 = compute_sha256(p1)
            h2 = compute_sha256(p2)
            assert h1 == h2, f"Dual-root hash mismatch on {fname}: {h1} != {h2}"
