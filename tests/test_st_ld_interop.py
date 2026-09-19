"""
Unit tests for Cscape ST vs Ladder Interop Guard.
Verifies detection of ladder artifacts, enforcement of pure IEC 61131-3 Structured Text,
automated conversion recommendations, and project-level validation.
"""

import json
from pathlib import Path
import pytest

from src.cscape.st_ld_interop import (
    STLadderInteropGuard,
    LadderConstructRejectedError,
    NonIECProjectError,
    InteropGuardError,
    LadderPatternMatch,
    ConversionRecipe,
    InteropAnalysisResult,
    ProjectModeReport,
    CONVERSION_RECIPES,
)


# ============================================================================
# Detection Tests
# ============================================================================

class TestLadderConstructDetection:
    """Tests identifying individual ladder symbols and constructs."""

    def test_detect_no_contact(self):
        code = "bOutput := ---[ bInput ]---;"
        matches = STLadderInteropGuard.detect_ladder_constructs(code)
        assert len(matches) > 0
        assert any("NO_CONTACT" in m.pattern_type for m in matches)

    def test_detect_nc_contact(self):
        code = "bOutput := ---[/ bInput ]---;"
        matches = STLadderInteropGuard.detect_ladder_constructs(code)
        assert len(matches) > 0
        assert any("NC_CONTACT" in m.pattern_type for m in matches)

    def test_detect_normal_coil(self):
        code = "---( bMotor )---"
        matches = STLadderInteropGuard.detect_ladder_constructs(code)
        assert len(matches) > 0
        assert any("NORMAL_COIL" in m.pattern_type for m in matches)

    def test_detect_set_latch_coil(self):
        samples = [
            "---(S bAlarm )---",
            "---(L bAlarm )---",
            "[SET bAlarm]",
            "[LATCH bAlarm]",
        ]
        for s in samples:
            matches = STLadderInteropGuard.detect_ladder_constructs(s)
            assert len(matches) > 0
            assert any("SET_COIL" in m.pattern_type for m in matches)

    def test_detect_reset_unlatch_coil(self):
        samples = [
            "---(R bAlarm )---",
            "---(U bAlarm )---",
            "[RESET bAlarm]",
            "[UNLATCH bAlarm]",
        ]
        for s in samples:
            matches = STLadderInteropGuard.detect_ladder_constructs(s)
            assert len(matches) > 0
            assert any("RESET_COIL" in m.pattern_type for m in matches)

    def test_detect_edge_triggers(self):
        samples = [
            "---[P]---",
            "---[N]---",
            "---[↑]---",
            "---[↓]---",
        ]
        for s in samples:
            matches = STLadderInteropGuard.detect_ladder_constructs(s)
            assert len(matches) > 0
            assert any("EDGE_CONTACT" in m.pattern_type for m in matches)

    def test_detect_power_rails(self):
        code = "|---[ Start ]---|---"
        matches = STLadderInteropGuard.detect_ladder_constructs(code)
        assert len(matches) > 0
        assert any("POWER_RAIL" in m.pattern_type or "NO_CONTACT" in m.pattern_type for m in matches)

    def test_detect_empty_contacts_and_coils(self):
        samples = [
            "--[ ]--",
            "--[/]--",
            "---[ ]---",
            "|--[ ]--|",
            "--( )--",
            "-- ( ) --",
            "---( )---",
            "|( )|",
            "|--( )--|",
            "--(S)--",
            "-- (S) --",
            "--(R)--",
            "-- (R) --",
        ]
        for s in samples:
            matches = STLadderInteropGuard.detect_ladder_constructs(s)
            assert len(matches) > 0, f"Failed to detect empty ladder construct in: '{s}'"
            assert any(
                m.pattern_type in (
                    "ASCII_NO_CONTACT",
                    "ASCII_NC_CONTACT",
                    "ASCII_NORMAL_COIL",
                    "ASCII_SET_COIL",
                    "ASCII_RESET_COIL",
                    "POWER_RAIL_ARTIFACT",
                )
                for m in matches
            )

    def test_detect_network_labels(self):
        samples = [
            "NETWORK",
            "NETWORK 1:",
            "NETWORK 1",
            "NETWORK: Main Motor Logic",
            "Network 12 - Conveyor Control",
            "NET 1:",
            "NET: 1",
            "NET 1",
            "NETWORK_LABEL: InitProcess",
            "END_NETWORK",
        ]
        for s in samples:
            matches = STLadderInteropGuard.detect_ladder_constructs(s)
            assert len(matches) > 0, f"Failed to detect network label in: '{s}'"
            assert any(m.pattern_type == "NETWORK_LABEL" for m in matches)
            assert any("NETWORK_LABEL" in m.st_recommendation or "network" in m.explanation.lower() for m in matches)

    def test_detect_rung_markers(self):
        samples = [
            "RUNG",
            "RUNG 1:",
            "RUNG 42",
            "RUNG: 1",
            "RUNG: Motor Start",
            "END_RUNG",
            "LADDER_RUNG",
        ]
        for s in samples:
            matches = STLadderInteropGuard.detect_ladder_constructs(s)
            assert len(matches) > 0
            assert any("RUNG_MARKER" in m.pattern_type for m in matches)

    def test_detect_ladder_mnemonics(self):
        code = "XIC(bStart) XIO(bStop) OTE(bMotor)"
        matches = STLadderInteropGuard.detect_ladder_constructs(code)
        assert len(matches) >= 3
        assert all(m.pattern_type == "MNEMONIC_LADDER_INSTRUCTION" for m in matches)

    def test_detect_ladder_timers_counters(self):
        code = "TON_LADDER(Timer1, 5000); CTU_LADDER(Counter1, 10);"
        matches = STLadderInteropGuard.detect_ladder_constructs(code)
        assert len(matches) >= 2
        types = [m.pattern_type for m in matches]
        assert "LADDER_TIMER_BOX" in types
        assert "LADDER_COUNTER_BOX" in types

    def test_detect_legacy_horner_registers(self):
        code = "%R0001 := 100; %M0010 := TRUE; %AI0001 := 50;"
        matches = STLadderInteropGuard.detect_ladder_constructs(code, check_legacy_registers=True)
        assert len(matches) == 3
        assert all(m.pattern_type == "LEGACY_REGISTER_ACCESS" for m in matches)

    def test_ignore_legacy_registers_when_disabled(self):
        code = "%R0001 := 100;"
        matches = STLadderInteropGuard.detect_ladder_constructs(code, check_legacy_registers=False)
        assert len(matches) == 0


# ============================================================================
# Comment Safety Tests
# ============================================================================

class TestCommentHandling:
    """Verifies that comments containing ladder terms are safe and do not trigger false positives."""

    def test_iec_block_comment_ignored(self):
        code = """
        PROGRAM Test
        VAR
            bStart : BOOL;
            bMotor : BOOL;
        END_VAR

        (* Migration Note: Replaced RUNG 1: ---[ bStart ]---( bMotor )--- with ST *)
        bMotor := bStart;
        END_PROGRAM
        """
        matches = STLadderInteropGuard.detect_ladder_constructs(code)
        assert len(matches) == 0

    def test_c_style_comment_ignored(self):
        code = """
        /* Legacy Ladder Reference:
           XIC(Start) OTE(Motor)
           %R0001 was speed
        */
        nSpeed := 1500;
        """
        matches = STLadderInteropGuard.detect_ladder_constructs(code)
        assert len(matches) == 0

    def test_line_comment_ignored(self):
        code = """
        bActive := TRUE; // Formerly: ---[ Run ]---(S Active )---
        """
        matches = STLadderInteropGuard.detect_ladder_constructs(code)
        assert len(matches) == 0

    def test_ladder_in_code_detected_despite_surrounding_comments(self):
        code = """
        // Clean comment
        ---[ BadContact ]---
        // Another comment
        """
        matches = STLadderInteropGuard.detect_ladder_constructs(code)
        assert len(matches) == 1
        assert matches[0].line_number == 3


# ============================================================================
# Enforcement Tests
# ============================================================================

class TestSTEnforcement:
    """Verifies strict ST enforcement and error throwing."""

    def test_valid_st_code_passes(self):
        valid_st = """
        PROGRAM MainLogic
        VAR
            bStart : BOOL := FALSE;
            bStop : BOOL := FALSE;
            bMotor : BOOL := FALSE;
            nSpeed : INT := 0;
        END_VAR

        IF bStart AND NOT bStop THEN
            bMotor := TRUE;
            nSpeed := 1750;
        ELSIF bStop THEN
            bMotor := FALSE;
            nSpeed := 0;
        END_IF;
        END_PROGRAM
        """
        result = STLadderInteropGuard.enforce_st_code(valid_st)
        assert result == valid_st

    def test_ladder_construct_raises_exception(self):
        ladder_code = """
        PROGRAM InvalidLogic
        VAR
            bStart : BOOL;
            bMotor : BOOL;
        END_VAR

        ---[ bStart ]---( bMotor )---
        END_PROGRAM
        """
        with pytest.raises(LadderConstructRejectedError) as exc_info:
            STLadderInteropGuard.enforce_st_code(ladder_code, context_name="TestPOU")

        err_str = str(exc_info.value)
        assert "[TestPOU]" in err_str
        assert "Ladder logic construct rejected" in err_str
        assert len(exc_info.value.violations) >= 2

    def test_pure_iec_st_constructs_not_rejected(self):
        """Verify that genuine IEC 61131-3 ST features are NOT falsely rejected as ladder constructs."""
        valid_code = """
        PROGRAM SensorProcess
        VAR
            DataBuffer : ARRAY[1..20] OF INT;
            i : INT := 1;
            Timestamp : DINT;
            NetworkState : INT := 0;
            bRun : BOOL;
            bStop : BOOL;
            bMotor : BOOL;
        END_VAR

        // Zero-argument standard and custom function calls
        Timestamp := GetTickCount();
        InitHardware();

        // Array indexing and assignment
        DataBuffer[i] := 100;
        DataBuffer[1] := 42;

        // Parenthesized boolean logic expressions
        bMotor := (bRun OR bMotor) AND NOT bStop;

        // Variables with 'network' or 'net' substring
        NetworkState := NetworkState + 1;
        END_PROGRAM
        """
        result = STLadderInteropGuard.enforce_st_code(valid_code, context_name="PureIEC")
        assert result == valid_code

    def test_rejection_of_contacts_coils_rungs_networks_with_actionable_guidance(self):
        """Verify rejection of contacts, coils, rungs, and network labels with actionable guidance."""
        bad_code = """
        NETWORK 1: Main Control Network
        RUNG 1:
        --[ ]----[/]----( )--
        -- ( ) --
        """
        with pytest.raises(LadderConstructRejectedError) as exc_info:
            STLadderInteropGuard.enforce_st_code(bad_code, context_name="NetworkRungPOU")

        err_str = str(exc_info.value)
        assert "[NetworkRungPOU]" in err_str
        assert "Ladder logic construct rejected" in err_str
        assert "Recommended Structured Text Conversion" in err_str

        # Check detected violations cover contacts, coils, rungs, and network labels
        types = [v.pattern_type for v in exc_info.value.violations]
        assert "NETWORK_LABEL" in types
        assert "RUNG_MARKER" in types
        assert any("CONTACT" in t for t in types)
        assert any("COIL" in t for t in types)

        # Verify actionable guidance exists in violations
        for v in exc_info.value.violations:
            assert len(v.explanation) > 10
            assert len(v.st_recommendation) >= 3

    def test_analyze_code_structure(self):
        mixed_code = "XIC(In1) OTE(Out1)"
        result = STLadderInteropGuard.analyze_code(mixed_code)
        assert not result.is_valid_st
        assert result.ladder_detected
        assert len(result.constructs_detected) == 2
        assert len(result.conversion_recommendations) > 0
        assert result.suggested_st_code is not None
        assert "Out1 := In1;" in result.suggested_st_code

    @pytest.mark.parametrize("construct, expected_pattern", [
        ("--[ ]--", "ASCII_NO_CONTACT"),
        ("--[/]--", "ASCII_NC_CONTACT"),
        ("--( )--", "ASCII_NORMAL_COIL"),
        ("--(S)--", "ASCII_SET_COIL"),
        ("--(R)--", "ASCII_RESET_COIL"),
        ("NETWORK", "NETWORK_LABEL"),
        ("RUNG", "RUNG_MARKER"),
    ])
    def test_strict_rejection_of_all_legacy_ladder_constructs(self, construct: str, expected_pattern: str):
        """Strictly verifies that each legacy Advanced Ladder construct is rejected with actionable recipes."""
        code = f"""
        PROGRAM LegacyAuditPOU
        VAR
            bVal : BOOL;
        END_VAR

        {construct}
        END_PROGRAM
        """
        with pytest.raises(LadderConstructRejectedError) as exc_info:
            STLadderInteropGuard.enforce_st_code(code, context_name="AuditCheck")

        err = str(exc_info.value)
        assert "[AuditCheck]" in err
        assert "Ladder logic construct rejected" in err
        assert "Recommended Structured Text Conversion" in err
        violations = exc_info.value.violations
        assert len(violations) >= 1
        assert any(expected_pattern in v.pattern_type for v in violations)
        for v in violations:
            assert len(v.explanation) > 10
            assert len(v.st_recommendation) >= 1


# ============================================================================
# Conversion & Recommendation Tests
# ============================================================================

class TestLadderConversion:
    """Verifies conversion of ladder constructs into valid Structured Text."""

    def test_convert_series_contacts_and_coil(self):
        ladder_snippet = "---[ Start ]---[/ Stop ]---( Motor )---"
        converted = STLadderInteropGuard.convert_ladder_to_st(ladder_snippet)
        assert converted == "Motor := Start AND NOT Stop;"

    def test_convert_set_latch_coil(self):
        ladder_snippet = "---[ Trigger ]---(S AlarmActive )---"
        converted = STLadderInteropGuard.convert_ladder_to_st(ladder_snippet)
        assert "IF Trigger THEN" in converted
        assert "AlarmActive := TRUE;" in converted
        assert "END_IF;" in converted

    def test_convert_reset_unlatch_coil(self):
        ladder_snippet = "---[ ResetBtn ]---(R AlarmActive )---"
        converted = STLadderInteropGuard.convert_ladder_to_st(ladder_snippet)
        assert "IF ResetBtn THEN" in converted
        assert "AlarmActive := FALSE;" in converted
        assert "END_IF;" in converted

    def test_convert_mnemonic_ote(self):
        mnemonic = "XIC(Sensor1) XIO(Sensor2) OTE(Valve1)"
        converted = STLadderInteropGuard.convert_ladder_to_st(mnemonic)
        assert converted == "Valve1 := Sensor1 AND NOT Sensor2;"

    def test_convert_mnemonic_otl(self):
        mnemonic = "XIC(EmergencyStop) OTL(FaultLatched)"
        converted = STLadderInteropGuard.convert_ladder_to_st(mnemonic)
        assert "IF EmergencyStop THEN" in converted
        assert "FaultLatched := TRUE;" in converted
        assert "END_IF;" in converted

    def test_convert_mnemonic_otu(self):
        mnemonic = "XIC(FaultAcknowledge) OTU(FaultLatched)"
        converted = STLadderInteropGuard.convert_ladder_to_st(mnemonic)
        assert "IF FaultAcknowledge THEN" in converted
        assert "FaultLatched := FALSE;" in converted
        assert "END_IF;" in converted

    def test_convert_network_and_rung_labels(self):
        ladder = """
        NETWORK 1: Motor Run Logic
        RUNG 1: Start Rung
        ---[ Start ]---( Motor )---
        END_RUNG
        END_NETWORK
        """
        converted = STLadderInteropGuard.convert_ladder_to_st(ladder)
        assert "// --- Network 1: Motor Run Logic ---" in converted
        assert "// --- Rung 1: Start Rung ---" in converted
        assert "Motor := Start;" in converted
        assert "// --- End of end_rung ---" in converted
        assert "// --- End of end_network ---" in converted

    def test_convert_empty_contact_and_coil(self):
        empty_sample = "--[ ]----( )--"
        converted = STLadderInteropGuard.convert_ladder_to_st(empty_sample)
        assert "LADDER_CONVERT_TODO" in converted
        assert "Actionable ST:" in converted

    def test_recipe_catalog_completeness(self):
        recipes = STLadderInteropGuard.list_all_recipes()
        assert len(recipes) >= 16
        keys = [
            "NO_CONTACT",
            "NC_CONTACT",
            "COIL_NORMAL",
            "COIL_SET",
            "COIL_RESET",
            "TIMER_ON",
            "COUNTER_UP",
            "NETWORK_LABEL",
            "RUNG_MARKER",
        ]
        for k in keys:
            recipe = STLadderInteropGuard.get_conversion_recipe(k)
            assert recipe is not None
            assert recipe.category in ("CONTACT", "COIL", "TIMER", "COUNTER", "EDGE", "MATH", "REGISTER", "RUNG")
            assert len(recipe.st_equivalent) > 0

    @pytest.mark.parametrize("construct, expected_indicators", [
        ("--[ ]--", ["LADDER_CONVERT_TODO", "Actionable ST", "Normally Open Contact", "Motor := Start;"]),
        ("--[/]--", ["LADDER_CONVERT_TODO", "Actionable ST", "Normally Closed Contact", "NOT"]),
        ("--( )--", ["LADDER_CONVERT_TODO", "Actionable ST", "Normal Output Coil", "Output := Condition;"]),
        ("--(S)--", ["LADDER_CONVERT_TODO", "Actionable ST", "Set / Latch Coil", "TRUE"]),
        ("--(R)--", ["LADDER_CONVERT_TODO", "Actionable ST", "Reset / Unlatch Coil", "FALSE"]),
        ("NETWORK", ["// --- Network ---"]),
        ("RUNG", ["// --- Rung ---"]),
    ])
    def test_actionable_recipes_for_all_legacy_ladder_constructs(self, construct: str, expected_indicators: list[str]):
        """Verifies actionable conversion recipes to pure ST for each legacy construct."""
        converted = STLadderInteropGuard.convert_ladder_to_st(construct)
        for ind in expected_indicators:
            assert ind in converted, f"Expected '{ind}' in converted output for construct '{construct}': {converted}"


# ============================================================================
# Project Validation Tests
# ============================================================================

class TestProjectValidation:
    """Verifies project-level validation against Cscape project files."""

    def test_valid_iec_st_project(self, tmp_path: Path):
        # Create standard IEC ST project layout
        k5p = tmp_path / "appli.k5p"
        k5p.write_text("/P,MainProgram,PROGRAM,ST\n/P,SafetyFB,FUNCTION_BLOCK,ST\n", encoding="utf-8")

        cpo = tmp_path / "appli.CPO"
        cpo.write_text("[Options]\nLanguage=ST\nTarget=K5_SIM\n", encoding="utf-8")

        pous = tmp_path / "pous"
        pous.mkdir()
        (pous / "MainProgram.st").write_text("PROGRAM MainProgram\nEND_PROGRAM\n", encoding="utf-8")

        manifest = tmp_path / "cscape_project.json"
        manifest.write_text(json.dumps({
            "name": "TestProj",
            "iec_engine": "Cscape IEC 61131-3 Structured Text",
            "pous": [{"name": "MainProgram", "file_path": str(pous / "MainProgram.st")}]
        }), encoding="utf-8")

        report = STLadderInteropGuard.validate_project(tmp_path)
        assert report.is_pure_iec_st
        assert report.mode == "IEC_61131_ST"
        assert len(report.violations) == 0
        assert report.pous == {"MainProgram": "ST", "SafetyFB": "ST"}

        # Enforce should not raise
        STLadderInteropGuard.enforce_project_st_mode(tmp_path)

    def test_project_with_legacy_csp_fails(self, tmp_path: Path):
        # Create a legacy .csp file
        (tmp_path / "LegacyApp.csp").write_bytes(b"\x00\x01\x02\x03")

        report = STLadderInteropGuard.validate_project(tmp_path)
        assert not report.is_pure_iec_st
        assert report.mode == "ADVANCED_LADDER"
        assert any(".csp" in v for v in report.violations)

        with pytest.raises(NonIECProjectError) as exc_info:
            STLadderInteropGuard.enforce_project_st_mode(tmp_path)
        assert "ADVANCED_LADDER" in str(exc_info.value)

    def test_project_with_ld_pou_in_k5p_fails(self, tmp_path: Path):
        k5p = tmp_path / "appli.k5p"
        k5p.write_text("/P,MainST,PROGRAM,ST\n/P,LadderRungs,PROGRAM,LD\n", encoding="utf-8")

        report = STLadderInteropGuard.validate_project(tmp_path)
        assert not report.is_pure_iec_st
        assert report.mode == "IEC_61131_LD_MIXED"
        assert any("LadderRungs" in v for v in report.violations)

        with pytest.raises(NonIECProjectError) as exc_info:
            STLadderInteropGuard.enforce_project_st_mode(tmp_path)
        assert "IEC_61131_LD_MIXED" in str(exc_info.value)

    def test_project_with_ld_file_in_pous_fails(self, tmp_path: Path):
        k5p = tmp_path / "appli.k5p"
        k5p.write_text("/P,MainST,PROGRAM,ST\n", encoding="utf-8")
        pous = tmp_path / "pous"
        pous.mkdir()
        (pous / "OldLogic.ld").write_text("<LD_Net>XML</LD_Net>", encoding="utf-8")

        report = STLadderInteropGuard.validate_project(tmp_path)
        assert not report.is_pure_iec_st
        assert any("OldLogic.ld" in v for v in report.violations)

        with pytest.raises(NonIECProjectError):
            STLadderInteropGuard.enforce_project_st_mode(tmp_path)

    def test_project_with_cpo_language_ld_fails(self, tmp_path: Path):
        k5p = tmp_path / "appli.k5p"
        k5p.write_text("/P,MainST,PROGRAM,ST\n", encoding="utf-8")
        cpo = tmp_path / "appli.CPO"
        cpo.write_text("[Options]\nLanguage=LD\n", encoding="utf-8")

        report = STLadderInteropGuard.validate_project(tmp_path)
        assert not report.is_pure_iec_st
        assert any("Language=LD" in v for v in report.violations)

    def test_nonexistent_project_directory(self, tmp_path: Path):
        bad_dir = tmp_path / "does_not_exist"
        report = STLadderInteropGuard.validate_project(bad_dir)
        assert not report.is_pure_iec_st
        assert report.mode == "INVALID"


# ============================================================================
# Serialization Tests
# ============================================================================

class TestDataModelsSerialization:
    """Verifies that dataclasses serialize cleanly to dictionaries."""

    def test_pattern_match_serialization(self):
        match = LadderPatternMatch(
            pattern_type="NO_CONTACT",
            line_number=10,
            matched_text="---[ Start ]---",
            st_recommendation="Start",
            explanation="Normally open contact",
        )
        d = match.to_dict()
        assert d["pattern_type"] == "NO_CONTACT"
        assert d["line_number"] == 10
        assert "Line 10" in str(match)

    def test_recipe_serialization(self):
        recipe = CONVERSION_RECIPES["NO_CONTACT"]
        d = recipe.to_dict()
        assert d["construct_name"] == "Normally Open Contact (XIC / NO)"
        assert d["category"] == "CONTACT"

    def test_analysis_result_serialization(self):
        res = STLadderInteropGuard.analyze_code("XIC(In) OTE(Out)")
        d = res.to_dict()
        assert d["ladder_detected"] is True
        assert d["constructs_count"] == 2
        assert "suggested_st_code" in d

    def test_report_serialization(self):
        report = ProjectModeReport(
            is_pure_iec_st=True,
            mode="IEC_61131_ST",
            project_dir="C:/test",
            violations=[],
            pous={"Main": "ST"},
            recommendations=[],
        )
        d = report.to_dict()
        assert d["is_pure_iec_st"] is True
        assert d["mode"] == "IEC_61131_ST"


# ============================================================================
# H12 Native Conversion Reality Tests
# ============================================================================

class TestSTToLDNativeConversionReality:
    """H12: Certify ST-to-LD native conversion reality in Cscape 10.2."""

    def test_native_conversion_permanently_blocked(self):
        assert STLadderInteropGuard.NATIVE_CONVERSION_STATUS == "BLOCKED_NATIVE: DOCUMENT_ONLY"
        assert STLadderInteropGuard.IN_GUI_CONVERSION_BLOCKED is True

    def test_request_in_gui_conversion_returns_blocked_status(self):
        res = STLadderInteropGuard.request_in_gui_conversion("TankLevelControl")
        assert res["status"] == "blocked"
        assert res["error_code"] == "BLOCKED_NATIVE"
        assert "permanently BLOCKED" in res["details"]
        assert res["data"]["in_gui_conversion_blocked"] is True
        assert res["data"]["offline_ast_transpilation_available"] is True
        assert res["data"]["pou_name"] == "TankLevelControl"

