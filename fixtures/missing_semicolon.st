PROGRAM MissingSemicolonProgram
VAR
    ValidVar : INT := 10;
    BrokenVar : BOOL := FALSE
END_VAR

ValidVar := ValidVar + 1
BrokenVar := TRUE;

END_PROGRAM
