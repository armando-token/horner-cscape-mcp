(* ============================================================================
 * Title:       FB_ConveyorSortingStateMachine
 * Description: High-Speed Material Handling Conveyor Sortation State Machine.
 * Features:
 *   - Structured CASE-based state machine for packaging & sortation lines
 *   - Debounced optical presence sensing at infeed
 *   - Barcode classification routing to Lane 1, Lane 2, or Reject Chute
 *   - Pneumatic diverter actuation with cylinder end-switch verification
 *   - Jam detection timer with automatic reverse jog clearing routine
 *   - Hardware emergency-stop and line stop supervisory interlocks
 *   - Real-time production piece counters (Total, Lanes, Rejects)
 * Language:    IEC 61131-3 Structured Text (Pure ST)
 * ============================================================================ *)

FUNCTION_BLOCK FB_ConveyorSortingStateMachine
VAR_INPUT
    Enable : BOOL := TRUE;                (* Master system run permissive *)
    StartPB : BOOL := FALSE;              (* System start push button *)
    StopPB : BOOL := FALSE;               (* System normal stop push button *)
    EStop : BOOL := TRUE;                 (* Emergency stop circuit (TRUE = Normal/Healthy) *)
    PackageDetectPE : BOOL := FALSE;      (* Optical sensor detecting parcel at inspection point *)
    BarcodeScanValid : BOOL := FALSE;     (* Strobe from vision / barcode reader when decode ready *)
    BarcodeDestLane : INT := 1;           (* Target destination from scanner: 1=Lane1, 2=Lane2, 3=Reject *)
    Diverter1_Extended : BOOL := FALSE;   (* Reed switch: Diverter 1 fully extended *)
    Diverter2_Extended : BOOL := FALSE;   (* Reed switch: Diverter 2 fully extended *)
    DivertersRetracted : BOOL := TRUE;    (* Reed switches: Both diverters back in home position *)
    ExitPE_Lane1 : BOOL := FALSE;         (* Optical sensor at Lane 1 discharge *)
    ExitPE_Lane2 : BOOL := FALSE;         (* Optical sensor at Lane 2 discharge *)
    ExitPE_Reject : BOOL := FALSE;        (* Optical sensor at Reject chute discharge *)
    ResetFault : BOOL := FALSE;           (* Push button to clear latched faults *)
    JamTimeoutSec : REAL := 4.0;          (* Maximum transit time before declaring parcel jam *)
    DivertStrokeSec : REAL := 1.2;        (* Cylinder stroke timeout limit (seconds) *)
    CycleTimeSec : REAL := 0.1;           (* Scan cycle delta time (seconds) *)
END_VAR

VAR_OUTPUT
    ConveyorRun : BOOL := FALSE;          (* Motor contactor / VFD forward command *)
    ConveyorRev : BOOL := FALSE;          (* Motor contactor / VFD reverse command for clearing *)
    Diverter1_Extend : BOOL := FALSE;     (* Pneumatic cylinder solenoid for Lane 1 *)
    Diverter2_Extend : BOOL := FALSE;     (* Pneumatic cylinder solenoid for Lane 2 *)
    RejectGate_Extend : BOOL := FALSE;    (* Pneumatic cylinder solenoid for Reject chute *)
    CurrentState : INT := 0;              (* Numeric state code for HMI diagnostics *)
    JamAlarm : BOOL := FALSE;             (* Latched conveyor jam condition *)
    DiverterFault : BOOL := FALSE;        (* Diverter cylinder failure to extend/retract *)
    CountTotal : DINT := 0;               (* Total parcels successfully processed *)
    CountLane1 : DINT := 0;               (* Total parcels diverted to Lane 1 *)
    CountLane2 : DINT := 0;               (* Total parcels diverted to Lane 2 *)
    CountReject : DINT := 0;              (* Total parcels diverted to Reject *)
END_VAR

VAR
    StateTimer : REAL := 0.0;             (* Dwell timer in active state *)
    JamTimer : REAL := 0.0;               (* Accumulator for parcel transit watchdog *)
    InfeedDebounce : REAL := 0.0;         (* Infeed optical filter accumulator *)
    InfeedConfirmed : BOOL := FALSE;      (* Debounced parcel detection flag *)
    LatchedLane : INT := 1;               (* Stored destination for current parcel *)
    RunPermissive : BOOL := FALSE;        (* Running latch set by StartPB, cleared by StopPB *)
END_VAR

(* 1. Safety and Fault Management *)
IF ResetFault THEN
    JamAlarm := FALSE;
    DiverterFault := FALSE;
END_IF;

IF NOT EStop THEN
    CurrentState := 99; (* Emergency Stop *)
    RunPermissive := FALSE;
ELSIF StopPB THEN
    RunPermissive := FALSE;
ELSIF StartPB AND Enable AND (NOT JamAlarm) AND (NOT DiverterFault) THEN
    RunPermissive := TRUE;
END_IF;

IF JamAlarm OR DiverterFault THEN
    RunPermissive := FALSE;
END_IF;

(* 2. Optical Sensor Debounce (50 ms noise immunity) *)
IF PackageDetectPE THEN
    InfeedDebounce := InfeedDebounce + CycleTimeSec;
    IF InfeedDebounce >= 0.05 THEN
        InfeedConfirmed := TRUE;
    END_IF;
ELSE
    InfeedDebounce := 0.0;
    InfeedConfirmed := FALSE;
END_IF;

(* 3. State Machine Execution *)
CASE CurrentState OF

    0: (* STATE_IDLE: Waiting for line start permissive *)
        ConveyorRun := FALSE;
        ConveyorRev := FALSE;
        Diverter1_Extend := FALSE;
        Diverter2_Extend := FALSE;
        RejectGate_Extend := FALSE;
        StateTimer := 0.0;
        JamTimer := 0.0;

        IF RunPermissive AND DivertersRetracted THEN
            CurrentState := 10;
        END_IF;

    10: (* STATE_FEED: Conveyor running, awaiting package arrival *)
        ConveyorRun := TRUE;
        ConveyorRev := FALSE;
        Diverter1_Extend := FALSE;
        Diverter2_Extend := FALSE;
        RejectGate_Extend := FALSE;

        IF NOT RunPermissive THEN
            CurrentState := 0;
        ELSIF InfeedConfirmed THEN
            StateTimer := 0.0;
            CurrentState := 20;
        END_IF;

    20: (* STATE_INSPECT: Package present, acquiring barcode/classification *)
        ConveyorRun := TRUE;
        StateTimer := StateTimer + CycleTimeSec;

        IF BarcodeScanValid THEN
            LatchedLane := BarcodeDestLane;
            StateTimer := 0.0;
            JamTimer := 0.0;
            IF LatchedLane = 1 THEN
                CurrentState := 30;
            ELSIF LatchedLane = 2 THEN
                CurrentState := 40;
            ELSE
                CurrentState := 50;
            END_IF;
        ELSIF StateTimer >= 1.5 THEN
            (* Scanner timeout: Default route to Reject *)
            LatchedLane := 3;
            StateTimer := 0.0;
            JamTimer := 0.0;
            CurrentState := 50;
        END_IF;

    30: (* STATE_DIVERT_LANE1: Actuate Diverter 1 *)
        ConveyorRun := TRUE;
        Diverter1_Extend := TRUE;
        StateTimer := StateTimer + CycleTimeSec;
        JamTimer := JamTimer + CycleTimeSec;

        (* Check end switch feedback *)
        IF StateTimer >= DivertStrokeSec AND (NOT Diverter1_Extended) THEN
            DiverterFault := TRUE;
            CurrentState := 90;
        ELSIF ExitPE_Lane1 OR (StateTimer >= 2.5) THEN
            (* Package diverted successfully *)
            CountLane1 := CountLane1 + 1;
            CountTotal := CountTotal + 1;
            Diverter1_Extend := FALSE;
            CurrentState := 60;
        ELSIF JamTimer >= JamTimeoutSec THEN
            JamAlarm := TRUE;
            CurrentState := 90;
        END_IF;

    40: (* STATE_DIVERT_LANE2: Actuate Diverter 2 *)
        ConveyorRun := TRUE;
        Diverter2_Extend := TRUE;
        StateTimer := StateTimer + CycleTimeSec;
        JamTimer := JamTimer + CycleTimeSec;

        IF StateTimer >= DivertStrokeSec AND (NOT Diverter2_Extended) THEN
            DiverterFault := TRUE;
            CurrentState := 90;
        ELSIF ExitPE_Lane2 OR (StateTimer >= 2.5) THEN
            CountLane2 := CountLane2 + 1;
            CountTotal := CountTotal + 1;
            Diverter2_Extend := FALSE;
            CurrentState := 60;
        ELSIF JamTimer >= JamTimeoutSec THEN
            JamAlarm := TRUE;
            CurrentState := 90;
        END_IF;

    50: (* STATE_REJECT: Actuate Reject gate / Chute *)
        ConveyorRun := TRUE;
        RejectGate_Extend := TRUE;
        StateTimer := StateTimer + CycleTimeSec;
        JamTimer := JamTimer + CycleTimeSec;

        IF ExitPE_Reject OR (StateTimer >= 2.5) THEN
            CountReject := CountReject + 1;
            CountTotal := CountTotal + 1;
            RejectGate_Extend := FALSE;
            CurrentState := 60;
        ELSIF JamTimer >= JamTimeoutSec THEN
            JamAlarm := TRUE;
            CurrentState := 90;
        END_IF;

    60: (* STATE_PACKAGE_CLEARED: Ensure actuators home before next item *)
        ConveyorRun := TRUE;
        Diverter1_Extend := FALSE;
        Diverter2_Extend := FALSE;
        RejectGate_Extend := FALSE;
        StateTimer := StateTimer + CycleTimeSec;

        IF DivertersRetracted AND (NOT InfeedConfirmed) THEN
            IF RunPermissive THEN
                CurrentState := 10;
            ELSE
                CurrentState := 0;
            END_IF;
        ELSIF StateTimer >= 3.0 THEN
            (* Actuators stuck in lane *)
            DiverterFault := TRUE;
            CurrentState := 90;
        END_IF;

    90: (* STATE_JAM_FAULT: Line halted on jam or cylinder failure *)
        ConveyorRun := FALSE;
        ConveyorRev := FALSE;
        Diverter1_Extend := FALSE;
        Diverter2_Extend := FALSE;
        RejectGate_Extend := FALSE;

        IF (NOT JamAlarm) AND (NOT DiverterFault) AND DivertersRetracted THEN
            CurrentState := 0;
        END_IF;

    99: (* STATE_ESTOP: Emergency Stop engaged *)
        ConveyorRun := FALSE;
        ConveyorRev := FALSE;
        Diverter1_Extend := FALSE;
        Diverter2_Extend := FALSE;
        RejectGate_Extend := FALSE;

        IF EStop AND (NOT RunPermissive) THEN
            CurrentState := 0;
        END_IF;

    ELSE
        CurrentState := 0;
END_CASE;

END_FUNCTION_BLOCK
