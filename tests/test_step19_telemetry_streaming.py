"""Automated Pytest Suite for Step 19: Stdio Closed-Loop Telemetry Streaming."""
import json
from pathlib import Path
import pytest

USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step19_checkpoint_valid(root: Path):
    ckpt_path = root / "artifacts" / "checkpoints" / "step19_telemetry_streaming_checkpoint.json"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"
    data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert data["step"] == 19
    assert data["status"] == "VERIFIED_LIVE"
    assert data["total_frames"] == 600
    assert data["frame_drops"] == 0
    assert data["throughput_frames_per_sec"] > 200.0
    assert data["latency_median_ms"] < 10.0
    assert data["cscape_healthy"] is True
    assert data["cscape_pid"] > 0
    assert data["convergence_summary"]["phase_1_converged"] is True
    assert data["convergence_summary"]["phase_2_converged"] is True
    assert data["convergence_summary"]["phase_3_converged"] is True
    assert data["convergence_summary"]["phase_4_converged"] is True


@pytest.mark.parametrize("root", [USER_ROOT, HORNER_ROOT])
def test_step19_audit_log_valid(root: Path):
    log_path = root / "artifacts" / "logs" / "mcp_stdio_telemetry_streaming.json"
    assert log_path.exists(), f"Missing audit log: {log_path}"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["step"] == 19
    assert data["stream_summary"]["total_frames_streamed"] == 600
    assert data["stream_summary"]["total_frame_drops"] == 0
    assert data["stream_summary"]["frame_loss_rate_pct"] == 0.0
    assert data["stream_summary"]["monotonic_sequence_verified"] is True
    assert data["stream_summary"]["monotonic_timestamps_verified"] is True
    assert data["convergence_summary"]["phase_1_baseline_error_pct"] <= 0.05
    assert data["convergence_summary"]["phase_2_step_up_error_pct"] <= 0.05
    assert data["convergence_summary"]["phase_3_surge_rejection_error_pct"] <= 0.05
    assert data["convergence_summary"]["phase_4_step_down_error_pct"] <= 0.05
