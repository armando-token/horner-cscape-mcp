(* ============================================================================
 * Title:       FB_RampRateLimiter
 * Description: Industrial Setpoint Slew-Rate Limiter & Motion Profiler.
 * Features:
 *   - Independent acceleration (Ramp Up) and deceleration (Ramp Down) rate limits
 *   - Smooth, linear setpoint profiling to prevent mechanical or thermal stress
 *   - Anti-overshoot clamping directly to target value
 *   - Instantaneous bypass mode for emergency positioning or step jumps
 *   - Target reached status and active direction indicators
 * Language:    IEC 61131-3 Structured Text (Pure ST)
 * ============================================================================ *)

FUNCTION_BLOCK FB_RampRateLimiter
VAR_INPUT
    TargetValue : REAL := 0.0;            (* Desired target setpoint in Engineering Units *)
    RampUpRate : REAL := 10.0;            (* Maximum allowable rate of increase (EU / second) *)
    RampDownRate : REAL := 10.0;          (* Maximum allowable rate of decrease (EU / second) *)
    BypassRamp : BOOL := FALSE;           (* TRUE = immediate step jump to TargetValue *)
    InitCmd : BOOL := FALSE;              (* Force output to InitValue *)
    InitValue : REAL := 0.0;              (* Preload value when InitCmd is active *)
    Deadband : REAL := 0.01;              (* Threshold band for declaring target reached *)
    CycleTimeSec : REAL := 0.1;           (* Execution scan period (seconds) *)
END_VAR

VAR_OUTPUT
    CurrentValue : REAL := 0.0;           (* Output following rate-limited profile *)
    RampingUp : BOOL := FALSE;            (* TRUE while output is ascending toward target *)
    RampingDown : BOOL := FALSE;          (* TRUE while output is descending toward target *)
    TargetReached : BOOL := TRUE;         (* TRUE when output is within Deadband of target *)
    DeltaRate : REAL := 0.0;              (* Actual rate of change applied (EU / second) *)
END_VAR

VAR
    MaxUpStep : REAL := 0.0;              (* Maximum positive change per cycle *)
    MaxDownStep : REAL := 0.0;            (* Maximum negative change per cycle *)
    Difference : REAL := 0.0;             (* Distance from target (TargetValue - CurrentValue) *)
    PrevValue : REAL := 0.0;              (* Output from previous scan *)
END_VAR

(* 1. Initialization and Direct Bypass *)
IF InitCmd THEN
    CurrentValue := InitValue;
    PrevValue := InitValue;
    RampingUp := FALSE;
    RampingDown := FALSE;
    TargetReached := TRUE;
    DeltaRate := 0.0;
    RETURN;
ELSIF BypassRamp THEN
    CurrentValue := TargetValue;
    PrevValue := TargetValue;
    RampingUp := FALSE;
    RampingDown := FALSE;
    TargetReached := TRUE;
    DeltaRate := 0.0;
    RETURN;
END_IF;

(* 2. Step Limit Calculation *)
MaxUpStep := ABS(RampUpRate) * CycleTimeSec;
MaxDownStep := ABS(RampDownRate) * CycleTimeSec;
Difference := TargetValue - CurrentValue;

(* 3. Rate-Limiting Logic *)
IF ABS(Difference) <= Deadband THEN
    (* Target successfully reached within deadband *)
    CurrentValue := TargetValue;
    RampingUp := FALSE;
    RampingDown := FALSE;
    TargetReached := TRUE;
ELSIF Difference > 0.0 THEN
    (* Ascending toward TargetValue *)
    RampingUp := TRUE;
    RampingDown := FALSE;
    TargetReached := FALSE;

    IF Difference <= MaxUpStep THEN
        CurrentValue := TargetValue; (* Clamp to avoid overshoot *)
    ELSE
        CurrentValue := CurrentValue + MaxUpStep;
    END_IF;
ELSE
    (* Descending toward TargetValue *)
    RampingUp := FALSE;
    RampingDown := TRUE;
    TargetReached := FALSE;

    IF ABS(Difference) <= MaxDownStep THEN
        CurrentValue := TargetValue; (* Clamp to avoid overshoot *)
    ELSE
        CurrentValue := CurrentValue - MaxDownStep;
    END_IF;
END_IF;

(* 4. Velocity Calculation for Diagnostics *)
IF CycleTimeSec > 0.0001 THEN
    DeltaRate := (CurrentValue - PrevValue) / CycleTimeSec;
ELSE
    DeltaRate := 0.0;
END_IF;
PrevValue := CurrentValue;

END_FUNCTION_BLOCK
