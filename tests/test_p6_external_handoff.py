"""Test Suite for Phase P6 External Handoff Project Opening and Verification."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import zipfile

from src.cscape.cfbf import is_valid_cfbf, extract_cfbf_streams
from src.iec.parser import Parser
from src.cscape.st_ld_interop import STLadderInteropGuard, LadderConstructRejectedError

HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
DELIVERY_ZIP = HORNER_ROOT / "artifacts" / "delivery" / "horner-cscape-project-handoff-v1.0.0.zip"
EXTERNAL_PUBLIC_DIR = Path(r"C:\Users\Public\HornerHandoffTest").resolve()


def test_p6_handoff_archive_exists():
    """Verify delivery archive exists and is non-empty."""
    assert DELIVERY_ZIP.exists()
    assert DELIVERY_ZIP.stat().st_size > 10000


def test_p6_handoff_archive_contents():
    """Verify handoff zip contains project, pous, modbus config, and docs."""
    with zipfile.ZipFile(DELIVERY_ZIP, "r") as zf:
        namelist = zf.namelist()
    
    assert any("TankLevel_P5_Dedicated.csp" in n for n in namelist)
    assert any("TankLevelControl.st" in n for n in namelist)
    assert any("modbus_pv_config.json" in n for n in namelist)
    assert any("modbus_protocol_inventory.json" in n for n in namelist)
    assert any("MANIFEST-SHA256.json" in n for n in namelist)
    assert any("TRANSFER_AND_OPEN_GUIDE.md" in n for n in namelist)


def test_p6_cfbf_container_validity():
    """Verify extracted .csp container is a valid CFBF / OLE2 file."""
    csp_file = EXTERNAL_PUBLIC_DIR / "projects" / "TankLevel_P5_Dedicated" / "TankLevel_P5_Dedicated.csp"
    if not csp_file.exists():
        pytest.skip("External public directory not yet extracted")
    assert is_valid_cfbf(csp_file)
    streams = extract_cfbf_streams(csp_file)
    assert len(streams) >= 1


def test_p6_pure_st_and_ast():
    """Verify extracted Structured Text code parses without errors or ladder constructs."""
    st_file = EXTERNAL_PUBLIC_DIR / "projects" / "TankLevel_P5_Dedicated" / "pous" / "TankLevelControl.st"
    if not st_file.exists():
        pytest.skip("External public directory not yet extracted")
    st_code = st_file.read_text(encoding="utf-8")
    STLadderInteropGuard.enforce_st_code(st_code)
    ast = Parser.from_source(st_code).parse()
    assert ast is not None
    assert ast.name == "TankLevelControl"
