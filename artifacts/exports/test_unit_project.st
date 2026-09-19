(* ============================================================================ *)
(* Consolidated Structured Text POU Bundle: test_unit_project *)
(* Export Format: IEC 61131-3 Pure Structured Text *)
(* Exported At: 2026-09-06T22:29:34.523620+00:00 *)
(* Hardware Lockout: Enforced (Simulation Only) *)
(* ============================================================================ *)

(* ---------------------------------------------------------------------------- *)
(* POU: FB_ConveyorTest (FB_ConveyorTest.st) *)
(* ---------------------------------------------------------------------------- *)
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

