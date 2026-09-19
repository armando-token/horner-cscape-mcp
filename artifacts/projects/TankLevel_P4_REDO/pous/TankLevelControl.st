PROGRAM TankLevelControl
VAR
    TankLevelPV : REAL := 0.0; (* %AI1 *)
    Setpoint : REAL := 50.0; (* %AQ1 *)
    AutoMode : BOOL := TRUE; (* %M10 *)
    ManualOutputCmd : REAL := 0.0; (* %AQ2 *)
    PumpCmdActive : BOOL := FALSE; (* %Q1 *)
    PumpRunningFeedback : BOOL := FALSE; (* %I1 *)
    HighAlarm : BOOL := FALSE; (* %T3 *)
    LowAlarm : BOOL := FALSE; (* %T4 *)
    ControlError : REAL := 0.0; (* %R10 *)
    HI_Limit : REAL := 75.0;
    LO_Limit : REAL := 35.0;
END_VAR

(* Control error calculation *)
ControlError := Setpoint - TankLevelPV;

(* High and Low alarm trip conditions *)
IF TankLevelPV >= HI_Limit THEN
    HighAlarm := TRUE;
ELSE
    HighAlarm := FALSE;
END_IF;

IF TankLevelPV <= LO_Limit THEN
    LowAlarm := TRUE;
ELSE
    LowAlarm := FALSE;
END_IF;

(* Control logic: Auto vs Manual *)
IF AutoMode THEN
    IF TankLevelPV < Setpoint THEN
        PumpCmdActive := TRUE;
    ELSE
        PumpCmdActive := FALSE;
    END_IF;
ELSE
    IF ManualOutputCmd > 0.0 THEN
        PumpCmdActive := TRUE;
    ELSE
        PumpCmdActive := FALSE;
    END_IF;
END_IF;

END_PROGRAM
