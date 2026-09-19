"""Contract and Verification Test Suite for Modbus Register Scaling & IEC FB Bridge.

Tests:
1. Pure IEC 61131-3 ST AST parsing & syntax validation of FB_ModbusScaleQuality.
2. Pure IEC 61131-3 ST AST parsing & syntax validation of TankLevelModbusBridge.
3. Strict fail-closed rejection of ladder logic constructs (ERR_LADDER_FORBIDDEN).
4. Multi-point linear scaling accuracy across nominal operating points (0%, 25%, 50%, 55%, 75%, 100%).
5. Underflow & overflow detection and boundary clamping.
6. Communication watchdog timeout gating (CommFailure -> AlarmActive, QualityGood=False, FailSafeValue).
7. Stale telemetry quality indicator gating (StaleQuality -> AlarmActive, QualityGood=False).
8. Fault recovery dynamic transition back to nominal telemetry.
9. 3-channel Modbus RTU telemetry integration (%AI1 Level, %AI2 Inflow, %AI3 Discharge).
10. Multi-cycle discrete software simulation via cscape_simulate_pou.
11. Template catalog integration (cscape://templates / TEMPLATES['modbus_scale_quality']).
12. Dual-root file presence and cryptographic integrity parity.
13. Fail-closed security invariants (zero live PLC, physical port lockout, download lockout).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict
import pytest

from src.cscape.st_ld_interop import STLadderInteropGuard, LadderConstructRejectedError
from src.iec.validator import IECValidator
from src.iec.parser import Parser
from src.iec.templates import get_template, get_template_code, TEMPLATES
from src.iec.modbus_bridge import (
    FB_MODBUS_SCALE_QUALITY_ST,
    TANK_LEVEL_MODBUS_BRIDGE_ST,
    ModbusScaleQualityChannel,
    ModbusScaleQualityBridge,
    create_default_channels,
)
from src.mcp.tools import cscape_simulate_pou
from src.security.guard import SecurityGuard
from src.security.exceptions import SecurityError, HardwareLockoutError


USER_ROOT = Path(r"C:\Users\ArmandoSilva")
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")


# =============================================================================
# 1. Pure ST AST Parsing & Syntax Validation
# =============================================================================

def test_pure_st_ast_parsing_fb_modbus_scale_quality():
    """Verify FB_ModbusScaleQuality parses into valid IEC 61131-3 AST with 0 syntax errors."""
    ast = Parser.from_source(FB_MODBUS_SCALE_QUALITY_ST).parse()
    assert ast is not None
    assert ast.name == "FB_ModbusScaleQuality"
    assert len(ast.body) >= 3

    val = IECValidator.validate(FB_MODBUS_SCALE_QUALITY_ST)
    assert val.get("valid") is True
    assert val.get("errors") == []
    assert val.get("pou_name") == "FB_ModbusScaleQuality"
    assert val.get("pou_type") == "FUNCTION_BLOCK"

    var_names = [v["name"] for v in val.get("variables", [])]
    expected_inputs = ["RawInput", "RawMin", "RawMax", "EUMin", "EUMax", "CommFailure", "StaleQuality", "FailSafeValue"]
    expected_outputs = ["ScaledOutput", "QualityGood", "AlarmActive", "Underflow", "Overflow"]
    for inp in expected_inputs:
        assert inp in var_names, f"Missing input variable: {inp}"
    for outp in expected_outputs:
        assert outp in var_names, f"Missing output variable: {outp}"


def test_pure_st_ast_parsing_tank_level_modbus_bridge():
    """Verify TankLevelModbusBridge parses into valid IEC 61131-3 AST with 0 syntax errors."""
    ast = Parser.from_source(TANK_LEVEL_MODBUS_BRIDGE_ST).parse()
    assert ast is not None
    assert ast.name == "TankLevelModbusBridge"
    assert len(ast.body) >= 15

    val = IECValidator.validate(TANK_LEVEL_MODBUS_BRIDGE_ST)
    assert val.get("valid") is True
    assert val.get("errors") == []
    assert val.get("pou_name") == "TankLevelModbusBridge"
    assert val.get("pou_type") == "PROGRAM"

    var_names = [v["name"] for v in val.get("variables", [])]
    assert "AI_TankLevelRaw" in var_names
    assert "AI_InflowRaw" in var_names
    assert "AI_DischargeRaw" in var_names
    assert "TankLevelPV" in var_names
    assert "InflowRatePV" in var_names
    assert "DischargePressPV" in var_names


# =============================================================================
# 2. Strict Fail-Closed Rejection of Ladder Logic (ERR_LADDER_FORBIDDEN)
# =============================================================================

def test_st_ladder_interop_guard_positive_pure_st():
    """Verify positive compliance check of pure ST code passes STLadderInteropGuard."""
    STLadderInteropGuard.enforce_st_code(FB_MODBUS_SCALE_QUALITY_ST)
    STLadderInteropGuard.enforce_st_code(TANK_LEVEL_MODBUS_BRIDGE_ST)


@pytest.mark.parametrize(
    "ladder_snippet",
    [
        "---[ ]---",
        "---[/]---",
        "---( )---",
        "---(S)---",
        "---(R)---",
        "RUNG 1",
        "NETWORK 1",
        "XIC(Tag1)",
        "OTE(Coil1)",
    ],
)
def test_st_ladder_interop_guard_rejection_of_ladder_constructs(ladder_snippet: str):
    """Verify STLadderInteropGuard intercepts and rejects all ladder constructs fail-closed."""
    poisoned_code = f"""FUNCTION_BLOCK FB_ModbusScaleQuality
VAR_INPUT
    RawInput : INT;
END_VAR
{ladder_snippet}
END_FUNCTION_BLOCK"""

    with pytest.raises(LadderConstructRejectedError) as exc_info:
        STLadderInteropGuard.enforce_st_code(poisoned_code)
    assert "Ladder logic construct rejected" in str(exc_info.value)


# =============================================================================
# 3. Multi-Point Linear Scaling Accuracy
# =============================================================================

def test_nominal_scaling_tank_level_pv_55pct_baseline():
    """Verify exact 55.0% baseline matches Phase P5 modbus_pv_config.json (17600 counts)."""
    bridge = ModbusScaleQualityBridge()
    res = bridge.scale_channel("TX01_LEVEL_PV", raw_input=17600)
    assert res["scaled_output"] == 55.0
    assert res["quality_good"] is True
    assert res["alarm_active"] is False
    assert res["underflow"] is False
    assert res["overflow"] is False
    assert res["normalized"] == 0.55


@pytest.mark.parametrize(
    "raw_counts, expected_level_pct",
    [
        (0, 0.0),
        (8000, 25.0),
        (16000, 50.0),
        (24000, 75.0),
        (32000, 100.0),
    ],
)
def test_multi_point_scaling_linear_grid(raw_counts: int, expected_level_pct: float):
    """Verify linear scaling precision across full 0..32000 count range."""
    bridge = ModbusScaleQualityBridge()
    res = bridge.scale_channel("TX01_LEVEL_PV", raw_input=raw_counts)
    assert res["scaled_output"] == expected_level_pct
    assert res["quality_good"] is True
    assert res["alarm_active"] is False
    assert res["underflow"] is False
    assert res["overflow"] is False


# =============================================================================
# 4. Underflow, Overflow, and Clamping
# =============================================================================

def test_underflow_detection_and_clamping():
    """Verify counts below RawMin trigger Underflow=True and clamp to EUMin."""
    bridge = ModbusScaleQualityBridge()
    res = bridge.scale_channel("TX01_LEVEL_PV", raw_input=-500)
    assert res["underflow"] is True
    assert res["overflow"] is False
    assert res["scaled_output"] == 0.0
    assert res["quality_good"] is True
    assert res["alarm_active"] is False


def test_overflow_detection_and_clamping():
    """Verify counts above RawMax trigger Overflow=True and clamp to EUMax."""
    bridge = ModbusScaleQualityBridge()
    res = bridge.scale_channel("TX01_LEVEL_PV", raw_input=35000)
    assert res["underflow"] is False
    assert res["overflow"] is True
    assert res["scaled_output"] == 100.0
    assert res["quality_good"] is True
    assert res["alarm_active"] is False


# =============================================================================
# 5. Communication Health & Telemetry Quality Gating
# =============================================================================

def test_comm_failure_fail_safe_gating():
    """Verify CommFailure=True sets AlarmActive, QualityGood=False, and forces FailSafeValue."""
    bridge = ModbusScaleQualityBridge()
    res = bridge.scale_channel("TX01_LEVEL_PV", raw_input=17600, comm_failure=True)
    assert res["alarm_active"] is True
    assert res["quality_good"] is False
    assert res["scaled_output"] == 0.0


def test_stale_quality_fail_safe_gating():
    """Verify StaleQuality=True sets AlarmActive, QualityGood=False, and forces FailSafeValue."""
    bridge = ModbusScaleQualityBridge()
    res = bridge.scale_channel("TX01_LEVEL_PV", raw_input=24000, stale_quality=True)
    assert res["alarm_active"] is True
    assert res["quality_good"] is False
    assert res["scaled_output"] == 0.0


def test_custom_fail_safe_fallback():
    """Verify custom fail-safe value (e.g. 50.0%) is respected upon comm failure."""
    res = ModbusScaleQualityBridge.scale_raw_to_eu(
        raw_input=17600,
        raw_min=0,
        raw_max=32000,
        eu_min=0.0,
        eu_max=100.0,
        comm_failure=True,
        fail_safe_value=50.0,
    )
    assert res["alarm_active"] is True
    assert res["quality_good"] is False
    assert res["scaled_output"] == 50.0


# =============================================================================
# 6. Multi-Channel 3-Transaction Integration
# =============================================================================

def test_multi_channel_bridge_all_channels():
    """Verify simultaneous acquisition and scaling across all 3 Modbus telemetry channels."""
    bridge = ModbusScaleQualityBridge()
    raw_inputs = {
        "TX01_LEVEL_PV": 17600,      # 55.0 %
        "TX02_INFLOW_RATE": 16000,   # 250.0 L/min (half of 500.0)
        "TX03_DISCHARGE_PRESS": 16000, # 5.0 bar (half of 10.0)
    }

    results = bridge.scale_all_channels(raw_inputs=raw_inputs)
    assert len(results) == 3

    # Channel 1: Level
    ch1 = results["TX01_LEVEL_PV"]
    assert ch1["scaled_output"] == 55.0
    assert ch1["engineering_unit"] == "%"
    assert ch1["ocs_input_register"] == "%AI1"
    assert ch1["ocs_output_register"] == "%R101"
    assert ch1["quality_good"] is True

    # Channel 2: Inflow
    ch2 = results["TX02_INFLOW_RATE"]
    assert ch2["scaled_output"] == 250.0
    assert ch2["engineering_unit"] == "L/min"
    assert ch2["ocs_input_register"] == "%AI2"
    assert ch2["ocs_output_register"] == "%R103"
    assert ch2["quality_good"] is True

    # Channel 3: Discharge
    ch3 = results["TX03_DISCHARGE_PRESS"]
    assert ch3["scaled_output"] == 5.0
    assert ch3["engineering_unit"] == "bar"
    assert ch3["ocs_input_register"] == "%AI3"
    assert ch3["ocs_output_register"] == "%R105"
    assert ch3["quality_good"] is True


def test_channel_fault_isolation():
    """Verify comm failure on Channel 2 does not corrupt Channel 1 or Channel 3."""
    bridge = ModbusScaleQualityBridge()
    raw_inputs = {
        "TX01_LEVEL_PV": 17600,
        "TX02_INFLOW_RATE": 16000,
        "TX03_DISCHARGE_PRESS": 16000,
    }
    comm_failures = {
        "TX02_INFLOW_RATE": True,
    }

    results = bridge.scale_all_channels(raw_inputs=raw_inputs, comm_failures=comm_failures)
    assert results["TX01_LEVEL_PV"]["quality_good"] is True
    assert results["TX01_LEVEL_PV"]["scaled_output"] == 55.0

    assert results["TX02_INFLOW_RATE"]["quality_good"] is False
    assert results["TX02_INFLOW_RATE"]["alarm_active"] is True
    assert results["TX02_INFLOW_RATE"]["scaled_output"] == 0.0

    assert results["TX03_DISCHARGE_PRESS"]["quality_good"] is True
    assert results["TX03_DISCHARGE_PRESS"]["scaled_output"] == 5.0


# =============================================================================
# 7. Discrete Software Simulation via cscape_simulate_pou
# =============================================================================

def test_software_simulation_nominal_execution():
    """Verify execution of FB_ModbusScaleQuality via cscape_simulate_pou tool."""
    res = cscape_simulate_pou(
        code=FB_MODBUS_SCALE_QUALITY_ST,
        inputs={"RawInput": 17600},
        steps=1,
    )
    assert res["status"] == "success"
    assert res["success"] is True
    assert res["steps_executed"] == 1
    final_state = res["final_state"]
    assert abs(final_state["ScaledOutput"] - 55.0) < 1e-4
    assert final_state["QualityGood"] is True
    assert final_state["AlarmActive"] is False


def test_software_simulation_comm_fault_gating():
    """Verify cscape_simulate_pou forces fail-safe value when CommFailure is set."""
    res = cscape_simulate_pou(
        code=FB_MODBUS_SCALE_QUALITY_ST,
        inputs={"RawInput": 17600, "CommFailure": True},
        steps=1,
    )
    assert res["status"] == "success"
    assert res["final_state"]["ScaledOutput"] == 0.0
    assert res["final_state"]["QualityGood"] is False
    assert res["final_state"]["AlarmActive"] is True


def test_software_simulation_multi_step_trajectory():
    """Verify 4-cycle state progression: 0% -> 55% -> CommFault -> Recovery."""
    raw_trajectory = [0, 17600, 17600, 24000]
    comm_trajectory = [False, False, True, False]

    # Step 1: 0%
    s1 = cscape_simulate_pou(code=FB_MODBUS_SCALE_QUALITY_ST, inputs={"RawInput": raw_trajectory[0], "CommFailure": comm_trajectory[0]}, steps=1)
    assert s1["final_state"]["ScaledOutput"] == 0.0
    assert s1["final_state"]["QualityGood"] is True

    # Step 2: 55%
    s2 = cscape_simulate_pou(code=FB_MODBUS_SCALE_QUALITY_ST, inputs={"RawInput": raw_trajectory[1], "CommFailure": comm_trajectory[1]}, steps=1)
    assert abs(s2["final_state"]["ScaledOutput"] - 55.0) < 1e-4
    assert s2["final_state"]["QualityGood"] is True

    # Step 3: Comm fault -> clamped to 0.0
    s3 = cscape_simulate_pou(code=FB_MODBUS_SCALE_QUALITY_ST, inputs={"RawInput": raw_trajectory[2], "CommFailure": comm_trajectory[2]}, steps=1)
    assert s3["final_state"]["ScaledOutput"] == 0.0
    assert s3["final_state"]["QualityGood"] is False
    assert s3["final_state"]["AlarmActive"] is True

    # Step 4: Recovery -> 75%
    s4 = cscape_simulate_pou(code=FB_MODBUS_SCALE_QUALITY_ST, inputs={"RawInput": raw_trajectory[3], "CommFailure": comm_trajectory[3]}, steps=1)
    assert abs(s4["final_state"]["ScaledOutput"] - 75.0) < 1e-4
    assert s4["final_state"]["QualityGood"] is True
    assert s4["final_state"]["AlarmActive"] is False


# =============================================================================
# 8. Template Catalog Integration
# =============================================================================

def test_template_catalog_modbus_scale_quality():
    """Verify modbus_scale_quality is registered in IEC template catalog."""
    t = get_template("modbus_scale_quality")
    assert t is not None
    assert t["id"] == "modbus_scale_quality"
    assert t["pou_type"] == "FUNCTION_BLOCK"
    assert "FB_ModbusScaleQuality" in t["code"]

    code = get_template_code("modbus_scale_quality")
    assert code is not None
    assert "FUNCTION_BLOCK FB_ModbusScaleQuality" in code
    assert "END_FUNCTION_BLOCK" in code


# =============================================================================
# 9. Dual-Root File Parity & Cryptographic Checksums
# =============================================================================

def test_pou_file_presence_and_dual_root_parity():
    """Verify POU files exist across dual roots with identical SHA-256 digests."""
    rel_paths = [
        "artifacts/projects/TankLevel_P5_Dedicated/pous/FB_ModbusScaleQuality.st",
        "artifacts/projects/TankLevel_P5_Dedicated/pous/TankLevelModbusBridge.st",
    ]

    for rel in rel_paths:
        user_file = USER_ROOT / rel
        horner_file = HORNER_ROOT / rel

        assert user_file.exists(), f"Missing user file: {user_file}"
        assert horner_file.exists(), f"Missing horner file: {horner_file}"

        user_digest = hashlib.sha256(user_file.read_bytes()).hexdigest()
        horner_digest = hashlib.sha256(horner_file.read_bytes()).hexdigest()

        assert user_digest == horner_digest, f"Digest mismatch on {rel}: {user_digest} vs {horner_digest}"


# =============================================================================
# 10. Fail-Closed Security Invariants
# =============================================================================

from src.security.policy import SafetyPolicy


def test_security_hardware_lockout_invariant():
    """Verify SecurityGuard and SafetyPolicy continue to fail closed on physical serial/COM ports."""
    policy = SafetyPolicy()
    assert policy.is_port_blocked("COM1") is True
    assert policy.is_port_blocked("COM4") is True
    assert policy.is_port_blocked(r"\\.\COM1") is True

    guard = SecurityGuard()
    with pytest.raises(HardwareLockoutError):
        guard.validate_command("python test.py --port COM1")


def test_no_live_claims_contract():
    """Verify contract forbids VERIFIED_LIVE pseudo-status on pure software simulation."""
    res = cscape_simulate_pou(
        code=FB_MODBUS_SCALE_QUALITY_ST,
        inputs={"RawInput": 17600},
        steps=1,
        mode="LIVE",
    )
    assert res["status"] == "failed"
    assert res["error_code"] == "ERR_VERIFIED_LIVE_PROHIBITED_ON_SIMULATION"
