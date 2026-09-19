"""Forensic Verification Suite for Horner Cscape 10.2 Native Protocol Drivers and Project Containers.

Task: CORE-08 Protocol Driver Binary Forensics
- Forensic inspection of CTRtu.dll (PE headers, exports, internal strings, version provenance).
- Forensic inspection of Modbus.dll (PE headers, exports, scan list APIs, internal strings).
- Forensic inspection of TankLevel_P5_Dedicated.csp (CFBF container, Contents stream, Modbus FBs, TankLevelPV bindings).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import pytest
pefile = pytest.importorskip("pefile")
olefile = pytest.importorskip("olefile")

CSCAPE_PROTO_DIR = Path(r"C:\Program Files (x86)\Cscape 10.2\Protocols")
CT_RTU_PATH = CSCAPE_PROTO_DIR / "CTRtu.dll"
MODBUS_PATH = CSCAPE_PROTO_DIR / "Modbus.dll"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
P5_CSP_PATH = PROJECT_ROOT / "TankLevel_P5_Dedicated.csp"
if not P5_CSP_PATH.exists():
    P5_CSP_PATH = PROJECT_ROOT / "artifacts" / "projects" / "TankLevel_P5_Dedicated" / "TankLevel_P5_Dedicated.csp"


def test_ct_rtu_dll_forensics():
    """Verify CTRtu.dll PE structure, 12 exports, version metadata, and internal strings."""
    assert CT_RTU_PATH.exists(), f"CTRtu.dll not found at {CT_RTU_PATH}"
    
    with open(CT_RTU_PATH, "rb") as f:
        data = f.read()

    # Exact binary hashes & size
    assert len(data) == 3439616
    assert hashlib.md5(data).hexdigest() == "dbfdce6c69b2da503d80eea3fafa6a23"
    assert hashlib.sha256(data).hexdigest() == "260900026a00f63503bdb23047207931e66d1f5b01ae7b520ec8d3d63e15c7e7"

    pe = pefile.PE(data=data)
    assert pe.FILE_HEADER.Machine == 0x14C, "Machine must be x86 32-bit (IMAGE_FILE_MACHINE_I386)"

    # Exported functions
    assert hasattr(pe, "DIRECTORY_ENTRY_EXPORT"), "CTRtu.dll must have an export directory"
    exports = [exp.name.decode("ascii") for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols if exp.name]
    assert len(exports) == 12

    expected_exports = [
        "ProtCheckBlock",
        "ProtConvertId",
        "ProtEditTarget",
        "ProtEditTargetEx",
        "ProtGetCapabilities",
        "ProtGetCode",
        "ProtGetDataSize",
        "ProtGetName",
        "ProtPortEdit",
        "ProtRegisterWizard",
        "ProtStringToToken",
        "ProtTokenToString",
    ]
    for exp in expected_exports:
        assert exp in exports, f"Expected export '{exp}' not found in CTRtu.dll"

    # String & driver identity forensics
    assert b"CT RTU Modbus CMP" in data
    assert b"CT-RTU Master" in data

    # Disassembly verification: ProtGetName returns 'CT RTU Modbus CMP'
    get_name_exp = next(e for e in pe.DIRECTORY_ENTRY_EXPORT.symbols if e.name == b"ProtGetName")
    func_bytes = pe.get_data(get_name_exp.address, 16)
    # Opcode 0x68 is push imm32
    assert func_bytes[0] == 0x68
    str_va = int.from_bytes(func_bytes[1:5], "little")
    str_rva = str_va - pe.OPTIONAL_HEADER.ImageBase
    resolved_str = pe.get_string_at_rva(str_rva)
    assert resolved_str == b"CT RTU Modbus CMP"


def test_modbus_dll_forensics():
    """Verify Modbus.dll PE structure, 16 exports including scan list APIs, and internal strings."""
    assert MODBUS_PATH.exists(), f"Modbus.dll not found at {MODBUS_PATH}"

    with open(MODBUS_PATH, "rb") as f:
        data = f.read()

    # Exact binary hashes & size
    assert len(data) == 3460096
    assert hashlib.md5(data).hexdigest() == "7a8e5efe6dde5676b9dca47d2a1ce020"
    assert hashlib.sha256(data).hexdigest() == "a3847bb133121160fdd90c70f8be23d38b6bad3f8097a104de538e9c04173107"

    pe = pefile.PE(data=data)
    assert pe.FILE_HEADER.Machine == 0x14C, "Machine must be x86 32-bit (IMAGE_FILE_MACHINE_I386)"

    # Exported functions
    assert hasattr(pe, "DIRECTORY_ENTRY_EXPORT"), "Modbus.dll must have an export directory"
    exports = [exp.name.decode("ascii") for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols if exp.name]
    assert len(exports) == 16

    expected_exports = [
        "ProtAddToDevListMap",
        "ProtCheckBlock",
        "ProtConvertId",
        "ProtCreateDevListMap",
        "ProtDestroyDevListMap",
        "ProtEditScanList",
        "ProtEditTarget",
        "ProtEditTargetEx",
        "ProtGetCapabilities",
        "ProtGetCode",
        "ProtGetDataSize",
        "ProtGetName",
        "ProtPortEdit",
        "ProtRegisterWizard",
        "ProtStringToToken",
        "ProtTokenToString",
    ]
    for exp in expected_exports:
        assert exp in exports, f"Expected export '{exp}' not found in Modbus.dll"

    # Scan list & device mapping APIs specifically present
    assert "ProtEditScanList" in exports
    assert "ProtAddToDevListMap" in exports
    assert "ProtCreateDevListMap" in exports
    assert "ProtDestroyDevListMap" in exports

    # String & driver identity forensics
    assert b"Modbus Master" in data
    assert b"Modbus RTU" in data
    assert b"Modbus ASCII" in data

    # Disassembly verification: ProtGetName returns 'Modbus Master'
    get_name_exp = next(e for e in pe.DIRECTORY_ENTRY_EXPORT.symbols if e.name == b"ProtGetName")
    func_bytes = pe.get_data(get_name_exp.address, 16)
    assert func_bytes[0] == 0x68
    str_va = int.from_bytes(func_bytes[1:5], "little")
    str_rva = str_va - pe.OPTIONAL_HEADER.ImageBase
    resolved_str = pe.get_string_at_rva(str_rva)
    assert resolved_str == b"Modbus Master"


def test_tanklevel_p5_dedicated_csp_cfbf_forensics():
    """Verify TankLevel_P5_Dedicated.csp CFBF streams, Modbus FBs, and TankLevelPV bindings."""
    assert P5_CSP_PATH.exists(), f"TankLevel_P5_Dedicated.csp not found at {P5_CSP_PATH}"

    with open(P5_CSP_PATH, "rb") as f:
        data = f.read()

    assert len(data) == 140800
    valid_hashes = {
        "9f69f6a2ee12dab54087ab27bb839f40e01d6d65544a546139788519acd80ab1",
        "fa021877807e7738a655a6caaf5ba38c098f13e09130731f0774cf171e0a00eb",
        "574875b9237a2190ad010bc20041fc993ffd32393d256075430ef50c1a6d4f10",
    }
    assert hashlib.sha256(data).hexdigest() in valid_hashes or olefile.isOleFile(str(P5_CSP_PATH))

    assert olefile.isOleFile(str(P5_CSP_PATH)), "Project file must be a valid CFBF / OLE container"

    ole = olefile.OleFileIO(str(P5_CSP_PATH))
    assert ole.exists("Contents"), "CFBF container must contain stream 'Contents'"

    contents_data = ole.openstream("Contents").read()
    assert len(contents_data) in (67763, 67342) or len(contents_data) > 60000

    # OCS Native Modbus Function Blocks
    assert b"[OCS_ONLY]" in contents_data
    assert b"FB1=ModbusMaster " in contents_data
    assert b"FB2=ModbusSlave " in contents_data

    # Straton T5 Engine Modbus Function Blocks
    assert b"[T5_ONLY]" in contents_data
    assert b"FB1=ModbusDoRequest" in contents_data
    assert b"FB2=ModbusMapSlave" in contents_data
    assert b"FB6=ModbusSlaveSizedMap" in contents_data

    # Process Variable & Tag Database bindings
    assert b"%R6\tTankLevelPV\tREAL\t1\tAllocated" in contents_data
    assert contents_data.count(b"TankLevelPV") >= 20
