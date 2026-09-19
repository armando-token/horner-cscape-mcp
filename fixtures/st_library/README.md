# IEC 61131-3 Structured Text Industrial Applications Library

Comprehensive, verified, production-grade library of IEC 61131-3 Structured Text (ST) Function Blocks designed for industrial automation systems, process control, and Horner OCS / Cscape 10.2 environments.

Strictly adheres to **Pure Structured Text** standards (zero ladder artifacts, contacts, or coils). Fully verified by AST lexical parsing (`STParser`), block-nesting validation (`IECValidator`), and static semantic safety analysis (`STValidator`).

---

## 📚 Application POU Catalog

| POU Name | Kind | File | Primary Function |
| :--- | :--- | :--- | :--- |
| `FB_LeadLagPumpControl` | `FUNCTION_BLOCK` | [`lead_lag_pump_controller.st`](file:///C:/HornerAI/horner-cscape-mcp/examples/st_applications/lead_lag_pump_controller.st) | Duplex pump wear-leveling alternation, auto-switchover on fault, lag staging, anti-short-cycling. |
| `FB_PIDTemperatureControl` | `FUNCTION_BLOCK` | [`pid_temperature_controller.st`](file:///C:/HornerAI/horner-cscape-mcp/examples/st_applications/pid_temperature_controller.st) | Closed-loop thermal PID, 1st-order PV filter, anti-windup, derivative-on-PV, PWM SSR heat & 4-20mA cool. |
| `FB_ConveyorSortingStateMachine` | `FUNCTION_BLOCK` | [`conveyor_sorting_state_machine.st`](file:///C:/HornerAI/horner-cscape-mcp/examples/st_applications/conveyor_sorting_state_machine.st) | 8-state CASE FSM, optical debounce, barcode routing, cylinder timing, jam reverse clearing. |
| `FB_AnalogScalingOutOfBounds` | `FUNCTION_BLOCK` | [`analog_scaling_bounds.st`](file:///C:/HornerAI/horner-cscape-mcp/examples/st_applications/analog_scaling_bounds.st) | 4-20mA/0-10V linear scaling to EU, wire-break (< 3.8mA) & short (> 20.5mA) detection, failsafe fallback. |
| `FB_ValveActuator` | `FUNCTION_BLOCK` | [`valve_actuator_controller.st`](file:///C:/HornerAI/horner-cscape-mcp/examples/st_applications/valve_actuator_controller.st) | Open/close commanding, dual limit switch feedback, transit timeout watchdog, stroke counter. |
| `FB_FirstFaultAnnunciator` | `FUNCTION_BLOCK` | [`first_fault_annunciator.st`](file:///C:/HornerAI/horner-cscape-mcp/examples/st_applications/first_fault_annunciator.st) | ISA-18.2 8-point first-out trip discriminator, fast/slow flashing, horn silence, acknowledge, reset. |
| `FB_FlowTotalizer` | `FUNCTION_BLOCK` | [`flow_totalizer_integrator.st`](file:///C:/HornerAI/horner-cscape-mcp/examples/st_applications/flow_totalizer_integrator.st) | Trapezoidal flow rate integration, low-flow cutoff drift filter, master/daily/batch totals, pulse out. |
| `FB_RampRateLimiter` | `FUNCTION_BLOCK` | [`ramp_rate_limiter.st`](file:///C:/HornerAI/horner-cscape-mcp/examples/st_applications/ramp_rate_limiter.st) | Independent acceleration/deceleration slew rate limits, anti-overshoot clamping, emergency bypass. |

---

## 🔍 Detailed Specifications

### 1. `FB_LeadLagPumpControl`
- **File**: `lead_lag_pump_controller.st`
- **Inputs**: `AutoEnable` (BOOL), `DemandLevel` (REAL, 0-100%), `LeadStartSP` (REAL), `LagStartSP` (REAL), `StopSP` (REAL), `Pump1_Tripped` (BOOL), `Pump2_Tripped` (BOOL), `Pump1_DryRun` (BOOL), `Pump2_DryRun` (BOOL), `ManualMode` (BOOL), `Pump1_Manual` (BOOL), `Pump2_Manual` (BOOL), `ResetFaults` (BOOL), `MaxRuntimeHours` (REAL), `MinRunTimeSec` (REAL), `MinRestTimeSec` (REAL), `CycleTimeSec` (REAL).
- **Outputs**: `Pump1_RunCmd` (BOOL), `Pump2_RunCmd` (BOOL), `LeadPumpId` (INT), `LagActive` (BOOL), `Pump1_Hours` (REAL), `Pump2_Hours` (REAL), `Pump1_Starts` (DINT), `Pump2_Starts` (DINT), `Pump1_Fault` (BOOL), `Pump2_Fault` (BOOL), `AllPumpsFaulted` (BOOL), `ServiceReqPump1` (BOOL), `ServiceReqPump2` (BOOL).

### 2. `FB_PIDTemperatureControl`
- **File**: `pid_temperature_controller.st`
- **Inputs**: `Enable` (BOOL), `Setpoint` (REAL), `RawPV` (REAL), `ManualMode` (BOOL), `ManualOutput` (REAL), `Kp` (REAL), `Ki` (REAL), `Kd` (REAL), `Deadband` (REAL), `FilterAlpha` (REAL), `CycleTimeSec` (REAL), `PwmPeriodSec` (REAL), `SplitRangeMid` (REAL), `HighHighSP` (REAL), `HighSP` (REAL), `LowSP` (REAL), `LowLowSP` (REAL), `SensorFault` (BOOL), `ResetAlarm` (BOOL).
- **Outputs**: `HeatOutput` (REAL), `CoolOutput` (REAL), `PWM_Heater` (BOOL), `FilteredPV` (REAL), `Error` (REAL), `AlarmHH` (BOOL), `AlarmH` (BOOL), `AlarmL` (BOOL), `AlarmLL` (BOOL), `LoopHealthy` (BOOL).

### 3. `FB_ConveyorSortingStateMachine`
- **File**: `conveyor_sorting_state_machine.st`
- **Inputs**: `Enable` (BOOL), `StartPB` (BOOL), `StopPB` (BOOL), `EStop` (BOOL), `PackageDetectPE` (BOOL), `BarcodeScanValid` (BOOL), `BarcodeDestLane` (INT), `Diverter1_Extended` (BOOL), `Diverter2_Extended` (BOOL), `DivertersRetracted` (BOOL), `ExitPE_Lane1` (BOOL), `ExitPE_Lane2` (BOOL), `ExitPE_Reject` (BOOL), `ResetFault` (BOOL), `JamTimeoutSec` (REAL), `DivertStrokeSec` (REAL), `CycleTimeSec` (REAL).
- **Outputs**: `ConveyorRun` (BOOL), `ConveyorRev` (BOOL), `Diverter1_Extend` (BOOL), `Diverter2_Extend` (BOOL), `RejectGate_Extend` (BOOL), `CurrentState` (INT), `JamAlarm` (BOOL), `DiverterFault` (BOOL), `CountTotal` (DINT), `CountLane1` (DINT), `CountLane2` (DINT), `CountReject` (DINT).

### 4. `FB_AnalogScalingOutOfBounds`
- **File**: `analog_scaling_bounds.st`
- **Inputs**: `RawIn` (REAL), `RawMin` (REAL), `RawMax` (REAL), `EngMin` (REAL), `EngMax` (REAL), `UnderflowTolerance` (REAL), `OverflowTolerance` (REAL), `ClampOutput` (BOOL), `FilterAlpha` (REAL), `FailSafeMode` (INT), `FailSafeValue` (REAL), `ResetFault` (BOOL).
- **Outputs**: `ScaledValue` (REAL), `RawFiltered` (REAL), `QualityOK` (BOOL), `AlarmUnderflow` (BOOL), `AlarmOverflow` (BOOL), `LatchedFault` (BOOL), `ErrorCode` (INT).

### 5. `FB_ValveActuator`
- **File**: `valve_actuator_controller.st`
- **Inputs**: `OpenCmd` (BOOL), `CloseCmd` (BOOL), `LimitOpen` (BOOL), `LimitClosed` (BOOL), `InterlockOpen` (BOOL), `InterlockClose` (BOOL), `PulseMode` (BOOL), `PulseDurationSec` (REAL), `TransitTimeoutSec` (REAL), `ResetFault` (BOOL), `CycleTimeSec` (REAL).
- **Outputs**: `SolOpen` (BOOL), `SolClose` (BOOL), `IsOpen` (BOOL), `IsClosed` (BOOL), `IsTraveling` (BOOL), `TravelFault` (BOOL), `SwitchFault` (BOOL), `TotalCycles` (DINT), `TransitTimeSec` (REAL).

### 6. `FB_FirstFaultAnnunciator`
- **File**: `first_fault_annunciator.st`
- **Inputs**: `AlarmIn1`..`AlarmIn8` (BOOL), `AckPB` (BOOL), `ResetPB` (BOOL), `TestPB` (BOOL), `CycleTimeSec` (REAL).
- **Outputs**: `Horn` (BOOL), `Beacon1`..`Beacon8` (BOOL), `FirstOutId` (INT), `AnyAlarmActive` (BOOL), `AnyUnack` (BOOL).

### 7. `FB_FlowTotalizer`
- **File**: `flow_totalizer_integrator.st`
- **Inputs**: `FlowRate` (REAL), `TimeBaseSec` (REAL), `LowFlowCutoff` (REAL), `ResetBatch` (BOOL), `ResetDaily` (BOOL), `ResetMaster` (BOOL), `PulseVolume` (REAL), `PulseDurationSec` (REAL), `CycleTimeSec` (REAL).
- **Outputs**: `TotalMaster` (LREAL), `TotalDaily` (REAL), `TotalBatch` (REAL), `NetFlowRate` (REAL), `PulseOut` (BOOL), `PulseCount` (DINT).

### 8. `FB_RampRateLimiter`
- **File**: `ramp_rate_limiter.st`
- **Inputs**: `TargetValue` (REAL), `RampUpRate` (REAL), `RampDownRate` (REAL), `BypassRamp` (BOOL), `InitCmd` (BOOL), `InitValue` (REAL), `Deadband` (REAL), `CycleTimeSec` (REAL).
- **Outputs**: `CurrentValue` (REAL), `RampingUp` (BOOL), `RampingDown` (BOOL), `TargetReached` (BOOL), `DeltaRate` (REAL).
