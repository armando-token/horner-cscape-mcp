"""Pytest suite for Step 190 Comprehensive Security & Safety Guard Audit.

Tests:
1. Fail-closed physical serial / COM port lockout (COM1-COM256, \\\\.\\COM*, /dev/tty*).
2. Industrial fieldbus blocking (CAN*, CsCAN, DeviceNet, Profibus, CANopen, J1939, Modbus-RTU, etc.).
3. USB & hardware debugger blocking (USB*, JTAG, SWD, ST-Link, J-Link, OpenOCD, Dfu-Util, WinJTAG, LPT*).
4. Companion flasher binary prohibition (BlockedExecutableError).
5. Download CLI switch & hardware flag interception (DangerousArgumentError / HardwareLockoutError).
6. Win32 download and communication command interception (32827, 33149, 32828, 32862, 32993, 38293-38297, 38372, 38373, etc.).
7. Straton K5 quarantine isolation (zero imports in src/, T5RTI/T5SIMUL deprecated).
8. Modern Horner hardware models allowlisting (EXL10, XL10, XL+, Micro OCS, X2-X7).
9. Gate simulation classification (offline/DEV [TESTED_MOCK] vs VERIFIED_LIVE fail-closed).
10. Step 190 checkpoint and log generation with dual-root parity, 4-state contract, and 398+ rules verified.
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

from scripts.step190_security_audit import (
    audit_rule1_physical_com_ports,
    audit_rule2_industrial_fieldbuses,
    audit_rule3_usb_and_debuggers,
    audit_rule4_companion_flashers,
    audit_rule5_download_cli_switches,
    audit_rule6_win32_download_commands,
    audit_rule7_straton_k5_quarantine,
    audit_rule8_modern_horner_models_allowlisted,
    audit_rule9_gate_simulation_classification,
    audit_rule10_dual_root_parity_and_contracts,
    run_step190_security_audit,
    sha256_file,
)


class TestStep190SecurityAudit:
    """Comprehensive test suite for Step 190 Security Lockouts, Allowlist & Straton Quarantine (398+ rules)."""

    def test_rule1_physical_com_ports(self):
        """Verify all 256 COM ports, UNC paths, and Linux TTY ports are blocked fail-closed."""
        res = audit_rule1_physical_com_ports()
        assert res["status"] == "blocked"
        assert res["tested_com_count"] == 256
        assert res["com_ports_blocked"] is True
        assert res["unc_com_ports_blocked"] is True
        assert res["linux_tty_ports_blocked"] is True
        assert res["raises_hardware_lockout_error"] is True
        assert len(res["sample_verifications"]) > 0
        assert res["rules_evaluated"] >= 268

    def test_rule2_industrial_fieldbuses(self):
        """Verify industrial fieldbuses (CAN*, CsCAN, DeviceNet, Profibus, CANopen, J1939, Modbus-RTU) are blocked."""
        res = audit_rule2_industrial_fieldbuses()
        assert res["status"] == "blocked"
        assert res["all_fieldbuses_blocked"] is True
        assert len(res["details"]) >= 16
        assert res["rules_evaluated"] >= 20

    def test_rule3_usb_and_debuggers(self):
        """Verify USB and hardware debuggers (USB*, JTAG, SWD, ST-Link, J-Link, OpenOCD, Dfu-Util, WinJTAG, LPT*) are blocked."""
        res = audit_rule3_usb_and_debuggers()
        assert res["status"] == "blocked"
        assert res["all_debuggers_blocked"] is True
        assert len(res["details"]) >= 14
        assert res["rules_evaluated"] >= 16

    def test_rule4_companion_flashers(self):
        """Verify companion flashers are blocked with BlockedExecutableError."""
        res = audit_rule4_companion_flashers()
        assert res["status"] == "blocked"
        assert res["all_binaries_blocked"] is True
        assert len(res["tested_binaries"]) >= 10
        assert res["rules_evaluated"] >= 15

    def test_rule5_download_cli_switches(self):
        """Verify download CLI switches and hardware flags are intercepted fail-closed."""
        res = audit_rule5_download_cli_switches()
        assert res["status"] == "blocked"
        assert res["all_switches_blocked"] is True
        assert len(res["tested_switches"]) >= 15
        assert res["rules_evaluated"] >= 25

    def test_rule6_win32_download_commands(self):
        """Verify Win32 download commands (32827, 33149, 32828, 32862, 32993, 38293-38297, 38372, 38373) and comms IDs are intercepted."""
        res = audit_rule6_win32_download_commands()
        assert res["status"] == "blocked"
        assert res["all_command_ids_blocked"] is True
        for cid in [32827, 33149, 32828, 32862, 32993, 38293, 38294, 38295, 38296, 38297, 38372, 38373]:
            assert cid in res["tested_command_ids"]
        assert res["rules_evaluated"] >= 17

    def test_rule7_straton_k5_quarantine(self):
        """Verify Straton K5 quarantine isolation and deprecation of T5RTI/T5SIMUL."""
        res = audit_rule7_straton_k5_quarantine()
        assert res["status"] == "blocked"
        assert res["src_import_violations_count"] == 0
        assert res["quarantine_file_count"] > 0
        assert res["k5p_export_quarantine_enforced"] is True
        assert len(res["legacy_targets"]) == 2
        assert res["rules_evaluated"] == 5

    def test_rule8_modern_horner_models_allowlisted(self):
        """Verify modern Horner hardware models (EXL10, XL10, XL+, Micro OCS, X2-X7) are allowlisted."""
        res = audit_rule8_modern_horner_models_allowlisted()
        assert res["status"] == "success"
        assert res["all_modern_models_allowlisted"] is True
        assert res["mandated_models_count"] >= 10
        # Specifically ensure EXL10, XL10, XL+, Micro OCS, X2, X4, X5, X7 are tested
        verified_model_names = [m["model"] for m in res["verified_models"]]
        for required_model in ["EXL10", "XL10", "XL+", "Micro OCS", "X2", "X4", "X5", "X7"]:
            assert required_model in verified_model_names
        assert len(res["hardware_targets_locked_out"]) >= 3
        assert len(res["alien_targets_rejected"]) >= 3
        assert res["rules_evaluated"] >= 23

    def test_rule9_gate_simulation_classification(self):
        """Verify gate simulation classification and fail-closed gate assertions."""
        res = audit_rule9_gate_simulation_classification()
        assert res["status"] == "blocked"
        assert res["offline_gate_fail_closed"] is True
        assert res["dead_pid_fail_closed"] is True
        assert res["missing_gate_fail_closed"] is True
        assert res["verification_taxonomy"]["offline_audits"] == "offline/DEV (TESTED_MOCK)"
        assert res["verification_taxonomy"]["live_gui_gate"] == "VERIFIED_LIVE"
        assert res["rules_evaluated"] == 3

    def test_rule10_run_step190_security_audit_and_checkpoints(self):
        """Execute full Step 190 security audit and verify dual-root artifacts, 398+ rules, and parity."""
        log_res = run_step190_security_audit()
        assert log_res["status"] == "success"
        assert log_res["step"] == 190
        assert log_res["gate"] == "G1"
        assert log_res["total_rules_evaluated"] >= 398
        assert log_res["verification_taxonomy"]["offline_audits"] == "offline/DEV (TESTED_MOCK)"
        assert log_res["verification_taxonomy"]["live_gui_gate"] == "VERIFIED_LIVE"

        # Checkpoint files
        chk_horner = HORNER_ROOT / "artifacts" / "checkpoints" / "step190_security_audit_checkpoint.json"
        chk_user = USER_ROOT / "artifacts" / "checkpoints" / "step190_security_audit_checkpoint.json"
        assert chk_horner.exists()
        assert chk_user.exists()

        chk_horner_hash = sha256_file(chk_horner)
        chk_user_hash = sha256_file(chk_user)
        assert chk_horner_hash == chk_user_hash, "Checkpoint hash mismatch between roots"

        chk_data = json.loads(chk_horner.read_text(encoding="utf-8"))
        assert chk_data["status"] == "success"
        assert chk_data["step"] == 190
        assert chk_data["total_rules_evaluated"] >= 398
        assert chk_data["all_safety_checks_passed"] is True
        assert chk_data["hardware_lockout"] == "ACTIVE_FAIL_CLOSED"
        assert chk_data["straton_isolation"] == "ACTIVE_QUARANTINED"
        assert chk_data["dual_root_parity"] is True
        assert "EXL10" in chk_data["safety_policies_enforced"]["modern_horner_models_allowlisted"]
        assert "X7" in chk_data["safety_policies_enforced"]["modern_horner_models_allowlisted"]

        # Log files
        log_horner = HORNER_ROOT / "artifacts" / "logs" / "step190_security_audit.json"
        log_user = USER_ROOT / "artifacts" / "logs" / "step190_security_audit.json"
        assert log_horner.exists()
        assert log_user.exists()

        log_horner_hash = sha256_file(log_horner)
        log_user_hash = sha256_file(log_user)
        assert log_horner_hash == log_user_hash, "Log hash mismatch between roots"
