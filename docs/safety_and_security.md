# Safety, Security, and Hardware Lockout Specification

## 1. Safety Philosophy & Threat Model

Industrial control systems operate high-voltage switchgear, pneumatic actuators, hydraulic pumps, and automated factory machinery. In an autonomous software engineering environment driven by Large Language Models (LLMs) and agentic workflows, **unintended physical execution or unauthorized controller firmware flashing carries severe risk to human safety, capital equipment, and operational continuity**.

To eliminate these risks completely, the Horner Cscape MCP architecture implements an **Absolute Hardware Lockout Policy**.

```mermaid
graph TD
    subgraph "Untrusted / Agent Operations"
        A[AI Model Generation]
        B[Automation Scripts]
        C[CLI Commands]
    end

    subgraph "Safety Guard Barrier"
        SG1{Hardware Port Interceptor}
        SG2{Dangerous Binary Blocker}
        SG3{Download Flag Interceptor}
        SG4{Path Traversal Sanitizer}
    end

    subgraph "Physical World (AIR-GAPPED)"
        P1[COM Ports COM1-COM256]
        P2[CAN / CsCAN Adapters]
        P3[USB DFU / Bootloader]
        P4[Physical OCS Controllers]
    end

    subgraph "Authorized Local Execution (Four Pillars)"
        L1[Pure Software Simulator (Horner OCS Registers)]
        L2[Real Cscape 10.2 Automation (Win32 ID_PROGRAM_ERRORCHECK 32826)]
        L3[Native CFBF Inspector & Pure-Python AST Validator]
        L4[Sandboxed Workspace Artifacts]
    end

    A --> SG1
    B --> SG2
    C --> SG3

    SG1 -.->|BLOCKED & INTERCEPTED| P1
    SG1 -.->|BLOCKED & INTERCEPTED| P2
    SG2 -.->|BLOCKED & INTERCEPTED| P3
    SG3 -.->|BLOCKED & INTERCEPTED| P4

    SG1 ==>|PASSED| L1
    SG2 ==>|PASSED| L2
    SG3 ==>|PASSED| L3
    SG3 ==>|PASSED| L4
```

---

## 2. Hardware Port Interception

Any attempt by tools, scripts, or subprocesses to open or communicate across physical hardware interfaces is intercepted and refused at runtime:

### 1. Serial COM Ports
- **Target Patterns**: `COM1` through `COM256`, `\\.\COM*`, `/dev/ttyS*`, `/dev/ttyUSB*`.
- **Enforcement**: Regular expression pattern matching on all connection strings and CLI arguments.
- **Action**: Raises `SecurityError("Direct hardware COM port access is strictly prohibited by Safety Policy")`.

### 2. CAN / CsCAN Adapters
- **Target Patterns**: Peak CAN (`pcan`), Vector Informatik (`vcan`), Kvaser, Horner HE-GSM / CsCAN USB adapters.
- **Enforcement**: Parameter sanitization and network adapter blocklists.
- **Action**: Rejection of controller download and fieldbus monitor attachment requests.

### 3. JTAG & Debug Interfaces
- **Target Interfaces**: Segger J-Link, ST-Link, WinJTAG, OpenOCD boundary scan ports.
- **Enforcement**: Immediate process kill and command refusal.

---

## 3. Dangerous Binary & Download Flag Interception

### Prohibited Flashing Binaries
The following binaries, located within the Cscape installation or system path, are prohibited from execution:

| Disallowed Binary | Mechanism / Purpose | Threat Prevented |
| :--- | :--- | :--- |
| `PGMUpdateUtility.exe` | Horner OCS firmware updater | Unintended controller firmware overwrite |
| `DfuSeCommand.exe` | STMicroelectronics USB DFU utility | Low-level STM32 bootloader flashing |
| `STMFlashLoader.exe` | STM UART system memory bootloader | ROM/Flash memory modification |
| `WinJTAG.exe` | Hardware JTAG boundary scan programmer | Direct hardware memory injection |

*Any attempt to execute these binaries raises `UnsafeProcessError`.*

### Intercepted CLI Flags
The process runner audits all argument sequences passed to `Cscape.exe` or toolchain utilities. The following flags are unconditionally rejected:
- Download flags: `/d`, `/download`, `/flash`, `/burn`, `/prog`, `/program_target`.
- Firmware flags: `/firmware`, `/update_fw`, `/erase_all`.
- Force communication flags: `/connect`, `/online_monitor`, `/run_target`.

---

## 4. Path Traversal & Workspace Isolation

To prevent directory traversal attacks or unauthorized file modification outside the project boundary:

1. **Project Name Sanitization**:
   - Project names are constrained to strict alphanumeric characters, underscores, and hyphens (`^[a-zA-Z0-9_\-]+$`).
   - Relative path tokens (`..`, `/`, `\`, `:`, `~`) are rejected with `SecurityError`.
2. **Canonical Workspace Confinement**:
   - All generated files (`.csp`, `.cpj`, `.st`, `.csv`, `.xml`) must resolve strictly within `C:\HornerAI\horner-cscape-mcp\artifacts\`.
   - Any path resolving outside the workspace directory structure is rejected.
   - Note: Legacy standalone Straton K5 files (`.k5p`, `.CPO`, `.XTI`, `.XWS`) are quarantined under `quarantine/straton_k5_legacy/`.

---

## 5. Pure Software Verification & Testing Matrix

Safety enforcement is verified through an automated test suite comprising **192 dedicated security test cases** (`tests/test_security.py`):

| Test Suite Category | Test Count | Scope of Verification |
| :--- | :--- | :--- |
| `TestHardwarePortLockout` | 48 tests | Validates interception of COM1-COM256, device URIs, and CAN adapters. |
| `TestDownloadUtilityLockout` | 32 tests | Confirms immediate blocking of PGMUpdateUtility, DfuSeCommand, STMFlashLoader, WinJTAG. |
| `TestDownloadFlagsLockout` | 24 tests | Audits CLI flag filter for `/d`, `/flash`, `/burn`, `/update`. |
| `TestPathTraversalGuard` | 36 tests | Tests directory traversal attempts (`..`, absolute system paths, null bytes). |
| `TestSecurityDecorators` | 28 tests | Verifies that `@enforce_safety_lockout` decorators protect all API entry points. |
| `TestSimulationIsolation` | 24 tests | Confirms simulator executes in-memory without invoking external Windows sockets or hardware drivers. |

**Result**: 192 / 192 safety tests pass with zero exceptions.

---

## 6. Supported Controller Hardware Models & Straton Deprecation (H04 & H05)

### 6.1 Modern Horner OCS Controller Allowlists (`ALLOWED_CONTROLLER_MODELS` & `ALLOWED_TARGETS`)
The MCP schemas (`src/mcp/schemas.py:ALLOWED_CONTROLLER_MODELS`) and security guard (`src/security/guard.py:ALLOWED_TARGETS`) strictly allowlist modern Horner OCS controller models for simulation and project targeting:

| Controller Family | Supported Models | Description |
| :--- | :--- | :--- |
| **EXL Series** | `EXL10`, `EXL6` | 10.4" and 6" High-Performance Color-Touch OCS |
| **XL Series** | `XL10`, `XL+`, `XL4`, `XL7`, `XLE` | Standard & Wide Screen Color-Touch OCS |
| **Micro OCS Series**| `Micro OCS`, `MICRO OCS`, `X2`, `X4`, `X5`, `X7` | Compact All-In-One Graphic OCS |
| **Specialized & Coprocessor** | `RCC972`, `ZX` | Remote Control Station & High-Speed Coprocessors |
| **Simulation / Software** | `SIMULATION`, `SIM`, `SOFTWARE` | In-memory scan cycle test harness targets |

### 6.2 Deprecated Legacy Straton K5 Targets (`T5RTI`, `T5SIMUL`)
- **Quarantine Status**: Standalone Straton K5 runtime targets (`T5RTI`, `T5SIMUL`) are permanently deprecated and quarantined under `quarantine/straton_k5_legacy/`.
- **Runtime Deprecation Warning**: Invoking project creation or targeting with `T5RTI` or `T5SIMUL` emits an explicit Python `DeprecationWarning` advising migration to modern Horner OCS families (`EXL10`, `XL10`, `XL+`, `Micro OCS`, `X2-X7`).
- **Synthetic File Rejection**: Standalone Straton project definitions (`appli.k5p`, `appli.CPO`) are rejected; native Cscape workflows exclusively operate on Compound File Binary Format (`.csp`/`.cpj`) containers and `cscape_project.json`.

