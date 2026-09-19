FUNCTION_BLOCK FB_ModbusScaleQuality
VAR_INPUT
    RawInput : INT;
    RawMin : INT := 0;
    RawMax : INT := 32000;
    EUMin : REAL := 0.0;
    EUMax : REAL := 100.0;
    CommFailure : BOOL := FALSE;
    StaleQuality : BOOL := FALSE;
    FailSafeValue : REAL := 0.0;
END_VAR
VAR_OUTPUT
    ScaledOutput : REAL;
    QualityGood : BOOL;
    AlarmActive : BOOL;
    Underflow : BOOL;
    Overflow : BOOL;
END_VAR
VAR
    RawSpan : REAL;
    EUSpan : REAL;
    Normalized : REAL;
    CalculatedEU : REAL;
END_VAR

(* 1. Out-of-bounds Detection *)
IF RawInput < RawMin THEN
    Underflow := TRUE;
ELSE
    Underflow := FALSE;
END_IF;

IF RawInput > RawMax THEN
    Overflow := TRUE;
ELSE
    Overflow := FALSE;
END_IF;

(* 2. Communication Health & Telemetry Quality Gating *)
IF CommFailure OR StaleQuality THEN
    AlarmActive := TRUE;
    QualityGood := FALSE;
    ScaledOutput := FailSafeValue;
ELSE
    AlarmActive := FALSE;
    QualityGood := TRUE;

    (* 3. Linear Interpolation & Clamping *)
    RawSpan := INT_TO_REAL(RawMax - RawMin);
    EUSpan := EUMax - EUMin;

    IF RawSpan <> 0.0 THEN
        Normalized := INT_TO_REAL(RawInput - RawMin) / RawSpan;
        CalculatedEU := EUMin + (Normalized * EUSpan);
    ELSE
        CalculatedEU := EUMin;
    END_IF;

    IF EUMin <= EUMax THEN
        IF CalculatedEU < EUMin THEN
            ScaledOutput := EUMin;
        ELSIF CalculatedEU > EUMax THEN
            ScaledOutput := EUMax;
        ELSE
            ScaledOutput := CalculatedEU;
        END_IF;
    ELSE
        IF CalculatedEU < EUMax THEN
            ScaledOutput := EUMax;
        ELSIF CalculatedEU > EUMin THEN
            ScaledOutput := EUMin;
        ELSE
            ScaledOutput := CalculatedEU;
        END_IF;
    END_IF;
END_IF;

END_FUNCTION_BLOCK
