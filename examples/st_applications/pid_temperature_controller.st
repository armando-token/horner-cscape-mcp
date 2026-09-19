(* ============================================================================
 * Title:       FB_PIDTemperatureControl
 * Description: Industrial Closed-Loop Precision Temperature PID Controller.
 * Features:
 *   - First-order low-pass noise filter on raw process variable (PV)
 *   - Proportional-Integral-Derivative algorithm with Anti-Reset Windup
 *   - Derivative on PV action to eliminate setpoint change kicks
 *   - Bumpless transfer between Manual and Automatic modes
 *   - Deadband gap to eliminate unnecessary actuator hunting
 *   - Time-proportional PWM output for solid-state relay (SSR) heating
 *   - Analog modulating cooling output (split-range heat/cool control)
 *   - Multi-tier process safety alarms: High-High, High, Low, Low-Low
 * Language:    IEC 61131-3 Structured Text (Pure ST)
 * ============================================================================ *)

FUNCTION_BLOCK FB_PIDTemperatureControl
VAR_INPUT
    Enable : BOOL := TRUE;                (* Master loop enable permissive *)
    Setpoint : REAL := 150.0;             (* Desired temperature setpoint in Deg C *)
    RawPV : REAL := 25.0;                 (* Unfiltered process variable from analog input *)
    ManualMode : BOOL := FALSE;           (* Mode select: TRUE = Manual, FALSE = Auto PID *)
    ManualOutput : REAL := 0.0;           (* Manual output target (0.0 to 100.0 %) *)
    Kp : REAL := 4.5;                     (* Proportional gain *)
    Ki : REAL := 0.05;                    (* Integral gain (1 / second) *)
    Kd : REAL := 1.20;                    (* Derivative gain (seconds) *)
    Deadband : REAL := 0.5;               (* Error deadband zone (+/- Deg C) *)
    FilterAlpha : REAL := 0.25;           (* PV 1st-order filter coefficient (0.01 to 1.0) *)
    CycleTimeSec : REAL := 0.1;           (* Scan period of the calling task (seconds) *)
    PwmPeriodSec : REAL := 5.0;           (* Time-proportional SSR heating cycle base (seconds) *)
    SplitRangeMid : REAL := 50.0;         (* Split-range boundary between cool and heat (%) *)
    HighHighSP : REAL := 220.0;           (* Emergency High-High temperature trip point *)
    HighSP : REAL := 180.0;               (* High temperature warning setpoint *)
    LowSP : REAL := 80.0;                 (* Low temperature warning setpoint *)
    LowLowSP : REAL := 50.0;              (* Critical Low-Low temperature trip point *)
    SensorFault : BOOL := FALSE;          (* Open thermocouple / RTD wire-break signal *)
    ResetAlarm : BOOL := FALSE;           (* Alarm acknowledgment / reset input *)
END_VAR

VAR_OUTPUT
    HeatOutput : REAL := 0.0;             (* Modulating heating demand (0.0 to 100.0 %) *)
    CoolOutput : REAL := 0.0;             (* Modulating cooling demand (0.0 to 100.0 %) *)
    PWM_Heater : BOOL := FALSE;           (* Digital pulse to SSR / contactor *)
    FilteredPV : REAL := 25.0;            (* Noise-filtered process temperature *)
    Error : REAL := 0.0;                  (* Regulation error (Setpoint - FilteredPV) *)
    AlarmHH : BOOL := FALSE;              (* Latched High-High critical trip alarm *)
    AlarmH : BOOL := FALSE;               (* High temperature warning alarm *)
    AlarmL : BOOL := FALSE;               (* Low temperature warning alarm *)
    AlarmLL : BOOL := FALSE;              (* Latched Low-Low critical trip alarm *)
    LoopHealthy : BOOL := TRUE;           (* Operational health status of loop *)
END_VAR

VAR
    LastPV : REAL := 25.0;                (* Previous PV for derivative computation *)
    IntegralSum : REAL := 0.0;            (* Accumulated integral sum *)
    PropTerm : REAL := 0.0;               (* Calculated proportional contribution *)
    DerivTerm : REAL := 0.0;              (* Calculated derivative contribution *)
    TotalEffort : REAL := 0.0;            (* Net unclamped control output (0.0 to 100.0 %) *)
    EffectiveError : REAL := 0.0;         (* Error after deadband filtering *)
    PwmAccumulator : REAL := 0.0;         (* Accumulator for PWM period generator *)
END_VAR

(* 1. Alarm Reset and Sensor Fault Evaluation *)
IF ResetAlarm THEN
    AlarmHH := FALSE;
    AlarmLL := FALSE;
END_IF;

IF SensorFault THEN
    LoopHealthy := FALSE;
    HeatOutput := 0.0;
    CoolOutput := 0.0;
    PWM_Heater := FALSE;
    RETURN;
END_IF;

(* 2. First-Order Digital Low-Pass Noise Filter on PV *)
FilteredPV := (FilterAlpha * RawPV) + ((1.0 - FilterAlpha) * FilteredPV);

(* 3. Process Safety Alarms *)
IF FilteredPV >= HighHighSP THEN
    AlarmHH := TRUE;
END_IF;

IF FilteredPV <= LowLowSP THEN
    AlarmLL := TRUE;
END_IF;

AlarmH := FilteredPV >= HighSP;
AlarmL := FilteredPV <= LowSP;
LoopHealthy := (NOT AlarmHH) AND (NOT SensorFault);

(* 4. Error Calculation with Deadband *)
Error := Setpoint - FilteredPV;

IF ABS(Error) <= Deadband THEN
    EffectiveError := 0.0;
ELSE
    EffectiveError := Error;
END_IF;

(* 5. Auto / Manual PID Algorithm *)
IF (NOT Enable) OR AlarmHH THEN
    (* Safety shutdown state *)
    HeatOutput := 0.0;
    CoolOutput := 0.0;
    IntegralSum := 0.0;
    TotalEffort := 0.0;
    LastPV := FilteredPV;
ELSIF ManualMode THEN
    (* Manual Override Mode with Bumpless Tracking *)
    TotalEffort := LIMIT(0.0, ManualOutput, 100.0);
    IntegralSum := TotalEffort;
    LastPV := FilteredPV;

    IF TotalEffort >= SplitRangeMid THEN
        HeatOutput := (TotalEffort - SplitRangeMid) * (100.0 / (100.0 - SplitRangeMid));
        CoolOutput := 0.0;
    ELSE
        HeatOutput := 0.0;
        CoolOutput := (SplitRangeMid - TotalEffort) * (100.0 / SplitRangeMid);
    END_IF;
ELSE
    (* Automatic PID Regulation *)
    (* Proportional Term *)
    PropTerm := Kp * EffectiveError;

    (* Integral Term with Anti-Reset Windup *)
    IntegralSum := IntegralSum + (Ki * EffectiveError * CycleTimeSec);
    IntegralSum := LIMIT(0.0, IntegralSum, 100.0);

    (* Derivative on Measurement: -Kd * d(PV)/dt eliminates setpoint kick *)
    DerivTerm := -1.0 * Kd * (FilteredPV - LastPV) / CycleTimeSec;
    LastPV := FilteredPV;

    (* Total Control Output [0.0 to 100.0 %] *)
    TotalEffort := LIMIT(0.0, PropTerm + IntegralSum + DerivTerm, 100.0);

    (* Split-Range Actuation (Heat / Cool) *)
    IF TotalEffort >= SplitRangeMid THEN
        HeatOutput := (TotalEffort - SplitRangeMid) * (100.0 / (100.0 - SplitRangeMid));
        CoolOutput := 0.0;
    ELSE
        HeatOutput := 0.0;
        CoolOutput := (SplitRangeMid - TotalEffort) * (100.0 / SplitRangeMid);
    END_IF;
END_IF;

(* 6. Time-Proportional PWM Solid-State Relay Generation *)
IF Enable AND (NOT AlarmHH) AND (HeatOutput > 0.0) THEN
    PwmAccumulator := PwmAccumulator + (CycleTimeSec / PwmPeriodSec * 100.0);
    IF PwmAccumulator >= 100.0 THEN
        PwmAccumulator := 0.0;
    END_IF;
    PWM_Heater := PwmAccumulator < HeatOutput;
ELSE
    PwmAccumulator := 0.0;
    PWM_Heater := FALSE;
END_IF;

END_FUNCTION_BLOCK
