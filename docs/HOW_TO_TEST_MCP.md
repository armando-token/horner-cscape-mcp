# How to Test the Horner Cscape Model Context Protocol (MCP) Server

**Operational Mode**: `offline/DEV [PRODUCT_EVIDENCE]`  
**Hardware Lockout**: `NO_PLC_DOWNLOAD_FAIL_CLOSED`  
**Live Telemetry Reality**: `verified_live: false` (Zero live PLC claims; pure-software simulation & offline forensics)  
**Single GUI Boundary**: Exclusive access on `winsta0\Default` (Cscape PID `12788`, HWND `3016360`)  

---

## 1. Overview & Testing Philosophy

The Horner Cscape MCP server provides programmatic JSON-RPC 2.0 integration between AI agents, automation clients, and Horner APG Cscape 10.2. Testing is partitioned into two distinct verification modes:

1. **Pure-Software Offline Testing (Tiers 1, 3, and 4)**:
   - 100% deterministic, executed in-memory or against native Compound File Binary Format (CFBF `.csp`/`.cpj`) files.
   - Evaluates pure IEC 61131-3 Structured Text ASTs, Horner OCS memory allocations (`%R`, `%AI`, `%AQ`, `%I`, `%Q`, `%M`), Modbus RTU inventories, and air-gapped evidence packaging.
   - Requires zero PLC hardware and zero live desktop interaction.

2. **Live Cscape 10.2 GUI Verification (Tier 2 - Honest Partial)**:
   - Interacts with real `Cscape.exe` (Build 10.2.751.4) via Win32 messaging (`WM_COMMAND`) and UIAutomation 3.0.
   - Restricted strictly to the **Single GUI Owner** on the interactive desktop (`winsta0\Default`).
   - Evaluates project reopening, Error Check compilation (`ID_PROGRAM_ERRORCHECK = 32826`), and modal `#32770` dialog suppression.

---

## 2. Environment Setup

### 2.1 Prerequisites
- **Operating System**: Windows 10/11 (x64) or Windows Server.
- **Python**: Python 3.12 (64-bit) recommended.
- **Virtual Environment**:
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  pip install -e .
  ```
- **Cscape 10.2 Host** (for Tier 2 GUI tests): Horner APG Cscape 10.2 (Build 10.2.751.4) installed at standard location `C:\Program Files (x86)\Horner APG\Cscape\Cscape.exe`.

---

## 3. Running MCP Server Locally

Launch the FastMCP server over `stdio` transport:
```powershell
& ".\.venv\Scripts\python.exe" "scripts\run_mcp_server.py"
```

### AI Client Configuration Example (`claude_desktop_config.json` / `antigravity.json`)
```json
{
  "mcpServers": {
    "horner-cscape": {
      "command": "C:\\HornerAI\\horner-cscape-mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\HornerAI\\horner-cscape-mcp\\scripts\\run_mcp_server.py"],
      "env": {
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

---

## 4. Key MCP Tool Verification Workflows

### 4.1 Pure ST Syntax & Ladder Rejection (`cscape_validate_st`)
Test that pure IEC 61131-3 Structured Text is accepted while legacy Advanced Ladder constructs are strictly rejected:

- **Valid Pure ST Input**:
  ```pascal
  PROGRAM TankLevelControl
  VAR
      TankLevelPV AT %AI1 : REAL;
      HighAlarm AT %M1 : BOOL;
  END_VAR
  IF TankLevelPV >= 85.0 THEN
      HighAlarm := TRUE;
  ELSE
      HighAlarm := FALSE;
  END_IF;
  END_PROGRAM
  ```
  *Expected Result*: `status: "success"`, `valid: true`, `errors: []`.

- **Forbidden Ladder Construct Input**:
  ```pascal
  ---[ ]--- %I1 ---[ / ]--- %I2 ---( )--- %Q1
  ```
  *Expected Result*: `status: "failed"`, `error_code: "ERR_LADDER_FORBIDDEN"`, zero disk mutation.

---

### 4.2 Scan-List Inspection & Fail-Closed Behavior (`cscape_inspect_scan_list`)
The tool inspects the native CFBF stream for configured Modbus RTU scan transactions:

1. **Baseline Inspection (`require_populated=False`)**:
   ```json
   {
     "project_path": "artifacts/projects/TankLevel_P5_Dedicated/TankLevel_P5_Dedicated.csp",
     "port": "MJ1",
     "require_populated": false
   }
   ```
   *Output*:
   ```json
   {
     "status": "success",
     "port": "MJ1",
     "driver": "MJ1 CT RTU Modbus CMP v5.05",
     "scan_list_status": "empty",
     "count": 0,
     "native_fill_status": "blocked_offline",
     "planned_devices_sidecar": "modbus_protocol_inventory.json"
   }
   ```

2. **Fail-Closed Assertion (`require_populated=True`)**:
   ```json
   {
     "project_path": "artifacts/projects/TankLevel_P5_Dedicated/TankLevel_P5_Dedicated.csp",
     "port": "MJ1",
     "require_populated": true
   }
   ```
   *Output*:
   ```json
   {
     "status": "blocked",
     "error_code": "SCAN_LIST_EMPTY_OFFLINE",
     "details": "Native scan list is empty offline. Population deferred to Phase P7 manual field commissioning."
   }
   ```

---

### 4.3 Scan-List Reconciliation (`cscape_reconcile_scan_list`)
Audits planned transactions in `modbus_protocol_inventory.json` (3 devices: `%AI1` Tank Level, `%AI2` Inflow Rate, `%AI3` Discharge Pressure) against the native container (0 entries):
- *Output*: `status: "success"`, `planned_count: 3`, `native_count: 0`, `discrepancy_delta: -3`, `classification: "DISCREPANCY_EXPLAINED_OFFLINE_LOCKOUT"`.

---

### 4.4 In-Memory Deterministic Plant Simulation (`cscape_run_simulation`)
Executes closed-loop simulation cycles without hardware:
```json
{
  "project_name": "TankLevel_P5_Dedicated",
  "steps": 100,
  "inputs": {
    "%AI1": 17600
  }
}
```
*Expected Result*: Evaluates scan cycles, updates `%R101` (scaled PV = 55.0%), checks high/low alarm triggers, and verifies zero memory leaks.

---

### 4.5 Security Lockout Verification (`test_security.py`)
Verifies fail-closed hardware ban:
1. **Serial Port Attempt**: Connecting to `COM1` through `COM256` raises `HardwareLockoutError`.
2. **Download Command Attempt**: Dispatching Win32 command IDs `32827` (`ID_PROGRAM_DOWNLOAD`) or `33149` (`ID_CONTROLLER_DOWNLOAD`) returns `status: "blocked"`.

---

## 5. Summary of Governance Invariants

- **`verified_live: false`**: Never simulate or claim live hardware verification in automated test runs.
- **`plc_download: false`**: Never attempt automated controller flashing.
- **`no_error_check_loop: true`**: Do not launch periodic polling loops against the Cscape compiler.
- **Single GUI Boundary**: Only one test process may hold handles on `winsta0\Default`.
