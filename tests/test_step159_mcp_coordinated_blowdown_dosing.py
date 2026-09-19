#!/usr/bin/env python3
r"""Test Suite for Step 159: Live FastMCP Coordinated Boiler Continuous Blowdown & Automatic Chemical Inhibitor Dosing Interlock Telemetry Audit.

MANDATES:
- Pure software simulation only. Zero PLC. Zero Straton.
- DO NOT touch the live Cscape GUI (HWND/WM_COMMAND).
- Live JSON-RPC 2.0 stdio subprocess client against scripts/run_mcp_server.py.
- Validates Scenario A: Normal Steady-State Chemical Equilibrium (%R1=50%, TDS %R13=2200 uS/cm, Blowdown %R15=15%, Dosing %R17=25%).
- Validates Scenario B: Feedwater Impurity Surge (%R13=3800 uS/cm -> %M11 trips, %R15=65%, %R17=50%).
- Validates Scenario C: Emergency Bottom Sludge Blowdown Pulse (%Q6=True, %M13=True, Feedwater %R7=65%).
- Validates Scenario D: Chemical Storage Depletion Interlock (%M12 trips, %Q5=False, %R17=0.0%).
- Validates Scenario E: Double-Fault Coordinated Recovery & Multi-Loop Re-Equilibrium.
- Validates hardware download lockout fail-closed rejection.
- Validates Step 159 checkpoints and audit logs across dual roots.
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

# Mandatory dual-root safety
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()

for r in [str(HORNER_ROOT), str(USER_ROOT)]:
    if r not in sys.path:
        sys.path.insert(0, r)

from src.cscape.gate import get_gate_status, assert_cscape_live, CscapeLivenessGateError
from scripts.execute_step159_mcp_coordinated_blowdown_dosing import (
    StdioRpcFastClient,
    PY_EXE,
    SERVER_PY,
    run_step159_mcp_simulation,
    CHECKPOINT_PATHS,
    LOG_PATHS,
)


class TestStep159GateAndEnvironment:
    """Verifies live Cscape environment status via read-only gate inspection (zero GUI interaction)."""

    def test_gate_status_ready_for_tests(self):
        gate = get_gate_status()
        live_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
            pytest.skip(f"Live Cscape gate not ready or offline: status='{gate.get('status')}', reason='{gate.get('reason')}'")
        assert gate.get("ready_for_tests") is True, f"Gate status not ready: {gate}"
        assert gate.get("status") == "READY_FOR_TESTS"
        assert gate.get("pid") > 0
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


class TestStep159BlowdownDosingSimulationScenarios:
    """Verifies Step 159 5-Phase Coordinated Blowdown & Dosing Scenarios via stdio FastMCP client."""

    @pytest.mark.asyncio
    async def test_full_step159_mimo_scenarios_and_lockout(self):
        gate = get_gate_status()
        live_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
            pytest.skip(f"Live Cscape gate not ready or offline: status='{gate.get("status")}', reason='{gate.get("reason")}'")
        try:
            report = await run_step159_mcp_simulation()
        except CscapeLivenessGateError as e:
            pytest.skip(f"Live Cscape gate not ready or offline: {e}")
        assert report.get("status") == "PASSED"
        assert report.get("step") == 159
        assert report["scenarios_passed"] == 5
        assert report["security"]["hardware_download_lockout"] == "FAIL_CLOSED_BLOCKED"

        for cp in CHECKPOINT_PATHS:
            assert cp.exists()
            data = json.loads(cp.read_text(encoding="utf-8"))
            assert data.get("status") == "PASSED"
            assert data.get("step") == 159
            assert data.get("coordinated_blowdown_dosing_verified") is True
            assert "checkpoint_sha256" in data
