PROGRAM TankLevelModbusBridge
VAR
    (* Raw Modbus Telemetry Inputs *)
    AI_TankLevelRaw AT %AI1 : INT := 0;
    AI_InflowRaw AT %AI2 : INT := 0;
    AI_DischargeRaw AT %AI3 : INT := 0;

    (* Telemetry Health & Communication Flags *)
    M_LevelCommFail AT %M10 : BOOL := FALSE;
    M_LevelStale AT %M11 : BOOL := FALSE;
    M_InflowCommFail AT %M12 : BOOL := FALSE;
    M_InflowStale AT %M13 : BOOL := FALSE;
    M_DischargeCommFail AT %M14 : BOOL := FALSE;
    M_DischargeStale AT %M15 : BOOL := FALSE;

    (* Engineering Unit Scaled Process Outputs *)
    TankLevelPV AT %R101 : REAL := 0.0;
    InflowRatePV AT %R103 : REAL := 0.0;
    DischargePressPV AT %R105 : REAL := 0.0;

    (* Quality & Status Output Flags *)
    LevelQualityGood AT %M21 : BOOL := FALSE;
    LevelAlarmActive AT %M20 : BOOL := FALSE;
    LevelUnderflow AT %M26 : BOOL := FALSE;
    LevelOverflow AT %M27 : BOOL := FALSE;

    InflowQualityGood AT %M23 : BOOL := FALSE;
    InflowAlarmActive AT %M22 : BOOL := FALSE;
    InflowUnderflow AT %M28 : BOOL := FALSE;
    InflowOverflow AT %M29 : BOOL := FALSE;

    DischargeQualityGood AT %M25 : BOOL := FALSE;
    DischargeAlarmActive AT %M24 : BOOL := FALSE;
    DischargeUnderflow AT %M30 : BOOL := FALSE;
    DischargeOverflow AT %M31 : BOOL := FALSE;

    (* Function Block Instances *)
    fbLevelScale : FB_ModbusScaleQuality;
    fbInflowScale : FB_ModbusScaleQuality;
    fbDischargeScale : FB_ModbusScaleQuality;
END_VAR

(* Channel 1: Tank Level PV (0..32000 -> 0.0..100.0 %) *)
fbLevelScale(RawInput := AI_TankLevelRaw, RawMin := 0, RawMax := 32000, EUMin := 0.0, EUMax := 100.0, CommFailure := M_LevelCommFail, StaleQuality := M_LevelStale, FailSafeValue := 0.0);
TankLevelPV := fbLevelScale.ScaledOutput;
LevelQualityGood := fbLevelScale.QualityGood;
LevelAlarmActive := fbLevelScale.AlarmActive;
LevelUnderflow := fbLevelScale.Underflow;
LevelOverflow := fbLevelScale.Overflow;

(* Channel 2: Inflow Rate PV (0..32000 -> 0.0..500.0 L/min) *)
fbInflowScale(RawInput := AI_InflowRaw, RawMin := 0, RawMax := 32000, EUMin := 0.0, EUMax := 500.0, CommFailure := M_InflowCommFail, StaleQuality := M_InflowStale, FailSafeValue := 0.0);
InflowRatePV := fbInflowScale.ScaledOutput;
InflowQualityGood := fbInflowScale.QualityGood;
InflowAlarmActive := fbInflowScale.AlarmActive;
InflowUnderflow := fbInflowScale.Underflow;
InflowOverflow := fbInflowScale.Overflow;

(* Channel 3: Discharge Pressure PV (0..32000 -> 0.0..10.0 bar) *)
fbDischargeScale(RawInput := AI_DischargeRaw, RawMin := 0, RawMax := 32000, EUMin := 0.0, EUMax := 10.0, CommFailure := M_DischargeCommFail, StaleQuality := M_DischargeStale, FailSafeValue := 0.0);
DischargePressPV := fbDischargeScale.ScaledOutput;
DischargeQualityGood := fbDischargeScale.QualityGood;
DischargeAlarmActive := fbDischargeScale.AlarmActive;
DischargeUnderflow := fbDischargeScale.Underflow;
DischargeOverflow := fbDischargeScale.Overflow;

END_PROGRAM
