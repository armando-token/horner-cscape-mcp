"""Tests for Phase P9: Plan v3 Offline Gaps Resolution.

Covers:
1. IEC 61131-3 TYPE ... END_TYPE, STRUCT, ENUM, Subranges AST & Parser Extension.
2. Semantic Range & Multi-Word Footprint Bounds Checking for Horner OCS Registers.
3. Structured Modal Dialog Diagnostics Harvester.
4. Air-Gapped Offline Packaging MCP Tool (cscape_package_offline_bundle).
5. Explicit Emulated Provenance Headers across Simulation & Variables MCP tools.
6. FastMCP 40-Tool Registry & Schema Parity (100% matching).
"""

import json
import zipfile
from pathlib import Path
import pytest

from src.iec.ast_nodes import (
    ProgramNode,
    TypeBlockNode,
    TypeDeclNode,
    TypeDefNode,
    StructTypeNode,
    EnumTypeNode,
    SubrangeTypeNode,
    AliasTypeNode,
)
from src.iec.parser import Parser
from src.iec.validator import IECValidator
from src.cscape.variables import HornerRegister
from src.cscape.lifecycle import (
    harvest_modal_dialog_diagnostics,
    harvest_all_modal_diagnostics,
)
from src.mcp.server import create_mcp_server
from src.mcp.schemas import (
    TOOL_SCHEMAS,
    CscapePackageOfflineBundleInput,
    CscapePackageOfflineBundleOutput,
)
from src.mcp.tools import (
    cscape_package_offline_bundle,
    cscape_validate_st,
    cscape_read_variables,
    cscape_write_variables,
    cscape_read_register,
    cscape_write_register,
    cscape_inspect_variables,
    cscape_simulate_cycle,
    cscape_simulate_pou,
)


# =============================================================================
# 1. IEC 61131-3 TYPE ... END_TYPE, STRUCT, ENUM, Subranges AST & Parser
# =============================================================================

def test_p9_iec_type_struct_enum_subrange_parsing():
    """Verify IEC 61131-3 parser parses TYPE blocks with STRUCT, ENUM, and subrange types."""
    st_code = """
TYPE
    E_PumpState : (STOPPED, STARTING, RUNNING, FAULT);
    T_Pressure : INT (0..100);
    T_FlowRate : REAL;
    ST_PumpData : STRUCT
        State : E_PumpState;
        Pressure : T_Pressure;
        Flow : T_FlowRate;
        Running : BOOL;
    END_STRUCT;
END_TYPE

PROGRAM Main
VAR
    Pump1 : ST_PumpData;
    AutoMode : BOOL := TRUE;
END_VAR

IF AutoMode THEN
    Pump1.Running := TRUE;
END_IF;
END_PROGRAM
"""
    ast = Parser.from_source(st_code).parse()
    assert isinstance(ast, ProgramNode)
    assert len(ast.type_blocks) == 1

    tb = ast.type_blocks[0]
    assert isinstance(tb, TypeBlockNode)
    assert len(tb.types) == 4

    # 1. Enum
    t0 = tb.types[0]
    assert isinstance(t0, TypeDeclNode)
    assert t0.name == "E_PumpState"
    assert isinstance(t0.type_def, EnumTypeNode)
    assert t0.type_def.values == ["STOPPED", "STARTING", "RUNNING", "FAULT"]

    # 2. Subrange
    t1 = tb.types[1]
    assert isinstance(t1, TypeDeclNode)
    assert t1.name == "T_Pressure"
    assert isinstance(t1.type_def, SubrangeTypeNode)
    assert t1.type_def.base_type == "INT"
    assert t1.type_def.lower_bound == 0
    assert t1.type_def.upper_bound == 100

    # 3. Alias
    t2 = tb.types[2]
    assert isinstance(t2, TypeDeclNode)
    assert t2.name == "T_FlowRate"
    assert isinstance(t2.type_def, AliasTypeNode)
    assert t2.type_def.target_type == "REAL"

    # 4. Struct
    t3 = tb.types[3]
    assert isinstance(t3, TypeDeclNode)
    assert t3.name == "ST_PumpData"
    assert isinstance(t3.type_def, StructTypeNode)
    assert len(t3.type_def.members) == 4
    assert t3.type_def.members[0].name == "State"
    assert t3.type_def.members[0].data_type == "E_PumpState"
    assert t3.type_def.members[1].name == "Pressure"
    assert t3.type_def.members[1].data_type == "T_Pressure"
    assert t3.type_def.members[2].name == "Flow"
    assert t3.type_def.members[2].data_type == "T_FlowRate"
    assert t3.type_def.members[3].name == "Running"
    assert t3.type_def.members[3].data_type == "BOOL"

    # Verify roundtrip to ST contains TYPE and END_TYPE and STRUCT
    st_roundtrip = ast.to_st()
    assert "TYPE" in st_roundtrip
    assert "END_TYPE" in st_roundtrip
    assert "STRUCT" in st_roundtrip
    assert "END_STRUCT" in st_roundtrip

    # Verify IECValidator validates clean code with TYPE definitions
    val_res = IECValidator.validate(st_code)
    assert val_res.get("valid") is True
    assert len(val_res.get("errors", [])) == 0


# =============================================================================
# 2. Semantic Range & Multi-Word Footprint Bounds Checking for Horner OCS Registers
# =============================================================================

def test_p9_horner_register_bounds_checking():
    """Verify single-register index bounds and multi-word footprint span bounds checking."""
    # Valid registers
    r1 = HornerRegister.parse("%R100")
    assert r1.is_within_bounds() is True
    assert r1.spans_within_bounds("INT") is True
    assert r1.spans_within_bounds("REAL") is True

    ai_max = HornerRegister.parse("%AI512")
    assert ai_max.is_within_bounds() is True

    # Out-of-bounds single register
    with pytest.raises(ValueError, match="out of bounds"):
        HornerRegister.parse("%R10000")

    with pytest.raises(ValueError, match="out of bounds"):
        HornerRegister.parse("%AI513")

    # Multi-word span overflow: %R9999 with REAL (2 words: %R9999 + %R10000)
    r9999 = HornerRegister.parse("%R9999")
    assert r9999.is_within_bounds() is True
    assert r9999.spans_within_bounds("INT") is True  # 1 word fits (%R9999)
    assert r9999.spans_within_bounds("REAL") is False  # 2 words overflow into %R10000
    assert r9999.spans_within_bounds("DINT") is False  # 2 words overflow into %R10000
    assert r9999.spans_within_bounds("LREAL") is False  # 4 words overflow

    # Multi-word span overflow on system registers: %SR256 (max is 256)
    sr256 = HornerRegister.parse("%SR256")
    assert sr256.is_within_bounds() is True
    assert sr256.spans_within_bounds("INT") is True
    assert sr256.spans_within_bounds("DINT") is False  # spans %SR256-%SR257


def test_p9_register_footprint_in_st_validation_fails_closed():
    """Verify ST validation fails closed when multi-word register footprint overflows."""
    code_overflow = """
PROGRAM TestOverflow
VAR
    SensorValue AT %R9999 : REAL;
END_VAR
SensorValue := 10.5;
END_PROGRAM
"""
    res = cscape_validate_st(code_overflow)
    assert res.get("valid") is False
    assert res.get("status") == "failed"
    assert res.get("error_code") == "ERR_REGISTER_OUT_OF_BOUNDS"
    assert any("exceeding %R maximum limit" in e or "exceeding" in e.lower() for e in res.get("errors", []))
    assert res.get("failure_location") is not None
    assert res.get("failure_location", {}).get("line") == 3


# =============================================================================
# 3. Structured Modal Dialog Diagnostics Harvester
# =============================================================================

def test_p9_modal_dialog_diagnostics_harvester_fails_closed_on_invalid_hwnd():
    """Verify dialog harvester fails closed gracefully on invalid/zero HWND without crashing."""
    diag = harvest_modal_dialog_diagnostics(hwnd=0)
    assert diag.get("hwnd") == 0
    assert diag.get("status") == "inconclusive"
    assert "Invalid or non-existent window handle" in diag.get("error", "")
    assert diag.get("static_texts") == []
    assert diag.get("buttons") == []


def test_p9_harvest_all_modal_diagnostics_runs_cleanly():
    """Verify harvest_all_modal_diagnostics runs safely and returns a list without crashing."""
    diags = harvest_all_modal_diagnostics()
    assert isinstance(diags, list)
    for d in diags:
        assert "hwnd" in d
        assert "title" in d
        assert "classification" in d
        assert "static_texts" in d
        assert "buttons" in d


# =============================================================================
# 4. Air-Gapped Offline Packaging MCP Tool
# =============================================================================

def test_p9_package_offline_bundle_creates_valid_bundle(tmp_path):
    """Verify cscape_package_offline_bundle packages project files, manifest, and instructions."""
    bundle_res = cscape_package_offline_bundle(
        project_name="TankLevel_P5_Dedicated",
        output_dir=str(tmp_path),
        bundle_name="test_bundle",
        include_st_sources=True,
        include_manifest=True,
        include_manual_guide=True,
    )
    assert bundle_res.get("success") is True
    assert bundle_res.get("status") == "success"
    assert bundle_res.get("provenance") == "OFFLINE_BUNDLE"
    assert bundle_res.get("hardware_connected") is False
    assert bundle_res.get("isolation_enforced") is True

    zip_path = Path(bundle_res["bundle_path"])
    assert zip_path.exists()
    assert zip_path.stat().st_size > 0

    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()
        assert "MANIFEST-SHA256.json" in namelist
        assert "docs/MANUAL_LOADING_INSTRUCTIONS.md" in namelist

        # Validate manifest contents
        manifest_data = json.loads(zf.read("MANIFEST-SHA256.json").decode("utf-8"))
        assert manifest_data.get("project_name") == "TankLevel_P5_Dedicated"
        assert manifest_data.get("provenance") == "OFFLINE_AIRGAPPED_BUNDLE"
        assert len(manifest_data.get("files", {})) >= 3


def test_p9_package_offline_bundle_fails_closed_on_invalid_project():
    """Verify cscape_package_offline_bundle fails closed on nonexistent project or path traversal."""
    res_not_found = cscape_package_offline_bundle(project_name="NonExistentProj_XYZ123")
    assert res_not_found.get("success") is False
    assert res_not_found.get("status") == "failed"
    assert res_not_found.get("error_code") == "PROJECT_NOT_FOUND"

    res_traversal = cscape_package_offline_bundle(project_name="../../etc/shadow")
    assert res_traversal.get("success") is False
    assert res_traversal.get("status") == "failed"
    assert res_traversal.get("error_code") == "INVALID_PROJECT_NAME"


# =============================================================================
# 5. Explicit Emulated Provenance Headers in Simulation & Variables Tools
# =============================================================================

def test_p9_provenance_headers_across_offline_tools(tmp_path):
    """Verify that all offline simulation and variables tools declare mock provenance."""
    # 1. cscape_read_register
    r_res = cscape_read_register(address="%R100")
    assert r_res.get("provenance") == "TESTED_MOCK [offline/DEV only]"
    assert r_res.get("hardware_connected") is False
    assert r_res.get("isolation_enforced") is True

    # 2. cscape_write_register
    w_res = cscape_write_register(address="%R100", value=42, data_type="INT")
    assert w_res.get("provenance") == "TESTED_MOCK [offline/DEV only]"
    assert w_res.get("hardware_connected") is False
    assert w_res.get("isolation_enforced") is True

    # 3. cscape_simulate_cycle
    c_res = cscape_simulate_cycle(dt_ms=50.0)
    assert c_res.get("provenance") == "TESTED_MOCK [offline/DEV only]"
    assert c_res.get("hardware_connected") is False
    assert c_res.get("isolation_enforced") is True

    # 4. cscape_simulate_pou
    st_code = """
PROGRAM SimTest
VAR
    InVal AT %AI1 : INT;
    OutVal AT %AQ1 : INT;
END_VAR
OutVal := InVal * 2;
END_PROGRAM
"""
    p_res = cscape_simulate_pou(code=st_code, inputs={"InVal": 10}, steps=2)
    assert p_res.get("provenance") == "TESTED_MOCK [offline/DEV only]"
    assert p_res.get("hardware_connected") is False
    assert p_res.get("isolation_enforced") is True

    # 5. cscape_write_variables & cscape_read_variables
    csv_file = tmp_path / "test_vars.csv"
    vars_to_write = [
        {"name": "PumpRun", "data_type": "BOOL", "address": "%Q1", "scope": "VAR_OUTPUT", "comment": "Pump running bit"}
    ]
    wv_res = cscape_write_variables(output_path=str(csv_file), variables=vars_to_write)
    assert wv_res.get("provenance") == "TESTED_MOCK [offline/DEV only]"
    assert wv_res.get("hardware_connected") is False
    assert wv_res.get("isolation_enforced") is True

    rv_res = cscape_read_variables(file_path=str(csv_file))
    assert rv_res.get("provenance") == "TESTED_MOCK [offline/DEV only]"
    assert rv_res.get("hardware_connected") is False
    assert rv_res.get("isolation_enforced") is True

    # 6. cscape_inspect_variables
    iv_res = cscape_inspect_variables(project_name="TankLevel_P5_Dedicated")
    assert iv_res.get("provenance") == "TESTED_MOCK [offline/DEV only]"
    assert iv_res.get("hardware_connected") is False
    assert iv_res.get("isolation_enforced") is True


# =============================================================================
# 6. FastMCP Tool Registry & Schema Parity
# =============================================================================

@pytest.mark.asyncio
async def test_p9_fastmcp_40_tools_registered_and_matched():
    """Verify that all tools are registered on the FastMCP server and in TOOL_SCHEMAS (43 tools)."""
    srv = create_mcp_server()
    tools = await srv.list_tools()
    tool_names = {t.name for t in tools}

    assert len(tools) == 43, f"Expected exactly 43 FastMCP tools, got {len(tools)}"
    assert len(TOOL_SCHEMAS) == 43, f"Expected exactly 43 tool schemas, got {len(TOOL_SCHEMAS)}"

    # 100% parity assertion
    schema_names = set(TOOL_SCHEMAS.keys())
    assert tool_names == schema_names, (
        f"Mismatch between announced FastMCP tools and schemas! "
        f"Missing in schemas: {tool_names - schema_names}; "
        f"Extra in schemas: {schema_names - tool_names}"
    )
    assert "cscape_package_offline_bundle" in tool_names
    assert "cscape_validate_scan_list_evidence" in tool_names
    assert "cscape_inspect_scan_list" in tool_names
    assert "cscape_reconcile_scan_list" in tool_names
