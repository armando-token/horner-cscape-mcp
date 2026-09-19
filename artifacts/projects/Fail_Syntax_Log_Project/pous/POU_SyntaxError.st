PROGRAM POU_SyntaxError
VAR
    Speed : INT := 100;
END_VAR

IF Speed > 50 THEN
    Speed := 50;
(* Deliberately missing END_IF *)

END_PROGRAM
