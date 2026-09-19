FUNCTION_BLOCK FB_Hysteresis
VAR_INPUT
    ProcessVal : REAL := 0.0;
    LowThreshold : REAL := 20.0;
    HighThreshold : REAL := 80.0;
END_VAR

VAR_OUTPUT
    OutputState : BOOL := FALSE;
END_VAR

VAR
    InternalState : BOOL := FALSE;
END_VAR

IF ProcessVal >= HighThreshold THEN
    InternalState := TRUE;
ELSIF ProcessVal <= LowThreshold THEN
    InternalState := FALSE;
END_IF;

OutputState := InternalState;

END_FUNCTION_BLOCK
