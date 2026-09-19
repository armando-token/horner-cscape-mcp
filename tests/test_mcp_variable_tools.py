"""Audit and Verification Test Suite for MCP Variable Tools.

Specifically audits and verifies:
1. Reading and writing variables.csv and variables.xml via MCP tools:
   - cscape_read_variables
   - cscape_write_variables
2. Validation of Horner OCS register addresses and data types:
   - %R, %M, %T, %AI, %AQ, %I, %Q, %S, %SR, %D, %K, %IG, %QG
   - Index bounds (%R1..%R9999, %M1..%M2048, %AI1..%AI512, %S1..%S128, etc.)
   - Bit-of-word indexing (%R1.1..%R1.16, %SR43.1)
   - Disallowing bit-offsets on discrete bit registers (%M1.1)
   - Supported IEC/Horner data types (BOOL, INT, REAL, STRING, DINT, UDINT, etc.)
   - Rejection of invalid data types and incompatible register assignments
   - Footprint calculation and memory collision/conflict detection
3. Bidirectional roundtrip consistency:
   - In-memory -> CSV -> Read CSV (exact fidelity)
   - In-memory -> XML -> Read XML (exact fidelity)
   - CSV -> Write to XML -> Read XML (cross-format roundtrip)
   - XML -> Write to CSV -> Read CSV (cross-format roundtrip)
4. FastMCP / MCPServer direct async dispatch:
   - server.call_tool("cscape_read_variables", ...)
   - server.call_tool("cscape_write_variables", ...)
"""

import json
from pathlib import Path
import pytest

from src.mcp.server import (
    server,
    cscape_read_variables,
    cscape_write_variables,
    cscape_import_variables,
    cscape_export_variables,
)
from src.cscape.variables import (
    CscapeVariable,
    HornerRegister,
    VariableManager,
    HORNER_REGISTER_LIMITS,
    SUPPORTED_DATA_TYPES,
)


@pytest.fixture
def sample_audit_variables():
    """Returns a rich set of variables covering Horner OCS register types and IEC data types."""
    return [
        {
            "name": "FirstScanPulse",
            "data_type": "BOOL",
            "scope": "globals",
            "tag": "%S001",
            "description": "First scan controller bit",
            "initial_value": "FALSE",
            "read_only": True,
        },
        {
            "name": "SystemHeartbeat",
            "data_type": "BOOL",
            "scope": "globals",
            "tag": "%SR43.1",
            "description": "Heartbeat pulse bit from SR43",
            "initial_value": "FALSE",
            "read_only": False,
        },
        {
            "name": "RunCommand",
            "data_type": "BOOL",
            "scope": "globals",
            "tag": "%M1",
            "description": "Operator run command",
            "initial_value": "FALSE",
            "read_only": False,
        },
        {
            "name": "TempTripRelay",
            "data_type": "BOOL",
            "scope": "globals",
            "tag": "%T1",
            "description": "Temporary trip flag",
            "initial_value": "FALSE",
            "read_only": False,
        },
        {
            "name": "EStopInput",
            "data_type": "BOOL",
            "scope": "globals",
            "tag": "%I1",
            "description": "Emergency Stop physical input",
            "initial_value": "TRUE",
            "read_only": True,
        },
        {
            "name": "MotorContactor",
            "data_type": "BOOL",
            "scope": "globals",
            "tag": "%Q1",
            "description": "Main motor contactor output",
            "initial_value": "FALSE",
            "read_only": False,
        },
        {
            "name": "MotorSpeedRPM",
            "data_type": "INT",
            "scope": "globals",
            "tag": "%R10",
            "description": "Target motor RPM",
            "initial_value": "1750",
            "read_only": False,
        },
        {
            "name": "BearingTempC",
            "data_type": "REAL",
            "scope": "globals",
            "tag": "%R100",  # spans %R100, %R101
            "description": "Bearing temperature in Celsius",
            "initial_value": "45.2",
            "read_only": False,
        },
        {
            "name": "AnalogPressureRaw",
            "data_type": "INT",
            "scope": "globals",
            "tag": "%AI1",
            "description": "Raw 4-20mA pressure sensor",
            "initial_value": "0",
            "read_only": True,
        },
        {
            "name": "AnalogValveCommand",
            "data_type": "INT",
            "scope": "globals",
            "tag": "%AQ1",
            "description": "Analog output valve positioning",
            "initial_value": "0",
            "read_only": False,
        },
        {
            "name": "RecipeCode",
            "data_type": "STRING",
            "string_length": 32,
            "scope": "retain",
            "tag": "%R500",  # spans %R500..%R516
            "description": "Active production recipe code",
            "initial_value": "'RECIPE-A'",
            "read_only": False,
        },
        {
            "name": "TotalPartsCounter",
            "data_type": "UDINT",
            "scope": "retain",
            "tag": "%R600",  # spans %R600, %R601
            "description": "Lifetime parts produced",
            "initial_value": "0",
            "read_only": False,
        },
    ]


# ==============================================================================
# 1. MCP Tool Registration & Schema Audit
# ==============================================================================

class TestMCPVariableToolRegistration:
    """Confirms registration and availability of variable tools in MCP server."""

    @pytest.mark.asyncio
    async def test_tools_registered_on_server(self):
        tools = await server.list_tools()
        tool_names = [t.name for t in tools]
        assert "cscape_read_variables" in tool_names
        assert "cscape_write_variables" in tool_names
        assert "cscape_import_variables" in tool_names
        assert "cscape_export_variables" in tool_names

    def test_direct_import_from_server(self):
        from src.mcp.server import (
            cscape_read_variables as r_var,
            cscape_write_variables as w_var,
        )
        assert callable(r_var)
        assert callable(w_var)


# ==============================================================================
# 2. Reading and Writing variables.csv and variables.xml
# ==============================================================================

class TestReadWriteVariablesCSVXML:
    """Verifies reading and writing variables.csv and variables.xml via MCP tools."""

    def test_write_and_read_variables_csv(self, tmp_path, sample_audit_variables):
        csv_file = tmp_path / "variables.csv"

        # 1. Write variables to CSV
        res_write = cscape_write_variables(
            output_path=str(csv_file),
            variables=sample_audit_variables,
            format_type="CSV",
            delimiter=";",
        )
        assert res_write["success"] is True
        assert res_write["format_type"] == "CSV"
        assert res_write["written_count"] == len(sample_audit_variables)
        assert res_write["validation_status"] == "VALID"
        assert csv_file.exists()
        assert res_write["file_size_bytes"] > 0

        # Verify CSV content on disk
        content = csv_file.read_text(encoding="utf-8")
        assert "BearingTempC" in content
        assert "%R100" in content
        assert "%S001" in content
        assert "%SR43.1" in content

        # 2. Read variables back from CSV
        res_read = cscape_read_variables(file_path=str(csv_file), delimiter=";")
        assert res_read["success"] is True
        assert res_read["format"] == "CSV"
        assert res_read["count"] == len(sample_audit_variables)
        assert res_read["validation_status"] == "VALID"
        assert len(res_read["variables"]) == len(sample_audit_variables)

        # Check specific variable fields
        v_map = {v["name"]: v for v in res_read["variables"]}
        assert v_map["BearingTempC"]["data_type"] == "REAL"
        assert v_map["BearingTempC"]["tag"] == "%R100"
        assert v_map["FirstScanPulse"]["tag"] == "%S001"
        assert v_map["SystemHeartbeat"]["tag"] == "%SR43.1"
        assert v_map["RecipeCode"]["string_length"] == 32
        assert v_map["RecipeCode"]["scope"] == "retain"

    def test_write_and_read_variables_xml(self, tmp_path, sample_audit_variables):
        xml_file = tmp_path / "variables.xml"

        # 1. Write variables to XML
        res_write = cscape_write_variables(
            output_path=str(xml_file),
            variables=sample_audit_variables,
            format_type="XML",
        )
        assert res_write["success"] is True
        assert res_write["format_type"] == "XML"
        assert res_write["written_count"] == len(sample_audit_variables)
        assert res_write["validation_status"] == "VALID"
        assert xml_file.exists()
        assert res_write["file_size_bytes"] > 0

        # Verify XML content structure
        xml_text = xml_file.read_text(encoding="utf-8")
        assert "<ProjectVariables" in xml_text
        assert '<vargroup name="globals">' in xml_text
        assert '<vargroup name="retain">' in xml_text
        assert 'varinfo type="tag" data="%R100"' in xml_text

        # 2. Read variables back from XML
        res_read = cscape_read_variables(file_path=str(xml_file))
        assert res_read["success"] is True
        assert res_read["format"] == "XML"
        assert res_read["count"] == len(sample_audit_variables)
        assert res_read["validation_status"] == "VALID"
        assert len(res_read["variables"]) == len(sample_audit_variables)

        v_map = {v["name"]: v for v in res_read["variables"]}
        assert v_map["TotalPartsCounter"]["data_type"] == "UDINT"
        assert v_map["TotalPartsCounter"]["tag"] == "%R600"
        assert v_map["AnalogPressureRaw"]["tag"] == "%AI1"
        assert v_map["AnalogPressureRaw"]["read_only"] is True

    def test_read_variables_from_directory_path(self, tmp_path, sample_audit_variables):
        """Confirms cscape_read_variables detects variables.csv or variables.xml when passed a directory."""
        csv_target = tmp_path / "variables.csv"
        cscape_write_variables(output_path=str(csv_target), variables=sample_audit_variables)

        # Pass directory path instead of full filename
        res = cscape_read_variables(file_path=str(tmp_path))
        assert res["success"] is True
        assert res["format"] == "CSV"
        assert res["count"] == len(sample_audit_variables)

    def test_read_nonexistent_file(self, tmp_path):
        res = cscape_read_variables(file_path=str(tmp_path / "non_existent.csv"))
        assert res["success"] is False
        assert res["validation_status"] == "INVALID"
        assert any("File not found" in e for e in res["validation_errors"])


# ==============================================================================
# 3. Validation of Horner OCS Register Addresses & Data Types
# ==============================================================================

class TestHornerRegisterAndTypeValidation:
    """Verifies strict validation of Horner OCS register addresses, data types, and bounds."""

    @pytest.mark.parametrize(
        "prefix,valid_idx,min_idx,max_idx",
        [
            ("%R", 500, 1, 9999),
            ("%M", 1024, 1, 2048),
            ("%T", 256, 1, 2048),
            ("%I", 64, 1, 2048),
            ("%Q", 32, 1, 2048),
            ("%AI", 8, 1, 512),
            ("%AQ", 4, 1, 512),
            ("%D", 100, 1, 1024),
            ("%K", 16, 1, 1024),
            ("%S", 7, 1, 128),
            ("%SR", 43, 1, 256),
            ("%IG", 100, 1, 2048),
            ("%QG", 100, 1, 2048),
        ],
    )
    def test_all_horner_register_types_valid(self, prefix, valid_idx, min_idx, max_idx):
        reg = HornerRegister.parse(f"{prefix}{valid_idx}")
        assert reg.prefix == prefix
        assert reg.index == valid_idx
        assert min_idx <= reg.index <= max_idx
        assert HornerRegister.is_valid(f"{prefix}{valid_idx}") is True

    @pytest.mark.parametrize(
        "invalid_reg",
        [
            "%XYZ100",        # Unknown prefix
            "%R0",            # Index 0 not allowed for Horner registers
            "%R10000",        # %R max is 9999
            "%M2049",         # %M max is 2048
            "%T2049",         # %T max is 2048
            "%AI513",         # %AI max is 512
            "%AQ513",         # %AQ max is 512
            "%S129",          # %S max is 128
            "%SR257",         # %SR max is 256
            "%R-1",           # Negative index
            "%M1.1",          # Bit offset on discrete bit register not allowed
            "%R1.17",         # Bit offset > 16 not allowed
            "%R1.-1",         # Negative bit offset
            "NotARegister",   # String without register syntax
        ],
    )
    def test_invalid_horner_registers_rejected(self, invalid_reg):
        assert HornerRegister.is_valid(invalid_reg) is False
        with pytest.raises(ValueError):
            HornerRegister.parse(invalid_reg)

    def test_bit_of_word_indexing_bounds(self):
        # Valid bit-of-word: 1..16
        r_low = HornerRegister.parse("%R1.1")
        assert r_low.bit_offset == 1
        assert r_low.is_bit is True

        r_high = HornerRegister.parse("%R1.16")
        assert r_high.bit_offset == 16
        assert r_high.is_bit is True

        r_sr = HornerRegister.parse("%SR43.1")
        assert r_sr.bit_offset == 1
        assert r_sr.prefix == "%SR"

    def test_data_type_validation_and_rejection(self, tmp_path):
        """Confirms variables with unsupported data types are flagged as INVALID."""
        bad_vars = [
            {
                "name": "InvalidTypeVar",
                "data_type": "BOGUS_TYPE",
                "tag": "%R10",
            }
        ]
        out_csv = tmp_path / "bad_type.csv"
        res = cscape_write_variables(str(out_csv), variables=bad_vars)
        assert res["validation_status"] == "INVALID"
        assert any("unsupported data type" in e for e in res["validation_errors"])

    def test_bit_register_and_data_type_compatibility(self, tmp_path):
        """Confirms 1-bit registers (%M, %T, %I, %Q, %R1.1) reject non-BOOL types."""
        incompatible_vars = [
            {
                "name": "IncompatibleVar",
                "data_type": "INT",  # 16-bit INT assigned to 1-bit %M1
                "tag": "%M1",
            }
        ]
        out_csv = tmp_path / "incompatible.csv"
        res = cscape_write_variables(str(out_csv), variables=incompatible_vars)
        assert res["validation_status"] == "INVALID"
        assert any("incompatible with 1-bit register" in e for e in res["validation_errors"])

    def test_register_word_span_overflow(self, tmp_path):
        """Confirms multi-word variables spanning beyond register limits are flagged."""
        overflow_vars = [
            {
                "name": "OverflowReal",
                "data_type": "REAL",  # 2 words at %R9999 would span %R9999 and %R10000 (overflow)
                "tag": "%R9999",
            }
        ]
        out_csv = tmp_path / "overflow.csv"
        res = cscape_write_variables(str(out_csv), variables=overflow_vars)
        assert res["validation_status"] == "INVALID"
        assert any("exceeding max limit" in e for e in res["validation_errors"])

    def test_register_overlap_collision_detection(self, tmp_path):
        """Confirms overlap conflict detection:

        - %R100 (REAL, 2 words) collides with %R101 (INT, 1 word)
        - %R200 (INT, 1 word) collides with %R200.1 (BOOL, bit-of-word)
        - %R300.5 collides with %R300.5
        - %R300.1 and %R300.2 do NOT collide (independent bits)
        """
        colliding_vars = [
            {"name": "TempA", "data_type": "REAL", "tag": "%R100"},  # spans %R100, %R101
            {"name": "TempB", "data_type": "INT", "tag": "%R101"},   # collision with %R101
            {"name": "WordControl", "data_type": "INT", "tag": "%R200"},
            {"name": "BitControl", "data_type": "BOOL", "tag": "%R200.1"}, # collision with %R200
            {"name": "Flag1", "data_type": "BOOL", "tag": "%R300.1"},
            {"name": "Flag2", "data_type": "BOOL", "tag": "%R300.2"},     # independent bit - no collision
        ]
        out_csv = tmp_path / "collisions.csv"
        res = cscape_write_variables(str(out_csv), variables=colliding_vars)
        assert res["conflicts_detected"] >= 2
        assert res["validation_status"] == "INVALID"

        conflicts = res["conflict_details"]
        conflict_pairs = [
            (c["variable1"], c["variable2"]) for c in conflicts
        ]
        assert any(("TempA" in p and "TempB" in p) for p in conflict_pairs)
        assert any(("WordControl" in p and "BitControl" in p) for p in conflict_pairs)


# ==============================================================================
# 4. Bidirectional Roundtrip Consistency
# ==============================================================================

class TestBidirectionalRoundtripConsistency:
    """Verifies roundtrip preservation between in-memory, CSV, XML, and cross-format conversion."""

    def test_in_memory_to_csv_roundtrip_consistency(self, tmp_path, sample_audit_variables):
        csv_file = tmp_path / "roundtrip.csv"

        # Step 1: Write to CSV
        w_res = cscape_write_variables(str(csv_file), variables=sample_audit_variables, format_type="CSV")
        assert w_res["success"] is True

        # Step 2: Read from CSV
        r_res = cscape_read_variables(str(csv_file))
        assert r_res["success"] is True
        assert r_res["count"] == len(sample_audit_variables)

        # Step 3: Compare each variable property
        orig_map = {v["name"]: v for v in sample_audit_variables}
        for read_v in r_res["variables"]:
            name = read_v["name"]
            assert name in orig_map
            orig = orig_map[name]
            assert read_v["data_type"] == orig["data_type"]
            assert read_v["tag"] == orig["tag"]
            assert read_v["scope"] == orig["scope"]
            if orig.get("string_length"):
                assert read_v["string_length"] == orig["string_length"]
            if orig.get("initial_value"):
                assert read_v["initial_value"] == orig["initial_value"]

    def test_in_memory_to_xml_roundtrip_consistency(self, tmp_path, sample_audit_variables):
        xml_file = tmp_path / "roundtrip.xml"

        # Step 1: Write to XML
        w_res = cscape_write_variables(str(xml_file), variables=sample_audit_variables, format_type="XML")
        assert w_res["success"] is True

        # Step 2: Read from XML
        r_res = cscape_read_variables(str(xml_file))
        assert r_res["success"] is True
        assert r_res["count"] == len(sample_audit_variables)

        # Step 3: Compare each variable property
        orig_map = {v["name"]: v for v in sample_audit_variables}
        for read_v in r_res["variables"]:
            name = read_v["name"]
            assert name in orig_map
            orig = orig_map[name]
            assert read_v["data_type"] == orig["data_type"]
            assert read_v["tag"] == orig["tag"]
            assert read_v["scope"] == orig["scope"]
            assert read_v["description"] == orig["description"]

    def test_csv_to_xml_cross_format_roundtrip(self, tmp_path, sample_audit_variables):
        """Converts CSV -> XML -> CSV and confirms complete bidirectional consistency."""
        csv_file1 = tmp_path / "step1.csv"
        xml_file = tmp_path / "step2.xml"
        csv_file2 = tmp_path / "step3.csv"

        # 1. Write CSV
        cscape_write_variables(str(csv_file1), variables=sample_audit_variables, format_type="CSV")

        # 2. Convert CSV -> XML using source_file
        cscape_write_variables(str(xml_file), format_type="XML", source_file=str(csv_file1))
        assert xml_file.exists()

        # 3. Convert XML -> CSV using source_file
        cscape_write_variables(str(csv_file2), format_type="CSV", source_file=str(xml_file))
        assert csv_file2.exists()

        # 4. Read back final CSV and compare with initial
        res_final = cscape_read_variables(str(csv_file2))
        assert res_final["count"] == len(sample_audit_variables)
        assert res_final["validation_status"] == "VALID"

        final_map = {v["name"]: v for v in res_final["variables"]}
        orig_map = {v["name"]: v for v in sample_audit_variables}
        for name, orig in orig_map.items():
            assert name in final_map
            assert final_map[name]["tag"] == orig["tag"]
            assert final_map[name]["data_type"] == orig["data_type"]


# ==============================================================================
# 5. MCP Server FastMCP Async Protocol Execution
# ==============================================================================

class TestMCPServerAsyncProtocolCalls:
    """Verifies calling cscape_read_variables and cscape_write_variables through FastMCP server.call_tool()."""

    @pytest.mark.asyncio
    async def test_call_tool_write_and_read_variables(self, tmp_path, sample_audit_variables):
        csv_path = str(tmp_path / "mcp_protocol_vars.csv")

        # Call cscape_write_variables via server.call_tool
        write_call = await server.call_tool(
            "cscape_write_variables",
            {
                "output_path": csv_path,
                "variables": sample_audit_variables,
                "format_type": "CSV",
            },
        )
        assert not write_call.is_error
        assert len(write_call.content) > 0
        w_data = json.loads(write_call.content[0].text)
        assert w_data["success"] is True
        assert w_data["written_count"] == len(sample_audit_variables)
        assert w_data["validation_status"] == "VALID"

        # Call cscape_read_variables via server.call_tool
        read_call = await server.call_tool(
            "cscape_read_variables",
            {
                "file_path": csv_path,
            },
        )
        assert not read_call.is_error
        assert len(read_call.content) > 0
        r_data = json.loads(read_call.content[0].text)
        assert r_data["success"] is True
        assert r_data["count"] == len(sample_audit_variables)
        assert r_data["validation_status"] == "VALID"
        assert len(r_data["variables"]) == len(sample_audit_variables)


# ==============================================================================
# 6. Register Scopes Export Without Schema Truncation (%R, %M, %AI, %AQ, %I, %Q, %S, %SR)
# ==============================================================================

class TestExportRegisterScopesNoSchemaTruncation:
    """Ensures export_csv and export_xml cleanly export all register scopes without schema truncation."""

    @pytest.fixture
    def full_scope_variables(self):
        return [
            CscapeVariable(name="Reg_R1", data_type="INT", tag="%R1", scope="globals", description="Retentive register 1"),
            CscapeVariable(name="Bit_M1", data_type="BOOL", tag="%M1", scope="globals", description="Internal bit 1"),
            CscapeVariable(name="Ana_AI1", data_type="INT", tag="%AI1", scope="globals", description="Analog input 1", read_only=True),
            CscapeVariable(name="Ana_AQ1", data_type="INT", tag="%AQ1", scope="globals", description="Analog output 1"),
            CscapeVariable(name="In_I1", data_type="BOOL", tag="%I1", scope="globals", description="Digital input 1", read_only=True),
            CscapeVariable(name="Out_Q1", data_type="BOOL", tag="%Q1", scope="globals", description="Digital output 1"),
            CscapeVariable(name="Sys_S1", data_type="BOOL", tag="%S001", scope="globals", description="System bit 1", read_only=True),
            CscapeVariable(name="Sys_SR1", data_type="INT", tag="%SR1", scope="globals", description="System register 1", read_only=True),
        ]

    def test_export_all_register_scopes_xml_no_truncation(self, tmp_path, full_scope_variables):
        vm = VariableManager(project_name="FullScopesTest")
        for v in full_scope_variables:
            vm.add_variable(v)

        xml_out = tmp_path / "all_scopes.xml"
        register_scopes = ["%R", "%M", "%AI", "%AQ", "%I", "%Q", "%S", "%SR"]
        xml_str = vm.export_xml(destination=xml_out, scopes=register_scopes)

        assert xml_out.exists()
        assert len(xml_str) > 0

        # Verify all 8 registers are present in XML
        for reg in ["%R1", "%M1", "%AI1", "%AQ1", "%I1", "%Q1", "%S001", "%SR1"]:
            assert reg in xml_str, f"Missing register {reg} in XML export"

        # Roundtrip read to ensure zero schema truncation
        vm_read = VariableManager(project_name="FullScopesRead")
        count = vm_read.import_xml(xml_out)
        assert count == 8
        for v in full_scope_variables:
            read_var = vm_read.get_variable(v.name, v.scope)
            assert read_var is not None, f"Variable {v.name} missing after XML roundtrip"
            assert read_var.tag == v.tag
            assert read_var.data_type == v.data_type
            assert read_var.read_only == v.read_only

    def test_export_all_register_scopes_csv_no_truncation(self, tmp_path, full_scope_variables):
        vm = VariableManager(project_name="FullScopesCSVTest")
        for v in full_scope_variables:
            vm.add_variable(v)

        csv_out = tmp_path / "all_scopes.csv"
        register_scopes = ["%R", "%M", "%AI", "%AQ", "%I", "%Q", "%S", "%SR"]
        csv_str = vm.export_csv(destination=csv_out, delimiter=";", scopes=register_scopes)

        assert csv_out.exists()
        assert len(csv_str) > 0

        # Verify all 8 registers are present in CSV
        for reg in ["%R1", "%M1", "%AI1", "%AQ1", "%I1", "%Q1", "%S001", "%SR1"]:
            assert reg in csv_str, f"Missing register {reg} in CSV export"

        # Roundtrip read to ensure zero schema truncation
        vm_read = VariableManager(project_name="FullScopesCSVRead")
        count = vm_read.import_csv(csv_out, delimiter=";")
        assert count == 8
        for v in full_scope_variables:
            read_var = vm_read.get_variable(v.name, v.scope)
            assert read_var is not None, f"Variable {v.name} missing after CSV roundtrip"
            assert read_var.tag == v.tag
            assert read_var.data_type == v.data_type

    def test_export_single_register_scope_filter(self, tmp_path, full_scope_variables):
        vm = VariableManager(project_name="FilterTest")
        for v in full_scope_variables:
            vm.add_variable(v)

        # Filter only %AI scope
        ai_xml = vm.export_xml(scopes=["%AI"])
        assert "%AI1" in ai_xml
        assert "%R1" not in ai_xml
        assert "%M1" not in ai_xml

        # Filter only %R scope
        r_csv = vm.export_csv(scopes=["%R"])
        assert "%R1" in r_csv
        assert "%AI1" not in r_csv
        assert "%Q1" not in r_csv
