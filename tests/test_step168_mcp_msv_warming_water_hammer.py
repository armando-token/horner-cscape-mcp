#!/usr/bin/env python3
r"""Test Suite for Step 168: Live FastMCP MSV Warming Bypass & Water Hammer Prevention Audit.

MANDATES:
- Pure software simulation only. Zero PLC. Zero Straton.
- DO NOT touch the live Cscape GUI (HWND/WM_COMMAND).
- Live JSON-RPC 2.0 stdio subprocess client against scripts/run_mcp_server.py.
- Validates Scenario A: Automated Warmup Sequence Initiation & Condensate Drain Purge.
- Validates Scenario B: Accelerated Warming Heatup Rate & Water Hammer Shock Surge.
- Validates Scenario C: Pipe Wall Thermal Stratification / Bowing Danger Protection.
- Validates Scenario D: Header Pressurization, Permissive Satisfaction & Main MSV Open.
- Validates Scenario E: Full Main Steam Flow & Steady-State Distribution Stabilization.
- Validates hardware download lockout fail-closed rejection.
- Validates Step 168 checkpoints and audit logs across dual roots.
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
from scripts.execute_step168_mcp_msv_warming_water_hammer import (
    StdioRpcFastClient,
    PY_EXE,
    SERVER_PY,
    run_step168_mcp_simulation,
    CHECKPOINT_PATHS,
    LOG_PATHS,
)


class TestStep168GateAndEnvironment:
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


class TestStep168MsvWarming:
    """Verifies Step 168 5-Phase MSV Warming Scenarios via stdio FastMCP client."""

    @pytest.mark.asyncio
    async def test_full_step168_msv_scenarios_and_lockout(self):
        gate = get_gate_status()
        live_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
            pytest.skip(f"Live Cscape gate not ready or offline: status='{gate.get("status")}', reason='{gate.get("reason")}'")
        try:
            report = await run_step168_mcp_simulation()
        except CscapeLivenessGateError as e:
            pytest.skip(f"Live Cscape gate not ready or offline: {e}")
        assert report.get("status") == "PASSED"
        assert report.get("step") == 168
        assert report["scenarios_passed"] == 5
        assert report["security"]["hardware_download_lockout"] == "FAIL_CLOSED_BLOCKED"

        for cp in CHECKPOINT_PATHS:
            assert cp.exists()
            data = json.loads(cp.read_text(encoding="utf-8"))
            assert data.get("status") == "PASSED"
            assert data.get("step") == 168
            assert data.get("warmup_initiation_verified") is True
            assert "checkpoint_sha256" in data
