PROGRAM TankLevelValid
VAR
    TankLevel : REAL := 50.0;
    TargetLevel : REAL := 60.0;
    PumpRun : BOOL := FALSE;
END_VAR

IF TankLevel < TargetLevel THEN
    PumpRun := TRUE;
ELSE
    PumpRun := FALSE;
END_IF;
END_PROGRAM
