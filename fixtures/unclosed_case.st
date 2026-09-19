PROGRAM UnclosedCaseProgram
VAR
    Selector : INT := 1;
    Result : INT := 0;
END_VAR

CASE Selector OF
    1: Result := 10;
    2: Result := 20;
(* Missing END_CASE; *)

END_PROGRAM
