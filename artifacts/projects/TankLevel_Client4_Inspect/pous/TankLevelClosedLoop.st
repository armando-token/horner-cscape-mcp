PROGRAM TankLevelClosedLoop
VAR
    RawLevelInput : INT := 16000;
    TankLevelPV : REAL := 50.0;
    Setpoint : REAL := 60.0;
    ControlOutput : REAL := 0.0;
    RawPumpOutput : INT := 0;
    RawValveOutput : INT := 0;
    ManualMode : BOOL := FALSE;
    ManualOutput : REAL := 0.0;
    Kp : REAL := 2.5;
    Ki : REAL := 0.2;
    Kd : REAL := 0.05;
    OutMin : REAL := 0.0;
    OutMax : REAL := 100.0;
    Error : REAL := 0.0;
    LastError : REAL := 0.0;
    IntegralSum : REAL := 0.0;
    DerivTerm : REAL := 0.0;
    PumpRunCmd : BOOL := FALSE;
    InflowValveCmd : BOOL := FALSE;
    AlarmHighHigh : BOOL := FALSE;
    AlarmHigh : BOOL := FALSE;
    AlarmLow : BOOL := FALSE;
    AlarmLowLow : BOOL := FALSE;
    CycleCounter : DINT := 0;
END_VAR

CycleCounter := CycleCounter + 1;

(* Sensor Scaling: 0..32000 counts to 0.0..100.0% *)
TankLevelPV := (INT_TO_REAL(RawLevelInput) / 32000.0) * 100.0;
Error := Setpoint - TankLevelPV;

(* Closed-Loop PID with Bumpless Transfer and Anti-Windup *)
IF ManualMode THEN
    ControlOutput := ManualOutput;
    IntegralSum := ManualOutput;
    DerivTerm := 0.0;
ELSE
    IntegralSum := IntegralSum + (Ki * Error * 0.01);
    IF IntegralSum > OutMax THEN
        IntegralSum := OutMax;
    ELSIF IntegralSum < OutMin THEN
        IntegralSum := OutMin;
    END_IF;
    DerivTerm := Kd * (Error - LastError) / 0.01;
    ControlOutput := (Kp * Error) + IntegralSum + DerivTerm;
END_IF;
LastError := Error;

(* Output Clamping *)
IF ControlOutput > OutMax THEN
    ControlOutput := OutMax;
ELSIF ControlOutput < OutMin THEN
    ControlOutput := OutMin;
END_IF;

(* Actuator Output Scaling: 0.0..100.0% to 0..32000 counts *)
RawPumpOutput := REAL_TO_INT((ControlOutput / 100.0) * 32000.0);
RawValveOutput := RawPumpOutput;

(* Alarm Hysteresis: HH >= 90%, H >= 80%, L <= 20%, LL <= 10% *)
IF TankLevelPV >= 90.0 THEN
    AlarmHighHigh := TRUE;
ELSIF TankLevelPV < 88.0 THEN
    AlarmHighHigh := FALSE;
END_IF;

IF TankLevelPV >= 80.0 THEN
    AlarmHigh := TRUE;
ELSIF TankLevelPV < 78.0 THEN
    AlarmHigh := FALSE;
END_IF;

IF TankLevelPV <= 20.0 THEN
    AlarmLow := TRUE;
ELSIF TankLevelPV > 22.0 THEN
    AlarmLow := FALSE;
END_IF;

IF TankLevelPV <= 10.0 THEN
    AlarmLowLow := TRUE;
    PumpRunCmd := FALSE;
ELSIF TankLevelPV > 12.0 THEN
    AlarmLowLow := FALSE;
    PumpRunCmd := TRUE;
END_IF;

(* Inflow Interlock *)
IF ControlOutput > 5.0 AND NOT AlarmHighHigh THEN
    InflowValveCmd := TRUE;
ELSE
    InflowValveCmd := FALSE;
END_IF;
END_PROGRAM
