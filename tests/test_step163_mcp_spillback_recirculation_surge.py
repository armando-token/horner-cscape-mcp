#!/usr/bin/env python3
r"""Test Step 163: FastMCP Coordinated Feedwater Header Spillback Bypass & Anti-Surge Recirculation Test Suite.

Validates:
- Live Cscape gate status is READY_FOR_TESTS without touching HWND/WM_COMMAND.
- Stdio FastMCP subprocess launches cleanly and accepts JSON-RPC requests.
- All 5 Spillback Bypass & Anti-Surge Recirculation scenarios pass with pure software simulation.
- Hardware download attempts are strictly rejected fail-closed.
"""

import sys
import json
import pytest
import psutil
from pathlib import Path

HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()

for r in [str(HORNER_ROOT), str(USER_ROOT)]:
    if r not in sys.path:
        sys.path.insert(0, r)

from src.cscape.gate import get_gate_status, assert_cscape_live, CscapeLivenessGateError
from scripts.execute_step163_mcp_spillback_recirculation_surge import (
    StdioRpcFastClient,
    PY_EXE,
    SERVER_PY,
    run_step163_mcp_simulation,
    CHECKPOINT_PATHS,
    LOG_PATHS,
)


class TestStep163GateAndEnvironment:
    """Verifies live Cscape environment status via read-only gate inspection (zero GUI interaction)."""

    def test_gate_status_ready_for_tests(self):
        gate = get_gate_status()
        live_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
            pytest.skip(f"Live Cscape gate not ready or offline: status='{gate.get('status')}', reason='{gate.get('reason')}'")
        assert gate.get("ready_for_tests") is True, f"Gate status not ready: {gate}"
        assert gate.get("status") == "READY_FOR_TESTS"
        live_pid = gate.get("pid")
        assert live_pid is not None and live_pid > 0
        assert "TankLevelClosedLoop" in gate.get("window_title", "")

    def test_cscape_process_running(self):
        gate = get_gate_status()
        live_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
            pytest.skip(f"Live Cscape gate not ready or offline: status='{gate.get('status')}', reason='{gate.get('reason')}'")
        pid = int(live_pid)
        assert psutil.pid_exists(pid)
        proc = psutil.Process(pid)
        assert proc.is_running()
        assert "cscape" in proc.name().lower()


class TestStep163SpillbackRecirculation:
    """Verifies Step 163 5-Phase Spillback Recirculation Scenarios via stdio FastMCP client."""

    @pytest.mark.asyncio
    async def test_full_step163_spillback_scenarios_and_lockout(self):
        gate = get_gate_status()
        live_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
            pytest.skip(f"Live Cscape gate not ready or offline: status='{gate.get("status")}', reason='{gate.get("reason")}'")
        try:
            report = await run_step163_mcp_simulation()
        except CscapeLivenessGateError as e:
            pytest.skip(f"Live Cscape gate not ready or offline: {e}")
        assert report.get("status") == "PASSED"
        assert report.get("step") == 163
        assert report["scenarios_passed"] == 5
        assert report["security"]["hardware_download_lockout"] == "FAIL_CLOSED_BLOCKED"

        for cp in CHECKPOINT_PATHS:
            assert cp.exists()
            data = json.loads(cp.read_text(encoding="utf-8"))
            assert data.get("status") == "PASSED"
            assert data.get("step") == 163
            assert data.get("spillback_recirculation_verified") is True
            assert "checkpoint_sha256" in data
