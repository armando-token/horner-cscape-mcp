# Horner Cscape MCP: Phase P8 Hardening, Known Limitations, and Remaining Gaps Audit

> **Document ID**: `DOC-P8-HARDENING-LIMITATIONS-v1.0.0`  
> **Target System**: Horner APG Cscape 10.2 (Build 10.2.751.4, x86 PE)  
> **Current Plan Phase**: `P8_IN_PROGRESS` (Plan v3)  
> **Prior Phases**: P0–P6 **ACCEPTED**; P7 **DEFERRED** (Manual Engineer Loading Only)  
> **Safety Guardrails**: Fail-Closed Hardware Lockout Active (Zero Physical Download, Zero COM Port Access)  
> **Execution Desktop**: `winsta0\Default` (Single Cscape GUI Automation Owner)  

---

## 1. Executive Summary

Phase P8 expands and hardens the **Horner Cscape Model Context Protocol (MCP)** architecture without compromising core stability, determinism, or safety.

Following the acceptance of **Phases P0 through P6** by the supervisor:
1. **Phase P7 Physical PLC Download is DEFERRED**: Automation strictly prohibits direct download, flashing, or physical COM transfer. The commissioning engineer loads project binaries manually via Cscape or removable storage.
2. **Phase P8 is IN PROGRESS**:
   - **Schema & Registry Parity**: Expanded `TOOL_SCHEMAS` from 23 to 39 tools (100% parity across FastMCP tools, Pydantic schemas, and package exports).
   - **False-Success Dismantling (H01–H13)**: Hardened template checks, path traversal guards, and error message classification; all 49 negative test cases pass.
   - **Robustness & Edge Cases**: Fail-closed handling for missing files, empty inputs, path traversal escapes, and external concurrency conflicts.
   - **Documented Remaining Gaps**: Transparently cataloging hardware deferrals, native platform limitations, single GUI boundaries, and physical runtime dependencies.

---

## 2. Phase P7 Physical PLC Download Deferral Policy

### 2.1 Explicit Directive
In accordance with engineering safety directives:
- **No Automated Download**: The Horner Cscape MCP server does not and will not automate physical PLC downloading, flashing, or serial COM transfer.
- **Manual Engineer Loading**: Transfer of compiled `.csp` binaries to physical OCS hardware (e.g., Horner XL4 Prime / HE-XPCE2) is deferred exclusively to manual execution by qualified commissioning engineers.

### 2.2 Manual Transfer & Loading Procedures
The controls engineer loads the project to physical hardware using one of the following manual methods:
1. **Direct USB Programming Cable**: Connect PC to OCS Mini-B USB port; open `TankLevel_P5_Dedicated.csp` in Cscape 10.2; select *Controller* -> *Download* (`Ctrl+F9`) manually.
2. **RS-232 / RS-485 Serial Interface**: Connect via Horner programming cable to port `MJ1` or `MJ2`; configure matching baud rate (default 57600/115200); initiate manual download.
3. **Removable Media (MicroSD Card Cloning)**:
   - Export project boot image or PGM file via Cscape manual dialogs to an authenticated MicroSD card.
   - Insert MicroSD card into the OCS controller slot; enter System Menu (`View` + `Enter`); select *Load PGM*.

### 2.3 Permanent Safety Lockouts Maintained in Code
The following invariants remain strictly enforced and fail-closed:
- **Physical Serial / COM Ports**: `COM1` through `COM256`, `\\.\COM*`, and `/dev/tty*` throw `HardwareLockoutError` / `SecurityError`.
- **Win32 Download Command IDs**: `ID_PROGRAM_DOWNLOAD` (`32827`) and `ID_CONTROLLER_DOWNLOAD` (`33149`) are unconditionally intercepted and blocked.
- **Companion Flashing Binaries**: `PGMUpdateUtility.exe`, `DfuSeCommand.exe`, `STMFlashLoader.exe`, and `WinJTAG.exe` execution is prohibited and monitored.
- **Download CLI Switches**: `/d`, `/download`, `/flash`, `/burn`, `/write-flash` are rejected at the argument boundary.
- **CORE-08 Status**: Formally classified as **INCOMPLETE** pending manual physical runtime commissioning.

---

## 3. ST-to-Ladder (ST→LD) Conversion Reality: BLOCKED_NATIVE

### 3.1 Architectural Separation in Cscape 10.2
Horner Cscape 10.2 maintains an architectural barrier between its legacy Advanced Ladder solver and its IEC 61131-3 engine:
- **Advanced Ladder**: Solves discrete rungs sequentially against native `%R`/`%M` memory using an internal solver engine.
- **IEC 61131-3 Mode**: Uses the embedded Straton K5 compilation engine (`W5EditST.dll`, `K5Cmp.dll`) to process Structured Text.

### 3.2 Native Impossibility (`BLOCKED_NATIVE: DOCUMENT_ONLY`)
- Extensive PE export audits and Win32 menu traversals confirm that **Cscape 10.2 contains zero menu items, accelerator keystrokes, OLE automation methods, or DLL exports for ST-to-ladder translation**.
- Any claim that Cscape 10.2 can natively convert an ST POU into Advanced Ladder rungs is a false success.
- **MCP Guardrail**: `STLadderInteropGuard` parses pure ST ASTs and generates external ASCII ladder diagrams and JSON AST proofs for engineering auditing outside of Cscape. Ladder constructs inside `.st` POUs are rejected with `ERR_LADDER_FORBIDDEN`.

---

## 4. Single GUI Automation Boundary & Desktop Context

### 4.1 Exclusive Single GUI Process Ownership
- Exactly **ONE** process (`scripts/cscape_supervisor.py` or dedicated GUI automation agent) may hold and drive live Cscape window handles (`HWND`) on the interactive desktop (`winsta0\Default`).
- Concurrently launching multiple GUI test runners or scripts against Cscape causes window focus theft, clipboard corruption during POU injection, and dialog deadlocks.
- All other test suites, MCP tools, and subagents must operate headlessly or perform non-intrusive read-only queries against `.cscape_live_gate.json`.

### 4.2 Known Historical Crash at `0x0051a4cd`
- When `Cscape.exe` is launched in an unattended, non-interactive Windows session (such as a Windows Service, SYSTEM account, or headless SSH context lacking an active Window Station), the application crashes during MFC docking pane initialization at offset `0x0051a4cd` (`PUSH DWORD PTR [EAX + 20h]` where `EAX == NULL`).
- **Mitigation**: Cscape must strictly execute within an active interactive user desktop (`winsta0\Default`) under a supervised watchdog process.

### 4.3 Modal Dialog Sweeping (`#32770`)
- Cscape frequently presents modal confirmation and warning dialogs (dialog class `#32770`) on project open, hardware target mismatch, or compilation warnings.
- While a modal dialog is displayed, Win32 calls `EnableWindow(main_hwnd, FALSE)`, temporarily disabling top-level accelerator dispatch.
- **Mitigation**: The supervisor continuously sweeps and safely dismisses approved modal dialogs without synthetic allow-all bypasses.

### 4.4 Exclusive CFBF Stream File Locking
- While Cscape holds `TankLevelClosedLoop.csp` open, the Windows OS denies exclusive write access to the underlying compound document.
- Modifications to project files on disk must either occur through live GUI automation or in separate sandboxed copies when Cscape is not holding an active handle.

---

## 5. False-Success Dismantling & Hardening Matrix (H01–H13)

| Vulnerability ID | Vulnerability Description | Enforcement & Hardening Patch | Status in P8 |
| :--- | :--- | :--- | :--- |
| **H01** | Fake export success without live engine | CFBF magic header (`0xD0CF11E0A1B11AE1`) validated; non-existent project export fails closed. | **ENFORCED** |
| **H02** | Fake open success on missing file | Missing file or non-existent project fails closed with `FAIL-CLOSED: Cscape main window not found or dead`. | **ENFORCED** |
| **H03** | Fake compile success without live engine | Directory traversal (`.`, `./`, `../`) rejected fail closed with `SECURITY_BLOCKED` via `SafetyGuard`. | **ENFORCED** |
| **H04** | Silent mocks disguised as live passes | Discrete simulation explicitly declares `provenance: TESTED_MOCK [offline/DEV only]`; never claims live hardware success. | **ENFORCED** |
| **H05** | Global allow dialog bypass | `find_allow_dialogs` strictly confined to Cscape PID; modal text inspected for specific permitted keywords. | **ENFORCED** |
| **H06** | Straton K5 files in active paths | All legacy templates quarantined under `quarantine/straton_k5_legacy/`; zero imports in active `src/` modules. | **ENFORCED** |
| **H07** | Hardcoded dead PIDs as permanent passes | Active PIDs dynamically resolved via `psutil` and window enumeration; stale gates fail closed. | **ENFORCED** |
| **H08** | Ladder constructs disguised as ST | Pure ST validator unconditionally rejects ladder coils, contacts, rungs (`---[ ]---`, `OTE`, `RUNG`) with `ERR_LADDER_FORBIDDEN`. | **ENFORCED** |
| **H09** | Fake 100% or FINAL_REPORT claims | Premature victory claims prohibited; 10-minute watchdog hard-kills idle commands. | **ENFORCED** |
| **H10** | Physical hardware port access | Ports `COM1`–`COM256`, CAN, USB, JTAG fail closed with `HardwareLockoutError`. | **ENFORCED** |
| **H11** | Companion flasher utilities allowed | `PGMUpdateUtility.exe`, `DfuSeCommand.exe`, download switches `/d`, `/download`, Win32 commands `32827`/`33149` blocked. | **ENFORCED** |
| **H12** | Unsupervised naked Cscape launch | Naked launch crash at `0x0051a4cd` documented; supervised stay-open loop enforced. | **ENFORCED** |
| **H13** | Status contract violations | All MCP tool returns strictly conform to `success`, `failed`, `blocked`, `inconclusive`. Pseudo-statuses normalize to `inconclusive`. | **ENFORCED** |

---

## 6. Complete FastMCP 39-Tool Registry & Schema Inventory

All 39 tools are registered on the FastMCP server, verified against JSON-RPC 2.0 stdio, and paired with Pydantic input and output schemas:

| # | Tool Name | Category | Input Schema | Output Schema | Safety Mode |
| :-: | :--- | :--- | :--- | :--- | :--- |
| 1 | `cscape_launch_ide` | Core Live GUI | `CscapeLaunchIDEInput` | `CscapeLaunchIDEOutput` | Live GUI |
| 2 | `cscape_new_iec_project` | Core Live GUI | `CscapeNewIECProjectInput` | `CscapeNewIECProjectOutput` | Live GUI / CFBF |
| 3 | `cscape_open_project` | Core Live GUI | `CscapeOpenProjectInput` | `CscapeOpenProjectOutput` | Live GUI / CFBF |
| 4 | `cscape_insert_st` | Core ST Logic | `CscapeInsertSTInput` | `CscapeInsertSTOutput` | Pure ST / No Ladder |
| 5 | `cscape_insert_st_pou` | Core ST Logic | `CscapeInsertSTInput` | `CscapeInsertSTOutput` | Pure ST / No Ladder |
| 6 | `cscape_compile` | Core Live GUI | `CscapeCompileInput` | `CscapeCompileOutput` | Win32 Error Check |
| 7 | `cscape_get_build_output` | Core Diagnostics | `CscapeGetBuildOutputInput` | `CscapeGetBuildOutputOutput` | Log Parser |
| 8 | `cscape_read_variables` | Core Variables | `CscapeReadVariablesInput` | `CscapeReadVariablesOutput` | Offline Tag Parser |
| 9 | `cscape_write_variables` | Core Variables | `CscapeWriteVariablesInput` | `CscapeWriteVariablesOutput` | Offline Tag Manager |
| 10 | `cscape_import_variables` | Core Variables | `CscapeImportVariablesInput` | `CscapeImportVariablesOutput` | CSV / XML Import |
| 11 | `cscape_export_variables` | Core Variables | `CscapeExportVariablesInput` | `CscapeExportVariablesOutput` | CSV / XML Export |
| 12 | `cscape_run_simulation` | Core Simulation | `CscapeRunSimulationInput` | `CscapeRunSimulationOutput` | Discrete Scan Engine |
| 13 | `cscape_create_project` | Convenience | `CscapeCreateProjectInput` | `CscapeCreateProjectOutput` | Native CFBF |
| 14 | `cscape_add_st_pou` | Convenience | `CscapeAddSTPOUInput` | `CscapeAddSTPOUOutput` | Pure ST / Rollback |
| 15 | `cscape_validate_st` | Convenience | `CscapeValidateSTInput` | `CscapeValidateSTOutput` | IEC 61131-3 AST |
| 16 | `cscape_inspect_variables` | Convenience | `CscapeInspectVariablesInput` | `CscapeInspectVariablesOutput` | OCS Register Scope |
| 17 | `cscape_compile_project` | Convenience | `CscapeCompileProjectInput` | `CscapeCompileProjectOutput` | AST / Error Check |
| 18 | `cscape_get_diagnostics` | Convenience | `CscapeGetDiagnosticsInput` | `CscapeGetDiagnosticsOutput` | Diagnostic Parser |
| 19 | `cscape_simulate_pou` | Convenience | `CscapeSimulatePOUInput` | `CscapeSimulatePOUOutput` | Headless Logic |
| 20 | `cscape_export_project` | Convenience | `CscapeExportProjectInput` | `CscapeExportProjectOutput` | Manifest / JSON |
| 21 | `cscape_simulate_cycle` | Simulation | `CscapeSimulateCycleInput` | `CscapeSimulateCycleOutput` | Single Scan Cycle |
| 22 | `cscape_read_register` | Simulation | `CscapeReadRegisterInput` | `CscapeReadRegisterOutput` | Emulated %R/%M/%AI |
| 23 | `cscape_write_register` | Simulation | `CscapeWriteRegisterInput` | `CscapeWriteRegisterOutput` | Emulated %R/%M/%AQ |
| 24 | `cscape_hmi_inventory` | Phase P3 HMI | `CscapeHMIInventoryInput` | `CscapeHMIInventoryOutput` | HMI Object Walker |
| 25 | `cscape_hmi_apply_group` | Phase P3 HMI | `CscapeHMIApplyGroupInput` | `CscapeHMIApplyGroupOutput` | Native Screen Group |
| 26 | `cscape_hmi_read_properties` | Phase P3 HMI | `CscapeHMIReadPropertiesInput` | `CscapeHMIReadPropertiesOutput` | Object Properties |
| 27 | `cscape_hmi_verify_bindings` | Phase P3 HMI | `CscapeHMIVerifyBindingsInput` | `CscapeHMIVerifyBindingsOutput` | OCS Binding Audit |
| 28 | `cscape_hmi_save_close_reopen` | Phase P3 HMI | `CscapeHMISaveCloseReopenInput` | `CscapeHMISaveCloseReopenOutput` | Durability Audit |
| 29 | `cscape_fixture_request_to_spec` | Phase P4 Fixture | `CscapeFixtureRequestToSpecInput` | `CscapeFixtureRequestToSpecOutput` | Spec Synthesizer |
| 30 | `cscape_fixture_create` | Phase P4 Fixture | `CscapeFixtureCreateInput` | `CscapeFixtureCreateOutput` | Project Generator |
| 31 | `cscape_fixture_selective_edit` | Phase P4 Fixture | `CscapeFixtureSelectiveEditInput` | `CscapeFixtureSelectiveEditOutput` | AST Selective Editor |
| 32 | `cscape_fixture_revision_impact` | Phase P4 Fixture | `CscapeFixtureRevisionImpactInput` | `CscapeFixtureRevisionImpactOutput` | Dependency Graph |
| 33 | `cscape_fixture_durability_check` | Phase P4 Fixture | `CscapeFixtureDurabilityCheckInput` | `CscapeFixtureDurabilityCheckOutput` | Roundtrip Durability |
| 34 | `cscape_fixture_detect_conflict` | Phase P4 Fixture | `CscapeFixtureDetectConflictInput` | `CscapeFixtureDetectConflictOutput` | Concurrency Guard |
| 35 | `cscape_modbus_create_config` | Phase P5 Modbus | `CscapeModbusCreateConfigInput` | `CscapeModbusCreateConfigOutput` | Sidecar Generator |
| 36 | `cscape_modbus_persist_config` | Phase P5 Modbus | `CscapeModbusPersistConfigInput` | `CscapeModbusPersistConfigOutput` | Config Persistence |
| 37 | `cscape_modbus_read_config` | Phase P5 Modbus | `CscapeModbusReadConfigInput` | `CscapeModbusReadConfigOutput` | Config Reader |
| 38 | `cscape_modbus_protocol_check` | Phase P5 Modbus | `CscapeModbusProtocolCheckInput` | `CscapeModbusProtocolCheckOutput` | Wire Protocol Check |
| 39 | `cscape_modbus_conversion_doc` | Phase P5 Modbus | `CscapeModbusConversionDocInput` | `CscapeModbusConversionDocOutput` | Scaling Reference |

---

## 7. Dual-Root Workspace Synchronization

To preserve operational consistency across environments, all source modules, documentation, test suites, and state records are synchronized between:
1. **Primary Development Workspace**: `C:\HornerAI\horner-cscape-mcp\`
2. **User Environment**: `C:\Users\ArmandoSilva\`
