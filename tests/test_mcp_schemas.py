"""Comprehensive Unit & Security Test Suite for Horner Cscape MCP Tool Schemas.

Validates:
- All 9 redesigned Cscape MCP tool schemas:
  1. cscape_launch_ide
  2. cscape_new_iec_project
  3. cscape_open_project
  4. cscape_insert_st
  5. cscape_compile
  6. cscape_get_build_output
  7. cscape_import_variables
  8. cscape_export_variables
  9. cscape_run_simulation
- Invariant safety checks:
  * extra="forbid" rejects unexpected arguments (download, com ports, etc.)
  * Prohibited download/flash parameter detection
  * Physical PLC lockout enforcement
  * Path traversal & DOS reserved identifier rejection
  * Pure Structured Text enforcement (ladder logic rejection)
- Tool registry and validation helper functions
"""

import pytest
from pydantic import ValidationError

from src.mcp.schemas import (
    CscapeBaseModel,
    POUType,
    VariableScope,
    VariableMergeStrategy,
    BuildLogLevel,
    VariableDeclaration,
    MemoryFootprint,
    POUCompilationStatus,
    SimulationStepTrace,
    # 1. Launch IDE
    CscapeLaunchIDEInput,
    CscapeLaunchIDEOutput,
    LaunchIDEInput,
    LaunchIDEOutput,
    # 2. New Project
    CscapeNewIECProjectInput,
    CscapeNewIECProjectOutput,
    NewIECProjectInput,
    NewIECProjectOutput,
    # 3. Open Project
    CscapeOpenProjectInput,
    CscapeOpenProjectOutput,
    OpenProjectInput,
    OpenProjectOutput,
    # 4. Insert ST
    CscapeInsertSTInput,
    CscapeInsertSTOutput,
    InsertSTInput,
    InsertSTOutput,
    # 5. Compile
    CscapeCompileInput,
    CscapeCompileOutput,
    CompileInput,
    CompileOutput,
    # 6. Build Output
    CscapeGetBuildOutputInput,
    CscapeGetBuildOutputOutput,
    GetBuildOutputInput,
    GetBuildOutputOutput,
    # 7. Import Variables
    CscapeImportVariablesInput,
    CscapeImportVariablesOutput,
    ImportVariablesInput,
    ImportVariablesOutput,
    # 8. Export Variables
    CscapeExportVariablesInput,
    CscapeExportVariablesOutput,
    ExportVariablesInput,
    ExportVariablesOutput,
    # 9. Run Simulation
    CscapeRunSimulationInput,
    CscapeRunSimulationOutput,
    RunSimulationInput,
    RunSimulationOutput,
    # Registry & Helpers
    TOOL_SCHEMAS,
    get_tool_input_schema,
    get_tool_output_schema,
    list_tool_schemas,
    validate_tool_input,
    validate_tool_output,
    # Path & OCS Register Validation
    validate_safe_path,
    validate_ocs_register,
    is_valid_ocs_register,
    OCS_REGISTER_BOUNDS,
)


# ==============================================================================
# 1. cscape_launch_ide Tests
# ==============================================================================

class TestCscapeLaunchIDESchemas:
    """Tests for cscape_launch_ide input and output schemas."""

    def test_launch_ide_input_defaults(self):
        inp = LaunchIDEInput()
        assert inp.headless is False
        assert inp.project_path is None
        assert inp.timeout_seconds == 30.0
        assert inp.kill_existing is False

    def test_launch_ide_input_valid(self):
        inp = LaunchIDEInput(
            headless=True,
            project_path=r"C:\HornerAI\horner-cscape-mcp\artifacts\projects\MyProj\MyProj.csp",
            timeout_seconds=45.0,
            kill_existing=True,
        )
        assert inp.headless is True
        assert inp.timeout_seconds == 45.0
        assert inp.kill_existing is True

    def test_launch_ide_input_rejects_k5p(self):
        with pytest.raises(ValidationError):
            LaunchIDEInput(project_path=r"C:\HornerAI\projects\MyProj\appli.k5p")

    def test_launch_ide_input_forbids_extra_download_params(self):
        with pytest.raises(ValidationError) as exc_info:
            LaunchIDEInput.model_validate({
                "headless": False,
                "download": True,
            })
        assert "extra_forbidden" in str(exc_info.value)

    def test_launch_ide_input_rejects_download_terms_in_path(self):
        with pytest.raises(ValidationError):
            LaunchIDEInput(project_path=r"C:\downloads\test\appli.k5p")

    def test_launch_ide_input_rejects_invalid_extension(self):
        with pytest.raises(ValidationError):
            LaunchIDEInput(project_path=r"C:\test\appli.exe")

    def test_launch_ide_output_valid(self):
        out = LaunchIDEOutput(
            success=True,
            pid=1234,
            executable_path=r"C:\Program Files (x86)\Cscape 10.2\Cscape.exe",
            version="10.2.751.4",
            mode="gui",
            message="Cscape launched successfully.",
        )
        assert out.success is True
        assert out.pid == 1234
        assert "Cscape launched" in out.message


# ==============================================================================
# 2. cscape_new_iec_project Tests
# ==============================================================================

class TestCscapeNewIECProjectSchemas:
    """Tests for cscape_new_iec_project input and output schemas."""

    def test_new_project_input_valid(self):
        inp = NewIECProjectInput(
            project_name="Water_Treatment_01",
            target_dir=r"C:\HornerAI\horner-cscape-mcp\artifacts\projects",
            controller_model="XL4",
            description="Water pump sequencing controller",
            author="Control Engineer",
        )
        assert inp.project_name == "Water_Treatment_01"
        assert inp.controller_model == "XL4"
        assert inp.author == "Control Engineer"

    def test_new_project_forbids_extra_params(self):
        with pytest.raises(ValidationError) as exc_info:
            NewIECProjectInput.model_validate({
                "project_name": "TestProj",
                "target_dir": r"C:\projects",
                "controller_model": "T5RTI",
                "download_to_plc": True,
            })
        assert "extra_forbidden" in str(exc_info.value)

    def test_new_project_rejects_physical_hardware_targets(self):
        for bad_target in ["PHYSICAL", "HARDWARE", "PLC_HARDWARE", "DOWNLOAD"]:
            with pytest.raises(ValidationError):
                NewIECProjectInput(
                    project_name="TestProj",
                    target_dir=r"C:\projects",
                    controller_model=bad_target,
                )

    def test_new_project_rejects_path_traversal_in_name(self):
        with pytest.raises(ValidationError):
            NewIECProjectInput(
                project_name="../../malicious",
                target_dir=r"C:\projects",
                controller_model="T5RTI",
            )

    def test_new_project_rejects_dos_reserved_device_names(self):
        for dev in ["CON", "PRN", "AUX", "NUL", "COM1", "LPT1"]:
            with pytest.raises(ValidationError):
                NewIECProjectInput(
                    project_name=dev,
                    target_dir=r"C:\projects",
                    controller_model="T5RTI",
                )

    def test_new_project_output_valid(self):
        out = NewIECProjectOutput(
            success=True,
            project_name="Pump_Station",
            project_path=r"C:\HornerAI\horner-cscape-mcp\artifacts\projects\Pump_Station",
            target_dir=r"C:\HornerAI\horner-cscape-mcp\artifacts\projects",
            controller_model="T5RTI",
            files_created=["appli.k5p", "appli.CPO", "K5DBXS.INI"],
            message="Project created successfully.",
        )
        assert out.success is True
        assert len(out.files_created) == 3


# ==============================================================================
# 3. cscape_open_project Tests
# ==============================================================================

class TestCscapeOpenProjectSchemas:
    """Tests for cscape_open_project input and output schemas."""

    def test_open_project_input_valid(self):
        inp = OpenProjectInput(
            file_path=r"C:\HornerAI\projects\MainApp\MainApp.csp",
            read_only=True,
        )
        assert inp.file_path.endswith("MainApp.csp")
        assert inp.read_only is True

    def test_open_project_forbids_extra_params(self):
        with pytest.raises(ValidationError) as exc_info:
            OpenProjectInput.model_validate({
                "file_path": r"C:\projects\MainApp.csp",
                "com_port": "COM3",
            })
        assert "extra_forbidden" in str(exc_info.value)

    def test_open_project_rejects_unsupported_extensions(self):
        with pytest.raises(ValidationError):
            OpenProjectInput(file_path=r"C:\projects\appli.exe")

    def test_open_project_rejects_k5p_extension(self):
        with pytest.raises(ValidationError):
            OpenProjectInput(file_path=r"C:\projects\appli.k5p")

    def test_open_project_output_valid(self):
        out = OpenProjectOutput(
            success=True,
            file_path=r"C:\projects\appli.k5p",
            project_name="MainApp",
            controller_model="T5RTI",
            pou_count=3,
            pous=["PRG_Main", "FB_Motor", "FC_Calc"],
            message="Project opened successfully.",
        )
        assert out.success is True
        assert out.pou_count == 3


# ==============================================================================
# 4. cscape_insert_st Tests
# ==============================================================================

class TestCscapeInsertSTSchemas:
    """Tests for cscape_insert_st input and output schemas."""

    def test_insert_st_input_valid(self):
        st_code = """PROGRAM PRG_Main
VAR
    RunCmd : BOOL := FALSE;
    Counter : DINT := 0;
END_VAR
IF RunCmd THEN
    Counter := Counter + 1;
END_IF;
END_PROGRAM
"""
        inp = InsertSTInput(
            pou_name="PRG_Main",
            pou_type=POUType.PROGRAM,
            st_code=st_code,
            cycle_time_ms=20,
        )
        assert inp.pou_name == "PRG_Main"
        assert inp.pou_type == "PROGRAM"
        assert inp.cycle_time_ms == 20

    def test_insert_st_input_string_enum_conversion(self):
        inp = InsertSTInput(
            pou_name="FB_Valve",
            pou_type="FUNCTION_BLOCK",
            st_code="FUNCTION_BLOCK FB_Valve\nEND_FUNCTION_BLOCK",
        )
        assert inp.pou_type == "FUNCTION_BLOCK"

    def test_insert_st_forbids_extra_params(self):
        with pytest.raises(ValidationError) as exc_info:
            InsertSTInput.model_validate({
                "pou_name": "PRG_Test",
                "pou_type": "PROGRAM",
                "st_code": "PROGRAM PRG_Test END_PROGRAM",
                "flash": True,
            })
        assert "extra_forbidden" in str(exc_info.value)

    def test_insert_st_rejects_invalid_pou_name(self):
        with pytest.raises(ValidationError):
            InsertSTInput(
                pou_name="123_invalid_start",
                pou_type="PROGRAM",
                st_code="PROGRAM P END_PROGRAM",
            )

    def test_insert_st_rejects_ladder_logic_artifacts(self):
        ladder_code = """PROGRAM PRG_Ladder
VAR In1: BOOL; Out1: BOOL; END_VAR
---[ ]--- In1 --- ( ) --- Out1;
END_PROGRAM
"""
        with pytest.raises(ValidationError) as exc_info:
            InsertSTInput(
                pou_name="PRG_Ladder",
                pou_type="PROGRAM",
                st_code=ladder_code,
            )
        assert "Ladder logic artifact detected" in str(exc_info.value)

    def test_insert_st_output_valid(self):
        out = InsertSTOutput(
            success=True,
            pou_name="PRG_Main",
            pou_type="PROGRAM",
            file_path=r"C:\projects\pous\PRG_Main.st",
            cycle_time_ms=10,
            variable_count=2,
            syntax_valid=True,
            message="POU inserted successfully.",
        )
        assert out.success is True
        assert out.variable_count == 2


# ==============================================================================
# 5. cscape_compile Tests
# ==============================================================================

class TestCscapeCompileSchemas:
    """Tests for cscape_compile input and output schemas."""

    def test_compile_input_defaults(self):
        inp = CompileInput()
        assert inp.project_path is None
        assert inp.clean_build is True
        assert inp.timeout_seconds == 60.0

    def test_compile_forbids_extra_download_params(self):
        # Strict safety invariant: Any injected download or target hardware param is rejected
        for bad_param in ["download", "flash", "burn", "firmware", "device_port", "ip_address"]:
            with pytest.raises(ValidationError) as exc_info:
                CompileInput.model_validate({
                    "clean_build": True,
                    bad_param: True,
                })
            assert "extra_forbidden" in str(exc_info.value)

    def test_compile_output_certifies_hardware_lockout(self):
        out = CompileOutput(
            success=True,
            compile_successful=True,
            project_name="BatchMixer",
            target_plc="T5RTI",
            clean_build=True,
            error_count=0,
            warning_count=0,
            hardware_lockout_enforced=True,
            duration_ms=45.2,
            message="Compilation successful.",
        )
        assert out.compile_successful is True
        assert out.hardware_lockout_enforced is True


# ==============================================================================
# 6. cscape_get_build_output Tests
# ==============================================================================

class TestCscapeGetBuildOutputSchemas:
    """Tests for cscape_get_build_output input and output schemas."""

    def test_get_build_output_input_valid(self):
        inp = GetBuildOutputInput(
            max_lines=100,
            log_level=BuildLogLevel.ERROR,
        )
        assert inp.max_lines == 100
        assert inp.log_level == "ERROR"

    def test_get_build_output_forbids_extra_params(self):
        with pytest.raises(ValidationError) as exc_info:
            GetBuildOutputInput.model_validate({
                "max_lines": 50,
                "remote_host": "192.168.1.100",
            })
        assert "extra_forbidden" in str(exc_info.value)

    def test_get_build_output_output_valid(self):
        out = GetBuildOutputOutput(
            success=True,
            compile_successful=True,
            project_name="Mixer",
            build_log="Compiling PRG_Main... Done.\\n0 errors, 0 warnings.",
            error_count=0,
            warning_count=0,
            message="Build log retrieved.",
        )
        assert out.success is True
        assert "PRG_Main" in out.build_log


# ==============================================================================
# 7. cscape_import_variables Tests
# ==============================================================================

class TestCscapeImportVariablesSchemas:
    """Tests for cscape_import_variables input and output schemas."""

    def test_import_variables_input_valid(self):
        inp = ImportVariablesInput(
            csv_path=r"C:\HornerAI\horner-cscape-mcp\fixtures\variables.csv",
            merge_strategy="merge",
            target_scope="GLOBAL",
        )
        assert inp.csv_path.endswith(".csv")
        assert inp.merge_strategy == "merge"
        assert inp.target_scope == "GLOBAL"

    def test_import_variables_forbids_extra_params(self):
        with pytest.raises(ValidationError) as exc_info:
            ImportVariablesInput.model_validate({
                "csv_path": r"C:\data\vars.csv",
                "direct_plc_write": True,
            })
        assert "extra_forbidden" in str(exc_info.value)

    def test_import_variables_rejects_non_csv_extension(self):
        with pytest.raises(ValidationError):
            ImportVariablesInput(csv_path=r"C:\data\vars.exe")

    def test_import_variables_output_valid(self):
        out = ImportVariablesOutput(
            success=True,
            csv_path=r"C:\data\vars.csv",
            project_name="PumpStation",
            variables_imported=5,
            variables_updated=2,
            variables_count=7,
            variable_names=["StartBtn", "StopBtn", "PumpRun", "PressureLevel"],
            message="Import completed.",
        )
        assert out.success is True
        assert out.variables_imported == 5


# ==============================================================================
# 8. cscape_export_variables Tests
# ==============================================================================

class TestCscapeExportVariablesSchemas:
    """Tests for cscape_export_variables input and output schemas."""

    def test_export_variables_input_valid(self):
        inp = ExportVariablesInput(
            output_csv_path=r"C:\HornerAI\horner-cscape-mcp\artifacts\exports\variables.csv",
            scope_filter="VAR_GLOBAL",
            pou_name=None,
        )
        assert inp.output_csv_path.endswith(".csv")
        assert inp.scope_filter == "VAR_GLOBAL"

    def test_export_variables_forbids_extra_params(self):
        with pytest.raises(ValidationError) as exc_info:
            ExportVariablesInput.model_validate({
                "output_csv_path": r"C:\exports\vars.csv",
                "upload_to_hardware": True,
            })
        assert "extra_forbidden" in str(exc_info.value)

    def test_export_variables_output_valid(self):
        out = ExportVariablesOutput(
            success=True,
            output_csv_path=r"C:\exports\vars.csv",
            project_name="PumpStation",
            variables_exported=12,
            file_size_bytes=1024,
            sha256="a" * 64,
            message="Variables exported successfully.",
        )
        assert out.success is True
        assert out.variables_exported == 12
        assert len(out.sha256) == 64


# ==============================================================================
# 9. cscape_run_simulation Tests
# ==============================================================================

class TestCscapeRunSimulationSchemas:
    """Tests for cscape_run_simulation input and output schemas."""

    def test_run_simulation_input_valid_with_code(self):
        code = "PROGRAM PRG_Sim VAR In1: INT; Out1: INT; END_VAR Out1 := In1 * 2; END_PROGRAM"
        inp = RunSimulationInput(
            steps=10,
            code=code,
            inputs={"In1": 5},
        )
        assert inp.steps == 10
        assert inp.code == code
        assert inp.inputs["In1"] == 5

    def test_run_simulation_input_valid_with_pou_name(self):
        inp = RunSimulationInput(
            steps=5,
            pou_name="FB_MotorStarter",
            inputs={"RunCmd": True},
        )
        assert inp.steps == 5
        assert inp.pou_name == "FB_MotorStarter"

    def test_run_simulation_rejects_neither_code_nor_pou(self):
        with pytest.raises(ValidationError) as exc_info:
            RunSimulationInput(steps=5)
        assert "Either 'code' (ST source) or 'pou_name' must be provided" in str(exc_info.value)

    def test_run_simulation_forbids_hardware_extra_params(self):
        with pytest.raises(ValidationError) as exc_info:
            RunSimulationInput.model_validate({
                "steps": 5,
                "pou_name": "PRG_Main",
                "com_port": "COM1",
                "plc_ip": "192.168.1.10",
            })
        assert "extra_forbidden" in str(exc_info.value)

    def test_run_simulation_validates_step_range(self):
        # Steps must be 1 <= steps <= 10000
        with pytest.raises(ValidationError):
            RunSimulationInput(steps=0, pou_name="PRG_Main")
        with pytest.raises(ValidationError):
            RunSimulationInput(steps=10001, pou_name="PRG_Main")

    def test_run_simulation_output_certifies_hardware_lockout(self):
        out = RunSimulationOutput(
            success=True,
            steps_executed=5,
            trace=[{"step": 0, "variables": {"Count": 1}}],
            final_state={"Count": 5},
            execution_time_ms=1.25,
            hardware_connected=False,
            message="Simulation completed successfully.",
        )
        assert out.success is True
        assert out.hardware_connected is False
        assert out.steps_executed == 5


# ==============================================================================
# Tool Registry & Helper Function Tests
# ==============================================================================

class TestToolSchemasRegistry:
    """Tests registry mappings and helper validation functions."""

    def test_all_9_tools_registered(self):
        expected_tools = [
            "cscape_launch_ide",
            "cscape_new_iec_project",
            "cscape_open_project",
            "cscape_insert_st",
            "cscape_compile",
            "cscape_get_build_output",
            "cscape_import_variables",
            "cscape_export_variables",
            "cscape_run_simulation",
        ]
        schemas = list_tool_schemas()
        for tool in expected_tools:
            assert tool in schemas
            assert "input" in schemas[tool]
            assert "output" in schemas[tool]
            assert issubclass(schemas[tool]["input"], CscapeBaseModel)
            assert issubclass(schemas[tool]["output"], CscapeBaseModel)

    def test_get_tool_input_schema(self):
        cls = get_tool_input_schema("cscape_compile")
        assert cls is CscapeCompileInput

    def test_get_tool_output_schema(self):
        cls = get_tool_output_schema("cscape_compile")
        assert cls is CscapeCompileOutput

    def test_get_unknown_tool_raises_key_error(self):
        with pytest.raises(KeyError):
            get_tool_input_schema("unknown_tool_xyz")

    def test_validate_tool_input_helper(self):
        model = validate_tool_input("cscape_compile", {"clean_build": False})
        assert isinstance(model, CscapeCompileInput)
        assert model.clean_build is False

    def test_validate_tool_output_helper(self):
        model = validate_tool_output("cscape_compile", {
            "success": True,
            "compile_successful": True,
            "message": "Done",
        })
        assert isinstance(model, CscapeCompileOutput)
        assert model.compile_successful is True

    def test_all_schemas_generate_json_schema(self):
        """Verify that every schema generates valid JSON Schema (critical for MCP tool registration)."""
        for tool_name, schema_pair in list_tool_schemas().items():
            input_schema = schema_pair["input"].model_json_schema()
            output_schema = schema_pair["output"].model_json_schema()
            assert "properties" in input_schema
            assert "properties" in output_schema
            assert input_schema.get("additionalProperties") is False


# ==============================================================================
# 10. Path Traversal Defenses Across All Tools
# ==============================================================================

class TestPathTraversalDefenses:
    """Rigorous security testing for path traversal and filesystem breakout defenses."""

    @pytest.mark.parametrize("bad_path", [
        "../escape.csp",
        "..\\escape.csp",
        "nested/../../secret.k5p",
        "C:\\HornerAI\\..\\..\\Windows\\System32\\calc.exe",
        "relative/path/../../../etc/passwd",
    ])
    def test_path_traversal_dot_dot_rejected(self, bad_path):
        with pytest.raises(ValidationError) as exc_info:
            OpenProjectInput(file_path=bad_path)
        assert "Path traversal sequence" in str(exc_info.value)

    @pytest.mark.parametrize("unc_path", [
        r"\\192.168.1.50\share\project.cpj",
        r"\\evil-server\payload\appli.k5p",
        "//nas/storage/project.csp",
    ])
    def test_unc_paths_rejected(self, unc_path):
        with pytest.raises(ValidationError) as exc_info:
            OpenProjectInput(file_path=unc_path)
        assert "UNC remote network paths are prohibited" in str(exc_info.value)

    @pytest.mark.parametrize("ads_path", [
        r"C:\projects\appli.k5p:hidden_stream",
        r"C:\data\vars.csv:evil.exe",
        "project.cpj:malware",
    ])
    def test_alternate_data_stream_rejected(self, ads_path):
        with pytest.raises(ValidationError) as exc_info:
            OpenProjectInput(file_path=ads_path)
        assert "Alternate Data Stream" in str(exc_info.value)

    def test_null_byte_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            OpenProjectInput(file_path="C:\\projects\\appli.k5p\0.exe")
        assert "Null byte detected" in str(exc_info.value)

    @pytest.mark.parametrize("dos_dev", [
        r"C:\projects\CON.csp",
        r"C:\projects\PRN.k5p",
        r"C:\projects\AUX.cpj",
        r"C:\projects\NUL.xml",
        r"C:\projects\COM1.csp",
        r"C:\projects\LPT1.csp",
        r"C:\projects\CLOCK$.k5p",
    ])
    def test_dos_reserved_device_names_rejected(self, dos_dev):
        with pytest.raises(ValidationError) as exc_info:
            OpenProjectInput(file_path=dos_dev)
        assert "Reserved Windows device name" in str(exc_info.value)

    def test_all_tools_with_paths_enforce_safe_paths(self):
        # 1. Launch IDE
        with pytest.raises(ValidationError):
            LaunchIDEInput(project_path="../escaped.k5p")
        # 2. New Project
        with pytest.raises(ValidationError):
            NewIECProjectInput(project_name="P", target_dir="../traversal", controller_model="XL4")
        # 3. Open Project
        with pytest.raises(ValidationError):
            OpenProjectInput(file_path="../traversal.csp")
        # 4. Insert ST
        with pytest.raises(ValidationError):
            InsertSTInput(pou_name="PRG_M", pou_type="PROGRAM", st_code="PROGRAM P END_PROGRAM", project_path="../traversal")
        # 5. Compile
        with pytest.raises(ValidationError):
            CompileInput(project_path="../traversal")
        # 6. Get Build Output
        with pytest.raises(ValidationError):
            GetBuildOutputInput(project_path="../traversal")
        # 7. Import Variables
        with pytest.raises(ValidationError):
            ImportVariablesInput(csv_path="../vars.csv")
        with pytest.raises(ValidationError):
            ImportVariablesInput(csv_path=r"C:\valid.csv", project_path="../traversal")
        # 8. Export Variables
        with pytest.raises(ValidationError):
            ExportVariablesInput(output_csv_path="../vars.csv")
        with pytest.raises(ValidationError):
            ExportVariablesInput(output_csv_path=r"C:\valid.csv", project_path="../traversal")
        # 9. Run Simulation
        with pytest.raises(ValidationError):
            RunSimulationInput(steps=5, code="PROGRAM P END_PROGRAM", project_path="../traversal")


# ==============================================================================
# 11. Horner OCS Register Validation Tests
# ==============================================================================

class TestOCSRegisterValidation:
    """Rigorous validation tests for Horner OCS memory registers and addressing."""

    def test_valid_holding_registers(self):
        assert validate_ocs_register("%R1") == "%R1"
        assert validate_ocs_register("%r100") == "%R100"
        assert validate_ocs_register("%R9999") == "%R9999"
        assert is_valid_ocs_register("%R500") is True

    def test_valid_internal_bits(self):
        assert validate_ocs_register("%M1") == "%M1"
        assert validate_ocs_register("%m2048") == "%M2048"
        assert validate_ocs_register("%T1") == "%T1"
        assert validate_ocs_register("%T2048") == "%T2048"

    def test_valid_io_registers(self):
        assert validate_ocs_register("%I1") == "%I1"
        assert validate_ocs_register("%I2048") == "%I2048"
        assert validate_ocs_register("%Q1") == "%Q1"
        assert validate_ocs_register("%Q2048") == "%Q2048"
        assert validate_ocs_register("%AI1") == "%AI1"
        assert validate_ocs_register("%AI512") == "%AI512"
        assert validate_ocs_register("%AQ1") == "%AQ1"
        assert validate_ocs_register("%AQ512") == "%AQ512"

    def test_valid_system_and_display_registers(self):
        assert validate_ocs_register("%S1") == "%S1"
        assert validate_ocs_register("%S128") == "%S128"
        assert validate_ocs_register("%SR1") == "%SR1"
        assert validate_ocs_register("%SR256") == "%SR256"
        assert validate_ocs_register("%D1") == "%D1"
        assert validate_ocs_register("%D1024") == "%D1024"
        assert validate_ocs_register("%K1") == "%K1"
        assert validate_ocs_register("%K1024") == "%K1024"

    def test_valid_cscan_global_registers(self):
        assert validate_ocs_register("%IG1") == "%IG1"
        assert validate_ocs_register("%QG2048") == "%QG2048"
        assert validate_ocs_register("%AIG100") == "%AIG100"
        assert validate_ocs_register("%AQG50") == "%AQG50"

    def test_valid_iec_standard_registers(self):
        assert validate_ocs_register("%IX0") == "%IX0"
        assert validate_ocs_register("%QX10") == "%QX10"
        assert validate_ocs_register("%MW100") == "%MW100"
        assert validate_ocs_register("%MD50") == "%MD50"

    def test_valid_bit_of_word_registers(self):
        assert validate_ocs_register("%R100.1") == "%R100.1"
        assert validate_ocs_register("%R100.16") == "%R100.16"
        assert validate_ocs_register("%SR43.1") == "%SR43.1"
        assert validate_ocs_register("%AI5.0") == "%AI5.0"

    @pytest.mark.parametrize("invalid_reg", [
        "INVALID",
        "%Z100",
        "%ABC5",
        "R100",  # missing %
        "%",
        "",
        "%R",
        "%100",
    ])
    def test_invalid_register_syntax_and_prefixes(self, invalid_reg):
        assert is_valid_ocs_register(invalid_reg) is False
        with pytest.raises(ValueError):
            validate_ocs_register(invalid_reg)

    @pytest.mark.parametrize("out_of_bounds", [
        "%R0",       # min index is 1
        "%R10000",   # max is 9999
        "%M0",
        "%M2049",    # max is 2048
        "%T2049",
        "%I2049",
        "%Q2049",
        "%AI0",
        "%AI513",    # max is 512
        "%AQ513",
        "%S0",
        "%S129",     # max is 128
        "%SR0",
        "%SR257",    # max is 256
        "%D1025",
        "%K1025",
    ])
    def test_out_of_bounds_register_indices(self, out_of_bounds):
        assert is_valid_ocs_register(out_of_bounds) is False
        with pytest.raises(ValueError) as exc_info:
            validate_ocs_register(out_of_bounds)
        assert "out of bounds" in str(exc_info.value)

    def test_bit_offset_on_discrete_bit_registers_rejected(self):
        # %M, %T, %I, %Q are already 1-bit registers, bit-of-word is prohibited
        for bit_reg in ["%M1.1", "%T5.2", "%I10.0", "%Q2.8"]:
            assert is_valid_ocs_register(bit_reg) is False
            with pytest.raises(ValueError) as exc_info:
                validate_ocs_register(bit_reg)
            assert "Bit offset not allowed on discrete bit register" in str(exc_info.value)

    def test_out_of_bounds_bit_offset(self):
        # Bit of word must be 0..16
        for bad_bit in ["%R100.17", "%R100.99", "%SR1.20"]:
            assert is_valid_ocs_register(bad_bit) is False
            with pytest.raises(ValueError) as exc_info:
                validate_ocs_register(bad_bit)
            assert "out of range" in str(exc_info.value)

    def test_variable_declaration_valid_address(self):
        decl = VariableDeclaration(
            name="MotorSpeed",
            data_type="INT",
            address="%R100",
        )
        assert decl.name == "MotorSpeed"
        assert decl.address == "%R100"

    def test_variable_declaration_invalid_address_rejected(self):
        # Missing '%' prefix
        with pytest.raises(ValidationError) as exc_info:
            VariableDeclaration(
                name="MotorSpeed",
                data_type="INT",
                address="NOT_A_REGISTER",
            )
        assert "must start with '%'" in str(exc_info.value)

        # Invalid prefix with '%'
        with pytest.raises(ValidationError) as exc_info:
            VariableDeclaration(
                name="MotorSpeed",
                data_type="INT",
                address="%INVALID_REG",
            )
        assert "Invalid Horner OCS register format" in str(exc_info.value)

    def test_variable_declaration_out_of_bounds_address_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            VariableDeclaration(
                name="SystemFault",
                data_type="BOOL",
                address="%SR999",
            )
        assert "out of bounds" in str(exc_info.value)

    def test_simulation_input_with_valid_register_map(self):
        inp = RunSimulationInput(
            steps=5,
            code="PROGRAM P VAR Start AT %M1: BOOL; END_VAR END_PROGRAM",
            register_map={
                "Start": "%M1",
                "Speed": "%R100",
                "Status": "%SR10",
            },
        )
        assert inp.register_map["Start"] == "%M1"
        assert inp.register_map["Speed"] == "%R100"
        assert inp.register_map["Status"] == "%SR10"

    def test_simulation_input_with_invalid_register_map_rejected(self):
        # Missing % prefix
        with pytest.raises(ValidationError) as exc_info:
            RunSimulationInput(
                steps=5,
                code="PROGRAM P END_PROGRAM",
                register_map={
                    "Start": "INVALID_REGISTER",
                },
            )
        assert "must start with '%'" in str(exc_info.value)

        # Invalid prefix with %
        with pytest.raises(ValidationError) as exc_info:
            RunSimulationInput(
                steps=5,
                code="PROGRAM P END_PROGRAM",
                register_map={
                    "Start": "%INVALID_REGISTER",
                },
            )
        assert "Invalid Horner OCS register format" in str(exc_info.value)

    def test_simulation_input_with_register_keys_in_inputs(self):
        # Valid register in input
        inp = RunSimulationInput(
            steps=5,
            code="PROGRAM P END_PROGRAM",
            inputs={"%R100": 42, "%M1": True, "RegularVar": 10},
        )
        assert inp.inputs["%R100"] == 42
        assert inp.inputs["%M1"] is True

        # Invalid register in input
        with pytest.raises(ValidationError) as exc_info:
            RunSimulationInput(
                steps=5,
                code="PROGRAM P END_PROGRAM",
                inputs={"%Z999": 1},
            )
        assert "Invalid Horner OCS register format" in str(exc_info.value)

