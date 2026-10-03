# Horner Cscape 10.2 Windows Registry & COM/ActiveX Architecture Audit

- **Date of Audit**: 2026-09-03
- **Audited Target**: Horner Cscape 10.2.751.4 (32-bit x86)
- **Host Platform**: Windows 11 64-bit (x64 / WOW64 subsystem)
- **Primary Executable**: `C:\Program Files (x86)\Cscape 10.2\Cscape.exe`
- **Output JSON Dump**: [`registry_audit.json`](file:///C:/HornerAI/horner-cscape-mcp/research/registry_audit.json)

---

## Executive Summary

1. **COM / ActiveX Automation Status: Completely Non-Existent**
   - No OLE Automation server (`IDispatch`), COM class factory, or Dual Interface is registered for Horner Cscape.
   - All standard ProgID candidates (`Cscape.Application`, `Horner.Cscape`, `cpj.Cscape`, `csp.Cscape`, `Cscape.Document`, `Cscape`, `Straton.Application`) return `CO_E_CLASSSTRING` / `REGDB_E_CLASSNOTREG` (`-2147221005`: Invalid class string).
   - Across all 10,470 files in `C:\Program Files (x86)\Cscape 10.2\`, there are **0 `.ocx` files**, **0 `.tlb` TypeLib files**, and **0 DLLs exporting `DllRegisterServer` / `DllGetClassObject`**.
   - `Cscape.exe` does not contain an embedded `TYPELIB` resource.
   - **Architectural Consequence for MCP**: The MCP server **cannot** use OLE COM Dispatch or COM interop to control Cscape programmatically. Automation must strictly utilize text-based project manipulation (`appli.k5p`, `appli.CPO`, `appli.txt`), compiler toolchains (`K5Cmp.dll`), CLI process invocation (`Cscape.exe "<path>"`), and headless Win32 / UIAutomation handlers.

2. **File Associations & Shell Invocation**:
   - Horner Cscape registers two primary file extensions in `HKEY_CLASSES_ROOT`:
     - `.cpj` &rarr; `cpj.Cscape` (*Operator Control Station Project File*)
     - `.csp` &rarr; `csp.Cscape` (*Operator Control Station Program File*)
   - Both command strings resolve directly to:
     ```
     "C:\Program Files (x86)\Cscape 10.2\Cscape.exe" "%1"
     ```
   - Windows Installer Darwin multi-string descriptor is also associated:
     `C*!p^y}1OA@VMkIi*!Q`AlwaysInstall>~Pw6uq0YZ9Uw.@YVA_}8 "%1"`
   - Note: `.cst` (Cscape Template) is not associated at the system level.

3. **Registry Configuration Storage Model**:
   - Horner Cscape 10.2 stores virtually all user state, editor behaviors, docking layouts, communication settings, and licensing data in:
     `HKEY_CURRENT_USER\Software\Horner_Electric\Cscape`
   - `HKEY_LOCAL_MACHINE\Software\WOW6432Node\Horner APG` does not exist as a primary runtime key; installation metadata resides exclusively under the Windows Installer Product GUID:
     `HKEY_LOCAL_MACHINE\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\{A780CECE-F628-4F37-86B7-1B698FB8A0AC}`

---

## 1. HKCU\Software\Horner_Electric\Cscape Subkey Analysis

The root key `HKCU\Software\Horner_Electric\Cscape` contains 18 subkeys managing the internal state of the MFC and Straton-based application:

| Subkey | Subkeys Count | Values Count | Description & Automation Impact |
| :--- | :--- | :--- | :--- |
| **`IECEditor`** | 0 | 15 | IEC 61131-3 editor settings (tab size, drag-drop, undo stack, variable querying). Critical for ST/LD/FBD editing behaviors. |
| **`ProgramVariables`** | 0 | 3 | IEC/Straton tag variable table columns and widths. |
| **`Editor`** | 0 | 44 | Global Cscape editor configuration, auto-save, baud rates, ladder logic rules, and default project templates. |
| **`Options`** | 0 | 0 | Container key for legacy or runtime option toggles. |
| **`Settings`** | 1 (`Bars`) | 0 | Toolbar and control bar persistent states. |
| **`Workspace`** | 17 | MFC Panes | MFC Ribbon, docking panes (`BasePane-*`, `Pane-*`), keyboard accelerators, and main window placement coordinates. |
| **`Colors`** | 3 (`Classic`, `Dark`, `Light`) | 2 | Editor syntax and canvas color palettes (RGB integers, font names `Franklin Gothic Medium`, dot grids). |
| **`ApplicationLook`**| 0 | 1 | `RibbonTheme = 0`. |
| **`Setup`** | 0 | 13 | Exit status flag (`CscapeExitedCorrectly`), default serial configuration (`COM1: 57600 baud`), and F1-F10 hotkeys. |
| **`HornerIDReg`** | 1 (`Users`) | 7 | User account credentials, Horner ID (`[REDACTED]`), and PC Unique ID. |
| **`HornerNodeLock`**| 0 | 1 | Licensing node lock state (`NodeKey = 0`). |
| **`Modem`** | 0 | 3 | AT modem initialization and dial strings (`ATZ&D0&K0`, `ATDT`). |
| **`OcsModelDatabase`**| 1 (`Settings`)| 0 | Part number formatting (`AbbreviatedPartNumbers = 1`). |
| **`Printing`** | 1 (`IECEditors`) | 22 | Print generation and IEC logic printing properties. |
| **`Recent File List`**| 0 | 0 | MRU list of recent `.cpj` / `.csp` files. |
| **`GrEdit`** | 2 | 0 | Graphic Screen Editor settings and recent files. |
| **`IO_CFG`** | 1 (`settings`) | 0 | I/O configuration window states. |
| **`Messaging`** | 1 (`Settings`) | 0 | Cscape messaging protocol definitions. |

---

### Detailed Key Breakdown

### 1.1 `IECEditor`
Configures the Copa-Data Straton IEC 61131-3 code editing environment:
- `EnableDragDrop`: `1` (Allows dragging function blocks and variables into Structured Text / Ladder / FBD)
- `UndoRedoStackSize`: `16` (Max undo operations stored in memory)
- `TabSize`: `4` (Indentation width in spaces)
- `SearchWindowsLimit`: `2`
- `SearchInAllLogicBlocks`: `0`
- `CopyBitmapToClipboard`: `1`
- `QueryVarDeclaration`: `1` (Prompts user to declare undeclared tags)
- `EnablePulseForElements`: `1`
- `PromptForVariableName`: `0`
- `RestoreFBDSelectionMode`: `0`
- `defaultFBDVariableWidth`: `8`
- `postVariableInsertAction`: `0`
- `fbdVariableInfoType`: `0`
- `editionTooltipsInfo`: `"0"`
- `debugTooltipsInfo`: `"0"`

### 1.2 `ProgramVariables`
Defines the structure of the tag dictionary table in the IEC editor:
- `TotalVisibleColumn`: `9`
- `ColumnName`: `Name#@#Type#@#Dim.#@#Attrib.#@#Init value#@#User Group#@#OCS360#@#Mapping#@#Description`
- `Width`: `100,80,40,75,60,50,100,50,500`

### 1.3 `Editor`
Core operational flags for compilation, project generation, and verification:
- `AutoSave`: `0` (Disabled by default; auto-save won't interfere with external file operations)
- `AutoSaveMinutes`: `3`
- `AllowBackup`: `0`
- `OpenLast`: `0` (Prevents auto-opening the previous project on startup)
- `CreateBlankProgram`: `1`
- `SwitchBetweenPrograms`: `1`
- `AllowUserProgramTypeCreate`: `1`
- `ProgramTypeToCreate`: `0`
- `PrgmTypeToCreateIsAddvLadderEditor`: `1`
- `PrgmTypeToCreateIsIECTagEditor`: `1`
- `PrgmTypeToCreateIsAddvLadderWithTagAddrEditor`: `1`
- `PrgmTypeToCreateIsEnhancedIECDefaultEnable`: `0`
- `UpdateBaud`: `57600`
- `WarnMaxBaud`: `1`
- `WarnFirmwareCable`: `1`
- `WarnIOStop`: `1`
- `AggressiveDebug`: `1`
- `ShowNames`: `1`
- `MultiCoil`: `1`
- `Check REAL/DINT`: `1`
- `Timer Register`: `1`
- `DintUint Register`: `1`
- `LadderNums`: `3`

### 1.4 `Setup` (Communication & Recovery State)
- `CscapeExitedCorrectly`: `0` &rarr; **CRITICAL AUTOMATION NOTE**: When `CscapeExitedCorrectly` is `0`, Cscape on startup may detect an abnormal termination and display an MFC modal dialog asking to restore the backup or previous session. For reliable headless/automation runs, setting this value to `1` prior to launching `Cscape.exe` prevents unexpected crash recovery prompts.
- `Connection`:
  ```
  Name:Default
  COM1:
  MaxBaud:57600
  Timeout:1000
  ```
  (Default serial channel for Horner controller communication)

### 1.5 `Workspace` (MFC Window Management)
Stores MFC 10+ ribbon and docking pane geometries:
- `WindowPlacement`:
  - `MainWindowRect`: `(26, 26, 986, 539)`
  - `ShowCmd`: `1` (`SW_SHOWNORMAL`)
- `ControlBars-Summary`: Screen dimensions `1280 x 760`.
- `MFCRibbonBar-59398`: Ribbon configuration and quick-access toolbar state.
- `Keyboard-0`: 348-byte binary table of registered keyboard accelerators (Ctrl+C, Ctrl+V, F5 build, etc.).

---

## 2. HKLM Registry Architecture

### 2.1 WOW6432Node Inspection
- The expected legacy key `HKLM\Software\WOW6432Node\Horner APG` is **not created** by the modern Cscape 10.2 WiX/MSI installer.
- The 64-bit root `HKLM\Software\Horner APG` is also **empty / absent**.
- System registration is centralized under the Windows Installer registry hive:
  `HKLM\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\{A780CECE-F628-4F37-86B7-1B698FB8A0AC}`

### 2.2 Installation Properties

| Property Name | Registry Value |
| :--- | :--- |
| **Product GUID** | `{A780CECE-F628-4F37-86B7-1B698FB8A0AC}` |
| **DisplayName** | `Cscape 10.2` |
| **DisplayVersion** | `10.2.751.4` |
| **Publisher** | `Horner APG, LLC` |
| **InstallLocation** | `C:\Program Files (x86)\Cscape 10.2\` |
| **UninstallString** | `MsiExec.exe /I{A780CECE-F628-4F37-86B7-1B698FB8A0AC}` |
| **InstallSource** | Path to original installer package cache |

### 2.3 App Paths Check
- `HKLM\Software\Microsoft\Windows\CurrentVersion\App Paths\Cscape.exe` is **not registered**.
- Consequently, invoking `cscape` in `cmd` or `powershell` without full path or PATH modification will fail. Always use the absolute binary path `C:\Program Files (x86)\Cscape 10.2\Cscape.exe`.

---

## 3. HKCR File Associations & Command Strings

### 3.1 `.cpj` (Horner OCS Project File)
- **Extension Key**: `HKEY_CLASSES_ROOT\.cpj`
  - `(Default)` = `cpj.Cscape`
  - Subkey `cpj.Cscape\ShellNew`: Enables right-click context menu creation of new projects.
- **ProgID Key**: `HKEY_CLASSES_ROOT\cpj.Cscape`
  - `(Default)` = `Operator Control Station Project File`
  - `DefaultIcon` = `C:\Windows\Installer\{A780CECE-F628-4F37-86B7-1B698FB8A0AC}\_B87AC96A_975E_4E95_B5DA_2B8468BEEBC3,0`
  - `shell\open\command` `(Default)` = `"C:\Program Files (x86)\Cscape 10.2\Cscape.exe" "%1"`
  - `shell\open\command` `command` (REG_MULTI_SZ) = `['C*!p^y}1OA@VMkIi*!Q`AlwaysInstall>~Pw6uq0YZ9Uw.@YVA_}8 "%1"']`

### 3.2 `.csp` (Horner OCS Program File)
- **Extension Key**: `HKEY_CLASSES_ROOT\.csp`
  - `(Default)` = `csp.Cscape`
  - Subkey `csp.Cscape\ShellNew`: Enables right-click context menu creation of new programs.
- **ProgID Key**: `HKEY_CLASSES_ROOT\csp.Cscape`
  - `(Default)` = `Operator Control Station Program File`
  - `DefaultIcon` = `C:\Windows\Installer\{A780CECE-F628-4F37-86B7-1B698FB8A0AC}\_E4D4D3DF_06E7_4A49_B11D_8547E04A3600,0`
  - `shell\open\command` `(Default)` = `"C:\Program Files (x86)\Cscape 10.2\Cscape.exe" "%1"`
  - `shell\open\command` `command` (REG_MULTI_SZ) = `['C*!p^y}1OA@VMkIi*!Q`AlwaysInstall>~Pw6uq0YZ9Uw.@YVA_}8 "%1"']`

---

## 4. COM / ActiveX Audit Results

### 4.1 Activation Test Matrix

| Tested ProgID | comtypes GUID Resolution | win32com Dispatch | HRESULT / Error |
| :--- | :--- | :--- | :--- |
| `Cscape.Application` | FAILED | FAILED | `0x80040154` (`-2147221005`: Invalid class string) |
| `Cscape.Application.1` | FAILED | FAILED | `0x80040154` (`-2147221005`: Invalid class string) |
| `Horner.Cscape` | FAILED | FAILED | `0x80040154` (`-2147221005`: Invalid class string) |
| `Horner.Cscape.Application` | FAILED | FAILED | `0x80040154` (`-2147221005`: Invalid class string) |
| `cpj.Cscape` | FAILED | FAILED | `0x80040154` (`-2147221005`: Invalid class string) |
| `csp.Cscape` | FAILED | FAILED | `0x80040154` (`-2147221005`: Invalid class string) |
| `Cscape.Document` | FAILED | FAILED | `0x80040154` (`-2147221005`: Invalid class string) |
| `Cscape` | FAILED | FAILED | `0x80040154` (`-2147221005`: Invalid class string) |
| `Straton.Application` | FAILED | FAILED | `0x80040154` (`-2147221005`: Invalid class string) |
| `K5.Application` | FAILED | FAILED | `0x80040154` (`-2147221005`: Invalid class string) |

### 4.2 Installation Binary Scan (PE Analysis)
- **Directory**: `C:\Program Files (x86)\Cscape 10.2`
- **Total Files Scanned**: 10,470
- **OCX Files (ActiveX Controls)**: **0**
- **TLB Files (Type Libraries)**: **0**
- **DLLs Exporting `DllRegisterServer` / `DllGetClassObject`**: **0**
- **Executable PE Header (`Cscape.exe`)**:
  - Architecture: 32-bit x86 (`IMAGE_FILE_MACHINE_I386` = `0x14c`)
  - Subsystem: `IMAGE_SUBSYSTEM_WINDOWS_GUI` (`2`)
  - Resource Directory: Contains standard icons, dialogs, bitmaps, ribbon resources. Contains **NO `TYPELIB` (Resource ID 16)**.

---

## 5. Architectural Implications & Recommendations for Horner MCP

1. **Pre-flight Registry Sanitation**:
   - Before invoking `Cscape.exe` in automated batch runs, the MCP server can ensure that `HKCU\Software\Horner_Electric\Cscape\Setup\CscapeExitedCorrectly` is set to `1` (DWORD).
   - This prevents Cscape from popping up modal MFC crash recovery dialogs if a previous session was terminated forcefully.

2. **No OLE Automation Dispatch**:
   - Do not attempt to instantiate COM objects (`win32com.client.Dispatch("Cscape.Application")`). Any such attempt will fail deterministically.

3. **Deterministic ST / IEC Code Injection**:
   - The underlying Copa-Data Straton K5 engine relies entirely on filesystem project definitions:
     - `appli.k5p`: Straton project file
     - `appli.CPO`: Compiler options
     - `appli.txt`: Variable table and logic blocks
   - MCP tools should generate and manipulate these text-based artifacts directly, bypassing any GUI overhead.

4. **Command-Line Invocation**:
   - Launching Cscape to open a project should always use:
     ```powershell
     & "C:\Program Files (x86)\Cscape 10.2\Cscape.exe" "C:\path\to\project.cpj"
     ```
   - When launching in background/automation contexts, use `CREATE_NO_WINDOW` or minimize/hide windows to prevent interference with interactive user sessions.
