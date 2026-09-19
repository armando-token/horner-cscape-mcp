PROGRAM MismatchedTypesProgram
VAR
    FlagBool : BOOL := FALSE;
    CounterInt : INT := 0;
    NameString : STRING := 'Test';
    TimerVal : TIME := T#1s;
END_VAR

(* Incompatible direct literal assignments *)
FlagBool := 123;
CounterInt := 'IllegalString';
CounterInt := 3.14159;
TimerVal := 500;

END_PROGRAM
