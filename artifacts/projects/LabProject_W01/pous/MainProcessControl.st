PROGRAM MainProcessControl
VAR
    RawSensor1 : REAL := 45.0;
    RawSensor2 : REAL := 78.5;
    Alpha : REAL := 0.25;
    MinRange : REAL := 0.0;
    MaxRange : REAL := 100.0;

    Filter1 : ScaleAnalogFilter;
    Filter2 : ScaleAnalogFilter;

    OutFiltered1 : REAL := 0.0;
    OutFiltered2 : REAL := 0.0;
    Alarm1 : BOOL := FALSE;
    Alarm2 : BOOL := FALSE;
END_VAR

(* Invoke Instance 1: Primary Tank Level Sensor *)
Filter1(RawInput := RawSensor1, SmoothingFactor := Alpha, LowLimit := MinRange, HighLimit := MaxRange);
OutFiltered1 := Filter1.FilteredVal;
Alarm1 := Filter1.AlarmHigh;

(* Invoke Instance 2: Secondary Redundant Sensor *)
Filter2(RawInput := RawSensor2, SmoothingFactor := Alpha, LowLimit := MinRange, HighLimit := MaxRange);
OutFiltered2 := Filter2.FilteredVal;
Alarm2 := Filter2.AlarmHigh;

END_PROGRAM
