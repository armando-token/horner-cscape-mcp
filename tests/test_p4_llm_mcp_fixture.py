"""Verification Suite for Plan v3 Phase P4: LLM/MCP Fixture Evolution & Selective Edit.

Verifies:
1. Fresh fixture request to formal IEC ST specification (cscape_fixture_request_to_spec).
2. Project container, Structured Text POU, and HMI creation (cscape_fixture_create).
3. Clean compilation and persistence (cscape_compile_project).
4. Selective edit: Limits 30/70 to 35/75 + renaming level label (cscape_fixture_selective_edit).
5. Revision impact analysis and untouched element audit (cscape_fixture_revision_impact).
6. Live durability cycle: Save -> Close MDI child -> Reopen -> Semantic check (cscape_fixture_durability_check).
7. Identical request deduplication / idempotency (cscape_fixture_selective_edit).
8. Negative parameter validation: Inverted limits and ladder injection (ERR_INVALID_LIMITS / ERR_LADDER_FORBIDDEN).
9. External manual conflict detection: Checksum mismatch fail-closed (cscape_fixture_detect_conflict).
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from src.cscape.cfbf import is_valid_cfbf
from src.cscape.fixture_evolution import (
    FixtureEvolutionManager,
    FixtureRequest,
    FixtureSpec,
    SelectiveEditRequest,
)
from src.mcp.tools import (
    cscape_fixture_request_to_spec,
    cscape_fixture_create,
    cscape_fixture_selective_edit,
    cscape_fixture_revision_impact,
    cscape_fixture_durability_check,
    cscape_fixture_detect_conflict,
    cscape_compile_project,
)


@pytest.fixture(scope="module")
def fixture_mgr():
    return FixtureEvolutionManager()


@pytest.fixture(scope="module")
def project_name():
    return "TankLevel_P4_Dedicated"


def test_p4_request_to_spec(fixture_mgr, project_name):
    """P4.1: Verify translation of high-level fixture request into formal ST & HMI specification."""
    req = {
        "fixture_id": "TankLevel_P4_Fixture",
        "description": "Closed-loop buffer tank level controller with dual threshold alarms",
        "process_variable": "TankLevelPV",
        "engineering_unit": "%",
        "lo_limit": 30.0,
        "hi_limit": 70.0,
        "setpoint": 50.0,
        "level_label": "Tank Level PV",
        "project_name": project_name,
        "screen_id": 1,
    }
    res = cscape_fixture_request_to_spec(**req)
    assert res["status"] == "success"
    spec = res["spec"]
    assert spec["project_name"] == project_name
    assert spec["revision"] == "1.0.0"
    assert spec["limits"] == {"lo_limit": 30.0, "hi_limit": 70.0}
    assert spec["level_label"] == "Tank Level PV"
    assert len(spec["variables"]) >= 10
    assert len(spec["hmi_objects"]) >= 9
    assert "LO_Limit : REAL := 30.0;" in spec["st_code"]
    assert "HI_Limit : REAL := 70.0;" in spec["st_code"]


def test_p4_create_fixture_project(fixture_mgr, project_name):
    """P4.2: Verify instantiation of dedicated CFBF container, ST POU, and HMI group."""
    spec_res = cscape_fixture_request_to_spec(project_name=project_name)
    assert spec_res["status"] == "success"
    spec = spec_res["spec"]

    create_res = cscape_fixture_create(spec=spec, project_name=project_name)
    assert create_res["status"] == "success"
    assert create_res["project_name"] == project_name
    assert create_res["revision"] == "1.0.0"
    assert create_res["cfbf_valid"] is True
    assert create_res["pous_count"] == 1
    assert create_res["hmi_objects_count"] >= 9

    csp_p = Path(create_res["csp_file_path"])
    assert csp_p.exists()
    assert is_valid_cfbf(csp_p)


def test_p4_compile_and_save(project_name):
    """P4.3: Verify clean compile of dedicated project with zero errors and zero warnings."""
    comp_res = cscape_compile_project(project_name=project_name, clean_build=True)
    assert comp_res["status"] == "success" or comp_res.get("error_count", 0) == 0
    assert comp_res.get("error_count", 0) == 0
    assert comp_res.get("warning_count", 0) == 0


def test_p4_selective_edit_limits_and_label(fixture_mgr, project_name):
    """P4.4: Verify selective modification of limits (30/70 -> 35/75) and label rename."""
    edit_res = cscape_fixture_selective_edit(
        project_name=project_name,
        new_lo_limit=35.0,
        new_hi_limit=75.0,
        new_level_label="Buffer Tank Level PV",
        expected_prior_revision="1.0.0",
    )
    assert edit_res["status"] == "success"
    assert edit_res["action"] == "MUTATION_APPLIED"
    assert edit_res["prior_revision"] == "1.0.0"
    assert edit_res["new_revision"] == "1.1.0"
    assert edit_res["mutated_limits"] == {"lo_limit": 35.0, "hi_limit": 75.0}
    assert edit_res["mutated_label"] == "Buffer Tank Level PV"


def test_p4_revision_impact_analysis(fixture_mgr, project_name):
    """P4.5: Verify semantic impact report, audit of untouched elements, and AST validity."""
    impact_res = cscape_fixture_revision_impact(project_name=project_name)
    assert impact_res["status"] == "success"
    report = impact_res["report"]
    assert report["prior_revision"] == "1.0.0"
    assert report["new_revision"] == "1.1.0"
    assert report["impact_rating"] == "LOW_LOCALIZED"
    assert report["ast_syntax_valid"] is True

    mut = report["mutations"]
    assert mut["limits_changed"]["lo_limit"]["after"] == 35.0
    assert mut["limits_changed"]["hi_limit"]["after"] == 75.0
    assert mut["labels_changed"]["level_label"]["after"] == "Buffer Tank Level PV"

    untouched = report["untouched_elements"]
    assert untouched["variables_preserved_count"] >= 9
    assert untouched["hmi_objects_preserved_count"] >= 5


def test_p4_durability_and_semantic_check(fixture_mgr, project_name):
    """P4.6: Verify live Cscape save, clean child close, reopen, and semantic assertions."""
    dur_res = cscape_fixture_durability_check(project_name=project_name)
    assert dur_res["status"] == "success"
    assert dur_res["durability_verified"] is True
    sem = dur_res["semantic_checks"]
    assert sem["lo_limit_equals_35"] is True
    assert sem["hi_limit_equals_75"] is True
    assert sem["level_label_equals_BufferTankLevelPV"] is True
    assert sem["st_code_contains_35"] is True
    assert sem["st_code_contains_75"] is True
    assert sem["clean_reopen_status"] is True


def test_p4_identical_request_no_dup(fixture_mgr, project_name):
    """P4.7: Verify identical request returns NO_OP without duplicate mutations (idempotency)."""
    identical_res = cscape_fixture_selective_edit(
        project_name=project_name,
        new_lo_limit=35.0,
        new_hi_limit=75.0,
        new_level_label="Buffer Tank Level PV",
    )
    assert identical_res["status"] == "success"
    assert identical_res["action"] == "NO_OP"
    assert identical_res["duplicate_prevented"] is True
    assert identical_res["revision"] == "1.1.0"


def test_p4_negative_parameter_validation(fixture_mgr, project_name):
    """P4.8: Verify fail-closed rejection of inverted limits and ladder injection."""
    # Negative Test 1: Inverted limits (85.0 > 25.0)
    neg_limits = cscape_fixture_selective_edit(
        project_name=project_name,
        new_lo_limit=85.0,
        new_hi_limit=25.0,
        new_level_label="Illegal Inverted Limits",
    )
    assert neg_limits["status"] == "failed"
    assert neg_limits["error_code"] == "ERR_INVALID_LIMITS"

    # Negative Test 2: Ladder logic construct in label
    neg_ladder = cscape_fixture_selective_edit(
        project_name=project_name,
        new_lo_limit=35.0,
        new_hi_limit=75.0,
        new_level_label="---[ ]--- Injected Ladder Contact",
    )
    assert neg_ladder["status"] == "failed"
    assert neg_ladder["error_code"] == "ERR_LADDER_FORBIDDEN"


def test_p4_external_conflict_detection(fixture_mgr, project_name):
    """P4.9: Verify external conflict detection when expected hash does not match disk."""
    fake_hash = "deadbeef0000111122223333444455556666777788889999aaaabbbbccccdddd"
    conflict_res = cscape_fixture_detect_conflict(
        project_name=project_name,
        expected_hash=fake_hash,
    )
    assert conflict_res["status"] == "failed"
    assert conflict_res["conflict_detected"] is True
    assert conflict_res["error_code"] == "ERR_EXTERNAL_CONFLICT"
