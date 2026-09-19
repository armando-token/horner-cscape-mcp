PROGRAM TankLevelPID
VAR_INPUT
    RawLevelIn : INT;
    SetPoint : REAL := 60.0;
    AutoMode : BOOL := TRUE;
END_VAR
VAR_OUTPUT
    PumpOutput : INT;
    HighAlarm : BOOL;
    LowAlarm : BOOL;
END_VAR
VAR
    LevelPercent : REAL;
    Error : REAL;
    IntegralTerm : REAL;
END_VAR

LevelPercent := (INT_TO_REAL(RawLevelIn) / 32000.0) * 100.0;
Error := SetPoint - LevelPercent;

IF LevelPercent >= 90.0 THEN
    HighAlarm := TRUE;
ELSE
    HighAlarm := FALSE;
END_IF;

IF LevelPercent <= 10.0 THEN
    LowAlarm := TRUE;
ELSE
    LowAlarm := FALSE;
END_IF;

IF AutoMode THEN
    IntegralTerm := IntegralTerm + (0.2 * Error * 0.01);
    IF IntegralTerm > 100.0 THEN
        IntegralTerm := 100.0;
    ELSIF IntegralTerm < 0.0 THEN
        IntegralTerm := 0.0;
    END_IF;
    PumpOutput := REAL_TO_INT((2.5 * Error + IntegralTerm) * 320.0);
    IF PumpOutput > 32000 THEN
        PumpOutput := 32000;
    ELSIF PumpOutput < 0 THEN
        PumpOutput := 0;
    END_IF;
ELSE
    PumpOutput := 0;
END_IF;
END_PROGRAM
