#!/usr/bin/env python3
r"""Test Suite for Step 173: Live FastMCP Generator AVR & Excitation Audit.

MANDATES:
- Pure software simulation only. Zero PLC. Zero Straton.
- DO NOT touch the live Cscape GUI (HWND/WM_COMMAND).
- Live JSON-RPC 2.0 stdio subprocess client against scripts/run_mcp_server.py.
- Validates Scenario A: AVR Voltage Regulation & Reactive Power Steady-State.
- Validates Scenario B: Grid Voltage Sag & AVR Boost / Over-Excitation Limiter (OEL).
- Validates Scenario C: Grid High Voltage & Under-Excitation Limiter (UEL) Clamp.
- Validates Scenario D: Volts-per-Hertz (V/Hz) Overfluxing Protection Trip.
- Validates Scenario E: Rotor Field Loss / Loss of Excitation (40 Relay) Trip.
- Validates hardware download lockout fail-closed rejection.
- Validates Step 173 checkpoints and audit logs across dual roots.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List

import psutil
import pytest

HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()

for r in [str(HORNER_ROOT), str(USER_ROOT)]:
    if r not in sys.path:
        sys.path.insert(0, r)

from src.cscape.gate import get_gate_status, assert_cscape_live, CscapeLivenessGateError
from scripts.execute_step173_mcp_generator_avr_excitation import (
    StdioRpcFastClient,
    PY_EXE,
    SERVER_PY,
    run_step173_mcp_simulation,
    CHECKPOINT_PATHS,
    LOG_PATHS,
)


class TestStep173GateAndEnvironment:
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

    def test_cscape_process_running(self):
        gate = get_gate_status()
        live_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
            pytest.skip(f"Live Cscape gate not ready or offline: status='{gate.get('status')}', reason='{gate.get('reason')}'")
        pid = int(live_pid)
        assert psutil.pid_exists(pid), f"PID {pid} not found running"
        p = psutil.Process(pid)
        assert "cscape" in p.name().lower()


class TestStep173GeneratorAvrControl:
    """Runs the pure-software Step 173 simulation and verifies checkpoints."""

    def test_full_step173_generator_scenarios_and_lockout(self):
        gate = get_gate_status()
        live_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
            pytest.skip(f"Live Cscape gate not ready or offline: status='{gate.get('status')}', reason='{gate.get('reason')}'")

        report = asyncio.run(run_step173_mcp_simulation())
        assert report.get("status") == "PASSED"
        assert report.get("scenarios", {}).get("scenario_A_avr_steady_state") == "PASSED"
        assert report.get("scenarios", {}).get("scenario_B_over_excitation_limiter") == "PASSED"
        assert report.get("scenarios", {}).get("scenario_C_under_excitation_limiter") == "PASSED"
        assert report.get("scenarios", {}).get("scenario_D_volts_per_hertz_overfluxing") == "PASSED"
        assert report.get("scenarios", {}).get("scenario_E_loss_of_field_40_trip") == "PASSED"
        assert report.get("scenarios", {}).get("hardware_download_lockout") == "PASSED"

        # Verify dual-root files
        for cp in CHECKPOINT_PATHS:
            assert cp.exists(), f"Missing checkpoint: {cp}"
            data = json.loads(cp.read_text(encoding="utf-8"))
            assert data.get("status") == "PASSED"
            assert data.get("step") == 173
            assert data.get("scenarios_passed") == 6
            assert data.get("hardware_lockout_verified") is True

        for lp in LOG_PATHS:
            assert lp.exists(), f"Missing log: {lp}"
            data = json.loads(lp.read_text(encoding="utf-8"))
            assert data.get("status") == "PASSED"
            assert data.get("step") == 173
