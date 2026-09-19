(* ============================================================================
 * Title:       FB_LeadLagPumpControl
 * Description: Industrial Duplex Lead-Lag Alternating Pump Controller.
 * Features:
 *   - Automatic wear-leveling duty/standby rotation based on run hours
 *   - Auto-switchover on pump trip, overload, or dry-run fault
 *   - Lag pump staging when process demand exceeds single pump capacity
 *   - Anti-short-cycling minimum run and minimum rest timers
 *   - Independent Hand/Off/Auto operation with maintenance warning thresholds
 * Language:    IEC 61131-3 Structured Text (Pure ST)
 * ============================================================================ *)

FUNCTION_BLOCK FB_LeadLagPumpControl
VAR_INPUT
    AutoEnable : BOOL := TRUE;            (* Master automatic control permissive *)
    DemandLevel : REAL := 0.0;            (* Current wet-well level or process demand (0.0 to 100.0 %) *)
    LeadStartSP : REAL := 60.0;           (* Level threshold to start lead pump (%) *)
    LagStartSP : REAL := 85.0;            (* Level threshold to stage in lag pump (%) *)
    StopSP : REAL := 20.0;                (* Level threshold to stop all pumps (%) *)
    Pump1_Tripped : BOOL := FALSE;        (* Pump 1 thermal overload / drive fault *)
    Pump2_Tripped : BOOL := FALSE;        (* Pump 2 thermal overload / drive fault *)
    Pump1_DryRun : BOOL := FALSE;         (* Pump 1 low suction / dry run sensor *)
    Pump2_DryRun : BOOL := FALSE;         (* Pump 2 low suction / dry run sensor *)
    ManualMode : BOOL := FALSE;           (* Manual override select: TRUE = Manual, FALSE = Auto *)
    Pump1_Manual : BOOL := FALSE;         (* Manual start command for Pump 1 *)
    Pump2_Manual : BOOL := FALSE;         (* Manual start command for Pump 2 *)
    ResetFaults : BOOL := FALSE;          (* Latch clear / fault reset push button *)
    MaxRuntimeHours : REAL := 5000.0;     (* Preventive maintenance hour threshold *)
    MinRunTimeSec : REAL := 15.0;         (* Minimum run duration to prevent short cycling *)
    MinRestTimeSec : REAL := 20.0;        (* Minimum rest delay before motor re-start *)
    CycleTimeSec : REAL := 0.1;           (* PLC cyclic task scan period (seconds) *)
END_VAR

VAR_OUTPUT
    Pump1_RunCmd : BOOL := FALSE;         (* Digital output: Pump 1 contactor / VFD run *)
    Pump2_RunCmd : BOOL := FALSE;         (* Digital output: Pump 2 contactor / VFD run *)
    LeadPumpId : INT := 1;                (* Currently designated lead pump (1 or 2) *)
    LagActive : BOOL := FALSE;            (* TRUE when secondary lag pump is commanded *)
    Pump1_Hours : REAL := 0.0;            (* Accumulated running hours on Pump 1 *)
    Pump2_Hours : REAL := 0.0;            (* Accumulated running hours on Pump 2 *)
    Pump1_Starts : DINT := 0;             (* Total start cycles on Pump 1 *)
    Pump2_Starts : DINT := 0;             (* Total start cycles on Pump 2 *)
    Pump1_Fault : BOOL := FALSE;          (* Latched fault status for Pump 1 *)
    Pump2_Fault : BOOL := FALSE;          (* Latched fault status for Pump 2 *)
    AllPumpsFaulted : BOOL := FALSE;      (* Alarm: No pumps available to service demand *)
    ServiceReqPump1 : BOOL := FALSE;      (* Maintenance warning: Pump 1 runtime exceeded *)
    ServiceReqPump2 : BOOL := FALSE;      (* Maintenance warning: Pump 2 runtime exceeded *)
END_VAR

VAR
    P1_RunTimer : REAL := 0.0;            (* Seconds Pump 1 has run in current cycle *)
    P2_RunTimer : REAL := 0.0;            (* Seconds Pump 2 has run in current cycle *)
    P1_RestTimer : REAL := 30.0;          (* Seconds Pump 1 has rested since last stop *)
    P2_RestTimer : REAL := 30.0;          (* Seconds Pump 2 has rested since last stop *)
    P1_PrevRun : BOOL := FALSE;           (* Rising edge detection for starts counter *)
    P2_PrevRun : BOOL := FALSE;           (* Rising edge detection for starts counter *)
    P1_Available : BOOL := TRUE;          (* Pump 1 ready for service *)
    P2_Available : BOOL := TRUE;          (* Pump 2 ready for service *)
    DemandActive : BOOL := FALSE;         (* Process level demand state *)
    LagDemandActive : BOOL := FALSE;      (* High demand requiring both pumps *)
END_VAR

(* 1. Fault Evaluation and Latching *)
IF ResetFaults THEN
    Pump1_Fault := FALSE;
    Pump2_Fault := FALSE;
END_IF;

IF Pump1_Tripped OR Pump1_DryRun THEN
    Pump1_Fault := TRUE;
END_IF;

IF Pump2_Tripped OR Pump2_DryRun THEN
    Pump2_Fault := TRUE;
END_IF;

P1_Available := NOT Pump1_Fault;
P2_Available := NOT Pump2_Fault;
AllPumpsFaulted := (NOT P1_Available) AND (NOT P2_Available);

(* 2. Process Demand Hysteresis Evaluation *)
IF DemandLevel >= LeadStartSP THEN
    DemandActive := TRUE;
ELSIF DemandLevel <= StopSP THEN
    DemandActive := FALSE;
END_IF;

IF DemandLevel >= LagStartSP THEN
    LagDemandActive := TRUE;
ELSIF DemandLevel < LeadStartSP THEN
    LagDemandActive := FALSE;
END_IF;

(* 3. Lead Selection & Wear Leveling *)
(* Rotate lead assignment when both pumps are off or if lead pump faults *)
IF (NOT Pump1_RunCmd) AND (NOT Pump2_RunCmd) THEN
    IF P1_Available AND P2_Available THEN
        IF Pump1_Hours <= Pump2_Hours THEN
            LeadPumpId := 1;
        ELSE
            LeadPumpId := 2;
        END_IF;
    ELSIF P1_Available THEN
        LeadPumpId := 1;
    ELSIF P2_Available THEN
        LeadPumpId := 2;
    END_IF;
ELSIF LeadPumpId = 1 AND (NOT P1_Available) AND P2_Available THEN
    (* Immediate auto-switchover upon lead pump failure *)
    LeadPumpId := 2;
ELSIF LeadPumpId = 2 AND (NOT P2_Available) AND P1_Available THEN
    (* Immediate auto-switchover upon lead pump failure *)
    LeadPumpId := 1;
END_IF;

(* 4. Automatic / Manual Control Execution *)
IF ManualMode THEN
    (* Manual Hand Mode *)
    Pump1_RunCmd := Pump1_Manual AND P1_Available;
    Pump2_RunCmd := Pump2_Manual AND P2_Available;
    LagActive := Pump1_RunCmd AND Pump2_RunCmd;
ELSIF AutoEnable AND (NOT AllPumpsFaulted) THEN
    (* Automatic Duplex Control *)
    IF DemandActive THEN
        IF LeadPumpId = 1 THEN
            (* Pump 1 is Lead *)
            IF P1_Available AND (P1_RestTimer >= MinRestTimeSec OR Pump1_RunCmd) THEN
                Pump1_RunCmd := TRUE;
            ELSE
                Pump1_RunCmd := FALSE;
            END_IF;

            (* Pump 2 is Lag *)
            IF LagDemandActive OR (NOT P1_Available) THEN
                IF P2_Available AND (P2_RestTimer >= MinRestTimeSec OR Pump2_RunCmd) THEN
                    Pump2_RunCmd := TRUE;
                ELSE
                    Pump2_RunCmd := FALSE;
                END_IF;
            ELSE
                IF P2_RunTimer >= MinRunTimeSec THEN
                    Pump2_RunCmd := FALSE;
                END_IF;
            END_IF;
        ELSE
            (* Pump 2 is Lead *)
            IF P2_Available AND (P2_RestTimer >= MinRestTimeSec OR Pump2_RunCmd) THEN
                Pump2_RunCmd := TRUE;
            ELSE
                Pump2_RunCmd := FALSE;
            END_IF;

            (* Pump 1 is Lag *)
            IF LagDemandActive OR (NOT P2_Available) THEN
                IF P1_Available AND (P1_RestTimer >= MinRestTimeSec OR Pump1_RunCmd) THEN
                    Pump1_RunCmd := TRUE;
                ELSE
                    Pump1_RunCmd := FALSE;
                END_IF;
            ELSE
                IF P1_RunTimer >= MinRunTimeSec THEN
                    Pump1_RunCmd := FALSE;
                END_IF;
            END_IF;
        END_IF;
    ELSE
        (* Below stop setpoint: respect minimum run time before stopping *)
        IF P1_RunTimer >= MinRunTimeSec THEN
            Pump1_RunCmd := FALSE;
        END_IF;
        IF P2_RunTimer >= MinRunTimeSec THEN
            Pump2_RunCmd := FALSE;
        END_IF;
    END_IF;

    LagActive := Pump1_RunCmd AND Pump2_RunCmd;
ELSE
    (* System disabled or critical lockout *)
    Pump1_RunCmd := FALSE;
    Pump2_RunCmd := FALSE;
    LagActive := FALSE;
END_IF;

(* Safety interlock override: faulted pumps are unconditionally prohibited from running *)
IF NOT P1_Available THEN
    Pump1_RunCmd := FALSE;
END_IF;
IF NOT P2_Available THEN
    Pump2_RunCmd := FALSE;
END_IF;
LagActive := Pump1_RunCmd AND Pump2_RunCmd;

(* 5. Runtime, Rest-Time, and Cycle Accumulation *)
IF Pump1_RunCmd THEN
    P1_RunTimer := P1_RunTimer + CycleTimeSec;
    P1_RestTimer := 0.0;
    Pump1_Hours := Pump1_Hours + (CycleTimeSec / 3600.0);
    IF NOT P1_PrevRun THEN
        Pump1_Starts := Pump1_Starts + 1;
    END_IF;
ELSE
    P1_RunTimer := 0.0;
    P1_RestTimer := P1_RestTimer + CycleTimeSec;
END_IF;
P1_PrevRun := Pump1_RunCmd;

IF Pump2_RunCmd THEN
    P2_RunTimer := P2_RunTimer + CycleTimeSec;
    P2_RestTimer := 0.0;
    Pump2_Hours := Pump2_Hours + (CycleTimeSec / 3600.0);
    IF NOT P2_PrevRun THEN
        Pump2_Starts := Pump2_Starts + 1;
    END_IF;
ELSE
    P2_RunTimer := 0.0;
    P2_RestTimer := P2_RestTimer + CycleTimeSec;
END_IF;
P2_PrevRun := Pump2_RunCmd;

(* 6. Preventive Maintenance Hour Warnings *)
ServiceReqPump1 := Pump1_Hours >= MaxRuntimeHours;
ServiceReqPump2 := Pump2_Hours >= MaxRuntimeHours;

END_FUNCTION_BLOCK
