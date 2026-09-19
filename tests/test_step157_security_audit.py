"""Pytest suite for Step 157 Security Lockout Audit.

Validates fail-closed security validation:
1. Hardware download lockout across safety.py and compilation.py (ID 32827 & 33149).
2. cscape_download_logic rejection via run_mcp_server.py stdio client.
3. Straton quarantine status and zero active .py imports of straton or k5.
4. Offline gate simulation fail-closed assertion raising CscapeLivenessGateError.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
import pytest
from unittest.mock import patch

USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()

for root in [USER_ROOT, HORNER_ROOT]:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from scripts.execute_step157_security_audit import (
    audit_task1_hardware_download_lockout,
    audit_task2_mcp_download_tool_rejection,
    audit_task3_straton_quarantine,
    audit_task4_offline_gate_simulation,
)


class TestStep157SecurityAudit:
    """Step 157 Security Lockout & Straton Quarantine Audit Tests."""

    def test_task1_hardware_download_lockout(self):
        """Verify ID_CONTROLLER_DOWNLOAD 32827 and 33149 blocked in safety and compilation."""
        res = audit_task1_hardware_download_lockout()
        assert res["status"] == "PASSED"
        assert res["safety_py"]["passed"] is True
        assert res["compilation_py"]["passed"] is True

    @pytest.mark.asyncio
    async def test_task2_mcp_download_tool_rejection(self):
        """Verify cscape_download_logic MCP tool is rejected fail-closed via stdio client."""
        res = await audit_task2_mcp_download_tool_rejection()
        assert res["status"] == "PASSED"
        assert res["is_error"] is True
        assert res["rejection_fail_closed"] is True

    def test_task3_straton_quarantine(self):
        """Verify quarantine holds legacy files and zero active .py files import straton or k5."""
        res = audit_task3_straton_quarantine()
        assert res["status"] == "PASSED"
        assert res["legacy_files_count"] > 0
        assert res["active_straton_imports_count"] == 0
        assert res["zero_straton_imports_verified"] is True

    def test_task4_offline_gate_simulation(self):
        """Verify assert_cscape_live() raises CscapeLivenessGateError fail-closed when gate offline."""
        res = audit_task4_offline_gate_simulation()
        assert res["status"] == "PASSED"
        assert res["cscape_liveness_gate_error_raised"] is True
        assert res["fail_closed_verified"] is True
