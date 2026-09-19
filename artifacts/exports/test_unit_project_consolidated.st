(* ========================================== *)
(* Project: test_unit_project                      *)
(* Target PLC: T5RTI *)
(* Exported at: 2026-09-04T05:52:29.070619+00:00                     *)
(* ========================================== *)

(* --- POU: FB_ConveyorTest --- *)
FUNCTION_BLOCK FB_ConveyorTest
VAR_INPUT
    RunCmd : BOOL;
    PE_Sensor : BOOL;
END_VAR
VAR_OUTPUT
    MotorOut : BOOL;
    BoxCount : INT := 0;
END_VAR
IF RunCmd THEN
    MotorOut := TRUE;
    IF PE_Sensor THEN
        BoxCount := BoxCount + 1;
    END_IF;
ELSE
    MotorOut := FALSE;
END_IF;
END_FUNCTION_BLOCK

