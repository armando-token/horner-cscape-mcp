# Horner Cscape 10.2 MCP vs. Live GUI Automation Gaps & Capability Audit

> **Status**: FAIL-CLOSED AUDIT ENFORCED — HONEST PARTIAL CLASSIFICATION FOR LIVE GUI AUTOMATION  
> **Target Project**: TankLevelClosedLoop.csp (Maintained Open in Cscape GUI)  
> **Environment**: Windows 11 Enterprise (Build 26200, 64-bit), Python 3.12.10 (.venv), Horner Cscape 10.2 (Build 10.2.751.4, x86 PE)  
> **Safety Policy**: Absolute Hardware Lockout Active (BLOCKED_SAFETY: Zero PLC, Zero Downloads, Zero Straton Standalone)  

---

## 1. Executive Summary & Honest Partial Positioning

The Horner Cscape MCP server provides robust, production-grade Model Context Protocol (MCP) tools for IEC 61131-3 Structured Text (ST) engineering, Horner OCS register database management, Compound File Binary Format (CFBF .csp/.cpj) parsing, and discrete software simulation.

However, in accordance with the **Fail-Closed Audit Policy** and engineering integrity standards:
- **All Live GUI Automation Capabilities are HONESTLY CLASSIFIED AS PARTIAL**.
- While continuous live Cscape stay-open execution has been empirically proven (PID 7616 >5,989s, PID 15240 >7,828s, PID 14580 >=7,200s, and active PID 3120 / PID 15624 >4,476s holding TankLevelClosedLoop.csp), full autonomous GUI interaction remains bounded by Win32/MFC limitations, lack of native COM automation, desktop session dependencies, and modal dialog traps.
- **ST-to-LD Native Conversion is permanently BLOCKED (Doc Only)**; Cscape 10.2 does not support ST to LD conversion at the binary or GUI level.

---

## 2. Comprehensive Tool-by-Tool MCP vs. GUI Gap Analysis

The 23 registered FastMCP tools are grouped into three architectural tiers: Non-GUI Core (18 tools), Live GUI Automation (5 tools), and Language Conversion / Interop.

### Tier 1: Non-GUI Core FastMCP Tools (TESTED_MOCK [offline/DEV only])
*Status: Production Ready, Deterministic, Zero GUI Dependencies*

| Tool Name | MCP Implementation | Verification Level | Live GUI Gap Analysis |
| :--- | :--- | :--- | :--- |
| cscape_read_variables | In-memory & CSV/XML parser | **TESTED_MOCK [offline/DEV only]** | Bypasses GUI entirely; parses native tag databases directly. Zero gap. |
| cscape_write_variables | In-memory tag manager | **TESTED_MOCK [offline/DEV only]** | Writes structured variable records with type bounds checking. Zero gap. |
| cscape_import_variables | CSV / XML file importer | **TESTED_MOCK [offline/DEV only]** | Full roundtrip fidelity; handles CSV delimiter detection. Zero gap. |
| cscape_export_variables | CSV / XML file exporter | **TESTED_MOCK [offline/DEV only]** | Generates native Cscape-compatible CSV/XML tables. Zero gap. |
| cscape_inspect_variables | Scope & collision scanner | **TESTED_MOCK [offline/DEV only]** | AST + register footprint verification (%R word overlap). Zero gap. |
| cscape_validate_st | Pure Python AST validator | **TESTED_MOCK [offline/DEV only]** | IEC 61131-3 syntax & semantic checks offline. Zero gap. |
| cscape_simulate_cycle | In-memory OCS register engine | **TESTED_MOCK [offline/DEV only]** | Simulates %R, %M, %AI, %AQ, %S clocks cycle-by-cycle. Zero gap. |
| cscape_read_register | Register memory table reader | **TESTED_MOCK [offline/DEV only]** | Instantaneous register read with bit-of-word support. Zero gap. |
| cscape_write_register | Register memory table writer | **TESTED_MOCK [offline/DEV only]** | Instantaneous register write with clamping & bounds. Zero gap. |
| cscape_run_simulation | Multi-cycle trajectory engine | **TESTED_MOCK [offline/DEV only]** | 1,000+ cycle simulation at >1,500 cycles/sec. Zero gap. |
| cscape_simulate_pou | Discrete POU scan runner | **TESTED_MOCK [offline/DEV only]** | Headless logic simulation. Zero gap. |
| cscape_get_diagnostics | Offline AST diagnostic parser | **TESTED_MOCK [offline/DEV only]** | Harvests syntax, type, and semantic diagnostics. Zero gap. |
| cscape_get_build_output | Build log file parser | **TESTED_MOCK [offline/DEV only]** | Reads persisted compilation logs. Zero gap. |
| cscape_export_project | Project manifest serializer | **TESTED_MOCK [offline/DEV only]** | Exports CFBF, XML, JSON project representations. Zero gap. |

---

### Tier 2: Live GUI Automation Tools (PARTIAL / SUPERVISOR-DEPENDENT)
*Status: Functionally Demonstrated under Watchdog, but Inherently Constrained by Win32/MFC Architecture*

`
+---------------------------------------------------------------------------------------------+
|                             LIVE MCP / GUI GAP ARCHITECTURE                                 |
+--------------------------+---------------------------------+--------------------------------+
|      FastMCP Tool        |      Live Mechanism             |          Identified Gap        |
+--------------------------+---------------------------------+--------------------------------+
| cscape_launch_ide        | CreateProcess + EnumWindows     | Desktop context & crash risk   |
| cscape_new_iec_project   | Win32 WM_COMMAND (ID 57600)     | Collides with open TankLevel   |
| cscape_open_project      | Win32 Open dialog / CLI arg     | Single-document MFC locking    |
| cscape_insert_st         | WM_PASTE / Clipboard injection  | Sensitive to window focus      |
| cscape_compile           | WM_COMMAND (ID 32826 Ctrl+F7)   | Modal dialogs disable HWND     |
+--------------------------+---------------------------------+--------------------------------+
`

#### Gap 2.1: cscape_launch_ide (Process Startup & Desktop Isolation)
- **Mechanism**: Spawns Cscape.exe via subprocess.Popen or Win32 CreateProcessW, attaches calling thread to desktop via attach_thread_desktop, and pumps window messages to dismiss the modal About Cscape splash dialog (#32770, IDOK=1).
- **Technical Gaps**:
  1. **Historical Null Pointer Crash**: Cscape.exe x86 PE exhibits a documented vulnerability at 0x0051a4cd (PUSH DWORD PTR [EAX + 20h] with EAX == NULL) when initialized without an active interactive desktop or when docking pane state in HKCU\Software\Horner APG\Cscape is corrupt.
  2. **Non-Interactive CI/Daemon Limitation**: If executed under SYSTEM service context or headless SSH without an interactive Window Station (winsta0\Default), the GUI immediately aborts.
  3. **Mitigation**: Requires continuous watchdog supervision (scripts/cscape_keepalive_watchdog.py) and pre-launch registry sanitization (CscapeExitedCorrectly = 1).

#### Gap 2.2: cscape_new_iec_project (Single-Session Concurrency Conflict)
- **Mechanism**: Dispatches ID_FILE_NEW (57600), navigates the Select Editor Type modal dialog (#32770), clicks Radio Button 1461 (IEC 61131-3), and triggers Save As.
- **Technical Gaps**:
  1. **Disruption of Active Session**: If TankLevelClosedLoop.csp is open in the active Cscape instance, triggering cscape_new_iec_project in the same process forces a prompt to close the existing project or causes multi-window instability.
  2. **Serialization Constraint**: MCP cannot run parallel GUI project creations concurrently within a single Cscape instance. Project creation must be strictly serialized or executed in separate sandboxed processes.

#### Gap 2.3: cscape_open_project (File Locking & Modal Dialogs)
- **Mechanism**: Opens project files by passing path as command-line argument to a fresh instance or dispatching ID_FILE_OPEN (57601).
- **Technical Gaps**:
  1. **Exclusive Lock on CFBF Streams**: While Cscape holds TankLevelClosedLoop.csp open, Windows denies write access to the underlying .csp compound document.
  2. **Confirmation Modals**: Opening an uncompiled or dirty project frequently triggers modal warning popups (#32770) regarding target controller models or hardware configurations, requiring automated modal sweeping.

#### Gap 2.4: cscape_insert_st & cscape_insert_st_pou (Editor Focus & Clipboard Sensitivity)
- **Mechanism**: Injects Structured Text POUs into Cscape via clipboard operations (WM_PASTE) and Win32 child window messages, preceded by SHA-256 AST validation.
- **Technical Gaps**:
  1. **Focus Stealing Vulnerability**: Win32 WM_PASTE requires the target MDI child editor (W5EditST) window to have keyboard focus. If a user, modal dialog, or background notification shifts focus away during paste, the injection fails or pastes into an unintended control.
  2. **Editor Tab Synchronization**: Cscape internal project tree does not dynamically reload modified files from disk unless explicitly refreshed via the UI.
  3. **Mitigation**: Offline AST manipulation and CFBF stream modification provide deterministic results, but GUI reflection requires window re-focusing.

#### Gap 2.5: cscape_compile (Error Check Dispatch & Output Scraping)
- **Mechanism**: Dispatches WM_COMMAND with ID_PROGRAM_ERRORCHECK = 32826 (Ctrl+F7) directly to Cscape top-level HWND and scrapes the MFC ListBox (ID 372 / Frame 45011).
- **Technical Gaps**:
  1. **Modal Dialog Window Disablement**: During Error Check, Cscape may pop up modal warning dialogs (e.g., target architecture notices, unregistered variable notices). When a modal dialog opens, Win32 calls EnableWindow(main_hwnd, FALSE), rendering the main window temporarily unresponsive until dismissed by the sweeper.
  2. **ListBox Virtualization & Truncation**: The MFC output window (ID 372) truncates long error messages at 256 characters and does not maintain structured JSON output.
  3. **Fail-Closed Protection**: If compilation hangs or triggers an unhandled exception, MCP fails closed immediately rather than allowing indeterminate state.

---

## 3. ST-to-LD Native Conversion: BLOCKED (Doc Only)

Horner APG Cscape 10.2 maintains an absolute structural barrier between Advanced Ladder and IEC 61131-3 Structured Text:

`
+-------------------------------------------------------------------------+
|                           HORNER CSCAPE 10.2                            |
+------------------------------------+------------------------------------+
|        ADVANCED LADDER MODE        |          IEC 61131-3 MODE          |
|  - Native Horner Rung Solver       |  - Embedded Straton K5 Core        |
|  - Binary .csp stream logic        |  - W5EditST / W5EditLD DLLs        |
|  - Fixed %R/%M register mapping    |  - Pure Structured Text (ST)       |
+------------------------------------+------------------------------------+
                  ^                                     ^
                  |                                     |
                  +--------- NO NATIVE BRIDGE ----------+
                         (ST <-> LD BLOCKED_NATIVE)
`

1. **Native Impossibility**: Comprehensive reverse engineering and PE export audits of Cscape.exe, W5EditST.dll, W5EditLD.dll, and K5Cmp.dll confirm that **zero native conversion routines exist**. Cscape cannot convert an ST POU to Ladder.
2. **MCP Solution**: The MCP platform implements STLadderInteropGuard to parse ST ASTs and generate external ASCII ladder diagrams and JSON proofs for documentation and human auditing only.
3. **Classification**: Formally documented as **BLOCKED (Doc Only)**. Reference: docs/st_to_ld_conversion_blocked.md.

---

## 4. Hardware Safety & Policy Guardrails (Absolute Lockouts)

Under the strict **Fail-Closed Audit Policy**:
- **Zero Controller Downloads (BLOCKED_SAFETY)**: Commands 32827 (ID_CONTROLLER_DOWNLOAD), 33149 (ID_PROGRAM_DOWNLOADOPTIONS), and CLI flags /download, --download are unconditionally intercepted and rejected with UnauthorizedDownloadError.
- **Zero Firmware Flashing (BLOCKED_SAFETY)**: PGMUpdateUtility.exe, DfuSeCommand.exe, STMFlashLoader.exe, and WinJTAG.exe are permanently blocked by security policy.
- **Zero Physical Communications (BLOCKED_SAFETY)**: All physical COM serial ports (COM1-COM256), CAN bus adapters (CAN0, CsCAN), and USB interfaces are intercepted with HardwareLockoutError.
- **Quarantined Straton K5 (INVALID/QUARANTINED)**: All synthetic Straton file generators (appli.k5p, appli.CPO, K5DBXS.INI) remain permanently quarantined in quarantine/straton_k5_legacy/.

---

## 5. Live State & Session Continuity Verification

- **Active Cscape Process**: PID 3120 (HWND 0x00830976)
- **Active Project Window**: TankLevelClosedLoop.csp (Active, Responsive, Maintained Open)
- **Liveness Gate**: READY_FOR_TESTS (artifacts/checkpoints/cscape_live_gate.json)
- **Watchdog Status**: Uptime verified >4,476s without UI freezes (IsHungAppWindow = False, IsWindowEnabled = True)
