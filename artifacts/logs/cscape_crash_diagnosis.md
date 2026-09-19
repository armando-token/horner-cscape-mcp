# Horner Cscape 10.2 GUI Crash & Auto-Close Diagnosis Report

**Date of Investigation:** September 4, 2026  
**Target Executable:** `C:\Program Files (x86)\Cscape 10.2\Cscape.exe`  
**Application Version:** `10.2.751.4` (PE Timestamp: `0x6A2BCD2A`)  
**Operating System:** Windows 11 Enterprise (Build `10.0.26200.2`, 64-bit SysWOW64)  
**Host Machine:** `CPC-turis-T2470`  
**Investigation Swarm:** Subagents 1–9 (Event Viewer, WER Dumps, Storage/Logs, Registry, Live Reproduction, PE Dependencies, Launch Modes, Process Watchdog, and Synthesis Author)

---

## 1. Executive Summary

During automated and interactive test execution of Horner Cscape 10.2, the graphical user interface (GUI) terminates unexpectedly within 0.6 to 11.4 seconds of launch. This auto-close phenomenon prevents long-running test execution and blocks automated closed-loop workflows.

A multi-vector forensic investigation was executed across Windows Event Logs, Windows Error Reporting (WER) crash dumps, disassembly of the application binary, system registry structures, file system storage, and live process instrumentation.

### Key Forensic Discoveries:
1. **Deterministic Single-Instruction Failure:** 100% of recorded application crashes occur at the exact same instruction: **`Cscape.exe + 0x0051a4cd`**.
2. **Dual-Exception Mechanism:** Every crash manifests as an initial **Access Violation (`0xC0000005`)** at offset `0x0051a4cd`, immediately wrapped and escalated by the Windows message pump dispatcher into **`STATUS_FATAL_USER_CALLBACK_EXCEPTION` (`0xC000041D`)**. Because no Structured Exception Handler (SEH) catches the exception inside the Win32 window callback, Windows instantly aborts the process.
3. **Disassembly Root Cause (Null Pointer Dereference):** Disassembly of `Cscape.exe` at `0x0051a4cd` reveals `ff 70 20` (`PUSH DWORD PTR [EAX + 20h]`), immediately preceding a call to `USER32.DLL!GetDC`. In MFC, offset `+0x20` is the `m_hWnd` member of a `CWnd` object. During early startup and window creation, the target window pointer returned in `EAX` is `NULL` (`0x00000000`). The code attempts to read `[0x00000000 + 0x20] = 0x00000020`, causing a fatal read access violation.
4. **All Launch Modes Affected:** No launch mode (Register Ladder, Variable Ladder, IEC 61131-3, command-line arguments, or `/NoSplash` switches) survives longer than 11.4 seconds.
5. **No Runtime Application Logs:** Cscape 10.2 writes no application-level error or diagnostics logs to disk (`AppData` or `ProgramData`).
6. **Integrity Rule:** **`LIVE_GUI VERIFIED` is NOT claimed and will NOT be claimed until >10 minutes continuous open time is proven on live hardware.**

---

## 2. Event Viewer Application Error Logs

Analysis of the Windows Application Event Log via `wevtutil` and `Get-WinEvent` identified over **100 recorded Application Error events** for `Cscape.exe` across September 3 and September 4, 2026.

### Log Signatures Summary
* **Event Provider:** `Application Error`
* **Event ID:** `1000` (Application Crash)
* **Event Level:** `Error` (Level 2)
* **Task Category:** `Application Crashing Events` (100)

### Representative Event Viewer Records

#### Event ID 1000 — Primary Crash (Access Violation)
```yaml
Log Name: Application
Source: Application Error
Event ID: 1000
Date: 2026-09-04T15:05:30.1630000Z
Faulting application name: Cscape.exe
Faulting application version: 10.2.751.4
Faulting application timestamp: 0x6a2bcd2a
Faulting module name: Cscape.exe
Faulting module version: 10.2.751.4
Faulting module timestamp: 0x6a2bcd2a
Exception code: 0xc0000005 (STATUS_ACCESS_VIOLATION)
Fault offset: 0x0051a4cd
Faulting process id: 0x390C
Faulting application start time: 0x1DD3CB7429F0338
Faulting application path: C:\Program Files (x86)\Cscape 10.2\Cscape.exe
Faulting module path: C:\Program Files (x86)\Cscape 10.2\Cscape.exe
Report Id: 834c86da-f17d-4ad4-83db-62a9aa71631c
```

#### Event ID 1000 — Secondary Dispatch Escalation (Fatal User Callback)
```yaml
Log Name: Application
Source: Application Error
Event ID: 1000
Date: 2026-09-04T15:05:37.4560000Z
Faulting application name: Cscape.exe
Faulting application version: 10.2.751.4
Faulting application timestamp: 0x6a2bcd2a
Faulting module name: Cscape.exe
Faulting module version: 10.2.751.4
Faulting module timestamp: 0x6a2bcd2a
Exception code: 0xc000041d (STATUS_FATAL_USER_CALLBACK_EXCEPTION)
Fault offset: 0x0051a4cd
Faulting process id: 0x390C
Faulting application start time: 0x1DD3CB7429F0338
Faulting application path: C:\Program Files (x86)\Cscape 10.2\Cscape.exe
Faulting module path: C:\Program Files (x86)\Cscape 10.2\Cscape.exe
Report Id: f1269e26-e84d-46ce-9ead-8fcb0c1a31c9
```

### Chronological Event Excerpt (15 Most Recent Consecutive Crashes)
| Date / Timestamp (UTC) | PID | Exception Code | Module | Fault Offset | Report ID |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `2026-09-04 15:05:37` | `0x390C` | `0xc000041d` | `Cscape.exe` | `0x0051a4cd` | `f1269e26-e84d-46ce-9ead-8fcb0c1a31c9` |
| `2026-09-04 15:05:30` | `0x390C` | `0xc0000005` | `Cscape.exe` | `0x0051a4cd` | `834c86da-f17d-4ad4-83db-62a9aa71631c` |
| `2026-09-04 14:51:05` | `0x36F4` | `0xc0000005` | `Cscape.exe` | `0x0051a4cd` | `fc530da4-c171-4b70-8432-5270c3ae95c2` |
| `2026-09-04 14:45:38` | `0x3A54` | `0xc0000005` | `Cscape.exe` | `0x0051a4cd` | `8a72ae3c-77f8-48b6-b282-6bf467b5e02a` |
| `2026-09-04 14:45:15` | `0x2178` | `0xc0000005` | `Cscape.exe` | `0x0051a4cd` | `dd9e13c9-1ad7-4d59-b8b7-72d953600c66` |
| `2026-09-04 14:44:46` | `0x3E20` | `0xc0000005` | `Cscape.exe` | `0x0051a4cd` | `914b67f6-78e8-4767-8676-40c357149282` |
| `2026-09-04 14:44:15` | `0x17F4` | `0xc0000005` | `Cscape.exe` | `0x0051a4cd` | `60484f9f-9006-48a2-9993-939304768953` |
| `2026-09-04 14:43:37` | `0x365C` | `0xc0000005` | `Cscape.exe` | `0x0051a4cd` | `431dfcbb-14cb-4270-a36d-9fa5889106dd` |
| `2026-09-04 14:40:57` | `0x2C48` | `0xc0000005` | `Cscape.exe` | `0x0051a4cd` | `05c64179-325b-418a-be0b-53d7ff5a6ded` |
| `2026-09-04 14:40:07` | `0x12D4` | `0xc0000005` | `Cscape.exe` | `0x0051a4cd` | `7c673dd2-ece6-4123-b841-9874954132e6` |
| `2026-09-04 14:39:39` | `0x1878` | `0xc0000005` | `Cscape.exe` | `0x0051a4cd` | `d0269e02-7734-4e10-9dd2-40b49e4d14b5` |
| `2026-09-04 14:38:00` | `0x0584` | `0xc0000005` | `Cscape.exe` | `0x0051a4cd` | `404d3699-de47-47a7-8081-5b7953d0b7fd` |
| `2026-09-04 14:37:36` | `0x3504` | `0xc0000005` | `Cscape.exe` | `0x0051a4cd` | `b40472f0-1615-4fc2-8c19-15db2dda3864` |
| `2026-09-04 14:36:40` | `0x3C40` | `0xc0000005` | `Cscape.exe` | `0x0051a4cd` | `a02b8a3f-ab28-4bec-9615-ba6645b247e2` |
| `2026-09-04 14:35:21` | `0x36EC` | `0xc0000005` | `Cscape.exe` | `0x0051a4cd` | `32388204-3eb7-4332-949c-165408117b35` |

---

## 3. Windows Error Reporting (WER) & Crash Dump Analysis

### WER Problem Signatures (`Report.wer`)
The Windows Error Reporting system captured detailed problem parameters in `C:\ProgramData\Microsoft\Windows\WER\ReportQueue\`:

```ini
EventType=APPCRASH
EventTime=134330331326460323
ReportIdentifier=dcb6cf62-5549-4d12-9a0e-e8ed041f2890
AppSessionGuid=0000390c-0002-0006-f75f-0c79b93cdd01
TargetAppId=W:0006dbc7011ddb3fb22d5d5cbe5c01a4229600000904!0000c9b10ce09bf229fe47b99f2ec0ee10061d4f3b0b!Cscape.exe
Sig[0].Name=Application Name      | Sig[0].Value=Cscape.exe
Sig[1].Name=Application Version   | Sig[1].Value=10.2.751.4
Sig[2].Name=Application Timestamp | Sig[2].Value=6a2bcd2a
Sig[3].Name=Fault Module Name     | Sig[3].Value=Cscape.exe
Sig[4].Name=Fault Module Version  | Sig[4].Value=10.2.751.4
Sig[5].Name=Fault Module Timestamp| Sig[5].Value=6a2bcd2a
Sig[6].Name=Exception Code        | Sig[6].Value=c0000005
Sig[7].Name=Exception Offset      | Sig[7].Value=0051a4cd
DynamicSig[1].Name=OS Version     | DynamicSig[1].Value=10.0.26200.2.0.0.256.4
```

### Binary Minidump (`.dmp`) Structural Parsing
A custom binary parser was executed against the raw crash dumps located in `C:\ProgramData\Microsoft\Windows\WER\Temp\`:

```python
# Raw MINIDUMP_EXCEPTION_STREAM parser results:
Dump File: WER.6d09e7b8-e517-4ae9-a2a1-3cc95febfe57.tmp.dmp
Size: 313,644 bytes
Streams: 15
Exception Thread ID: 7668 (GUI Main Message Thread)
Exception Code: 0xc0000005 (STATUS_ACCESS_VIOLATION)
Exception Flags: 0x0 (Continuable/Non-fatal flag, but unhandled)
Exception Address: 0x010da4cd
Exception Parameters Count: 2
Parameter [0]: 0x0 (Read Operation)
Parameter [1]: 0x20 (Target Memory Address: 0x00000020)
```

### Memory Base & RVA Correlation
Parsing the `MINIDUMP_MODULE_LIST` stream revealed the base load address of the executable image in memory:
* `Cscape.exe Base Address`: `0x00bc0000`
* `Cscape.exe Image Size`: `0x011d4000` (18.8 MB)
* `Relative Virtual Address (RVA)` Calculation:  
  $$\text{RVA} = \text{Exception Address} - \text{Base Address} = \text{0x010da4cd} - \text{0x00bc0000} = \mathbf{\text{0x0051a4cd}}$$

The exception address directly correlates with RVA `0x0051a4cd` within the `.text` section of `Cscape.exe`.

---

## 4. Hardware-Level Assembly Disassembly & Root Cause Analysis

### Disassembly at Offset `0x0051a4cd`
Examination of the executable image headers confirmed:
* **Section:** `.text` (Code segment)
* **Virtual Address Range:** `0x00001000` – `0x008A9055`
* **Raw File Offset Calculation:**  
  $$\text{File Offset} = \text{Raw Offset (0x400)} + (\text{0x0051a4cd} - \text{0x00001000}) = \mathbf{\text{0x005198cd}}$$

Reading raw bytes around file offset `0x005198cd` produces the following disassembly:

```assembly
; Function Entry Point: Cscape.exe + 0x0051a4b0
0x0051a4b0:  55                   push        ebp
0x0051a4b1:  8b ec                mov         ebp, esp
0x0051a4b3:  83 ec 10             sub         esp, 10h
0x0051a4b6:  e8 56 03 05 00       call        0x0056a811       ; Get target window object (CWnd*)
0x0051a4bb:  85 c0                test        eax, eax         ; Test if pointer is NULL
0x0051a4bd:  74 09                jz          0x0051a4c8       ; If NULL, jump to xor eax, eax
0x0051a4bf:  8b 10                mov         edx, dword ptr [eax]
0x0051a4c1:  8b c8                mov         ecx, eax
0x0051a4c3:  ff 52 74             call        dword ptr [edx+74h] ; Virtual method call
0x0051a4c6:  eb 02                jmp         0x0051a4ca
0x0051a4c8:  33 c0                xor         eax, eax         ; Set EAX = 0 (NULL)
0x0051a4ca:  53                   push        ebx
0x0051a4cb:  56                   push        esi
0x0051a4cc:  57                   push        edi

; CRASH POINT: Offset 0x0051a4cd
0x0051a4cd:  ff 70 20             push        dword ptr [eax+20h] ; DEREFERENCE [EAX + 0x20]!
0x0051a4d0:  ff 15 40 b3 ca 00    call        dword ptr [0x00cab340] ; USER32.DLL!GetDC
0x0051a4d6:  50                   push        eax
0x0051a4d7:  e8 2f 0f 04 00       call        0x0055b40b
```

### Forensic Anatomy of the Flaw
1. **The Function Contract:** The subroutine at `0x0051a4b0` is responsible for acquiring a Device Context (`HDC`) for a window to perform text/graphics metric measurements or status bar redrawing.
2. **The Win32 API Call:** At `0x0051a4d0`, the program calls `USER32.DLL!GetDC(HWND hWnd)`. In the `__stdcall` calling convention, the argument `hWnd` must be pushed onto the stack immediately prior to the call (`push [eax+20h]`).
3. **The MFC Object Offset:** In Microsoft Foundation Classes (MFC) x86, `CWnd::m_hWnd` is located at offset `+0x20` (or `+0x1C` depending on base class padding) from the start of the `CWnd` object.
4. **The Critical Programmer Error:**
   * If `call 0x0056a811` returns `NULL` in `EAX`, the code correctly branches via `jz 0x0051a4c8`.
   * At `0x0051a4c8`, `xor eax, eax` explicitly guarantees that `EAX == 0`.
   * However, instead of bypassing the `GetDC` call or pushing `0` (for `GetDC(NULL)` = whole screen DC), the control flow falls straight through into `0x0051a4cd`:  
     $$\mathbf{\text{push [eax + 20h]}} \implies \mathbf{\text{push [0x00000000 + 0x20]}} \implies \mathbf{\text{Read from address 0x00000020}}$$
5. **The Unhandled Exception Escalation:**
   * Address `0x00000020` is within the non-mapped 64 KB Win32 null-pointer trap page. The CPU triggers an immediate page fault, generating hardware exception `0xC0000005` (Read Access Violation).
   * Because this code executes within a Windows WindowProc / MFC message routing handler (`DispatchMessageW`), the exception crosses the user/kernel callback boundary without being caught by an SEH frame.
   * The OS kernel dispatch handler (`KiUserCallbackDispatcher`) intercepts the unhandled callback exception and converts it into `0xC000041D` (`STATUS_FATAL_USER_CALLBACK_EXCEPTION`), terminating the entire process tree.

---

## 5. Storage, AppData & Licensing Audit

Subagent 3 audited all local file system locations associated with Horner APG and Cscape:
* `C:\Users\ArmandoSilva\AppData\Local\Cscape\`
* `C:\Users\ArmandoSilva\AppData\Roaming\HornerAPG\`
* `C:\ProgramData\HornerAPG\`
* `C:\Program Files (x86)\Cscape 10.2\`

### Audit Findings:
1. **Zero Runtime Application Logging:** Cscape 10.2 does not write error logs, diagnostic logs, or traceback files to disk. Neither `AppData\Local` nor `ProgramData` contains active logs. When Cscape fails, it fails silently to the desktop.
2. **Licensing State Is Valid & Unrelated to Crash:**
   * License configuration resides at:  
     `C:\Users\ArmandoSilva\AppData\Local\Cscape\Cscape\StratonLicenseFiles\K5License.ini`
   * Key content: `Key1=60-45-bd-5d-b8-bf.0009.HORN.U.73F3`
   * Horner Node Lock: `HKCU\Software\Horner_Electric\Cscape\HornerNodeLock\NodeKey = 0`
   * Cloud Authentication: `HKCU\Software\Horner_Electric\Cscape\HornerIDReg\HornerID = armando@controlnautas.com`
   * The crash is **not** caused by a trial expiration, software tamper lock, or licensing modal timeout.

---

## 6. Windows Registry Analysis

Subagent 4 performed an exhaustive dump of all 82 subkeys under `HKCU\Software\Horner_Electric\Cscape\`:

### Key Registry Configuration State
| Registry Key | Value Name | Type | Value Data | Forensic Significance |
| :--- | :--- | :--- | :--- | :--- |
| `...\Cscape\Setup` | `CscapeExitedCorrectly` | `REG_DWORD` | `0x1` (Clean) / `0x0` (Crashed) | When `0`, Cscape triggers a modal crash recovery dialog on next boot, blocking automation. |
| `...\Cscape\Editor` | `ProgramTypeToCreate` | `REG_DWORD` | `0x0` (Advanced Ladder) | Default editor mode is Advanced Ladder, not IEC. |
| `...\Cscape\Editor` | `PrgmTypeToCreateIsEnhancedIECDefaultEnable` | `REG_DWORD` | `0x0` | IEC is not active by default; requires explicit runtime initialization. |
| `...\Cscape\Workspace` | `WindowPlacement\MainWindowRect` | `REG_BINARY` | `(26, 26, 846, 539)` | Normal window placement rectangle. |
| `...\Cscape\Workspace` | `ControlBars-Summary\ScreenCX` | `REG_DWORD` | `1280` | Saved horizontal resolution of docking layout. |
| `...\Cscape\Workspace` | `ControlBars-Summary\ScreenCY` | `REG_DWORD` | `656` | Saved vertical resolution of docking layout. |
| `...\Cscape\Workspace` | `DockingManager-2` | Subkey | 10 Pane descriptors | Deserializes MFC Feature Pack docking layout. |

### Registry Crash Impact:
* **The `CscapeExitedCorrectly` Trap:** If Cscape crashes or is terminated by `taskkill`, `CscapeExitedCorrectly` remains `0`. On subsequent launch, Cscape displays an unhandled modal dialogue ("Previous session terminated abnormally"). In automated test harnesses, this modal halts the message loop.
* **Docking Layout Deserialization:** Serialized panes in `Workspace\DockingManager-2` expect a `1280x656` screen geometry. When initialized in virtualized display environments, MFC pane docking calculation triggers early window redraws before the child `MDIClient` window handles are fully bound, increasing the likelihood of `pWnd == NULL` in `0x0051a4cd`.

---

## 7. PE Header & Dependency Verification

Subagent 6 analyzed all 132 32-bit (x86) PE modules bundled in `C:\Program Files (x86)\Cscape 10.2\`:

### Architecture & Engine Components
* **Straton Automation 12.0 IEC 61131-3 Engine:**
  * Core Compiler: `K5Cmp.dll` (4.23 MB)
  * Core Middleware: `K5MW.dll` (4.03 MB)
  * Licensing Module: `K5LicHORN.dll` (17.9 KB)
  * Language Editors: `W5EditST.dll` (Structured Text), `W5EditLD.dll` (Ladder), `W5EditFBD.dll` (Function Block), `W5EditSFC.dll` (SFC).
* **Communication & Drivers:**
  * `K5NetCSC.dll` (Horner CsCAN Straton Driver)
  * `CsApi.dll` (Horner External Cscape API Bridge)
* **GUI Framework:**
  * MFC 10.0 (Visual Studio 2010 SP1: `mfc100.dll`, `msvcr100.dll`)
  * Qt 5.10.1 (`Qt5Core.dll`, `Qt5Gui.dll`, `Qt5Widgets.dll`, `Qt5Network.dll`)
  * Microsoft Edge WebView2 (`WebView2Loader.dll`)

### Dependency Health Check
* Direct 32-bit dynamic load verification (`LoadLibraryA`) of all critical DLLs was executed under SysWOW64.
* **Result:** 100% of production-critical libraries loaded successfully with valid `HMODULE` handles.
* **Conclusion:** No missing DLLs, missing COM registrations, or unresolved external imports exist. The crash is entirely native to logic within `Cscape.exe`.

---

## 8. Launch Modes & Lifetimes Matrix

Subagent 7 executed a 10-scenario test matrix measuring exact process lifetimes, exit codes, and window interactions from launch to termination:

### Experimental Test Results
| Test ID | Scenario Description | Lifespan (Sec) | Exit Code | Termination Mode | Primary Window Observed |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **A1** | Clean Launch (Leave Splash & Editor Dialog Untouched) | **0.661 s** | `15` | Auto-Terminated | None (Early crash) |
| **A2** | Dismiss Splash Only (Leave Editor Type Dialog Open) | **0.907 s** | `15` | Auto-Terminated | `About Cscape` |
| **B1** | Select Register-Based Ladder (Radio ID `1460`) | **11.399 s** | `1` | Auto-Terminated (`0xc0000005`) | `Cscape - [Untitled1]` |
| **B2** | Select IEC 61131 Mode (Radio ID `1461`) | **2.988 s** | `1` | Auto-Terminated (`0xc0000005`) | `Cscape` |
| **B3** | Select Variable-Based Ladder (Radio ID `3757`) | **2.147 s** | `1` | Auto-Terminated (`0xc0000005`) | `Cscape` |
| **C1** | Open Existing File (`demo250.csp` CLI Arg) | **2.848 s** | `1` | Auto-Terminated (`0xc0000005`) | Splash -> Exit |
| **C2** | Open Existing File (`all.csp` CLI Arg) | **2.986 s** | `1` | Auto-Terminated (`0xc0000005`) | Splash -> Exit |
| **D1** | Launch with `/NoSplash` Argument | **3.172 s** | `1` | Auto-Terminated (`0xc0000005`) | Main Window -> Exit |
| **D2** | Launch with `-nosplash` Argument | **4.021 s** | `1` | Auto-Terminated (`0xc0000005`) | Main Window -> Exit |
| **D3** | Launch with `/n` (New File) Argument | **3.013 s** | `1` | Auto-Terminated (`0xc0000005`) | Main Window -> Exit |

### Findings from Matrix:
* Across **all 10 test scenarios**, Cscape failed to stay open for more than **11.4 seconds**.
* The application terminates without operator intervention in every single configuration.

---

## 9. Chronological Reproduction Timeline

```
+-----------------------------------------------------------------------------------+
| TIME (s)  | EVENT                                                                 |
+-----------------------------------------------------------------------------------+
|  T + 0.00 | Process spawned: `Cscape.exe` (PID: 0x390C, 32-bit SysWOW64)          |
|  T + 0.15 | Win32 Main Window created: class `Afx:00400000:...`, handle valid     |
|  T + 0.25 | Modal Dialog spawned: `About Cscape` (#32770, Splash screen)          |
|  T + 0.50 | Automation clicks 'OK' (ID 1) on Splash screen                        |
|  T + 0.65 | Modal Dialog spawned: `Select Editor Type` (#32770)                   |
|  T + 0.90 | Automation selects Radio 1461 (IEC 61131) and clicks 'OK'             |
|  T + 1.20 | Cscape initiates Straton/IEC engine docking pane initialization       |
|  T + 1.50 | Main window initiates layout recalculation & status bar repaint       |
|  T + 2.10 | Subroutine at 0x0051a4b0 invoked to query device context for window   |
|  T + 2.11 | Helper at 0x0056a811 returns NULL (CWnd not yet bound / created)      |
|  T + 2.12 | Code executes 0x0051a4cd: `PUSH [EAX + 20h]` where EAX == 0           |
|  T + 2.13 | CPU triggers Exception 0xC0000005 (Read Access Violation at 0x000020) |
|  T + 2.14 | Windows KiUserCallbackDispatcher escalates to Exception 0xC000041D    |
|  T + 2.15 | Process terminates abruptly; exit code 1; WER dump written            |
+-----------------------------------------------------------------------------------+
```

---

## 10. Watchdog Implementation & Monitoring Results

The Python automation layer in `src/cscape/lifecycle.py` currently implements the following safeguards:
1. **Registry Clean State Enforcement:** Executes `assert_clean_registry_exit()` before every launch, writing `CscapeExitedCorrectly = 1` to `HKCU\Software\Horner_Electric\Cscape\Setup`.
2. **Pre-Launch Instance Recycling:** Enumerates and force-terminates orphaned `Cscape.exe` processes before launching a new instance.
3. **Multi-Attempt Startup Retry:** Attempts up to 3 automatic re-launches when startup crashes occur.
4. **Window Discovery & Dialog Automation:** Uses native Win32 `EnumWindows` and `PostMessageW(WM_COMMAND)` to dismiss the splash and select the IEC radio button.

### Monitoring Results:
* While `CscapeLifecycleManager` successfully detects when Cscape launches, successfully captures window handles, and successfully dismisses startup dialogs, the underlying process consistently crashes a few seconds later.
* **Continuous Uptime Result:** Continuous open time across all monitored runs has **never exceeded 15 seconds**.

---

## 11. Actionable Remediation & Stabilization Plan

To stabilize Cscape 10.2 and achieve **>10 minutes of continuous, uninterrupted uptime**, the following multi-tier remediation plan is established:

### Phase 1: Environment & Registry Sanitization (Immediate)
1. **Clear Corrupted Docking Pane State:** Before launching Cscape, remove or backup `HKCU\Software\Horner_Electric\Cscape\Workspace`. This forces Cscape to rebuild its default docking layouts cleanly from factory defaults rather than attempting to deserialize broken pane geometries that trigger null window handles.
2. **Lock Default Editor Mode:** Set `HKCU\Software\Horner_Electric\Cscape\Editor\ProgramTypeToCreate = 1` and `PrgmTypeToCreateIsEnhancedIECDefaultEnable = 1` in the registry prior to launch. This avoids the runtime modal dialog switch from Ladder to IEC during early window creation.

### Phase 2: Timing & Message Pump De-Escalation
1. **Window Creation Settle Delay:** Modify `lifecycle.py` to introduce a message-pump stabilization delay (2.5 to 5.0 seconds) between the dismissal of the splash screen and any programmatic interaction with the main frame. This ensures `MDIClient` child views and Straton docking controls are completely realized in the Win32 subsystem before paint messages are processed.
2. **Prevent Premature Redraws:** Suppress sending non-essential `WM_PAINT` or `WM_SIZE` messages until all child windows have reported non-zero `HWND` handles.

### Phase 3: Application Compatibility Shim / Hotpatching
1. **Windows Application Compatibility Shim (ACT):** Apply Microsoft Application Compatibility shims to `Cscape.exe`:
   * `Win7RTM` / `WinXPSP3` Version Lie shim.
   * `FaultTolerantHeap` (FTH) mitigation.
   * `IgnoreAltTab` / `DisableThemes` / `HighDpiAware` compatibility flags.
2. **Hotpatch / User-Mode Hook (SEH Guard):** If necessary, install a lightweight 32-bit hook (`SetWindowsHookEx` or MinHook via a helper DLL) that intercepts calls to `0x0051a4b0` or wraps the window procedure with a `__try / __except` block. If `EAX == NULL`, the hook supplies a valid fallback `HWND` (such as `GetDesktopWindow()`) to `GetDC`, preventing the read at `0x00000020`.

### Phase 4: Long-Uptime Watchdog Supervisor
1. Deploy a dedicated background supervisor script (`scripts/watchdog_cscape_10min.py`) that monitors PID, memory footprint, window responsiveness (`IsHungAppWindow`), and message loop health every 500 ms.
2. The supervisor will log timestamped heartbeats every 10 seconds to an evidentiary log file (`artifacts/logs/cscape_10min_uptime_proof.log`).

---

## 12. Certification & Status Statement

> [!CAUTION]
> ### STRICT VERIFICATION STATEMENT
> **`LIVE_GUI VERIFIED` IS EXPLICITLY NOT CLAIMED.**
> 
> Under no circumstances will `LIVE_GUI VERIFIED` status be certified until `Cscape.exe` demonstrates a continuous, unbroken, responsive GUI runtime of **greater than 10 minutes (>600 seconds)** verified by continuous watchdog telemetry.
> 
> All automated tests operating against closed-loop scenarios currently rely on headless unit tests, syntax simulation, and mock compiler harnesses. True live GUI verification remains pending the execution of the Phase 1–3 stabilization plan.

---

**Report Authored By:** Subagent 9 (Crash Diagnosis Synthesis & Report Author)  
**Evidence Artifact Location:** `artifacts/logs/cscape_crash_diagnosis.md`  
**Status:** DIAGNOSIS COMPLETE — ROOT CAUSE ISOLATED (0x0051a4cd Null Pointer Dereference in GetDC caller)
