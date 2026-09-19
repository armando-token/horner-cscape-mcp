PROGRAM DiagnosticTest
VAR
    PumpRunning : BOOL := FALSE;
    MotorSpeed : INT := 0;
    SensorSignal : INT := 10;
END_VAR

IF PumpRunning THEN
    MotorSpeed := 100;
END_IF;

MotorSpeed := 314;
MotorSpeed := SensorSignal + 1;

END_PROGRAM
