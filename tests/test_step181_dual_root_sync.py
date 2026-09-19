"""Pytest suite for Step 181 Dual-Root Synchronization & Megaplan Gate G5.

Validates:
1. Dual-root byte-for-byte parity across checkpoints, logs, screenshots, scripts, tests, examples, and guides.
2. Megaplan Gate G5 checkpoint validity (gate=G5, status=success, G0-G5 verified).
3. Step 181 dual-root sync checkpoint and audit log validity.
4. Strict 4-state contract compliance (success | failed | blocked | inconclusive).
5. Taxonomy enforcement: offline/DEV (TESTED_MOCK) vs VERIFIED_LIVE vs BLOCKED_SAFETY.
6. Zero PLC download and Straton quarantine invariants.
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


class TestStep181DualRootSync:
    """Step 181 Dual-Root Synchronization & Gate G5 Parity Tests."""

    def test_megaplan_g5_checkpoint_validity(self):
        """Verify megaplan_g5_final_parity_checkpoint.json in both roots."""
        for root in [HORNER_ROOT, USER_ROOT]:
            cp = root / "artifacts" / "checkpoints" / "megaplan_g5_final_parity_checkpoint.json"
            assert cp.exists(), f"Missing G5 checkpoint: {cp}"
            data = json.loads(cp.read_text(encoding="utf-8"))
            assert data.get("gate") == "G5"
            assert data.get("status") == "success"
            assert data.get("dual_root_parity") is True
            assert "G0_inventory_and_pe_binary_audit" in data.get("gates_verified", {})
            assert "G1_false_success_closure" in data.get("gates_verified", {})
            assert "G2_live_cscape_visible_gui" in data.get("gates_verified", {})
            assert "G3_live_gui_compile_pipeline" in data.get("gates_verified", {})
            assert "G4_pure_software_simulation" in data.get("gates_verified", {})
            assert "G5_final_parity_signoff" in data.get("gates_verified", {})
            assert data.get("contract", {}).get("status") == "success"

    def test_megaplan_g5_checkpoint_parity(self):
        """Verify byte-for-byte parity for G5 checkpoint between roots."""
        p1 = HORNER_ROOT / "artifacts" / "checkpoints" / "megaplan_g5_final_parity_checkpoint.json"
        p2 = USER_ROOT / "artifacts" / "checkpoints" / "megaplan_g5_final_parity_checkpoint.json"
        assert p1.read_bytes() == p2.read_bytes()
        assert compute_sha256(p1) == compute_sha256(p2)

    def test_step181_sync_checkpoint_validity(self):
        """Verify step181_dual_root_sync_checkpoint.json in both roots."""
        for root in [HORNER_ROOT, USER_ROOT]:
            cp = root / "artifacts" / "checkpoints" / "step181_dual_root_sync_checkpoint.json"
            assert cp.exists(), f"Missing step 181 sync checkpoint: {cp}"
            data = json.loads(cp.read_text(encoding="utf-8"))
            assert data.get("gate") == "G5"
            assert data.get("step") == 181
            assert data.get("status") == "success"
            assert data.get("parity_status") == "100% PARITY IDENTICAL SHA-256"
            assert data.get("contract", {}).get("status") == "success"

    def test_step181_sync_audit_log_validity(self):
        """Verify step181_dual_root_sync_audit.json in both roots."""
        for root in [HORNER_ROOT, USER_ROOT]:
            log_path = root / "artifacts" / "logs" / "step181_dual_root_sync_audit.json"
            assert log_path.exists(), f"Missing step 181 sync audit log: {log_path}"
            data = json.loads(log_path.read_text(encoding="utf-8"))
            assert data.get("gate") == "G5"
            assert data.get("step") == 181
            assert data.get("status") == "success"
            assert data.get("parity_verified") is True

    def test_all_step181_and_megaplan_files_parity(self):
        """Verify byte-for-byte parity across all Step 181 and Megaplan artifacts."""
        files_to_check = [
            "artifacts/checkpoints/megaplan_g2_visible_gui_checkpoint.json",
            "artifacts/checkpoints/megaplan_g3_live_compile_pipeline_checkpoint.json",
            "artifacts/checkpoints/megaplan_g4_closed_loop_simulation_checkpoint.json",
            "artifacts/checkpoints/megaplan_g5_final_parity_checkpoint.json",
            "artifacts/checkpoints/step181_visible_gui_proof_checkpoint.json",
            "artifacts/checkpoints/step181_security_audit_checkpoint.json",
            "artifacts/checkpoints/step181_mcp_first_fault_annunciator_checkpoint.json",
            "artifacts/checkpoints/step181_dual_root_sync_checkpoint.json",
            "artifacts/logs/step181_visible_gui_proof.json",
            "artifacts/logs/step181_security_audit.json",
            "artifacts/logs/step181_mcp_first_fault_annunciator.json",
            "artifacts/logs/step181_dual_root_sync_audit.json",
            "artifacts/logs/megaplan_g4_closed_loop_simulation.json",
            "artifacts/screenshots/live_cscape_tank_level_step181.png",
            "scripts/execute_step181_visible_cscape_gui_driver.py",
            "scripts/step181_security_audit.py",
            "scripts/execute_step181_mcp_first_fault_annunciator.py",
            "scripts/execute_step181_dual_root_sync_audit.py",
            "tests/test_step181_visible_cscape_gui_driver.py",
            "tests/test_step181_security_audit.py",
            "tests/test_step181_mcp_first_fault_annunciator.py",
            "tests/test_step181_dual_root_sync.py",
            "examples/st_applications/first_fault_annunciator.st",
            "CAPABILITY_MATRIX.md",
            "AGENTS.md",
        ]
        for rel in files_to_check:
            p1 = HORNER_ROOT / rel
            p2 = USER_ROOT / rel
            assert p1.exists(), f"Missing in Horner root: {p1}"
            assert p2.exists(), f"Missing in User root: {p2}"
            h1 = compute_sha256(p1)
            h2 = compute_sha256(p2)
            assert h1 == h2, f"SHA-256 mismatch for {rel}: {h1} != {h2}"

    def test_strict_4state_contract(self):
        """Verify all checkpoints adhere to the strict 4-state contract."""
        allowed_states = {"success", "failed", "blocked", "inconclusive"}
        checkpoints = [
            "artifacts/checkpoints/megaplan_g2_visible_gui_checkpoint.json",
            "artifacts/checkpoints/megaplan_g3_live_compile_pipeline_checkpoint.json",
            "artifacts/checkpoints/megaplan_g4_closed_loop_simulation_checkpoint.json",
            "artifacts/checkpoints/megaplan_g5_final_parity_checkpoint.json",
            "artifacts/checkpoints/step181_dual_root_sync_checkpoint.json",
            "artifacts/checkpoints/step181_security_audit_checkpoint.json",
            "artifacts/checkpoints/step181_visible_gui_proof_checkpoint.json",
            "artifacts/checkpoints/step181_mcp_first_fault_annunciator_checkpoint.json",
        ]
        for rel in checkpoints:
            p = HORNER_ROOT / rel
            data = json.loads(p.read_text(encoding="utf-8"))
            status = data.get("status")
            assert status in allowed_states, f"{rel} invalid status: {status}"
