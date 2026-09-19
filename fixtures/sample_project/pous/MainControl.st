
PROGRAM MainControl
VAR_INPUT
    bStart : BOOL := FALSE;
    bStop  : BOOL := FALSE;
END_VAR
VAR_OUTPUT
    bRunning : BOOL := FALSE;
END_VAR

IF bStart AND NOT bStop THEN
    bRunning := TRUE;
ELSIF bStop THEN
    bRunning := FALSE;
END_IF;
END_PROGRAM
