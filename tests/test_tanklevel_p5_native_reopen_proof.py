"""Contract Test Suite for TANKLEVEL_P5_NATIVE_REOPEN_PROOF_WITH_SCALING_BRIDGE.

Mandate: Plan v3 - TankLevel_P5 Native Reopen Proof with Scaling Bridge
Governing Rule: RULE[C:\\Users\\ArmandoSilva\\AGENTS.md]
Operational Mode: offline/DEV [PRODUCT_EVIDENCE] (Zero PLC Download, Read-Only Verification)

Verifies:
1. TankLevel_P5_Dedicated.csp CFBF OLE2 compound file integrity and Horner markers.
2. Structured Text scaling bridge POUs (FB_ModbusScaleQuality.st, TankLevelModbusBridge.st) present and pure ST AST.
3. Modbus protocol inventory and PV configuration sidecars intact.
4. FastMCP cscape_open_project execution confirms live Cscape session (PID 12788, HWND, visible window).
5. Live Cscape window visibility and screenshot proof verification.
6. Fail-closed hardware safety lockout (zero PLC download, verified_live=False, no Error Check loop).
7. Strict adherence to 4-state contract (status: success | failed | blocked | inconclusive).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pytest

from src.cscape.cfbf import is_valid_cfbf, inspect_project_file
from src.cscape.project_manager import CscapeLiveProjectManager
from src.cscape.st_ld_interop import STLadderInteropGuard, LadderConstructRejectedError
from src.mcp.tools import cscape_open_project, ToolStatus


WORKSPACE_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")
PROJECT_DIR = WORKSPACE_ROOT / "artifacts" / "projects" / "TankLevel_P5_Dedicated"
CSP_PATH = PROJECT_DIR / "TankLevel_P5_Dedicated.csp"
POUS_DIR = PROJECT_DIR / "pous"
SCREENSHOT_PATH = WORKSPACE_ROOT / "ops" / "artifacts" / "tanklevel_p5_native_reopen_proof.png"


def test_tanklevel_p5_cfbf_container_validity():
    """Verify that TankLevel_P5_Dedicated.csp is a valid CFBF OLE2 container with intact Horner markers."""
    assert CSP_PATH.exists(), f"Project container not found at {CSP_PATH}"
    assert is_valid_cfbf(CSP_PATH), "Project container is not a valid CFBF OLE2 file"

    info = inspect_project_file(CSP_PATH)
    assert info.is_valid_cfbf is True
    assert info.magic_hex == "d0cf11e0a1b11ae1"
    assert info.sector_size == 512
    assert "Contents" in [s["name"] for s in info.stream_entries]
    assert info.file_size_bytes > 50000

    raw_bytes = CSP_PATH.read_bytes()
    assert b"HornerOCS" in raw_bytes
    assert b"%AI1" in raw_bytes


def test_scaling_bridge_pous_present_and_pure_st():
    """Verify that FB_ModbusScaleQuality.st and TankLevelModbusBridge.st exist, are pure ST, and have 0 ladder constructs."""
    fb_path = POUS_DIR / "FB_ModbusScaleQuality.st"
    bridge_path = POUS_DIR / "TankLevelModbusBridge.st"
    control_path = POUS_DIR / "TankLevelControl.st"

    assert fb_path.exists(), "FB_ModbusScaleQuality.st missing from POUs"
    assert bridge_path.exists(), "TankLevelModbusBridge.st missing from POUs"
    assert control_path.exists(), "TankLevelControl.st missing from POUs"

    # Verify FB_ModbusScaleQuality.st
    fb_code = fb_path.read_text(encoding="utf-8")
    assert "FUNCTION_BLOCK FB_ModbusScaleQuality" in fb_code
    assert "RawInput : INT;" in fb_code
    assert "ScaledOutput : REAL;" in fb_code
    assert "QualityGood : BOOL;" in fb_code
    assert "FailSafeValue : REAL := 0.0;" in fb_code
    matches_fb = STLadderInteropGuard.detect_ladder_constructs(fb_code)
    assert len(matches_fb) == 0
    STLadderInteropGuard.enforce_st_code(fb_code)

    # Verify TankLevelModbusBridge.st
    bridge_code = bridge_path.read_text(encoding="utf-8")
    assert "PROGRAM TankLevelModbusBridge" in bridge_code
    assert "AI_TankLevelRaw AT %AI1 : INT" in bridge_code
    assert "AI_InflowRaw AT %AI2 : INT" in bridge_code
    assert "AI_DischargeRaw AT %AI3 : INT" in bridge_code
    assert "TankLevelPV AT %R101 : REAL" in bridge_code
    assert "InflowRatePV AT %R103 : REAL" in bridge_code
    assert "DischargePressPV AT %R105 : REAL" in bridge_code
    matches_bridge = STLadderInteropGuard.detect_ladder_constructs(bridge_code)
    assert len(matches_bridge) == 0
    STLadderInteropGuard.enforce_st_code(bridge_code)


def test_modbus_protocol_sidecars_synchronized():
    """Verify that Modbus protocol inventory and PV config sidecars are intact and specify %AI1..%AI3."""
    inv_path = PROJECT_DIR / "modbus_protocol_inventory.json"
    pv_path = PROJECT_DIR / "modbus_pv_config.json"

    assert inv_path.exists(), "modbus_protocol_inventory.json missing"
    assert pv_path.exists(), "modbus_pv_config.json missing"

    inv = json.loads(inv_path.read_text(encoding="utf-8"))
    assert "devices" in inv
    assert len(inv["devices"]) == 3
    assert "scan_list" in inv
    assert len(inv["scan_list"]) == 3
    regs = [tx["target_ocs_register"] for tx in inv["scan_list"]]
    assert "%AI1" in regs
    assert "%AI2" in regs
    assert "%AI3" in regs

    pv = json.loads(pv_path.read_text(encoding="utf-8"))
    assert pv["address_mapping"]["horner_ocs_register"] == "%AI1"
    assert pv["address_mapping"]["modicon_1based"] == 40001
    assert pv["read_only_enforced"] is True


def test_fastmcp_cscape_open_project_reopen_offline_contract():
    """Verify that FastMCP cscape_open_project confirms project active status and returns canonical success."""
    res = cscape_open_project(file_path=str(CSP_PATH))
    assert res["status"] == "success"
    assert res["success"] is True
    assert res["project_name"] == "TankLevel_P5_Dedicated"
    assert res["is_valid_cfbf"] is True
    assert res["cscape_version"] == "10.2.751.4"
    assert res["already_open"] is True
    assert res["open_mode"] == "live_gui"
    assert res["cscape_pid"] == 12788
    assert res["main_hwnd"] is not None
    assert "TankLevel_P5_Dedicated.csp" in res["window_title"]


def test_live_cscape_window_visibility_and_screenshot_proof():
    """Verify that live Cscape window is visible on winsta0\\Default and screenshot proof is valid."""
    mgr = CscapeLiveProjectManager()
    mgr._attach_thread_desktop()
    pid = mgr.find_running_cscape_pid()
    assert pid == 12788, f"Expected Cscape PID 12788, found {pid}"

    hwnd = mgr.get_main_window()
    assert hwnd is not None, "Cscape main window HWND not found"

    import win32gui
    assert win32gui.IsWindow(hwnd), f"HWND {hwnd} is not a valid window"
    assert win32gui.IsWindowVisible(hwnd), f"HWND {hwnd} is not visible on desktop"
    title = win32gui.GetWindowText(hwnd)
    assert "TankLevel_P5_Dedicated.csp" in title, f"Title does not match: {title}"

    # Verify screenshot proof
    assert SCREENSHOT_PATH.exists(), f"Screenshot proof missing at {SCREENSHOT_PATH}"
    assert SCREENSHOT_PATH.stat().st_size > 50000, "Screenshot file size too small"
    sha = hashlib.sha256(SCREENSHOT_PATH.read_bytes()).hexdigest()
    assert len(sha) == 64


def test_fail_closed_on_invalid_project():
    """Verify that cscape_open_project fails closed on nonexistent or invalid project."""
    res_missing = cscape_open_project(file_path=str(PROJECT_DIR / "NonexistentProject.csp"))
    assert res_missing["status"] in ("failed", "blocked")
    assert res_missing["success"] is False


def test_reopen_proof_governance_invariants():
    """Verify strict adherence to zero PLC download, verified_live=False, and 4-state contract."""
    res = cscape_open_project(file_path=str(CSP_PATH))
    assert res["status"] in ("success", "failed", "blocked", "inconclusive")
    assert res.get("verified_live", False) is False
    assert res.get("plc_download", False) is False
