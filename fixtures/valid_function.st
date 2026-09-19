FUNCTION ScaleAnalog : REAL
VAR_INPUT
    RawInput : INT;
    RawMin : INT;
    RawMax : INT;
    ScaledMin : REAL;
    ScaledMax : REAL;
END_VAR

VAR
    SpanRaw : REAL;
    SpanScaled : REAL;
    Normalized : REAL;
END_VAR

SpanRaw := INT_TO_REAL(RawMax - RawMin);
SpanScaled := ScaledMax - ScaledMin;

IF SpanRaw <> 0.0 THEN
    Normalized := INT_TO_REAL(RawInput - RawMin) / SpanRaw;
    ScaleAnalog := ScaledMin + (Normalized * SpanScaled);
ELSE
    ScaleAnalog := ScaledMin;
END_IF;

END_FUNCTION
