# Cscape 10.2 & Straton K5 Research Log

## 1. Installation & Environment Overview
- **Cscape Version**: 10.2.751.4 (32-bit x86 binary).
- **Location**: `C:\Program Files (x86)\Cscape 10.2\Cscape.exe`.
- **Underlying IEC 61131-3 Architecture**: Copa-Data Straton (K5) Engine.
- **Project Template**: `C:\Program Files (x86)\Cscape 10.2\TEMPLATE\EmptyProject\`.
  - `appli.k5p`: Straton project file definition.
  - `appli.CPO`: Straton project compiler options.
  - `appli.lge`: Language/localization mapping.
  - `K5DBXS.INI`: Straton database XML schema settings & function block catalog.
  - `Default/appli.txt`: Variable definitions and project sections.

## 2. Key DLLs & Straton Components Discovered
- `K5Cmp.dll`: Core IEC 61131-3 compiler for ST (Structured Text), IL, SFC, FBD, and LD.
- `K5CmpPost.dll`: Post-compiler linking and binary generation.
- `K5XML.dll`: XML import/export for Straton IEC projects.
- `K5DBOpt.dll`, `K5DBReg.dll`, `K5DBSrv.dll`: Straton variable and dictionary database engine.
- `K5NetCSC.dll`, `K5XGCSC.dll`: Horner Cscape bridging layers.
- `K5NETSim.dll`: IEC 61131-3 software simulation runtime engine.
- `K5Zipper.dll`: Archive / packaging utility.

## 3. Automation & Process Discoveries
- Cscape 10.2 does not expose an out-of-the-box registered dual-interface OLE automation server (`IDispatch`) in Windows Registry, but associates `.cpj` and `.csp` file extensions.
- CLI execution of `Cscape.exe` handles file paths cleanly.
- Headless execution requires `CREATE_NO_WINDOW` and `SW_HIDE` to prevent MFC windows from blocking agent sessions.
- Straton K5 project files (`appli.k5p`) and compiler configuration (`appli.CPO`) are text-based, enabling deterministic code injection, AST validation, and compilation workflows for Structured Text (ST).

## 4. Hardware Safety Audit
- Blocked dangerous executables: `PGMUpdateUtility.exe`, `DfuSeCommand.exe`, `STMFlashLoader.exe`, `WinJTAG.exe`.
- Prohibited communication ports: COM1-COM256, CAN adapters, USB hardware interfaces.
- Prohibited operations: Controller download, firmware flash, online monitor hardware attachments.

## 5. Registry & COM/ActiveX Audit Findings (Subagent 3)
- **Detailed Audit Files**: `research/registry_audit.json` and `research/registry_audit.md`.
- **COM / ActiveX Status**:
  - Confirmed: 0 registered CLSIDs, 0 TypeLibs, 0 OCX files, 0 COM-exporting DLLs, and no embedded `TYPELIB` resource in `Cscape.exe`.
  - Tested ProgIDs (`Cscape.Application`, `Horner.Cscape`, `cpj.Cscape`, `csp.Cscape`, etc.) deterministically fail with `0x80040154` / `CO_E_CLASSSTRING`.
  - Automation must strictly use file-based Straton K5 project generation, compiler CLI tools, and Win32 UI automation.
- **File Associations**:
  - `.cpj` -> `cpj.Cscape` -> `"C:\Program Files (x86)\Cscape 10.2\Cscape.exe" "%1"`
  - `.csp` -> `csp.Cscape` -> `"C:\Program Files (x86)\Cscape 10.2\Cscape.exe" "%1"`
- **Key Registry Subtrees**:
  - `HKCU\Software\Horner_Electric\Cscape`: 18 subkeys controlling `IECEditor`, `ProgramVariables`, `Editor`, `Workspace`, `Colors`, `Setup`, `Printing`, etc.
  - `HKCU\Software\Horner_Electric\Cscape\Setup\CscapeExitedCorrectly`: Set to `1` prior to headless runs to suppress crash recovery popups.
  - `HKLM\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\{A780CECE-F628-4F37-86B7-1B698FB8A0AC}`: Product GUID for Cscape 10.2.751.4 installation.
