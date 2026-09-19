"""Unit tests for Horner Cscape Variable and Tag Database Management.

Verifies:
- Horner OCS register addressing (%R, %M, %T, %AI, %AQ, %I, %Q, %S, %SR, %D, %K, %IG, %QG)
- Bit-of-word indexing (%R1.1, %SR43.1)
- Address normalization and validation
- Contiguous register footprint and collision/overlap detection
- Automatic register allocator
- Bidirectional Cscape XML parser and serializer (<ProjectVariables>)
- Bidirectional Cscape CSV parser and serializer (semicolon and comma delimited)
- IEC 61131-3 text mode declaration parser and serializer
- VariableManager / TagDatabase CRUD, query filtering, and project sync
- Parsing real Cscape installation XML templates
"""

import os
import tempfile
from pathlib import Path
import pytest

from src.cscape.variables import (
    CscapeCSVParser,
    CscapeCSVSerializer,
    CscapeIECParser,
    CscapeIECSerializer,
    CscapeVariable,
    CscapeVariableManager,
    CscapeXMLParser,
    CscapeXMLSerializer,
    HornerRegister,
    HORNER_REGISTER_LIMITS,
    RegisterType,
    TagDatabase,
    VariableManager,
)


# ===========================================================================
# 1. Horner OCS Register Addressing Tests
# ===========================================================================

class TestHornerRegisterAddressing:
    """Tests for Horner OCS register syntax, validation, bit indexing, and normalization."""

    @pytest.mark.parametrize(
        "addr,expected_prefix,expected_index,expected_bit",
        [
            ("%R1", "%R", 1, None),
            ("%R100", "%R", 100, None),
            ("%r500", "%R", 500, None),
            ("%M1", "%M", 1, None),
            ("%m2048", "%M", 2048, None),
            ("%T1", "%T", 1, None),
            ("%T256", "%T", 256, None),
            ("%AI1", "%AI", 1, None),
            ("%ai8", "%AI", 8, None),
            ("%AQ1", "%AQ", 1, None),
            ("%aq4", "%AQ", 4, None),
            ("%I1", "%I", 1, None),
            ("%i64", "%I", 64, None),
            ("%Q1", "%Q", 1, None),
            ("%q32", "%Q", 32, None),
            ("%S1", "%S", 1, None),
            ("%S007", "%S", 7, None),
            ("%SR1", "%SR", 1, None),
            ("%SR029", "%SR", 29, None),
            ("%D1", "%D", 1, None),
            ("%K1", "%K", 1, None),
            ("%IG1", "%IG", 1, None),
            ("%QG1", "%QG", 1, None),
            ("%AIG1", "%AIG", 1, None),
            ("%AQG1", "%AQG", 1, None),
            ("%R100.1", "%R", 100, 1),
            ("%R100.16", "%R", 100, 16),
            ("%SR043.1", "%SR", 43, 1),
            ("%R100.0", "%R", 100, 0),
            ("R100", "%R", 100, None),  # Auto-prepends '%'
        ],
    )
    def test_parse_valid_registers(self, addr, expected_prefix, expected_index, expected_bit):
        reg = HornerRegister.parse(addr)
        assert reg.prefix == expected_prefix
        assert reg.index == expected_index
        assert reg.bit_offset == expected_bit
        assert HornerRegister.is_valid(addr) is True

    @pytest.mark.parametrize(
        "invalid_addr",
        [
            "",
            "   ",
            "%XYZ100",
            "%R",
            "%R-5",
            "%R0",
            "%R1.25",      # Bit offset > 16
            "%R1.-1",
            "123",
            "%%R100",
            "%R100.abc",
        ],
    )
    def test_parse_invalid_registers_raises(self, invalid_addr):
        with pytest.raises(ValueError):
            HornerRegister.parse(invalid_addr)
        assert HornerRegister.is_valid(invalid_addr) is False

    def test_register_normalization(self):
        assert HornerRegister.normalize("%r1") == "%R1"
        assert HornerRegister.normalize("%s7", pad_zeros=3) == "%S007"
        assert HornerRegister.normalize("%sr043.1") == "%SR43.1"
        assert HornerRegister.normalize("r50") == "%R50"

    def test_register_classification_properties(self):
        r_word = HornerRegister.parse("%R100")
        assert r_word.is_word is True
        assert r_word.is_bit is False
        assert r_word.is_retentive is True
        assert r_word.is_read_only is False

        r_bit = HornerRegister.parse("%R100.1")
        assert r_bit.is_word is False
        assert r_bit.is_bit is True

        m_bit = HornerRegister.parse("%M5")
        assert m_bit.is_bit is True
        assert m_bit.is_word is False
        assert m_bit.is_retentive is True

        t_bit = HornerRegister.parse("%T1")
        assert t_bit.is_bit is True
        assert t_bit.is_retentive is False

        ai_word = HornerRegister.parse("%AI1")
        assert ai_word.is_analog is True
        assert ai_word.is_read_only is True

        s_bit = HornerRegister.parse("%S7")
        assert s_bit.is_system is True
        assert s_bit.is_read_only is True


# ===========================================================================
# 2. Footprint & Memory Overlap Tests
# ===========================================================================

class TestRegisterFootprintAndOverlap:
    """Tests memory span calculations and collision detection."""

    def test_word_span_by_data_type(self):
        reg = HornerRegister.parse("%R100")
        assert reg.get_word_span("BOOL") == 1
        assert reg.get_word_span("INT") == 1
        assert reg.get_word_span("UINT") == 1
        assert reg.get_word_span("WORD") == 1
        assert reg.get_word_span("DINT") == 2
        assert reg.get_word_span("UDINT") == 2
        assert reg.get_word_span("REAL") == 2
        assert reg.get_word_span("TIME") == 2
        assert reg.get_word_span("LREAL") == 4
        assert reg.get_word_span("LINT") == 4

        # Array of 10 INTs = 10 words
        assert reg.get_word_span("INT", dim_count=10) == 10
        # Array of 5 REALs = 10 words
        assert reg.get_word_span("REAL", dim_count=5) == 10

        # STRING(80): (80 + 1) / 2 = 41 words
        assert reg.get_word_span("STRING", string_len=80) == 41

    def test_occupied_registers_list(self):
        r_dint = HornerRegister.parse("%R10")
        assert r_dint.get_occupied_registers("DINT") == ["%R10", "%R11"]

        r_lreal = HornerRegister.parse("%R100")
        assert r_lreal.get_occupied_registers("LREAL") == ["%R100", "%R101", "%R102", "%R103"]

        r_bit = HornerRegister.parse("%M5")
        assert r_bit.get_occupied_registers("BOOL") == ["%M5"]

    def test_overlaps_detection(self):
        r1 = HornerRegister.parse("%R100")  # DINT -> %R100, %R101
        r2 = HornerRegister.parse("%R101")  # INT -> %R101
        r3 = HornerRegister.parse("%R102")  # INT -> %R102

        # r1 and r2 overlap at %R101
        assert r1.overlaps_with(r2, self_type="DINT", other_type="INT") is True
        assert r2.overlaps_with(r1, self_type="INT", other_type="DINT") is True

        # r1 and r3 do not overlap
        assert r1.overlaps_with(r3, self_type="DINT", other_type="INT") is False

        # Different prefixes never overlap
        r_ai = HornerRegister.parse("%AI100")
        assert r1.overlaps_with(r_ai, self_type="DINT", other_type="INT") is False

    def test_bit_of_word_overlaps(self):
        r_word = HornerRegister.parse("%R100")
        r_bit1 = HornerRegister.parse("%R100.1")
        r_bit2 = HornerRegister.parse("%R100.2")

        # Full word %R100 overlaps with bit-of-word %R100.1
        assert r_word.overlaps_with(r_bit1, self_type="INT", other_type="BOOL") is True

        # Two different bit offsets on the same word do NOT overlap each other
        assert r_bit1.overlaps_with(r_bit2, self_type="BOOL", other_type="BOOL") is False

        # Same bit offset DOES overlap
        r_bit1_dup = HornerRegister.parse("%R100.1")
        assert r_bit1.overlaps_with(r_bit1_dup, self_type="BOOL", other_type="BOOL") is True


# ===========================================================================
# 3. Cscape Variable Model Tests
# ===========================================================================

class TestCscapeVariableModel:
    """Tests variable creation, validation, attributes, and IEC code generation."""

    def test_create_valid_variable(self):
        var = CscapeVariable(
            name="MotorSpeed",
            data_type="REAL",
            scope="globals",
            tag="%R100",
            description="Motor shaft speed in RPM",
            initial_value="0.0",
        )
        assert var.name == "MotorSpeed"
        assert var.data_type == "REAL"
        assert var.scope == "globals"
        assert var.tag == "%R100"
        assert var.occupied_registers() == ["%R100", "%R101"]
        assert var.validate() == []

    def test_string_length_inference(self):
        var = CscapeVariable(name="BatchName", data_type="STRING(50)")
        assert var.data_type == "STRING"
        assert var.string_length == 50

    def test_array_dimensions_calculation(self):
        var1 = CscapeVariable(name="Counts", data_type="INT", dimensions="10")
        assert var1.is_array is True
        assert var1.array_element_count == 10
        assert len(var1.occupied_registers()) == 0  # no tag yet

        var1.tag = "%R10"
        assert len(var1.occupied_registers()) == 10

        var2 = CscapeVariable(name="Matrix", data_type="REAL", dimensions="2, 5")
        assert var2.array_element_count == 10
        var2.tag = "%R100"
        # 10 elements * 2 words = 20 words
        assert len(var2.occupied_registers()) == 20

    def test_validation_errors(self):
        # Invalid variable name
        v_bad_name = CscapeVariable(name="123_invalid", data_type="BOOL")
        errs = v_bad_name.validate()
        assert any("invalid characters" in e for e in errs)

        # Consecutive underscores
        v_double_under = CscapeVariable(name="Motor__Speed", data_type="INT")
        assert any("consecutive underscores" in e for e in v_double_under.validate())

        # Invalid tag
        v_bad_tag = CscapeVariable(name="ValidName", data_type="INT", tag="%INVALID")
        assert any("invalid register tag" in e for e in v_bad_tag.validate())

    def test_iec_declaration_formatting(self):
        var = CscapeVariable(
            name="TargetTemp",
            data_type="REAL",
            initial_value="75.5",
            tag="%R200",
            description="Setpoint in Celsius",
            read_only=True,
        )
        decl = var.to_iec_declaration(indent="")
        assert "CONSTANT TargetTemp : REAL := 75.5;" in decl
        assert "(*$tag=%R200*)" in decl
        assert "(*$desc=Setpoint in Celsius*)" in decl


# ===========================================================================
# 4. Bidirectional XML Parser & Serializer Tests
# ===========================================================================

class TestCscapeXMLBidirectional:
    """Tests XML export and import matching Cscape 10.2 format."""

    def test_serialize_and_parse_roundtrip(self):
        vars_in = [
            CscapeVariable(
                name="FST_SCN",
                data_type="BOOL",
                scope="globals",
                tag="%S001",
                description="First scan bit",
            ),
            CscapeVariable(
                name="RawSpeed",
                data_type="INT",
                scope="globals",
                tag="%AI1",
                description="Raw analog tachometer input",
                usergroup="Telemetry",
            ),
            CscapeVariable(
                name="SetpointRPM",
                data_type="REAL",
                scope="globals",
                tag="%R100",
                initial_value="1500.0",
            ),
            CscapeVariable(
                name="PartRecipe",
                data_type="STRING",
                scope="retain",
                string_length=40,
                tag="%R500",
                description="Selected batch recipe string",
            ),
            CscapeVariable(
                name="BufferTable",
                data_type="UINT",
                scope="retain",
                dimensions="16",
                tag="%R600",
            ),
        ]

        xml_str = CscapeXMLSerializer.serialize(vars_in)
        assert "<ProjectVariables version=\"1.0\">" in xml_str
        assert "<vargroup name=\"globals\">" in xml_str
        assert "<vargroup name=\"retain\">" in xml_str
        assert "<varinfo type=\"tag\" data=\"%S001\"" in xml_str

        # Parse back
        vars_out = CscapeXMLParser.parse(xml_str)
        assert len(vars_out) == len(vars_in)

        out_map = {v.name: v for v in vars_out}
        assert "FST_SCN" in out_map
        assert out_map["FST_SCN"].tag == "%S001"
        assert out_map["FST_SCN"].data_type == "BOOL"
        assert out_map["FST_SCN"].scope == "globals"

        assert "PartRecipe" in out_map
        assert out_map["PartRecipe"].scope == "retain"
        assert out_map["PartRecipe"].string_length == 40
        assert out_map["PartRecipe"].tag == "%R500"

        assert "BufferTable" in out_map
        assert out_map["BufferTable"].dimensions == "16"

    def test_xml_special_character_escaping(self):
        var = CscapeVariable(
            name="TestEscapes",
            data_type="BOOL",
            description="Checking <tag> & \"quotes\" and 'apostrophe'",
            initial_value="TRUE",
        )
        xml_str = CscapeXMLSerializer.serialize([var])
        assert "&lt;tag&gt;" in xml_str
        assert "&amp;" in xml_str

        parsed = CscapeXMLParser.parse(xml_str)
        assert len(parsed) == 1
        assert parsed[0].description == "Checking <tag> & \"quotes\" and 'apostrophe'"


# ===========================================================================
# 5. Bidirectional CSV Parser & Serializer Tests
# ===========================================================================

class TestCscapeCSVBidirectional:
    """Tests CSV export and import conforming to Cscape CSV Mode Variables Editor."""

    def test_csv_semicolon_native_roundtrip(self):
        vars_in = [
            CscapeVariable(
                name="PumpState",
                data_type="BOOL",
                scope="globals",
                tag="%M10",
                description="Primary feed pump active flag",
                initial_value="FALSE",
                read_only=False,
            ),
            CscapeVariable(
                name="FlowRate",
                data_type="REAL",
                scope="globals",
                tag="%R200",
                description="Flow in L/min",
                initial_value="0.0",
                read_only=True,
            ),
            CscapeVariable(
                name="UnitSerial",
                data_type="STRING",
                scope="globals",
                string_length=32,
                initial_value="'SN-9901'",
            ),
        ]

        csv_str = CscapeCSVSerializer.serialize(vars_in, delimiter=";")
        lines = csv_str.strip().splitlines()
        assert len(lines) == 4  # header + 3 rows
        assert ";" in lines[0]
        assert '"name";"type"' in lines[0]

        # Parse back
        vars_out = CscapeCSVParser.parse(csv_str, delimiter=";")
        assert len(vars_out) == 3

        v_map = {v.name: v for v in vars_out}
        assert v_map["PumpState"].tag == "%M10"
        assert v_map["PumpState"].read_only is False
        assert v_map["FlowRate"].tag == "%R200"
        assert v_map["FlowRate"].read_only is True
        assert v_map["UnitSerial"].string_length == 32

    def test_csv_comma_delimiter_auto_detection(self):
        vars_in = [
            CscapeVariable(name="Valve1", data_type="BOOL", tag="%Q1"),
            CscapeVariable(name="Valve2", data_type="BOOL", tag="%Q2"),
        ]
        csv_str = CscapeCSVSerializer.serialize(vars_in, delimiter=",")
        assert "," in csv_str

        # Parse without specifying delimiter -> should auto-detect
        vars_out = CscapeCSVParser.parse(csv_str)
        assert len(vars_out) == 2
        assert vars_out[0].name == "Valve1"
        assert vars_out[0].tag == "%Q1"


# ===========================================================================
# 6. IEC Text Mode Parser & Serializer Tests
# ===========================================================================

class TestCscapeIECTextMode:
    """Tests parsing and serializing IEC declaration blocks with (*$tag*) directives."""

    def test_iec_block_roundtrip(self):
        vars_in = [
            CscapeVariable(
                name="StartPB",
                data_type="BOOL",
                scope="globals",
                tag="%I1",
                description="Green start pushbutton",
            ),
            CscapeVariable(
                name="TargetTemp",
                data_type="REAL",
                scope="globals",
                tag="%R50",
                initial_value="120.0",
                description="Oven target temperature",
            ),
            CscapeVariable(
                name="MaxThreshold",
                data_type="INT",
                scope="globals",
                read_only=True,
                initial_value="500",
            ),
        ]

        iec_text = CscapeIECSerializer.serialize_block(vars_in, scope_header="VAR_GLOBAL")
        assert "VAR_GLOBAL" in iec_text
        assert "StartPB : BOOL;" in iec_text
        assert "(*$tag=%I1*)" in iec_text
        assert "CONSTANT MaxThreshold : INT := 500;" in iec_text
        assert "END_VAR" in iec_text

        # Parse back
        parsed = CscapeIECParser.parse(iec_text)
        assert len(parsed) == 3

        p_map = {v.name: v for v in parsed}
        assert p_map["StartPB"].tag == "%I1"
        assert p_map["StartPB"].description == "Green start pushbutton"
        assert p_map["TargetTemp"].initial_value == "120.0"
        assert p_map["TargetTemp"].tag == "%R50"
        assert p_map["MaxThreshold"].read_only is True


# ===========================================================================
# 7. VariableManager / TagDatabase Tests
# ===========================================================================

class TestVariableManagerOperations:
    """Tests CRUD operations, conflict detection, auto-allocation, and project synchronization."""

    def test_crud_operations(self):
        vm = VariableManager(project_name="BatchControl")
        assert vm.total_count == 0

        # Add
        v1 = CscapeVariable(name="RunCmd", data_type="BOOL", tag="%M1")
        vm.add_variable(v1)
        assert vm.total_count == 1

        # Get
        retrieved = vm.get_variable("RunCmd")
        assert retrieved is not None
        assert retrieved.tag == "%M1"

        # Update
        vm.update_variable("RunCmd", tag="%M2", description="Updated command")
        updated = vm.get_variable("RunCmd")
        assert updated is not None
        assert updated.tag == "%M2"
        assert updated.description == "Updated command"

        # Duplicate without overwrite raises
        with pytest.raises(ValueError):
            vm.add_variable(v1, overwrite=False)

        # Remove
        assert vm.remove_variable("RunCmd") is True
        assert vm.total_count == 0

    def test_conflict_detection_multi_word_overlap(self):
        vm = VariableManager()

        # Variable 1: DINT at %R10 occupies %R10 and %R11
        vm.add_variable(CscapeVariable(name="EncoderPos", data_type="DINT", tag="%R10"))

        # Variable 2: INT at %R11 collides with %R11
        vm.add_variable(CscapeVariable(name="CycleCounter", data_type="INT", tag="%R11"))

        # Variable 3: INT at %R12 does NOT collide
        vm.add_variable(CscapeVariable(name="SafeCounter", data_type="INT", tag="%R12"))

        conflicts = vm.detect_conflicts()
        assert len(conflicts) == 1
        c = conflicts[0]
        assert (c["variable1"] == "EncoderPos" and c["variable2"] == "CycleCounter") or \
               (c["variable1"] == "CycleCounter" and c["variable2"] == "EncoderPos")
        assert "%R11" in c["reason"]

    def test_automatic_register_allocation(self):
        vm = VariableManager()

        # Pre-assign %R1, %R2, %R3
        vm.add_variable(CscapeVariable(name="V1", data_type="DINT", tag="%R1"))  # spans %R1, %R2
        vm.add_variable(CscapeVariable(name="V2", data_type="INT", tag="%R3"))   # spans %R3

        # Allocate INT: next free is %R4
        next_r = vm.allocate_register(data_type="INT", prefix="%R", start_index=1)
        assert next_r == "%R4"

        # Pre-assign %R4 to %R5
        vm.add_variable(CscapeVariable(name="V3", data_type="DINT", tag="%R4")) # spans %R4, %R5

        # Allocate DINT (requires 2 contiguous words): next free is %R6
        next_dint = vm.allocate_register(data_type="DINT", prefix="%R", start_index=1)
        assert next_dint == "%R6"

        # Allocate bit: %M1
        vm.add_variable(CscapeVariable(name="B1", data_type="BOOL", tag="%M1"))
        next_m = vm.allocate_register(data_type="BOOL", prefix="%M", start_index=1)
        assert next_m == "%M2"

    def test_filter_and_queries(self):
        vm = VariableManager()
        vm.add_variable(CscapeVariable(name="G_Var1", data_type="INT", scope="globals", tag="%R1"))
        vm.add_variable(CscapeVariable(name="G_Var2", data_type="REAL", scope="globals"))
        vm.add_variable(CscapeVariable(name="R_Var1", data_type="INT", scope="retain", tag="%R10"))

        # Filter by scope
        globals_list = vm.list_variables(scope="globals")
        assert len(globals_list) == 2

        retain_list = vm.list_variables(scope="retain")
        assert len(retain_list) == 1

        # Filter by data_type
        reals = vm.list_variables(data_type="REAL")
        assert len(reals) == 1
        assert reals[0].name == "G_Var2"

        # Filter by has_tag
        tagged = vm.list_variables(has_tag=True)
        assert len(tagged) == 2
        untagged = vm.list_variables(has_tag=False)
        assert len(untagged) == 1
        assert untagged[0].name == "G_Var2"

    def test_sync_to_and_load_from_project(self, tmp_path):
        vm = VariableManager(project_name="TestProject")
        vm.add_variable(CscapeVariable(
            name="MotorTemp",
            data_type="REAL",
            scope="globals",
            tag="%R100",
            description="Bearing temperature in degC",
            initial_value="25.0",
        ))
        vm.add_variable(CscapeVariable(
            name="CycleCount",
            data_type="UDINT",
            scope="retain",
            tag="%R200",
            description="Total production cycle counter",
        ))

        sync_result = vm.sync_to_project(tmp_path)
        assert sync_result["variables_count"] == 2
        assert not (tmp_path / "Default" / "appli.txt").exists()
        assert (tmp_path / "variables.xml").exists()
        assert (tmp_path / "variables.csv").exists()

        # Create new manager and load from project (via variables.xml)
        vm2 = VariableManager()
        loaded_count = vm2.load_from_project(tmp_path)
        assert loaded_count == 2
        v_motor = vm2.get_variable("MotorTemp")
        assert v_motor is not None
        assert v_motor.tag == "%R100"
        assert v_motor.data_type == "REAL"
        assert v_motor.description == "Bearing temperature in degC"

        # Verify fallback loading from variables.csv when variables.xml is removed
        (tmp_path / "variables.xml").unlink()
        vm3 = VariableManager()
        loaded_csv_count = vm3.load_from_project(tmp_path)
        assert loaded_csv_count == 2
        v_cycle = vm3.get_variable("CycleCount", scope="retain")
        assert v_cycle is not None
        assert v_cycle.tag == "%R200"
        assert v_cycle.data_type == "UDINT"


# ===========================================================================
# 8. Real Cscape Installed Template Integration Tests
# ===========================================================================

class TestRealCscapeInstallationXML:
    """Parses real Cscape 10.2 XML templates if installed on the host."""

    def test_parse_predefined_variables_if_present(self):
        xml_path = Path(r"C:\Program Files (x86)\Cscape 10.2\PredefinedVariablesforIEC.xml")
        if not xml_path.exists():
            pytest.skip("Cscape 10.2 installation directory not found on host.")

        vars_parsed = CscapeXMLParser.parse(xml_path)
        assert len(vars_parsed) > 10

        # Check for Horner system variables known to be in this file
        var_names = {v.name.upper() for v in vars_parsed}
        assert "FST_SCN" in var_names
        assert "ALW_ON" in var_names
        assert "ALW_OFF" in var_names

        v_fst = next(v for v in vars_parsed if v.name.upper() == "FST_SCN")
        assert v_fst.tag == "%S001"
        assert v_fst.data_type == "BOOL"

        v_usr_scr = next((v for v in vars_parsed if v.name.upper() == "USER_SCR"), None)
        if v_usr_scr:
            assert v_usr_scr.tag == "%SR001"

    def test_parse_io_variables_if_present(self):
        xml_path = Path(r"C:\Program Files (x86)\Cscape 10.2\IOVariables.xml")
        if not xml_path.exists():
            pytest.skip("Cscape 10.2 installation directory not found on host.")

        # Note: IOVariables.xml has example XML commented out, but parser should safely handle empty or comments
        vars_parsed = CscapeXMLParser.parse(xml_path)
        assert isinstance(vars_parsed, list)


# ===========================================================================
# 9. CscapeVariableManager Comprehensive Audit & Verification Tests
# ===========================================================================

class TestCscapeVariableManagerAudit:
    """Rigorous audit verifying CscapeVariableManager supports Horner OCS registers,

    bit-of-word addressing, and CSV/XML import/export.
    """

    def test_cscape_variable_manager_supports_all_ocs_registers(self):
        """Verify CscapeVariableManager fully supports Horner OCS registers:

        %R, %M, %T, %AI, %AQ, %I, %Q.
        """
        vm = CscapeVariableManager("OCS_Register_Audit")

        # Define variables across all required Horner OCS register types
        test_vars = [
            CscapeVariable(name="HoldingReg", data_type="INT", tag="%R1", description="General retentive word"),
            CscapeVariable(name="InternalBit", data_type="BOOL", tag="%M1", description="Retentive internal bit"),
            CscapeVariable(name="TempBit", data_type="BOOL", tag="%T1", description="Non-retentive temporary bit"),
            CscapeVariable(name="AnalogIn", data_type="INT", tag="%AI1", description="Analog input register"),
            CscapeVariable(name="AnalogOut", data_type="INT", tag="%AQ1", description="Analog output register"),
            CscapeVariable(name="DigitalIn", data_type="BOOL", tag="%I1", description="Hardware digital input"),
            CscapeVariable(name="DigitalOut", data_type="BOOL", tag="%Q1", description="Hardware digital output"),
        ]

        for var in test_vars:
            registered = vm.add_variable(var)
            assert registered.tag == var.tag
            assert registered.register is not None

        assert vm.total_count == 7

        # Verify Horner hardware memory attributes
        r_var = vm.get_variable("HoldingReg")
        assert r_var.register.prefix == "%R"
        assert r_var.register.is_word is True
        assert r_var.register.is_retentive is True
        assert r_var.register.is_read_only is False

        m_var = vm.get_variable("InternalBit")
        assert m_var.register.prefix == "%M"
        assert m_var.register.is_bit is True
        assert m_var.register.is_retentive is True

        t_var = vm.get_variable("TempBit")
        assert t_var.register.prefix == "%T"
        assert t_var.register.is_bit is True
        assert t_var.register.is_retentive is False

        ai_var = vm.get_variable("AnalogIn")
        assert ai_var.register.prefix == "%AI"
        assert ai_var.register.is_analog is True
        assert ai_var.register.is_read_only is True

        aq_var = vm.get_variable("AnalogOut")
        assert aq_var.register.prefix == "%AQ"
        assert aq_var.register.is_analog is True
        assert aq_var.register.is_read_only is False

        i_var = vm.get_variable("DigitalIn")
        assert i_var.register.prefix == "%I"
        assert i_var.register.is_bit is True
        assert i_var.register.is_read_only is True

        q_var = vm.get_variable("DigitalOut")
        assert q_var.register.prefix == "%Q"
        assert q_var.register.is_bit is True
        assert q_var.register.is_read_only is False

    def test_cscape_variable_manager_bit_of_word_addressing(self):
        """Verify CscapeVariableManager supports bit-of-word addressing:

        %R100.1, %R100.16, %SR43.1, and handles overlap detection.
        """
        vm = CscapeVariableManager("BitOfWord_Audit")

        v_bit1 = CscapeVariable(name="StatusBit1", data_type="BOOL", tag="%R100.1", description="Bit 1 of R100")
        v_bit16 = CscapeVariable(name="StatusBit16", data_type="BOOL", tag="%R100.16", description="Bit 16 of R100")
        v_sr_bit = CscapeVariable(name="SysClockBit", data_type="BOOL", tag="%SR43.1", description="Bit 1 of SR43")

        vm.add_variable(v_bit1)
        vm.add_variable(v_bit16)
        vm.add_variable(v_sr_bit)

        assert vm.get_variable("StatusBit1").register.bit_offset == 1
        assert vm.get_variable("StatusBit1").register.is_bit is True
        assert vm.get_variable("StatusBit16").register.bit_offset == 16
        assert vm.get_variable("StatusBit16").register.is_bit is True
        assert vm.get_variable("SysClockBit").register.prefix == "%SR"
        assert vm.get_variable("SysClockBit").register.bit_offset == 1

        # No collision between different bits of the same word
        assert len(vm.detect_conflicts()) == 0

        # Adding whole word %R100 should collide with %R100.1 and %R100.16
        v_word = CscapeVariable(name="ControlWord", data_type="INT", tag="%R100")
        vm.add_variable(v_word)
        conflicts = vm.detect_conflicts()
        assert len(conflicts) >= 2
        conflict_vars = {c["variable1"] for c in conflicts} | {c["variable2"] for c in conflicts}
        assert "ControlWord" in conflict_vars
        assert "StatusBit1" in conflict_vars

    def test_cscape_variable_manager_csv_import_export(self, tmp_path):
        """Verify CscapeVariableManager CSV import and export with full fidelity."""
        vm = CscapeVariableManager("CSV_Audit")

        variables = [
            CscapeVariable(name="Holding1", data_type="INT", tag="%R1", description="Holding register 1"),
            CscapeVariable(name="MotorRun", data_type="BOOL", tag="%M10", initial_value="FALSE"),
            CscapeVariable(name="TimerPulse", data_type="BOOL", tag="%T5"),
            CscapeVariable(name="PressureIn", data_type="INT", tag="%AI2", description="Sensor pressure"),
            CscapeVariable(name="SpeedRef", data_type="INT", tag="%AQ1"),
            CscapeVariable(name="SensorLimit", data_type="BOOL", tag="%I16"),
            CscapeVariable(name="ValveRelay", data_type="BOOL", tag="%Q8"),
            CscapeVariable(name="MotorFaultBit", data_type="BOOL", tag="%R100.1", description="Bit-of-word"),
        ]
        for v in variables:
            vm.add_variable(v)

        csv_file = tmp_path / "cscape_variables.csv"

        # Test export via export_csv and to_csv alias
        csv_text = vm.export_csv(destination=csv_file, delimiter=";")
        assert csv_file.exists()
        assert "%R1" in csv_text
        assert "%R100.1" in csv_text
        assert "%AI2" in csv_text

        csv_text_alias = vm.to_csv(delimiter=";")
        assert csv_text == csv_text_alias

        # Test import via import_csv and from_csv alias
        vm_imported = CscapeVariableManager("CSV_Imported")
        imported_count = vm_imported.import_csv(csv_file, delimiter=";")
        assert imported_count == len(variables)
        assert vm_imported.total_count == len(variables)

        # Verify all variables and tags preserved
        v_fault = vm_imported.get_variable("MotorFaultBit")
        assert v_fault is not None
        assert v_fault.tag == "%R100.1"
        assert v_fault.register.bit_offset == 1

        v_pres = vm_imported.get_variable("PressureIn")
        assert v_pres is not None
        assert v_pres.tag == "%AI2"

        # Verify from_csv alias works
        vm_alias = CscapeVariableManager("CSV_Alias")
        alias_count = vm_alias.from_csv(csv_file, delimiter=";")
        assert alias_count == len(variables)

    def test_cscape_variable_manager_xml_import_export(self, tmp_path):
        """Verify CscapeVariableManager XML import and export with full fidelity."""
        vm = CscapeVariableManager("XML_Audit")

        variables = [
            CscapeVariable(name="RegAlpha", data_type="INT", tag="%R50"),
            CscapeVariable(name="FlagRetain", data_type="BOOL", tag="%M2", scope="retain"),
            CscapeVariable(name="FlowSensor", data_type="REAL", tag="%AI5"),
            CscapeVariable(name="MotorInterlock", data_type="BOOL", tag="%R200.5", description="Interlock bit"),
        ]
        for v in variables:
            vm.add_variable(v)

        xml_file = tmp_path / "cscape_variables.xml"

        # Test export via export_xml and to_xml alias
        xml_text = vm.export_xml(destination=xml_file)
        assert xml_file.exists()
        assert "<ProjectVariables" in xml_text
        assert "%R50" in xml_text
        assert "%R200.5" in xml_text

        xml_text_alias = vm.to_xml()
        assert xml_text == xml_text_alias

        # Test import via import_xml and from_xml alias
        vm_imported = CscapeVariableManager("XML_Imported")
        imported_count = vm_imported.import_xml(xml_file)
        assert imported_count == len(variables)
        assert vm_imported.total_count == len(variables)

        v_interlock = vm_imported.get_variable("MotorInterlock")
        assert v_interlock is not None
        assert v_interlock.tag == "%R200.5"
        assert v_interlock.register.bit_offset == 5

        # Verify from_xml alias works
        vm_alias = CscapeVariableManager("XML_Alias")
        alias_count = vm_alias.from_xml(xml_file)
        assert alias_count == len(variables)


# ===========================================================================
# 10. Dedicated Horner OCS Range Validation Tests (%R, %M, %T, %AI, %AQ, %I, %Q)
# ===========================================================================

class TestHornerOCSRangeValidation:
    """Dedicated tests verifying exact range boundaries for Horner OCS registers:
    %R (1..9999), %M (1..2048), %T (1..2048), %AI (1..512), %AQ (1..512), %I (1..2048), %Q (1..2048).
    """

    @pytest.mark.parametrize(
        "reg_str,expected_prefix,expected_index",
        [
            ("%R1", "%R", 1),
            ("%R9999", "%R", 9999),
            ("%M1", "%M", 1),
            ("%M2048", "%M", 2048),
            ("%T1", "%T", 1),
            ("%T2048", "%T", 2048),
            ("%AI1", "%AI", 1),
            ("%AI512", "%AI", 512),
            ("%AQ1", "%AQ", 1),
            ("%AQ512", "%AQ", 512),
            ("%I1", "%I", 1),
            ("%I2048", "%I", 2048),
            ("%Q1", "%Q", 1),
            ("%Q2048", "%Q", 2048),
        ],
    )
    def test_in_range_register_boundaries(self, reg_str, expected_prefix, expected_index):
        """Verify boundary extremes: minimum (1) and maximum indices are valid."""
        reg = HornerRegister.parse(reg_str)
        assert reg.prefix == expected_prefix
        assert reg.index == expected_index
        assert HornerRegister.is_valid(reg_str) is True

    @pytest.mark.parametrize(
        "invalid_reg,expected_reason",
        [
            ("%R0", "out of bounds"),
            ("%R10000", "out of bounds"),
            ("%M0", "out of bounds"),
            ("%M2049", "out of bounds"),
            ("%T0", "out of bounds"),
            ("%T2049", "out of bounds"),
            ("%AI0", "out of bounds"),
            ("%AI513", "out of bounds"),
            ("%AQ0", "out of bounds"),
            ("%AQ513", "out of bounds"),
            ("%I0", "out of bounds"),
            ("%I2049", "out of bounds"),
            ("%Q0", "out of bounds"),
            ("%Q2049", "out of bounds"),
        ],
    )
    def test_out_of_range_register_indices_rejected(self, invalid_reg, expected_reason):
        """Verify indices below 1 or above the upper limit are strictly rejected."""
        assert HornerRegister.is_valid(invalid_reg) is False
        with pytest.raises(ValueError) as exc_info:
            HornerRegister.parse(invalid_reg)
        assert expected_reason in str(exc_info.value)

    def test_multi_word_variable_range_boundary_overflow(self):
        """Verify variable validation catches multi-word spans that exceed upper range."""
        # Valid: %R9998 with DINT spans %R9998..%R9999 (within 1..9999)
        v_valid_dint = CscapeVariable(name="MaxValidDint", data_type="DINT", tag="%R9998")
        assert v_valid_dint.validate() == []
        assert v_valid_dint.occupied_registers() == ["%R9998", "%R9999"]

        # Invalid: %R9999 with DINT spans %R9999 and %R10000 (exceeds 9999)
        v_invalid_dint = CscapeVariable(name="OverflowDint", data_type="DINT", tag="%R9999")
        errs = v_invalid_dint.validate()
        assert len(errs) > 0
        assert any("exceeding max limit" in e for e in errs)

        # Valid: %R9996 with LREAL spans %R9996..%R9999
        v_valid_lreal = CscapeVariable(name="MaxValidLReal", data_type="LREAL", tag="%R9996")
        assert v_valid_lreal.validate() == []
        assert v_valid_lreal.occupied_registers() == ["%R9996", "%R9997", "%R9998", "%R9999"]

        # Invalid: %R9997 with LREAL spans %R9997..%R10000 (exceeds 9999)
        v_invalid_lreal = CscapeVariable(name="OverflowLReal", data_type="LREAL", tag="%R9997")
        errs = v_invalid_lreal.validate()
        assert len(errs) > 0
        assert any("exceeding max limit" in e for e in errs)

        # Valid: %R9998 with REAL spans %R9998..%R9999
        v_valid_real = CscapeVariable(name="MaxValidReal", data_type="REAL", tag="%R9998")
        assert v_valid_real.validate() == []

        # Invalid: %R9999 with REAL spans %R9999..%R10000
        v_invalid_real = CscapeVariable(name="OverflowReal", data_type="REAL", tag="%R9999")
        assert any("exceeding max limit" in e for e in v_invalid_real.validate())


# ===========================================================================
# 11. Bit-of-Word Indexing Tests (%R1.0 .. %R1.15)
# ===========================================================================

class TestBitOfWordIndexingVerification:
    """Dedicated tests verifying bit-of-word indexing (%R1.0 .. %R1.15) behavior:
    parsing, discrete bit register restrictions, and collision semantics.
    """

    @pytest.mark.parametrize("bit_idx", range(16))
    def test_all_16_bit_offsets_parsed_successfully(self, bit_idx):
        """Verify each bit offset 0 through 15 (%R1.0 to %R1.15) is parsed correctly."""
        addr = f"%R1.{bit_idx}"
        reg = HornerRegister.parse(addr)
        assert reg.prefix == "%R"
        assert reg.index == 1
        assert reg.bit_offset == bit_idx
        assert reg.is_bit is True
        assert reg.is_word is False
        assert reg.get_occupied_registers("BOOL") == [addr]

    @pytest.mark.parametrize("bit_reg", ["%M1.0", "%T1.5", "%I1.0", "%Q1.15", "%S1.0"])
    def test_bit_offsets_rejected_on_discrete_bit_registers(self, bit_reg):
        """Verify bit offsets are strictly prohibited on single-bit discrete registers."""
        assert HornerRegister.is_valid(bit_reg) is False
        with pytest.raises(ValueError) as exc:
            HornerRegister.parse(bit_reg)
        assert "Bit offset not allowed on discrete bit register" in str(exc.value)

    @pytest.mark.parametrize("invalid_bit", ["%R1.17", "%R1.99", "%R1.-1"])
    def test_out_of_range_bit_offsets_rejected(self, invalid_bit):
        """Verify bit offsets outside 0..16 are rejected."""
        assert HornerRegister.is_valid(invalid_bit) is False
        with pytest.raises(ValueError):
            HornerRegister.parse(invalid_bit)

    def test_bit_of_word_collision_with_containing_word(self):
        """Verify word variable collides with any bit-of-word on that register."""
        vm = VariableManager()
        vm.add_variable(CscapeVariable(name="WordVar", data_type="INT", tag="%R1"))
        vm.add_variable(CscapeVariable(name="Bit0", data_type="BOOL", tag="%R1.0"))
        vm.add_variable(CscapeVariable(name="Bit15", data_type="BOOL", tag="%R1.15"))

        conflicts = vm.detect_conflicts()
        # WordVar collides with Bit0 and Bit15
        assert len(conflicts) == 2
        conflict_pairs = {
            (c["variable1"], c["variable2"]) for c in conflicts
        } | {
            (c["variable2"], c["variable1"]) for c in conflicts
        }
        assert ("WordVar", "Bit0") in conflict_pairs
        assert ("WordVar", "Bit15") in conflict_pairs

    def test_distinct_bits_of_same_word_do_not_collide(self):
        """Verify distinct bit-of-word indices on the same register do not collide."""
        vm = VariableManager()
        for b in range(16):
            vm.add_variable(CscapeVariable(name=f"BitFlag_{b}", data_type="BOOL", tag=f"%R1.{b}"))

        conflicts = vm.detect_conflicts()
        assert len(conflicts) == 0

    def test_duplicate_bit_of_word_collides(self):
        """Verify identical bit-of-word indices on the same register collide."""
        vm = VariableManager()
        vm.add_variable(CscapeVariable(name="FirstFlag", data_type="BOOL", tag="%R1.5"))
        vm.add_variable(CscapeVariable(name="SecondFlag", data_type="BOOL", tag="%R1.5"))

        conflicts = vm.detect_conflicts()
        assert len(conflicts) == 1
        assert "%R1.5" in conflicts[0]["reason"]


# ===========================================================================
# 12. Multi-Word Data Type Collision Detection Tests (DINT, REAL, LREAL)
# ===========================================================================

class TestMultiWordCollisionDetectionVerification:
    """Dedicated tests verifying multi-word data type collision detection:
    - DINT (2 consecutive 16-bit %R registers)
    - REAL (2 consecutive 16-bit %R registers)
    - LREAL (4 consecutive 16-bit %R registers)
    """

    def test_dint_two_consecutive_registers_footprint_and_collision(self):
        """DINT at %R100 occupies %R100 and %R101.
        Must collide with variables on %R100 and %R101, but not %R99 or %R102.
        """
        r_dint = HornerRegister.parse("%R100")
        assert r_dint.get_word_span("DINT") == 2
        assert r_dint.get_occupied_registers("DINT") == ["%R100", "%R101"]

        vm = VariableManager()
        vm.add_variable(CscapeVariable(name="DintVal", data_type="DINT", tag="%R100"))

        # Preceding adjacent INT: %R99 -> NO collision
        vm.add_variable(CscapeVariable(name="PrecedingInt", data_type="INT", tag="%R99"))
        assert len(vm.detect_conflicts()) == 0

        # Following adjacent INT: %R102 -> NO collision
        vm.add_variable(CscapeVariable(name="FollowingInt", data_type="INT", tag="%R102"))
        assert len(vm.detect_conflicts()) == 0

        # Overlap on first word: %R100 -> COLLISION
        vm.add_variable(CscapeVariable(name="OverlapFirst", data_type="INT", tag="%R100"))
        conflicts = vm.detect_conflicts()
        assert len(conflicts) == 1
        assert "DintVal" in conflicts[0]["reason"]
        assert "OverlapFirst" in conflicts[0]["reason"]
        assert "%R100" in conflicts[0]["reason"]
        vm.remove_variable("OverlapFirst")

        # Overlap on second word: %R101 -> COLLISION
        vm.add_variable(CscapeVariable(name="OverlapSecond", data_type="INT", tag="%R101"))
        conflicts = vm.detect_conflicts()
        assert len(conflicts) == 1
        assert "DintVal" in conflicts[0]["reason"]
        assert "OverlapSecond" in conflicts[0]["reason"]
        assert "%R101" in conflicts[0]["reason"]
        vm.remove_variable("OverlapSecond")

        # Remove adjacent INTs before testing overlapping multi-word types
        vm.remove_variable("PrecedingInt")
        vm.remove_variable("FollowingInt")

        # Overlapping DINT at %R99 (occupies %R99, %R100) -> COLLISION at %R100
        vm.add_variable(CscapeVariable(name="PrecedingDint", data_type="DINT", tag="%R99"))
        conflicts = vm.detect_conflicts()
        assert len(conflicts) == 1
        assert "%R100" in conflicts[0]["reason"]
        vm.remove_variable("PrecedingDint")

        # Overlapping DINT at %R101 (occupies %R101, %R102) -> COLLISION at %R101
        vm.add_variable(CscapeVariable(name="FollowingDint", data_type="DINT", tag="%R101"))
        conflicts = vm.detect_conflicts()
        assert len(conflicts) == 1
        assert "%R101" in conflicts[0]["reason"]

    def test_real_two_consecutive_registers_footprint_and_collision(self):
        """REAL at %R200 occupies %R200 and %R201.
        Must collide with variables on %R200 and %R201, and cross-collide with DINT.
        """
        r_real = HornerRegister.parse("%R200")
        assert r_real.get_word_span("REAL") == 2
        assert r_real.get_occupied_registers("REAL") == ["%R200", "%R201"]

        vm = VariableManager()
        vm.add_variable(CscapeVariable(name="TankPressure", data_type="REAL", tag="%R200"))
        # Overlapping DINT at %R199 (occupies %R199, %R200)
        vm.add_variable(CscapeVariable(name="FlowCounter", data_type="DINT", tag="%R199"))

        conflicts = vm.detect_conflicts()
        assert len(conflicts) == 1
        c = conflicts[0]
        assert c["overlapping_registers"] == ["%R200"]
        assert "%R200" in c["reason"]

    def test_lreal_four_consecutive_registers_footprint_and_collision(self):
        """LREAL at %R300 occupies 4 words: %R300, %R301, %R302, %R303.
        Must collide with variables on all 4 words, and cross-collide with DINT and REAL.
        """
        r_lreal = HornerRegister.parse("%R300")
        assert r_lreal.get_word_span("LREAL") == 4
        assert r_lreal.get_occupied_registers("LREAL") == ["%R300", "%R301", "%R302", "%R303"]

        vm = VariableManager()
        vm.add_variable(CscapeVariable(name="HighPrecisionValue", data_type="LREAL", tag="%R300"))

        # Test collisions on every one of the 4 words individually
        for offset in range(4):
            idx = 300 + offset
            test_name = f"CollisionInt_{idx}"
            vm.add_variable(CscapeVariable(name=test_name, data_type="INT", tag=f"%R{idx}"))
            conflicts = vm.detect_conflicts()
            assert len(conflicts) == 1
            assert conflicts[0]["overlapping_registers"] == [f"%R{idx}"]
            vm.remove_variable(test_name)

        # Test boundaries: %R299 (INT) and %R304 (INT) do NOT collide
        vm.add_variable(CscapeVariable(name="BeforeInt", data_type="INT", tag="%R299"))
        vm.add_variable(CscapeVariable(name="AfterInt", data_type="INT", tag="%R304"))
        assert len(vm.detect_conflicts()) == 0
        vm.remove_variable("BeforeInt")
        vm.remove_variable("AfterInt")

        # Overlap with DINT at %R299 (occupies %R299, %R300) -> Collides at %R300
        vm.add_variable(CscapeVariable(name="OverlappingDint", data_type="DINT", tag="%R299"))
        conflicts = vm.detect_conflicts()
        assert len(conflicts) == 1
        assert conflicts[0]["overlapping_registers"] == ["%R300"]
        vm.remove_variable("OverlappingDint")

        # Overlap with REAL at %R302 (occupies %R302, %R303) -> Collides at %R302, %R303
        vm.add_variable(CscapeVariable(name="OverlappingReal", data_type="REAL", tag="%R302"))
        conflicts = vm.detect_conflicts()
        assert len(conflicts) == 1
        assert conflicts[0]["overlapping_registers"] == ["%R302", "%R303"]
        vm.remove_variable("OverlappingReal")

        # Overlap with bit-of-word at %R303.8 -> Collides at %R303
        vm.add_variable(CscapeVariable(name="BitInLReal", data_type="BOOL", tag="%R303.8"))
        conflicts = vm.detect_conflicts()
        assert len(conflicts) == 1
        vm.remove_variable("BitInLReal")

    def test_allocation_exhaustion_at_register_limit(self):
        """Verify allocate_register raises ValueError when approaching %R limit of 9999."""
        vm = VariableManager()
        # Pre-assign %R9998 and %R9999
        vm.add_variable(CscapeVariable(name="NearEnd", data_type="DINT", tag="%R9998"))

        # Trying to allocate DINT (needs 2 contiguous words) from %R9998 -> should fail because max is 9999
        with pytest.raises(ValueError) as exc:
            vm.allocate_register(data_type="DINT", prefix="%R", start_index=9998)
        assert "memory space exhausted" in str(exc.value)
