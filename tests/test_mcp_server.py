"""Comprehensive Test Suite for Horner Cscape MCP Server.

Validates:
- MCP Server instance configuration and registration
- All 8 core MCP tools:
  * cscape_create_project
  * cscape_add_st_pou
  * cscape_validate_st
  * cscape_inspect_variables
  * cscape_compile_project
  * cscape_get_diagnostics
  * cscape_simulate_pou
  * cscape_export_project
- MCP Resources reading & templating
- MCP Prompts generation & schema
- Safety guardrails (hardware lockout, parameter validation, ladder rejection)
"""

import json
import os
import shutil
import subprocess
import sys
import pytest
from pathlib import Path

from src.mcp.server import create_mcp_server, server, SERVER_NAME, SERVER_VERSION
from src.mcp.tools import (
    cscape_create_project,
    cscape_add_st_pou,
    cscape_insert_st,
    cscape_insert_st_pou,
    cscape_validate_st,
    cscape_inspect_variables,
    cscape_compile_project,
    cscape_get_diagnostics,
    cscape_simulate_pou,
    cscape_export_project,
)
from src.security.guard import SafetyGuard, SecurityError
from src.iec.validator import IECValidator
from src.iec.simulator import STSimulator
from src.iec.templates import get_template_catalog, get_template_code


@pytest.fixture(scope="module")
def test_project_name():
    return "test_unit_project"


@pytest.fixture(scope="module", autouse=True)
def cleanup_test_project(test_project_name):
    # Setup
    projects_dir = Path("C:/HornerAI/horner-cscape-mcp/artifacts/projects")
    proj_dir = projects_dir / test_project_name
    if proj_dir.exists():
        shutil.rmtree(proj_dir, ignore_errors=True)
    yield
    # Teardown
    if proj_dir.exists():
        shutil.rmtree(proj_dir, ignore_errors=True)


class TestMCPServerStructure:
    """Verifies MCP server metadata and tool/resource/prompt registration."""

    def test_server_metadata(self):
        assert server.name == SERVER_NAME
        assert server.version == SERVER_VERSION
        assert "Horner Cscape" in server.instructions
        assert "Hardware lockout" in server.instructions

    @pytest.mark.asyncio
    async def test_tools_registered(self):
        tools = await server.list_tools()
        tool_names = [t.name for t in tools]
        core_tools = [
            "cscape_launch_ide",
            "cscape_new_iec_project",
            "cscape_open_project",
            "cscape_insert_st",
            "cscape_insert_st_pou",
            "cscape_compile",
            "cscape_get_build_output",
            "cscape_read_variables",
            "cscape_write_variables",
            "cscape_import_variables",
            "cscape_export_variables",
            "cscape_run_simulation",
        ]
        simulation_tools = [
            "cscape_simulate_cycle",
            "cscape_read_register",
            "cscape_write_register",
        ]
        convenience_tools = [
            "cscape_create_project",
            "cscape_add_st_pou",
            "cscape_validate_st",
            "cscape_inspect_variables",
            "cscape_compile_project",
            "cscape_get_diagnostics",
            "cscape_simulate_pou",
            "cscape_export_project",
        ]
        hmi_tools = [
            "cscape_hmi_inventory",
            "cscape_hmi_apply_group",
            "cscape_hmi_read_properties",
            "cscape_hmi_verify_bindings",
            "cscape_hmi_save_close_reopen",
        ]
        all_expected = core_tools + simulation_tools + convenience_tools + hmi_tools
        assert len(tools) == len(all_expected) == 28
        for exp in all_expected:
            assert exp in tool_names, f"Tool '{exp}' missing from registered MCP tools."


    @pytest.mark.asyncio
    async def test_resources_registered(self):
        resources = await server.list_resources()
        uris = [str(r.uri) for r in resources]
        assert any("cscape://projects" in u for u in uris)
        assert any("cscape://templates" in u for u in uris)
        assert any("cscape://safety/status" in u for u in uris)

    @pytest.mark.asyncio
    async def test_prompts_registered(self):
        prompts = await server.list_prompts()
        prompt_names = [p.name for p in prompts]
        assert "generate_iec_st_controller" in prompt_names
        assert "refactor_ladder_to_st" in prompt_names
        assert "debug_st_diagnostics" in prompt_names
        assert "simulate_st_logic" in prompt_names


class TestSTValidator:
    """Verifies IEC 61131-3 Structured Text validation logic."""

    def test_valid_st_program(self):
        code = """PROGRAM PRG_Test
VAR_INPUT
    Start : BOOL;
    Stop : BOOL;
END_VAR
VAR_OUTPUT
    Running : BOOL;
END_VAR
IF Start AND NOT Stop THEN
    Running := TRUE;
ELSIF Stop THEN
    Running := FALSE;
END_IF;
END_PROGRAM
"""
        res = cscape_validate_st(code)
        assert res["valid"] is True
        assert res["pou_name"] == "PRG_Test"
        assert res["pou_type"] == "PROGRAM"
        assert len(res["variables"]) == 3
        assert len(res["errors"]) == 0

    def test_unclosed_block_detected(self):
        code = """PROGRAM PRG_Broken
VAR_INPUT
    A : BOOL;
END_VAR
IF A THEN
    A := FALSE;
(* Missing END_IF *)
END_PROGRAM
"""
        res = cscape_validate_st(code)
        assert res["valid"] is False
        assert any("Unclosed 'IF'" in e or "Mismatched" in e for e in res["errors"])

    def test_reject_ladder_logic(self):
        code = """PROGRAM PRG_Ladder
VAR
    In1 : BOOL;
    Out1 : BOOL;
END_VAR
---[ ]--- In1 --- ( ) --- Out1;
END_PROGRAM
"""
        res = cscape_validate_st(code)
        assert res["valid"] is False
        assert any("Ladder logic artifact detected" in e for e in res["errors"])


class TestProjectLifecycleTools:
    """Verifies project creation, POU injection, compilation, variable inspection, and export."""

    def test_cscape_create_project(self, test_project_name):
        res = cscape_create_project(
            name=test_project_name,
            description="Unit test project for Horner Cscape MCP",
            target_plc="T5RTI",
        )
        assert res["status"] == "success"
        assert res["project_name"] == test_project_name
        assert res["target_plc"] == "T5RTI"
        assert Path(res["project_path"]).exists()
        assert "cscape_project.json" in res["files_created"]

    def test_cscape_add_st_pou(self, test_project_name):
        pou_code = """FUNCTION_BLOCK FB_ConveyorTest
VAR_INPUT
    RunCmd : BOOL;
    PE_Sensor : BOOL;
END_VAR
VAR_OUTPUT
    MotorOut : BOOL;
    BoxCount : INT := 0;
END_VAR
IF RunCmd THEN
    MotorOut := TRUE;
    IF PE_Sensor THEN
        BoxCount := BoxCount + 1;
    END_IF;
ELSE
    MotorOut := FALSE;
END_IF;
END_FUNCTION_BLOCK
"""
        res = cscape_add_st_pou(
            project_name=test_project_name,
            pou_name="FB_ConveyorTest",
            pou_type="FUNCTION_BLOCK",
            code=pou_code,
            cycle_time_ms=10,
        )
        assert res["status"] == "success"
        assert res["pou_name"] == "FB_ConveyorTest"
        assert Path(res["file_path"]).exists()
        assert res["variables_count"] == 4

    def test_cscape_inspect_variables(self, test_project_name):
        res = cscape_inspect_variables(test_project_name)
        assert res["project_name"] == test_project_name
        assert res["total_variables"] >= 4
        assert "FB_ConveyorTest" in res["pous"]
        inputs = res["by_scope"]["inputs"]
        outputs = res["by_scope"]["outputs"]
        assert any(v["name"] == "RunCmd" for v in inputs)
        assert any(v["name"] == "MotorOut" for v in outputs)

    def test_cscape_compile_project(self, test_project_name):
        res = cscape_compile_project(test_project_name, clean_build=True)
        assert res["compile_successful"] is True
        assert res["clean_build"] is True
        assert res["project_name"] == test_project_name
        assert res["memory_footprint"]["code_size_bytes"] > 0
        assert len(res["pous_compiled"]) >= 1

    def test_cscape_get_diagnostics(self, test_project_name):
        res = cscape_get_diagnostics(test_project_name)
        assert res["project_name"] == test_project_name
        assert res["compile_successful"] is True
        assert "diagnostics" in res
        assert "memory_footprint" in res

    def test_cscape_export_project(self, test_project_name):
        # Test Native CSP export
        csp_res = cscape_export_project(test_project_name, output_format="csp")
        assert csp_res["status"] == "success"
        assert csp_res["output_format"] == "csp"
        assert Path(csp_res["export_file"]).exists()
        assert csp_res["size_bytes"] > 0
        assert len(csp_res["sha256"]) == 64

        # Test K5P export routes to quarantine
        k5p_res = cscape_export_project(test_project_name, output_format="k5p")
        assert k5p_res["status"] == "success"
        assert "warning" in k5p_res
        assert "quarantine" in k5p_res["export_file"]
        assert Path(k5p_res["export_file"]).exists()

        # Test ST export
        st_res = cscape_export_project(test_project_name, output_format="st")
        assert st_res["status"] == "success"
        assert Path(st_res["export_file"]).exists()

        # Test XML export
        xml_res = cscape_export_project(test_project_name, output_format="xml")
        assert xml_res["status"] == "success"
        assert Path(xml_res["export_file"]).exists()

        # Test JSON export
        json_res = cscape_export_project(test_project_name, output_format="json")
        assert json_res["status"] == "success"
        assert Path(json_res["export_file"]).exists()


class TestSTSimulator:
    """Verifies software simulation of Structured Text logic without hardware."""

    def test_simulate_counter_logic(self):
        code = """PROGRAM PRG_Counter
VAR_INPUT
    Pulse : BOOL;
    Reset : BOOL;
END_VAR
VAR_OUTPUT
    Count : INT := 0;
END_VAR
IF Reset THEN
    Count := 0;
ELSIF Pulse THEN
    Count := Count + 1;
END_IF;
END_PROGRAM
"""
        inputs = {"Pulse": True, "Reset": False}
        res = cscape_simulate_pou(code=code, inputs=inputs, steps=4)
        assert res["success"] is True
        assert res["steps_executed"] == 4
        assert len(res["trace"]) == 4
        assert res["final_state"]["Count"] == 4

    def test_simulate_step_inputs(self):
        code = """PROGRAM PRG_StepTest
VAR_INPUT
    InVal : INT;
END_VAR
VAR_OUTPUT
    OutVal : INT;
END_VAR
OutVal := InVal * 2;
END_PROGRAM
"""
        inputs = {"InVal": [10, 20, 30]}
        res = cscape_simulate_pou(code=code, inputs=inputs, steps=3)
        assert res["success"] is True
        assert res["trace"][0]["variables"]["OutVal"] == 20
        assert res["trace"][1]["variables"]["OutVal"] == 40
        assert res["trace"][2]["variables"]["OutVal"] == 60


class TestMCPAsyncCalls:
    """Verifies executing tools, resources, and prompts through the MCPServer interface."""

    @pytest.mark.asyncio
    async def test_call_tool_validate_st(self):
        code = "PROGRAM P\nVAR\n  x: INT;\nEND_VAR\n  x := 10;\nEND_PROGRAM"
        res = await server.call_tool("cscape_validate_st", {"code": code})
        assert not res.is_error
        assert len(res.content) > 0
        data = json.loads(res.content[0].text)
        assert data["valid"] is True

    @pytest.mark.asyncio
    async def test_call_tool_simulate(self):
        code = "PROGRAM P\nVAR_INPUT\n  in: INT;\nEND_VAR\nVAR_OUTPUT\n  out: INT;\nEND_VAR\nout := in + 5;\nEND_PROGRAM"
        res = await server.call_tool("cscape_simulate_pou", {"code": code, "inputs": {"in": 7}, "steps": 2})
        assert not res.is_error
        data = json.loads(res.content[0].text)
        assert data["success"] is True
        assert data["final_state"]["out"] == 12

    @pytest.mark.asyncio
    async def test_call_tool_lifecycle_pipeline(self):
        proj = "async_mcp_test_proj"
        # 1. cscape_create_project
        res_create = await server.call_tool("cscape_create_project", {"name": proj, "description": "Async test"})
        assert not res_create.is_error
        data_create = json.loads(res_create.content[0].text)
        assert data_create["status"] in ("success", "exists")

        # 2. cscape_add_st_pou
        pou_code = "PROGRAM P_Main\nVAR\n  Run: BOOL := TRUE;\n  Count: INT := 0;\nEND_VAR\n  IF Run THEN\n    Count := Count + 1;\n  END_IF;\nEND_PROGRAM"
        res_add = await server.call_tool("cscape_add_st_pou", {
            "project_name": proj,
            "pou_name": "P_Main",
            "pou_type": "PROGRAM",
            "code": pou_code,
            "cycle_time_ms": 20
        })
        assert not res_add.is_error
        data_add = json.loads(res_add.content[0].text)
        assert data_add["status"] == "success"

        # 3. cscape_inspect_variables
        res_vars = await server.call_tool("cscape_inspect_variables", {"project_name": proj})
        assert not res_vars.is_error
        data_vars = json.loads(res_vars.content[0].text)
        assert data_vars["total_variables"] >= 2

        # 4. cscape_compile_project
        res_compile = await server.call_tool("cscape_compile_project", {"project_name": proj, "clean_build": True})
        assert not res_compile.is_error
        data_compile = json.loads(res_compile.content[0].text)
        assert data_compile["compile_successful"] is True

        # 5. cscape_get_diagnostics
        res_diag = await server.call_tool("cscape_get_diagnostics", {"project_name": proj})
        assert not res_diag.is_error
        data_diag = json.loads(res_diag.content[0].text)
        assert data_diag["compile_successful"] is True

        # 6. cscape_export_project
        res_export = await server.call_tool("cscape_export_project", {"project_name": proj, "output_format": "csp"})
        assert not res_export.is_error
        data_export = json.loads(res_export.content[0].text)
        assert data_export["status"] == "success"

        # Cleanup
        projects_dir = Path("C:/HornerAI/horner-cscape-mcp/artifacts/projects")
        shutil.rmtree(projects_dir / proj, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_call_9_core_tools_pipeline(self):
        """Verifies that all 9 native Cscape 10.2 MCP tools execute cleanly and return structured JSON."""
        proj = "core_tools_test_proj"
        projects_dir = Path("C:/HornerAI/horner-cscape-mcp/artifacts/projects")
        proj_dir = projects_dir / proj
        shutil.rmtree(proj_dir, ignore_errors=True)

        try:
            # 1. cscape_launch_ide
            res_launch = await server.call_tool("cscape_launch_ide", {"headless": True, "timeout_seconds": 0.5})
            assert not res_launch.is_error
            d_launch = json.loads(res_launch.content[0].text)
            assert "success" in d_launch
            assert "lifecycle_state" in d_launch

            # 2. cscape_new_iec_project (Happy + Error path)
            res_new = await server.call_tool("cscape_new_iec_project", {
                "project_name": proj,
                "target_dir": str(projects_dir),
                "controller_model": "XL4",
            })
            assert not res_new.is_error
            d_new = json.loads(res_new.content[0].text)
            assert d_new["success"] is True
            assert Path(d_new["project_file"]).exists()

            res_new_err = await server.call_tool("cscape_new_iec_project", {
                "project_name": "CON",
                "target_dir": str(projects_dir),
            })
            assert not res_new_err.is_error
            d_new_err = json.loads(res_new_err.content[0].text)
            assert d_new_err["success"] is False

            # 3. cscape_open_project (Happy + Error path)
            csp_path = str(proj_dir / f"{proj}.csp")
            res_open = await server.call_tool("cscape_open_project", {"file_path": csp_path})
            assert not res_open.is_error
            d_open = json.loads(res_open.content[0].text)
            assert d_open["success"] is True
            assert d_open["is_valid_cfbf"] is True

            res_open_err = await server.call_tool("cscape_open_project", {"file_path": "non_existent.csp"})
            assert not res_open_err.is_error
            d_open_err = json.loads(res_open_err.content[0].text)
            assert d_open_err["success"] is False

            # 4. cscape_insert_st (Happy + Ladder rejection error path)
            st_code = "PROGRAM CoreMain\nVAR\n  Speed : INT := 100;\nEND_VAR\n  Speed := Speed + 10;\nEND_PROGRAM"
            res_st = await server.call_tool("cscape_insert_st", {
                "pou_name": "CoreMain",
                "pou_type": "PROGRAM",
                "st_code": st_code,
                "target_project_path": str(proj_dir),
            })
            assert not res_st.is_error
            d_st = json.loads(res_st.content[0].text)
            assert d_st["success"] is True
            assert d_st["syntax_valid"] is True

            ladder_code = "PROGRAM LadderTest\n---[ ]--- X1 --- ( ) --- Y1;\nEND_PROGRAM"
            res_st_err = await server.call_tool("cscape_insert_st", {
                "pou_name": "LadderTest",
                "pou_type": "PROGRAM",
                "st_code": ladder_code,
            })
            assert not res_st_err.is_error
            d_st_err = json.loads(res_st_err.content[0].text)
            assert d_st_err["success"] is False
            assert "Advanced Ladder rejected" in d_st_err["message"]

            # 5. cscape_compile
            res_compile = await server.call_tool("cscape_compile", {
                "project_path": str(proj_dir),
                "clean_build": True,
            })
            assert not res_compile.is_error
            d_compile = json.loads(res_compile.content[0].text)
            assert "success" in d_compile
            assert d_compile["hardware_lockout_enforced"] is True

            # 6. cscape_get_build_output
            res_build = await server.call_tool("cscape_get_build_output", {
                "project_path": str(proj_dir),
            })
            assert not res_build.is_error
            d_build = json.loads(res_build.content[0].text)
            assert d_build["success"] is True

            # 7. cscape_import_variables (Happy + Error path)
            csv_file = proj_dir / "test_vars.csv"
            csv_file.write_text("Name,Type,Address,Scope\nMotorRun,BOOL,%M0010,GLOBAL\n", encoding="utf-8")
            res_imp = await server.call_tool("cscape_import_variables", {"file_path": str(csv_file)})
            assert not res_imp.is_error
            d_imp = json.loads(res_imp.content[0].text)
            assert d_imp["success"] is True
            assert d_imp["imported_count"] >= 1

            res_imp_err = await server.call_tool("cscape_import_variables", {"file_path": "missing.invalid"})
            assert not res_imp_err.is_error
            d_imp_err = json.loads(res_imp_err.content[0].text)
            assert d_imp_err["success"] is False

            # 8. cscape_export_variables (Happy + Error path)
            out_csv = proj_dir / "out_vars.csv"
            res_exp = await server.call_tool("cscape_export_variables", {"output_path": str(out_csv), "format_type": "CSV"})
            assert not res_exp.is_error
            d_exp = json.loads(res_exp.content[0].text)
            assert d_exp["success"] is True
            assert out_csv.exists()

            res_exp_err = await server.call_tool("cscape_export_variables", {"output_path": "test.dat", "format_type": "UNKNOWN"})
            assert not res_exp_err.is_error
            d_exp_err = json.loads(res_exp_err.content[0].text)
            assert d_exp_err["success"] is False

            # 9. cscape_run_simulation (Code mode + Raw register mode + Error path)
            res_sim1 = await server.call_tool("cscape_run_simulation", {
                "steps": 3,
                "st_code": st_code,
            })
            assert not res_sim1.is_error
            d_sim1 = json.loads(res_sim1.content[0].text)
            assert d_sim1["success"] is True
            assert len(d_sim1["trace"]) == 3

            res_sim2 = await server.call_tool("cscape_run_simulation", {"steps": 2})
            assert not res_sim2.is_error
            d_sim2 = json.loads(res_sim2.content[0].text)
            assert d_sim2["success"] is True
            assert d_sim2["total_cycles"] == 2

            res_sim_err = await server.call_tool("cscape_run_simulation", {"steps": -1})
            assert not res_sim_err.is_error
            d_sim_err = json.loads(res_sim_err.content[0].text)
            assert d_sim_err["success"] is False
            assert "Simulation error" in d_sim_err["message"]

        finally:
            shutil.rmtree(proj_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_read_resource_templates(self):
        res = await server.read_resource("cscape://templates")
        assert len(res) > 0
        data = json.loads(res[0].content)
        assert "templates" in data
        assert data["total_count"] >= 5

    @pytest.mark.asyncio
    async def test_read_resource_safety_status(self):
        res = await server.read_resource("cscape://safety/status")
        assert len(res) > 0
        data = json.loads(res[0].content)
        assert data["hardware_lockout_active"] is True
        assert data["physical_plc_allowed"] is False
        assert data["controller_download_allowed"] is False

    @pytest.mark.asyncio
    async def test_read_resource_template_content(self):
        res = await server.read_resource("cscape://template/motor_starter")
        assert len(res) > 0
        assert "FB_MotorStarter" in res[0].content

    @pytest.mark.asyncio
    async def test_get_prompt_generate_controller(self):
        p = await server.get_prompt(
            "generate_iec_st_controller",
            {"application_type": "Pump Station", "requirements": "Lead-lag alternating 2 pumps with high level float", "target_plc": "T5RTI"}
        )
        assert len(p.messages) > 0
        content = p.messages[0].content.text
        assert "Pump Station" in content
        assert "T5RTI" in content
        assert "PURE STRUCTURED TEXT" in content


class TestSafetyGuardrails:
    """Verifies security rules, hardware isolation, and input validation."""

    def test_forbid_path_traversal(self):
        with pytest.raises(SecurityError):
            SafetyGuard.validate_project_name("../../../malicious")

    def test_forbid_reserved_names(self):
        with pytest.raises(SecurityError):
            SafetyGuard.validate_project_name("CON")
        with pytest.raises(SecurityError):
            SafetyGuard.validate_project_name("COM1")

    def test_forbid_invalid_pou_name(self):
        with pytest.raises(SecurityError):
            SafetyGuard.validate_pou_name("123_invalid_start")
        with pytest.raises(SecurityError):
            SafetyGuard.validate_pou_name("bad name with spaces")

    def test_forbid_unsupported_target_plc(self):
        with pytest.raises(SecurityError):
            SafetyGuard.validate_target_plc("UNSUPPORTED_HW_CHIP")

    def test_assert_compile_only_blocks_download(self):
        with pytest.raises(SecurityError):
            SafetyGuard.assert_compile_only("download_to_controller")
        with pytest.raises(SecurityError):
            SafetyGuard.assert_compile_only("flash_firmware")

    def test_safety_status_structure(self):
        status = SafetyGuard.get_safety_status()
        assert status["hardware_lockout_active"] is True
        assert status["physical_plc_allowed"] is False
        assert "COM*" in status["blocked_ports"]
        assert "PGMUpdateUtility.exe" in status["blocked_executables"]


class TestCscapeInsertSTPOUAudit:
    """Subagent 10 Audit: Full verification of MCP tool cscape_insert_st_pou.

    1. Verify input arguments: project_path, pou_name, st_code, pou_type.
    2. Confirm ST code syntax validation prior to insertion.
    3. Confirm rejection of ladder logic constructs before calling Cscape automation.
    """

    def test_insert_st_pou_input_arguments_named(self, tmp_path):
        """1. Verify input arguments: project_path, pou_name, st_code, pou_type (named kwargs)."""
        proj_dir = tmp_path / "AuditProjNamed"
        proj_dir.mkdir()
        st_code = """PROGRAM PRG_AuditTest
VAR
    Run : BOOL := FALSE;
    Counter : DINT := 0;
END_VAR
IF Run THEN
    Counter := Counter + 1;
END_IF;
END_PROGRAM
"""
        res = cscape_insert_st_pou(
            project_path=str(proj_dir),
            pou_name="PRG_AuditTest",
            st_code=st_code,
            pou_type="PROGRAM",
        )
        assert res["success"] is True
        assert res["syntax_valid"] is True
        assert res["pou_name"] == "PRG_AuditTest"
        assert res["pou_type"] == "PROGRAM"
        assert len(res["code_hash"]) == 64
        assert res["line_count"] > 0
        assert res["variable_count"] == 2
        assert (proj_dir / "pous" / "PRG_AuditTest.st").exists()
        saved_code = (proj_dir / "pous" / "PRG_AuditTest.st").read_text(encoding="utf-8")
        assert "PROGRAM PRG_AuditTest" in saved_code

    def test_insert_st_pou_input_arguments_positional(self, tmp_path):
        """1. Verify input arguments: project_path, pou_name, st_code, pou_type (positional)."""
        proj_dir = tmp_path / "AuditProjPos"
        proj_dir.mkdir()
        st_code = """FUNCTION_BLOCK FB_Positional
VAR_INPUT
    Start : BOOL;
END_VAR
VAR_OUTPUT
    Active : BOOL;
END_VAR
Active := Start;
END_FUNCTION_BLOCK
"""
        res = cscape_insert_st_pou(
            str(proj_dir),
            "FB_Positional",
            st_code,
            "FUNCTION_BLOCK",
        )
        assert res["success"] is True
        assert res["syntax_valid"] is True
        assert res["pou_name"] == "FB_Positional"
        assert res["pou_type"] == "FUNCTION_BLOCK"
        assert (proj_dir / "pous" / "FB_Positional.st").exists()

    @pytest.mark.asyncio
    async def test_insert_st_pou_async_mcp_call(self, tmp_path):
        """1. Verify async MCP server tool dispatch: server.call_tool('cscape_insert_st_pou')."""
        proj_dir = tmp_path / "AuditProjMCP"
        proj_dir.mkdir()
        st_code = """FUNCTION FC_AuditAdd : INT
VAR_INPUT
    A : INT;
    B : INT;
END_VAR
FC_AuditAdd := A + B;
END_FUNCTION
"""
        res = await server.call_tool("cscape_insert_st_pou", {
            "project_path": str(proj_dir),
            "pou_name": "FC_AuditAdd",
            "st_code": st_code,
            "pou_type": "FUNCTION",
        })
        assert not res.is_error
        data = json.loads(res.content[0].text)
        assert data["success"] is True
        assert data["syntax_valid"] is True
        assert data["pou_name"] == "FC_AuditAdd"
        assert data["pou_type"] == "FUNCTION"
        assert (proj_dir / "pous" / "FC_AuditAdd.st").exists()

    def test_insert_st_pou_syntax_validation_prior_to_insertion(self, tmp_path):
        """2. Confirm ST code syntax validation prior to insertion.

        Invalid ST code must be detected and rejected; success=False;
        no code persisted to disk; no Cscape automation invoked.
        """
        proj_dir = tmp_path / "AuditSyntaxErr"
        proj_dir.mkdir()
        broken_st = """PROGRAM PRG_SyntaxError
VAR
    x : INT;
END_VAR
IF x > 0 THEN
    x := 1;
(* Missing END_IF and missing END_PROGRAM *)
"""
        res = cscape_insert_st_pou(
            project_path=str(proj_dir),
            pou_name="PRG_SyntaxError",
            st_code=broken_st,
            pou_type="PROGRAM",
        )
        assert res["success"] is False
        assert res["syntax_valid"] is False
        assert len(res["errors"]) > 0
        assert any("Unclosed" in e or "Missing" in e or "Mismatched" in e for e in res["errors"])
        # Confirm no file was created in project pous/
        assert not (proj_dir / "pous" / "PRG_SyntaxError.st").exists()

    def test_insert_st_pou_ladder_rejection_before_cscape_automation(self, tmp_path):
        """3. Confirm rejection of ladder logic constructs before calling Cscape automation.

        Advanced Ladder constructs (ASCII contacts, coils, rungs, mnemonics)
        must be caught immediately and rejected before any Cscape automation.
        """
        proj_dir = tmp_path / "AuditLadderRejection"
        proj_dir.mkdir()

        ladder_samples = [
            ("LadderContacts", "PROGRAM P1\nVAR In1: BOOL; Out1: BOOL; END_VAR\n---[ ]--- In1 --- ( ) --- Out1;\nEND_PROGRAM"),
            ("LadderNCContact", "PROGRAM P2\nVAR In1: BOOL; Out1: BOOL; END_VAR\n---[/]--- In1 --- ( ) --- Out1;\nEND_PROGRAM"),
            ("LadderRungMarker", "PROGRAM P3\nRUNG 1:\nMotor := TRUE;\nEND_PROGRAM"),
            ("LadderMnemonic", "PROGRAM P4\nVAR In1: BOOL; Out1: BOOL; END_VAR\nXIC(In1) OTE(Out1);\nEND_PROGRAM"),
        ]

        for pou_name, ladder_code in ladder_samples:
            res = cscape_insert_st_pou(
                project_path=str(proj_dir),
                pou_name=pou_name,
                st_code=ladder_code,
                pou_type="PROGRAM",
            )
            assert res["success"] is False, f"Ladder construct '{pou_name}' was not rejected!"
            assert res["syntax_valid"] is False
            assert any("Ladder logic rejected" in e or "Ladder logic artifact" in e for e in res["errors"])
            assert "Advanced Ladder rejected" in res["message"]
            # Verify no file written to disk
            assert not (proj_dir / "pous" / f"{pou_name}.st").exists()


class TestJSONRPCComplianceAndFailClosed:
    """Verifies JSON-RPC 2.0 stdio compliance, tool registry, and error code mappings."""

    def test_jsonrpc_error_code_mappings(self):
        """Verify standard JSON-RPC 2.0 error code constants."""
        from mcp_types.jsonrpc import (
            PARSE_ERROR,
            INVALID_REQUEST,
            METHOD_NOT_FOUND,
            INVALID_PARAMS,
            INTERNAL_ERROR,
            JSONRPC_VERSION,
        )
        assert JSONRPC_VERSION == "2.0"
        assert PARSE_ERROR == -32700
        assert INVALID_REQUEST == -32600
        assert METHOD_NOT_FOUND == -32601
        assert INVALID_PARAMS == -32602
        assert INTERNAL_ERROR == -32603

    @pytest.mark.asyncio
    async def test_unknown_tool_call_fail_closed(self):
        """Verify unknown tool call raises error and fails closed."""
        with pytest.raises(Exception) as exc_info:
            await server.call_tool("unknown_nonexistent_tool", {})
        assert "Unknown tool" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_tool_fail_closed_error_structures(self):
        """Verify fail-closed structured error responses on invalid inputs."""
        from src.mcp.tools import (
            cscape_new_iec_project,
            cscape_open_project,
            cscape_read_register,
            cscape_write_register,
            cscape_run_simulation,
        )
        # Reserved DOS device name
        res1 = cscape_new_iec_project(project_name="CON", target_dir="artifacts/projects")
        assert res1["success"] is False
        assert "Security violation" in res1["message"] or "Failed" in res1["message"]

        # Nonexistent file
        res2 = cscape_open_project(file_path="nonexistent/path/file.csp")
        assert res2["success"] is False
        assert "Failed" in res2["message"]

        # Out-of-bounds register address
        res3 = cscape_read_register(address="%R99999")
        assert res3["success"] is False
        assert "out of bounds" in res3["message"].lower() or "failed" in res3["message"].lower()

        res4 = cscape_write_register(address="%R99999", value=10)
        assert res4["success"] is False
        assert "out of bounds" in res4["message"].lower() or "failed" in res4["message"].lower()

        # Invalid simulation steps
        res5 = cscape_run_simulation(steps=-5)
        assert res5["success"] is False
        assert "Simulation error" in res5["message"] or "failed" in res5["message"].lower()

    def test_clean_stdio_json_serialization(self):
        """Verify all tool return dictionaries serialize cleanly to JSON with zero stdout corruption."""
        from src.mcp.tools import (
            cscape_validate_st,
            cscape_read_register,
            cscape_write_register,
            cscape_simulate_cycle,
        )
        samples = [
            cscape_validate_st("PROGRAM P\nVAR x: INT; END_VAR\nEND_PROGRAM"),
            cscape_read_register("%R1"),
            cscape_write_register("%R1", 42),
            cscape_simulate_cycle(dt_ms=10.0),
        ]
        for item in samples:
            dumped = json.dumps(item)
            assert isinstance(dumped, str)
            reloaded = json.loads(dumped)
            assert isinstance(reloaded, dict)

    def test_stdio_jsonrpc_wire_protocol(self):
        """Verify full JSON-RPC 2.0 handshake and tool execution over stdio."""
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "run_mcp_server.py"
        cmd = [sys.executable, str(script_path), "--transport", "stdio"]
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=str(repo_root),
        )
        try:
            # 1. Initialize
            init_req = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "audit-test-client", "version": "1.0.0"},
                },
            }
            proc.stdin.write(json.dumps(init_req) + "\n")
            proc.stdin.flush()

            line1 = proc.stdout.readline()
            resp1 = json.loads(line1)
            assert resp1.get("jsonrpc") == "2.0"
            assert resp1.get("id") == 1
            assert "result" in resp1
            assert resp1["result"]["serverInfo"]["name"] == SERVER_NAME

            # 2. Initialized notification
            notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
            proc.stdin.write(json.dumps(notif) + "\n")
            proc.stdin.flush()

            # 3. Tools list
            list_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
            proc.stdin.write(json.dumps(list_req) + "\n")
            proc.stdin.flush()

            line2 = proc.stdout.readline()
            resp2 = json.loads(line2)
            assert resp2.get("jsonrpc") == "2.0"
            assert resp2.get("id") == 2
            tools_list = resp2["result"]["tools"]
            assert len(tools_list) == 23

            # 4. Tool call
            call_req = {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "cscape_validate_st",
                    "arguments": {
                        "code": "PROGRAM P_Main\nVAR\n  Run : BOOL;\nEND_VAR\nEND_PROGRAM"
                    },
                },
            }
            proc.stdin.write(json.dumps(call_req) + "\n")
            proc.stdin.flush()

            line3 = proc.stdout.readline()
            resp3 = json.loads(line3)
            assert resp3.get("jsonrpc") == "2.0"
            assert resp3.get("id") == 3
            assert "result" in resp3
            content = resp3["result"]["content"]
            assert len(content) > 0
            call_data = json.loads(content[0]["text"])
            assert call_data["valid"] is True
            assert call_data["pou_name"] == "P_Main"

        finally:
            proc.stdin.close()
            proc.terminate()
            proc.wait(timeout=5)


