"""Tests for Multi-Rate Dynamic Closed-Loop Scan Verification (Step 16)."""
import json
from pathlib import Path
import pytest


def test_multirate_scan_checkpoint_verified():
    for root in [Path(r"C:\Users\ArmandoSilva"), Path(r"C:\HornerAI\horner-cscape-mcp")]:
        ckpt_path = root / "artifacts" / "checkpoints" / "step16_multirate_scan_checkpoint.json"
        assert ckpt_path.exists(), f"Checkpoint missing at {ckpt_path}"
        data = json.loads(ckpt_path.read_text(encoding="utf-8"))
        assert data["status"] == "PASSED"
        assert data["total_scan_rates_tested"] == 6
        assert data["total_cycles_executed"] == 3000
        assert data["discretization_invariance_verified"] is True
        assert data["numerical_stability_verified"] is True
        assert data["bumpless_behavior_verified"] is True
        assert data["zero_nan_or_overflow"] is True
        assert data["zero_plc_download_enforced"] is True
        assert data["zero_straton_dependencies_enforced"] is True


def test_multirate_scan_audit_log_verified():
    for root in [Path(r"C:\Users\ArmandoSilva"), Path(r"C:\HornerAI\horner-cscape-mcp")]:
        audit_path = root / "artifacts" / "logs" / "mcp_closed_loop_multirate_scan_audit.json"
        assert audit_path.exists(), f"Audit log missing at {audit_path}"
        data = json.loads(audit_path.read_text(encoding="utf-8"))
        assert data["overall_status"] == "PASSED"
        assert len(data["scan_rates"]) == 6
        for r in data["scan_rates"]:
            assert r["disturbance_phase"]["final_error"] <= 0.50
            assert r["disturbance_phase"]["overshoot_pct"] <= 5.0
            assert r["bumpless_transfer_phase"]["transfer_delta_cv"] <= 0.05
            assert r["numerical_stability"]["nan_detected"] is False
            assert r["numerical_stability"]["inf_detected"] is False
