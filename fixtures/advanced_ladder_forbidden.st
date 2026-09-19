(* Attempting forbidden ladder logic construct inside project *)
PROGRAM LadderAttempt
VAR
    InputContact : BOOL := TRUE;
    CoilOutput : BOOL := FALSE;
END_VAR

RUNG 1:
---[ ]--- InputContact --- ( ) --- CoilOutput
END_RUNG

END_PROGRAM
