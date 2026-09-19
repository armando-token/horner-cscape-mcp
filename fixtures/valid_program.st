PROGRAM SimpleProgram
VAR
    RunCommand : BOOL := FALSE;
    CycleCounter : INT := 0;
    CycleLimit : INT := 100;
    CycleComplete : BOOL := FALSE;
END_VAR

IF RunCommand THEN
    IF CycleCounter < CycleLimit THEN
        CycleCounter := CycleCounter + 1;
    ELSE
        CycleComplete := TRUE;
    END_IF;
ELSE
    CycleComplete := FALSE;
END_IF;

END_PROGRAM
