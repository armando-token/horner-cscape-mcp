PROGRAM TankLevelControl
VAR_INPUT
    RawLevelIn : INT;
    SetPoint : REAL := 50.0;
    AutoMode : BOOL := TRUE;
END_VAR
VAR_OUTPUT
    PumpSpeed : INT;
    HighAlarm : BOOL;
END_VAR
VAR
    LevelPercent : REAL;
END_VAR

LevelPercent := (INT_TO_REAL(RawLevelIn) / 32000.0) * 100.0;

IF LevelPercent >= 90.0 THEN
    HighAlarm := TRUE;
ELSE
    HighAlarm := FALSE;
END_IF;

IF AutoMode THEN
    IF LevelPercent < SetPoint THEN
        PumpSpeed := 25000;
    ELSE
        PumpSpeed := 8000;
    END_IF;
ELSE
    PumpSpeed := 0;
END_IF;
END_PROGRAM
