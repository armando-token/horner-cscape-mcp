PROGRAM TankLevelClosedLoop
VAR
    Setpoint : REAL := 60.0;
    TankLevelPV : REAL := 50.0;
    Error : REAL := 0.0;
    ControlOutput : REAL := 0.0;
    Kp : REAL := 2.5;
END_VAR

(* Simple Tank-Level Closed Loop: Setpoint, Measured Level, Error, Output *)
Error := Setpoint - TankLevelPV;
ControlOutput := Kp * Error;

IF ControlOutput > 100.0 THEN
    ControlOutput := 100.0;
ELSIF ControlOutput < 0.0 THEN
    ControlOutput := 0.0;
END_IF;
END_PROGRAM
