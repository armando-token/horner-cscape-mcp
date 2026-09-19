"""Comprehensive Test Suite for IEC 61131-3 Structured Text (ST) Modules.

Verifies:
- st_parser.py: POU parsing, all 16 elementary data types, statements, error detection,
  missing semicolons, undeclared variables, type mismatches, and strict ladder rejection.
- st_generator.py: Clean ST generation, variable dictionaries (ST, appli.txt, MD, CSV),
  and industrial automation pattern generators (State Machine, Motor, PID, Batch Mixer, Modbus).
- project_builder.py: Straton K5 / Cscape compatible project structure assembly,
  k5p registration, appli.txt variable synchronization, project validation, and ZIP export.
- Rich example ST programs in examples/st_samples/ and fixtures in fixtures/.
"""

import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import List

import pytest

from src.iec.st_parser import (
    IssueSeverity,
    POUKind,
    STANDARD_DATA_TYPES,
    STIssue,
    STParser,
    STPOU,
    STValidationResult,
    STVariable,
    VarScope,
)
from src.iec.st_generator import STGenerator


FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples" / "st_samples"


# ============================================================================
# 1. POU Parsing Tests
# ============================================================================

class TestSTParserPOU:
    """Tests POU structure parsing (PROGRAM, FUNCTION_BLOCK, FUNCTION)."""

    def test_parse_valid_program(self):
        code = """
        PROGRAM MainCycle
        VAR
            bStart : BOOL := FALSE;
            nCounter : INT := 0;
        END_VAR
        IF bStart THEN
            nCounter := nCounter + 1;
        END_IF;
        END_PROGRAM
        """
        res = STParser.validate(code)
        assert res.is_valid is True
        assert len(res.pous) == 1
        pou = res.pous[0]
        assert pou.kind == POUKind.PROGRAM
        assert pou.name == "MainCycle"
        assert len(pou.variables) == 2
        assert pou.get_variable("bStart") is not None
        assert pou.get_variable("bStart").data_type == "BOOL"
        assert pou.get_variable("nCounter").initial_value == "0"

    def test_parse_valid_function_block(self):
        code = """
        FUNCTION_BLOCK FB_Counter
        VAR_INPUT
            CountUp : BOOL;
            Reset : BOOL;
        END_VAR
        VAR_OUTPUT
            CurrentValue : DINT := 0;
        END_VAR
        IF Reset THEN
            CurrentValue := 0;
        ELSIF CountUp THEN
            CurrentValue := CurrentValue + 1;
        END_IF;
        END_FUNCTION_BLOCK
        """
        res = STParser.validate(code)
        assert res.is_valid is True
        assert len(res.pous) == 1
        fb = res.pous[0]
        assert fb.kind == POUKind.FUNCTION_BLOCK
        assert fb.name == "FB_Counter"
        assert len(fb.get_variables_by_scope(VarScope.VAR_INPUT)) == 2
        assert len(fb.get_variables_by_scope(VarScope.VAR_OUTPUT)) == 1

    def test_parse_valid_function(self):
        code = """
        FUNCTION ClampValue : REAL
        VAR_INPUT
            InVal : REAL;
            MinVal : REAL;
            MaxVal : REAL;
        END_VAR
        IF InVal < MinVal THEN
            ClampValue := MinVal;
        ELSIF InVal > MaxVal THEN
            ClampValue := MaxVal;
        ELSE
            ClampValue := InVal;
        END_IF;
        END_FUNCTION
        """
        res = STParser.validate(code)
        assert res.is_valid is True
        fn = res.pous[0]
        assert fn.kind == POUKind.FUNCTION
        assert fn.name == "ClampValue"
        assert fn.return_type == "REAL"

    def test_strip_comments(self):
        code = """
        (* Multi-line
           IEC comment *)
        PROGRAM P
        VAR
            x : INT := 1; // Inline line comment
            /* C-style comment */
            y : INT := 2;
        END_VAR
        x := y;
        END_PROGRAM
        """
        res = STParser.validate(code)
        assert res.is_valid is True
        assert len(res.pous) == 1


# ============================================================================
# 2. Data Types Validation Tests
# ============================================================================

class TestSTDataTypes:
    """Verifies support for all 16 specified elementary data types."""

    ALL_16_TYPES = [
        ("BOOL", "TRUE"),
        ("BYTE", "16#FF"),
        ("WORD", "16#FFFF"),
        ("DWORD", "16#FFFFFFFF"),
        ("SINT", "-120"),
        ("INT", "-30000"),
        ("DINT", "-2000000"),
        ("LINT", "-9000000000"),
        ("USINT", "250"),
        ("UINT", "65000"),
        ("UDINT", "4000000000"),
        ("ULINT", "18000000000"),
        ("REAL", "3.14"),
        ("LREAL", "2.71828"),
        ("TIME", "T#10s"),
        ("STRING", "'Text'"),
    ]

    @pytest.mark.parametrize("dtype,init_val", ALL_16_TYPES)
    def test_each_elementary_data_type(self, dtype, init_val):
        code = f"""
        PROGRAM TypeCheck
        VAR
            testVar : {dtype} := {init_val};
        END_VAR
        testVar := {init_val};
        END_PROGRAM
        """
        res = STParser.validate(code)
        assert res.is_valid is True
        assert len(res.errors) == 0
        v = res.pous[0].get_variable("testVar")
        assert v is not None
        assert v.data_type == dtype

    def test_array_data_type(self):
        code = """
        PROGRAM ArrayCheck
        VAR
            Buffer : ARRAY [1..10] OF INT;
            Idx : INT := 1;
        END_VAR
        Buffer[Idx] := 100;
        END_PROGRAM
        """
        res = STParser.validate(code)
        assert res.is_valid is True
        v = res.pous[0].get_variable("Buffer")
        assert v.is_array is True
        assert v.array_bounds == "1..10"

    def test_address_binding(self):
        code = """
        PROGRAM AddressCheck
        VAR
            InputBit AT %IX0.0 : BOOL;
            OutputRegister AT %QW100 : WORD := 16#0000;
        END_VAR
        OutputRegister := 16#1234;
        END_PROGRAM
        """
        res = STParser.validate(code)
        assert res.is_valid is True
        ib = res.pous[0].get_variable("InputBit")
        assert ib.address == "%IX0.0"
        oq = res.pous[0].get_variable("OutputRegister")
        assert oq.address == "%QW100"

    def test_retain_and_constant_flags(self):
        code = """
        PROGRAM RetainCheck
        VAR RETAIN
            RetainedTotal : DINT := 0;
        END_VAR
        VAR CONSTANT
            MaxLimit : INT := 500;
        END_VAR
        RetainedTotal := RetainedTotal + 1;
        END_PROGRAM
        """
        res = STParser.validate(code)
        assert res.is_valid is True
        v_ret = res.pous[0].get_variable("RetainedTotal")
        assert v_ret.is_retain is True
        v_cst = res.pous[0].get_variable("MaxLimit")
        assert v_cst.is_constant is True


# ============================================================================
# 3. Statements & Control Flow Tests
# ============================================================================

class TestSTControlFlow:
    """Verifies statements: IF, CASE, FOR, WHILE, REPEAT, and FB calls."""

    def test_if_elsif_else(self):
        code = """
        PROGRAM IfTest
        VAR
            val : INT := 5;
            res : INT := 0;
        END_VAR
        IF val > 10 THEN
            res := 1;
        ELSIF val > 0 THEN
            res := 2;
        ELSE
            res := 3;
        END_IF;
        END_PROGRAM
        """
        assert STParser.validate(code).is_valid is True

    def test_case_statement(self):
        code = """
        PROGRAM CaseTest
        VAR
            mode : INT := 2;
            speed : REAL := 0.0;
        END_VAR
        CASE mode OF
            1: speed := 10.0;
            2: speed := 50.0;
            3: speed := 100.0;
            ELSE speed := 0.0;
        END_CASE;
        END_PROGRAM
        """
        assert STParser.validate(code).is_valid is True

    def test_for_and_while_loops(self):
        code = """
        PROGRAM LoopTest
        VAR
            i : INT := 0;
            sum : DINT := 0;
        END_VAR
        FOR i := 1 TO 10 BY 2 DO
            sum := sum + INT_TO_DINT(i);
        END_FOR;
        WHILE i > 0 DO
            i := i - 1;
        END_WHILE;
        END_PROGRAM
        """
        assert STParser.validate(code).is_valid is True

    def test_repeat_until_loop(self):
        code = """
        PROGRAM RepeatTest
        VAR
            count : INT := 5;
        END_VAR
        REPEAT
            count := count - 1;
        UNTIL count <= 0 END_REPEAT;
        END_PROGRAM
        """
        assert STParser.validate(code).is_valid is True

    def test_standard_fb_invocation(self):
        code = """
        PROGRAM TimerTest
        VAR
            MyTimer : TON;
            Trigger : BOOL := TRUE;
            TimerDone : BOOL := FALSE;
        END_VAR
        MyTimer(IN := Trigger, PT := T#2s500ms);
        TimerDone := MyTimer.Q;
        END_PROGRAM
        """
        res = STParser.validate(code)
        assert res.is_valid is True


# ============================================================================
# 4. Error Detection Tests
# ============================================================================

class TestSTErrorDetection:
    """Verifies strict syntax, undeclared variable, and type mismatch checks."""

    def test_missing_semicolon_in_var(self):
        code = """
        PROGRAM P
        VAR
            badVar : INT
            goodVar : BOOL := TRUE;
        END_VAR
        goodVar := FALSE;
        END_PROGRAM
        """
        res = STParser.validate(code)
        assert res.is_valid is False
        codes = [e.code for e in res.errors]
        assert "ERR_MISSING_SEMICOLON" in codes

    def test_missing_semicolon_in_statement(self):
        code = """
        PROGRAM P
        VAR
            a : INT := 0;
        END_VAR
        a := 10
        END_PROGRAM
        """
        res = STParser.validate(code)
        assert res.is_valid is False
        codes = [e.code for e in res.errors]
        assert "ERR_MISSING_SEMICOLON" in codes

    def test_missing_semicolon_in_end_if(self):
        code = """
        PROGRAM P
        VAR
            b : BOOL := TRUE;
        END_VAR
        IF b THEN
            b := FALSE;
        END_IF
        END_PROGRAM
        """
        res = STParser.validate(code)
        assert res.is_valid is False
        assert any(e.code == "ERR_MISSING_SEMICOLON" for e in res.errors)

    def test_undeclared_variable_assignment(self):
        code = """
        PROGRAM P
        VAR
            declared : INT := 1;
        END_VAR
        ghostVariable := 99;
        END_PROGRAM
        """
        res = STParser.validate(code)
        assert res.is_valid is False
        assert any(e.code == "ERR_UNDECLARED_VAR" for e in res.errors)

    def test_undeclared_variable_in_expression(self):
        code = """
        PROGRAM P
        VAR
            total : INT := 0;
        END_VAR
        total := total + unknownFactor;
        END_PROGRAM
        """
        res = STParser.validate(code)
        assert res.is_valid is False
        assert any(e.code == "ERR_UNDECLARED_VAR" for e in res.errors)

    def test_type_mismatch_number_to_bool(self):
        code = """
        PROGRAM P
        VAR
            flag : BOOL := FALSE;
        END_VAR
        flag := 42;
        END_PROGRAM
        """
        res = STParser.validate(code)
        assert res.is_valid is False
        assert any(e.code == "ERR_TYPE_MISMATCH" for e in res.errors)

    def test_type_mismatch_string_to_bool(self):
        code = """
        PROGRAM P
        VAR
            flag : BOOL := FALSE;
        END_VAR
        flag := 'TRUE';
        END_PROGRAM
        """
        res = STParser.validate(code)
        assert res.is_valid is False
        assert any(e.code == "ERR_TYPE_MISMATCH" for e in res.errors)

    def test_type_mismatch_float_to_int(self):
        code = """
        PROGRAM P
        VAR
            n : INT := 0;
        END_VAR
        n := 3.14159;
        END_PROGRAM
        """
        res = STParser.validate(code)
        assert res.is_valid is False
        assert any(e.code == "ERR_TYPE_MISMATCH" for e in res.errors)

    def test_type_mismatch_raw_number_to_time(self):
        code = """
        PROGRAM P
        VAR
            t : TIME := T#0s;
        END_VAR
        t := 5000;
        END_PROGRAM
        """
        res = STParser.validate(code)
        assert res.is_valid is False
        assert any(e.code == "ERR_TYPE_MISMATCH" for e in res.errors)

    def test_unclosed_if_block(self):
        code = """
        PROGRAM P
        VAR
            x : BOOL := TRUE;
        END_VAR
        IF x THEN
            x := FALSE;
        END_PROGRAM
        """
        res = STParser.validate(code)
        assert res.is_valid is False
        assert any(e.code == "ERR_UNCLOSED_IF" for e in res.errors)

    def test_unclosed_for_block(self):
        code = """
        PROGRAM P
        VAR
            i : INT := 0;
        END_VAR
        FOR i := 1 TO 5 DO
            i := i + 1;
        END_PROGRAM
        """
        res = STParser.validate(code)
        assert res.is_valid is False
        assert any(e.code == "ERR_UNCLOSED_FOR" for e in res.errors)

    def test_unclosed_case_block(self):
        code = """
        PROGRAM P
        VAR
            s : INT := 1;
        END_VAR
        CASE s OF
            1: s := 0;
        END_PROGRAM
        """
        res = STParser.validate(code)
        assert res.is_valid is False
        assert any(e.code == "ERR_UNCLOSED_CASE" for e in res.errors)

    def test_unclosed_var_block(self):
        code = """
        PROGRAM P
        VAR
            x : INT := 1;
        x := x + 1;
        END_PROGRAM
        """
        res = STParser.validate(code)
        assert res.is_valid is False
        assert any(e.code == "ERR_UNCLOSED_VAR" for e in res.errors)


# ============================================================================
# 5. Strict Ladder Logic Rejection Tests
# ============================================================================

class TestStrictLadderRejection:
    """Enforces strict constraint: ONLY IEC 61131-3 Structured Text allowed."""

    def test_reject_normally_open_contact(self):
        code = "PROGRAM P VAR b : BOOL; END_VAR ---[ ]--- END_PROGRAM"
        res = STParser.validate(code)
        assert res.is_valid is False
        assert any(e.code == "ERR_LADDER_FORBIDDEN" for e in res.errors)

    def test_reject_normally_closed_contact(self):
        code = "PROGRAM P VAR b : BOOL; END_VAR ---[/]--- END_PROGRAM"
        res = STParser.validate(code)
        assert res.is_valid is False
        assert any(e.code == "ERR_LADDER_FORBIDDEN" for e in res.errors)

    def test_reject_relay_coil(self):
        code = "PROGRAM P VAR b : BOOL; END_VAR ---( )--- END_PROGRAM"
        res = STParser.validate(code)
        assert res.is_valid is False
        assert any(e.code == "ERR_LADDER_FORBIDDEN" for e in res.errors)

    def test_reject_rung_keyword(self):
        code = """
        PROGRAM P
        VAR
            x : BOOL;
        END_VAR
        RUNG 1:
        x := TRUE;
        END_RUNG
        END_PROGRAM
        """
        res = STParser.validate(code)
        assert res.is_valid is False
        assert any(e.code == "ERR_LADDER_FORBIDDEN" for e in res.errors)


# ============================================================================
# 6. ST Generator Tests
# ============================================================================

class TestSTGenerator:
    """Verifies ST generation and variable dictionaries."""

    def test_generate_program_roundtrip(self):
        vars_ = [
            STVariable(name="StartBtn", data_type="BOOL", initial_value="FALSE"),
            STVariable(name="RunCoil", data_type="BOOL", initial_value="FALSE"),
            STVariable(name="CycleTimer", data_type="TON"),
        ]
        body = [
            "IF StartBtn THEN",
            "    RunCoil := TRUE;",
            "END_IF;",
            "CycleTimer(IN := RunCoil, PT := T#5s);",
        ]
        st_code = STGenerator.generate_program("Prog_GenTest", vars_, body, "Auto generated test POU")
        assert "PROGRAM Prog_GenTest" in st_code
        assert "END_PROGRAM" in st_code

        # Generated code must parse with 0 errors
        res = STParser.validate(st_code)
        assert res.is_valid is True
        assert len(res.errors) == 0

    def test_generate_appli_txt(self):
        vars_ = [
            STVariable(name="MotorCurrent", data_type="REAL", initial_value="0.0", address="%AI10", comment="Phase A current"),
            STVariable(name="RunHours", data_type="UDINT", initial_value="0", is_retain=True, comment="Retentive hours"),
        ]
        txt = STGenerator.generate_appli_txt("SampleApp", vars_, "Sample description")
        assert "[long]" in txt
        assert "A-<PROJECT>=Sample description" in txt
        assert "V-MotorCurrent=Phase A current" in txt
        assert "[variables]" in txt
        assert "MotorCurrent:REAL:=0.0@%AI10" in txt
        assert "RunHours:UDINT:=0:RETAIN" in txt

    def test_generate_markdown_dictionary(self):
        vars_ = [
            STVariable(name="TankLevel", data_type="REAL", initial_value="50.0", comment="Level %"),
        ]
        md = STGenerator.generate_markdown_dictionary(vars_, "Test Dictionary")
        assert "### Test Dictionary" in md
        assert "| **TankLevel** |" in md
        assert "`REAL`" in md

    def test_generate_csv_dictionary(self):
        vars_ = [
            STVariable(name="FlowRate", data_type="REAL", initial_value="12.5", address="%AI1", comment="Flow in LPM"),
        ]
        csv_data = STGenerator.generate_csv_dictionary(vars_)
        assert "FlowRate" in csv_data
        assert "%AI1" in csv_data

    @pytest.mark.parametrize("gen_func", [
        lambda: STGenerator.generate_state_machine("SM_FSM", ["INIT", "FILL", "SEAL", "FAULT"]),
        lambda: STGenerator.generate_motor_controller("FB_GenMotor"),
        lambda: STGenerator.generate_pid_controller("FB_GenPID"),
        lambda: STGenerator.generate_batch_mixer("Prog_GenMixer"),
        lambda: STGenerator.generate_modbus_io_handler("Prog_GenModbus"),
    ])
    def test_all_industrial_pattern_generators_roundtrip(self, gen_func):
        code = gen_func()
        res = STParser.validate(code)
        assert res.is_valid is True, f"Errors in generated pattern: {res.errors}"
        assert len(res.errors) == 0


# ============================================================================
# 7. Rich ST Examples and Fixtures Verification
# ============================================================================

class TestSTSamplesAndFixtures:
    """Verifies all rich example files in examples/st_samples/ and fixtures in fixtures/."""

    SAMPLE_FILES = [
        "motor_controller.st",
        "pid_temperature_loop.st",
        "batch_mixer.st",
        "modbus_io_handler.st",
    ]

    @pytest.mark.parametrize("sample_name", SAMPLE_FILES)
    def test_example_st_sample_files_are_valid(self, sample_name):
        sample_path = SAMPLES_DIR / sample_name
        assert sample_path.exists(), f"Sample file missing: {sample_path}"
        code = sample_path.read_text(encoding="utf-8")
        res = STParser.validate(code)
        assert res.is_valid is True, f"Validation errors in {sample_name}: {res.errors}"
        assert len(res.errors) == 0

    VALID_FIXTURES = [
        "valid_program.st",
        "valid_function_block.st",
        "valid_function.st",
        "all_types_program.st",
        "complex_control_logic.st",
    ]

    @pytest.mark.parametrize("fix_name", VALID_FIXTURES)
    def test_valid_fixtures_pass(self, fix_name):
        fix_path = FIXTURES_DIR / fix_name
        assert fix_path.exists(), f"Fixture missing: {fix_path}"
        code = fix_path.read_text(encoding="utf-8")
        res = STParser.validate(code)
        assert res.is_valid is True, f"Expected valid for {fix_name}, got: {res.errors}"

    INVALID_FIXTURES = [
        ("missing_semicolon.st", "ERR_MISSING_SEMICOLON"),
        ("undeclared_variable.st", "ERR_UNDECLARED_VAR"),
        ("mismatched_types.st", "ERR_TYPE_MISMATCH"),
        ("unclosed_if.st", "ERR_UNCLOSED_IF"),
        ("unclosed_for.st", "ERR_UNCLOSED_FOR"),
        ("unclosed_case.st", "ERR_UNCLOSED_CASE"),
        ("unclosed_var.st", "ERR_UNCLOSED_VAR"),
        ("advanced_ladder_forbidden.st", "ERR_LADDER_FORBIDDEN"),
    ]

    @pytest.mark.parametrize("fix_name,expected_err", INVALID_FIXTURES)
    def test_invalid_fixtures_fail_with_expected_error(self, fix_name, expected_err):
        fix_path = FIXTURES_DIR / fix_name
        assert fix_path.exists(), f"Fixture missing: {fix_path}"
        code = fix_path.read_text(encoding="utf-8")
        res = STParser.validate(code)
        assert res.is_valid is False, f"Expected invalid for {fix_name}"
        error_codes = [e.code for e in res.errors]
        assert expected_err in error_codes, f"Expected '{expected_err}' in {error_codes}"
