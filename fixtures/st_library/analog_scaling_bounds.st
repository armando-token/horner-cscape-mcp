(* ============================================================================
 * Title:       FB_AnalogScalingOutOfBounds
 * Description: Industrial Analog Scaling with Out-of-Bounds & Sensor Diagnostics.
 * Features:
 *   - Linear interpolation: Raw ADC / mA counts to Engineering Units (EU)
 *   - Out-of-bounds detection: 4-20mA open-loop wire-break and short-circuit faults
 *   - Configurable exponential smoothing digital filter for noisy plant signals
 *   - Output clamping to user process limits
 *   - Fail-safe fallback strategies (Hold Last Valid or Drive to Safe Preset)
 *   - Real-time sensor quality status and latched diagnostic error codes
 * Language:    IEC 61131-3 Structured Text (Pure ST)
 * ============================================================================ *)

FUNCTION_BLOCK FB_AnalogScalingOutOfBounds
VAR_INPUT
    RawIn : REAL := 0.0;                  (* Unscaled raw analog reading from ADC / PLC input *)
    RawMin : REAL := 4000.0;              (* Raw value corresponding to 0% range (e.g. 4.00 mA = 4000) *)
    RawMax : REAL := 20000.0;             (* Raw value corresponding to 100% range (e.g. 20.00 mA = 20000) *)
    EngMin : REAL := 0.0;                 (* Engineering units minimum (e.g. 0.0 Bar, Deg C, or RPM) *)
    EngMax : REAL := 100.0;               (* Engineering units maximum (e.g. 100.0 Bar, Deg C, or RPM) *)
    UnderflowTolerance : REAL := 400.0;   (* Margin below RawMin before declaring wire break (e.g. < 3.6 mA) *)
    OverflowTolerance : REAL := 800.0;    (* Margin above RawMax before declaring short circuit (e.g. > 20.8 mA) *)
    ClampOutput : BOOL := TRUE;           (* TRUE = constrain output between EngMin and EngMax *)
    FilterAlpha : REAL := 0.20;           (* Digital 1st-order filter factor (0.01 = heavy, 1.0 = bypass) *)
    FailSafeMode : INT := 0;              (* Fallback action on fault: 0 = Preset SafeValue, 1 = Hold Last Valid *)
    FailSafeValue : REAL := 0.0;          (* Fallback value emitted when FailSafeMode = 0 during fault *)
    ResetFault : BOOL := FALSE;           (* Pushbutton input to reset latched fault flags *)
END_VAR

VAR_OUTPUT
    ScaledValue : REAL := 0.0;            (* Final conditioned engineering units value *)
    RawFiltered : REAL := 0.0;            (* Filtered raw analog signal before scaling *)
    QualityOK : BOOL := TRUE;             (* Sensor signal is healthy and within legal electrical bounds *)
    AlarmUnderflow : BOOL := FALSE;       (* Active wire-break / open-loop / disconnected transmitter *)
    AlarmOverflow : BOOL := FALSE;        (* Active over-current / wiring short / ADC saturation *)
    LatchedFault : BOOL := FALSE;         (* Latch indicating an abnormal electrical event occurred *)
    ErrorCode : INT := 0;                 (* Diagnostics: 0=OK, 1=Underflow/Break, 2=Overflow/Short, 3=Config *)
END_VAR

VAR
    RawSpan : REAL := 16000.0;            (* Calculated raw range (RawMax - RawMin) *)
    EngSpan : REAL := 100.0;              (* Calculated engineering range (EngMax - EngMin) *)
    NormalizedFrac : REAL := 0.0;         (* Fraction between 0.0 and 1.0 *)
    CalculatedEng : REAL := 0.0;          (* Scaled value before clamping *)
    LastValidValue : REAL := 0.0;         (* Memory storing last known healthy measurement *)
    FilterInitialized : BOOL := FALSE;    (* Flag for initializing filter on first scan *)
END_VAR

(* 1. Reset Diagnostic Faults *)
IF ResetFault THEN
    LatchedFault := FALSE;
    ErrorCode := 0;
END_IF;

(* 2. Configuration Validation *)
RawSpan := RawMax - RawMin;
EngSpan := EngMax - EngMin;

IF ABS(RawSpan) < 0.001 THEN
    QualityOK := FALSE;
    LatchedFault := TRUE;
    ErrorCode := 3; (* Invalid configuration: zero raw span *)
    ScaledValue := FailSafeValue;
    RETURN;
END_IF;

(* 3. First-Order Digital Low-Pass Noise Filter *)
IF NOT FilterInitialized THEN
    RawFiltered := RawIn;
    FilterInitialized := TRUE;
ELSE
    RawFiltered := (FilterAlpha * RawIn) + ((1.0 - FilterAlpha) * RawFiltered);
END_IF;

(* 4. Out-of-Bounds Electrical Limit Verification *)
AlarmUnderflow := RawFiltered < (RawMin - UnderflowTolerance);
AlarmOverflow  := RawFiltered > (RawMax + OverflowTolerance);

IF AlarmUnderflow THEN
    QualityOK := FALSE;
    LatchedFault := TRUE;
    ErrorCode := 1; (* Wire break / open loop *)
ELSIF AlarmOverflow THEN
    QualityOK := FALSE;
    LatchedFault := TRUE;
    ErrorCode := 2; (* Over-range / short circuit *)
ELSE
    QualityOK := TRUE;
    IF NOT LatchedFault THEN
        ErrorCode := 0;
    END_IF;
END_IF;

(* 5. Scaling Calculation and Failsafe Strategy *)
IF QualityOK THEN
    (* Linear Scaling: EngMin + ((Raw - RawMin) / RawSpan) * EngSpan *)
    NormalizedFrac := (RawFiltered - RawMin) / RawSpan;
    CalculatedEng := EngMin + (NormalizedFrac * EngSpan);

    IF ClampOutput THEN
        IF EngMax >= EngMin THEN
            ScaledValue := LIMIT(EngMin, CalculatedEng, EngMax);
        ELSE
            ScaledValue := LIMIT(EngMax, CalculatedEng, EngMin);
        END_IF;
    ELSE
        ScaledValue := CalculatedEng;
    END_IF;

    LastValidValue := ScaledValue;
ELSE
    (* Sensor Fault: Apply Configured Failsafe Strategy *)
    IF FailSafeMode = 1 THEN
        ScaledValue := LastValidValue; (* Hold Last Valid *)
    ELSE
        ScaledValue := FailSafeValue;  (* Drive to Safe Preset *)
    END_IF;
END_IF;

END_FUNCTION_BLOCK
