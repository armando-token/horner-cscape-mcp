"""Pytest suite for Step 188 Dual-Root Synchronization & Megaplan Gate G5.

Validates:
1. Dual-root byte-for-byte parity across checkpoints, logs, screenshots, scripts, tests, examples, project files, and guides.
2. Megaplan Gate G5 checkpoint validity (gate=G5, step=188, status=success, G0-G5 verified, FB_PumpLeadLagAlternator in G4).
3. Step 188 dual-root sync checkpoint and audit log validity.
4. Strict 4-state contract compliance (success | failed | blocked | inconclusive).
5. Taxonomy enforcement: offline/DEV (TESTED_MOCK) vs VERIFIED_LIVE vs BLOCKED_SAFETY.
6. Zero physical PLC / download lockout (32827/33149) and Straton quarantine invariants.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class TestStep188DualRootSync:
    """Step 188 Dual-Root Synchronization & Gate G5 Parity Tests."""

    def test_megaplan_g5_checkpoint_validity(self):
        """Verify megaplan_g5_final_parity_checkpoint.json in both roots."""
        for root in [HORNER_ROOT, USER_ROOT]:
            cp = root / "artifacts" / "checkpoints" / "megaplan_g5_final_parity_checkpoint.json"
            assert cp.exists(), f"Missing G5 checkpoint: {cp}"
            data = json.loads(cp.read_text(encoding="utf-8"))
            assert data.get("gate") == "G5"
            assert data.get("step") == 188
            assert data.get("status") == "success"
            assert data.get("dual_root_parity") is True
            assert "G0_inventory_and_pe_binary_audit" in data.get("gates_verified", {})
            assert "G1_false_success_closure" in data.get("gates_verified", {})
            assert "G2_live_cscape_visible_gui" in data.get("gates_verified", {})
            assert "G3_live_gui_compile_pipeline" in data.get("gates_verified", {})
            assert "G4_pure_software_simulation" in data.get("gates_verified", {})
            assert "FB_PumpLeadLagAlternator" in data.get("gates_verified", {}).get("G4_pure_software_simulation", "")
            assert "artifacts/screenshots/live_cscape_tank_level_step188.png" in data.get("gates_verified", {}).get("G2_live_cscape_visible_gui", "")
            assert "G5_final_parity_signoff" in data.get("gates_verified", {})
            assert data.get("contract", {}).get("status") == "success"

    def test_megaplan_g5_checkpoint_parity(self):
        """Verify byte-for-byte parity for G5 checkpoint between roots."""
        p1 = HORNER_ROOT / "artifacts" / "checkpoints" / "megaplan_g5_final_parity_checkpoint.json"
        p2 = USER_ROOT / "artifacts" / "checkpoints" / "megaplan_g5_final_parity_checkpoint.json"
        assert p1.read_bytes() == p2.read_bytes()
        assert compute_sha256(p1) == compute_sha256(p2)

    def test_step188_sync_checkpoint_validity(self):
        """Verify step188_dual_root_sync_checkpoint.json in both roots."""
        for root in [HORNER_ROOT, USER_ROOT]:
            cp = root / "artifacts" / "checkpoints" / "step188_dual_root_sync_checkpoint.json"
            assert cp.exists(), f"Missing step 188 sync checkpoint: {cp}"
            data = json.loads(cp.read_text(encoding="utf-8"))
            assert data.get("gate") == "G5"
            assert data.get("step") == 188
            assert data.get("status") == "success"
            assert data.get("parity_status") == "success"
            assert data.get("contract", {}).get("status") == "success"

    def test_step188_sync_audit_log_validity(self):
        """Verify step188_dual_root_sync_audit.json in both roots."""
        for root in [HORNER_ROOT, USER_ROOT]:
            log_path = root / "artifacts" / "logs" / "step188_dual_root_sync_audit.json"
            assert log_path.exists(), f"Missing step 188 sync audit log: {log_path}"
            data = json.loads(log_path.read_text(encoding="utf-8"))
            assert data.get("gate") == "G5"
            assert data.get("step") == 188
            assert data.get("status") == "success"
            assert data.get("parity_verified") is True

    def test_all_step188_and_megaplan_files_parity(self):
        """Verify byte-for-byte parity across all Step 188 and Megaplan artifacts."""
        files_to_check = [
            "artifacts/checkpoints/megaplan_g2_visible_gui_checkpoint.json",
            "artifacts/checkpoints/megaplan_g3_live_compile_pipeline_checkpoint.json",
            "artifacts/checkpoints/megaplan_g4_closed_loop_simulation_checkpoint.json",
            "artifacts/checkpoints/megaplan_g5_final_parity_checkpoint.json",
            "artifacts/checkpoints/step188_visible_gui_proof_checkpoint.json",
            "artifacts/checkpoints/step188_security_audit_checkpoint.json",
            "artifacts/checkpoints/step188_pure_st_audit_checkpoint.json",
            "artifacts/checkpoints/step188_mcp_pump_lead_lag_alternator_checkpoint.json",
            "artifacts/checkpoints/step188_g1_false_success_audit_checkpoint.json",
            "artifacts/checkpoints/step188_dual_root_sync_checkpoint.json",
            "artifacts/logs/step188_visible_gui_proof.json",
            "artifacts/logs/step188_security_audit.json",
            "artifacts/logs/step188_pure_st_audit.json",
            "artifacts/logs/step188_mcp_pump_lead_lag_alternator.json",
            "artifacts/logs/step188_g1_false_success_audit.json",
            "artifacts/logs/step188_dual_root_sync_audit.json",
            "artifacts/screenshots/live_cscape_tank_level_step188.png",
            "examples/st_applications/pump_lead_lag_alternator.st",
            "scripts/execute_step188_visible_cscape_gui_driver.py",
            "scripts/step188_security_audit.py",
            "scripts/execute_step188_pure_st_audit.py",
            "scripts/execute_step188_mcp_pump_lead_lag_alternator.py",
            "scripts/execute_step188_g1_false_success_audit.py",
            "scripts/execute_step188_dual_root_sync_audit.py",
            "tests/test_step188_visible_cscape_gui_driver.py",
            "tests/test_step188_security_audit.py",
            "tests/test_step188_pure_st_audit.py",
            "tests/test_step188_mcp_pump_lead_lag_alternator.py",
            "tests/test_step188_g1_false_success_audit.py",
            "tests/test_step188_dual_root_sync.py",
            "CHANGELOG.md",
            "AGENTS.md",
        ]
        for rel in files_to_check:
            p1 = HORNER_ROOT / rel
            p2 = USER_ROOT / rel
            assert p1.exists(), f"Missing in HORNER_ROOT: {rel}"
            assert p2.exists(), f"Missing in USER_ROOT: {rel}"
            h1 = compute_sha256(p1)
            h2 = compute_sha256(p2)
            assert h1 == h2, f"SHA-256 mismatch for {rel}: {h1} != {h2}"

    def test_strict_4_state_contract_compliance(self):
        """Ensure all Step 188 checkpoints and logs strictly adhere to the 4-state contract."""
        allowed_statuses = {"success", "failed", "blocked", "inconclusive"}
        checkpoints = [
            "step188_visible_gui_proof_checkpoint.json",
            "step188_security_audit_checkpoint.json",
            "step188_pure_st_audit_checkpoint.json",
            "step188_mcp_pump_lead_lag_alternator_checkpoint.json",
            "step188_g1_false_success_audit_checkpoint.json",
            "step188_dual_root_sync_checkpoint.json",
            "megaplan_g2_visible_gui_checkpoint.json",
            "megaplan_g3_live_compile_pipeline_checkpoint.json",
            "megaplan_g4_closed_loop_simulation_checkpoint.json",
            "megaplan_g5_final_parity_checkpoint.json",
        ]
        for root in [HORNER_ROOT, USER_ROOT]:
            for cp_name in checkpoints:
                path = root / "artifacts" / "checkpoints" / cp_name
                if path.exists():
                    data = json.loads(path.read_text(encoding="utf-8"))
                    assert data.get("status") in allowed_statuses, (
                        f"Violated status contract in {cp_name}: '{data.get('status')}'"
                    )

    def test_zero_hardware_download_and_straton_invariants(self):
        """Enforce fail-closed hardware lockout and Straton quarantine invariants."""
        cp = HORNER_ROOT / "artifacts" / "checkpoints" / "megaplan_g5_final_parity_checkpoint.json"
        data = json.loads(cp.read_text(encoding="utf-8"))
        contract = data.get("contract", {})
        assert contract.get("no_plc_downloads") is True
        assert contract.get("no_straton_imports") is True
        assert contract.get("fail_closed_guaranteed") is True

    def test_verification_taxonomy_enforcement(self):
        """Ensure honest architectural taxonomy labeling in checkpoints."""
        cp = HORNER_ROOT / "artifacts" / "checkpoints" / "megaplan_g5_final_parity_checkpoint.json"
        data = json.loads(cp.read_text(encoding="utf-8"))
        taxonomy = data.get("verification_classification", {})
        assert "offline/DEV (TESTED_MOCK)" in taxonomy.get("offline_compilation_and_ast", "")
        assert "offline/DEV (TESTED_MOCK)" in taxonomy.get("pure_software_simulation", "")
        assert "VERIFIED_LIVE" in taxonomy.get("live_cscape_gui_gate", "")
        assert "BLOCKED_SAFETY" in taxonomy.get("hardware_lockout", "")
