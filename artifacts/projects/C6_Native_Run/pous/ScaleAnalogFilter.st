FUNCTION_BLOCK ScaleAnalogFilter
VAR_INPUT
    RawInput : REAL;
    SmoothingFactor : REAL;
    LowLimit : REAL;
    HighLimit : REAL;
END_VAR
VAR_OUTPUT
    FilteredVal : REAL;
    AlarmHigh : BOOL;
END_VAR
VAR
    ClampedInput : REAL;
END_VAR

(* Clamping raw input to engineering unit limits *)
IF RawInput < LowLimit THEN
    ClampedInput := LowLimit;
ELSIF RawInput > HighLimit THEN
    ClampedInput := HighLimit;
ELSE
    ClampedInput := RawInput;
END_IF;

(* First-order exponential smoothing filter *)
FilteredVal := (SmoothingFactor * ClampedInput) + ((1.0 - SmoothingFactor) * FilteredVal);

(* High alarm threshold at 95% high range *)
IF FilteredVal >= (HighLimit * 0.95) THEN
    AlarmHigh := TRUE;
ELSE
    AlarmHigh := FALSE;
END_IF;

END_FUNCTION_BLOCK
