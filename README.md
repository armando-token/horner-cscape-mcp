# Horner Cscape 10.2 Model Context Protocol (MCP) Server

[![IEC Standard](https://img.shields.io/badge/IEC%2061131--3-Structured%20Text%20Only-blue.svg)](docs/iec61131_st_guide.md)
[![Cscape Automation](https://img.shields.io/badge/Cscape%2010.2-Win32%20%2B%20UIAutomation-orange.svg)](docs/cscape_automation_architecture.md)
[![Native Files](https://img.shields.io/badge/Native%20Files-.cpj%20%7C%20.csp%20(CFBF)-teal.svg)](docs/cscape_internals.md)
[![Safety](https://img.shields.io/badge/Safety-Hardware%20Lockout%20Enforced-red.svg)](docs/safety_and_security.md)
[![Protocol](https://img.shields.io/badge/Protocol-FastMCP%20JSON--RPC%202.0-purple.svg)](docs/mcp_server_reference.md)
[![Operational State](https://img.shields.io/badge/State-RUNTIME__PENDING__P7-yellow.svg)](Downloads/SUPERVISOR_OFFLINE_ACCEPTANCE.md)

Autonomous Model Context Protocol (MCP) server delivering programmatic engineering integration between AI pair programming agents and **Horner APG Cscape 10.2 (Build 10.2.751.4)** via Win32 messaging, Windows UIAutomation, native Compound File Binary Format (CFBF `.csp`/`.cpj`) parsing, pure-Python IEC 61131-3 Structured Text validation, and deterministic software simulation.

---

## Operational Governance & Honesty Invariants

- **`verified_live: false`**: All verifications reported in this repository reflect deterministic offline software simulation, CFBF container forensics, and in-GUI Error Check compilation. No live physical PLC hardware is claimed connected or verified in software test runs.
- **`plc_download: false` (Zero Automated Download)**: Communication ports (`COM1`–`COM256`, CAN, USB, JTAG) and Win32 download command IDs (`ID_PROGRAM_DOWNLOAD = 32827`, `ID_CONTROLLER_DOWNLOAD = 33149`) are intercepted and blocked fail-closed.
- **Offline Engineering vs. Physical Lab / Phase P7**: All logic POUs, Modbus telemetry scaling bridges, and FastMCP tools are 100% verified offline. Actual physical PLC programming is strictly deferred to **Phase P7 manual loading** by authorized commissioning engineers (`DEFERRED_MANUAL`).
- **Single GUI Owner Boundary**: Live Cscape 10.2 GUI handles on the interactive desktop (`winsta0\Default`) are driven exclusively by one dedicated supervisor process to prevent window focus deadlocks.
- **No Keep-Alive Loops**: Repetitive compiler polling and keep-alive loops are prohibited.

---

## Architectural Highlights: The Core Pillars

1. **Production Win32 & UIAutomation Cscape 10.2 Control**:
   - Programmatically drives the production 32-bit MFC executable (`Cscape.exe`, version `10.2.751.4`).
   - Dispatches menus and accelerators via Win32 messaging (`WM_COMMAND`, `ID_PROGRAM_ERRORCHECK = 32826` / `Ctrl+F8`) and queries Output Window streams safely.
   - Automatically detects and dismisses modal dialogs (`#32770` splash screens, "Tip of the Day", and Save As warnings).

2. **Native Compound File Binary Format (CFBF / OLE2)**:
   - Deep inspection, validation, and stream synthesis for native Horner **`.csp`** and **`.cpj`** project containers.
   - Preserves OLE2 sector integrity and relational pointers without inducing binary corruption.

3. **Pure-Python IEC 61131-3 AST Lexer, Parser & Ladder Guard**:
   - Strict standard IEC 61131-3 Structured Text (ST) parser supporting 16 standard data types and standard Function Blocks (`TON`, `TOF`, `TP`, `CTU`, `CTD`, `CTUD`).
   - **Strict Advanced Ladder Rejection**: Rejects ladder coils (`---( )---`), contacts (`---[ ]---`), and rung markers (`RUNG`, `NETWORK`) with `ERR_LADDER_FORBIDDEN` to guarantee pure ST code quality.

4. **Pure-Software Horner OCS Cycle Simulation**:
   - Deterministic in-memory cyclic execution engine (`SimulationBackend.EMULATED`) tracking register states for `%R` (analog words), `%AI` (analog inputs), `%AQ` (analog outputs), `%I`/`%Q` (digital I/O), `%M` (markers), and `%S` (system flags) without requiring physical PLC hardware.

5. **Straton K5 Isolation**:
   - Legacy standalone Copa-Data Straton K5 templates (`appli.k5p`, `appli.CPO`, `K5DBXS.INI`) remain permanently quarantined under `quarantine/straton_k5_legacy/` with zero active runtime dependencies.

---

## FastMCP 43-Tool Capability Architecture

The FastMCP server exposes 43 registered tools over JSON-RPC 2.0 stdio, classified into 4 operational tiers:

| Tier | Domain | Tool Count | Operational Status | Representative Tools |
| :---: | :--- | :---: | :--- | :--- |
| **1** | Non-GUI Core & AST Analysis | 28 | 100% Production Ready Offline | `cscape_validate_st`, `cscape_inspect_variables`, `cscape_simulate_cycle`, `cscape_run_simulation`, `cscape_create_project` |
| **2** | Live Cscape GUI Automation | 6 | Honest PARTIAL (Single GUI Owner) | `cscape_launch_ide`, `cscape_open_project`, `cscape_compile` (single-pass Error Check 32826) |
| **3** | Modbus RTU & Scan-List Tools | 8 | Resolved Offline / Reconciled | `cscape_inspect_scan_list`, `cscape_validate_scan_list_evidence`, `cscape_reconcile_scan_list`, `cscape_modbus_protocol_check` |
| **4** | Packaging & Distribution | 1 | Production Ready Air-Gapped | `cscape_package_offline_bundle` |

### Fail-Closed Scan-List Inspection (`cscape_inspect_scan_list`)
In Cscape 10.2, adding native Modbus scan list records offline causes relational stream desynchronization because Cscape requires active target node responses over serial. The tool honors this platform boundary:
- **Default baseline inspection (`require_populated=False`)**: Confirms native table is empty (`count: 0`, `scan_list_status: "empty"`).
- **Fail-closed validation (`require_populated=True`)**: Returns `status: "blocked"`, `error_code: "SCAN_LIST_EMPTY_OFFLINE"` to prevent unsafe execution.
- **Offline Reconciliation (`cscape_reconcile_scan_list`)**: Reconciles planned slave device inventory (3 devices in `modbus_protocol_inventory.json`: Level `%AI1`, Inflow `%AI2`, Pressure `%AI3`) against native container (0 entries), capturing discrepancy delta (-3) with status `DISCREPANCY_EXPLAINED_OFFLINE_LOCKOUT`.

---

## Windows Installation & Quick Start

### 1. Prerequisites
- **Operating System**: Windows 10/11 (64-bit).
- **Python**: Python 3.12 (64-bit).
- **Horner Cscape**: Horner APG Cscape 10.2 (Build 10.2.751.4) installed.

### 2. Setup Virtual Environment
```powershell
# Clone or navigate to repository root
cd C:\HornerAI\horner-cscape-mcp

# Initialize virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install package in editable development mode
pip install -e .
```

### 3. Running the FastMCP Server
```powershell
& ".\.venv\Scripts\python.exe" "scripts\run_mcp_server.py"
```

### 4. Running Offline Unit & Integration Tests
```powershell
& ".\.venv\Scripts\pytest.exe" -q
```
*All tests execute in pure-software offline mode without requiring live PLC hardware.*

---

## Physical Hardware Commissioning (Phase P7 Manual)

Physical controller loading is strictly deferred to manual execution by authorized commissioning engineers. Automated scripts, FastMCP servers, and AI agents are permanently locked out fail-closed from physical communication ports.

To test on physical hardware:
1. Review the step-by-step Standard Operating Procedure: [`docs/HOW_TO_TEST_PHYSICAL_PLC.md`](docs/HOW_TO_TEST_PHYSICAL_PLC.md) and [`Downloads/P7_MANUAL_COMMISSIONING_PROCEDURE.md`](file:///C:/Users/ArmandoSilva/Downloads/P7_MANUAL_COMMISSIONING_PROCEDURE.md).
2. Execute the bilingual pre-download checklist: [`Downloads/P7_MANUAL_LOAD_CHECKLIST.md`](file:///C:/Users/ArmandoSilva/Downloads/P7_MANUAL_LOAD_CHECKLIST.md).
3. Connect programming cable (USB Mini-B or MJ1 serial) and manually execute `Controller -> Download` (`Ctrl+F9`) in Cscape 10.2.

---

## Release Distribution Assets Guidance

Large standalone distribution archives are maintained as air-gapped evidence packages with internal SHA-256 cryptographic manifests. To keep the Git repository lightweight, performant, and clean, these archives are distributed as GitHub Releases and staging packages in `Downloads/`, rather than being tracked in Git:
- **`TankLevel_P5_Dedicated_offline_bundle_v1.1.0.zip`** (72,977 bytes): Standalone distribution package containing pure ST POUs (`FB_ModbusScaleQuality.st`, `TankLevelControl.st`, `TankLevelModbusBridge.st`), `TankLevel_P5_Dedicated.csp`, and Modbus configuration sidecars.
- **`offline_evidence_bundle_v1.1.0.zip`** (364,842 bytes): Consolidated air-gapped evidence archive consolidating 42 forensic reports, test proofs, and field verification matrices.

---

## Key Documentation Pointers

| Document | Purpose & Scope | Location |
| :--- | :--- | :--- |
| **Bilingual Progress Summary** | Comprehensive EN/ES summary of real offline deliverables and still-open list | [`Downloads/AVANCE_2026-09-17.md`](file:///C:/Users/ArmandoSilva/Downloads/AVANCE_2026-09-17.md) |
| **Master Handoff Index** | Master distribution table of all 55 cataloged project deliverables | [`Downloads/HANDOFF_INDEX.md`](file:///C:/Users/ArmandoSilva/Downloads/HANDOFF_INDEX.md) |
| **Supervisor Offline Acceptance** | Formal sign-off on Plan v3 offline deliverables (`supervisor_offline_accepted = true`) | [`Downloads/SUPERVISOR_OFFLINE_ACCEPTANCE.md`](file:///C:/Users/ArmandoSilva/Downloads/SUPERVISOR_OFFLINE_ACCEPTANCE.md) |
| **P7 Manual Load Checklist** | Bilingual safety checklist for physical OCS commissioning (`DEFERRED_MANUAL`) | [`Downloads/P7_MANUAL_LOAD_CHECKLIST.md`](file:///C:/Users/ArmandoSilva/Downloads/P7_MANUAL_LOAD_CHECKLIST.md) |
| **How to Test MCP** | Complete guide for local FastMCP testing and tool verification | [`docs/HOW_TO_TEST_MCP.md`](docs/HOW_TO_TEST_MCP.md) |
| **How to Test on Physical PLC** | Guide for physical hardware connection and manual Cscape loading | [`docs/HOW_TO_TEST_PHYSICAL_PLC.md`](docs/HOW_TO_TEST_PHYSICAL_PLC.md) |
| **Runtime Gaps & Roadmap** | Technical audit for CORE-08 runtime, CORE-09 HMI, and CORE-10 24h soak | [`Downloads/CORE_08_09_10_RUNTIME_GAPS_AND_ROADMAP.md`](file:///C:/Users/ArmandoSilva/Downloads/CORE_08_09_10_RUNTIME_GAPS_AND_ROADMAP.md) |
| **Field Test Matrix** | 23-test vector point-by-point field commissioning matrix | [`Downloads/CORE_08_09_10_FIELD_VERIFICATION_MATRIX.md`](file:///C:/Users/ArmandoSilva/Downloads/CORE_08_09_10_FIELD_VERIFICATION_MATRIX.md) |
| **Capability Matrix** | 4-tier honest capability matrix and platform boundaries | [`CAPABILITY_MATRIX.md`](CAPABILITY_MATRIX.md) |
| **Safety & Security Spec** | Fail-closed hardware ban, blocked ports, and download lockout | [`docs/safety_and_security.md`](docs/safety_and_security.md) |
