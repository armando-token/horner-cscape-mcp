"""Verification Suite for Phase P3: Native Cscape HMI Screen and Object Group.

Verifies:
1. Native screen inventory on TankLevel_P2_Dedicated.csp (Screen 1 Main Screen, Screen 2, Screen 3).
2. Native HMI object group creation representing and controlling P2 logic:
   - PV display with unit (%)
   - Manual/Auto selector switch (AutoMode)
   - Manual command input (ManualOutputCmd)
   - Editable thresholds with limits (Setpoint, HI_Limit=65.0, LO_Limit=35.0)
   - Differentiated command vs feedback indicators (PumpCmdActive vs PumpRunningFeedback)
   - Sensor/permission state (UNAVAILABLE / OFFLINE_DEV without fake feedback)
3. Properties reading and CFBF stream verification.
4. Correct variable bindings to P2 logic (STBlock1).
5. Lifecycle persistence proof across save, child close, and reopen.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from src.cscape.hmi import CscapeHMIManager, HMIScreen, HMIObject
from src.cscape.cfbf import is_valid_cfbf
from src.mcp.tools import (
    cscape_hmi_inventory,
    cscape_hmi_apply_group,
    cscape_hmi_read_properties,
    cscape_hmi_verify_bindings,
)


@pytest.fixture(scope="module")
def hmi_manager():
    return CscapeHMIManager()


@pytest.fixture(scope="module")
def dedicated_project_path():
    p = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\projects\TankLevel_P2_Dedicated\TankLevel_P2_Dedicated.csp")
    assert p.exists(), f"Dedicated project container does not exist: {p}"
    assert is_valid_cfbf(p), f"Dedicated container is not valid CFBF: {p}"
    return p


def test_p3_screen_inventory(hmi_manager, dedicated_project_path):
    """P3.1: Verify screen inventory extracts screens from TankLevel_P2_Dedicated.csp."""
    screens = hmi_manager.inventory_screens(dedicated_project_path)
    assert len(screens) >= 1, "At least 1 screen must be inventoried"
    
    screen1 = next((s for s in screens if s.screen_id == 1), None)
    assert screen1 is not None, "Screen 1 must be present"
    assert screen1.is_main_screen is True
    assert screen1.name == "Screen 1"
    assert screen1.group == "Main Screen"
    assert screen1.objects_count > 0


def test_p3_object_group_application(hmi_manager, dedicated_project_path):
    """P3.2: Verify native object group creation for P2 control and representation."""
    res = hmi_manager.apply_p2_hmi_group(dedicated_project_path, screen_id=1)
    assert res["status"] == "success"
    assert res["objects_count"] >= 6
    
    objects = res["objects"]
    names = [obj["name"] for obj in objects]
    assert "HMI_TankLevelPV" in names
    assert "HMI_ModeSelector" in names
    assert "HMI_ManualCommand" in names
    assert "HMI_Setpoint" in names
    assert "HMI_PumpCommandIndicator" in names
    assert "HMI_PumpFeedbackIndicator" in names
    assert "HMI_SensorPermissionState" in names


def test_p3_properties_and_cfbf_streams(hmi_manager, dedicated_project_path):
    """P3.3: Verify properties after apply and CFBF stream integrity."""
    props = hmi_manager.read_properties_after_apply(dedicated_project_path, screen_id=1)
    assert props["status"] == "success"
    assert props["screen_id"] == 1
    
    streams = props["cfbf_stream_verified"]
    assert streams["has_pv_stream"] is True
    assert streams["has_sp_stream"] is True
    assert streams["has_error_stream"] is True
    assert streams["container_size"] > 0


def test_p3_p2_logic_bindings(hmi_manager, dedicated_project_path):
    """P3.4: Verify HMI object bindings strictly match P2 IEC ST logic."""
    bindings = hmi_manager.verify_p2_bindings(dedicated_project_path, screen_id=1)
    assert bindings["status"] == "success"
    assert bindings["bindings_verified"] is True
    
    checks = bindings["checks"]
    assert checks["TankLevelPV_bound_to_logic"] is True
    assert checks["Setpoint_bound_to_logic"] is True
    assert checks["HI_alarm_threshold_matches"] is True
    assert checks["LO_alarm_threshold_matches"] is True
    assert checks["Error_calculation_matches"] is True


def test_p3_minimum_hmi_contract(hmi_manager, dedicated_project_path):
    """P3.5: Verify complete Minimum HMI specification requirements."""
    props = hmi_manager.read_properties_after_apply(dedicated_project_path, screen_id=1)
    objs = {o["name"]: o for o in props["objects"]}
    
    # 1. PV display with unit
    pv = objs["HMI_TankLevelPV"]
    assert pv["unit"] == "%"
    assert pv["bound_variable"] == "TankLevelPV"
    assert pv["min_limit"] == 0.0
    assert pv["max_limit"] == 100.0
    
    # 2. Manual / Auto selector
    mode = objs["HMI_ModeSelector"]
    assert mode["object_type"] == "SELECTOR_SWITCH"
    assert mode["bound_variable"] == "AutoMode"
    
    # 3. Manual command
    cmd = objs["HMI_ManualCommand"]
    assert cmd["bound_variable"] == "ManualOutputCmd"
    assert cmd["min_limit"] == 0.0
    assert cmd["max_limit"] == 100.0
    
    # 4. Editable thresholds with limits
    sp = objs["HMI_Setpoint"]
    assert sp["bound_variable"] == "Setpoint"
    assert sp["min_limit"] == 0.0
    assert sp["max_limit"] == 100.0
    assert sp["properties"]["hi_threshold_trip"] == 65.0
    assert sp["properties"]["lo_threshold_trip"] == 35.0
    
    # 5. Differentiated command vs feedback indicators
    cmd_ind = objs["HMI_PumpCommandIndicator"]
    fb_ind = objs["HMI_PumpFeedbackIndicator"]
    assert cmd_ind["indicator_type"] == "COMMAND"
    assert fb_ind["indicator_type"] == "FEEDBACK"
    assert cmd_ind["bound_variable"] != fb_ind["bound_variable"]
    assert fb_ind["properties"]["differentiated_from_cmd"] is True
    
    # 6. Sensor / permission state (Fail-Closed, No Invented Feedback)
    sensor = objs["HMI_SensorPermissionState"]
    assert "UNAVAILABLE" in sensor["permission_state"]
    assert "FAIL_CLOSED" in sensor["permission_state"]
    assert "NO_PHYSICAL_FEEDBACK" in sensor["feedback_state"]


def test_p3_hmi_lifecycle_durability():
    """P3.6: Verify HMI durability evidence across save, close, reopen, and native re-read."""
    chk = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\checkpoints\p3_native_hmi_evidence.json")
    assert chk.exists(), "P3 evidence checkpoint must exist"
    
    data = json.loads(chk.read_text(encoding="utf-8"))
    assert data["status"] == "success"
    assert data["phase"] == "P3"
    assert data["reopened_screens_count"] >= 1
    assert data["hmi_objects_count"] >= 6
    
    life = data["lifecycle_verified"]
    assert life["saved"] is True
    assert life["closed_cleanly"] is True
    assert life["reopened"] is True
    assert life["screens_retained"] is True
    assert life["objects_retained"] is True
    
    min_hmi = data["minimum_hmi_verified"]
    assert min_hmi["pv_display_with_unit"] is True
    assert min_hmi["manual_auto_selector"] is True
    assert min_hmi["manual_command"] is True
    assert min_hmi["editable_thresholds_with_limits"] is True
    assert min_hmi["differentiated_command_vs_feedback"] is True
    assert min_hmi["sensor_permission_state_fail_closed"] is True
    assert min_hmi["no_invented_physical_feedback"] is True


def test_p3_wrong_binding_negative_test(hmi_manager, dedicated_project_path):
    """P3.7: Mandatory wrong-binding negative test detectable via binding map.

    Verifies that:
    1. Mapping TankLevelPV to an invalid/unmapped variable fails closed.
    2. Colliding command and feedback indicator bindings fails closed.
    3. Setting an invalid threshold or unmapped setpoint fails closed.
    """
    # Negative Test 1: TankLevelPV bound to unmapped wrong variable
    wrong_pv_res = hmi_manager.verify_p2_bindings(
        dedicated_project_path,
        screen_id=1,
        binding_overrides={"HMI_TankLevelPV": "WrongVar_NotInP2Logic"},
    )
    assert wrong_pv_res["status"] == "failed"
    assert wrong_pv_res["bindings_verified"] is False
    assert wrong_pv_res["error_code"] == "ERR_HMI_WRONG_BINDING"
    assert any("HMI_TankLevelPV" == m["object"] for m in wrong_pv_res["mismatches"])
    assert any("WrongVar_NotInP2Logic" in m["reason"] for m in wrong_pv_res["mismatches"])

    # Negative Test 2: Command and feedback indicators bound to same variable (no differentiation)
    collision_res = hmi_manager.verify_p2_bindings(
        dedicated_project_path,
        screen_id=1,
        binding_overrides={"HMI_PumpFeedbackIndicator": "PumpCmdActive"},
    )
    assert collision_res["status"] == "failed"
    assert collision_res["bindings_verified"] is False
    assert collision_res["error_code"] == "ERR_HMI_WRONG_BINDING"
    assert any("HMI_PumpFeedbackIndicator" == m["object"] for m in collision_res["mismatches"])
    assert any("Collision between command" in m["reason"] for m in collision_res["mismatches"])

    # Negative Test 3: Setpoint bound to unknown tag
    wrong_sp_res = hmi_manager.verify_p2_bindings(
        dedicated_project_path,
        screen_id=1,
        binding_overrides={"HMI_Setpoint": "Unmapped_Setpoint_Var"},
    )
    assert wrong_sp_res["status"] == "failed"
    assert wrong_sp_res["bindings_verified"] is False
    assert any("HMI_Setpoint" == m["object"] for m in wrong_sp_res["mismatches"])


def test_p3_mcp_hmi_tools(dedicated_project_path):
    """P3.8: Verify Native Cscape HMI tools via the FastMCP tool interface."""
    proj_str = str(dedicated_project_path)

    # 1. cscape_hmi_inventory
    inv = cscape_hmi_inventory(project_path=proj_str)
    assert inv["status"] == "success"
    assert inv["screens_count"] >= 1
    assert any(s["screen_id"] == 1 for s in inv["screens"])

    # 2. cscape_hmi_apply_group
    app = cscape_hmi_apply_group(project_path=proj_str, screen_id=1)
    assert app["status"] == "success"
    assert app["objects_count"] >= 6
    assert len(app["objects"]) >= 6

    # 3. cscape_hmi_read_properties
    props = cscape_hmi_read_properties(project_path=proj_str, screen_id=1)
    assert props["status"] == "success"
    assert props["cfbf_stream_verified"]["has_pv_stream"] is True
    assert props["cfbf_stream_verified"]["has_sp_stream"] is True

    # 4. cscape_hmi_verify_bindings (positive case)
    pos_bind = cscape_hmi_verify_bindings(project_path=proj_str, screen_id=1)
    assert pos_bind["status"] == "success"
    assert pos_bind["bindings_verified"] is True
    assert pos_bind["checks"]["TankLevelPV_bound_to_logic"] is True

    # 5. cscape_hmi_verify_bindings (negative wrong-binding case via MCP)
    neg_bind = cscape_hmi_verify_bindings(
        project_path=proj_str,
        screen_id=1,
        binding_overrides={"HMI_TankLevelPV": "Fake_PV_NegativeTest"},
    )
    assert neg_bind["status"] == "failed"
    assert neg_bind["bindings_verified"] is False
    assert len(neg_bind["mismatches"]) > 0
    assert any("HMI_TankLevelPV" == m["object"] for m in neg_bind["mismatches"])

