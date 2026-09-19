"""Negative and contract verification test suite for Phase C3 Offline/DEV contracts.

Verifies:
1. C3-N01: Compilation empty output window fails closed (COMPILATION_OUTPUT_EMPTY).
2. C3-N01b: Whitespace-only compile output fails closed (COMPILATION_OUTPUT_EMPTY).
3. C3-N01c: cscape_compile MCP tool fails closed on empty output (COMPILATION_OUTPUT_EMPTY).
4. C3-N02: Stale success tokens without compile activity are rejected (is_clean=False, FAILED).
5. C3-N02b: Bare success status without summary rejected (is_clean=False, FAILED).
6. C3-N03: Project with zero .st source files fails closed (NO_SOURCE_POUS).
7. C3-N03b: cscape_compile MCP tool fails closed on zero source POUs (NO_SOURCE_POUS).
8. C3-N03c: cscape_compile_project wrapper fails closed on zero source POUs (NO_SOURCE_POUS).
9. C3-N04: Gate missing PID fails closed (INCOMPLETE_GATE_DATA).
10. C3-N05: Gate missing HWND fails closed (INCOMPLETE_GATE_DATA).
11. C3-N06: Gate with PID <= 0 fails closed (INCOMPLETE_GATE_DATA).
12. C3-N07: Gate with HWND == 0 or empty fails closed (INCOMPLETE_GATE_DATA).
13. C3-N07b: get_gate_status sets ready_for_tests=False on incomplete fields.
14. C3-N08: Non-fatal compilation error dialog auto-Yes is strictly prohibited.
15. C3-N09: Foreign modal dialog fails closed without blind dismissal.
16. C3-N09b: cscape_compile fails closed on foreign modal dialog (FOREIGN_MODAL_DETECTED).
17. C3-N09c: cscape_compile fails closed on non-fatal error dialog (NON_FATAL_ERROR).
18. C3-N10: Modal classification contract matrix (CLEAN_RESULT, NON_FATAL_ERROR, FOREIGN_MODAL).
19. C3-N11: GUI compile output with stale token fails closed (STALE_OR_INVALID_BUILD_PROOF).
20. C3-N12: Simulation mode='VERIFIED_LIVE' strictly prohibited (ERR_VERIFIED_LIVE_PROHIBITED_ON_SIMULATION).
21. C3-N13: Ladder logic injection in simulation fails closed (ERR_LADDER_FORBIDDEN).
22. C3-N14: Malformed ST syntax in simulation fails closed (ST_SYNTAX_ERROR).
23. C3-N15: All simulator modules declare strict TESTED_MOCK [offline/DEV only] taxonomy.
24. C3-P01: Genuine clean compilation proof accepted (0 errors, 0 warnings + activity).
25. C3-P02: GUI compile with verified clean output succeeds.
26. C3-P03: Pure-software simulation returns explicit TESTED_MOCK [offline/DEV only] taxonomy.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.cscape.gate import (
    get_gate_status,
    assert_cscape_live,
    CscapeLivenessGateError,
)
from src.cscape.diagnostics import (
    CscapeLogParser,
    verify_clean_build,
)
from src.cscape.compilation import (
    CscapeCompiler,
    BuildStatus,
    classify_compilation_modal,
)
from src.mcp.tools import (
    cscape_simulate_pou,
    cscape_run_simulation,
    cscape_simulate_cycle,
    cscape_compile,
    cscape_compile_project,
    cscape_get_build_output,
    normalize_tool_result,
    ToolStatus,
)
from src.cscape.simulation import (
    simulate_pou_with_registers,
    CLASSIFICATION as CSCAPE_SIM_CLASSIFICATION,
    VERIFICATION_CLASSIFICATION as CSCAPE_SIM_VERIF_CLASS,
)
import src.cscape.simulator as cscape_simulator_mod
import src.cscape.simulation as cscape_simulation_mod
import src.iec.simulator as iec_simulator_mod
import src.simulation.simulator as sim_simulator_mod

SCRATCH_DIR = Path(r"C:\HornerAI\horner-cscape-mcp\scratch")


@pytest.fixture
def empty_project_dir():
    """Provides an empty project directory inside workspace scratch."""
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    p = SCRATCH_DIR / f"test_c3_empty_{uuid.uuid4().hex[:8]}"
    p.mkdir(parents=True, exist_ok=True)
    (p / "cscape_project.json").write_text("{}", encoding="utf-8")
    yield p
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)


class TestC3EmptyAndStaleCompilationContracts:
    """Negative tests for compilation output, stale tokens, and zero source files."""

    def test_c3_n01_empty_compile_output_fails_closed(self):
        """Mandate: Empty compilation output window must never become success."""
        compiler = CscapeCompiler()
        with patch.object(compiler, "_discover_live_cscape_hwnd", return_value=12345):
            with patch.object(compiler, "_attach_thread_to_window_desktop"):
                with patch.object(compiler, "scrape_output_window", return_value=("", [])):
                    with patch("win32gui.IsWindow", return_value=True):
                        with patch("win32gui.PostMessage", return_value=0):
                            with patch("time.sleep"):
                                res = compiler.trigger_cscape_gui_compile(cscape_hwnd=12345)

        assert res["success"] is False
        assert res["status"] == "failed"
        assert res["error_code"] == "COMPILATION_OUTPUT_EMPTY"
        assert res["error_count"] >= 1
        assert any("empty" in e.lower() for e in res["errors"])

    def test_c3_n01b_whitespace_only_compile_output_fails_closed(self):
        """Mandate: Whitespace-only compilation output window must never become success."""
        compiler = CscapeCompiler()
        with patch.object(compiler, "_discover_live_cscape_hwnd", return_value=12345):
            with patch.object(compiler, "_attach_thread_to_window_desktop"):
                with patch.object(compiler, "scrape_output_window", return_value=("   \r\n\t  \n", [])):
                    with patch("win32gui.IsWindow", return_value=True):
                        with patch("win32gui.PostMessage", return_value=0):
                            with patch("time.sleep"):
                                res = compiler.trigger_cscape_gui_compile(cscape_hwnd=12345)

        assert res["success"] is False
        assert res["status"] == "failed"
        assert res["error_code"] == "COMPILATION_OUTPUT_EMPTY"
        assert res["error_count"] >= 1

    def test_c3_n02_stale_success_token_without_compile_activity_rejected(self):
        """Mandate: Bare 0-error string without compilation activity must fail closed."""
        stale_tokens = [
            "0 errors, 0 warnings",
            "0 error(s), 0 warning(s)",
            "Errors: 0, Warnings: 0",
            "No errors detected",
        ]
        for token in stale_tokens:
            proof = CscapeLogParser.extract_clean_build_proof(token)
            assert proof.is_clean is False, f"Stale token '{token}' should not be clean"
            assert proof.status_text == "FAILED", f"Stale token '{token}' should be FAILED"

    def test_c3_n02b_bare_success_status_without_summary_rejected(self):
        """Mandate: Bare Build Result: SUCCESS without error counts must fail closed."""
        bare_status = "Build Result: SUCCESS"
        proof = verify_clean_build(bare_status)
        assert proof.is_clean is False
        assert proof.status_text == "FAILED"

    def test_c3_n03_zero_source_pous_compile_fails_closed(self, empty_project_dir):
        """Mandate: Compiling a project containing zero .st files must fail closed."""
        compiler = CscapeCompiler()
        res = compiler.compile_project(empty_project_dir)

        assert res.success is False
        assert res.status == BuildStatus.FAILED
        assert res.error_count >= 1
        assert any(d.error_code == "NO_SOURCE_POUS" for d in res.diagnostics)
        assert any("no structured text" in d.message.lower() for d in res.diagnostics)

    def test_c3_n11_gui_compile_with_stale_output_fails_closed(self):
        """Mandate: GUI compilation returning only bare stale token must fail closed."""
        compiler = CscapeCompiler()
        stale_text = "0 error(s), 0 warning(s)"
        with patch.object(compiler, "_discover_live_cscape_hwnd", return_value=12345):
            with patch.object(compiler, "_attach_thread_to_window_desktop"):
                with patch.object(compiler, "scrape_output_window", return_value=(stale_text, [])):
                    with patch("win32gui.IsWindow", return_value=True):
                        with patch("win32gui.PostMessage", return_value=0):
                            with patch("time.sleep"):
                                res = compiler.trigger_cscape_gui_compile(cscape_hwnd=12345)

        assert res["success"] is False
        assert res["status"] == "failed"
        assert res["error_code"] == "STALE_OR_INVALID_BUILD_PROOF"
        assert res["error_count"] >= 1

    def test_c3_n01c_mcp_tool_compile_empty_output_fails_closed(self):
        """Mandate: cscape_compile MCP tool fails closed on empty output."""
        with patch.object(CscapeCompiler, "_discover_live_cscape_hwnd", return_value=12345):
            with patch.object(CscapeCompiler, "_attach_thread_to_window_desktop"):
                with patch.object(CscapeCompiler, "scrape_output_window", return_value=("", [])):
                    with patch("win32gui.IsWindow", return_value=True):
                        with patch("win32gui.PostMessage", return_value=0):
                            with patch("time.sleep"):
                                res = cscape_compile(cscape_hwnd=12345)

        assert res["success"] is False
        assert res["status"] == "failed"
        assert res["error_code"] == "COMPILATION_OUTPUT_EMPTY"
        assert res["error_count"] >= 1

    def test_c3_n03b_mcp_tool_compile_zero_source_pous_fails_closed(self, empty_project_dir):
        """Mandate: cscape_compile MCP tool fails closed when compiling zero source POUs."""
        res = cscape_compile(project_path=str(empty_project_dir))
        assert res["success"] is False
        assert res["status"] == "failed"
        assert res["error_code"] == "NO_SOURCE_POUS"
        assert res["error_count"] >= 1

    def test_c3_n03c_mcp_compile_project_zero_source_pous_fails_closed(self, empty_project_dir):
        """Mandate: cscape_compile_project convenience wrapper fails closed on zero source POUs."""
        proj_name = empty_project_dir.name
        target_dir = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\projects") / proj_name
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "cscape_project.json").write_text("{}", encoding="utf-8")
        try:
            res = cscape_compile_project(project_name=proj_name)
            assert res["success"] is False
            assert res["status"] == "failed"
            assert res["error_code"] == "NO_SOURCE_POUS"
        finally:
            shutil.rmtree(target_dir, ignore_errors=True)

    def test_c3_n01d_compile_project_empty_name_fails_closed(self):
        """Mandate: cscape_compile_project with empty or whitespace name must fail closed."""
        for invalid_name in ["", "   ", "\t\n", None]:
            res = cscape_compile_project(project_name=invalid_name)
            assert res["success"] is False
            assert res["compile_successful"] is False
            assert res["status"] == "failed"
            assert res["error_code"] == "INVALID_PROJECT_NAME"
            assert res["error_count"] >= 1

    def test_c3_n01e_compile_empty_or_whitespace_path_fails_closed(self):
        """Mandate: cscape_compile with empty or whitespace-only project_path must fail closed."""
        for invalid_path in ["", "   ", "\t  \n"]:
            res = cscape_compile(project_path=invalid_path)
            assert res["success"] is False
            assert res["status"] == "failed"
            assert res["error_code"] == "INVALID_PROJECT_PATH"
            assert res["error_count"] >= 1


class TestC3GateDataValidationContracts:
    """Negative tests for gate validation without PID/HWND or non-positive handles."""

    def test_c3_n04_gate_without_pid_fails_closed(self):
        """Mandate: Gate data missing PID must fail closed."""
        gate_missing_pid = {
            "ready_for_tests": True,
            "pid": None,
            "hwnd": 12345,
            "heartbeat_utc": "2026-09-06T12:00:00Z",
        }
        with patch("src.cscape.gate.GATE_PATHS", []):
            with patch("src.cscape.gate.get_gate_status", return_value=dict(gate_missing_pid)):
                with patch("win32gui.IsWindow", return_value=True), patch("win32gui.GetWindowText", return_value="Cscape - TankLevelClosedLoop.csp"):
                    with pytest.raises(CscapeLivenessGateError) as exc_info:
                        assert_cscape_live()
                    assert "INCOMPLETE_GATE_DATA" in str(exc_info.value) or "valid PID" in str(exc_info.value)

    def test_c3_n05_gate_without_hwnd_fails_closed(self):
        """Mandate: Gate data missing HWND must fail closed."""
        gate_missing_hwnd = {
            "ready_for_tests": True,
            "pid": 9999,
            "hwnd": None,
            "heartbeat_utc": "2026-09-06T12:00:00Z",
        }
        with patch("src.cscape.gate.GATE_PATHS", []):
            with patch("src.cscape.gate.get_gate_status", return_value=dict(gate_missing_hwnd)):
                with patch("psutil.pid_exists", return_value=True), patch("psutil.Process") as mock_proc:
                    mock_proc.return_value.name.return_value = "cscape.exe"
                    with pytest.raises(CscapeLivenessGateError) as exc_info:
                        assert_cscape_live()
                    assert "INCOMPLETE_GATE_DATA" in str(exc_info.value) or "valid HWND" in str(exc_info.value)

    def test_c3_n06_gate_pid_zero_or_negative_fails_closed(self):
        """Mandate: Gate data with PID <= 0 must fail closed."""
        for invalid_pid in [0, -1, -999]:
            gate = {
                "ready_for_tests": True,
                "pid": invalid_pid,
                "hwnd": 12345,
                "heartbeat_utc": "2026-09-06T12:00:00Z",
            }
            with patch("src.cscape.gate.GATE_PATHS", []):
                with patch("src.cscape.gate.get_gate_status", return_value=dict(gate)):
                    with pytest.raises(CscapeLivenessGateError) as exc_info:
                        assert_cscape_live()
                    assert "INCOMPLETE_GATE_DATA" in str(exc_info.value) or "valid PID" in str(exc_info.value)

    def test_c3_n07_gate_hwnd_zero_or_empty_fails_closed(self):
        """Mandate: Gate data with HWND 0, '0', or empty must fail closed."""
        for invalid_hwnd in [0, "0", "", None]:
            gate = {
                "ready_for_tests": True,
                "pid": 9999,
                "hwnd": invalid_hwnd,
                "heartbeat_utc": "2026-09-06T12:00:00Z",
            }
            with patch("src.cscape.gate.GATE_PATHS", []):
                with patch("src.cscape.gate.get_gate_status", return_value=dict(gate)):
                    with patch("psutil.pid_exists", return_value=True), patch("psutil.Process") as mock_proc:
                        mock_proc.return_value.name.return_value = "cscape.exe"
                        with pytest.raises(CscapeLivenessGateError) as exc_info:
                            assert_cscape_live()
                        assert "INCOMPLETE_GATE_DATA" in str(exc_info.value) or "valid HWND" in str(exc_info.value)

    def test_c3_n07b_get_gate_status_enforces_ready_for_tests_false_on_missing_fields(self, tmp_path):
        """Mandate: get_gate_status sets ready_for_tests=False if file has missing PID or HWND."""
        incomplete_file = tmp_path / "incomplete_gate.json"
        import json
        incomplete_file.write_text(json.dumps({
            "ready_for_tests": True,
            "pid": None,
            "hwnd": None,
            "heartbeat_utc": "2026-09-06T12:00:00Z"
        }), encoding="utf-8")

        with patch("src.cscape.gate.GATE_PATHS", [incomplete_file]):
            status = get_gate_status()
            assert status["ready_for_tests"] is False
            assert status["status"] == "inconclusive"
            assert status["error_code"] == "INCOMPLETE_GATE_DATA"

    def test_c3_n06b_gate_pid_boolean_fails_closed(self, tmp_path):
        """Mandate: Gate data with boolean PID (True/False) must fail closed."""
        import json
        for b_pid in [True, False]:
            gate_file = tmp_path / f"gate_b_pid_{b_pid}.json"
            gate_file.write_text(json.dumps({
                "ready_for_tests": True,
                "pid": b_pid,
                "hwnd": 12345,
                "heartbeat_utc": "2026-09-06T12:00:00Z"
            }), encoding="utf-8")

            with patch("src.cscape.gate.GATE_PATHS", [gate_file]):
                status = get_gate_status()
                assert status["ready_for_tests"] is False
                assert status["status"] == "inconclusive"
                assert status["error_code"] == "INCOMPLETE_GATE_DATA"

                with pytest.raises(CscapeLivenessGateError) as exc_info:
                    assert_cscape_live()
                assert "INCOMPLETE_GATE_DATA" in str(exc_info.value)

    def test_c3_n07c_gate_hwnd_boolean_fails_closed(self, tmp_path):
        """Mandate: Gate data with boolean HWND (True/False) must fail closed."""
        import json
        for b_hwnd in [True, False]:
            gate_file = tmp_path / f"gate_b_hwnd_{b_hwnd}.json"
            gate_file.write_text(json.dumps({
                "ready_for_tests": True,
                "pid": 9999,
                "hwnd": b_hwnd,
                "heartbeat_utc": "2026-09-06T12:00:00Z"
            }), encoding="utf-8")

            with patch("src.cscape.gate.GATE_PATHS", [gate_file]):
                status = get_gate_status()
                assert status["ready_for_tests"] is False
                assert status["status"] == "inconclusive"
                assert status["error_code"] == "INCOMPLETE_GATE_DATA"

                with pytest.raises(CscapeLivenessGateError) as exc_info:
                    assert_cscape_live()
                assert "INCOMPLETE_GATE_DATA" in str(exc_info.value)

    def test_c3_n07d_gate_hwnd_unparseable_string_fails_closed(self, tmp_path):
        """Mandate: Gate data with unparseable or non-positive HWND string must fail closed."""
        import json
        for invalid_hwnd in ["0xNOT_A_HEX", "invalid_handle", "-12345"]:
            gate_file = tmp_path / f"gate_unparseable_{abs(hash(invalid_hwnd))}.json"
            gate_file.write_text(json.dumps({
                "ready_for_tests": True,
                "pid": 9999,
                "hwnd": invalid_hwnd,
                "heartbeat_utc": "2026-09-06T12:00:00Z"
            }), encoding="utf-8")

            with patch("src.cscape.gate.GATE_PATHS", [gate_file]):
                status = get_gate_status()
                assert status["ready_for_tests"] is False
                assert status["status"] == "inconclusive"
                assert status["error_code"] == "INCOMPLETE_GATE_DATA"

                with pytest.raises(CscapeLivenessGateError) as exc_info:
                    assert_cscape_live()
                assert "INCOMPLETE_GATE_DATA" in str(exc_info.value)

    def test_c3_n07e_gate_corrupt_non_dict_json_fails_closed(self, tmp_path):
        """Mandate: Gate file containing non-dict JSON (list, int, str) must fail closed."""
        for corrupt_content in ["[1, 2, 3]", "12345", '"just_a_string"', "true"]:
            gate_file = tmp_path / "corrupt_gate.json"
            gate_file.write_text(corrupt_content, encoding="utf-8")

            with patch("src.cscape.gate.GATE_PATHS", [gate_file]):
                status = get_gate_status()
                assert status["ready_for_tests"] is False
                assert status["status"] == "inconclusive"
                assert status["error_code"] == "GATE_FILE_NOT_FOUND"

                with pytest.raises(CscapeLivenessGateError) as exc_info:
                    assert_cscape_live()
                assert "GATE_FILE_NOT_FOUND" in str(exc_info.value)


class TestC3ModalInterceptionContracts:
    """Negative and contract tests for modal dialog interception and auto-Yes prohibition."""

    def test_c3_n08_non_fatal_dialog_auto_yes_prohibited(self):
        """Mandate: Non-fatal compilation error dialogs must never be auto-dismissed with Yes."""
        classification = classify_compilation_modal("Cscape", ["Non-fatal errors detected in project. Continue?"])
        assert classification == "NON_FATAL_ERROR"

        classification2 = classify_compilation_modal("Cscape Compiler - Nonfatal", ["Warning details"])
        assert classification2 == "NON_FATAL_ERROR"

    def test_c3_n09_foreign_modal_fails_closed_no_blind_dismissal(self):
        """Mandate: Unrecognized or foreign modal dialogs must fail closed without blind dismissal."""
        foreign_cases = [
            ("Save Project As", ["Save file to disk?"]),
            ("Hardware Configuration Error", ["Controller mismatch"]),
            ("Cscape - Straton", ["Target runtime unreachable"]),
            ("Update Available", ["New version available"]),
            ("Windows Security", ["Firewall alert"]),
        ]
        for title, texts in foreign_cases:
            cls = classify_compilation_modal(title, texts)
            assert cls == "FOREIGN_MODAL", f"Modal '{title}' should be classified as FOREIGN_MODAL"

    def test_c3_n10_classify_compilation_modal_contract(self):
        """Mandate: Modal classification strictly identifies CLEAN_RESULT, NON_FATAL_ERROR, and FOREIGN_MODAL."""
        assert classify_compilation_modal("Cscape", ["No error detected."]) == "CLEAN_RESULT"
        assert classify_compilation_modal("Compilation succeeded", ["0 error(s), 0 warning(s)"]) == "CLEAN_RESULT"
        assert classify_compilation_modal("Cscape", ["non-fatal error occurred", "Yes", "No"]) == "NON_FATAL_ERROR"
        assert classify_compilation_modal("Cscape", ["Unknown prompt", "Cancel"]) == "FOREIGN_MODAL"

    def test_c3_n09b_mcp_tool_compile_foreign_modal_fails_closed(self):
        """Mandate: cscape_compile fails closed with FOREIGN_MODAL_DETECTED when a foreign modal is encountered."""
        with patch.object(CscapeCompiler, "_discover_live_cscape_hwnd", return_value=12345):
            with patch.object(
                CscapeCompiler,
                "_trigger_cscape_gui_compile_internal",
                side_effect=RuntimeError("FAIL-CLOSED: Foreign modal dialog detected during compilation ('Update Available': New version). Auto-dismissal is prohibited."),
            ):
                res = cscape_compile(cscape_hwnd=12345)

        assert res["success"] is False
        assert res["status"] == "failed"
        assert res["error_code"] == "FOREIGN_MODAL_DETECTED"
        assert res["error_count"] >= 1
        assert any("foreign modal" in e.lower() for e in res["errors"])

    def test_c3_n09c_mcp_tool_compile_non_fatal_dialog_fails_closed(self):
        """Mandate: cscape_compile fails closed with NON_FATAL_ERROR when non-fatal error dialog appears."""
        with patch.object(CscapeCompiler, "_discover_live_cscape_hwnd", return_value=12345):
            with patch.object(
                CscapeCompiler,
                "_trigger_cscape_gui_compile_internal",
                side_effect=RuntimeError("FAIL-CLOSED: Non-fatal error dialog detected during compilation. Auto-Yes dismissal is strictly prohibited."),
            ):
                res = cscape_compile(cscape_hwnd=12345)

        assert res["success"] is False
        assert res["status"] == "failed"
        assert res["error_code"] == "NON_FATAL_ERROR"
        assert res["error_count"] >= 1
        assert any("non-fatal error dialog" in e.lower() for e in res["errors"])

    def test_c3_n08b_non_fatal_dialog_variants_classified_and_rejected(self):
        """Mandate: Various non-fatal error dialog texts must all be classified as NON_FATAL_ERROR and rejected."""
        variants = [
            ("Build Warning", ["Errors occurred during compilation. Proceed?"]),
            ("Cscape", ["Do you wish to continue?"]),
            ("Compiler", ["Continue build despite errors?"]),
            ("Notice", ["Proceed with errors?"]),
            ("Compilation Error", ["Errors found in code"]),
            (None, ["errors occurred"]),
            ("Title", [123, None, "do you wish to continue"]),
            ("Nonfatal Notice", ["Some details"]),
            ("Build", ["Continue build"]),
        ]
        for title, texts in variants:
            assert classify_compilation_modal(title, texts) == "NON_FATAL_ERROR"

    def test_c3_n08c_allow_dialogs_never_clicks_non_fatal_dialog(self):
        """Mandate: find_allow_dialogs strictly excludes non-fatal compilation error dialogs."""
        from src.cscape.lifecycle import CscapeLifecycleManager, WindowInfo, ChildControlInfo

        mgr = CscapeLifecycleManager()
        mgr.pid = 1234
        mock_win = WindowInfo(
            hwnd=54321,
            pid=1234,
            class_name="#32770",
            title="Non-fatal Error Detected",
            visible=True,
        )
        mock_child = ChildControlInfo(
            hwnd=54322,
            control_id=1,
            class_name="Button",
            text="Yes",
            visible=True,
            enabled=True,
        )

        with patch("src.cscape.lifecycle.is_windows", return_value=True):
            with patch.object(mgr, "_enum_process_windows", return_value=[mock_win]):
                with patch.object(mgr, "_get_allowed_pids", return_value={1234}):
                    with patch.object(mgr, "_enum_all_child_controls", return_value=[mock_child]):
                        dialogs = mgr.find_allow_dialogs(check_system_windows=False)
                        assert len(dialogs) == 0

        # Test dialog where title is generic but combined_text contains 'errors occurred'
        mock_win_generic = WindowInfo(
            hwnd=54323,
            pid=1234,
            class_name="#32770",
            title="Cscape",
            visible=True,
        )
        mock_child_err = ChildControlInfo(
            hwnd=54324,
            control_id=101,
            class_name="Static",
            text="Errors occurred. Do you wish to continue?",
            visible=True,
            enabled=True,
        )
        with patch("src.cscape.lifecycle.is_windows", return_value=True):
            with patch.object(mgr, "_enum_process_windows", return_value=[mock_win_generic]):
                with patch.object(mgr, "_get_allowed_pids", return_value={1234}):
                    with patch.object(mgr, "_enum_all_child_controls", return_value=[mock_child_err, mock_child]):
                        dialogs = mgr.find_allow_dialogs(check_system_windows=False)
                        assert len(dialogs) == 0

        # Test dialog where text contains 'build error'
        mock_child_build_err = ChildControlInfo(
            hwnd=54325,
            control_id=102,
            class_name="Static",
            text="Build error encountered during compile pass.",
            visible=True,
            enabled=True,
        )
        with patch("src.cscape.lifecycle.is_windows", return_value=True):
            with patch.object(mgr, "_enum_process_windows", return_value=[mock_win_generic]):
                with patch.object(mgr, "_get_allowed_pids", return_value={1234}):
                    with patch.object(mgr, "_enum_all_child_controls", return_value=[mock_child_build_err, mock_child]):
                        dialogs = mgr.find_allow_dialogs(check_system_windows=False)
                        assert len(dialogs) == 0

    def test_c3_n09d_foreign_modal_unknown_text_fails_closed(self):
        """Mandate: Foreign modal with unknown text is classified as FOREIGN_MODAL and fails closed."""
        res = classify_compilation_modal("Unknown Modal", ["Unexpected content"])
        assert res == "FOREIGN_MODAL"

        with patch.object(CscapeCompiler, "_discover_live_cscape_hwnd", return_value=12345):
            with patch.object(
                CscapeCompiler,
                "_trigger_cscape_gui_compile_internal",
                side_effect=RuntimeError("FAIL-CLOSED: Foreign modal dialog detected during compilation ('Unknown Modal': Unexpected content). Auto-dismissal is prohibited."),
            ):
                comp_res = cscape_compile(cscape_hwnd=12345)

        assert comp_res["success"] is False
        assert comp_res["status"] == "failed"
        assert comp_res["error_code"] == "FOREIGN_MODAL_DETECTED"
        assert comp_res["error_count"] >= 1


class TestC3PositiveProofContracts:
    """Positive baseline contracts ensuring genuine clean builds and verified outputs pass."""

    def test_c3_p01_genuine_clean_compile_proof_accepted(self):
        """Mandate: Genuine compilation log with compile activity and 0 errors/warnings is clean."""
        log = """=== Horner Cscape 10.2 Compile Pass: TankLevelClosedLoop ===
Clean Build: True
Compiling POU: Logic (300 bytes)...
  POU 'Logic' parsed and validated cleanly.
----------------------------------------------------------------
Build Result: SUCCESS
Errors: 0, Warnings: 0
Duration: 0.015s
Hardware Lockout: ENFORCED (Zero PLC communication / No download)
"""
        proof = verify_clean_build(log)
        assert proof.is_clean is True
        assert proof.status_text == "SUCCESS"
        assert proof.error_count == 0
        assert proof.warning_count == 0

    def test_c3_p02_gui_compile_with_clean_output_succeeds(self):
        """Mandate: GUI compile with genuine clean output succeeds."""
        compiler = CscapeCompiler()
        clean_text = "Compilation succeeded.\r\n0 error(s), 0 warning(s)"
        with patch.object(compiler, "_discover_live_cscape_hwnd", return_value=12345):
            with patch.object(compiler, "_attach_thread_to_window_desktop"):
                with patch.object(compiler, "scrape_output_window", return_value=(clean_text, [])):
                    with patch("win32gui.IsWindow", return_value=True):
                        with patch("win32gui.PostMessage", return_value=0):
                            with patch("time.sleep"):
                                res = compiler.trigger_cscape_gui_compile(cscape_hwnd=12345)

        assert res["success"] is True
        assert res["status"] == "success"
        assert res["error_count"] == 0
        assert res["warning_count"] == 0


class TestC3SimulationMockContracts:
    """Negative and contract tests for pure-software simulation and mock taxonomy (R03/H04)."""

    def test_c3_n12_simulation_verified_live_prohibited_fails_closed(self):
        """Mandate: Requesting or claiming VERIFIED_LIVE on simulation must fail closed."""
        code = "PROGRAM Simple\nVAR\n  x : INT := 1;\nEND_VAR\n  x := x + 1;\nEND_PROGRAM"
        for mode in ["VERIFIED_LIVE", "LIVE", "verified_live"]:
            res_pou = cscape_simulate_pou(code=code, inputs={}, steps=1, mode=mode)
            assert res_pou["success"] is False
            assert res_pou["status"] == "failed"
            assert res_pou["error_code"] == "ERR_VERIFIED_LIVE_PROHIBITED_ON_SIMULATION"
            assert res_pou["classification"] == "TESTED_MOCK [offline/DEV only]"
            assert res_pou["verification_classification"] == "TESTED_MOCK [offline/DEV only]"

            res_run = cscape_run_simulation(steps=1, mode=mode)
            assert res_run["success"] is False
            assert res_run["status"] == "failed"
            assert res_run["error_code"] == "ERR_VERIFIED_LIVE_PROHIBITED_ON_SIMULATION"
            assert res_run["classification"] == "TESTED_MOCK [offline/DEV only]"
            assert res_run["verification_classification"] == "TESTED_MOCK [offline/DEV only]"

            res_cycle = cscape_simulate_cycle(mode=mode)
            assert res_cycle["success"] is False
            assert res_cycle["status"] == "failed"
            assert res_cycle["error_code"] == "ERR_VERIFIED_LIVE_PROHIBITED_ON_SIMULATION"
            assert res_cycle["classification"] == "TESTED_MOCK [offline/DEV only]"
            assert res_cycle["verification_classification"] == "TESTED_MOCK [offline/DEV only]"

    def test_c3_n13_simulation_ladder_injection_fails_closed(self):
        """Mandate: Injecting ladder constructs into simulation POUs must fail closed."""
        ladder_snippets = [
            "PROGRAM Ladder1\nVAR\n  x : BOOL;\nEND_VAR\n  ---( )---\nEND_PROGRAM",
            "PROGRAM Ladder2\nVAR\n  x : BOOL;\nEND_VAR\n  ---[ ]---\nEND_PROGRAM",
            "PROGRAM Ladder3\nVAR\n  x : BOOL;\nEND_VAR\n  XIC(x);\nEND_PROGRAM",
        ]
        for snippet in ladder_snippets:
            res = cscape_simulate_pou(code=snippet, inputs={}, steps=1)
            assert res["success"] is False
            assert res["status"] == "failed"
            assert res["error_code"] == "ERR_LADDER_FORBIDDEN"
            assert res["classification"] == "TESTED_MOCK [offline/DEV only]"

            res_run = cscape_run_simulation(steps=1, st_code=snippet)
            assert res_run["success"] is False
            assert res_run["status"] == "failed"
            assert res_run["error_code"] == "ERR_LADDER_FORBIDDEN"
            assert res_run["classification"] == "TESTED_MOCK [offline/DEV only]"

            with pytest.raises(ValueError) as exc_info:
                simulate_pou_with_registers(st_code=snippet, inputs={}, steps=1)
            assert "ERR_LADDER_FORBIDDEN" in str(exc_info.value)

    def test_c3_n14_simulation_syntax_error_fails_closed(self):
        """Mandate: Malformed ST syntax in simulation must fail closed."""
        malformed_snippets = [
            "PROGRAM Broken\nVAR\n  x : INT;\nEND_VAR\n  IF THEN END_PROGRAM",
            "PROGRAM Unclosed\nVAR\n  x : INT;\nEND_VAR\n  x := 1;",
        ]
        for snippet in malformed_snippets:
            res = cscape_simulate_pou(code=snippet, inputs={}, steps=1)
            assert res["success"] is False
            assert res["status"] == "failed"
            assert res["error_code"] in ("ST_SYNTAX_ERROR", "SIMULATE_POU_ERROR")
            assert res["classification"] == "TESTED_MOCK [offline/DEV only]"

            with pytest.raises(ValueError) as exc_info:
                simulate_pou_with_registers(st_code=snippet, inputs={}, steps=1)
            assert "ST_SYNTAX_ERROR" in str(exc_info.value)

    def test_c3_n15_all_simulator_modules_declare_tested_mock_offline_taxonomy(self):
        """Mandate: All simulator modules must explicitly declare TESTED_MOCK [offline/DEV only] taxonomy."""
        expected = "TESTED_MOCK [offline/DEV only]"
        modules = [
            cscape_simulator_mod,
            cscape_simulation_mod,
            iec_simulator_mod,
            sim_simulator_mod,
        ]
        for mod in modules:
            assert getattr(mod, "CLASSIFICATION", None) == expected, f"{mod.__name__} missing CLASSIFICATION"
            assert getattr(mod, "VERIFICATION_CLASSIFICATION", None) == expected, f"{mod.__name__} missing VERIFICATION_CLASSIFICATION"

    def test_c3_p03_simulation_explicit_mock_taxonomy_returned(self):
        """Mandate: Valid simulation execution returns explicit TESTED_MOCK [offline/DEV only] taxonomy."""
        code = """PROGRAM ValidSim
VAR
  raw_level : INT := 100;
  scaled_level : INT := 0;
END_VAR
  scaled_level := raw_level * 2;
END_PROGRAM"""
        expected = "TESTED_MOCK [offline/DEV only]"

        # 1. cscape_simulate_pou
        res = cscape_simulate_pou(code=code, inputs={"raw_level": 250}, steps=2)
        assert res["success"] is True
        assert res["status"] == "success"
        assert res["classification"] == expected
        assert res["verification_classification"] == expected
        assert res["final_state"].get("scaled_level") == 500

        # 2. simulate_pou_with_registers
        reg_res = simulate_pou_with_registers(st_code=code, inputs={"raw_level": 150}, steps=2)
        assert reg_res["success"] is True
        assert reg_res["classification"] == expected
        assert reg_res["verification_classification"] == expected
        assert reg_res["final_variables"].get("scaled_level") == 300

        # 3. cscape_run_simulation with st_code
        run_res = cscape_run_simulation(steps=2, st_code=code, inputs={"raw_level": 50})
        assert run_res["success"] is True
        assert run_res["status"] == "success"
        assert run_res["classification"] == expected
        assert run_res["verification_classification"] == expected

        # 4. cscape_simulate_cycle
        cycle_res = cscape_simulate_cycle(dt_ms=10.0)
        assert cycle_res["success"] is True
        assert cycle_res["status"] == "success"
        assert cycle_res["classification"] == expected
        assert cycle_res["verification_classification"] == expected


class TestC3ExtendedNegativeContracts:
    """Extended negative contract tests for C3 offline hardening."""

    def test_c3_n16_plural_warnings_contract_normalization(self):
        """Mandate: Status 'WARNINGS' must normalize safely to inconclusive without INVALID_RESULT_CONTRACT."""
        assert ToolStatus("warnings") == "inconclusive"
        assert ToolStatus("warning") == "inconclusive"
        assert ToolStatus("warn") == "inconclusive"

        res = normalize_tool_result(
            {
                "success": False,
                "status": "WARNINGS",
                "warnings": ["Warning: variable 'w' is declared but never read"],
                "diagnostics": [{"level": "WARNING", "message": "variable 'w' unused"}],
            },
            default_source="TestCompile",
            default_error_code="TEST_ERROR",
        )
        assert res["success"] is False
        assert res["status"] == "inconclusive"
        assert res.get("error_code") != "INVALID_RESULT_CONTRACT"
        assert len(res["warnings"]) == 1

    def test_c3_n17_cscape_compile_project_root_error_code_present(self, monkeypatch):
        """Mandate: cscape_compile_project failure returns top-level error_code."""
        # 1. Non-existent project
        missing_p = "non_existent_project_999"
        res_missing = cscape_compile_project(missing_p)
        assert res_missing["success"] is False
        assert res_missing["status"] == "failed"
        assert res_missing["error_code"] == "PROJECT_NOT_FOUND"

        # 2. Live GUI dead failure
        monkeypatch.setattr(
            "src.cscape.gate.assert_cscape_live",
            MagicMock(side_effect=CscapeLivenessGateError("FAIL-CLOSED: Gate offline")),
        )
        res_dead = cscape_compile_project("TankLevelClosedLoop", require_live_gui=True)
        assert res_dead["success"] is False
        assert res_dead["status"] in ("failed", "error")
        assert res_dead["error_code"] == "GUI_DEAD_FAIL_CLOSED"

    def test_c3_n18_file_path_as_project_dir_fails_closed(self, tmp_path):
        """Mandate: Passing a file path as project_dir must fail closed without NotADirectoryError."""
        dummy_file = tmp_path / "dummy_project.csp"
        dummy_file.write_text("not a directory", encoding="utf-8")

        res = cscape_compile(project_path=str(dummy_file))
        assert res["success"] is False
        assert res["status"] == "failed"
        assert res["error_code"] == "INVALID_PROJECT_PATH"
        assert "not a directory" in res["message"].lower()

    def test_c3_n19_invalid_timeouts_handled(self):
        """Mandate: Invalid, non-positive, or non-numeric timeout values fail closed."""
        for bad_timeout in [-10.0, 0, "invalid_num"]:
            res = cscape_compile(timeout_seconds=bad_timeout)
            assert res["success"] is False
            assert res["status"] == "failed"
            assert res["error_code"] == "INVALID_TIMEOUT_VALUE"

    def test_c3_n20_modal_classification_clean_summary_variants(self):
        """Mandate: Clean summary variants correctly classify as CLEAN_RESULT, while unknowns remain FOREIGN_MODAL."""
        clean_cases = [
            ("Cscape", ["0 error(s), 0 warning(s)"]),
            ("Cscape", ["0 errors, 0 warnings"]),
            ("Cscape", ["Compilation succeeded"]),
            ("Cscape", ["Build succeeded"]),
            ("Cscape", ["No errors detected in project"]),
        ]
        for title, texts in clean_cases:
            cls_name = classify_compilation_modal(title, texts)
            assert cls_name == "CLEAN_RESULT", f"Failed for {title} {texts}"

        foreign_cases = [
            ("Cscape", ["Fatal Exception: Out of memory"]),
            ("Windows Security", ["Allow access to network?"]),
            ("Cscape Tip", ["Did you know?"]),
        ]
        for title, texts in foreign_cases:
            cls_name = classify_compilation_modal(title, texts)
            assert cls_name == "FOREIGN_MODAL", f"Failed for {title} {texts}"

    def test_c3_n21_zero_source_pous_empty_list_contract(self, empty_project_dir):
        """Mandate: Projects with zero source POUs must return pous_compiled == [] without synthetic 'Main'."""
        res = cscape_compile_project(str(empty_project_dir))
        assert res["success"] is False
        assert res["status"] == "failed"
        assert res["error_code"] == "NO_SOURCE_POUS"
        assert res["pous_compiled"] == []

    def test_c3_n22_get_build_output_empty_log_fails_closed(self, empty_project_dir):
        """Mandate: cscape_get_build_output on empty or missing log fails closed."""
        res = cscape_get_build_output(project_path=str(empty_project_dir))
        assert res["success"] is False
        assert res["status"] == "failed"
        assert res["error_code"] == "BUILD_LOG_EMPTY"
        assert res["build_successful"] is False

    def test_c3_n23_log_parser_none_or_corrupt_input_fails_closed(self):
        """Mandate: CscapeLogParser safely handles None, non-string, and corrupt ANSI inputs fail-closed."""
        assert CscapeLogParser.parse_log(None) == []
        assert CscapeLogParser.parse_log(12345) == []

        proof_none = CscapeLogParser.extract_clean_build_proof(None)
        assert proof_none.is_clean is False
        assert proof_none.status_text == "FAILED"

        corrupt_input = "\x00\x01\x1b[31mANSI_ESC_CORRUPT\x1b[0m\xff\xfe"
        proof_corrupt = CscapeLogParser.extract_clean_build_proof(corrupt_input)
        assert proof_corrupt.is_clean is False
        assert proof_corrupt.status_text == "FAILED"

    def test_c3_n24_iec_simulator_ladder_and_syntax_prevalidation_fails_closed(self):
        """Mandate: src.iec.simulator.STSimulator pre-validates ST code and rejects ladder or syntax errors."""
        from src.iec.simulator import STSimulator as IecSTSimulator

        # 1. Ladder injection
        ladder_code = """PROGRAM LadderTest
VAR
  x : BOOL;
END_VAR
  ---( )---
END_PROGRAM"""
        res_ladder = IecSTSimulator.simulate(ladder_code, inputs={}, steps=1)
        assert res_ladder["success"] is False
        assert res_ladder["status"] == "failed"
        assert res_ladder["error_code"] == "ERR_LADDER_FORBIDDEN"
        assert res_ladder["steps_executed"] == 0

        # 2. Syntax error
        broken_code = """PROGRAM SyntaxTest
VAR
  x : INT;
END_VAR
  IF THEN END_PROGRAM"""
        res_syntax = IecSTSimulator.simulate(broken_code, inputs={}, steps=1)
        assert res_syntax["success"] is False
        assert res_syntax["status"] == "failed"
        assert res_syntax["error_code"] == "ST_SYNTAX_ERROR"
        assert res_syntax["steps_executed"] == 0


