(* ============================================================================
 * Title:       PROGRAM AnalogScalingApp
 * Description: Multichannel Process Analog Signal Conditioner with Bounds Checking.
 * Features:
 *   - 4-Channel transmitter linear scaling to engineering units
 *   - Independent out-of-bounds detection: Wire-break and short-circuit faults
 *   - Safe value substitution during hardware transducer failure
 *   - Process alarms for high and low limit excursions
 *   - Master diagnostic health word encoding for SCADA / HMI telemetry
 * Language:    IEC 61131-3 Structured Text (Pure ST)
 * ============================================================================ *)

PROGRAM AnalogScalingApp
VAR_INPUT
    RawCh1 : REAL := 16000.0;             (* Raw ADC Channel 1: Pressure transmitter *)
    RawCh2 : REAL := 18500.0;             (* Raw ADC Channel 2: Temperature transmitter *)
    RawCh3 : REAL := 12000.0;             (* Raw ADC Channel 3: Flow rate transmitter *)
    RawCh4 : REAL := 22000.0;             (* Raw ADC Channel 4: Tank level transmitter *)
    ResetFaults : BOOL := FALSE;          (* Push button to clear sensor fault latches *)
END_VAR

VAR_OUTPUT
    Press_PSIG : REAL := 0.0;             (* Scaled pressure: 0.0 to 150.0 PSIG *)
    Temp_DegC : REAL := 0.0;              (* Scaled temperature: -20.0 to 250.0 Deg C *)
    Flow_GPM : REAL := 0.0;               (* Scaled flow rate: 0.0 to 500.0 GPM *)
    Level_Pct : REAL := 0.0;              (* Scaled vessel level: 0.0 to 100.0 % *)
    Ch1_Fault : BOOL := FALSE;            (* Channel 1 wire break or short circuit *)
    Ch2_Fault : BOOL := FALSE;            (* Channel 2 wire break or short circuit *)
    Ch3_Fault : BOOL := FALSE;            (* Channel 3 wire break or short circuit *)
    Ch4_Fault : BOOL := FALSE;            (* Channel 4 wire break or short circuit *)
    HealthStatusWord : WORD := 16#FFFF;   (* 16-bit status mask (Bit 0-3 = Channel OK) *)
    HighPressureAlarm : BOOL := FALSE;    (* Pressure above 135.0 PSIG warning *)
    HighLevelAlarm : BOOL := FALSE;       (* Level above 90.0 % overflow warning *)
END_VAR

VAR
    RawMinVal : REAL := 3200.0;           (* Raw count corresponding to 4.0 mA *)
    RawMaxVal : REAL := 32000.0;          (* Raw count corresponding to 20.0 mA *)
    BreakThreshold : REAL := 2500.0;      (* Underflow threshold declaring open circuit *)
    ShortThreshold : REAL := 32500.0;     (* Overflow threshold declaring short circuit *)
    SpanCh1 : REAL := 150.0;              (* Range span: Channel 1 *)
    SpanCh2 : REAL := 270.0;              (* Range span: Channel 2 (-20 to 250) *)
    SpanCh3 : REAL := 500.0;              (* Range span: Channel 3 *)
    SpanCh4 : REAL := 100.0;              (* Range span: Channel 4 *)
    RawSpan : REAL := 28800.0;            (* RawSpan = 32000 - 3200 *)
END_VAR

(* 1. Fault Clear *)
IF ResetFaults THEN
    Ch1_Fault := FALSE;
    Ch2_Fault := FALSE;
    Ch3_Fault := FALSE;
    Ch4_Fault := FALSE;
END_IF;

(* 2. Channel 1: Steam Header Pressure (0.0 to 150.0 PSIG) *)
IF RawCh1 < BreakThreshold OR RawCh1 > ShortThreshold THEN
    Ch1_Fault := TRUE;
    Press_PSIG := 0.0; (* Fail-safe pressure reading *)
ELSE
    Press_PSIG := ((RawCh1 - RawMinVal) / RawSpan) * SpanCh1;
    Press_PSIG := LIMIT(0.0, Press_PSIG, 150.0);
END_IF;

(* 3. Channel 2: Reactor Fluid Temperature (-20.0 to 250.0 Deg C) *)
IF RawCh2 < BreakThreshold OR RawCh2 > ShortThreshold THEN
    Ch2_Fault := TRUE;
    Temp_DegC := 25.0; (* Fail-safe ambient default *)
ELSE
    Temp_DegC := -20.0 + (((RawCh2 - RawMinVal) / RawSpan) * SpanCh2);
    Temp_DegC := LIMIT(-20.0, Temp_DegC, 250.0);
END_IF;

(* 4. Channel 3: Feed Flow Rate (0.0 to 500.0 GPM) *)
IF RawCh3 < BreakThreshold OR RawCh3 > ShortThreshold THEN
    Ch3_Fault := TRUE;
    Flow_GPM := 0.0; (* Fail-safe zero flow *)
ELSE
    Flow_GPM := ((RawCh3 - RawMinVal) / RawSpan) * SpanCh3;
    Flow_GPM := LIMIT(0.0, Flow_GPM, 500.0);
END_IF;

(* 5. Channel 4: Bulk Storage Tank Level (0.0 to 100.0 %) *)
IF RawCh4 < BreakThreshold OR RawCh4 > ShortThreshold THEN
    Ch4_Fault := TRUE;
    Level_Pct := 0.0; (* Fail-safe empty level *)
ELSE
    Level_Pct := ((RawCh4 - RawMinVal) / RawSpan) * SpanCh4;
    Level_Pct := LIMIT(0.0, Level_Pct, 100.0);
END_IF;

(* 6. Process Excursion Alarms *)
HighPressureAlarm := Press_PSIG >= 135.0 AND (NOT Ch1_Fault);
HighLevelAlarm := Level_Pct >= 90.0 AND (NOT Ch4_Fault);

(* 7. Health Status Diagnostics Word *)
IF (NOT Ch1_Fault) AND (NOT Ch2_Fault) AND (NOT Ch3_Fault) AND (NOT Ch4_Fault) THEN
    HealthStatusWord := 16#000F; (* All 4 channels healthy *)
ELSE
    HealthStatusWord := 16#0000;
END_IF;

END_PROGRAM
