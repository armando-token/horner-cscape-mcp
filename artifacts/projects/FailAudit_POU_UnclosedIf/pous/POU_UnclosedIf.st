PROGRAM POU_UnclosedIf
VAR
    Level : REAL := 75.0;
END_VAR
IF Level > 50.0 THEN
    Level := 50.0;
(* Intentional omission of END_IF *)
END_PROGRAM
