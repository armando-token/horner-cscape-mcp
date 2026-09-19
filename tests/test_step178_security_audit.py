"""Pytest suite for Step 178 Security Lockout Audit.

Validates fail-closed security validation:
1. Hardware download lockout across safety.py and compilation.py (ID 32827 & 33149).
2. Physical serial port lockout (COM1..COM256) and fieldbus/debugger lockout.
3. cscape_download_logic rejection via FastMCP stdio client.
4. Straton quarantine status and zero active .py imports of straton or k5.
5. Offline gate simulation fail-closed assertion raising CscapeLivenessGateError.
6. Verify step178 security audit checkpoint exists and conforms to 4-state contract.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()

for root in [USER_ROOT, HORNER_ROOT]:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from scripts.execute_step178_security_audit import (
    audit_task1_download_lockout,
    audit_task2_mcp_download_tool,
    audit_task3_straton_quarantine,
    audit_task4_offline_gate_simulation,
)


class TestStep178SecurityAudit:
    """Step 178 Security Lockout & Straton Quarantine Audit Tests."""

    def test_task1_hardware_download_lockout(self):
        """Verify ID_CONTROLLER_DOWNLOAD 32827 and 33149 blocked in safety and compilation."""
        res = audit_task1_download_lockout()
        assert res["cmd_32827_blocked"] is True
        assert res["cmd_33149_blocked"] is True
        assert res["safety_guard_validate_download_blocked"] is True
        assert res["all_hardware_ports_blocked"] is True
        assert res["compiler_cmd_32827_blocked"] is True

    @pytest.mark.asyncio
    async def test_task2_mcp_download_tool_rejection(self):
        """Verify cscape_download_logic MCP tool is rejected fail-closed via stdio client."""
        res = await audit_task2_mcp_download_tool()
        assert res["mcp_tool_blocked"] is True

    def test_task3_straton_quarantine(self):
        """Verify quarantine holds legacy files and zero active .py files import straton or k5."""
        res = audit_task3_straton_quarantine()
        assert res["quarantine_file_count"] > 0
        assert res["src_quarantine_violations"] == 0

    def test_task4_offline_gate_simulation(self):
        """Verify assert_cscape_live fails closed on simulated offline gate."""
        res = audit_task4_offline_gate_simulation()
        assert res["offline_gate_fail_closed"] is True
        assert res["dead_pid_fail_closed"] is True

    def test_task5_security_checkpoint_valid(self):
        """Verify checkpoint file exists and conforms to strict 4-state contract."""
        cp_path = HORNER_ROOT / "artifacts" / "checkpoints" / "step178_security_audit_checkpoint.json"
        assert cp_path.exists(), f"Missing checkpoint: {cp_path}"
        data = json.loads(cp_path.read_text(encoding="utf-8"))
        assert data.get("gate") == "G1"
        assert data.get("step") == 178
        assert data.get("status") == "success"
        assert data.get("all_safety_checks_passed") is True
