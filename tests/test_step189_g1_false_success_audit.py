"""Test Suite for Step 189: G1 False-Success & Status Contract Auditor.

Mandates Verified:
1. Dismantling of false successes H01-H13 under Gate G1.
2. Strict enforcement of the 4-state contract: status: success | failed | blocked | inconclusive.
3. Offline/DEV suites declare TESTED_MOCK [offline/DEV only] and never falsely claim VERIFIED_LIVE.
4. Dual-root byte-for-byte parity across C:\\HornerAI\\horner-cscape-mcp and C:\\Users\\ArmandoSilva.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
import pytest

HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()

for root in [HORNER_ROOT, USER_ROOT]:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from src.mcp.tools import (
    cscape_export_project,
    cscape_open_project,
    cscape_compile_project,
    normalize_tool_result,
)
from src.cscape.project_manager import CFBF_MAGIC
from src.cscape.st_ld_interop import (
    STLadderInteropGuard,
    LadderConstructRejectedError,
)
from src.iec.validator import IECValidator
from src.security.policy import (
    SafetyPolicy,
    DEFAULT_BLOCKED_EXECUTABLES,
    DEFAULT_BLOCKED_PORT_PATTERNS,
    DEFAULT_BLOCKED_DOWNLOAD_FLAGS,
)
from src.cscape.safety import (
    CscapeSafetyGuard,
    ID_CONTROLLER_DOWNLOAD,
    ID_CONTROLLER_DOWNLOAD_ALT,
)
from src.cscape.compilation import (
    CscapeCompiler,
    UnauthorizedDownloadError,
    compute_honest_ast_metrics,
)

CANONICAL_STATUSES = {"success", "failed", "blocked", "inconclusive"}

CHECKPOINT_REL = Path("artifacts/checkpoints/step189_g1_false_success_audit_checkpoint.json")
LOG_REL = Path("artifacts/logs/step189_g1_false_success_audit.json")


def compute_sha256(data: bytes) -> str:
    """Computes SHA-256 hexadecimal hash."""
    return hashlib.sha256(data).hexdigest()


# ----------------------------------------------------------------------------
# 1. Dual-Root Parity & Checkpoint Validation
# ----------------------------------------------------------------------------
def test_step189_deliverables_dual_root_parity():
    """Verify step189 checkpoint and log exist in both roots with identical bytes and SHA-256."""
    for rel_path in [CHECKPOINT_REL, LOG_REL]:
        h_file = HORNER_ROOT / rel_path
        u_file = USER_ROOT / rel_path

        assert h_file.exists(), f"Horner root deliverable missing: {h_file}"
        assert u_file.exists(), f"User root deliverable missing: {u_file}"

        h_bytes = h_file.read_bytes()
        u_bytes = u_file.read_bytes()

        assert h_bytes == u_bytes, f"Byte mismatch for {rel_path}"
        assert compute_sha256(h_bytes) == compute_sha256(u_bytes)


def test_step189_checkpoint_contract_and_structure():
    """Verify step189 checkpoint structure and strict status contract."""
    cp_file = HORNER_ROOT / CHECKPOINT_REL
    data = json.loads(cp_file.read_text(encoding="utf-8"))

    assert data.get("gate") == "G1"
    assert data.get("step") == 189
    assert data.get("status") == "success"
    assert data.get("dual_root_parity") is True
    assert len(data.get("items_verified", [])) == 13

    # Check all 13 items passed
    h_results = data.get("h01_to_h13_results", {})
    assert len(h_results) == 13
    for k in [f"H{i:02d}" for i in range(1, 14)]:
        assert k in h_results, f"Missing item {k} in checkpoint results"
        assert h_results[k] == "success", f"Item {k} did not pass in checkpoint"


def test_step189_log_structure_and_metrics():
    """Verify step189 log structure, durations, and audit summaries."""
    log_file = HORNER_ROOT / LOG_REL
    log_data = json.loads(log_file.read_text(encoding="utf-8"))

    assert log_data.get("gate") == "G1"
    assert log_data.get("step") == 189
    assert log_data.get("status") == "success"
    assert log_data.get("summary", {}).get("total_items") == 13
    assert log_data.get("summary", {}).get("passed_items") == 13
    assert log_data.get("summary", {}).get("failed_items") == 0
    assert log_data.get("summary", {}).get("all_passed") is True


# ----------------------------------------------------------------------------
# 2. H01: Fake Export Success Without Live Engine
# ----------------------------------------------------------------------------
def test_h01_export_fail_closed():
    """H01: Export on non-existent project must fail closed with error messages."""
    res = cscape_export_project("nonexistent_test_project_h01", output_format="csp")
    assert res.get("success") is False
    assert res.get("status") in ("failed", "error", "blocked")
    assert len(res.get("errors", [])) > 0
    assert CFBF_MAGIC == bytes.fromhex("d0cf11e0a1b11ae1")


# ----------------------------------------------------------------------------
# 3. H02: Fake Open Success Without Live Engine
# ----------------------------------------------------------------------------
def test_h02_open_fail_closed():
    """H02: Open on non-existent project or with require_live_gui must fail closed."""
    res_bad = cscape_open_project("artifacts/projects/NonExistent/NonExistent.csp")
    assert res_bad.get("success") is False
    assert res_bad.get("status") in ("failed", "error")

    res_live = cscape_open_project("artifacts/projects/NonExistent/NonExistent.csp", require_live_gui=True)
    assert res_live.get("success") is False


# ----------------------------------------------------------------------------
# 4. H03: Fake Compile Success Without Live Engine
# ----------------------------------------------------------------------------
def test_h03_compile_fail_closed_and_honest_metrics():
    """H03: Compile on non-existent project must fail closed; metrics must be honest AST-derived."""
    res = cscape_compile_project("NonExistentProject_H03")
    assert res.get("success") is False
    assert res.get("compile_successful") is False

    compiler = CscapeCompiler(workspace_root=HORNER_ROOT)
    with pytest.raises(UnauthorizedDownloadError):
        compiler.trigger_cscape_gui_compile(command_id=32827)

    sample_st = "PROGRAM P VAR n:INT; END_VAR n:=n+1; END_PROGRAM"
    metrics = compute_honest_ast_metrics(sample_st)
    assert isinstance(metrics, dict)
    assert metrics["ast_statement_count"] > 0
    assert metrics["ast_variable_count"] > 0


# ----------------------------------------------------------------------------
# 5. H04: Silent Mocks Disguised as Live Passes
# ----------------------------------------------------------------------------
def test_h04_simulation_offline_mock_classification():
    """H04: Simulator must explicitly declare TESTED_MOCK [offline/DEV only]."""
    sim_py = HORNER_ROOT / "src" / "cscape" / "simulator.py"
    text = sim_py.read_text(encoding="utf-8")
    assert 'CLASSIFICATION = "TESTED_MOCK [offline/DEV only]"' in text
    assert 'VERIFICATION_CLASSIFICATION = "TESTED_MOCK [offline/DEV only]"' in text

    cap_file = HORNER_ROOT / "CAPABILITY_MATRIX.md"
    cap_text = cap_file.read_text(encoding="utf-8")
    assert "TESTED_MOCK [offline/DEV only]" in cap_text


# ----------------------------------------------------------------------------
# 6. H05: Global Allow Dialog Bypass Without Modal Inspection
# ----------------------------------------------------------------------------
def test_h05_modal_dialog_inspection():
    """H05: lifecycle.py must inspect #32770 dialogs and match allowed keywords."""
    lifecycle_py = HORNER_ROOT / "src" / "cscape" / "lifecycle.py"
    content = lifecycle_py.read_text(encoding="utf-8")
    assert "ALLOW_TEXT_KEYWORDS" in content
    assert "ALLOW_BUTTON_KEYWORDS" in content
    assert "#32770" in content
    assert "def find_allow_dialogs" in content
    assert "def handle_allow_dialogs" in content


# ----------------------------------------------------------------------------
# 7. H06: Straton K5 Files in Active Code Paths
# ----------------------------------------------------------------------------
def test_h06_straton_k5_quarantine():
    """H06: Legacy Straton K5 templates must remain quarantined with 0 active imports in src/."""
    quarantine_dir = HORNER_ROOT / "quarantine" / "straton_k5_legacy"
    assert quarantine_dir.exists()
    assert len(list(quarantine_dir.rglob("*"))) > 0

    src_dir = HORNER_ROOT / "src"
    for py_file in src_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        for line in content.splitlines():
            clean = line.strip()
            if clean.startswith("#"):
                continue
            assert not re.search(r"\bimport\s+straton\b", clean), f"Active Straton import in {py_file}"
            assert not re.search(r"\bfrom\s+straton\b", clean), f"Active Straton import in {py_file}"
            assert "quarantine.straton_k5_legacy" not in clean, f"Active quarantine import in {py_file}"


# ----------------------------------------------------------------------------
# 8. H07: Hardcoded Dead PIDs Treated as Permanent Passes
# ----------------------------------------------------------------------------
def test_h07_dead_pids_decoupled():
    """H07: Ephemeral PID tests must be recognized as historical milestones, not invariant passes."""
    cap_file = HORNER_ROOT / "CAPABILITY_MATRIX.md"
    text = cap_file.read_text(encoding="utf-8")
    assert "HISTORICAL MILESTONE / GATE-DEPENDENT" in text
    assert "Dismantling of \"379/379 Live Tests Passed\" False Success" in text


# ----------------------------------------------------------------------------
# 9. H08: Ladder Constructs Disguised as ST
# ----------------------------------------------------------------------------
def test_h08_ladder_forbidden_rejection():
    """H08: Ladder contacts, coils, rungs, and mnemonics must be rejected fail-closed."""
    samples = [
        ("---[ ]---", "bOut := ---[ bIn ]---;"),
        ("---[/]---", "bOut := ---[/ bIn ]---;"),
        ("---( )---", "---( bMotor )---;"),
        ("---(S)---", "---(S) bValve;"),
        ("---(R)---", "---(R) bValve;"),
        ("RUNG", "RUNG 1\nIF bRun THEN x:=1; END_IF;"),
        ("XIC(", "XIC(bStart) OTE(bRun);"),
    ]
    for sym, code in samples:
        assert len(IECValidator.check_ladder_artifacts(sym)) > 0
        with pytest.raises(LadderConstructRejectedError):
            STLadderInteropGuard.enforce_st_code(code)

    doc_file = HORNER_ROOT / "docs" / "st_to_ld_conversion_blocked.md"
    assert doc_file.exists()
    assert "BLOCKED_NATIVE" in doc_file.read_text(encoding="utf-8")


# ----------------------------------------------------------------------------
# 10. H09: Fake 100% or FINAL_REPORT Claims
# ----------------------------------------------------------------------------
def test_h09_fake_victory_prohibited():
    """H09: AGENTS.md must prohibit premature victory and FINAL_REPORT spam."""
    agents_md = HORNER_ROOT / "AGENTS.md"
    text = agents_md.read_text(encoding="utf-8")
    assert "Strict Invariant: NO Claim of G2+/G5 Done" in text
    assert "FINAL_REPORT.md" in text
    assert "spam" in text
    assert "Execution Watchdog Enforcement" in text


# ----------------------------------------------------------------------------
# 11. H10: Physical Hardware Port Access Without Lockout
# ----------------------------------------------------------------------------
def test_h10_hardware_port_lockout():
    """H10: COM1-256, CAN, USB, and JTAG ports must be unconditionally blocked."""
    policy = SafetyPolicy()
    for p in ["COM1", "COM3", "COM256", "CAN0", "can1", "USB1", "JTAG"]:
        assert policy.is_port_blocked(p)

    guard = CscapeSafetyGuard()
    with pytest.raises(Exception):
        guard.validate_hardware_connection(port="COM1")


# ----------------------------------------------------------------------------
# 12. H11: Companion Flasher Utilities Allowed
# ----------------------------------------------------------------------------
def test_h11_companion_flasher_lockout():
    """H11: Flashing utilities and Win32 download command IDs must be blocked."""
    policy = SafetyPolicy()
    for exe in ["PGMUpdateUtility.exe", "DfuSeCommand.exe", "STMFlashLoader.exe", "WinJTAG.exe"]:
        assert policy.is_executable_blocked(exe)

    for sw in ["/d", "/download", "/flash", "/burn", "/write-flash"]:
        assert policy.is_flag_blocked(sw)

    assert ID_CONTROLLER_DOWNLOAD == 32827
    assert ID_CONTROLLER_DOWNLOAD_ALT == 33149

    guard = CscapeSafetyGuard()
    with pytest.raises(Exception):
        guard.validate_cscape_download(command_id=32827)
    with pytest.raises(Exception):
        guard.validate_cscape_download(command_id=33149)


# ----------------------------------------------------------------------------
# 13. H12: Unsupervised Naked Cscape Launch Claiming Stability
# ----------------------------------------------------------------------------
def test_h12_naked_launch_crash_documented():
    """H12: Naked launch crash at 0x0051a4cd must be honestly documented vs supervisor stay-open."""
    diag_file = HORNER_ROOT / "artifacts" / "logs" / "cscape_crash_diagnosis.md"
    assert diag_file.exists()
    d_text = diag_file.read_text(encoding="utf-8")
    assert "0x0051a4cd" in d_text
    assert "GetDC" in d_text


# ----------------------------------------------------------------------------
# 14. H13: Status Contract Violations
# ----------------------------------------------------------------------------
def test_h13_strict_4_state_status_contract():
    """H13: All active checkpoints and MCP normalization must adhere strictly to 4-state contract."""
    # Tool normalization
    res_norm = normalize_tool_result({"success": True, "status": "custom"}, default_source="Test")
    assert res_norm["status"] in CANONICAL_STATUSES

    # Active checkpoints
    checkpoints_dir = HORNER_ROOT / "artifacts" / "checkpoints"
    assert checkpoints_dir.exists()

    active_count = 0
    for step_num in range(174, 190):
        for cp in checkpoints_dir.glob(f"step{step_num}_*.json"):
            active_count += 1
            data = json.loads(cp.read_text(encoding="utf-8"))
            assert data.get("status") in CANONICAL_STATUSES, f"Invalid status in {cp.name}: {data.get('status')}"

    assert active_count >= 50, f"Expected at least 50 active step checkpoints, got {active_count}"
