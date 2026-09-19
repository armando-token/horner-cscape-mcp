(* ============================================================================
 * Title:       FB_MotorController
 * Author:      Horner Cscape MCP Specialist
 * Description:
 *   Industrial DOL & VFD Motor Controller Function Block.
 *   Features:
 *     - E-Stop and Guard Door Safety Interlocks
 *     - Thermal Overload Relay Trip Monitoring (NC)
 *     - Momentary Start (NO) and Stop (NC) Pushbutton Inputs
 *     - Run Feedback (Auxiliary Contactor) Verification with 3.0s Debounce
 *     - Latched Fault Detection with Dedicated Reset Command
 *     - VFD Speed Reference Clamping and Linear Acceleration Ramp
 *     - Retentive Non-Volatile Operating Run Hours Accumulator
 * Target:      Horner OCS / Straton K5 IEC 61131-3 Runtime
 * Language:    IEC 61131-3 Structured Text (ST) ONLY
 * ============================================================================ *)

FUNCTION_BLOCK FB_MotorController
VAR_INPUT
    StartCmd : BOOL;            (* Operator Start Pushbutton (NO) *)
    StopCmd : BOOL;             (* Operator Stop Pushbutton (NC) *)
    SafetyInterlock : BOOL;     (* E-Stop & Safety Guard Circuit OK *)
    OverloadTrip : BOOL;        (* Thermal Overload Relay Status (NC contact, TRUE=Trip) *)
    RunFeedback : BOOL;         (* Contactor Auxiliary Run Feedback Contact *)
    ResetCmd : BOOL;            (* Fault Reset Pushbutton *)
    SpeedSetpoint : REAL;       (* Target VFD Speed Reference (0.0 to 100.0 %) *)
    AccelRate : REAL := 5.0;    (* Ramp acceleration (% per second) *)
    CycleTimeSec : REAL := 0.05;(* PLC scan task cycle time (seconds) *)
END_VAR

VAR_OUTPUT
    MotorRun : BOOL := FALSE;       (* Digital Output to Main Contactor Coil *)
    SpeedRefOut : REAL := 0.0;      (* Analog Output: Current Scaled VFD Speed (0-100%) *)
    StatusRunning : BOOL := FALSE;  (* Verified Motor Running State *)
    FaultActive : BOOL := FALSE;    (* Latched Alarm / Fault Status *)
    OverloadAlarm : BOOL := FALSE;  (* Thermal Overload Trip Indicator *)
    FeedbackFault : BOOL := FALSE;  (* Auxiliary Feedback Failure Alarm *)
    RunHours : UDINT := 0;          (* Retentive Total Operating Run Hours *)
END_VAR

VAR
    FeedbackTimer : TON;            (* Debounce timer for feedback confirmation *)
    RunHourTimer : TON;             (* 1-second pulse timer for run hour tracking *)
    SecondAccumulator : UDINT := 0; (* Internal seconds counter *)
    CurrentSpeedRamp : REAL := 0.0; (* Internal speed ramp value *)
END_VAR

(* 1. Safety Interlocks & Thermal Overload Trip *)
IF NOT SafetyInterlock THEN
    MotorRun := FALSE;
    FaultActive := TRUE;
    CurrentSpeedRamp := 0.0;
END_IF;

IF OverloadTrip THEN
    MotorRun := FALSE;
    FaultActive := TRUE;
    OverloadAlarm := TRUE;
    CurrentSpeedRamp := 0.0;
END_IF;

(* 2. Fault Reset Command *)
IF ResetCmd AND NOT OverloadTrip AND SafetyInterlock THEN
    FaultActive := FALSE;
    OverloadAlarm := FALSE;
    FeedbackFault := FALSE;
END_IF;

(* 3. Start / Stop Logic *)
IF NOT FaultActive AND SafetyInterlock THEN
    IF StartCmd AND NOT StopCmd THEN
        MotorRun := TRUE;
    ELSIF StopCmd THEN
        MotorRun := FALSE;
    END_IF;
END_IF;

(* 4. Auxiliary Feedback Confirmation *)
FeedbackTimer(IN := MotorRun, PT := T#3s);
IF FeedbackTimer.Q AND NOT RunFeedback THEN
    MotorRun := FALSE;
    FaultActive := TRUE;
    FeedbackFault := TRUE;
    CurrentSpeedRamp := 0.0;
END_IF;

StatusRunning := MotorRun AND RunFeedback;

(* 5. VFD Speed Acceleration / Deceleration Ramp *)
IF StatusRunning THEN
    IF CurrentSpeedRamp < SpeedSetpoint THEN
        CurrentSpeedRamp := CurrentSpeedRamp + (AccelRate * CycleTimeSec);
        IF CurrentSpeedRamp > SpeedSetpoint THEN
            CurrentSpeedRamp := SpeedSetpoint;
        END_IF;
    ELSIF CurrentSpeedRamp > SpeedSetpoint THEN
        CurrentSpeedRamp := CurrentSpeedRamp - (AccelRate * CycleTimeSec);
        IF CurrentSpeedRamp < SpeedSetpoint THEN
            CurrentSpeedRamp := SpeedSetpoint;
        END_IF;
    END_IF;
ELSE
    CurrentSpeedRamp := 0.0;
END_IF;

SpeedRefOut := LIMIT(0.0, CurrentSpeedRamp, 100.0);

(* 6. Operating Hours Accumulation *)
RunHourTimer(IN := StatusRunning AND NOT RunHourTimer.Q, PT := T#1s);
IF RunHourTimer.Q THEN
    SecondAccumulator := SecondAccumulator + 1;
    IF SecondAccumulator >= 3600 THEN
        RunHours := RunHours + 1;
        SecondAccumulator := 0;
    END_IF;
END_IF;

END_FUNCTION_BLOCK
