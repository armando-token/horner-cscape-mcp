PROGRAM TankLevelControl
VAR
    RawAnalogInput : WORD := 0; (* %AI1: Modbus Register 40001 (Wire offset 0x0000) *)
    TankLevelPV : REAL := 0.0; (* Scaled Process Variable: 0.0..100.0 % *)
    Setpoint : REAL := 50.0; (* %AQ1 *)
    AutoMode : BOOL := TRUE; (* %M1 *)
    ManualOutputCmd : REAL := 0.0; (* %AQ2 *)
    PumpCmdActive : BOOL := FALSE; (* %Q1 *)
    PumpRunningFeedback : BOOL := FALSE; (* %I1 *)
    HighAlarm : BOOL := FALSE; (* %T3 *)
    LowAlarm : BOOL := FALSE; (* %T4 *)
    ControlError : REAL := 0.0; (* %R10 *)
    HI_Limit : REAL := 75.0;
    LO_Limit : REAL := 35.0;
    CommFailureAlarm : BOOL := FALSE; (* %M10: Remote Modbus Comm Timeout Fault *)
    TankLevelPV_Stale : BOOL := FALSE; (* %M11: Stale Telemetry Quality Indicator *)
    CommWatchdogReg : WORD := 0; (* Remote Modbus Heartbeat Register *)
    LastWatchdogReg : WORD := 0;
    WatchdogTimer : TON;
END_VAR

(* 1. Modbus Communication Health & Watchdog Check *)
IF CommWatchdogReg <> LastWatchdogReg THEN
    LastWatchdogReg := CommWatchdogReg;
    CommFailureAlarm := FALSE;
    TankLevelPV_Stale := FALSE;
END_IF;

WatchdogTimer(IN := NOT CommFailureAlarm, PT := T#2s);
IF WatchdogTimer.Q THEN
    CommFailureAlarm := TRUE;
    TankLevelPV_Stale := TRUE;
END_IF;

(* 2. Modbus Telemetry Scaling & Fail-Safe Handling *)
IF NOT CommFailureAlarm THEN
    (* Linear scaling: 0.0..32000.0 count -> 0.0..100.0 % *)
    TankLevelPV := WORD_TO_REAL(RawAnalogInput) * 100.0 / 32000.0;
    TankLevelPV := LIMIT(0.0, TankLevelPV, 100.0);
ELSE
    (* Fail-safe clamp to safe state during fieldbus comm loss *)
    TankLevelPV := 0.0;
END_IF;

(* 3. Closed-Loop Tank Level Control Logic *)
ControlError := Setpoint - TankLevelPV;

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
