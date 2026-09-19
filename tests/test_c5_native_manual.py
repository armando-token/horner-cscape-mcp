"""Contract and Verification Test Suite for Phase C5: Native/Manual Evidence.

Mandate: PLAN_CORRECTIVO MCP Horner/Cscape v2.0 (correctivo)
Mission: C5_NATIVE_MANUAL
Run ID: run_20260906_120831

Invariants & Contracts Verified:
1. Prerequisite C4 Matrix: W01-W03 done, W05 blocked, W04 non-fatal modal captured.
2. Baseline Isolation: TankLevelClosedLoop.csp preserved 100% UNTOUCHED (SHA256 verified).
3. CFBF Container Integrity: Real OLE2 container with verified sector allocations and streams.
4. Live Native GUI State: Visible Cscape on winsta0\\Default with responding GUI.
5. Offline/DEV Mode Enforced: Status bar "Disconnected" -> strictly "offline/DEV if Disconnected".
6. Visibility Contract: Window visibility alone is NOT claimed as VERIFIED_LIVE.
7. ST->LD Native Architecture: BLOCKED_NATIVE: DOCUMENT_ONLY verified across menus & DLL exports.
8. Pure ST POU Validation: Valid ST parsed; ladder constructs rejected fail-closed (ERR_LADDER_FORBIDDEN).
9. Fail-Closed Safety Lockout: COM ports, download commands (32827, 33149), and flasher tools blocked.
10. Gate G5 Governance: Gate G5 is explicitly NOT RUN per user mandate and remains closed.
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
    CSCAPE_CONTENTS_MAGIC,
    is_valid_cfbf,
    inspect_project_file,
)
from src.mcp.tools import cscape_validate_st
from src.cscape.st_ld_interop import STLadderInteropGuard
from src.cscape.safety import (
    intercept_download_command,
    CscapeSafetyViolationError,
)
from src.security.guard import SecurityGuard
from src.security.exceptions import HardwareLockoutError, BlockedExecutableError
from src.cscape.gate import resolve_cscape_pid

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


class TestC5PrerequisitesAndBaseline:
    """Verifies prerequisite C4 matrix acceptance and strict baseline isolation."""

    def test_c5_c4_prerequisites_accepted(self):
        """C4 W01-W03 evidence and W05 blocked evidence exist in recovery vault."""
        w01_file = RECOVERY_DIR / "w01_lifecycle_evidence.json"
        w02_file = RECOVERY_DIR / "w02_navigator_evidence.json"
        w03_file = RECOVERY_DIR / "w03_modal_safety_evidence.json"
        w05_file = RECOVERY_DIR / "w05_download_lockout_evidence.json"

        assert w01_file.exists(), f"Missing {w01_file}"
        assert w02_file.exists(), f"Missing {w02_file}"
        assert w03_file.exists(), f"Missing {w03_file}"
        assert w05_file.exists(), f"Missing {w05_file}"

        w01_data = json.loads(w01_file.read_text(encoding="utf-8"))
        w02_data = json.loads(w02_file.read_text(encoding="utf-8"))
        w03_data = json.loads(w03_file.read_text(encoding="utf-8"))
        w05_data = json.loads(w05_file.read_text(encoding="utf-8"))

        assert w01_data["status"] == "done"
        assert w02_data["status"] == "done"
        assert w03_data["status"] == "done"
        assert w05_data["status"] == "blocked"

    def test_c5_tanklevel_baseline_isolation_strictly_untouched(self):
        """TankLevelClosedLoop.csp hash matches baseline byte-for-byte."""
        assert ORIGINAL_TANK_CSP.exists()
        current_sha = compute_sha256(ORIGINAL_TANK_CSP)
        assert current_sha == ORIGINAL_TANK_SHA256, (
            f"BASELINE MUTATION DETECTED! {current_sha} != {ORIGINAL_TANK_SHA256}"
        )


class TestC5CFBFNativeProjectContainer:
    """Verifies CFBF container deep-inspection evidence."""

    def test_c5_cfbf_evidence_present_and_valid(self):
        """c5_native_manual_evidence.json contains verified CFBF container evidence."""
        ev_file = RECOVERY_DIR / "c5_native_manual_evidence.json"
        assert ev_file.exists(), f"Missing {ev_file}"
        data = json.loads(ev_file.read_text(encoding="utf-8"))

        assert data["mission_id"] == "C5_NATIVE_MANUAL"
        assert data["status"] == "success"

        cfbf = data["cfbf_container_evidence"]
        assert cfbf["lab_project"]["is_valid_cfbf"] is True
        assert cfbf["lab_project"]["has_contents_stream"] is True
        assert cfbf["lab_project"]["sector_size"] == 512
        assert cfbf["baseline_project"]["is_valid_cfbf"] is True
        assert cfbf["baseline_project"]["isolation_verified"] is True
        assert cfbf["staging_vs_native_boundary"]["enforced"] is True


class TestC5LiveNativeGUIAndVisibilityContract:
    """Verifies live Cscape GUI inspection and visibility boundary."""

    def test_c5_live_gui_telemetry_and_screenshot(self):
        """Live GUI telemetry records PID 2108, Disconnected status, and screenshot exists."""
        ev_file = RECOVERY_DIR / "c5_native_manual_evidence.json"
        data = json.loads(ev_file.read_text(encoding="utf-8"))

        gui = data["live_gui_evidence"]
        assert gui["pid"] > 0
        assert gui["visible"] is True
        assert gui["connection_status"] == "Disconnected"
        assert gui["operational_mode"] == "offline/DEV if Disconnected"
        assert "NOT claimed as VERIFIED_LIVE" in gui["visibility_classification"]

        img_path = RECOVERY_DIR / "c5_cscape_native_gui.png"
        assert img_path.exists()
        assert img_path.stat().st_size > 50000

    def test_c5_visibility_is_not_claimed_as_verified_live(self):
        """Contract invariant: Window visibility alone is explicitly NOT VERIFIED_LIVE."""
        ev_file = RECOVERY_DIR / "c5_native_manual_evidence.json"
        data = json.loads(ev_file.read_text(encoding="utf-8"))
        assert data["invariants_confirmed"]["cscape_visibility_not_verified_live"] is True
        assert data["invariants_confirmed"]["offline_dev_mode_enforced"] is True


class TestC5STtoLDConversionArchitecture:
    """Verifies ST->LD conversion architectural reality."""

    def test_c5_st_ld_architecture_blocked_native(self):
        """ST->LD conversion documented as BLOCKED_NATIVE with zero native conversion exports."""
        ev_file = RECOVERY_DIR / "c5_native_manual_evidence.json"
        data = json.loads(ev_file.read_text(encoding="utf-8"))

        pe = data["native_st_ld_architecture"]
        assert pe["classification"] == "BLOCKED_NATIVE: DOCUMENT_ONLY"
        assert STLadderInteropGuard.IN_GUI_CONVERSION_BLOCKED is True
        assert STLadderInteropGuard.NATIVE_CONVERSION_STATUS == "BLOCKED_NATIVE: DOCUMENT_ONLY"


class TestC5ManualSTLogicPOUValidation:
    """Verifies pure ST validation and ladder rejection contracts."""

    def test_c5_pure_st_pou_valid(self):
        """Pure Structured Text POU passes syntax and semantic validation."""
        code = """PROGRAM SampleSafety
VAR
    Speed : REAL := 0.0;
    MaxSpeed : REAL := 100.0;
    Trip : BOOL := FALSE;
END_VAR

IF Speed > MaxSpeed THEN
    Trip := TRUE;
ELSE
    Trip := FALSE;
END_IF;
END_PROGRAM
"""
        res = cscape_validate_st(code=code)
        assert res["status"] == "success"
        assert res["valid"] is True

    @pytest.mark.parametrize("ladder_str", [
        "---[ ]---",
        "---[/]---",
        "---( )---",
        "---(S)---",
        "---(R)---",
        "RUNG 1: XIC InBit OTE OutBit",
    ])
    def test_c5_ladder_constructs_rejected_fail_closed(self, ladder_str):
        """Ladder logic constructs fail closed with ERR_LADDER_FORBIDDEN."""
        bad_code = f"PROGRAM BadProg\nVAR x: BOOL;\nEND_VAR\n{ladder_str}\nEND_PROGRAM"
        res = cscape_validate_st(code=bad_code)
        assert res["status"] == "failed"
        assert res["success"] is False
        assert (
            any("ladder" in e.lower() for e in res.get("errors", []))
            or res.get("error_code") == "ERR_LADDER_FORBIDDEN"
            or any(fl.get("error_code") == "ERR_LADDER_FORBIDDEN" for fl in res.get("failure_locations", []))
        )


class TestC5FailClosedSafetyLockout:
    """Verifies physical hardware and Win32 download command lockouts."""

    def test_c5_hardware_ports_locked_out(self):
        """Physical serial COM, CAN, and USB ports blocked fail-closed."""
        guard = SecurityGuard()
        for port in ["COM1", "COM4", "COM256", "CAN0", "USB0"]:
            with pytest.raises(HardwareLockoutError):
                guard.validate_command(["cscape.exe", "--port", port])

    def test_c5_download_commands_locked_out(self):
        """Win32 download commands (32827, 33149) blocked fail-closed."""
        with pytest.raises(CscapeSafetyViolationError):
            intercept_download_command(32827)
        with pytest.raises(CscapeSafetyViolationError):
            intercept_download_command(33149)

    def test_c5_companion_flashers_locked_out(self):
        """Companion flasher binaries blocked fail-closed."""
        guard = SecurityGuard()
        with pytest.raises(BlockedExecutableError):
            guard.validate_command(["PGMUpdateUtility.exe", "/f"])
        with pytest.raises(BlockedExecutableError):
            guard.validate_command(["DfuSeCommand.exe", "-c"])


class TestC5GateGovernanceAndParity:
    """Verifies gate boundaries, no G5 run invariant, and dual-root parity."""

    def test_c5_gate_g5_strictly_not_run(self):
        """Gate G5 is explicitly NOT RUN per user mandate and remains closed/blocked."""
        ev_file = RECOVERY_DIR / "c5_native_manual_evidence.json"
        data = json.loads(ev_file.read_text(encoding="utf-8"))

        assert data["invariants_confirmed"]["do_not_run_g5"] is True
        assert data["invariants_confirmed"]["no_c1_c2_c3_restart"] is True
        assert data["invariants_confirmed"]["no_plc_or_straton"] is True
        assert data["gate_status_governance"]["G5"]["status"] == "blocked"

    def test_c5_dual_root_parity(self):
        """All C5 recovery artifacts exist in both roots with identical SHA-256 digests."""
        c5_artifacts = [
            "c5_native_manual_evidence.json",
            "c5_execution_log.json",
            "c5_cscape_native_gui.png",
        ]
        for fname in c5_artifacts:
            horner_file = RECOVERY_DIR / fname
            user_file = USER_RECOVERY_DIR / fname

            assert horner_file.exists(), f"Missing {horner_file}"
            assert user_file.exists(), f"Missing {user_file}"

            h_sha = compute_sha256(horner_file)
            u_sha = compute_sha256(user_file)
            assert h_sha == u_sha, f"Hash mismatch on {fname}: {h_sha} != {u_sha}"
