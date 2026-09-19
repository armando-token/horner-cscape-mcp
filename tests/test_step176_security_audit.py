"""Pytest suite for Step 176 Security Lockout Audit.

Validates fail-closed security validation:
1. Hardware download lockout across safety.py and compilation.py (ID 32827 & 33149).
2. Physical serial port lockout (COM1..COM256) and fieldbus/debugger lockout.
3. cscape_download_logic rejection via FastMCP stdio client.
4. Straton quarantine status and zero active .py imports of straton or k5.
5. Offline gate simulation fail-closed assertion raising CscapeLivenessGateError.
6. Verify step176 security audit checkpoint exists and conforms to 4-state contract.
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

from scripts.execute_step176_security_audit import (
    audit_task1_hardware_lockout,
    audit_task2_mcp_download_tool,
    audit_task3_straton_quarantine,
    audit_task4_offline_gate_simulation,
)


class TestStep176SecurityAudit:
    """Step 176 Security Lockout & Straton Quarantine Audit Tests."""

    def test_task1_hardware_download_lockout(self):
        """Verify ID_CONTROLLER_DOWNLOAD 32827 and 33149 blocked in safety and compilation."""
        res = audit_task1_hardware_lockout()
        assert res["cmd_32827_blocked"] is True
        assert res["cmd_33149_blocked"] is True
        assert res["safety_guard_validate_download_blocked"] is True
        assert res["all_hardware_ports_blocked"] is True
        assert res["compiler_cmd_32827_blocked"] is True
        assert res["compiler_cmd_33149_blocked"] is True

    @pytest.mark.asyncio
    async def test_task2_mcp_download_tool_rejection(self):
        """Verify cscape_download_logic MCP tool is rejected fail-closed via stdio client."""
        res = await audit_task2_mcp_download_tool()
        assert res["mcp_tool_blocked"] is True

    def test_task3_straton_quarantine(self):
        """Verify quarantine holds legacy files and zero active .py files import straton or k5."""
        res = audit_task3_straton_quarantine()
        assert res["quarantine_file_count"] > 0
        assert res["straton_import_violations"] == 0

    def test_task4_offline_gate_simulation(self):
        """Verify assert_cscape_live() raises CscapeLivenessGateError fail-closed when gate offline."""
        res = audit_task4_offline_gate_simulation()
        assert res["offline_gate_rejected"] is True
        assert res["dead_pid_rejected"] is True

    def test_step176_checkpoint_verification(self):
        """Verify step176 checkpoint exists, has status 'success', and maintains dual-root parity."""
        horner_cp = HORNER_ROOT / "artifacts" / "checkpoints" / "step176_security_audit_checkpoint.json"
        user_cp = USER_ROOT / "artifacts" / "checkpoints" / "step176_security_audit_checkpoint.json"

        assert horner_cp.exists(), f"Horner checkpoint missing: {horner_cp}"
        assert user_cp.exists(), f"User checkpoint missing: {user_cp}"

        h_data = json.loads(horner_cp.read_text(encoding="utf-8"))
        u_data = json.loads(user_cp.read_text(encoding="utf-8"))

        assert h_data["status"] == "success"
        assert u_data["status"] == "success"
        assert h_data["step"] == 176
        assert u_data["step"] == 176
        assert h_data["gate"] == "G1"
        assert h_data["safety_audit"]["hardware_lockout_verified"] is True
        assert h_data["safety_audit"]["straton_quarantined"] is True
        assert h_data["safety_audit"]["offline_gate_fail_closed"] is True
        assert h_data["dual_root_parity"] is True
        assert h_data == u_data
