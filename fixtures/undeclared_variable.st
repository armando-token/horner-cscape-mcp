PROGRAM UndeclaredVariableProgram
VAR
    DeclaredCounter : INT := 0;
END_VAR

DeclaredCounter := DeclaredCounter + 1;
UndeclaredFlag := TRUE;
DeclaredCounter := PhantomMultiplier * 10;

END_PROGRAM
