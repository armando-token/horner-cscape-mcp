(* ============================================================================
 * Title:       PROGRAM BatchReactorApp
 * Description: Automated Chemical Batch Synthesis Sequential Controller.
 * Features:
 *   - Structured sequential batch phases: Fill, Dose, Heat/Mix, Soak, Cool, Drain
 *   - Recipe parameter integration: Target volume, reagent volume, cook time
 *   - Multi-actuator control: Solvent valve, dosing pump, steam, cooling, agitator
 *   - Reactor overpressure and high-temperature emergency abort interlocks
 * Language:    IEC 61131-3 Structured Text (Pure ST)
 * ============================================================================ *)

PROGRAM BatchReactorApp
VAR_INPUT
    BatchStart : BOOL := FALSE;           (* Operator start batch recipe push button *)
    BatchAbort : BOOL := FALSE;           (* Operator emergency abort push button *)
    EStopHealthy : BOOL := TRUE;          (* Safety circuit permissive *)
    CurrentLevelPct : REAL := 0.0;        (* Vessel liquid level (0.0 to 100.0 %) *)
    CurrentTempC : REAL := 22.0;          (* Vessel liquid temperature (Deg C) *)
    VesselPressBar : REAL := 0.5;         (* Internal vessel pressure (Bar) *)
    ResetAbortPB : BOOL := FALSE;         (* Clear latched abort status *)
    TargetSolventPct : REAL := 65.0;      (* Recipe: Solvent target level (%) *)
    CookTempC : REAL := 85.0;             (* Recipe: Target reaction temperature (Deg C) *)
    CookDurationSec : REAL := 120.0;      (* Recipe: Soak hold duration at cook temperature (s) *)
    CoolTempC : REAL := 35.0;             (* Recipe: Target discharge temperature (Deg C) *)
END_VAR

VAR_OUTPUT
    SolventValve : BOOL := FALSE;         (* Feed valve: Bulk solvent *)
    ReagentPump : BOOL := FALSE;          (* Dosing pump: Catalyst / reagent *)
    AgitatorMotor : BOOL := FALSE;        (* Reaction vessel impeller agitator *)
    SteamValve : BOOL := FALSE;           (* Heating jacket steam admission valve *)
    CoolingValve : BOOL := FALSE;         (* Heating jacket chilled water admission *)
    DischargePump : BOOL := FALSE;        (* Product transfer / emptying pump *)
    BatchPhase : INT := 0;                (* Current recipe phase step code *)
    BatchComplete : BOOL := FALSE;        (* Batch cycle finished flag *)
    PressureAlarm : BOOL := FALSE;        (* Overpressure safety shutdown flag *)
    PhaseTimeSec : REAL := 0.0;           (* Elapsed duration in current phase *)
END_VAR

VAR
    ScanSec : REAL := 0.1;                (* Cyclic scan interval (seconds) *)
    DoseTimer : REAL := 0.0;              (* Reagent dosing duration timer *)
    DoseRequiredSec : REAL := 20.0;       (* Dosing run time required *)
END_VAR

(* 1. Safety Interlocks and Overpressure Protection *)
IF ResetAbortPB THEN
    PressureAlarm := FALSE;
END_IF;

IF VesselPressBar >= 3.5 THEN
    PressureAlarm := TRUE;
END_IF;

IF (NOT EStopHealthy) OR BatchAbort OR PressureAlarm THEN
    BatchPhase := 9; (* Emergency Abort *)
END_IF;

(* 2. Sequential Phase Execution *)
CASE BatchPhase OF

    0: (* PHASE_IDLE: Awaiting Recipe Start *)
        SolventValve := FALSE;
        ReagentPump := FALSE;
        AgitatorMotor := FALSE;
        SteamValve := FALSE;
        CoolingValve := FALSE;
        DischargePump := FALSE;
        PhaseTimeSec := 0.0;
        BatchComplete := FALSE;

        IF BatchStart AND EStopHealthy AND (NOT PressureAlarm) THEN
            BatchPhase := 1;
        END_IF;

    1: (* PHASE_CHARGE_SOLVENT: Fill vessel with bulk solvent *)
        SolventValve := TRUE;
        AgitatorMotor := CurrentLevelPct >= 20.0; (* Start agitator once liquid covers impeller *)
        PhaseTimeSec := PhaseTimeSec + ScanSec;

        IF CurrentLevelPct >= TargetSolventPct THEN
            SolventValve := FALSE;
            DoseTimer := 0.0;
            PhaseTimeSec := 0.0;
            BatchPhase := 2;
        END_IF;

    2: (* PHASE_DOSE_REAGENT: Meter chemical catalyst *)
        ReagentPump := TRUE;
        AgitatorMotor := TRUE;
        DoseTimer := DoseTimer + ScanSec;
        PhaseTimeSec := PhaseTimeSec + ScanSec;

        IF DoseTimer >= DoseRequiredSec THEN
            ReagentPump := FALSE;
            PhaseTimeSec := 0.0;
            BatchPhase := 3;
        END_IF;

    3: (* PHASE_HEAT: Apply steam until target cook temperature is reached *)
        AgitatorMotor := TRUE;
        SteamValve := CurrentTempC < CookTempC;
        CoolingValve := FALSE;
        PhaseTimeSec := PhaseTimeSec + ScanSec;

        IF CurrentTempC >= CookTempC THEN
            PhaseTimeSec := 0.0;
            BatchPhase := 4;
        END_IF;

    4: (* PHASE_SOAK: Hold at reaction temperature for recipe duration *)
        AgitatorMotor := TRUE;
        SteamValve := CurrentTempC < CookTempC;
        CoolingValve := CurrentTempC > (CookTempC + 2.0);
        PhaseTimeSec := PhaseTimeSec + ScanSec;

        IF PhaseTimeSec >= CookDurationSec THEN
            SteamValve := FALSE;
            PhaseTimeSec := 0.0;
            BatchPhase := 5;
        END_IF;

    5: (* PHASE_COOL: Circulate chilled water to quench reaction *)
        AgitatorMotor := TRUE;
        SteamValve := FALSE;
        CoolingValve := TRUE;
        PhaseTimeSec := PhaseTimeSec + ScanSec;

        IF CurrentTempC <= CoolTempC THEN
            CoolingValve := FALSE;
            PhaseTimeSec := 0.0;
            BatchPhase := 6;
        END_IF;

    6: (* PHASE_DISCHARGE: Transfer product out of reactor *)
        AgitatorMotor := CurrentLevelPct >= 15.0;
        DischargePump := TRUE;
        PhaseTimeSec := PhaseTimeSec + ScanSec;

        IF CurrentLevelPct <= 2.0 THEN
            DischargePump := FALSE;
            AgitatorMotor := FALSE;
            BatchComplete := TRUE;
            BatchPhase := 7;
        END_IF;

    7: (* PHASE_COMPLETE: Finished, waiting for unload acknowledge *)
        SolventValve := FALSE;
        ReagentPump := FALSE;
        AgitatorMotor := FALSE;
        SteamValve := FALSE;
        CoolingValve := FALSE;
        DischargePump := FALSE;
        BatchComplete := TRUE;

        IF NOT BatchStart THEN
            BatchPhase := 0;
        END_IF;

    9: (* PHASE_ABORT: Safe shutdown state *)
        SolventValve := FALSE;
        ReagentPump := FALSE;
        SteamValve := FALSE;
        CoolingValve := TRUE; (* Quench reactor on emergency *)
        DischargePump := FALSE;
        AgitatorMotor := FALSE;

        IF (NOT PressureAlarm) AND (NOT BatchAbort) AND EStopHealthy AND ResetAbortPB THEN
            BatchPhase := 0;
        END_IF;

    ELSE
        BatchPhase := 0;
END_CASE;

END_PROGRAM
