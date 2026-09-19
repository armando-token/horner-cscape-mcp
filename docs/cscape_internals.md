# Horner Cscape 10.2 Internals Reference: Win32, CFBF, AST & Quarantined Straton K5 Legacy

## 1. Executive Summary & Core Technologies

Horner APG Cscape 10.2 is the flagship engineering toolchain for configuring, programming, and monitoring Horner Operator Control Station (OCS) all-in-one industrial controllers. Cscape is built as a 32-bit (x86) Windows application (`Cscape.exe`, version `10.2.751.4`).

The **Horner Cscape MCP Server** automates real Horner Cscape 10.2 across four core architectural pillars:
1. **Win32 UI & Accelerator Automation**: Direct programmatic control of `Cscape.exe` via Win32 messaging (`WM_COMMAND`, `ID_PROGRAM_ERRORCHECK = 32826` / Ctrl+F7), dialog dismissal (`#32770` splash screens, IEC editor selection radio button 1461), and output list scraping (`SysListView32` / `ListBox ID 372`).
2. **Compound File Binary Format (CFBF / OLE2)**: Direct parsing, structural inspection, and generation of native Horner `.csp` (Single Program) and `.cpj` (Project) binary containers starting with standard OLE2 header magic bytes `\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1`.
3. **Pure-Python AST Lexer, Parser & IEC Validator**: Deterministic IEC 61131-3 Structured Text engine enforcing strict typing across all 16 elementary data types, user-defined POUs (`PROGRAM`, `FUNCTION_BLOCK`, `FUNCTION`), and standard function blocks (`TON`, `TOF`, `TP`, `CTU`, `CTD`, `CTUD`), while unconditionally rejecting legacy Advanced Ladder constructs.
4. **Horner OCS Software Cycle Simulator**: In-memory cycle-by-cycle logic execution simulating Horner OCS register tables (%R general registers, %M markers, %T temporary bits, %AI/%AQ analog, %I/%Q digital) and %S clock pulses (%S1 first scan, %S7 10ms, %S8 100ms, %S9 1000ms) with zero physical PLC hardware.

### Engine Status & Straton K5 Legacy Quarantine
- **Legacy Advanced Ladder**: **Explicitly rejected and strictly forbidden**. Advanced Ladder lacks deterministic text representation, cannot be diffed cleanly in version control, and presents severe safety risks in unattended agentic coding environments.
- **Quarantined Legacy: Standalone Straton K5 Project Generation**: Earlier development iterations generated synthetic standalone Copa-Data Straton K5 files (`appli.k5p`, `appli.CPO`, `appli.lge`, `K5DBXS.INI`, `Default/appli.txt`). A forensic audit proved that Cscape 10.2 saves projects in native CFBF OLE2 binary streams (`.csp`/`.cpj`), not bare Straton project directories. All synthetic Straton K5 file generators have been quarantined under `quarantine/straton_k5_legacy/` and marked as **`QUARANTINED/INVALID`**.
- **The Sole Authorized Language Target**: All program logic is generated, validated, simulated, and compiled exclusively in IEC 61131-3 **Structured Text (ST)**.

---

## 2. Installation Inventory & Binary Modules

- **Default File System Location**: `C:\Program Files (x86)\Cscape 10.2\`
- **Core Executable**: `Cscape.exe` (PE32 executable, GUI subsystem, linked against MFC 10.0 runtime)
- **Windows File Associations**:
  - `.cpj` -> `cpj.Cscape` ("Operator Control Station Project File")
  - `.csp` -> `csp.Cscape` ("Operator Control Station Program File")

### Embedded Straton K5 Engine DLL Inventory
Cscape 10.2 bundles Copa-Data Straton K5 engine modules directly in its program directory for internal IEC processing. Standalone execution of these DLLs has been superseded by the MCP server's direct Win32 automation of `Cscape.exe`, native CFBF file format handling, AST parsing/validation, and software cycle simulation:

| Module | File Size | Description & Responsibilities |
| :--- | :--- | :--- |
| `K5Cmp.dll` | ~5.2 MB | Core IEC 61131-3 multi-language compiler internal to Cscape.exe. |
| `K5CmpPost.dll` | ~1.1 MB | Internal post-link optimizer and bytecode resolver. |
| `K5XML.dll` | ~4.0 MB | Industrial XML exchange engine for PLCopen XML serialization. |
| `K5DBOpt.dll` | ~1.8 MB | Symbol database optimizer and indexing engine. |
| `K5DBReg.dll` | ~0.9 MB | Data type registry validating UDTs and complex structures. |
| `K5DBSrv.dll` | ~1.4 MB | Database server engine facilitating fast variable lookups. |
| `K5NETSim.dll` | ~3.7 MB | 32-bit software simulation runtime engine (`T5SIMUL` target). |
| `K5NetCSC.dll` | ~0.8 MB | Horner Cscape bridge library mapping OCS registers to Straton symbol tables. |
| `K5XGCSC.dll` | ~0.6 MB | Graphical and protocol interface between Cscape MFC views and Straton models. |
| `K5Zipper.dll` | ~0.5 MB | Archive and compression engine for legacy `.k5p` project archives. |

---

## 3. Native File Formats: `.cpj`, `.csp`, and Quarantined Legacy `.k5p`

### 3.1 `.cpj` (Cscape Project File - Primary CFBF OLE2 Format)
The `.cpj` format represents a multi-tiered Horner automation project packaged as an OLE Compound File Binary Format (CFBF) container starting with magic header `\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1`. It bundles:
- **System Architecture**: Network topologies, CAN network configurations (CsCAN), and Modbus RTU/TCP master/slave mappings.
- **Hardware Inventory**: OCS base controller specifications, smart-rail I/O modules, expansion bases, and remote fieldbus nodes.
- **Operator Interface (HMI)**: Screen definitions, tactile key mappings, font tables, graphics libraries, and alarm banner configurations.
- **Controller Program Link**: References to the primary logic files (`.csp`).

### 3.2 `.csp` (Cscape Single Program File - Primary CFBF OLE2 Format)
The `.csp` format represents an autonomous controller program packaged as an OLE Compound File Binary Format (CFBF) container (`\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1`). It encapsulates:
- **Register Memory Map**: Pre-allocated Horner OCS memory registers:
  - `%R1`–`%R9999`: 16-bit general-purpose retain registers.
  - `%AI1`–`%AI1024`: Analog input registers (16-bit integer).
  - `%AQ1`–`%AQ1024`: Analog output registers (16-bit integer).
  - `%I1`–`%I2048`: Digital input bits (discrete inputs).
  - `%Q1`–`%Q2048`: Digital output bits (discrete relay/transistor outputs).
  - `%M1`–`%M2048`: Internal bit markers / scratch flags.
  - `%T1`–`%T2048`: Temporary scratch bits (re-initialized every scan).
- **Symbol Table**: User-defined variable names, descriptions, and assigned register bindings.
- **IEC 61131-3 Logic Container**: Embedded Structured Text POUs and execution cycle parameters.

### 3.3 Quarantined Legacy: `.k5p` (Straton K5 Project Bundle)

> [!WARNING]
> **QUARANTINED LEGACY ARTIFACT**: Standalone `.k5p` project directory bundles were used in early development iterations under the false assumption that Cscape 10.2 operated on bare Straton folders. These tools and templates are **quarantined** under `quarantine/straton_k5_legacy/`. The production MCP server targets native CFBF `.csp` and `.cpj` containers and drives `Cscape.exe` directly.

The legacy Straton K5 workspace directory structure is archived for historical reference:

```
<ProjectRoot>/
├── appli.k5p             # Straton project manifest & POU scheduler table
├── appli.CPO             # Compiler configuration options and target architectures
├── appli.lge             # Multi-language string localization table
├── K5DBXS.INI            # Symbol database schema and function block definitions
├── Default/
│   └── appli.txt         # Global variable declarations, types, and initial values
├── pous/                 # Individual Structured Text POU source files
│   ├── MainControl.st    # Program Organization Unit (PROGRAM)
│   └── FB_Motor.st       # Function Block Unit (FUNCTION_BLOCK)
└── artifacts/            # Output directory for compiled bytecode and diagnostics
    ├── appli.XTI         # Intel-ordered runtime target bytecode (T5RTI)
    ├── appli.XWS         # Software simulator bytecode (T5SIMUL)
    └── appli.map         # Memory address allocation and symbol map
```

---

## 4. Quarantined Legacy Straton K5 Configuration Files (`quarantine/straton_k5_legacy/`)

> [!WARNING]
> **QUARANTINED LEGACY REFERENCE**: The configuration files below (`appli.CPO`, `appli.k5p`, and `Default/appli.txt`) reflect the legacy standalone Straton K5 workspace architecture previously tested in mock environments. These files have been quarantined under `quarantine/straton_k5_legacy/`. Production workflows operate directly on native Cscape 10.2 CFBF `.csp`/`.cpj` containers and drive `Cscape.exe` via Win32 messaging, AST validation, and cycle simulation.

### 4.1 `appli.CPO` (Legacy Compiler Options - Quarantined)
The `appli.CPO` file historically configured standalone Straton compilation targets:

```ini
[Options]
Trace=OFF
TraceTime=OFF
Simul=ON
Lock=IO
DEBUG=ON
CSCAPE=ON
CTSEG=OFF
NOCODESTAMP=ON
EMBEDSYMBOLS=ON
EMBEDSYBCASE=ON
NoCodeStamp = ON
FBDOPTIM=ON
LDOPTIM=ON
CHECKSYBCONFLICTS=ON
MAPBOOL=ON
MAPUSINT=ON
MAPUINT=ON
MAPUDINT=ON
MAPULINT=ON
MAPREAL=ON
MAPLREAL=ON
MAPTIME=ON
MAPSTRING=ON
MAPCOMPLEX=ON

[SimulCode]
Target=T5SIMUL
Suffix=.XWS
MotorolaEndian=FALSE
T5Style=ON

[TargetCode]
Target=T5RTI
Suffix=.XTI
MotorolaEndian=FALSE
T5Style=ON
Comment=Straton T5 runtime for T5RTI
ConfigName=T5RTI
```

#### Key Compiler Directives Explained:
- **`Simul=ON`**: Directs the compiler to emit software simulator bytecode alongside target binaries.
- **`CSCAPE=ON`**: Activates Horner Cscape symbol tables and runtime extensions.
- **`CHECKSYBCONFLICTS=ON`**: Strictly enforces variable uniqueness, preventing duplicate symbol errors across POUs.
- **`MAPBOOL=ON` through `MAPCOMPLEX=ON`**: Enables full IEEE and IEC type mapping for primitives and structures.
- **`Target=T5SIMUL` (`.XWS`)**: Software simulator target used for offline, hardware-free validation.
- **`Target=T5RTI` (`.XTI`)**: Target runtime target code for Intel-architecture Horner OCS controllers.

### 4.2 `appli.k5p` (Legacy Project Definition - Quarantined)
The `appli.k5p` file historically registered POUs in legacy Straton projects:

```
;K5 project - Horner Cscape IEC 61131-3
;Project: IndustrialControl

/A,<5>65537,65538,131073,131074,131075,131076,131077,131078,131080,...
</A,end>
/P,PRG_Main,PROGRAM,10,ST
/P,PRG_Alarms,PROGRAM,50,ST
/P,FB_PumpControl,FUNCTION_BLOCK,10,ST
</P,end>
```

- Each `/P` entry defines: `POU_Name`, `POU_Type` (`PROGRAM`, `FUNCTION_BLOCK`, `FUNCTION`), `Cycle_Time_ms` (execution period in milliseconds), and `Language` (`ST`).

### 4.3 `Default/appli.txt` (Legacy Global Variable Dictionary - Quarantined)
Global variables and system tags were registered in this legacy text format:
```
// Global Variables Definition
bEmergencyStop : BOOL := FALSE;
rTankLevel : REAL := 0.0;
nBatchCount : DINT := 0;
```

---

## 5. Horner OCS Controller Hardware Matrix

The Cscape toolchain compiles code for diverse Horner Operator Control Station families. The table below lists the hardware profiles supported by the project's target builder:

| OCS Controller Series | Display / Form Factor | I/O Capacity | Primary Runtime Target |
| :--- | :--- | :--- | :--- |
| **XL4** | 3.5" Color Touchscreen | 12-24 DI, 12-16 DO, 2-4 AI, 2 AQ | `T5RTI` |
| **XLE / XLT** | 2.2" Monochrome / 3.5" Touch | Built-in High-Density I/O | `T5RTI` |
| **XL7 / XL7 Prime** | 7.0" Color Touchscreen | Dual CAN, Dual 10/100 Ethernet | `T5RTI` |
| **EXL6** | 5.7" High-Resolution Touch | Industrial Temperature Grade | `T5RTI` |
| **RCC972 / RCC** | Blind DIN-rail Controller | High-Speed Pulse I/O, Remote I/O | `T5RTI` |
| **ZX Series** | 4.3"–15" Harsh Environment | High-Performance Dual-Core ARM | `T5RTI` |
| **T5SIMUL** | Headless Software Simulator | Virtual I/O Memory Space | `T5SIMUL` |

---

## 6. Prohibited Hardware Download Utilities

To guarantee zero physical machine contact, the following binaries located in the Cscape 10.2 installation are unconditionally locked out:

- `PGMUpdateUtility.exe`: Microcontroller bootloader and flash utility.
- `DfuSeCommand.exe`: STMicroelectronics USB Device Firmware Upgrade tool.
- `STMFlashLoader.exe`: STM UART bootloader flash tool.
- `WinJTAG.exe`: JTAG boundary scan and firmware flashing binary.

Attempting to execute any of these binaries immediately raises `UnsafeProcessError` and terminates the operation.
