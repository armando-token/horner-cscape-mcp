"""Focused Negative Test Suite for Phase P1 (Plan v3).

Verifies the dismantling of false successes across the minimal public path:
1. A01: Project Creation - Enforces offline staging mode; prohibits fabricating binary .csp projects.
2. A02: ST POU Insertion - Separates offline staging from native mutation; prohibits self-referential
   verification by reading back the same source file on disk; rejects ladder logic fail-closed.
3. A03: Live Compilation - Deactivated in offline public path (LIVE_GUI_COMPILATION_DEACTIVATED).
4. A04: Live Build Scraper - Deactivated in offline public path (LIVE_BUILD_SCRAPER_DEACTIVATED).
5. A08: Live Simulation - Hardware connection deactivated/blocked; emulated provenance enforced.
6. A09: PLC Download - Unconditional fail-closed lockout on physical ports and download commands.
7. P2 Adapter: Minimal adapter interface verified with strict P1 boundary enforcement (no P2 execution).
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from src.mcp.tools import (
    cscape_new_iec_project,
    cscape_create_project,
    cscape_insert_st,
    cscape_add_st_pou,
    cscape_compile,
    cscape_get_build_output,
    cscape_run_simulation,
)
from src.cscape.st_inserter import StructuredTextInserter, STVerificationResult
from src.cscape.st_ld_interop import LadderConstructRejectedError, STLadderInteropGuard
from src.cscape.native_adapter import CscapeNativeAdapter, OfflineStagingResult
from src.cscape.compiler import (
    ID_PROGRAM_DOWNLOAD,
    ID_CONTROLLER_DOWNLOAD,
    ID_PROGRAM_ERRORCHECK,
    CscapeCompiler,
)
from src.security.exceptions import HardwareLockoutError, UnauthorizedDownloadError, SecurityError
from src.security.guard import SafetyGuard


# =============================================================================
# 1. A01: Project Creation - No Binary Fabrication Offline
# =============================================================================

def test_a01_offline_creation_does_not_fabricate_binary_csp(tmp_path: Path):
    """A01: Offline project creation must prepare staging directories and manifest,
    WITHOUT copying template files or fabricating fake binary .csp files."""
    proj_name = "OfflinePrepProject"
    res = cscape_new_iec_project(
        project_name=proj_name,
        target_dir=str(tmp_path),
        controller_model="XL4",
        live_gui=False,
        require_native_binary=False,
    )

    assert res["success"] is True
    assert res["status"] == "success"
    assert res["storage_mode"] == "staging"
    assert res["is_staged"] is True
    assert res["is_native_persisted"] is False
    assert res["has_native_binary"] is False
    assert res["csp_created"] is False
    assert res["project_file"] is None

    proj_dir = tmp_path / proj_name
    csp_file = proj_dir / f"{proj_name}.csp"
    manifest_file = proj_dir / "cscape_project.json"

    # Invariant: .csp binary container must NOT be fabricated offline
    assert not csp_file.exists(), (
        f"Fabricated binary project '{csp_file}' must NOT exist in offline staging mode."
    )
    # Manifest must exist and record staging mode
    assert manifest_file.exists()
    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest_data.get("storage_mode") == "staging"
    assert manifest_data.get("has_native_binary") is False
    assert manifest_data.get("native_mutation_pending") is True


def test_a01_requiring_native_binary_offline_fails_closed(tmp_path: Path):
    """A01: Requesting a native binary project (.csp) without live GUI must fail closed
    with error_code='NATIVE_MUTATION_REQUIRED'."""
    proj_name = "RequireNativeOffline"
    res = cscape_new_iec_project(
        project_name=proj_name,
        target_dir=str(tmp_path),
        controller_model="XL4",
        live_gui=False,
        require_native_binary=True,
    )

    assert res["success"] is False
    assert res["status"] == "failed"
    assert res.get("error_code") == "NATIVE_MUTATION_REQUIRED"
    assert "NATIVE_MUTATION_REQUIRED" in res.get("error_code", "")
    assert not (tmp_path / proj_name / f"{proj_name}.csp").exists()


def test_a01_invalid_project_name_or_traversal_fails_closed(tmp_path: Path):
    """A01: Path traversal, illegal characters, and empty names fail closed."""
    for bad_name in ["", "   ", "../../escape", "bad name with spaces", "CON", "NUL"]:
        res = cscape_create_project(name=bad_name, target_plc="XL4")
        assert res["success"] is False
        assert res["status"] in ("failed", "blocked")


# =============================================================================
# 2. A02: ST POU Insertion - Separation of Staging from Native Mutation
# =============================================================================

def test_a02_st_staging_marks_native_mutation_pending(tmp_path: Path):
    """A02: Staging ST source files marks is_native_persisted: False and native_mutation_applied: False."""
    proj_name = "StagingProj"
    cscape_new_iec_project(project_name=proj_name, target_dir=str(tmp_path), live_gui=False)
    proj_dir = tmp_path / proj_name

    valid_st = """PROGRAM StagedPumpControl
VAR
    bStartPump : BOOL := FALSE;
    bPumpRunning : BOOL := FALSE;
END_VAR
IF bStartPump THEN
    bPumpRunning := TRUE;
ELSE
    bPumpRunning := FALSE;
END_IF;
END_PROGRAM"""

    res = cscape_insert_st(
        pou_name="StagedPumpControl",
        pou_type="PROGRAM",
        st_code=valid_st,
        target_project_path=str(proj_dir),
    )

    assert res["success"] is True
    assert res["status"] == "success"
    assert res["storage_mode"] == "staging"
    assert res["is_staged"] is True
    assert res["is_native_persisted"] is False
    assert res["native_mutation_applied"] is False
    assert res["native_insertion_verified"] is False
    assert res.get("validation_source") == "iec_ast_offline"


def test_a02_ladder_constructs_rejected_with_zero_disk_mutation(tmp_path: Path):
    """A02: Injection of ladder constructs (---[ ]---, RUNG, coils) is rejected
    with ERR_LADDER_FORBIDDEN and causes ZERO disk writes."""
    proj_name = "LadderRejectionProj"
    cscape_new_iec_project(project_name=proj_name, target_dir=str(tmp_path), live_gui=False)
    proj_dir = tmp_path / proj_name

    ladder_st = """PROGRAM MaliciousLadder
VAR
    x : BOOL;
END_VAR
---[ ]------( )---
END_PROGRAM"""

    res = cscape_insert_st(
        pou_name="MaliciousLadder",
        pou_type="PROGRAM",
        st_code=ladder_st,
        target_project_path=str(proj_dir),
    )

    assert res["success"] is False
    assert res["status"] == "failed"
    fail_locs = res.get("failure_locations", [])
    assert any(loc.get("error_code") == "ERR_LADDER_FORBIDDEN" for loc in fail_locs)
    # Invariant: Zero disk mutation on rejected code
    assert not (proj_dir / "pous" / "MaliciousLadder.st").exists()


def test_a02_anti_self_referential_editor_verification_fails_closed():
    """A02: StructuredTextInserter must NEVER return verified=True by falling back
    to reading the file from disk when no editor HWND is active."""
    inserter = StructuredTextInserter()
    st_code = "PROGRAM AntiSelfRef VAR a:INT; END_VAR a:=1; END_PROGRAM"

    # Calling verify_editor_content with invalid/zero editor_hwnd must fail closed
    res: STVerificationResult = inserter.verify_editor_content(
        editor_hwnd=0,
        expected_code=st_code,
        pou_name="AntiSelfRef",
    )
    assert res.verified is False
    assert res.exact_match is False


# =============================================================================
# 3. A03: Live Compile Deactivation in Public Offline Path
# =============================================================================

def test_a03_public_compile_deactivated_in_offline_path(tmp_path: Path):
    """A03: Invoking live compilation in public path without live GUI HWND must return
    status: inconclusive with error_code='LIVE_GUI_COMPILATION_DEACTIVATED'."""
    proj_dir = tmp_path / "DummyProject"
    proj_dir.mkdir(parents=True, exist_ok=True)

    res = cscape_compile(
        project_path=str(proj_dir),
        clean_build=True,
        deactivate_public_path=True,
    )

    assert res["success"] is False
    assert res["status"] == "inconclusive"
    assert res.get("error_code") == "LIVE_GUI_COMPILATION_DEACTIVATED"
    assert "deactivated in offline public path" in res.get("message", "")


# =============================================================================
# 4. A04: Live Build Output Scraper Deactivation
# =============================================================================

def test_a04_public_build_output_scraper_deactivated(tmp_path: Path):
    """A04: Live build output scraping without active Cscape GUI returns
    status: inconclusive with error_code='LIVE_BUILD_SCRAPER_DEACTIVATED'."""
    res = cscape_get_build_output(
        project_path=str(tmp_path),
        deactivate_public_path=True,
    )

    assert res["success"] is False
    assert res["status"] == "inconclusive"
    assert res.get("error_code") == "LIVE_BUILD_SCRAPER_DEACTIVATED"


# =============================================================================
# 5. A08: Live Simulation Deactivation / Emulated Provenance
# =============================================================================

def test_a08_simulation_live_hardware_deactivated_and_blocked():
    """A08: Attempting to invoke simulation with live hardware returns status: blocked."""
    st_code = "PROGRAM SimTest VAR cnt:INT:=0; END_VAR cnt:=cnt+1; END_PROGRAM"
    res = cscape_run_simulation(
        steps=5,
        st_code=st_code,
        live_hardware=True,
    )

    assert res["success"] is False
    assert res["status"] == "blocked"
    assert res.get("error_code") in ("LIVE_HARDWARE_SIMULATION_BLOCKED", "SECURITY_BLOCKED")


def test_a08_simulation_provenance_explicitly_emulated():
    """A08: Pure software simulation explicitly declares provenance: emulated_in_memory."""
    st_code = "PROGRAM SimTest VAR cnt:INT:=0; END_VAR cnt:=cnt+1; END_PROGRAM"
    res = cscape_run_simulation(steps=3, st_code=st_code)

    assert res["success"] is True
    assert res["status"] == "success"
    assert res.get("provenance") == "emulated_in_memory"
    assert res.get("hardware_connected") is False


# =============================================================================
# 6. A09: PLC Download Lockout (Fail-Closed)
# =============================================================================

def test_a09_download_command_ids_permanently_blocked():
    """A09: Program and controller download command IDs (32827, 33149) are blocked fail-closed."""
    assert ID_PROGRAM_DOWNLOAD in (32827, 33149)
    assert ID_CONTROLLER_DOWNLOAD in (32827, 33149)

    compiler = CscapeCompiler()
    with pytest.raises(UnauthorizedDownloadError):
        compiler.download_to_controller()

    with pytest.raises(UnauthorizedDownloadError):
        compiler.download_project("TestProj")


def test_a09_physical_port_lockout_enforced():
    """A09: Physical serial ports COM1-COM256 are unconditionally blocked."""
    for port in ["COM1", "COM3", "\\\\.\\COM4", "CAN0"]:
        with pytest.raises((HardwareLockoutError, SecurityError)):
            SafetyGuard.validate_hardware_connection(port)


# =============================================================================
# 7. Minimal P2 Adapter Interface Contracts
# =============================================================================

def test_p2_adapter_offline_preparation_and_phase_boundary(tmp_path: Path):
    """Verifies that CscapeNativeAdapter executes offline staging cleanly,
    and strictly forbids P2 native mutation during Phase P1."""
    adapter = CscapeNativeAdapter(workspace_root=tmp_path, phase="P1")
    pous = [
        {
            "name": "FeedPump",
            "type": "PROGRAM",
            "code": "PROGRAM FeedPump VAR bRun:BOOL; END_VAR bRun:=TRUE; END_PROGRAM",
        }
    ]

    # 1. Offline preparation succeeds with staging guarantees
    prep_res: OfflineStagingResult = adapter.prepare_offline(
        project_name="Phase1Prep",
        pous=pous,
        target_dir=tmp_path / "projects",
    )

    assert prep_res.success is True
    assert prep_res.status == "success"
    assert prep_res.storage_mode == "staging"
    assert prep_res.is_staged is True
    assert prep_res.is_native_persisted is False
    assert prep_res.has_native_binary is False
    assert prep_res.native_mutation_pending is True
    assert len(prep_res.staged_pous) == 1
    assert prep_res.staged_pous[0].name == "FeedPump"

    # 2. Invariant: .csp binary container must NOT exist
    csp_file = Path(prep_res.project_dir) / "Phase1Prep.csp"
    assert not csp_file.exists()

    # 3. P2 boundary enforcement: Calling execute_native_mutation in P1 raises NotImplementedError
    with pytest.raises(NotImplementedError) as exc_info:
        adapter.execute_native_mutation(prep_res)

    assert "Phase P1 boundary enforcement" in str(exc_info.value)
    assert "reserved for Phase P2" in str(exc_info.value)
