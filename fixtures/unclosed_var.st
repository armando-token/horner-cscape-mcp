PROGRAM UnclosedVarProgram
VAR
    A : INT := 1;
    B : INT := 2;
(* Missing END_VAR *)

A := B + 10;

END_PROGRAM
