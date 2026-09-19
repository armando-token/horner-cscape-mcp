# Comprehensive Engineering Report: MJ1 Devices and Scan List State

**Mission ID**: `MJ1_DEVICES_AND_SCAN_LIST_STATE_DOCUMENTATION`  
**Task ID**: `OFFLINE_MJ1_DEVICES_AND_SCAN_LIST_STATE_DOCUMENTATION`  
**Target Project Container**: `TankLevel_P5_Dedicated.csp`  
**Target Port**: `MJ1` (Serial RS-485 Half-Duplex)  
**Protocol Driver**: `CT RTU Modbus CMP v5.05` (`Modbus Master v 5.07`)  
**Operational Mode**: `offline/DEV [PRODUCT_EVIDENCE]`  
**Execution Environment**: Pure Software / Zero PLC Connection / Fail-Closed Hardware Lockout  
**System State**: `RUNTIME_PENDING_P7`  
**Fail-Closed Invariants**: `verified_live: false`, `zero_plc_download: true`, `no_error_check_loop: true`  
**Timestamp UTC**: `2026-09-17T21:00:00Z`  
**Dual-Root Mirroring**: `C:\Users\ArmandoSilva` $\longleftrightarrow$ `C:\HornerAI\horner-cscape-mcp`  

---

## 1. Executive Summary

This report delivers comprehensive, authoritative engineering documentation regarding the state of serial port **`MJ1`**, the **`CT RTU Modbus CMP v5.05`** protocol configuration, and the **Scan List table** in native project container **`TankLevel_P5_Dedicated.csp`** (CFBF / OLE2, 140,800 bytes).

Key findings and architectural guarantees:
1. **Configured Port & Driver**: Port `MJ1` is configured with Horner Cscape Modbus RTU Master driver `CT RTU Modbus CMP v 5.05 / Modbus Master v 5.07` operating in Half-Duplex RS-485 at 19200 baud, 8-N-1 framing.
2. **Native Scan List State**: The native project scan list table on port `MJ1` is **confirmed empty** (`count: 0`, `scan_list: []`, `scan_list_status: "empty"`).
3. **Native Fill Status**: Native scan list addition is **blocked offline** (`native_fill_status: "blocked_offline"`).
4. **Offline Blocker Analysis**: Cscape 10.2 (Build 10.2.751.4) requires a responding physical hardware slave node or an online Cscape connection to establish native scan-list table structures. In an offline environment without PLC hardware, attempting direct OLE stream mutation without driver relational descriptors induces project corruption.
5. **Planned Device Inventory**: The sidecar specification `modbus_protocol_inventory.json` defines 3 Modbus RTU slave devices:
   - `DEV_LT01` (Unit ID 1): Buffer Tank Level Transmitter (`%AI1`, 0..100 %, Modicon 40001)
   - `DEV_FT01` (Unit ID 2): Inflow Coriolis Flowmeter (`%AI2`, 0..500 L/min, Modicon 40002)
   - `DEV_PT01` (Unit ID 3): Discharge Pressure Transmitter (`%AI3`, 0..10 bar, Modicon 40003)
6. **Planned vs. Native Reconciliation**: FastMCP tool `cscape_reconcile_scan_list` confirms an offline discrepancy delta of **-3** (`native_count: 0`, `planned_count: 3`, `reconciliation_status: "discrepancy_detected"`, `pending_gate: "P7_PHYSICAL_PLC_DOWNLOAD_AND_COMMISSIONING"`).
7. **Pure ST Scaling Bridge**: The input data path from `%AI1..%AI3` to engineering registers `%R101`, `%R103`, `%R105` is governed offline by pure Structured Text function blocks `FB_ModbusScaleQuality` and `TankLevelModbusBridge`.
8. **Phase P7 Commissioning Deferral**: Native scan list population and physical controller download are strictly deferred to Phase P7 for manual field execution by a commissioning engineer.

---

## 2. Port & Protocol Driver Configuration

Native Cscape hardware configuration details for the MJ1 port:

| Property | Value | Description |
| :--- | :--- | :--- |
| **Port Name** | `MJ1` | Modular Jack 1 (OCS Serial Comm Port) |
| **Interface Standard** | `RS-485` | 2-wire differential half-duplex serial |
| **Protocol Name** | `CT RTU Modbus CMP v5.05` | Cscape Modbus RTU Master Protocol Driver |
| **Driver Specification** | `CT RTU Modbus CMP v 5.05 / Modbus Master v 5.07` | Horner Cscape native DLL driver |
| **Operational Role** | `CLIENT_MASTER_READ_ONLY` | Polling Master (Writes disabled) |
| **Baud Rate** | `19200` | 19,200 bits per second |
| **Data Bits** | `8` | 8 bits per character |
| **Parity** | `NONE` | No parity bit |
| **Stop Bits** | `1` | 1 stop bit |
| **Framing Format** | `8-N-1` | Standard industrial Modbus RTU format |
| **Inter-Frame Delay** | `3.5` chars | $\ge 3.5$ character times silent interval |
| **Max Concurrent Sockets** | `4` | Software buffer allocation limit |

---

## 3. Native Scan List Inspection & Blocker Analysis

### 3.1 Inspection Findings
Executing `cscape_inspect_scan_list(project_path="artifacts/projects/TankLevel_P5_Dedicated/TankLevel_P5_Dedicated.csp", port="MJ1")` returns:
```json
{
  "status": "success",
  "project_name": "TankLevel_P5_Dedicated.csp",
  "port": "MJ1",
  "protocol": "CT RTU Modbus CMP v5.05",
  "cfbf_valid": true,
  "count": 0,
  "scan_list": [],
  "scan_list_status": "empty",
  "native_fill_status": "blocked_offline",
  "blocker": "Native add requires a configured target node/device and/or live PLC context; no PLC connection or download was permitted.",
  "pending_gate": "P7_PHYSICAL_PLC_DOWNLOAD_AND_COMMISSIONING",
  "offline_safety_enforced": true,
  "zero_download_enforced": true,
  "verified_live": false,
  "plc_download": false
}
```

### 3.2 Offline Blocker Root Cause Analysis
In Horner Cscape 10.2:
- The Modbus RTU driver configuration dialog requires selection of a target node address (`Unit ID`).
- The native scan-list builder UI validates target device connectivity and slave device response timings over the serial COM channel.
- If no physical serial device is attached (or if COM ports are blocked by security policy), Cscape fails to initialize the device definition sub-records within the CFBF project stream.
- Modifying raw OLE streams without Cscape's internal relational pointers causes `INVALID_CFBF_CONTAINER` or Error Check compilation failure.
- **Fail-Closed Determination**: In accordance with the Project Contract and `AGENTS.md`, native scan list population is honestly classified as `blocked_offline`. No synthetic entries or mocks are injected into the native container.

---

## 4. Planned Modbus Devices & Transactions Topology

The planned communication architecture is preserved in `artifacts/projects/TankLevel_P5_Dedicated/modbus_protocol_inventory.json`:

### 4.1 Device Inventory Table

| Device ID | Device Name | Unit ID | Type / Function | Nominal Range | Raw Range | Target Register | Polling Interval |
| :--- | :--- | :---: | :--- | :---: | :---: | :---: | :---: |
| **`DEV_LT01`** | Buffer Tank Level Transmitter | `1` | Hydrostatic Level Sensor | `0.0 .. 100.0 %` | `0 .. 32000` | `%AI1` | `100 ms` |
| **`DEV_FT01`** | Inflow Coriolis Flowmeter | `2` | Electromagnetic Flowmeter | `0.0 .. 500.0 L/min` | `0 .. 32000` | `%AI2` | `200 ms` |
| **`DEV_PT01`** | Discharge Pressure Transmitter | `3` | Piezoresistive Pressure Sensor | `0.0 .. 10.0 bar` | `0 .. 32000` | `%AI3` | `200 ms` |

### 4.2 Planned Scan List Transactions

| Transaction ID | Unit ID | FC | Modicon Addr | Wire Offset | Regs | OCS Reg | Variable Name | EU | Comm Alarm | Stale Quality |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :---: | :---: | :---: |
| **`TX01_LEVEL_PV`** | 1 | 03 | `40001` | 0 | 1 | `%AI1` | `TankLevelPV` | `%` | `%M10` | `%M11` |
| **`TX02_INFLOW_RATE`** | 2 | 03 | `40002` | 1 | 1 | `%AI2` | `InflowRatePV` | `L/min` | `%M12` | `%M13` |
| **`TX03_DISCHARGE_PRESS`** | 3 | 03 | `40003` | 2 | 1 | `%AI3` | `DischargePressPV` | `bar` | `%M14` | `%M15` |

---

## 5. Planned vs. Native Reconciliation State

Reconciliation between the native CFBF project container and the planned protocol inventory via `cscape_reconcile_scan_list` reports:

```
+-----------------------------------------------------------------------------------+
| RECONCILIATION SUMMARY: TankLevel_P5_Dedicated.csp                                |
+-----------------------------------------------------------------------------------+
| Native Scan List Entries : 0                                                      |
| Planned Inventory Entries: 3                                                      |
| Discrepancy Delta        : -3 (3 unpopulated transactions)                        |
| Reconciled Status        : False                                                  |
| Reconciliation Status    : discrepancy_detected (pending_p7)                       |
| Pending Gate             : P7_PHYSICAL_PLC_DOWNLOAD_AND_COMMISSIONING             |
+-----------------------------------------------------------------------------------+
```

### Discrepancy Breakdown:
1. **`TX01_LEVEL_PV`**: Missing in native scan list. Planned: Modbus FC03 from Unit 1, Modicon 40001 $\rightarrow$ `%AI1`.
2. **`TX02_INFLOW_RATE`**: Missing in native scan list. Planned: Modbus FC03 from Unit 2, Modicon 40002 $\rightarrow$ `%AI2`.
3. **`TX03_DISCHARGE_PRESS`**: Missing in native scan list. Planned: Modbus FC03 from Unit 3, Modicon 40003 $\rightarrow$ `%AI3`.

---

## 6. Offline IEC 61131-3 Scaling Bridge Integration

To ensure deterministic data processing without live PLC polling, the tank control logic incorporates pure IEC 61131-3 Structured Text function blocks:

- **`FB_ModbusScaleQuality.st`**: Encapsulates linear interpolation ($Y = Y_{min} + \frac{X - X_{min}}{X_{max} - X_{min}} \cdot (Y_{max} - Y_{min})$), underflow clamping ($< 0$), overflow clamping ($> 32000$), communication alarm gating, and stale quality clamping.
- **`TankLevelModbusBridge.st`**: Instantiates three instances of the function block:
  - `fb_level_scale`: Converts `%AI1` ($0..32000$) to `%R101` ($0.0..100.0\%$).
  - `fb_inflow_scale`: Converts `%AI2` ($0..32000$) to `%R103` ($0.0..500.0\text{ L/min}$).
  - `fb_press_scale`: Converts `%AI3` ($0..32000$) to `%R105` ($0.0..10.0\text{ bar}$).
- **Quality & Alarm Bit Mapping**:
  - Telemetry Health: `%M10`..`%M15`
  - Logic Alarm & Quality Bits: `%M20`..`%M31`

---

## 7. Safety, Security & Lockout Directives

The offline documentation and verification process strictly adheres to all safety directives:

| Security Domain | Restricting Invariant | Verification Evidence |
| :--- | :--- | :--- |
| **Physical Serial Ports** | `COM1` through `COM256` locked out | Attempted COM open triggers `SecurityError` |
| **Win32 Download ID 32827** | `ID_PROGRAM_DOWNLOAD` intercepted | Message dispatch blocked fail-closed |
| **Win32 Download ID 33149** | `ID_CONTROLLER_DOWNLOAD` intercepted | Message dispatch blocked fail-closed |
| **Flashing Utilities** | Execution of companion tools prohibited | Blocked by security policy |
| **Live Verification Claim** | `verified_live: false` strictly enforced | Contract test asserts `verified_live == False` |
| **Zero PLC Download** | `plc_download: false` strictly enforced | Contract test asserts `plc_download == False` |
| **Error Check Polling** | Background polling loops prohibited | Single-pass deterministic execution |

---

## 8. Phase P7 Commissioning Deferral Notice

> [!IMPORTANT]
> **Definitive Deferral Statement**:
> Populating the native Horner Cscape scan list table on port `MJ1` and downloading the finalized hardware configuration to physical OCS hardware is **STRICTLY DEFERRED TO PHASE P7**.
> Phase P7 is reserved for manual loading and end-to-end electrical loop check by a qualified field commissioning engineer on site. No automated script, subagent, or CLI tool is authorized to initiate serial communications or download sequences to physical hardware.
