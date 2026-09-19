r"""Test Suite for MEGAPLAN Gate G3 and Gate G4 Evidence Verification.

Mandates:
1. Live Cscape (TankLevelClosedLoop.csp) MUST REMAIN VISIBLE on interactive desktop (winsta0\Default). Fail-closed if hidden.
2. Offline audits must be classified as offline/DEV (TESTED_MOCK), never VERIFIED_LIVE.
3. Strict zero PLC download (32827, 33149) and zero Straton legacy dependencies.
4. Gate G2, Gate G3, and Gate G4 checkpoints and logs verified across dual roots with strict 4-state contract.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict

import psutil
import pytest

HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()

for r in [str(HORNER_ROOT), str(USER_ROOT)]:
    if r not in sys.path:
        sys.path.insert(0, r)

from src.cscape.gate import assert_cscape_live, attach_thread_desktop, get_gate_status
from src.cscape.compiler import ID_PROGRAM_ERRORCHECK, ID_CONTROLLER_DOWNLOAD, ID_PROGRAM_DOWNLOADOPTIONS
from src.cscape.safety import ID_CONTROLLER_DOWNLOAD_ALT, BLOCKED_DOWNLOAD_COMMAND_IDS
from src.security.guard import SafetyGuard
from src.security.exceptions import HardwareLockoutError, UnauthorizedDownloadError


class TestGateG2VisibleGUIVerification:
    """Verifies Gate G2 evidence on interactive desktop."""

    def test_g2_live_cscape_visible_and_responsive(self):
        gate = assert_cscape_live()
        assert gate["ready_for_tests"] is True
        assert gate["status"] == "READY_FOR_TESTS"

        pid = int(gate["pid"])
        assert psutil.pid_exists(pid)
        proc = psutil.Process(pid)
        assert "cscape" in proc.name().lower()

        raw_h = gate["hwnd"]
        hwnd = int(raw_h, 16) if isinstance(raw_h, str) and raw_h.startswith("0x") else int(raw_h)
        desk = attach_thread_desktop(hwnd)
        assert desk.lower() == "default"

        user32 = ctypes.windll.user32
        assert user32.IsWindow(hwnd), f"HWND {hex(hwnd)} is not a valid window"
        assert user32.IsWindowVisible(hwnd), f"HWND {hex(hwnd)} is hidden! Must fail-closed."
        assert not user32.IsHungAppWindow(hwnd), f"HWND {hex(hwnd)} is hung!"
        assert user32.IsWindowEnabled(hwnd), f"HWND {hex(hwnd)} is disabled!"

        title_buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title_buf, 512)
        assert "tanklevel" in title_buf.value.lower()

    def test_g2_checkpoint_dual_root_parity(self):
        cp_h = HORNER_ROOT / "artifacts" / "checkpoints" / "megaplan_g2_visible_gui_checkpoint.json"
        cp_u = USER_ROOT / "artifacts" / "checkpoints" / "megaplan_g2_visible_gui_checkpoint.json"

        assert cp_h.exists(), f"Missing Horner G2 checkpoint: {cp_h}"
        assert cp_u.exists(), f"Missing User G2 checkpoint: {cp_u}"
        assert cp_h.read_bytes() == cp_u.read_bytes(), "G2 checkpoint byte mismatch across dual roots!"

        data = json.loads(cp_h.read_text(encoding="utf-8"))
        assert data["gate"] == "G2"
        assert data["status"] == "success"
        assert data["dual_root_parity"] is True
        assert data["live_cscape"]["is_window_visible"] is True


class TestGateG3LiveCompilePipelineVerification:
    """Verifies Gate G3 live GUI compilation & FastMCP pipeline evidence."""

    def test_g3_download_commands_fail_closed_lockout(self):
        assert ID_PROGRAM_ERRORCHECK == 32826
        assert ID_CONTROLLER_DOWNLOAD == 32827
        assert ID_PROGRAM_DOWNLOADOPTIONS == 33149
        assert 32827 in BLOCKED_DOWNLOAD_COMMAND_IDS
        assert 33149 in BLOCKED_DOWNLOAD_COMMAND_IDS

        guard = SafetyGuard()
        with pytest.raises(UnauthorizedDownloadError):
            guard.validate_download("/download")

    def test_g3_screenshot_proof_dual_root_parity(self):
        sp_h = HORNER_ROOT / "artifacts" / "screenshots" / "live_cscape_tank_level_compile_clean_proof.png"
        sp_u = USER_ROOT / "artifacts" / "screenshots" / "live_cscape_tank_level_compile_clean_proof.png"

        assert sp_h.exists(), f"Missing Horner screenshot: {sp_h}"
        assert sp_u.exists(), f"Missing User screenshot: {sp_u}"
        assert sp_h.stat().st_size >= 10240
        assert sp_h.read_bytes() == sp_u.read_bytes()

        sha_h = hashlib.sha256(sp_h.read_bytes()).hexdigest()
        assert len(sha_h) == 64

    def test_g3_checkpoint_and_log_parity(self):
        cp_h = HORNER_ROOT / "artifacts" / "checkpoints" / "megaplan_g3_live_compile_pipeline_checkpoint.json"
        cp_u = USER_ROOT / "artifacts" / "checkpoints" / "megaplan_g3_live_compile_pipeline_checkpoint.json"

        assert cp_h.exists(), f"Missing Horner G3 checkpoint: {cp_h}"
        assert cp_u.exists(), f"Missing User G3 checkpoint: {cp_u}"
        assert cp_h.read_bytes() == cp_u.read_bytes(), "G3 checkpoint byte mismatch across dual roots!"

        data = json.loads(cp_h.read_text(encoding="utf-8"))
        assert data["gate"] == "G3"
        assert data["status"] == "success"
        assert data["dual_root_parity"] is True
        assert data["compilation_pipeline_verified"]["command_dispatched"].startswith("ID_PROGRAM_ERRORCHECK")
        assert data["compilation_pipeline_verified"]["clean_compile_result"] == "0 errors, 0 warnings"

        # Verify offline classification
        assert "offline/DEV" in data["verification_classification"]["offline_compilation_and_ast"]
        assert "VERIFIED_LIVE" in data["verification_classification"]["live_gui_error_check"]


class TestGateG4ClosedLoopSimulationVerification:
    """Verifies Gate G4 pure software closed-loop plant simulation & concurrency evidence."""

    def test_g4_simulation_offline_classification(self):
        cp_h = HORNER_ROOT / "artifacts" / "checkpoints" / "megaplan_g4_closed_loop_simulation_checkpoint.json"
        cp_u = USER_ROOT / "artifacts" / "checkpoints" / "megaplan_g4_closed_loop_simulation_checkpoint.json"

        assert cp_h.exists(), f"Missing Horner G4 checkpoint: {cp_h}"
        assert cp_u.exists(), f"Missing User G4 checkpoint: {cp_u}"
        assert cp_h.read_bytes() == cp_u.read_bytes(), "G4 checkpoint byte mismatch across dual roots!"

        data = json.loads(cp_h.read_text(encoding="utf-8"))
        assert data["gate"] == "G4"
        assert data["status"] == "success"
        assert data["dual_root_parity"] is True

        # Pure software classification
        assert "offline/DEV" in data["closed_loop_simulation_engine"]["mode"]
        assert "offline/DEV" in data["verification_classification"]["simulation_suites"]
        assert "VERIFIED_LIVE" in data["verification_classification"]["live_gate_inspections"]

        # Straton quarantine
        assert data["straton_quarantine_enforced"]["status"] == "CERTIFIED_ENFORCED"
        assert data["straton_quarantine_enforced"]["straton_tools_in_mcp"] == 0

    def test_g4_audit_log_parity_and_evidence(self):
        log_h = HORNER_ROOT / "artifacts" / "logs" / "megaplan_g4_closed_loop_simulation.json"
        log_u = USER_ROOT / "artifacts" / "logs" / "megaplan_g4_closed_loop_simulation.json"

        assert log_h.exists(), f"Missing Horner G4 audit log: {log_h}"
        assert log_u.exists(), f"Missing User G4 audit log: {log_u}"
        assert log_h.read_bytes() == log_u.read_bytes(), "G4 audit log byte mismatch across dual roots!"

        log_data = json.loads(log_h.read_text(encoding="utf-8"))
        assert log_data["gate"] == "G4"
        assert log_data["status"] == "success"
        assert log_data["simulation_results"]["hh_trip_verified"] is True
        assert log_data["simulation_results"]["ll_dry_run_verified"] is True
        assert log_data["simulation_results"]["hysteresis_deadbands_verified"] is True
        assert log_data["concurrency_results"]["straton_tools_count"] == 0
        assert log_data["concurrency_results"]["cross_contamination_detected"] is False
        assert log_data["verification_taxonomy"]["offline_audits"] == "offline/DEV (TESTED_MOCK)"
        assert log_data["verification_taxonomy"]["live_gui_gate"] == "VERIFIED_LIVE"
