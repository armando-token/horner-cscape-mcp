# Comprehensive Technical Report: MJ1 Devices and Scan List State Documentation

**Document ID**: `MJ1_DEVICES_AND_SCAN_LIST_STATE_DOCUMENTATION`  
**Target Container**: `TankLevel_P5_Dedicated.csp`  
**Serial Port**: `MJ1` (RS-485 Half-Duplex)  
**Protocol Driver**: `CT RTU Modbus CMP v5.05` (`Modbus Master v 5.07`)  
**Operational Scope**: `offline/DEV [PRODUCT_EVIDENCE]`  
**Operational Mode**: Pure Software / Zero PLC Download / Fail-Closed Safety Lockout  
**System State**: `RUNTIME_PENDING_P7`  
**Verification Invariant**: `verified_live: false`, `zero_plc_download: true`  
**Timestamp UTC**: `2026-09-17T21:00:00Z`  
**Dual-Root Mirroring**: `C:\Users\ArmandoSilva` $\longleftrightarrow$ `C:\HornerAI\horner-cscape-mcp`  

---

## 1. Executive Summary

This document provides definitive engineering documentation of the **MJ1 Serial Port**, its configured **CT RTU Modbus CMP v5.05** protocol driver, and the **Scan List state** within the native Horner APG Cscape project container **`TankLevel_P5_Dedicated.csp`**.

Inspection and validation across native Compound File Binary Format (CFBF / OLE2) storage streams and the FastMCP protocol suite confirm:
1. **Physical & Driver Binding**: Port `MJ1` is configured for Half-Duplex RS-485 serial communication using driver `CT RTU Modbus CMP v 5.05 / Modbus Master v 5.07` with framing `19200-8-N-1`.
2. **Native Scan List State**: The native project scan list table on port `MJ1` is **confirmed empty** (`count: 0`, `scan_list: []`, `scan_list_status: "empty"`).
3. **Native Fill Status**: Native scan-list population is **blocked offline** (`native_fill_status: "blocked_offline"`).
4. **Root Cause Analysis**: In Horner Cscape 10.2 (Build 10.2.751.4), adding Modbus RTU target slave devices and configuring scan transactions via native dialogs requires an active target slave node or live online PLC context. In an offline development environment with zero hardware connection, attempting to force uninitialized OLE stream mutations without hardware feedback risks corrupting binary project blocks.
5. **Planned Device Inventory**: The project specification (`modbus_protocol_inventory.json`) defines three Modbus RTU transmitter devices (`DEV_LT01`, `DEV_FT01`, `DEV_PT01`) mapped to OCS registers `%AI1`, `%AI2`, and `%AI3`.
6. **Planned vs. Native Reconciliation**: Automated reconciliation reports `native_count = 0`, `planned_count = 3`, producing an offline discrepancy delta of **-3**. The reconciliation state is `discrepancy_detected` (`pending_p7`).
7. **IEC 61131-3 Scaling Bridge**: The input data path from `%AI1..%AI3` to holding registers `%R101`, `%R103`, `%R105` is governed by pure Structured Text function blocks `FB_ModbusScaleQuality` and `TankLevelModbusBridge`.
8. **Fail-Closed Safety**: Zero PLC download commands were issued. Win32 commands `32827` and `33149`, companion utilities, and all COM ports (`COM1`–`COM256`) remain strictly blocked fail-closed.

---

## 2. Port & Protocol Driver Configuration

The project container `TankLevel_P5_Dedicated.csp` contains native controller hardware configuration specifying the MJ1 port parameters:

| Parameter | Value | Engineering Specification |
| :--- | :--- | :--- |
| **Port Identifier** | `MJ1` | Modular Jack 1 on Horner OCS Controller |
| **Physical Interface** | `RS-485` | 2-wire Half-Duplex balanced differential serial |
| **Driver Label** | `CT RTU Modbus CMP v 5.05` | Horner Cscape Modbus Master Driver (v5.05 / 5.07) |
| **Operating Role** | `CLIENT_MASTER_READ_ONLY` | Modbus RTU Master (Read-only polling) |
| **Baud Rate** | `19200` bps | Standard industrial baud rate |
| **Data Bits** | `8` | 8-bit data character size |
| **Parity** | `NONE` | No parity bit |
| **Stop Bits** | `1` | Single stop bit |
| **Framing Specification** | `8-N-1` | 1 Start bit, 8 Data bits, No Parity, 1 Stop bit (10 bits/char) |
| **Inter-Frame Delay** | `3.5` chars | $\ge 3.5$ character times silence separator (Modbus RTU Standard) |
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
