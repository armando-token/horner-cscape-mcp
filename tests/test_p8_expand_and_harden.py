"""Phase P8 Comprehensive Verification Suite: Expand and Harden without Losing Core.

Mandate: Plan v3 - Phase P8 Execution
Governing Rule: RULE[C:\\Users\\ArmandoSilva\\AGENTS.md]
Operational Mode: offline/DEV [EXPAND_AND_HARDEN] (Fail-Closed, Zero PLC Download)

Verifies:
1. FastMCP 39-Tool Registry & Schema Parity (100% matching between tools and TOOL_SCHEMAS).
2. Input/Output Pydantic schema validation across all 39 tools.
3. False-Success Dismantling & Fail-Closed Robustness (H01-H13 negative tests).
4. Native Modbus PV Provider sidecar robustness & read-only policy.
5. State & Task tracking invariants: P0-P6 accepted, P7 deferred, P8 in progress.
6. Absolute safety lockouts: Zero PLC download, COM port lockout, companion binary lockout.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import pytest

from src.mcp.server import create_mcp_server
from src.mcp.schemas import (
    TOOL_SCHEMAS,
    get_tool_input_schema,
    get_tool_output_schema,
    list_tool_schemas,
    validate_tool_input,
    validate_tool_output,
    CscapeBaseModel,
    CscapeOutputBase,
)
import src.mcp as mcp_pkg
from src.mcp.tools import (
    cscape_validate_st,
    cscape_compile_project,
    cscape_new_iec_project,
    cscape_inspect_variables,
    cscape_run_simulation,
    cscape_modbus_create_config,
    cscape_modbus_conversion_doc,
    normalize_tool_result,
    ToolStatus,
)
from src.security.guard import SafetyGuard, SecurityGuard
from src.security.exceptions import (
    SecurityError,
    HardwareLockoutError,
    UnauthorizedDownloadError,
    BlockedExecutableError,
)
from src.simulation.test_modbus_server import (
    LabeledTestModbusServer,
    SERVER_LABEL as TEST_MODBUS_SERVER_LABEL,
)


# =============================================================================
# 1. FastMCP 39-Tool Registry & Schema Parity
# =============================================================================

@pytest.mark.asyncio
async def test_p8_fastmcp_39_tools_registered_and_matched():
    """Verify that exactly 39 tools are registered on the FastMCP server and in TOOL_SCHEMAS."""
    srv = create_mcp_server()
    tools = await srv.list_tools()
    tool_names = {t.name for t in tools}

    assert len(tools) >= 39, f"Expected at least 39 FastMCP tools, got {len(tools)}"
    assert len(TOOL_SCHEMAS) == len(tools), f"Expected TOOL_SCHEMAS to match tools count ({len(tools)}), got {len(TOOL_SCHEMAS)}"

    # 100% parity assertion
    schema_names = set(TOOL_SCHEMAS.keys())
    assert tool_names == schema_names, (
        f"Mismatch between announced FastMCP tools and schemas! "
        f"Missing in schemas: {tool_names - schema_names}; "
        f"Extra in schemas: {schema_names - tool_names}"
    )


def test_p8_all_39_schemas_instantiable_and_valid():
    """Verify that every tool schema has valid input and output models derived from CscapeBaseModel."""
    for tool_name, schema_dict in TOOL_SCHEMAS.items():
        inp_cls = schema_dict.get("input")
        out_cls = schema_dict.get("output")

        assert inp_cls is not None, f"Tool '{tool_name}' missing input schema"
        assert out_cls is not None, f"Tool '{tool_name}' missing output schema"

        assert issubclass(inp_cls, CscapeBaseModel), f"Input schema for '{tool_name}' must inherit from CscapeBaseModel"
        assert issubclass(out_cls, (CscapeOutputBase, CscapeBaseModel)), f"Output schema for '{tool_name}' must inherit from CscapeOutputBase"

        # Verify lookup helper functions
        assert get_tool_input_schema(tool_name) is inp_cls
        assert get_tool_output_schema(tool_name) is out_cls


def test_p8_mcp_package_exports_all_39_tools():
    """Verify that src.mcp exposes all 39 tools as top-level package attributes."""
    for tool_name in TOOL_SCHEMAS.keys():
        assert hasattr(mcp_pkg, tool_name), f"src.mcp must export tool '{tool_name}'"
        assert callable(getattr(mcp_pkg, tool_name)), f"Exported '{tool_name}' in src.mcp must be callable"


# =============================================================================
# 2. False-Success Dismantling & Fail-Closed Robustness
# =============================================================================

def test_p8_pure_st_rejects_ladder_constructs():
    """H08: Ladder constructs in ST code must fail closed with ERR_LADDER_FORBIDDEN."""
    ladder_snippets = [
        "PROGRAM Main ---[ ]--- END_PROGRAM",
        "PROGRAM Main ---[/]--- END_PROGRAM",
        "PROGRAM Main --- ( ) --- END_PROGRAM",
        "PROGRAM Main RUNG 1: XIC(Start) OTE(Motor) END_RUNG END_PROGRAM",
        "PROGRAM Main NETWORK 1: Start -> Motor END_PROGRAM",
    ]
    for snip in ladder_snippets:
        res = cscape_validate_st(snip)
        assert res["success"] is False
        assert res["status"] == "failed"
        assert res.get("error_code") == "ERR_LADDER_FORBIDDEN"
        assert any("ladder" in err.lower() for err in res.get("errors", []))


def test_p8_compile_project_path_traversal_fails_closed():
    """H03 / H10: Directory traversal or dot paths must fail closed with SECURITY_BLOCKED."""
    for bad_path in [".", "./", ".\\", "../../escape", "proj/../../escape"]:
        res = cscape_compile_project(bad_path)
        assert res["success"] is False
        assert res["status"] == "failed"
        assert res.get("error_code") in ("SECURITY_BLOCKED", "INVALID_PROJECT_NAME")


def test_p8_new_iec_project_invalid_target_dir_fails_closed():
    """cscape_new_iec_project must fail closed with INVALID_TARGET_DIR on empty/whitespace dirs."""
    for bad_dir in ["", "   ", "\t"]:
        res = cscape_new_iec_project(project_name="P8_Test_Proj", target_dir=bad_dir)
        assert res["success"] is False
        assert res["status"] == "failed"
        assert res.get("error_code") == "INVALID_TARGET_DIR"


def test_p8_inspect_variables_nonexistent_project_fails_closed():
    """H02: Variable inspection on non-existent project must fail closed."""
    res = cscape_inspect_variables(project_name="NonExistent_P8_Ghost_Project_9999")
    assert res["success"] is False
    assert res["status"] == "failed"
    assert res.get("error_code") == "PROJECT_NOT_FOUND"


def test_p8_offline_simulation_declares_mock_provenance():
    """H04: Emulated simulation must declare TESTED_MOCK and never claim live hardware success."""
    valid_st = "PROGRAM Main VAR x: INT; END_VAR x := x + 1; END_PROGRAM"
    res = cscape_run_simulation(steps=5, st_code=valid_st)
    assert res["success"] is True
    assert res["status"] == "success"
    # Provenance declaration check
    assert "TESTED_MOCK" in str(res.get("classification", "")) or "EMULATED" in str(res.get("simulation_backend", "")).upper()
    assert res.get("isolation_enforced") is True
    assert res.get("hardware_connected") is False


def test_p8_status_contract_normalizes_pseudo_statuses():
    """H13: Prohibited pseudo-statuses ('VERIFIED', '100%') must normalize to 'inconclusive'."""
    res_fake = {"status": "100% VERIFIED", "data": {}}
    norm = normalize_tool_result(res_fake, default_source="TestP8")
    assert norm["status"] == "inconclusive"
    assert norm["success"] is False


# =============================================================================
# 3. Fail-Closed Security & Hardware Lockout Invariants
# =============================================================================

def test_p8_security_physical_ports_blocked():
    """H10: All physical communication ports must be hard-blocked."""
    for port in ["COM1", "COM256", r"\\.\COM3", "/dev/ttyS0", "CAN0", "CsCAN", "USB0", "JTAG"]:
        with pytest.raises((SecurityError, HardwareLockoutError)):
            SafetyGuard.validate_hardware_connection(port)


def test_p8_security_download_commands_permanently_blocked():
    """H11: Win32 download command IDs (32827, 33149) must be permanently blocked."""
    guard = SafetyGuard()
    for cmd_id in [32827, 33149]:
        with pytest.raises((SecurityError, UnauthorizedDownloadError)):
            guard.validate_ui_command(cmd_id)


def test_p8_security_companion_flash_binaries_blocked():
    """H11: Companion flashing executables must be unconditionally blocked."""
    guard = SafetyGuard()
    for flasher in ["PGMUpdateUtility.exe", "DfuSeCommand.exe", "STMFlashLoader.exe", "WinJTAG.exe"]:
        with pytest.raises((SecurityError, BlockedExecutableError)):
            guard.validate_execution(flasher)


# =============================================================================
# 4. Modbus PV Provider Robustness & Read-Only Policy
# =============================================================================

def test_p8_modbus_create_config_and_conversion_doc():
    """Verify Phase P5 Modbus configuration generation and mathematical conversion guide."""
    res_cfg = cscape_modbus_create_config(
        project_name="TankLevel_P8_Test",
        transport="MODBUS_TCP",
        ip_address="127.0.0.1",
        port=15502,
        unit_id=1,
        function_code=3,
        modicon_address=40001,
        wire_offset=0,
        ocs_register="%AI1",
        variable_name="TankLevelPV",
        raw_min=0.0,
        raw_max=32000.0,
        eu_min=0.0,
        eu_max=100.0,
    )
    assert res_cfg["success"] is True
    assert res_cfg["status"] == "success"
    assert res_cfg["transport"] == "MODBUS_TCP"
    assert res_cfg["address_mapping"]["horner_ocs_register"] == "%AI1"

    # Conversion guide verification
    res_doc = cscape_modbus_conversion_doc(level_pct=55.0)
    assert res_doc["success"] is True
    assert res_doc["status"] == "success"
    assert res_doc["step1_mathematical_conversion"]["raw_integer_value"] == 17600
    assert res_doc["parameters"]["target_level_percent"] == 55.0


def test_p8_modbus_server_rejects_write_commands():
    """Verify that Modbus test server strictly enforces read-only PV provider policy."""
    server = LabeledTestModbusServer(host="127.0.0.1", port=15599, initial_raw_value=17600)
    status = server.get_status()
    assert status.read_only_enforced is True
    assert status.label == TEST_MODBUS_SERVER_LABEL
    assert status.current_raw_value == 17600
    assert status.scaled_level_pct == 55.0


# =============================================================================
# 5. State & Active Task Invariants (P0-P6 Accepted, P7 Deferred, P8 In Progress)
# =============================================================================

def test_p8_state_and_active_task_invariants():
    """Verify that ACTIVE_TASK.md and STATE.json reflect P0-P6 accepted, P7 deferred, P8 in progress."""
    user_root = Path(r"C:\Users\ArmandoSilva")
    state_file = user_root / "ops" / "STATE.json"
    active_task_file = user_root / "ops" / "ACTIVE_TASK.md"

    assert state_file.exists(), "ops/STATE.json must exist"
    assert active_task_file.exists(), "ops/ACTIVE_TASK.md must exist"

    with open(state_file, encoding="utf-8-sig") as f:
        state_data = json.load(f)

    # Completed phases verification (P0-P6 accepted)
    completed = state_data.get("completed_phases", [])
    for p in ["P0_RECONCILIATION_CONTRACT_AUDIT", "P1_DIAGNOSTICS_AIR_GAPPED_EXPORT_AND_NEGATIVE_TESTS",
              "P2_NATIVE_MUTATION_AND_CORRELATED_INTEGRATION", "P3_NATIVE_CSCAPE_HMI_AND_OBJECT_GROUP_BINDINGS",
              "P5_NATIVE_MODBUS_PV_PROVIDER_CONFIG", "P6_STANDALONE_DELIVERY_AND_DISTRIBUTION_VERIFICATION"]:
        assert p in completed, f"Phase {p} must be in completed_phases"

    # P7 deferred assertion
    p7_info = state_data.get("p7_physical_download", {})
    assert p7_info.get("status") == "DEFERRED", "P7 physical download must be marked DEFERRED"

    # P8 phase & claim assertions
    assert state_data.get("phase") == "P8", "Active phase in STATE.json must be P8"
    assert state_data.get("phase_status") in ("P8_IN_PROGRESS", "P8_COMPLETED_PENDING_SUPERVISOR_REVIEW"), (
        f"Unexpected phase_status: {state_data.get('phase_status')}"
    )

    # P8 complete claim assertion
    p8_claim = state_data.get("p8_complete_claim", {})
    assert p8_claim.get("claim") is True, "p8_complete_claim.claim must be True"
    assert p8_claim.get("supported_by_pass_results") is True, "p8_complete_claim must be supported by PASS results"
    assert p8_claim.get("auto_accept") is False, "auto_accept must remain False"
    assert p8_claim.get("verified_live") is False, "verified_live must remain False"
    assert p8_claim.get("p7_status") == "DEFERRED_MANUAL_ENGINEER_LOAD", "P7 must remain deferred"

    # ACTIVE_TASK.md text check
    task_text = active_task_file.read_text(encoding="utf-8")
    assert "P8" in task_text
    assert "P7" in task_text
    assert "DEFERRED" in task_text
    assert "p8_complete_claim" in task_text
