#!/usr/bin/env python3
r"""Test Suite for Step 172: Live FastMCP Turbine EHC Overspeed & Grid Sync Audit.

MANDATES:
- Pure software simulation only. Zero PLC. Zero Straton.
- DO NOT touch the live Cscape GUI (HWND/WM_COMMAND).
- Live JSON-RPC 2.0 stdio subprocess client against scripts/run_mcp_server.py.
- Validates Scenario A: Rated Speed Equilibrium & Grid Synchronization Window.
- Validates Scenario B: Full Load Generation Steady-State.
- Validates Scenario C: Sudden Grid Load Rejection & 110% Overspeed Emergency Trip.
- Validates Scenario D: Generator Anti-Motoring / Reverse Power Trip Protection.
- Validates Scenario E: Post-Trip Cooldown & Automatic Turning Gear Engagement.
- Validates hardware download lockout fail-closed rejection.
- Validates Step 172 checkpoints and audit logs across dual roots.
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
from scripts.execute_step172_mcp_turbine_ehc_grid_sync import (
    StdioRpcFastClient,
    PY_EXE,
    SERVER_PY,
    run_step172_mcp_simulation,
    CHECKPOINT_PATHS,
    LOG_PATHS,
)


class TestStep172GateAndEnvironment:
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


class TestStep172TurbineControl:
    """Runs the pure-software Step 172 simulation and verifies checkpoints."""

    def test_full_step172_turbine_scenarios_and_lockout(self):
        gate = get_gate_status()
        live_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
            pytest.skip(f"Live Cscape gate not ready or offline: status='{gate.get('status')}', reason='{gate.get('reason')}'")

        report = asyncio.run(run_step172_mcp_simulation())
        assert report.get("status") == "PASSED"
        assert report.get("scenarios", {}).get("scenario_A_grid_sync_equilibrium") == "PASSED"
        assert report.get("scenarios", {}).get("scenario_B_full_load_generation") == "PASSED"
        assert report.get("scenarios", {}).get("scenario_C_overspeed_trip_latched") == "PASSED"
        assert report.get("scenarios", {}).get("scenario_D_reverse_power_anti_motoring") == "PASSED"
        assert report.get("scenarios", {}).get("scenario_E_turning_gear_cooldown") == "PASSED"
        assert report.get("scenarios", {}).get("hardware_download_lockout") == "PASSED"

        # Verify dual-root files
        for cp in CHECKPOINT_PATHS:
            assert cp.exists(), f"Missing checkpoint: {cp}"
            data = json.loads(cp.read_text(encoding="utf-8"))
            assert data.get("status") == "PASSED"
            assert data.get("step") == 172
            assert data.get("scenarios_passed") == 6
            assert data.get("hardware_lockout_verified") is True

        for lp in LOG_PATHS:
            assert lp.exists(), f"Missing log: {lp}"
            data = json.loads(lp.read_text(encoding="utf-8"))
            assert data.get("status") == "PASSED"
            assert data.get("step") == 172
