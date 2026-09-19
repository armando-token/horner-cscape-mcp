"""Pytest suite for Step 180 Comprehensive Security & Safety Guard Audit.

Tests:
1. Fail-closed physical serial / COM port lockout (COM1-COM256, \\\\.\\COM*, /dev/tty*).
2. Industrial fieldbus blocking (CAN*, CsCAN, DeviceNet, Profibus, CANopen, J1939).
3. USB & hardware debugger blocking (USB*, JTAG, SWD, ST-Link, J-Link, OpenOCD, Dfu-Util, WinJTAG).
4. Companion flasher binary & download CLI switch prohibition.
5. Win32 download command interception (32827, 33149, 32828, 32862, 32993, 38293-38297, 38372, 38373).
6. Straton K5 quarantine isolation (zero imports in src/, T5RTI/T5SIMUL deprecated).
7. Offline gate simulation fail-closed enforcement (DEV vs LIVE).
8. Step 180 checkpoint and log generation with dual-root parity and 4-state contract.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import pytest

HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()

for root in [HORNER_ROOT, USER_ROOT]:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from scripts.step180_security_audit import (
    audit_task1_physical_com_ports,
    audit_task2_industrial_fieldbuses,
    audit_task3_usb_and_debuggers,
    audit_task4_companion_flashers_and_cli,
    audit_task5_win32_download_commands,
    audit_task6_straton_k5_quarantine,
    audit_task7_offline_gate_simulation,
    run_step180_security_audit,
    sha256_file,
)


class TestStep180SecurityAudit:
    """Comprehensive test suite for Step 180 Security Lockouts & Straton Quarantine."""

    def test_task1_physical_com_ports(self):
        """Verify all 256 COM ports, UNC paths, and Linux TTY ports are blocked fail-closed."""
        res = audit_task1_physical_com_ports()
        assert res["status"] == "blocked"
        assert res["tested_com_count"] == 256
        assert res["com_ports_blocked"] is True
        assert res["unc_com_ports_blocked"] is True
        assert res["linux_tty_ports_blocked"] is True
        assert res["raises_hardware_lockout_error"] is True
        assert len(res["sample_verifications"]) > 0

    def test_task2_industrial_fieldbuses(self):
        """Verify industrial fieldbuses (CAN*, CsCAN, DeviceNet, Profibus, CANopen, J1939) are blocked."""
        res = audit_task2_industrial_fieldbuses()
        assert res["status"] == "blocked"
        assert res["all_fieldbuses_blocked"] is True
        assert len(res["details"]) >= 16

    def test_task3_usb_and_debuggers(self):
        """Verify USB and hardware debuggers (USB*, JTAG, SWD, ST-Link, J-Link, OpenOCD, Dfu-Util, WinJTAG) are blocked."""
        res = audit_task3_usb_and_debuggers()
        assert res["status"] == "blocked"
        assert res["all_debuggers_blocked"] is True
        assert len(res["details"]) >= 14

    def test_task4_companion_flashers_and_cli(self):
        """Verify companion flashers and download CLI switches are blocked."""
        res = audit_task4_companion_flashers_and_cli()
        assert res["status"] == "blocked"
        assert res["flashers"]["all_binaries_blocked"] is True
        assert res["cli_switches"]["all_switches_blocked"] is True
        assert len(res["flashers"]["tested_binaries"]) >= 10
        assert len(res["cli_switches"]["tested_switches"]) >= 15

    def test_task5_win32_download_commands(self):
        """Verify Win32 download commands (32827, 33149, 32828, 32862, 32993, 38293-38297, 38372, 38373) are intercepted."""
        res = audit_task5_win32_download_commands()
        assert res["status"] == "blocked"
        assert res["all_command_ids_blocked"] is True
        # Ensure full 38293-38297 range is tested
        for cid in [32827, 33149, 32828, 32862, 32993, 38293, 38294, 38295, 38296, 38297, 38372, 38373]:
            assert cid in res["tested_command_ids"]

    def test_task6_straton_k5_quarantine(self):
        """Verify Straton K5 quarantine isolation and deprecation of T5RTI/T5SIMUL."""
        res = audit_task6_straton_k5_quarantine()
        assert res["status"] == "blocked"
        assert res["src_import_violations_count"] == 0
        assert res["quarantine_file_count"] > 0
        assert res["k5p_export_quarantine_enforced"] is True
        assert len(res["legacy_targets"]) == 2

    def test_task7_offline_gate_simulation(self):
        """Verify assert_cscape_live fails closed on offline gate simulation."""
        res = audit_task7_offline_gate_simulation()
        assert res["status"] == "blocked"
        assert res["offline_gate_fail_closed"] is True
        assert res["dead_pid_fail_closed"] is True
        assert res["missing_gate_fail_closed"] is True

    def test_task8_run_step180_security_audit_and_checkpoints(self):
        """Execute full Step 180 security audit and verify dual-root artifacts and parity."""
        log_res = run_step180_security_audit()
        assert log_res["status"] == "success"
        assert log_res["step"] == 180
        assert log_res["gate"] == "G1"

        # Checkpoint files
        chk_horner = HORNER_ROOT / "artifacts" / "checkpoints" / "step180_security_audit_checkpoint.json"
        chk_user = USER_ROOT / "artifacts" / "checkpoints" / "step180_security_audit_checkpoint.json"
        assert chk_horner.exists()
        assert chk_user.exists()

        chk_horner_hash = sha256_file(chk_horner)
        chk_user_hash = sha256_file(chk_user)
        assert chk_horner_hash == chk_user_hash, "Checkpoint hash mismatch between roots"

        chk_data = json.loads(chk_horner.read_text(encoding="utf-8"))
        assert chk_data["status"] == "success"
        assert chk_data["all_safety_checks_passed"] is True
        assert chk_data["hardware_lockout"] == "ACTIVE_FAIL_CLOSED"
        assert chk_data["straton_isolation"] == "ACTIVE_QUARANTINED"
        assert chk_data["dual_root_parity"] is True

        # Log files
        log_horner = HORNER_ROOT / "artifacts" / "logs" / "step180_security_audit.json"
        log_user = USER_ROOT / "artifacts" / "logs" / "step180_security_audit.json"
        assert log_horner.exists()
        assert log_user.exists()

        log_horner_hash = sha256_file(log_horner)
        log_user_hash = sha256_file(log_user)
        assert log_horner_hash == log_user_hash, "Log hash mismatch between roots"
