#!/usr/bin/env python3
r"""
Test Suite for Step 139: Multi-POU CFBF Project Envelope and POU Insertion Verification.

Verifies:
1. Active Cscape GUI health and liveness gate.
2. Authentic CFBF OLE2 envelope inspection on TankLevelClosedLoop.csp and reg_min.csp.
3. Stream extraction ('Contents') and synthetic CFBF generation with Horner markers.
4. MCP tool `cscape_open_project` on valid, corrupted, empty, and nonexistent project files.
5. MCP tools `cscape_insert_st` and `cscape_insert_st_pou` across all 3 IEC 61131-3 POU types:
   - PROGRAM
   - FUNCTION_BLOCK
   - FUNCTION
6. Exact SHA-256 code hash computation and file persistence in pous/.
7. Strict fail-closed rejection of ladder logic constructs (contacts, coils, rungs, rails)
   with ERR_LADDER_FORBIDDEN.
8. Precision syntax error detection with structured failure locations (line, column, message).
9. Security and hardware download lockout enforcement and zero Straton legacy dependencies.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import tempfile
import psutil
import pytest
import sys

# Prepend paths safely before any src.* imports
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()

for r in [str(HORNER_ROOT), str(USER_ROOT)]:
    if r not in sys.path:
        sys.path.insert(0, r)

from src.cscape.gate import assert_cscape_live, get_gate_status
from src.cscape.cfbf import (
    CFBF_MAGIC,
    CSCAPE_CONTENTS_MAGIC,
    ProjectFileInfo,
    inspect_project_file,
    extract_cfbf_streams,
    generate_minimal_cfbf_bytes,
    parse_csp_contents_header,
)
from src.mcp.tools import (
    cscape_open_project,
    cscape_insert_st,
    cscape_insert_st_pou,
)
from src.cscape.st_inserter import (
    calculate_code_hash,
    POUType,
)
from src.cscape.safety import (
    ID_CONTROLLER_DOWNLOAD,
    ID_CONTROLLER_DOWNLOAD_ALT,
    intercept_download_command,
    CscapeSafetyViolationError,
)

TANK_LEVEL_CSP = USER_ROOT / "artifacts" / "projects" / "TankLevelClosedLoop" / "TankLevelClosedLoop.csp"
REG_MIN_CANDIDATES = [
    HORNER_ROOT / "artifacts" / "projects" / "reg_min.csp",
    HORNER_ROOT / "fixtures" / "cscape_native_samples" / "reg_min.csp",
]
STRATON_BINARIES = ["k5bus.exe", "k5edit.exe", "k5run.exe", "k5vm.exe", "k5cmd.exe", "t5.exe"]


def _get_reg_min_path() -> Path:
    for candidate in REG_MIN_CANDIDATES:
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    pytest.skip("reg_min.csp not found in fixtures or artifacts.")


# ============================================================================
# 1. Cscape Live Gate & Process Health
# ============================================================================

def test_01_cscape_live_gate_precheck():
    """Verifies that the live Cscape GUI is healthy and responsive."""
    try:
        gate = assert_cscape_live()
    except Exception as exc:
        pytest.skip(f"No active live Cscape gate: {exc}")
    assert gate["ready_for_tests"] is True, f"Gate not ready: {gate}"
    live_pid = gate.get("pid")
    assert live_pid is not None and live_pid > 0, f"Unexpected PID: {live_pid}"
    assert "TankLevelClosedLoop" in gate.get("window_title", "")
    assert psutil.pid_exists(live_pid), f"PID {live_pid} does not exist in OS"


# ============================================================================
# 2. CFBF Project Envelope Inspection
# ============================================================================

def test_02_cfbf_envelope_inspection_tank_level():
    """Inspects TankLevelClosedLoop.csp for OLE2 magic, sector size, version, and streams."""
    assert TANK_LEVEL_CSP.exists(), f"Missing TankLevelClosedLoop.csp at {TANK_LEVEL_CSP}"
    info = inspect_project_file(TANK_LEVEL_CSP)

    assert isinstance(info, ProjectFileInfo)
    assert info.is_valid_cfbf is True
    assert info.magic_hex.lower() == "d0cf11e0a1b11ae1"
    assert info.sector_size == 512
    assert info.dir_sector >= 0
    assert info.file_size_bytes > 0
    assert info.has_contents_stream is True

    # Check streams
    stream_names = [s["name"] for s in info.stream_entries]
    assert "Contents" in stream_names
    assert "Root Entry" in stream_names

    # Check Cscape version
    assert info.cscape_version == "10.2.751.4"


def test_03_cfbf_envelope_inspection_reg_min():
    """Inspects reg_min.csp for valid CFBF magic, sector size, and legacy version."""
    reg_path = _get_reg_min_path()
    info = inspect_project_file(reg_path)

    assert info.is_valid_cfbf is True
    assert info.magic_hex.lower() == "d0cf11e0a1b11ae1"
    assert info.sector_size == 512
    assert info.file_size_bytes == 5120
    assert info.has_contents_stream is True

    stream_names = [s["name"] for s in info.stream_entries]
    assert "Contents" in stream_names

    # Cscape legacy version 3.02 (build 1)
    assert info.cscape_version == "3.02 (build 1)"


# ============================================================================
# 3. CFBF Stream Extraction & Synthetic Generation
# ============================================================================

def test_04_cfbf_stream_extraction_contents():
    """Extracts streams from TankLevelClosedLoop.csp and parses the Contents header."""
    streams = extract_cfbf_streams(TANK_LEVEL_CSP)
    assert "Contents" in streams, "Expected 'Contents' stream in TankLevelClosedLoop.csp"

    contents_bytes = streams["Contents"]
    assert len(contents_bytes) > 12, "Contents stream too small for Cscape header"

    hdr = parse_csp_contents_header(contents_bytes)
    assert hdr["valid"] is True, f"Header parsing failed: {hdr.get('error')}"
    assert hdr["magic"] == CSCAPE_CONTENTS_MAGIC
    assert hdr["header_type"] == "modern_unicode"
    assert hdr["cscape_version"] == "10.2.751.4"


def test_05_cfbf_synthetic_generation_and_roundtrip():
    """Synthesizes minimal CFBF project bytes and verifies structural validity."""
    proj_name = "SynthEnvelopeTest"
    cscape_ver = "10.2.751.4"
    data = generate_minimal_cfbf_bytes(project_name=proj_name, cscape_version=cscape_ver)

    assert data[:8] == CFBF_MAGIC
    assert len(data) % 512 == 0
    assert len(data) >= 2048

    with tempfile.TemporaryDirectory() as tmpdir:
        synth_file = Path(tmpdir) / f"{proj_name}.csp"
        synth_file.write_bytes(data)

        info = inspect_project_file(synth_file)
        assert info.is_valid_cfbf is True
        assert info.sector_size == 512
        assert info.cscape_version == cscape_ver
        assert info.has_contents_stream is True

        streams = [s["name"] for s in info.stream_entries]
        assert "Root Entry" in streams
        assert "Contents" in streams


# ============================================================================
# 4. MCP Tool `cscape_open_project`
# ============================================================================

def test_06_cscape_open_project_valid_cfbf():
    """Verifies cscape_open_project on authentic TankLevelClosedLoop and reg_min files."""
    # Test TankLevelClosedLoop
    res_tank = cscape_open_project(str(TANK_LEVEL_CSP))
    assert res_tank["success"] is True
    assert res_tank["is_valid_cfbf"] is True
    assert res_tank["file_size_bytes"] > 0
    assert "Contents" in res_tank["stream_entries"]
    assert res_tank["cscape_version"] == "10.2.751.4"

    # Test reg_min
    reg_path = _get_reg_min_path()
    res_reg = cscape_open_project(str(reg_path))
    assert res_reg["success"] is True
    assert res_reg["is_valid_cfbf"] is True
    assert res_reg["file_size_bytes"] == 5120
    assert "Contents" in res_reg["stream_entries"]
    assert res_reg["cscape_version"] == "3.02 (build 1)"


def test_07_cscape_open_project_fail_closed_corrupted():
    """Verifies cscape_open_project fails closed on corrupted magic."""
    with tempfile.TemporaryDirectory() as tmpdir:
        corrupt_file = Path(tmpdir) / "corrupt_magic.csp"
        corrupt_file.write_bytes(b"INVALID_HEADER_MAGIC_BYTES_CORRUPTED_STREAM")

        res = cscape_open_project(str(corrupt_file))
        assert res["success"] is False
        assert res["is_valid_cfbf"] is False
        assert "not a valid Cscape Compound File" in res["message"]


def test_08_cscape_open_project_fail_closed_empty():
    """Verifies cscape_open_project fails closed on a 0-byte file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        empty_file = Path(tmpdir) / "empty_project.csp"
        empty_file.touch()

        res = cscape_open_project(str(empty_file))
        assert res["success"] is False
        assert res["is_valid_cfbf"] is False
        assert res["file_size_bytes"] == 0
        assert "empty" in res["message"].lower()


def test_09_cscape_open_project_fail_closed_nonexistent():
    """Verifies cscape_open_project fails closed on nonexistent file path."""
    fake_path = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\nonexistent_proj_xyz.csp")
    res = cscape_open_project(str(fake_path))
    assert res["success"] is False
    assert res["is_valid_cfbf"] is False
    assert "does not exist" in res["message"]


# ============================================================================
# 5. MCP Tool `cscape_insert_st_pou` & `cscape_insert_st` Across POU Types
# ============================================================================

def test_10_cscape_insert_st_program_pou():
    """Verifies valid ST insertion for PROGRAM POU with exact SHA-256 and persistence."""
    prog_code = """PROGRAM MainProgram
VAR
    bSystemRunning : BOOL;
    nHeartbeat : INT;
END_VAR
    bSystemRunning := TRUE;
    nHeartbeat := nHeartbeat + 1;
END_PROGRAM"""

    with tempfile.TemporaryDirectory() as tmpdir:
        res = cscape_insert_st_pou(
            project_path=tmpdir,
            pou_name="MainProgram",
            st_code=prog_code,
            pou_type="PROGRAM",
        )

        assert res["success"] is True
        assert res["syntax_valid"] is True
        assert res["pou_name"] == "MainProgram"
        assert res["pou_type"] == "PROGRAM"

        expected_hash = calculate_code_hash(prog_code)
        assert res["code_hash"] == expected_hash

        pou_file = Path(tmpdir) / "pous" / "MainProgram.st"
        assert pou_file.exists(), "POU file was not written to pous/"
        assert pou_file.read_text(encoding="utf-8") == prog_code


def test_11_cscape_insert_st_function_block_pou():
    """Verifies valid ST insertion for FUNCTION_BLOCK POU with inputs, outputs, and logic."""
    fb_code = """FUNCTION_BLOCK FB_PumpController
VAR_INPUT
    bStartCmd : BOOL;
    bStopCmd : BOOL;
    rFlowRate : REAL;
END_VAR
VAR_OUTPUT
    bPumpRunning : BOOL;
    bFault : BOOL;
END_VAR
    IF bStopCmd THEN
        bPumpRunning := FALSE;
    ELSIF bStartCmd THEN
        IF rFlowRate < 0.0 THEN
            bFault := TRUE;
            bPumpRunning := FALSE;
        ELSE
            bFault := FALSE;
            bPumpRunning := TRUE;
        END_IF;
    END_IF;
END_FUNCTION_BLOCK"""

    with tempfile.TemporaryDirectory() as tmpdir:
        res = cscape_insert_st_pou(
            project_path=tmpdir,
            pou_name="FB_PumpController",
            st_code=fb_code,
            pou_type="FUNCTION_BLOCK",
        )

        assert res["success"] is True
        assert res["syntax_valid"] is True
        assert res["pou_name"] == "FB_PumpController"
        assert res["pou_type"] == "FUNCTION_BLOCK"

        expected_hash = calculate_code_hash(fb_code)
        assert res["code_hash"] == expected_hash

        pou_file = Path(tmpdir) / "pous" / "FB_PumpController.st"
        assert pou_file.exists()
        assert pou_file.read_text(encoding="utf-8") == fb_code


def test_12_cscape_insert_st_function_pou():
    """Verifies valid ST insertion for FUNCTION POU with return value calculation."""
    fn_code = """FUNCTION F_ScaleAnalog : REAL
VAR_INPUT
    nRawInput : INT;
    rMinVal : REAL;
    rMaxVal : REAL;
END_VAR
VAR
    rFraction : REAL;
END_VAR
    rFraction := INT_TO_REAL(nRawInput) / 32767.0;
    F_ScaleAnalog := rMinVal + (rFraction * (rMaxVal - rMinVal));
END_FUNCTION"""

    with tempfile.TemporaryDirectory() as tmpdir:
        res = cscape_insert_st_pou(
            project_path=tmpdir,
            pou_name="F_ScaleAnalog",
            st_code=fn_code,
            pou_type="FUNCTION",
        )

        assert res["success"] is True
        assert res["syntax_valid"] is True
        assert res["pou_name"] == "F_ScaleAnalog"
        assert res["pou_type"] == "FUNCTION"

        expected_hash = calculate_code_hash(fn_code)
        assert res["code_hash"] == expected_hash

        pou_file = Path(tmpdir) / "pous" / "F_ScaleAnalog.st"
        assert pou_file.exists()
        assert pou_file.read_text(encoding="utf-8") == fn_code


def test_13_cscape_insert_multi_pou_directory_envelope():
    """Verifies multi-POU coexistence in a single project envelope with zero cross-talk."""
    pou_specs = [
        ("ProgAlpha", "PROGRAM", "PROGRAM ProgAlpha\nVAR\n    x : INT;\nEND_VAR\n    x := 100;\nEND_PROGRAM"),
        ("FB_Beta", "FUNCTION_BLOCK", "FUNCTION_BLOCK FB_Beta\nVAR_INPUT\n    in : BOOL;\nEND_VAR\nVAR_OUTPUT\n    out : BOOL;\nEND_VAR\n    out := in;\nEND_FUNCTION_BLOCK"),
        ("F_Gamma", "FUNCTION", "FUNCTION F_Gamma : INT\nVAR_INPUT\n    val : INT;\nEND_VAR\n    F_Gamma := val * 2;\nEND_FUNCTION"),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        for name, p_type, code in pou_specs:
            res = cscape_insert_st(
                pou_name=name,
                pou_type=p_type,
                st_code=code,
                project_path=tmpdir,
            )
            assert res["success"] is True
            assert res["code_hash"] == calculate_code_hash(code)

        pous_dir = Path(tmpdir) / "pous"
        assert pous_dir.exists()
        files = sorted([f.name for f in pous_dir.glob("*.st")])
        assert files == ["FB_Beta.st", "F_Gamma.st", "ProgAlpha.st"]

        # Verify exact individual code contents
        for name, _, code in pou_specs:
            saved_code = (pous_dir / f"{name}.st").read_text(encoding="utf-8")
            assert saved_code == code


# ============================================================================
# 6. Fail-Closed Rejection of Ladder Logic Constructs
# ============================================================================

def test_14_ladder_rejection_contacts_and_coils():
    """Verifies fail-closed rejection of ladder contacts --[ ]-- and coils --( )--."""
    ladder_code_contacts_coils = """PROGRAM BadLadderPOU
VAR
    bStart : BOOL;
    bMotor : BOOL;
END_VAR
    --[ bStart ]--( bMotor )--
END_PROGRAM"""

    with tempfile.TemporaryDirectory() as tmpdir:
        res = cscape_insert_st(
            pou_name="BadLadderPOU",
            pou_type="PROGRAM",
            st_code=ladder_code_contacts_coils,
            project_path=tmpdir,
        )

        assert res["success"] is False
        assert res["syntax_valid"] is False
        assert "ERR_LADDER_FORBIDDEN" in [loc["error_code"] for loc in res["failure_locations"]]
        assert any("Normally open contact symbol detected" in loc["message"] or "Normal output coil symbol" in loc["message"] for loc in res["failure_locations"])

        # Ensure NO file is written to disk
        pou_file = Path(tmpdir) / "pous" / "BadLadderPOU.st"
        assert not pou_file.exists(), "Forbidden ladder code was written to disk!"


def test_15_ladder_rejection_rungs_and_power_rails():
    """Verifies fail-closed rejection of RUNG markers and mnemonic ladder instructions."""
    ladder_code_rungs = """PROGRAM BadRungPOU
VAR
    x : BOOL;
END_VAR
    RUNG 1: Motor Control Logic
    x := TRUE;
END_PROGRAM"""

    ladder_code_mnemonics = """PROGRAM BadMnemonicPOU
VAR
    a : BOOL;
    b : BOOL;
END_VAR
    XIC(a) OTE(b);
END_PROGRAM"""

    with tempfile.TemporaryDirectory() as tmpdir:
        for name, code in [("BadRungPOU", ladder_code_rungs), ("BadMnemonicPOU", ladder_code_mnemonics)]:
            res = cscape_insert_st(
                pou_name=name,
                pou_type="PROGRAM",
                st_code=code,
                project_path=tmpdir,
            )

            assert res["success"] is False
            assert res["syntax_valid"] is False
            assert "ERR_LADDER_FORBIDDEN" in [loc["error_code"] for loc in res["failure_locations"]]

            # Ensure zero file persistence
            assert not (Path(tmpdir) / "pous" / f"{name}.st").exists()


# ============================================================================
# 7. Structured Syntax Error Locations
# ============================================================================

def test_16_syntax_error_failure_location_precision():
    """Verifies that Structured Text syntax errors produce exact line/col failure locations."""
    bad_syntax_code = """PROGRAM BadSyntaxPOU
VAR
    nVal : INT;
END_VAR
    nVal := ;
END_PROGRAM"""

    with tempfile.TemporaryDirectory() as tmpdir:
        res = cscape_insert_st(
            pou_name="BadSyntaxPOU",
            pou_type="PROGRAM",
            st_code=bad_syntax_code,
            project_path=tmpdir,
        )

        assert res["success"] is False
        assert res["syntax_valid"] is False
        assert len(res["failure_locations"]) >= 1

        loc = res["failure_locations"][0]
        assert loc["file_path"] == "BadSyntaxPOU.st"
        assert loc["line"] == 5
        assert loc["column"] == 13
        assert loc["error_code"] == "ST_SYNTAX_ERROR"
        assert "SEMICOLON" in loc["message"]

        # Ensure no file written
        assert not (Path(tmpdir) / "pous" / "BadSyntaxPOU.st").exists()


# ============================================================================
# 8. Security & Hardware Lockout Verification
# ============================================================================

def test_17_cscape_safety_hardware_lockout_and_straton_quarantine():
    """Verifies that controller downloads remain blocked and no Straton processes run."""
    # 1. Hardware download lockout
    with pytest.raises(CscapeSafetyViolationError):
        intercept_download_command(ID_CONTROLLER_DOWNLOAD)

    with pytest.raises(CscapeSafetyViolationError):
        intercept_download_command(ID_CONTROLLER_DOWNLOAD_ALT)

    # 2. Zero Straton processes
    for proc in psutil.process_iter(["name"]):
        try:
            name = (proc.info["name"] or "").lower()
            assert name not in STRATON_BINARIES, f"Straton binary detected running: {name}"
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # 3. GUI PID is alive and not hung
    gate = get_gate_status()
    live_pid = gate.get("pid")
    if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
        pytest.skip(f"No active live Cscape gate (PID {live_pid})")
    assert psutil.pid_exists(live_pid), f"Cscape PID {live_pid} not running"
    user32 = ctypes.windll.user32
    gate = get_gate_status()
    raw_h = gate.get("hwnd")
    if raw_h:
        hwnd = int(raw_h, 0) if isinstance(raw_h, str) else int(raw_h)
        if hasattr(user32, "IsHungAppWindow"):
            assert not user32.IsHungAppWindow(hwnd), f"Cscape window {hex(hwnd)} is hung!"
