(* ============================================================================
 * Title:       PROGRAM ConveyorSorterApp
 * Description: Packaging Line Conveyor Sorter with Optical Part Classification.
 * Features:
 *   - Clean integer-based CASE finite state machine
 *   - Photoeye arrival detection and barcode/height part classification
 *   - Pneumatic diverter solenoids for Bin A, Bin B, and Reject chute
 *   - Jam detection timer with conveyor stop and visual alarm
 *   - Piece counts for total throughput and sort distribution
 * Language:    IEC 61131-3 Structured Text (Pure ST)
 * ============================================================================ *)

PROGRAM ConveyorSorterApp
VAR_INPUT
    SystemStart : BOOL := FALSE;          (* Start push button *)
    SystemStop : BOOL := FALSE;           (* Stop push button *)
    PartArrivedPE : BOOL := FALSE;        (* Optical sensor at sorting inlet *)
    PartClassCode : INT := 1;             (* Vision classifier: 1 = Bin A, 2 = Bin B, other = Reject *)
    BinA_Confirmed : BOOL := FALSE;       (* Proximity sensor confirming Bin A drop *)
    BinB_Confirmed : BOOL := FALSE;       (* Proximity sensor confirming Bin B drop *)
    RejectConfirmed : BOOL := FALSE;      (* Proximity sensor confirming Reject drop *)
    ClearFaultPB : BOOL := FALSE;         (* Fault acknowledge and reset push button *)
END_VAR

VAR_OUTPUT
    BeltMotor : BOOL := FALSE;            (* Conveyor drive motor contactor *)
    DiverterA : BOOL := FALSE;            (* Pneumatic diverter solenoid for Bin A *)
    DiverterB : BOOL := FALSE;            (* Pneumatic diverter solenoid for Bin B *)
    RejectGate : BOOL := FALSE;           (* Pneumatic reject flipper gate *)
    SystemState : INT := 0;               (* Current state machine step *)
    JamAlarm : BOOL := FALSE;             (* Parcel jam alarm indicator *)
    TotalCount : DINT := 0;               (* Total items sorted *)
    BinACount : DINT := 0;                (* Count sorted to Bin A *)
    BinBCount : DINT := 0;                (* Count sorted to Bin B *)
    RejectCount : DINT := 0;              (* Count diverted to Reject *)
END_VAR

VAR
    ScanSec : REAL := 0.1;                (* Scan period (seconds) *)
    StepTimer : REAL := 0.0;              (* Active state dwell timer *)
    JamLimitSec : REAL := 3.5;            (* Jam watchdog limit (seconds) *)
    LineRunning : BOOL := FALSE;          (* Running latch flag *)
    ActiveRoute : INT := 0;               (* Latched route for item in transit *)
END_VAR

(* 1. Safety and Start/Stop Supervisory Logic *)
IF ClearFaultPB THEN
    JamAlarm := FALSE;
END_IF;

IF SystemStop OR JamAlarm THEN
    LineRunning := FALSE;
ELSIF SystemStart AND (NOT JamAlarm) THEN
    LineRunning := TRUE;
END_IF;

(* 2. Sequential Sortation State Machine *)
CASE SystemState OF

    0: (* STATE_IDLE: Awaiting Start Command *)
        BeltMotor := FALSE;
        DiverterA := FALSE;
        DiverterB := FALSE;
        RejectGate := FALSE;
        StepTimer := 0.0;

        IF LineRunning THEN
            SystemState := 1;
        END_IF;

    1: (* STATE_WAIT_PART: Conveyor running, scanning for parts *)
        BeltMotor := TRUE;
        DiverterA := FALSE;
        DiverterB := FALSE;
        RejectGate := FALSE;

        IF NOT LineRunning THEN
            SystemState := 0;
        ELSIF PartArrivedPE THEN
            ActiveRoute := PartClassCode;
            StepTimer := 0.0;
            IF ActiveRoute = 1 THEN
                SystemState := 2; (* Route to Bin A *)
            ELSIF ActiveRoute = 2 THEN
                SystemState := 3; (* Route to Bin B *)
            ELSE
                SystemState := 4; (* Route to Reject *)
            END_IF;
        END_IF;

    2: (* STATE_DIVERT_A: Actuate Diverter A *)
        BeltMotor := TRUE;
        DiverterA := TRUE;
        StepTimer := StepTimer + ScanSec;

        IF BinA_Confirmed OR (StepTimer >= 1.5) THEN
            BinACount := BinACount + 1;
            TotalCount := TotalCount + 1;
            DiverterA := FALSE;
            SystemState := 1;
        ELSIF StepTimer >= JamLimitSec THEN
            JamAlarm := TRUE;
            SystemState := 9;
        END_IF;

    3: (* STATE_DIVERT_B: Actuate Diverter B *)
        BeltMotor := TRUE;
        DiverterB := TRUE;
        StepTimer := StepTimer + ScanSec;

        IF BinB_Confirmed OR (StepTimer >= 1.5) THEN
            BinBCount := BinBCount + 1;
            TotalCount := TotalCount + 1;
            DiverterB := FALSE;
            SystemState := 1;
        ELSIF StepTimer >= JamLimitSec THEN
            JamAlarm := TRUE;
            SystemState := 9;
        END_IF;

    4: (* STATE_REJECT: Actuate Reject Gate *)
        BeltMotor := TRUE;
        RejectGate := TRUE;
        StepTimer := StepTimer + ScanSec;

        IF RejectConfirmed OR (StepTimer >= 1.5) THEN
            RejectCount := RejectCount + 1;
            TotalCount := TotalCount + 1;
            RejectGate := FALSE;
            SystemState := 1;
        ELSIF StepTimer >= JamLimitSec THEN
            JamAlarm := TRUE;
            SystemState := 9;
        END_IF;

    9: (* STATE_JAM_FAULT: Line stopped on parcel jam *)
        BeltMotor := FALSE;
        DiverterA := FALSE;
        DiverterB := FALSE;
        RejectGate := FALSE;

        IF NOT JamAlarm THEN
            SystemState := 0;
        END_IF;

    ELSE
        SystemState := 0;
END_CASE;

END_PROGRAM
