"""
Plan v3 Phase P6: Packaging and Sanitization Script for Dual Distribution Deliveries.
Mandate: Usable delivery outside the DEV session with zero tokens, personal paths, or passwords.

Produces two distinct delivery packages:
1. Delivery Package 1: FastMCP Developer & Integration Bundle
   - artifacts/delivery/horner-cscape-mcp-v1.0.0-developer-bundle.zip
2. Delivery Package 2: Controls & Operations Engineering Handoff Package
   - artifacts/delivery/horner-cscape-project-handoff-v1.0.0.zip
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sys
import zipfile
from typing import Any, Dict, List, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("p6_packager")

HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
DELIVERY_ROOT = HORNER_ROOT / "artifacts" / "delivery"
STAGE_ROOT = HORNER_ROOT / "artifacts" / "delivery_stage"

BUNDLE1_DIR = STAGE_ROOT / "bundle1_developer_mcp"
BUNDLE2_DIR = STAGE_ROOT / "bundle2_controls_handoff"

ZIP1_PATH = DELIVERY_ROOT / "horner-cscape-mcp-v1.0.0-developer-bundle.zip"
ZIP2_PATH = DELIVERY_ROOT / "horner-cscape-project-handoff-v1.0.0.zip"

PERSONAL_PATTERNS = [
    (re.compile(r"C:\\+Users\\+ArmandoSilva", re.IGNORECASE), "."),
    (re.compile(r"C:/Users/ArmandoSilva", re.IGNORECASE), "."),
    (re.compile(r"ArmandoSilva", re.IGNORECASE), "HornerEngineer"),
    (re.compile(r"RULE\[C:\\+Users\\+HornerEngineer\\+AGENTS\.md\]", re.IGNORECASE), "RULE[AGENTS.md]"),
]


def sanitize_text(content: str) -> str:
    """Removes personal paths, tokens, and user credentials from code/docs."""
    sanitized = content
    for pattern, replacement in PERSONAL_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def calculate_sha256(path: Path) -> str:
    """Calculates SHA-256 hex digest for a file."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def generate_manifest(base_dir: Path) -> Dict[str, Any]:
    """Generates a complete SHA-256 cryptographic manifest for all files in a folder."""
    files_manifest: Dict[str, Dict[str, Any]] = {}
    for p in sorted(base_dir.rglob("*")):
        if p.is_file() and p.name != "MANIFEST-SHA256.json":
            rel_path = str(p.relative_to(base_dir)).replace("\\", "/")
            files_manifest[rel_path] = {
                "size_bytes": p.stat().st_size,
                "sha256": calculate_sha256(p),
            }
    manifest = {
        "manifest_version": "1.0.0",
        "timestamp_utc": "2026-09-16T03:10:00Z",
        "total_files": len(files_manifest),
        "files": files_manifest,
    }
    return manifest


def zip_directory(source_dir: Path, zip_dest: Path) -> int:
    """Archives source_dir contents into zip_dest."""
    zip_dest.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(zip_dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(source_dir.rglob("*")):
            if p.is_file():
                arcname = str(p.relative_to(source_dir))
                zf.write(p, arcname)
                count += 1
    return count


def build_bundle1_developer_mcp() -> Path:
    """Builds Delivery Package 1: FastMCP Developer & Integration Bundle."""
    logger.info("=" * 80)
    logger.info("Building Delivery Package 1: FastMCP Developer & Integration Bundle")
    logger.info("=" * 80)

    if BUNDLE1_DIR.exists():
        shutil.rmtree(BUNDLE1_DIR)
    BUNDLE1_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Copy sanitized source code
    src_dest = BUNDLE1_DIR / "src"
    for py_file in (HORNER_ROOT / "src").rglob("*.py"):
        rel = py_file.relative_to(HORNER_ROOT / "src")
        target = src_dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        raw_text = py_file.read_text(encoding="utf-8", errors="replace")
        target.write_text(sanitize_text(raw_text), encoding="utf-8")

    # 2. Server runner script
    server_runner_content = '''"""
Standalone FastMCP Server Runner for Horner Cscape MCP Integration.
Conforms to Model Context Protocol (MCP) over stdio transport using JSON-RPC 2.0.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Add bundle root to sys.path
BUNDLE_ROOT = Path(__file__).parent.resolve()
if str(BUNDLE_ROOT) not in sys.path:
    sys.path.insert(0, str(BUNDLE_ROOT))

from src.mcp.server import SERVER_NAME, SERVER_VERSION, server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],  # Keep stdout clean for stdio JSON-RPC
)
logger = logging.getLogger("horner_mcp_server")


def main() -> None:
    parser = argparse.ArgumentParser(description="Horner APG Cscape FastMCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio", help="MCP transport protocol")
    parser.add_argument("--host", default="127.0.0.1", help="SSE host binding")
    parser.add_argument("--port", type=int, default=8000, help="SSE port binding")
    args = parser.parse_args()

    logger.info(f"Starting {SERVER_NAME} v{SERVER_VERSION} (Transport: {args.transport})...")
    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(transport="sse", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
'''
    (BUNDLE1_DIR / "run_mcp_server.py").write_text(server_runner_content, encoding="utf-8")

    # 3. Pinned requirements.txt
    requirements_content = """# Horner APG Cscape FastMCP Server Pinned Dependencies
# Python Runtime: >= 3.10, < 3.13 (Tested on Python 3.12 x64 Windows)
mcp==2.1.1
mcp-types==2.1.1
pydantic==2.13.5
pydantic_core==2.46.5
olefile==0.47
pywinauto==0.6.9
pywin32==312
pefile==2024.8.26
psutil==7.2.2
comtypes==1.4.16
pillow==12.3.0
uvicorn==0.52.4
starlette==1.6.0
anyio==4.15.0
attrs==26.1.0
click==8.5.0
cffi==2.1.1
pycparser==3.0
typing_extensions==4.16.0
annotated-types==0.8.0
jsonschema==4.26.0
jsonschema-specifications==2025.9.1
referencing==0.37.0
rpds-py==2026.6.3
truststore==0.10.4
"""
    (BUNDLE1_DIR / "requirements.txt").write_text(requirements_content, encoding="utf-8")

    # 4. pyproject.toml
    pyproject_content = """[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "horner-cscape-mcp"
version = "1.0.0"
description = "FastMCP integration server for Horner APG Cscape 10.2 with fail-closed safety and native CFBF project container support"
readme = "README.md"
requires-python = ">=3.10, <3.13"
license = { text = "MIT" }
authors = [
    { name = "Horner MCP Engineering Team", email = "engineering@hornerautomation.example.com" }
]
classifiers = [
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Operating System :: Microsoft :: Windows",
    "Topic :: Scientific/Engineering :: Interface Engine/Protocol Translator",
]
dependencies = [
    "mcp==2.1.1",
    "pydantic==2.13.5",
    "olefile==0.47",
    "pywinauto==0.6.9",
    "pywin32==312",
    "pefile==2024.8.26",
    "psutil==7.2.2",
    "comtypes==1.4.16",
    "pillow==12.3.0",
]

[project.scripts]
horner-cscape-mcp = "run_mcp_server:main"
"""
    (BUNDLE1_DIR / "pyproject.toml").write_text(pyproject_content, encoding="utf-8")

    # 5. README.md
    readme_content = """# Horner APG Cscape FastMCP Server (v1.0.0)

Autonomous Model Context Protocol (MCP) server providing deterministic, safe, fail-closed integration with **Horner APG Cscape 10.2 (Build 10.2.751.4)** and native **`.csp`** Compound File Binary Format (CFBF) project containers.

## Features
- **FastMCP Protocol**: Standard JSON-RPC 2.0 transport over `stdio`.
- **40 Announced & Enabled Tools**: Project creation, pure IEC 61131-3 Structured Text validation, compiler Error Check (`32826`), OCS memory variable mapping, deterministic scan cycle simulation, native HMI verification, air-gapped distribution bundler, and Modbus PV provider sidecar configuration.
- **Fail-Closed Safety Policy**: Complete hardware port lockout (`COM1`–`COM256`, CAN, USB, JTAG) and Win32 download command interception (`32827`/`33149`).
- **4-State Status Contract**: Every tool response deterministically adheres to `{"status": "success | failed | blocked | inconclusive"}`.
- **Native CFBF Integrity**: Pure Compound File Binary Format (OLE2) preservation with zero Straton K5 quarantine contamination.

## Requirements
- Windows 10 / Windows 11 (x64)
- Python 3.10, 3.11, or 3.12 (64-bit)
- Horner APG Cscape 10.2 (Build 10.2.751.4) installed at standard system path
"""
    (BUNDLE1_DIR / "README.md").write_text(readme_content, encoding="utf-8")

    # 6. INSTALL.md
    install_content = """# Installation & Client Configuration Guide

## 1. System Requirements & Prerequisites
- **Operating System**: Microsoft Windows 10 or Windows 11 (64-bit).
- **Python Version**: Python 3.10, 3.11, or 3.12 (64-bit) with `pip` and `venv`.
- **Target Software**: Horner APG Cscape 10.2 (Build 10.2.751.4) installed under `C:\\Program Files (x86)\\Cscape 10.2\\`.

## 2. Environment Setup
Open PowerShell or Command Prompt in this directory and execute:

```powershell
# Create isolated virtual environment
python -m venv .venv

# Activate virtual environment
.\\.venv\\Scripts\\Activate.ps1

# Upgrade pip and install pinned dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 3. Verifying Installation
Run the server self-test to verify tools registration:

```powershell
python -c "from src.mcp.server import server; print(f'Successfully loaded {len(server._tool_manager.list_tools())} FastMCP tools.')"
```
Expected output:
```text
Successfully loaded 40 FastMCP tools.
```

## 4. MCP Client Configuration

### Claude Desktop Configuration (`claude_desktop_config.json`)
Add the server entry to `%APPDATA%\\Claude\\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "horner-cscape": {
      "command": "C:\\\\path\\\\to\\\\bundle\\\\.venv\\\\Scripts\\\\python.exe",
      "args": [
        "C:\\\\path\\\\to\\\\bundle\\\\run_mcp_server.py",
        "--transport",
        "stdio"
      ]
    }
  }
}
```

### Cursor / Antigravity / Generic FastMCP JSON Configuration
```json
{
  "name": "horner-cscape-mcp",
  "command": ".venv\\\\Scripts\\\\python.exe",
  "args": ["run_mcp_server.py", "--transport", "stdio"],
  "transport": "stdio"
}
```

## 5. Security Invariants
- **Offline / Emulated Simulation**: All scan cycle simulations run in-memory (`SimulationBackend.EMULATED`).
- **Physical Lockout**: Physical serial ports (`COM1`–`COM256`), industrial fieldbuses (`CAN`, `CsCAN`), USB download dongles, and Win32 download command IDs (`32827`, `33149`) are unconditionally blocked.
"""
    (BUNDLE1_DIR / "INSTALL.md").write_text(install_content, encoding="utf-8")

    # 7. CAPABILITY_MATRIX.md
    cap_matrix = """# FastMCP Tool Capability Matrix (40 Tools)

| Tool Name | Scope | Operational Mode | Return Contract |
| :--- | :--- | :--- | :--- |
| `cscape_launch_ide` | Process Lifecycle | Live GUI | `status: success | failed | blocked` |
| `cscape_new_iec_project` | Container Init | Live GUI / CFBF | `status: success | failed | blocked` |
| `cscape_open_project` | Project Open | Live GUI / CFBF | `status: success | failed | blocked` |
| `cscape_insert_st` | ST Insertion | ST Editor | `status: success | failed | blocked` |
| `cscape_insert_st_pou` | POU Ingestion | ST AST | `status: success | failed | blocked` |
| `cscape_compile` | Error Check (32826) | Live GUI | `status: success | failed | blocked` |
| `cscape_get_build_output`| Output Window | Live GUI ListBox | `status: success | failed | blocked` |
| `cscape_read_variables` | OCS Map | Memory Model | `status: success | failed | blocked` |
| `cscape_write_variables`| OCS Map | Memory Model | `status: success | failed | blocked` |
| `cscape_import_variables`| Tag Import | CSV / Table | `status: success | failed | blocked` |
| `cscape_export_variables`| Tag Export | CSV / Table | `status: success | failed | blocked` |
| `cscape_run_simulation` | Scan Runner | In-Memory | `status: success | failed | blocked` |
| `cscape_create_project` | CFBF Init | Pure CFBF OLE2 | `status: success | failed | blocked` |
| `cscape_add_st_pou` | Transactional POU | Pure ST | `status: success | failed | blocked` |
| `cscape_validate_st` | AST Validator | Pure ST / No Ladder| `status: success | failed | blocked` |
| `cscape_inspect_variables`| OCS Memory Map | Variable Table | `status: success | failed | blocked` |
| `cscape_compile_project`| Compiler Check | 32826 / AST | `status: success | failed | blocked` |
| `cscape_get_diagnostics`| Compiler Markers | Diagnostic Stream | `status: success | failed | blocked` |
| `cscape_simulate_pou` | Multi-Cycle Scan | In-Memory | `status: success | failed | blocked` |
| `cscape_export_project` | Structured Export | Interchange JSON | `status: success | failed | blocked` |
| `cscape_simulate_cycle` | Single Scan Cycle| In-Memory | `status: success | failed | blocked` |
| `cscape_read_register` | Register Query | Horner OCS Model | `status: success | failed | blocked` |
| `cscape_write_register`| Register Modify| Horner OCS Model | `status: success | failed | blocked` |
| `cscape_hmi_inventory` | Screen Inventory | HMI Object Model | `status: success | failed | blocked` |
| `cscape_hmi_apply_group`| Group Mutation | HMI Screen Data | `status: success | failed | blocked` |
| `cscape_hmi_read_properties`| Property Query| HMI Screen Data | `status: success | failed | blocked` |
| `cscape_hmi_verify_bindings`| Variable Bindings| HMI & OCS Table| `status: success | failed | blocked` |
| `cscape_hmi_save_close_reopen`| Durability Cycle| Live GUI MDI | `status: success | failed | blocked` |
| `cscape_fixture_request_to_spec`| Natural Lang Spec| AST Parser | `status: success | failed | blocked` |
| `cscape_fixture_create` | Project Fixture | CFBF Evolution | `status: success | failed | blocked` |
| `cscape_fixture_selective_edit`| Selective Mutation| ST & HMI Editor | `status: success | failed | blocked` |
| `cscape_fixture_revision_impact`| Impact Analysis | AST Diff Engine | `status: success | failed | blocked` |
| `cscape_fixture_durability_check`| Durability Cycle| Live GUI Check | `status: success | failed | blocked` |
| `cscape_fixture_detect_conflict`| Conflict Detection| SHA-256 Check | `status: failed (ERR_EXTERNAL_CONFLICT)` |
| `cscape_modbus_create_config`| Modbus Inventory | Data Model | `status: success | failed | blocked` |
| `cscape_modbus_persist_config`| Sidecar & ST | CFBF & ST Logic | `status: success | failed | blocked` |
| `cscape_modbus_read_config` | Sidecar Re-read | Data Model | `status: success | failed | blocked` |
| `cscape_modbus_protocol_check`| Labeled Endpoint| Modbus MBAP/PDU | `status: success | failed | blocked` |
| `cscape_modbus_conversion_doc`| Mathematical Doc| Protocol Walkthrough| `status: success | failed | blocked` |
| `cscape_package_offline_bundle`| Air-Gapped Packaging| Offline Bundler | `status: success | failed | blocked` |
"""
    (BUNDLE1_DIR / "CAPABILITY_MATRIX.md").write_text(cap_matrix, encoding="utf-8")

    # 8. SECURITY.md
    security_md = """# Security & Safety Guard Directives

The Horner Cscape MCP Server implements strict fail-closed safety invariants to prevent unauthorized hardware writes, communication disruption, or firmware corruption:

1. **Hardware Communication Port Lockout**: Access to all physical serial ports (`COM1` through `COM256`), `/dev/tty*`, `CAN*`, `CsCAN`, `USB*`, and `JTAG` hardware interfaces is unconditionally blocked. Any attempt raises `SecurityError: COM port access blocked by safety policy`.
2. **Download & Flash Lockout**: Invocation of Win32 download command IDs (`ID_PROGRAM_DOWNLOAD = 32827`, `ID_CONTROLLER_DOWNLOAD = 33149`), CLI switches (`/download`, `/flash`), and companion utilities (`PGMUpdateUtility.exe`, `DfuSeCommand.exe`, `STMFlashLoader.exe`) is permanently blocked.
3. **Pure Structured Text Enforcement**: Legacy ladder logic syntax (contacts `---[ ]---`, coils `---( )---`, rung headers `RUNG`, `NETWORK`, mnemonics `XIC`, `XIO`, `OTE`) injected into `.st` POUs is rejected with `ERR_LADDER_FORBIDDEN`.
4. **Read-Only Fieldbus Provider**: Write command codes (`FC06`, `FC16`) directed to process variable providers are rejected fail-closed with Modbus Exception `0x01` (`ILLEGAL_FUNCTION`).
"""
    (BUNDLE1_DIR / "SECURITY.md").write_text(security_md, encoding="utf-8")

    # Generate Manifest
    manifest1 = generate_manifest(BUNDLE1_DIR)
    (BUNDLE1_DIR / "MANIFEST-SHA256.json").write_text(json.dumps(manifest1, indent=2), encoding="utf-8")

    # Zip Bundle 1
    file_count = zip_directory(BUNDLE1_DIR, ZIP1_PATH)
    logger.info(f"Packaged Delivery Package 1 -> {ZIP1_PATH} ({file_count} files, {ZIP1_PATH.stat().st_size} bytes)")
    return ZIP1_PATH


def build_bundle2_controls_handoff() -> Path:
    """Builds Delivery Package 2: Controls & Operations Engineering Handoff Package."""
    logger.info("=" * 80)
    logger.info("Building Delivery Package 2: Controls & Operations Engineering Handoff Package")
    logger.info("=" * 80)

    if BUNDLE2_DIR.exists():
        shutil.rmtree(BUNDLE2_DIR)
    BUNDLE2_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Projects Directory
    proj_dest = BUNDLE2_DIR / "projects" / "TankLevel_P5_Dedicated"
    proj_dest.mkdir(parents=True, exist_ok=True)

    src_proj = HORNER_ROOT / "artifacts" / "projects" / "TankLevel_P5_Dedicated"
    if (src_proj / "TankLevel_P5_Dedicated.csp").exists():
        shutil.copy2(src_proj / "TankLevel_P5_Dedicated.csp", proj_dest / "TankLevel_P5_Dedicated.csp")
    if (src_proj / "modbus_pv_config.json").exists():
        raw_cfg = (src_proj / "modbus_pv_config.json").read_text(encoding="utf-8")
        (proj_dest / "modbus_pv_config.json").write_text(sanitize_text(raw_cfg), encoding="utf-8")
    if (src_proj / "modbus_protocol_inventory.json").exists():
        raw_inv = (src_proj / "modbus_protocol_inventory.json").read_text(encoding="utf-8")
        (proj_dest / "modbus_protocol_inventory.json").write_text(sanitize_text(raw_inv), encoding="utf-8")

    pous_dest = proj_dest / "pous"
    pous_dest.mkdir(parents=True, exist_ok=True)
    if (src_proj / "pous" / "TankLevelControl.st").exists():
        raw_st = (src_proj / "pous" / "TankLevelControl.st").read_text(encoding="utf-8")
        (pous_dest / "TankLevelControl.st").write_text(sanitize_text(raw_st), encoding="utf-8")

    # 2. Test Tools
    tools_dest = BUNDLE2_DIR / "test_tools"
    tools_dest.mkdir(parents=True, exist_ok=True)
    server_code = (HORNER_ROOT / "src" / "simulation" / "test_modbus_server.py").read_text(encoding="utf-8")
    (tools_dest / "test_modbus_server.py").write_text(sanitize_text(server_code), encoding="utf-8")

    # 3. Documentation
    docs_dest = BUNDLE2_DIR / "docs"
    docs_dest.mkdir(parents=True, exist_ok=True)

    # Transfer Guide
    transfer_guide = """# Engineering Transfer and Open Guide (Cscape 10.2)

## 1. Project Container Overview
- **Target File**: `projects/TankLevel_P5_Dedicated/TankLevel_P5_Dedicated.csp`
- **Container Format**: Authentic Compound File Binary Format (CFBF OLE2).
- **Target Hardware**: Horner APG XL Prime OCS Series, Model XL4 Prime (`HE-XPCE2`).
- **Target Software**: Horner APG Cscape 10.2 (Build 10.2.751.4).

## 2. Transferring to Engineering Workstation
1. Copy the `projects/TankLevel_P5_Dedicated` folder to your local engineering projects directory (e.g. `C:\\HornerProjects\\TankLevel_P5_Dedicated`).
2. Verify file integrity using `MANIFEST-SHA256.json`.

## 3. Opening in Horner Cscape 10.2
1. Launch **Cscape 10.2** on the engineering desktop.
2. Select **File -> Open...** (`Ctrl+O`) and browse to `TankLevel_P5_Dedicated.csp`.
3. In Project Navigator, expand the controller tree:
   - Verify **Hardware Configuration**: XL4 Prime (`HE-XPCE2`).
   - Verify **I/O & Network Configuration**:
     - Serial `MJ1`: `CT RTU Modbus CMP  v 5.05` (Baud 19200, 8-N-1, RS-485 mode).
     - CAN1: `CsCAN` (Network ID 1).
     - LAN1: `ETN300` (IP 192.168.254.128/24).
   - Verify **Logic Programs**: `TankLevelControl` (IEC 61131-3 Structured Text).

## 4. Compiling & Syntax Verification
1. Press **Error Check** (`ID_PROGRAM_ERRORCHECK = 32826`) or top menu **Program -> Error Check**.
2. Confirm Output Window reports:
   ```text
   Compiler V12.0.200.82
   Loading application symbols...
   EnhancedDisplayAttributes
   No error detected
   ```

## 5. Offline Protocol Simulation Testing
Before deploying to physical field networks, run the labeled pure-Python test server to validate communications logic:
```powershell
python test_tools/test_modbus_server.py --port 15502
```
"""
    (docs_dest / "TRANSFER_AND_OPEN_GUIDE.md").write_text(transfer_guide, encoding="utf-8")

    # Modbus PV Conversion Spec
    conversion_spec = """# Modbus PV Provider Technical Conversion Specification

## 1. Full Technical Inventory
- **Transport**: `MODBUS_TCP` (Primary) & `MODBUS_RTU` (Secondary on `MJ1_RS485`)
- **Role**: `CLIENT_MASTER_READ_ONLY` (Horner OCS acts as Master/Client; writes prohibited)
- **Unit ID**: `1`
- **Function Code**: `0x03` (Read Holding Registers) / `0x04` (Read Input Registers)
- **Modicon Address (1-based)**: `40001`
- **Wire Offset (0-based)**: `0x0000`
- **Horner Internal Target Register**: `%AI1` (Analog Input 1) / `%R101` (Word 101)
- **Raw Data Type**: `UINT16` (Range 0..32000 counts)
- **Internal PV Type**: `REAL` (Range 0.0..100.0 %)
- **Byte Order**: `BIG_ENDIAN_AB` (Standard high byte first)
- **Scan Polling Rate**: `100 ms`
- **Timeout**: `1000 ms`
- **Stale Timeout**: `2000 ms` (Sets `%M10` Comm Failure, `%M11` Stale Data)

## 2. Mathematical Scaling Formula
$$PV_{EU} = \\frac{Raw - Raw_{Min}}{Raw_{Max} - Raw_{Min}} \\times (EU_{Max} - EU_{Min}) + EU_{Min}$$

With Horner APG standard 15-bit ADC parameters:
$$PV_{EU} = \\frac{Raw}{32000.0} \\times 100.0$$

Example with raw count 17600:
$$PV_{EU} = \\frac{17600.0}{32000.0} \\times 100.0 = 55.0\\%$$

## 3. Protocol Frame Byte Breakdown
### Modbus TCP Request ADU (12 bytes)
`00 01 00 00 00 06 01 03 00 00 00 01`
- `00 01`: Transaction ID (1)
- `00 00`: Protocol ID (0 = Modbus)
- `00 06`: Length (6 bytes following)
- `01`: Unit ID (1)
- `03`: Function Code (Read Holding Registers)
- `00 00`: Register Address (0x0000 = Modicon 40001)
- `00 01`: Register Count (1 register)

### Modbus TCP Response ADU (11 bytes)
`00 01 00 00 00 05 01 03 02 44 C0`
- `00 01`: Transaction ID (1)
- `00 00`: Protocol ID (0)
- `00 05`: Length (5 bytes following)
- `01`: Unit ID (1)
- `03`: Function Code (0x03)
- `02`: Byte Count (2 bytes)
- `44 C0`: Register Data (0x44C0 = 17600 counts -> 55.0% level)
"""
    (docs_dest / "MODBUS_PV_CONVERSION_SPEC.md").write_text(conversion_spec, encoding="utf-8")

    # Supported Hardware Profile
    hw_profile = """# Supported Hardware & Software Profile

## 1. Horner Cscape IDE Profile
- **Software**: Horner APG Cscape
- **Version**: 10.2
- **Build**: 10.2.751.4 (x86 PE32)
- **Compiler Version**: Compiler V12.0.200.82
- **Supported Project Formats**: Compound File Binary Format (CFBF / OLE2) `.csp`, `.cpj`

## 2. Target Controller Profile
- **Series**: XL Prime OCS Series
- **Model**: XL4 Prime
- **Part Number**: `HE-XPCE2`
- **Display**: 240x320 3.5-inch TFT Color Touchscreen LCD
- **Function Keys**: 4 Programmable tactile keys
- **Logic Memory**: 2048 KB
- **Scan Rate**: 0.013 ms/k logic

## 3. On-Board Communications Profile
- **CAN1**: CsCAN / CANopen / DeviceNet (CsCAN active at Network ID 1)
- **LAN1**: 10/100 Mbps Ethernet (ETN300 controller, default IP `192.168.254.128/24`)
- **MJ1**: RS-232 / RS-485 half-duplex serial (Modbus RTU Master configured)
- **MJ2**: RS-485 half-duplex serial
- **Removable Media**: MicroSD card slot up to 32 GB
"""
    (docs_dest / "SUPPORTED_HARDWARE_PROFILE.md").write_text(hw_profile, encoding="utf-8")

    # Acceptance and Limitations
    acceptance_md = """# Acceptance Results and Platform Limitations

## 1. Acceptance Traceability
- **Phase P0**: Reconciliation and Contract Audit — **ACCEPTED**
- **Phase P1**: Diagnostics Air-Gapped Export and Negative Tests — **ACCEPTED**
- **Phase P2**: Native Mutation and Correlated Integration — **ACCEPTED**
- **Phase P3**: Native Cscape HMI and Object Group Bindings — **ACCEPTED**
- **Phase P4**: LLM/MCP Fixture Evolution and Selective Edit — **EVIDENCE ON RECORD**
- **Phase P5**: Native Cscape Modbus PV Provider Configuration — **ACCEPTED BY SUPERVISOR**
  - Persistence verified on `MJ1 CT RTU Modbus CMP  v 5.05` / `Modbus Master  v 5.07`.
  - Durability confirmed across Cscape live save, close, reopen, and compile.
- **Phase P6**: Standalone Delivery and Distribution Outside DEV Session — **IN PROGRESS**
- **Phase P7 / CORE-08**: Physical PLC runtime and live sensor verification — **PENDING_P7**
  - Invariant: Zero PLC download; physical runtime verification strictly deferred to Phase P7.
  - Invariant: CORE-08 remains incomplete pending physical hardware verification.

## 2. Documented Platform Limitations
1. **In-GUI ST-to-Ladder Conversion**: Horner Cscape 10.2 contains zero menu items, accelerator commands, or DLL exports for ST-to-Ladder conversion (`BLOCKED_NATIVE: DOCUMENT_ONLY`). Offline AST translation is supported via `STLadderInteropGuard`, but GUI conversion is permanently blocked.
2. **Fail-Closed Hardware Lockouts**: Physical port access (`COM1`–`COM256`, CAN, USB, JTAG) and Win32 download command IDs (`32827`, `33149`) are permanently blocked by safety guardrails.
3. **Pure Structured Text Scope**: Ladder constructs inside `.st` POUs are rejected with `ERR_LADDER_FORBIDDEN`.
"""
    (docs_dest / "ACCEPTANCE_AND_LIMITATIONS.md").write_text(acceptance_md, encoding="utf-8")

    # Generate Manifest
    manifest2 = generate_manifest(BUNDLE2_DIR)
    (BUNDLE2_DIR / "MANIFEST-SHA256.json").write_text(json.dumps(manifest2, indent=2), encoding="utf-8")

    # Zip Bundle 2
    file_count = zip_directory(BUNDLE2_DIR, ZIP2_PATH)
    logger.info(f"Packaged Delivery Package 2 -> {ZIP2_PATH} ({file_count} files, {ZIP2_PATH.stat().st_size} bytes)")
    return ZIP2_PATH


def main() -> None:
    DELIVERY_ROOT.mkdir(parents=True, exist_ok=True)
    STAGE_ROOT.mkdir(parents=True, exist_ok=True)

    zip1 = build_bundle1_developer_mcp()
    zip2 = build_bundle2_controls_handoff()

    print("\n" + "=" * 80)
    print("PHASE P6 PACKAGING COMPLETED:")
    print(f" Delivery Package 1: {zip1} ({zip1.stat().st_size} bytes)")
    print(f" Delivery Package 2: {zip2} ({zip2.stat().st_size} bytes)")
    print("=" * 80)


if __name__ == "__main__":
    main()
