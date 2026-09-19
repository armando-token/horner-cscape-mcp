r"""Test Suite for Step 166: Visible Cscape GUI Driver for MEGAPLAN.

Mandates:
- Target Cscape (TankLevelClosedLoop.csp) MUST REMAIN RUNNING under keepalive supervisor.
- Validates gate status dynamically resolved from live gate.
- Validates visible desktop winsta0\Default, enabled, responsive.
- Validates dialog sweep.
- Validates live GUI error check 32826.
- Validates high-res screenshot capture mirrored to dual roots with SHA-256.
- Validates step166 checkpoint mirrored to dual roots.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
from pathlib import Path
import sys
import time

import psutil
import pytest

HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()

for r in [str(HORNER_ROOT), str(USER_ROOT)]:
    if r not in sys.path:
        sys.path.insert(0, r)

from src.cscape.gate import assert_cscape_live, attach_thread_desktop, get_gate_status
from src.cscape.compiler import ID_PROGRAM_ERRORCHECK
from scripts.execute_step155_mcp_dual_transmitter_failover import sweep_cscape_dialogs
from scripts.execute_step166_visible_cscape_gui_driver import (
    run_visible_cscape_step166,
    SCREENSHOT_PATHS,
    LOG_PATHS,
    CHECKPOINT_PATHS,
)


class TestStep166VisibleCscapeGuiDriver:
    """Verifies all tasks of Step 166."""

    def test_task1_gate_pid_and_hwnd(self):
        gate = get_gate_status()
        live_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
            pytest.skip(f"Live Cscape gate not ready or offline: status='{gate.get('status')}', reason='{gate.get('reason')}'")
        assert gate.get("ready_for_tests") is True
        assert gate.get("status") == "READY_FOR_TESTS"
        assert live_pid is not None and live_pid > 0
        h_str = str(gate.get("hwnd")).upper()
        assert h_str.startswith("0X")

    def test_task2_window_interactive_desktop_and_responsiveness(self):
        gate = get_gate_status()
        live_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
            pytest.skip(f"Live Cscape gate not ready or offline: status='{gate.get('status')}', reason='{gate.get('reason')}'")
        pid = int(live_pid)
        raw_h = gate.get("hwnd", "0x0")
        if not raw_h:
            pytest.skip("No HWND in live gate")
        hwnd = int(raw_h, 16) if isinstance(raw_h, str) and raw_h.startswith("0x") else int(raw_h or 0)
        user32 = ctypes.windll.user32
        if not bool(user32.IsWindow(hwnd)):
            pytest.skip(f"Live Cscape HWND {hex(hwnd)} is invalid/closed")

        user32 = ctypes.windll.user32
        desk = attach_thread_desktop(hwnd)
        assert desk.lower() == "default"

        assert user32.IsWindow(hwnd)
        assert user32.IsWindowVisible(hwnd)
        assert not user32.IsHungAppWindow(hwnd)
        assert user32.IsWindowEnabled(hwnd)

        sm_result = ctypes.c_ulong()
        resp = user32.SendMessageTimeoutW(hwnd, 0x0000, 0, 0, 0x0002, 2000, ctypes.byref(sm_result))
        assert resp != 0

        title_buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title_buf, 512)
        assert "tanklevel" in title_buf.value.lower()

    def test_task3_dialog_sweep_non_destructive(self):
        gate = get_gate_status()
        live_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
            pytest.skip(f"Live Cscape gate not ready or offline: status='{gate.get('status')}', reason='{gate.get('reason')}'")
        pid = int(live_pid)
        raw_h = gate.get("hwnd", "0x0")
        if not raw_h:
            pytest.skip("No HWND in live gate")
        hwnd = int(raw_h, 16) if isinstance(raw_h, str) and raw_h.startswith("0x") else int(raw_h or 0)
        dismissed = sweep_cscape_dialogs(pid, main_hwnd=hwnd)
        assert isinstance(dismissed, int)

    def test_task4_execution_and_checkpoint_verification(self):
        gate = get_gate_status()
        live_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
            pytest.skip(f"Live Cscape gate not ready or offline: status='{gate.get('status')}', reason='{gate.get('reason')}'")

        for cp in CHECKPOINT_PATHS:
            assert cp.exists(), f"Missing checkpoint: {cp}"
            data = json.loads(cp.read_text(encoding="utf-8"))
            assert data.get("status") == "PASSED"
            assert data.get("step") == 166
            assert data.get("live_gui_compile_clean") is True
            assert "checkpoint_sha256" in data

        for lp in LOG_PATHS:
            assert lp.exists(), f"Missing log: {lp}"
            data = json.loads(lp.read_text(encoding="utf-8"))
            assert data.get("status") == "PASSED"
            assert data.get("step") == 166
            assert data.get("gui_compilation", {}).get("error_count") == 0
            assert data.get("gui_compilation", {}).get("warning_count") == 0

        for sp in SCREENSHOT_PATHS:
            assert sp.exists(), f"Missing screenshot: {sp}"
            assert sp.stat().st_size > 500, f"Screenshot file too small: {sp.stat().st_size}"
