# Environment Proof & System Verification Report

**Document**: `docs/env_proof.md`  
**Target Workspace**: `C:\HornerAI\horner-cscape-mcp`  
**Execution Timestamp**: `2026-09-03T20:20:43-07:00`  
**Agent**: Subagent 1: Env Proof Specialist  
**Status**: **VERIFIED & PASSING**

---

## 1. Executive Summary & Verification Matrix

| Verification Category | Requirement / Specification | Observed System State | Status |
| :--- | :--- | :--- | :--- |
| **Operating System** | Windows 11 Enterprise (Build 26200, 64-bit) | Microsoft Windows 11 Enterprise `10.0.26200.9168` (64-bit) | **PASS** |
| **PowerShell Version** | `$PSVersionTable` capture | Windows PowerShell `5.1.26100.9168` (Desktop Edition) | **PASS** |
| **Python Runtime** | Python 3.12.10 (`.venv` runtime) | Python `3.12.10` (`MSC v.1943 64 bit AMD64`) | **PASS** |
| **pywinauto** | Installed & importable in `.venv` | `0.6.9` | **PASS** |
| **uiautomation** | Installed & importable in `.venv` | `2.0.29` | **PASS** |
| **pywin32** | Installed & importable in `.venv` | `312` | **PASS** |
| **psutil** | Installed & importable in `.venv` | `7.2.2` | **PASS** |
| **pefile** | Installed & importable in `.venv` | `2024.8.26` | **PASS** |
| **.NET SDK** | .NET SDK 11.0.100-preview.7 | `11.0.100-preview.7.26381.103` (x64) | **PASS** |

---

## 2. Operating System Incontrovertible Proof

### 2.1 WMI / CIM Operating System Information
- **Command**:
  ```powershell
  Get-CimInstance Win32_OperatingSystem | Format-List Caption, Version, BuildNumber, OSArchitecture, InstallDate, LastBootUpTime
  ```
- **Timestamp**: `2026-09-03T20:17:43Z`
- **Exit Code**: `0`
- **Output**:
  ```text
  Caption        : Microsoft Windows 11 Enterprise
  Version        : 10.0.26200
  BuildNumber    : 26200
  OSArchitecture : 64-bit
  InstallDate    : 9/2/2026 10:04:32 PM
  LastBootUpTime : 9/2/2026 10:24:14 PM
  ```

### 2.2 Command Prompt Version Check
- **Command**:
  ```cmd
  cmd.exe /c ver
  ```
- **Timestamp**: `2026-09-03T20:20:14Z`
- **Exit Code**: `0`
- **Output**:
  ```text
  Microsoft Windows [Version 10.0.26200.9168]
  ```

### 2.3 Windows Registry NT CurrentVersion Inspection
- **Command**:
  ```powershell
  Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion' | Select-Object ProductName, DisplayVersion, CurrentBuild, CurrentBuildNumber, UBR, ReleaseId | Format-List
  ```
- **Timestamp**: `2026-09-03T20:20:27Z`
- **Exit Code**: `0`
- **Output**:
  ```text
  ProductName        : Windows 10 Enterprise
  DisplayVersion     : 25H2
  CurrentBuild       : 26200
  CurrentBuildNumber : 26200
  UBR                : 9168
  ReleaseId          : 2009
  ```

---

## 3. PowerShell Environment Proof

### 3.1 `$PSVersionTable` Output
- **Command**:
  ```powershell
  powershell -NoProfile -Command '$PSVersionTable'
  ```
- **Timestamp**: `2026-09-03T20:18:16Z`
- **Exit Code**: `0`
- **Output**:
  ```text
  Name                           Value                                                                                           
  ----                           -----                                                                                           
  PSVersion                      5.1.26100.9168                                                                                  
  PSEdition                      Desktop                                                                                         
  PSCompatibleVersions           {1.0, 2.0, 3.0, 4.0...}                                                                         
  BuildVersion                   10.0.26100.9168                                                                                 
  CLRVersion                     4.0.30319.42000                                                                                 
  WSManStackVersion              3.0                                                                                             
  PSRemotingProtocolVersion      2.3                                                                                             
  SerializationVersion           1.1.0.1
  ```

---

## 4. Python 3.12.10 Runtime Proof (`.venv`)

### 4.1 Executable CLI Version Flag
- **Command**:
  ```powershell
  & "C:\HornerAI\horner-cscape-mcp\.venv\Scripts\python.exe" --version
  ```
- **Timestamp**: `2026-09-03T20:17:08Z`
- **Exit Code**: `0`
- **Output**:
  ```text
  Python 3.12.10
  ```

### 4.2 Python Runtime Introspection
- **Command**:
  ```powershell
  & "C:\HornerAI\horner-cscape-mcp\.venv\Scripts\python.exe" -c "import sys, platform; print('Executable:', sys.executable); print('Version:', sys.version); print('Compiler:', platform.python_compiler()); print('Architecture:', platform.architecture())"
  ```
- **Timestamp**: `2026-09-03T20:18:44Z`
- **Exit Code**: `0`
- **Output**:
  ```text
  Executable: C:\HornerAI\horner-cscape-mcp\.venv\Scripts\python.exe
  Version: 3.12.10 (tags/v3.12.10:0cc8128, Apr  8 2025, 12:21:36) [MSC v.1943 64 bit (AMD64)]
  Compiler: MSC v.1943 64 bit (AMD64)
  Architecture: ('64bit', 'WindowsPE')
  ```

---

## 5. Automation Packages Proof

### 5.1 Package Metadata Verification & Module Paths
- **Command**:
  ```powershell
  & "C:\HornerAI\horner-cscape-mcp\.venv\Scripts\python.exe" -c "
  import importlib.metadata as im
  import pywinauto, uiautomation, win32api, psutil, pefile

  targets = ['pywinauto', 'uiautomation', 'pywin32', 'psutil', 'pefile']
  for pkg in targets:
      ver = im.version(pkg)
      print(f'{pkg}=={ver}')

  print('--- Import Details ---')
  print('pywinauto location:', pywinauto.__file__)
  print('uiautomation location:', uiautomation.__file__)
  print('win32api location:', win32api.__file__)
  print('psutil location:', psutil.__file__)
  print('pefile location:', pefile.__file__)
  "
  ```
- **Timestamp**: `2026-09-03T20:19:01Z`
- **Exit Code**: `0`
- **Output**:
  ```text
  pywinauto==0.6.9
  uiautomation==2.0.29
  pywin32==312
  psutil==7.2.2
  pefile==2024.8.26
  --- Import Details ---
  pywinauto location: C:\HornerAI\horner-cscape-mcp\.venv\Lib\site-packages\pywinauto\__init__.py
  uiautomation location: C:\HornerAI\horner-cscape-mcp\.venv\Lib\site-packages\uiautomation\__init__.py
  win32api location: C:\HornerAI\horner-cscape-mcp\.venv\Lib\site-packages\win32\win32api.pyd
  psutil location: C:\HornerAI\horner-cscape-mcp\.venv\Lib\site-packages\psutil\__init__.py
  pefile location: C:\HornerAI\horner-cscape-mcp\.venv\Lib\site-packages\pefile.py
  ```

### 5.2 Target Packages in `pip list`
- **Command**:
  ```powershell
  & "C:\HornerAI\horner-cscape-mcp\.venv\Scripts\python.exe" -m pip list | Select-String -Pattern 'pywinauto|uiautomation|pywin32|psutil|pefile'
  ```
- **Timestamp**: `2026-09-03T20:17:08Z`
- **Exit Code**: `0`
- **Output**:
  ```text
  pefile                    2024.8.26
  psutil                    7.2.2
  pywin32                   312
  pywinauto                 0.6.9
  uiautomation              2.0.29
  ```

### 5.3 Complete `.venv` Package Inventory (`pip freeze`)
- **Command**:
  ```powershell
  & "C:\HornerAI\horner-cscape-mcp\.venv\Scripts\python.exe" -m pip freeze
  ```
- **Timestamp**: `2026-09-03T20:19:38Z`
- **Exit Code**: `0`
- **Output**:
  ```text
  annotated-types==0.8.0
  anyio==4.15.0
  attrs==26.1.0
  cffi==2.1.1
  click==8.5.0
  colorama==0.4.6
  comtypes==1.4.16
  coverage==7.16.0
  cryptography==50.0.1
  h11==0.16.0
  httpcore2==2.12.0
  httpx2==2.12.0
  idna==3.19
  iniconfig==2.3.0
  jsonschema==4.26.0
  jsonschema-specifications==2025.9.1
  mcp==2.1.1
  mcp-types==2.1.1
  olefile==0.47
  opentelemetry-api==1.44.0
  packaging==26.3
  pefile==2024.8.26
  pluggy==1.6.0
  psutil==7.2.2
  pycparser==3.0
  pydantic==2.13.5
  pydantic_core==2.46.5
  Pygments==2.21.0
  PyJWT==2.13.0
  pytest==9.1.1
  pytest-asyncio==1.4.0
  pytest-cov==7.1.0
  python-multipart==0.0.32
  pywin32==312
  pywinauto==0.6.9
  referencing==0.37.0
  rpds-py==2026.6.3
  six==1.17.0
  sse-starlette==3.4.10
  starlette==1.6.0
  truststore==0.10.4
  typing-inspection==0.4.4
  typing_extensions==4.16.0
  uiautomation==2.0.29
  uvicorn==0.52.4
  ```

---

## 6. .NET SDK Environment Proof

### 6.1 `dotnet --version`
- **Command**:
  ```cmd
  dotnet --version
  ```
- **Timestamp**: `2026-09-03T20:17:08Z`
- **Exit Code**: `0`
- **Output**:
  ```text
  11.0.100-preview.7.26381.103
  ```

### 6.2 `dotnet --list-sdks`
- **Command**:
  ```cmd
  dotnet --list-sdks
  ```
- **Timestamp**: `2026-09-03T20:17:08Z`
- **Exit Code**: `0`
- **Output**:
  ```text
  11.0.100-preview.7.26381.103 [C:\Program Files\dotnet\sdk]
  ```

### 6.3 Comprehensive `dotnet --info`
- **Command**:
  ```cmd
  dotnet --info
  ```
- **Timestamp**: `2026-09-03T20:19:16Z`
- **Exit Code**: `0`
- **Output**:
  ```text
  .NET SDK:
   Version:           11.0.100-preview.7.26381.103
   Commit:            e2c1e00b3d
   Workload version:  11.0.100-manifests.2ce71a7f
   MSBuild version:   18.10.0-1.26381.103+e2c1e00b3

  Runtime Environment:
   OS Name:     Windows
   OS Version:  10.0.26200
   OS Platform: Windows
   RID:         win-x64
   Base Path:   C:\Program Files\dotnet\sdk\11.0.100-preview.7.26381.103

  .NET workloads installed:
  There are no installed workloads to display.
  Configured to use workload sets when installing new manifests.
  No workload sets are installed. Run "dotnet workload restore" to install a workload set.

  Host:
    Version:      11.0.0-preview.7.26381.103
    Architecture: x64
    Commit:       e2c1e00b3d

  .NET SDKs installed:
    11.0.100-preview.7.26381.103 [C:\Program Files\dotnet\sdk]

  .NET runtimes installed:
    Microsoft.AspNetCore.App 11.0.0-preview.7.26381.103 [C:\Program Files\dotnet\shared\Microsoft.AspNetCore.App]
    Microsoft.NETCore.App 11.0.0-preview.7.26381.103 [C:\Program Files\dotnet\shared\Microsoft.NETCore.App]
    Microsoft.WindowsDesktop.App 11.0.0-preview.7.26381.103 [C:\Program Files\dotnet\shared\Microsoft.WindowsDesktop.App]

  Other architectures found:
    None

  Environment variables:
    Not set

  global.json file:
    Not found
  ```

---

## 7. Verification Sign-Off
All 5 prerequisite categories have been verified with 100% concordance against project specifications. The host machine is verified for Horner Cscape automation and MCP operations.
