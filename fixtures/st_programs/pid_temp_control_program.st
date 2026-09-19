(* ============================================================================
 * Title:       PROGRAM PIDTemperatureApp
 * Description: Industrial Oven Closed-Loop Thermal Process Controller.
 * Features:
 *   - Raw RTD temperature input filter and scaling
 *   - Proportional-Integral-Derivative temperature loop with Anti-Windup
 *   - Time-proportional SSR heater power modulation
 *   - Forced-air cooling fan trigger on positive temperature overshoot
 *   - Hard safety latch cutting heater contactor on High-High alarm
 * Language:    IEC 61131-3 Structured Text (Pure ST)
 * ============================================================================ *)

PROGRAM PIDTemperatureApp
VAR_INPUT
    SystemEnable : BOOL := TRUE;          (* Master control loop enable *)
    TempSetpoint : REAL := 175.0;         (* Target operating temperature in Deg C *)
    RawAdcInput : REAL := 8750.0;         (* Raw ADC input counts (0 to 32000) *)
    ManualOverride : BOOL := FALSE;       (* Hand mode select *)
    ManualOutputVal : REAL := 0.0;        (* Manual output power (0.0 to 100.0 %) *)
    ResetTrip : BOOL := FALSE;            (* Over-temperature latch reset *)
END_VAR

VAR_OUTPUT
    SSR_HeaterPulse : BOOL := FALSE;      (* Solid-state relay digital pulse *)
    CoolingFanCmd : BOOL := FALSE;        (* Exhaust cooling fan contactor *)
    HeaterPowerPct : REAL := 0.0;         (* Calculated heating duty cycle (0.0 to 100.0 %) *)
    CurrentTemp : REAL := 25.0;           (* Filtered process temperature in Deg C *)
    HighTempAlarm : BOOL := FALSE;        (* Critical overtemperature trip latch *)
END_VAR

VAR
    ScanSec : REAL := 0.1;                (* Scan cycle time in seconds *)
    Kp : REAL := 3.5;                     (* Proportional gain *)
    Ki : REAL := 0.04;                    (* Integral gain (1/sec) *)
    Kd : REAL := 1.50;                    (* Derivative gain (sec) *)
    Error : REAL := 0.0;                  (* Control error (SP - PV) *)
    LastPV : REAL := 25.0;                (* Previous measurement for derivative *)
    IntegralAcc : REAL := 0.0;            (* Clamped integral accumulator *)
    RawPV : REAL := 25.0;                 (* Unfiltered converted temperature *)
    PwmAcc : REAL := 0.0;                 (* Time-proportional PWM period accumulator *)
    PwmPeriodSec : REAL := 4.0;           (* Base period for SSR cycling (seconds) *)
END_VAR

(* 1. Safety Trip Reset *)
IF ResetTrip THEN
    HighTempAlarm := FALSE;
END_IF;

(* 2. Analog Conversion: 0-32000 counts to 0.0-300.0 Deg C *)
RawPV := (RawAdcInput / 32000.0) * 300.0;

(* 1st-Order Low-Pass Filter: 20% alpha *)
CurrentTemp := (0.20 * RawPV) + (0.80 * CurrentTemp);

(* 3. High-High Safety Interlock *)
IF CurrentTemp >= 230.0 THEN
    HighTempAlarm := TRUE;
END_IF;

(* 4. Error and Closed-Loop PID Calculation *)
Error := TempSetpoint - CurrentTemp;

IF (NOT SystemEnable) OR HighTempAlarm THEN
    HeaterPowerPct := 0.0;
    IntegralAcc := 0.0;
    CoolingFanCmd := FALSE;
ELSIF ManualOverride THEN
    HeaterPowerPct := LIMIT(0.0, ManualOutputVal, 100.0);
    IntegralAcc := HeaterPowerPct;
    CoolingFanCmd := FALSE;
ELSE
    (* Anti-Reset Windup Integral Accumulation *)
    IntegralAcc := IntegralAcc + (Ki * Error * ScanSec);
    IntegralAcc := LIMIT(0.0, IntegralAcc, 100.0);

    (* PID Calculation: P + I - Derivative on Measurement *)
    HeaterPowerPct := (Kp * Error) + IntegralAcc - (Kd * (CurrentTemp - LastPV) / ScanSec);
    HeaterPowerPct := LIMIT(0.0, HeaterPowerPct, 100.0);

    (* Cooling Fan Assist on Significant Overshoot (+5.0 Deg C above SP) *)
    CoolingFanCmd := CurrentTemp >= (TempSetpoint + 5.0);
END_IF;
LastPV := CurrentTemp;

(* 5. Time-Proportional PWM SSR Trigger *)
IF HeaterPowerPct > 0.0 AND (NOT HighTempAlarm) AND SystemEnable THEN
    PwmAcc := PwmAcc + (ScanSec / PwmPeriodSec * 100.0);
    IF PwmAcc >= 100.0 THEN
        PwmAcc := 0.0;
    END_IF;
    SSR_HeaterPulse := PwmAcc < HeaterPowerPct;
ELSE
    PwmAcc := 0.0;
    SSR_HeaterPulse := FALSE;
END_IF;

END_PROGRAM
