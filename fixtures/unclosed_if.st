PROGRAM UnclosedIfProgram
VAR
    ConditionA : BOOL := TRUE;
    OutputVal : INT := 0;
END_VAR

IF ConditionA THEN
    OutputVal := 42;
(* Missing END_IF; here *)

END_PROGRAM
