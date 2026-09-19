(* ============================================================================
 * Title:       FB_TemperaturePID
 * Author:      Horner Cscape MCP Specialist
 * Description:
 *   Industrial Closed-Loop Temperature PID Controller Function Block.
 *   Features:
 *     - Digital 1st-Order Low-Pass Noise Filter on Raw PV
 *     - Proportional-Integral-Derivative Algorithm with Anti-Reset Windup
 *     - Manual Override Mode with Bumpless Transfer on Mode Switch
 *     - Time-Proportional PWM Output for Solid-State Relay / Contactor
 *     - Multi-Level Process Alarms: High-High, High, Low, Low-Low
 * Target:      Horner OCS / Straton K5 IEC 61131-3 Runtime
 * Language:    IEC 61131-3 Structured Text (ST) ONLY
 * ============================================================================ *)

FUNCTION_BLOCK FB_TemperaturePID
VAR_INPUT
    Setpoint : REAL := 120.0;           (* Desired Temperature in Deg C *)
    RawPV : REAL := 25.0;               (* Unfiltered Sensor Measurement *)
    ManualMode : BOOL := FALSE;         (* TRUE = Manual Override, FALSE = Auto PID *)
    ManualOutput : REAL := 0.0;         (* Manual Control Output (0.0 to 100.0 %) *)
    Kp : REAL := 3.2;                   (* Proportional Gain *)
    Ki : REAL := 0.04;                  (* Integral Gain (1 / sec) *)
    Kd : REAL := 0.25;                  (* Derivative Gain (sec) *)
    FilterAlpha : REAL := 0.20;         (* PV Low-Pass Filter Coefficient (0.0 - 1.0) *)
    CycleTimeSec : REAL := 0.1;         (* PID Update Scan Period (seconds) *)
    PwmPeriodSec : REAL := 10.0;        (* Solid-State Relay Cycle Base Period *)
END_VAR

VAR_OUTPUT
    ControlOutput : REAL := 0.0;        (* Calculated Control Action (0.0 to 100.0 %) *)
    FilteredPV : REAL := 25.0;          (* Noise-Filtered Process Temperature *)
    PWM_HeaterOut : BOOL := FALSE;      (* Solid-State Relay Digital Heating Pulse *)
    Error : REAL := 0.0;                (* Current Regulation Error (SP - PV) *)
    AlarmHH : BOOL := FALSE;            (* Critical High-High Temperature Trip *)
    AlarmH : BOOL := FALSE;             (* High Temperature Warning Alarm *)
    AlarmL : BOOL := FALSE;             (* Low Temperature Warning Alarm *)
    AlarmLL : BOOL := FALSE;            (* Critical Low-Low Temperature Alarm *)
END_VAR

VAR
    LastError : REAL := 0.0;            (* Previous Error for Derivative Term *)
    IntegralSum : REAL := 0.0;          (* Accumulated Integral Action *)
    PropTerm : REAL := 0.0;             (* Proportional Term Component *)
    DerivTerm : REAL := 0.0;            (* Derivative Term Component *)
    RawPIDOutput : REAL := 0.0;         (* Unclamped PID Sum *)
    PwmTimerAcc : REAL := 0.0;          (* Internal PWM Period Accumulator *)
END_VAR

(* 1. First-Order Digital Low-Pass Filter on Process Variable *)
FilteredPV := (FilterAlpha * RawPV) + ((1.0 - FilterAlpha) * FilteredPV);

(* 2. Error Calculation *)
Error := Setpoint - FilteredPV;

(* 3. Process Alarm Limits *)
AlarmHH := FilteredPV >= (Setpoint + 25.0);
AlarmH  := FilteredPV >= (Setpoint + 10.0);
AlarmL  := FilteredPV <= (Setpoint - 10.0);
AlarmLL := FilteredPV <= (Setpoint - 25.0);

(* 4. Automatic / Manual Control Computation *)
IF ManualMode OR AlarmHH THEN
    IF AlarmHH THEN
        ControlOutput := 0.0; (* Safety cut-off on critical overtemperature *)
    ELSE
        ControlOutput := LIMIT(0.0, ManualOutput, 100.0);
    END_IF;
    (* Bumpless transfer tracking *)
    IntegralSum := ControlOutput;
    LastError := Error;
ELSE
    (* Proportional Component *)
    PropTerm := Kp * Error;

    (* Integral Component with Anti-Reset Windup Clamping *)
    IntegralSum := IntegralSum + (Ki * Error * CycleTimeSec);
    IntegralSum := LIMIT(0.0, IntegralSum, 100.0);

    (* Derivative Component *)
    DerivTerm := Kd * (Error - LastError) / CycleTimeSec;
    LastError := Error;

    (* Total Control Effort Clamped to [0.0, 100.0] % *)
    RawPIDOutput := PropTerm + IntegralSum + DerivTerm;
    ControlOutput := LIMIT(0.0, RawPIDOutput, 100.0);
END_IF;

(* 5. Time-Proportional PWM Solid-State Relay Generation *)
PwmTimerAcc := PwmTimerAcc + (CycleTimeSec / PwmPeriodSec * 100.0);
IF PwmTimerAcc >= 100.0 THEN
    PwmTimerAcc := 0.0;
END_IF;

PWM_HeaterOut := (PwmTimerAcc < ControlOutput) AND NOT AlarmHH;

END_FUNCTION_BLOCK
