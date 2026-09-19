"""Test Suite for Industrial IEC 61131-3 Structured Text Applications Library.

Verifies:
- All POUs in examples/st_applications/ and fixtures/st_programs/
- Strict compliance with IEC 61131-3 Structured Text standard
- Strict enforcement of pure Structured Text (zero ladder artifacts)
- Validation across STParser, IECValidator, and STValidator
"""

import os
from pathlib import Path
import pytest

from src.iec.st_parser import STParser, POUKind
from src.iec.validator import IECValidator
from src.validation.validator import STValidator

REPO_ROOT = Path(__file__).resolve().parent.parent
APPLICATIONS_DIR = REPO_ROOT / "examples" / "st_applications"
PROGRAMS_DIR = REPO_ROOT / "fixtures" / "st_programs"

APPLICATION_FILES = [
    "lead_lag_pump_controller.st",
    "pid_temperature_controller.st",
    "conveyor_sorting_state_machine.st",
    "analog_scaling_bounds.st",
    "valve_actuator_controller.st",
    "first_fault_annunciator.st",
    "flow_totalizer_integrator.st",
    "ramp_rate_limiter.st",
]

PROGRAM_FILES = [
    "pump_alternation_program.st",
    "pid_temp_control_program.st",
    "conveyor_sorter_program.st",
    "analog_scaling_program.st",
    "batch_reactor_program.st",
    "traffic_control_program.st",
]


class TestSTApplicationsLibrary:
    """Verifies production-grade industrial applications in examples/st_applications/."""

    @pytest.mark.parametrize("filename", APPLICATION_FILES)
    def test_application_file_exists(self, filename: str):
        filepath = APPLICATIONS_DIR / filename
        assert filepath.exists(), f"Application file missing: {filepath}"
        assert filepath.stat().st_size > 0, f"Application file empty: {filepath}"

    @pytest.mark.parametrize("filename", APPLICATION_FILES)
    def test_application_pure_st_no_ladder(self, filename: str):
        filepath = APPLICATIONS_DIR / filename
        code = filepath.read_text(encoding="utf-8")
        ladder_issues = IECValidator.check_ladder_artifacts(code)
        assert len(ladder_issues) == 0, f"Ladder artifacts found in {filename}: {ladder_issues}"

    @pytest.mark.parametrize("filename", APPLICATION_FILES)
    def test_application_block_nesting(self, filename: str):
        filepath = APPLICATIONS_DIR / filename
        code = filepath.read_text(encoding="utf-8")
        nesting_issues = IECValidator.check_block_nesting(code)
        assert len(nesting_issues) == 0, f"Nesting issues in {filename}: {nesting_issues}"

    @pytest.mark.parametrize("filename", APPLICATION_FILES)
    def test_application_st_parser_validation(self, filename: str):
        filepath = APPLICATIONS_DIR / filename
        code = filepath.read_text(encoding="utf-8")
        result = STParser.validate(code)
        assert result.is_valid is True, f"STParser validation failed for {filename}: {result.errors}"
        assert len(result.errors) == 0
        assert len(result.pous) >= 1
        pou = result.pous[0]
        assert pou.kind == POUKind.FUNCTION_BLOCK
        assert len(pou.variables) > 0

    @pytest.mark.parametrize("filename", APPLICATION_FILES)
    def test_application_st_validator_ast(self, filename: str):
        filepath = APPLICATIONS_DIR / filename
        code = filepath.read_text(encoding="utf-8")
        validator = STValidator()
        result = validator.validate(code)
        assert result.is_valid is True, f"STValidator failed for {filename}: {result.errors}"
        assert len(result.errors) == 0


class TestSTProgramsFixtures:
    """Verifies benchmark and test programs in fixtures/st_programs/."""

    @pytest.mark.parametrize("filename", PROGRAM_FILES)
    def test_program_file_exists(self, filename: str):
        filepath = PROGRAMS_DIR / filename
        assert filepath.exists(), f"Program fixture missing: {filepath}"
        assert filepath.stat().st_size > 0, f"Program fixture empty: {filepath}"

    @pytest.mark.parametrize("filename", PROGRAM_FILES)
    def test_program_pure_st_no_ladder(self, filename: str):
        filepath = PROGRAMS_DIR / filename
        code = filepath.read_text(encoding="utf-8")
        ladder_issues = IECValidator.check_ladder_artifacts(code)
        assert len(ladder_issues) == 0, f"Ladder artifacts found in {filename}: {ladder_issues}"

    @pytest.mark.parametrize("filename", PROGRAM_FILES)
    def test_program_block_nesting(self, filename: str):
        filepath = PROGRAMS_DIR / filename
        code = filepath.read_text(encoding="utf-8")
        nesting_issues = IECValidator.check_block_nesting(code)
        assert len(nesting_issues) == 0, f"Nesting issues in {filename}: {nesting_issues}"

    @pytest.mark.parametrize("filename", PROGRAM_FILES)
    def test_program_st_parser_validation(self, filename: str):
        filepath = PROGRAMS_DIR / filename
        code = filepath.read_text(encoding="utf-8")
        result = STParser.validate(code)
        assert result.is_valid is True, f"STParser validation failed for {filename}: {result.errors}"
        assert len(result.errors) == 0
        assert len(result.pous) >= 1
        pou = result.pous[0]
        assert pou.kind == POUKind.PROGRAM
        assert len(pou.variables) > 0

    @pytest.mark.parametrize("filename", PROGRAM_FILES)
    def test_program_st_validator_ast(self, filename: str):
        filepath = PROGRAMS_DIR / filename
        code = filepath.read_text(encoding="utf-8")
        validator = STValidator()
        result = validator.validate(code)
        assert result.is_valid is True, f"STValidator failed for {filename}: {result.errors}"
        assert len(result.errors) == 0
