# Offline Modbus Register Scaling to IEC Function Block Bridge Evidence Report

**Document ID**: `EVIDENCE-MODBUS-IEC-FB-BRIDGE`  
**Task ID**: `OFFLINE_MODBUS_REGISTER_SCALING_IEC_FB_BRIDGE`  
**Mission ID**: `OFFLINE_MODBUS_REGISTER_SCALING_IEC_FB_BRIDGE`  
**Timestamp UTC**: `2026-09-17T20:30:00Z`  
**Governing Standard**: `IEC 61131-3 3rd Edition (Structured Text)`  
**Operational Mode**: `offline/DEV [PRODUCT_EVIDENCE]`  
**Execution Status**: `success`  
**verified_live**: `false` (Deterministic offline software verification; zero live PLC connection)  
**zero_plc_download**: `true` (Enforced fail-closed)  
**p7_status**: `DEFERRED_MANUAL_ENGINEER_LOAD (STRICTLY NOT P7; pure software offline IEC FB)`  

---

## 1. Executive Summary

This deliverable reports the complete execution and verification of **`OFFLINE_MODBUS_REGISTER_SCALING_IEC_FB_BRIDGE`**. The task resolves the offline telemetry acquisition gap between raw Modbus RTU telemetry transactions received into Horner OCS analog input registers (`%AI1`..`%AI3`, 0..32000 counts) and engineering unit process variables (`TankLevelPV`, `InflowRatePV`, `DischargePressPV`).

### Key Deliverables Completed:
1. **Pure IEC 61131-3 Function Block (`FB_ModbusScaleQuality.st`)**:
   - Encapsulates linear interpolation, bounds checking, underflow/overflow detection, communication watchdog timeout gating, and fail-safe clamping.
   - Syntax validated: 0 errors, 0 warnings via recursive descent AST parser (`Parser.from_source()`) and `IECValidator.validate()`.
   - Pure ST enforced: Zero ladder logic contacts, coils, or mnemonics (`ERR_LADDER_FORBIDDEN`).
2. **Multi-Channel Bridge Program (`TankLevelModbusBridge.st`)**:
   - Integrates 3 instances of `FB_ModbusScaleQuality` for Channel 1 (`%AI1` Tank Level), Channel 2 (`%AI2` Inflow Rate), and Channel 3 (`%AI3` Discharge Pressure).
   - Direct Horner OCS memory mappings configured via `AT %...` declarations for inputs, outputs, alarms, and quality markers.
3. **Python Bridge Engine (`src/iec/modbus_bridge.py`)**:
   - Implements `ModbusScaleQualityChannel` and `ModbusScaleQualityBridge` for deterministic simulation, offline telemetry synthesis, and unit test verification.
   - Registered in `src/iec/__init__.py`.
4. **IEC Template Catalog Integration**:
   - Registered template `"modbus_scale_quality"` in [`src/iec/templates.py`](file:///C:/HornerAI/horner-cscape-mcp/src/iec/templates.py) for direct reuse across FastMCP and engineering clients.
5. **Contract Test Suite (`tests/test_modbus_register_scaling_bridge.py`)**:
   - 32 targeted test cases: 32/32 PASSED in 3.84 seconds.
   - 100% regression pass across 44 existing scan-list, inventory, and gap tests.

---

## 2. POU Deliverables & Cryptographic Hashes

| # | POU Name | Type | Target Project Path | Size | SHA-256 Digest | Status |
| :- | :--- | :---: | :--- | :---: | :--- | :---: |
| 1 | **[`FB_ModbusScaleQuality.st`](file:///C:/HornerAI/horner-cscape-mcp/artifacts/projects/TankLevel_P5_Dedicated/pous/FB_ModbusScaleQuality.st)** | `FUNCTION_BLOCK` | `artifacts/projects/TankLevel_P5_Dedicated/pous/` | 1,784 B | `53db9193692a69b2976138ac3dd364b9c2a906b06dd259b6bff73c1c28af8b5a` | `success` |
| 2 | **[`TankLevelModbusBridge.st`](file:///C:/HornerAI/horner-cscape-mcp/artifacts/projects/TankLevel_P5_Dedicated/pous/TankLevelModbusBridge.st)** | `PROGRAM` | `artifacts/projects/TankLevel_P5_Dedicated/pous/` | 2,937 B | `a1cd7c6c34047c1e13c9aad9d06c5c81544bdb4c50b9c261391f2794012ffbdd` | `success` |

Both POU files are cryptographically mirrored with 100% byte and digest parity across:
- Primary workspace: `C:\HornerAI\horner-cscape-mcp\`
- User mirror environment: `C:\Users\ArmandoSilva\`

---

## 3. Multi-Channel Modbus RTU Register Mapping

The bridge governs three Modbus RTU telemetry transactions received on serial port `MJ1` (`CT RTU Modbus CMP v5.05`):

```
+---------------------------------------------------------------------------------------------------------+
|                                    HORNER OCS REGISTER MEMORY MAP                                       |
+---------------------+-------------------+-------------------+-------------------+-----------------------+
| Transaction ID      | Raw Input (%AI)   | Scaled PV (%R)    | Comm Fault (%M)   | Quality Good (%M)     |
+---------------------+-------------------+-------------------+-------------------+-----------------------+
| TX01_LEVEL_PV       | %AI1 (0..32000)   | %R101 (0..100.0%) | %M10 (LevelComm)  | %M21 (LevelQualGood)  |
| TX02_INFLOW_RATE    | %AI2 (0..32000)   | %R103 (0..500.0L) | %M12 (FlowComm)   | %M23 (FlowQualGood)   |
| TX03_DISCHARGE_PRESS| %AI3 (0..32000)   | %R105 (0..10.0bar)| %M14 (PressComm)  | %M25 (PressQualGood)  |
+---------------------+-------------------+-------------------+-------------------+-----------------------+
```

### Detailed Channel Parameters:
1. **`TX01_LEVEL_PV`**:
   - Modbus Address: Unit 1, Modicon 40001 (0x0000 wire offset)
   - Input: `%AI1` (`AI_TankLevelRaw`), Range 0..32000 counts
   - Output: `%R101` (`TankLevelPV`), Range `0.0 .. 100.0 %`
   - Fault Gating: `%M10` (`M_LevelCommFail`), `%M11` (`M_LevelStale`)
   - Diagnostics: `%M20` (`LevelAlarmActive`), `%M21` (`LevelQualityGood`), `%M26` (Underflow), `%M27` (Overflow)
   - Fail-Safe Value: `0.0 %`

2. **`TX02_INFLOW_RATE`**:
   - Modbus Address: Unit 2, Modicon 40002 (0x0001 wire offset)
   - Input: `%AI2` (`AI_InflowRaw`), Range 0..32000 counts
   - Output: `%R103` (`InflowRatePV`), Range `0.0 .. 500.0 L/min`
   - Fault Gating: `%M12` (`M_InflowCommFail`), `%M13` (`M_InflowStale`)
   - Diagnostics: `%M22` (`InflowAlarmActive`), `%M23` (`InflowQualityGood`), `%M28` (Underflow), `%M29` (Overflow)
   - Fail-Safe Value: `0.0 L/min`

3. **`TX03_DISCHARGE_PRESS`**:
   - Modbus Address: Unit 3, Modicon 40003 (0x0002 wire offset)
   - Input: `%AI3` (`AI_DischargeRaw`), Range 0..32000 counts
   - Output: `%R105` (`DischargePressPV`), Range `0.0 .. 10.0 bar`
   - Fault Gating: `%M14` (`M_DischargeCommFail`), `%M15` (`M_DischargeStale`)
   - Diagnostics: `%M24` (`DischargeAlarmActive`), `%M25` (`DischargeQualityGood`), `%M30` (Underflow), `%M31` (Overflow)
   - Fail-Safe Value: `0.0 bar`

---

## 4. Software Simulation & Test Assertions

Discrete simulation executed via `cscape_simulate_pou` confirms all functional requirements:

1. **Nominal Scaling Baseline (55.0 %)**:
   - Input `RawInput = 17600` counts $\rightarrow$ Output `ScaledOutput = 55.0 %`.
   - Quality flag `QualityGood = TRUE`, Alarm flag `AlarmActive = FALSE`.
   - Exactly matches Phase P5 `modbus_pv_config.json` baseline.
2. **Boundary Clamping & Out-of-Bounds Detection**:
   - Input `RawInput = -500` counts $\rightarrow$ `Underflow = TRUE`, `ScaledOutput = 0.0 %` (clamped).
   - Input `RawInput = 35000` counts $\rightarrow$ `Overflow = TRUE`, `ScaledOutput = 100.0 %` (clamped).
3. **Communication Watchdog Timeout Fault**:
   - `CommFailure = TRUE` $\rightarrow$ `AlarmActive = TRUE`, `QualityGood = FALSE`, `ScaledOutput = 0.0 %` (FailSafeValue).
4. **Stale Telemetry Quality Marker**:
   - `StaleQuality = TRUE` $\rightarrow$ `AlarmActive = TRUE`, `QualityGood = FALSE`, `ScaledOutput = 0.0 %` (FailSafeValue).
5. **Fault Recovery Trajectory**:
   - 4-cycle discrete scan sequence: `0% (0) -> 55% (17600) -> CommFault (0.0 clamped) -> Recovery (75% / 24000)`.
   - Verified seamless resumption of nominal process variable output when watchdog alarm clears.
6. **Channel Fault Isolation**:
   - Comm fault injected specifically on Channel 2 (`InflowRatePV`) leaves Channel 1 (`TankLevelPV` = 55.0%) and Channel 3 (`DischargePressPV` = 5.0 bar) healthy and active.

---

## 5. Verification Test Suite Results

```text
tests/test_modbus_register_scaling_bridge.py:
  test_pure_st_ast_parsing_fb_modbus_scale_quality ............ PASSED
  test_pure_st_ast_parsing_tank_level_modbus_bridge .......... PASSED
  test_st_ladder_interop_guard_positive_pure_st ............... PASSED
  test_st_ladder_interop_guard_rejection_of_ladder [9 cases] .. PASSED
  test_nominal_scaling_tank_level_pv_55pct_baseline ........... PASSED
  test_multi_point_scaling_linear_grid [5 cases] .............. PASSED
  test_underflow_detection_and_clamping ....................... PASSED
  test_overflow_detection_and_clamping ........................ PASSED
  test_comm_failure_fail_safe_gating .......................... PASSED
  test_stale_quality_fail_safe_gating ......................... PASSED
  test_custom_fail_safe_fallback .............................. PASSED
  test_multi_channel_bridge_all_channels ...................... PASSED
  test_channel_fault_isolation ................................ PASSED
  test_software_simulation_nominal_execution .................. PASSED
  test_software_simulation_comm_fault_gating .................. PASSED
  test_software_simulation_multi_step_trajectory .............. PASSED
  test_template_catalog_modbus_scale_quality .................. PASSED
  test_pou_file_presence_and_dual_root_parity ................. PASSED
  test_security_hardware_lockout_invariant .................... PASSED
  test_no_live_claims_contract ................................ PASSED
============================= 32 passed in 3.84s ==============================
```

---

## 6. Safety Governance & Phase P7 Deferral Statement

In accordance with strict project governance:
1. **Zero PLC Download**: No physical connection, flash, or download was made.
2. **Hardware Lockout Policy**: All physical serial communication ports (`COM1`..`COM256`), industrial fieldbuses (`CAN`, `CsCAN`), and USB debugging dongles remain unconditionally blocked by `SecurityGuard`.
3. **No VERIFIED_LIVE Pseudo-Status**: Contract returns deterministic `status: "success"` with `verified_live: false`.
4. **P7 Status**: Physical download and loading to physical controller hardware remain strictly deferred to Phase P7 for manual commissioning engineer execution.
