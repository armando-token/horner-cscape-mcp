PROGRAM UnclosedForProgram
VAR
    Index : INT := 0;
    Sum : INT := 0;
END_VAR

FOR Index := 1 TO 10 DO
    Sum := Sum + Index;
(* Missing END_FOR; *)

END_PROGRAM
