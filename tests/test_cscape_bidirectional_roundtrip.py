"""Comprehensive Bidirectional CSV and XML Roundtrip Verification Suite for Horner Cscape Variable Database.

Verifies:
- 100% identical register assignments across all Horner OCS registers
- 100% identical type mappings across all IEC 61131-3 data types
- Bit-of-word indexing accuracy
- Semicolon-delimited (native Cscape) and comma-delimited CSV roundtrip
- XML (<ProjectVariables>) roundtrip
- High-level VariableManager / TagDatabase file export/import
- Double roundtrip idempotency (export -> import -> export -> import)
- Detailed verification metrics calculation
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import pytest

from src.cscape.variables import (
    CscapeCSVParser,
    CscapeCSVSerializer,
    CscapeVariable,
    CscapeVariableManager,
    CscapeXMLParser,
    CscapeXMLSerializer,
    HornerRegister,
    RegisterType,
    VariableManager,
)


def create_exhaustive_test_dataset() -> List[CscapeVariable]:
    """Builds an exhaustive variable dataset spanning all register families and IEC types."""
    dataset: List[CscapeVariable] = []

    # 1. Discrete / Bit registers
    discrete_regs = [
        ("%M1", "M_InternalBit_1", "BOOL", "globals", "Internal scratch bit 1", "FALSE"),
        ("%M2048", "M_MaxInternalBit", "BOOL", "retain", "Maximum OCS internal bit", "TRUE"),
        ("%T1", "T_TimerBit_1", "BOOL", "globals", "Temporary coil bit", "FALSE"),
        ("%T2048", "T_MaxTimerBit", "BOOL", "globals", "Temporary max coil bit", "FALSE"),
        ("%I1", "I_EStopPB", "BOOL", "globals", "Emergency Stop PB (NC)", "TRUE"),
        ("%I64", "I_ProxSwitch", "BOOL", "globals", "Inductive proximity sensor", "FALSE"),
        ("%Q1", "Q_MainContactor", "BOOL", "globals", "Main 480V supply contactor", "FALSE"),
        ("%Q32", "Q_AlarmHorn", "BOOL", "globals", "Klaxon horn output", "FALSE"),
        ("%D1", "D_ScreenJump_1", "BOOL", "globals", "Screen navigation trigger bit", "FALSE"),
        ("%D256", "D_MaxScreenBit", "BOOL", "globals", "Max screen trigger bit", "FALSE"),
        ("%K1", "K_F1_Key", "BOOL", "globals", "Function key F1 on OCS fascia", "FALSE"),
        ("%K16", "K_F16_Key", "BOOL", "globals", "Function key F16 on OCS fascia", "FALSE"),
        ("%S1", "S_FstScan", "BOOL", "globals", "First scan cycle flag", "TRUE"),
        ("%S7", "S_SecClock", "BOOL", "globals", "1 second clock flash bit", "FALSE"),
        ("%IG1", "IG_CsCanNode1_In", "BOOL", "globals", "Global network bit node 1", "FALSE"),
        ("%QG1", "QG_CsCanNode1_Out", "BOOL", "globals", "Global network output node 1", "FALSE"),
    ]
    for tag, name, dtype, scope, desc, init in discrete_regs:
        dataset.append(CscapeVariable(
            name=name, data_type=dtype, scope=scope, tag=tag,
            description=desc, initial_value=init,
        ))

    # 2. Word / Integer registers (%R, %AI, %AQ, %SR, %AIG, %AQG)
    word_regs = [
        ("%R1", "R_ScratchWord", "INT", "globals", "General retentive register 1", "0"),
        ("%R100", "R_BatchStep", "UINT", "retain", "Current recipe sequence step", "1"),
        ("%R500", "R_CounterPre", "WORD", "globals", "High-speed counter preset", "10000"),
        ("%R9999", "R_MaxReg", "INT", "retain", "Upper boundary register", "32767"),
        ("%AI1", "AI_TempSensor", "INT", "globals", "4-20mA temperature transmitter", "0"),
        ("%AI512", "AI_MaxChannel", "INT", "globals", "Maximum analog input channel", "0"),
        ("%AQ1", "AQ_ValveDrive", "INT", "globals", "0-10V analog throttle valve command", "0"),
        ("%AQ512", "AQ_MaxChannel", "INT", "globals", "Maximum analog output channel", "0"),
        ("%SR1", "SR_CurrentSeconds", "UINT", "globals", "RTC clock seconds", "0"),
        ("%SR29", "SR_NetStatus", "WORD", "globals", "CsCAN network diagnostic status", "0"),
        ("%SR256", "SR_MaxSysReg", "WORD", "globals", "Maximum system status register", "0"),
        ("%AIG1", "AIG_RemoteTemp", "INT", "globals", "CsCAN remote analog input register", "0"),
        ("%AQG1", "AQG_RemoteValve", "INT", "globals", "CsCAN remote analog output register", "0"),
    ]
    for tag, name, dtype, scope, desc, init in word_regs:
        dataset.append(CscapeVariable(
            name=name, data_type=dtype, scope=scope, tag=tag,
            description=desc, initial_value=init,
        ))

    # 3. Multi-word registers (DINT, UDINT, DWORD, REAL, LREAL, TIME, DATE, TOD, DT)
    multiword_regs = [
        ("%R1000", "R_TotalizerCounts", "DINT", "retain", "32-bit production totalizer", "1000000"),
        ("%R1002", "R_HighResTimer", "UDINT", "globals", "32-bit millisecond timer tick", "0"),
        ("%R1004", "R_StatusBitMask", "DWORD", "globals", "32-bit hardware status mask", "16#FFFF0000"),
        ("%R1006", "R_PressurePSI", "REAL", "globals", "32-bit IEEE float manifold pressure", "14.696"),
        ("%R1008", "R_FlowRateLPM", "REAL", "globals", "32-bit IEEE float hydraulic flow", "125.75"),
        ("%R1010", "R_CycleTimeout", "TIME", "globals", "32-bit IEC time interval", "T#45s"),
        ("%R1012", "R_ManufactureDate", "DATE", "retain", "32-bit IEC calendar date", "D#2026-09-03"),
        ("%R1014", "R_ShiftEndTime", "TOD", "globals", "32-bit time of day", "TOD#16:30:00"),
        ("%R1016", "R_LastAuditTimestamp", "DT", "retain", "32-bit date and time", "DT#2026-09-03-23:00:00"),
        ("%R1018", "R_MicroStrain64", "LREAL", "globals", "64-bit precision strain measurement", "0.000012345"),
        ("%R1022", "R_LargeSigned64", "LINT", "retain", "64-bit signed production counter", "9876543210"),
        ("%R1026", "R_LargeUnsigned64", "ULINT", "retain", "64-bit unsigned cycle accumulator", "123456789012"),
        ("%R1030", "R_BroadBitMask64", "LWORD", "globals", "64-bit diagnostic register", "16#FEDCBA9876543210"),
    ]
    for tag, name, dtype, scope, desc, init in multiword_regs:
        dataset.append(CscapeVariable(
            name=name, data_type=dtype, scope=scope, tag=tag,
            description=desc, initial_value=init,
        ))

    # 4. Bit-of-word indexed registers (%R.bit, %SR.bit)
    bit_of_word_regs = [
        ("%R200.1", "R_Motor1_Running", "BOOL", "globals", "Motor 1 running state (bit 1 of %R200)", "FALSE"),
        ("%R200.2", "R_Motor1_Overload", "BOOL", "globals", "Motor 1 thermal overload trip (bit 2)", "FALSE"),
        ("%R200.8", "R_Motor1_RemoteReady", "BOOL", "globals", "Motor 1 remote control enable (bit 8)", "TRUE"),
        ("%R200.16", "R_Motor1_EstopActive", "BOOL", "globals", "Motor 1 e-stop status (bit 16)", "FALSE"),
        ("%SR43.1", "SR_BatteryLow", "BOOL", "globals", "OCS lithium battery low flag (%SR43.1)", "FALSE"),
        ("%SR43.16", "SR_SysFaultPresent", "BOOL", "globals", "OCS system fault present (%SR43.16)", "FALSE"),
    ]
    for tag, name, dtype, scope, desc, init in bit_of_word_regs:
        dataset.append(CscapeVariable(
            name=name, data_type=dtype, scope=scope, tag=tag,
            description=desc, initial_value=init,
        ))

    # 5. STRING variables with varied lengths
    strings = [
        ("%R3000", "Str_ShortTag", "STRING", 10, "retain", "Short identification code", "'TAG_01'"),
        ("%R3010", "Str_RecipeName", "STRING", 40, "retain", "Active batch recipe label", "'Beer_Lager_V2'"),
        ("%R3035", "Str_OperatorLogin", "STRING", 20, "globals", "Logged in operator username", "'jsmith'"),
        ("%R3050", "Str_MaxBuffer", "STRING", 255, "retain", "Maximum length ASCII serial buffer", "''"),
    ]
    for tag, name, dtype, slen, scope, desc, init in strings:
        dataset.append(CscapeVariable(
            name=name, data_type=dtype, string_length=slen, scope=scope, tag=tag,
            description=desc, initial_value=init,
        ))

    # 6. ARRAY variables (1D and 2D)
    arrays = [
        ("%R4000", "Arr_SensorCalib", "REAL", "globals", "10", "10-point linear calibration offsets", ""),
        ("%R4020", "Arr_ZoneTemps", "INT", "globals", "1..8", "8 heating zone thermocouple inputs", ""),
        ("%R4030", "Arr_BatchMatrix", "UINT", "retain", "0..4, 0..9", "5x10 batch parameter lookup table", ""),
    ]
    for tag, name, dtype, scope, dims, desc, init in arrays:
        dataset.append(CscapeVariable(
            name=name, data_type=dtype, scope=scope, dimensions=dims, tag=tag,
            description=desc, initial_value=init if init else None,
        ))

    # 7. IEC 61131-3 Register Prefixes (%IX, %QX, %MX, %IW, %QW, %MW, %ID, %QD, %MD)
    iec_regs = [
        ("%IX1", "IEC_DiscreteIn", "BOOL", "globals", "IEC input bit 1", "FALSE"),
        ("%QX1", "IEC_DiscreteOut", "BOOL", "globals", "IEC output bit 1", "FALSE"),
        ("%MX1", "IEC_MemoryBit", "BOOL", "globals", "IEC memory bit 1", "FALSE"),
        ("%IW1", "IEC_InputWord", "INT", "globals", "IEC input word 1", "0"),
        ("%QW1", "IEC_OutputWord", "INT", "globals", "IEC output word 1", "0"),
        ("%MW1", "IEC_MemoryWord", "INT", "globals", "IEC memory word 1", "0"),
        ("%ID1", "IEC_InputDWord", "DINT", "globals", "IEC input double word 1", "0"),
        ("%QD1", "IEC_OutputDWord", "DINT", "globals", "IEC output double word 1", "0"),
        ("%MD1", "IEC_MemoryDWord", "DINT", "globals", "IEC memory double word 1", "0"),
    ]
    for tag, name, dtype, scope, desc, init in iec_regs:
        dataset.append(CscapeVariable(
            name=name, data_type=dtype, scope=scope, tag=tag,
            description=desc, initial_value=init,
        ))

    # 8. Read-only / Constant variables
    constants = [
        ("%R5000", "Const_MaxPressureLimit", "REAL", "globals", "Maximum allowed system pressure", "250.0", True),
        ("%R5002", "Const_VendorID", "UINT", "globals", "Horner APG OEM Vendor Identifier", "4590", True),
    ]
    for tag, name, dtype, scope, desc, init, ro in constants:
        dataset.append(CscapeVariable(
            name=name, data_type=dtype, scope=scope, tag=tag,
            description=desc, initial_value=init, read_only=ro,
            attributes=["constant"],
        ))

    # 9. Special character testing (XML & CSV escaping)
    special_chars = [
        ("%R6000", "Var_XmlEscapeCheck", "INT", "globals", 'Testing <tags> & "quotes" and \'apostrophes\' in desc', "10"),
        ("%R6001", "Var_CsvDelimCheck", "INT", "globals", 'Testing ; semicolons, commas, and "quotes" in CSV', "20"),
    ]
    for tag, name, dtype, scope, desc, init in special_chars:
        dataset.append(CscapeVariable(
            name=name, data_type=dtype, scope=scope, tag=tag,
            description=desc, initial_value=init,
        ))

    # 10. Untagged variable (no register assigned)
    dataset.append(CscapeVariable(
        name="Var_UntaggedInternal",
        data_type="BOOL",
        scope="globals",
        tag=None,
        description="Internal software variable without assigned register",
        initial_value="FALSE",
    ))

    return dataset


def verify_dataset_pair(
    expected_list: List[CscapeVariable],
    actual_list: List[CscapeVariable],
    context: str = "Roundtrip",
) -> Dict[str, Any]:
    """Exhaustively compares two datasets and computes precision metrics."""
    assert len(expected_list) == len(actual_list), (
        f"{context}: Variable count mismatch: expected {len(expected_list)}, got {len(actual_list)}"
    )

    actual_map: Dict[Tuple[str, str], CscapeVariable] = {
        (v.scope.lower(), v.name.upper()): v for v in actual_list
    }

    metrics = {
        "total_variables": len(expected_list),
        "name_matches": 0,
        "type_matches": 0,
        "register_matches": 0,
        "bit_offset_matches": 0,
        "string_length_matches": 0,
        "dimensions_matches": 0,
        "scope_matches": 0,
        "read_only_matches": 0,
        "initial_value_matches": 0,
        "description_matches": 0,
        "mismatches": [],
    }

    for exp in expected_list:
        key = (exp.scope.lower(), exp.name.upper())
        act = actual_map.get(key)
        if not act:
            metrics["mismatches"].append(f"Missing variable: {exp.name} in scope {exp.scope}")
            continue

        # 1. Name
        if exp.name == act.name:
            metrics["name_matches"] += 1
        else:
            metrics["mismatches"].append(f"Name mismatch: {exp.name} vs {act.name}")

        # 2. Data Type
        if exp.data_type.upper() == act.data_type.upper():
            metrics["type_matches"] += 1
        else:
            metrics["mismatches"].append(f"{exp.name}: Data type mismatch {exp.data_type} vs {act.data_type}")

        # 3. Register Assignment
        if exp.tag == act.tag:
            metrics["register_matches"] += 1
        else:
            metrics["mismatches"].append(f"{exp.name}: Register tag mismatch {exp.tag} vs {act.tag}")

        # 4. Bit offset
        exp_bit = exp.register.bit_offset if exp.register else None
        act_bit = act.register.bit_offset if act.register else None
        if exp_bit == act_bit:
            metrics["bit_offset_matches"] += 1
        else:
            metrics["mismatches"].append(f"{exp.name}: Bit offset mismatch {exp_bit} vs {act_bit}")

        # 5. String length
        if exp.string_length == act.string_length:
            metrics["string_length_matches"] += 1
        else:
            metrics["mismatches"].append(f"{exp.name}: String length mismatch {exp.string_length} vs {act.string_length}")

        # 6. Dimensions
        if (exp.dimensions or None) == (act.dimensions or None):
            metrics["dimensions_matches"] += 1
        else:
            metrics["mismatches"].append(f"{exp.name}: Dimensions mismatch {exp.dimensions} vs {act.dimensions}")

        # 7. Scope
        if exp.scope.lower() == act.scope.lower():
            metrics["scope_matches"] += 1
        else:
            metrics["mismatches"].append(f"{exp.name}: Scope mismatch {exp.scope} vs {act.scope}")

        # 8. Read only
        if exp.read_only == act.read_only:
            metrics["read_only_matches"] += 1
        else:
            metrics["mismatches"].append(f"{exp.name}: Read-only mismatch {exp.read_only} vs {act.read_only}")

        # 9. Initial value
        if (exp.initial_value or None) == (act.initial_value or None):
            metrics["initial_value_matches"] += 1
        else:
            metrics["mismatches"].append(f"{exp.name}: Initial value mismatch {exp.initial_value} vs {act.initial_value}")

        # 10. Description
        if (exp.description or None) == (act.description or None):
            metrics["description_matches"] += 1
        else:
            metrics["mismatches"].append(f"{exp.name}: Description mismatch {exp.description!r} vs {act.description!r}")

    tot = metrics["total_variables"]
    metrics["register_match_rate_pct"] = (metrics["register_matches"] / tot) * 100.0
    metrics["type_match_rate_pct"] = (metrics["type_matches"] / tot) * 100.0
    metrics["bit_offset_match_rate_pct"] = (metrics["bit_offset_matches"] / tot) * 100.0
    metrics["overall_fidelity_pct"] = 100.0 if not metrics["mismatches"] else (
        ((tot * 10 - len(metrics["mismatches"])) / (tot * 10)) * 100.0
    )

    return metrics


class TestCscapeBidirectionalExhaustive:
    """Exhaustive roundtrip verification across all formats and managers."""

    def test_xml_bidirectional_roundtrip(self):
        """Verify XML export -> import roundtrip yields 100% register & type fidelity."""
        dataset = create_exhaustive_test_dataset()

        xml_text = CscapeXMLSerializer.serialize(dataset)
        assert "<ProjectVariables version=\"1.0\">" in xml_text
        assert len(xml_text) > 500

        imported = CscapeXMLParser.parse(xml_text)

        metrics = verify_dataset_pair(dataset, imported, context="XML Direct Roundtrip")
        assert metrics["mismatches"] == [], f"XML Mismatches: {metrics['mismatches']}"
        assert metrics["register_match_rate_pct"] == 100.0
        assert metrics["type_match_rate_pct"] == 100.0
        assert metrics["bit_offset_match_rate_pct"] == 100.0

    def test_csv_semicolon_bidirectional_roundtrip(self):
        """Verify semicolon-delimited CSV export -> import yields 100% register & type fidelity."""
        dataset = create_exhaustive_test_dataset()

        csv_text = CscapeCSVSerializer.serialize(
            dataset, delimiter=";", include_scope_col=True
        )
        assert ";" in csv_text
        assert '"name";"type"' in csv_text

        imported = CscapeCSVParser.parse(csv_text, delimiter=";")

        metrics = verify_dataset_pair(dataset, imported, context="CSV Semicolon Roundtrip")
        assert metrics["mismatches"] == [], f"CSV Semicolon Mismatches: {metrics['mismatches']}"
        assert metrics["register_match_rate_pct"] == 100.0
        assert metrics["type_match_rate_pct"] == 100.0
        assert metrics["bit_offset_match_rate_pct"] == 100.0

    def test_csv_comma_bidirectional_roundtrip(self):
        """Verify comma-delimited CSV export -> import yields 100% register & type fidelity."""
        dataset = create_exhaustive_test_dataset()

        csv_text = CscapeCSVSerializer.serialize(
            dataset, delimiter=",", include_scope_col=True
        )
        assert "," in csv_text
        assert '"name","type"' in csv_text

        imported = CscapeCSVParser.parse(csv_text, delimiter=None)

        metrics = verify_dataset_pair(dataset, imported, context="CSV Comma Roundtrip")
        assert metrics["mismatches"] == [], f"CSV Comma Mismatches: {metrics['mismatches']}"
        assert metrics["register_match_rate_pct"] == 100.0
        assert metrics["type_match_rate_pct"] == 100.0
        assert metrics["bit_offset_match_rate_pct"] == 100.0

    def test_variable_manager_xml_file_roundtrip(self, tmp_path):
        """Verify VariableManager export_xml -> import_xml disk file roundtrip."""
        vm_source = VariableManager("SourcePlant")
        dataset = create_exhaustive_test_dataset()
        for v in dataset:
            vm_source.add_variable(v)

        xml_target_file = tmp_path / "cscape_test_vars.xml"
        vm_source.export_xml(xml_target_file)
        assert xml_target_file.exists()

        vm_dest = VariableManager("DestPlant")
        imported_count = vm_dest.import_xml(xml_target_file, merge=False)
        assert imported_count == len(dataset)
        assert vm_dest.total_count == len(dataset)

        metrics = verify_dataset_pair(
            dataset, vm_dest.list_variables(), context="VariableManager XML File Roundtrip"
        )
        assert metrics["mismatches"] == []
        assert metrics["register_match_rate_pct"] == 100.0
        assert metrics["type_match_rate_pct"] == 100.0

    def test_variable_manager_csv_file_roundtrip(self, tmp_path):
        """Verify VariableManager export_csv -> import_csv disk file roundtrip."""
        vm_source = VariableManager("SourcePlantCSV")
        dataset = create_exhaustive_test_dataset()
        for v in dataset:
            vm_source.add_variable(v)

        csv_target_file = tmp_path / "cscape_test_vars.csv"
        vm_source.export_csv(csv_target_file, delimiter=";")
        assert csv_target_file.exists()

        vm_dest = VariableManager("DestPlantCSV")
        imported_count = vm_dest.import_csv(csv_target_file, delimiter=";", merge=False)
        assert imported_count == len(dataset)
        assert vm_dest.total_count == len(dataset)

        metrics = verify_dataset_pair(
            dataset, vm_dest.list_variables(), context="VariableManager CSV File Roundtrip"
        )
        assert metrics["mismatches"] == []
        assert metrics["register_match_rate_pct"] == 100.0
        assert metrics["type_match_rate_pct"] == 100.0

    def test_double_roundtrip_idempotency_xml(self):
        """Verify idempotency: export -> import -> export -> import produces identical outputs."""
        dataset = create_exhaustive_test_dataset()

        # Pass 1
        xml1 = CscapeXMLSerializer.serialize(dataset)
        vars1 = CscapeXMLParser.parse(xml1)

        # Pass 2
        xml2 = CscapeXMLSerializer.serialize(vars1)
        vars2 = CscapeXMLParser.parse(xml2)

        assert xml1 == xml2

        metrics = verify_dataset_pair(vars1, vars2, context="XML Idempotency Pass")
        assert metrics["mismatches"] == []
        assert metrics["register_match_rate_pct"] == 100.0
        assert metrics["type_match_rate_pct"] == 100.0

    def test_double_roundtrip_idempotency_csv(self):
        """Verify idempotency for CSV: export -> import -> export -> import produces identical outputs."""
        dataset = create_exhaustive_test_dataset()

        # Pass 1
        csv1 = CscapeCSVSerializer.serialize(dataset, delimiter=";", include_scope_col=True)
        vars1 = CscapeCSVParser.parse(csv1, delimiter=";")

        # Pass 2
        csv2 = CscapeCSVSerializer.serialize(vars1, delimiter=";", include_scope_col=True)
        vars2 = CscapeCSVParser.parse(csv2, delimiter=";")

        assert csv1 == csv2

        metrics = verify_dataset_pair(vars1, vars2, context="CSV Idempotency Pass")
        assert metrics["mismatches"] == []
        assert metrics["register_match_rate_pct"] == 100.0
        assert metrics["type_match_rate_pct"] == 100.0

    def test_industrial_automation_plant_full_roundtrip(self, tmp_path):
        """Verify complex industrial automation plant (PID, VFD, recipe, I/O) roundtrip."""
        vm = VariableManager("IndustrialBrewery")

        # Digital field devices (%I, %Q)
        for i in range(1, 17):
            vm.add_variable(CscapeVariable(name=f"DI_Sensor_{i}", data_type="BOOL", tag=f"%I{i}", description=f"Digital Input Channel {i}"))
            vm.add_variable(CscapeVariable(name=f"DO_Actuator_{i}", data_type="BOOL", tag=f"%Q{i}", description=f"Digital Output Channel {i}"))

        # Analog instruments (%AI, %AQ)
        for i in range(1, 9):
            vm.add_variable(CscapeVariable(name=f"AI_Transmitter_{i}", data_type="INT", tag=f"%AI{i}", description=f"Analog Input Channel {i}"))
        for i in range(1, 5):
            vm.add_variable(CscapeVariable(name=f"AQ_ControlValve_{i}", data_type="INT", tag=f"%AQ{i}", description=f"Analog Output Channel {i}"))

        # PID loop parameters (%R)
        pid_tags = [
            ("%R100", "PID_PV", "REAL", "globals", "Process variable (deg C)"),
            ("%R102", "PID_SP", "REAL", "globals", "Setpoint (deg C)"),
            ("%R104", "PID_CV", "REAL", "globals", "Control output (%)"),
            ("%R106", "PID_Kp", "REAL", "retain", "Proportional gain"),
            ("%R108", "PID_Ti", "REAL", "retain", "Integral time constant"),
            ("%R110", "PID_Td", "REAL", "retain", "Derivative time constant"),
        ]
        for tag, name, dtype, scope, desc in pid_tags:
            vm.add_variable(CscapeVariable(name=name, data_type=dtype, scope=scope, tag=tag, description=desc))

        # Motor bit-of-word flags (%R.bit)
        for bit in range(1, 9):
            vm.add_variable(CscapeVariable(name=f"MTR_StatusBit_{bit}", data_type="BOOL", tag=f"%R200.{bit}", description=f"Motor status word bit {bit}"))

        # Recipe strings and arrays (%R retain)
        vm.add_variable(CscapeVariable(name="RCP_BatchName", data_type="STRING", string_length=50, scope="retain", tag="%R1000", description="Recipe product title"))
        vm.add_variable(CscapeVariable(name="RCP_Weights", data_type="REAL", dimensions="1..10", scope="retain", tag="%R1030", description="10-stage ingredient array"))

        # XML file roundtrip
        xml_file = tmp_path / "brewery_vars.xml"
        vm.export_xml(xml_file)
        vm_xml = VariableManager("BreweryFromXml")
        vm_xml.import_xml(xml_file)

        assert vm_xml.total_count == vm.total_count
        metrics_xml = verify_dataset_pair(vm.list_variables(), vm_xml.list_variables(), context="Brewery XML Roundtrip")
        assert metrics_xml["mismatches"] == []
        assert metrics_xml["register_match_rate_pct"] == 100.0
        assert metrics_xml["type_match_rate_pct"] == 100.0

        # CSV file roundtrip
        csv_file = tmp_path / "brewery_vars.csv"
        vm.export_csv(csv_file, delimiter=";")
        vm_csv = VariableManager("BreweryFromCsv")
        vm_csv.import_csv(csv_file, delimiter=";")

        assert vm_csv.total_count == vm.total_count
        metrics_csv = verify_dataset_pair(vm.list_variables(), vm_csv.list_variables(), context="Brewery CSV Roundtrip")
        assert metrics_csv["mismatches"] == []
        assert metrics_csv["register_match_rate_pct"] == 100.0
        assert metrics_csv["type_match_rate_pct"] == 100.0

