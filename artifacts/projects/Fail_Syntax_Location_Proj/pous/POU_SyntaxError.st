PROGRAM POU_SyntaxError
VAR
    Speed : INT := 100;
END_VAR

IF Speed > 50 THEN
    Speed := 50;
(* Intentional syntax error: unclosed IF missing END_IF *)

END_PROGRAM
