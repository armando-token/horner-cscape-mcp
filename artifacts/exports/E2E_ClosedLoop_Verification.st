(* ============================================================================ *)
(* Consolidated Structured Text POU Bundle: E2E_ClosedLoop_Verification *)
(* Export Format: IEC 61131-3 Pure Structured Text *)
(* Exported At: 2026-09-06T22:29:33.746050+00:00 *)
(* Hardware Lockout: Enforced (Simulation Only) *)
(* ============================================================================ *)

(* ---------------------------------------------------------------------------- *)
(* POU: ClosedLoopTank (ClosedLoopTank.st) *)
(* ---------------------------------------------------------------------------- *)
PROGRAM ClosedLoopTank
VAR_INPUT
    RawLevelIn : INT;
    SetPoint : REAL := 50.0;
    AutoMode : BOOL := TRUE;
END_VAR
VAR_OUTPUT
    PumpSpeed : INT;
    HighAlarm : BOOL;
END_VAR
VAR
    LevelPercent : REAL;
END_VAR

LevelPercent := (INT_TO_REAL(RawLevelIn) / 32000.0) * 100.0;

IF LevelPercent >= 90.0 THEN
    HighAlarm := TRUE;
ELSE
    HighAlarm := FALSE;
END_IF;

IF AutoMode THEN
    IF LevelPercent < SetPoint THEN
        PumpSpeed := 25000;
    ELSE
        PumpSpeed := 8000;
    END_IF;
ELSE
    PumpSpeed := 0;
END_IF;
END_PROGRAM

