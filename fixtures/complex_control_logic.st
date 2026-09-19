PROGRAM ComplexControlLogic
VAR
    StateSelector : INT := 10;
    LoopIndex : INT := 0;
    Accumulator : DINT := 0;
    ConditionMet : BOOL := FALSE;
    Buffer : ARRAY [1..10] OF INT;
    TimerDelay : TON;
    ProcessComplete : BOOL := FALSE;
END_VAR

(* 1. CASE Statement *)
CASE StateSelector OF
    0:
        Accumulator := 0;
    10:
        (* 2. FOR Loop *)
        FOR LoopIndex := 1 TO 10 DO
            Buffer[LoopIndex] := LoopIndex * 5;
            Accumulator := Accumulator + INT_TO_DINT(Buffer[LoopIndex]);
        END_FOR;
        StateSelector := 20;
    20:
        (* 3. WHILE Loop *)
        LoopIndex := 1;
        WHILE LoopIndex <= 5 DO
            Accumulator := Accumulator + INT_TO_DINT(Buffer[LoopIndex]);
            LoopIndex := LoopIndex + 1;
        END_WHILE;
        StateSelector := 30;
    30:
        (* 4. REPEAT Loop *)
        LoopIndex := 10;
        REPEAT
            Accumulator := Accumulator - 1;
            LoopIndex := LoopIndex - 1;
        UNTIL LoopIndex <= 0 END_REPEAT;
        StateSelector := 40;
    40:
        (* 5. Timer Function Block Call *)
        TimerDelay(IN := TRUE, PT := T#500ms);
        IF TimerDelay.Q THEN
            TimerDelay(IN := FALSE);
            ProcessComplete := TRUE;
            StateSelector := 0;
        END_IF;
    ELSE
        StateSelector := 0;
END_CASE;

END_PROGRAM
