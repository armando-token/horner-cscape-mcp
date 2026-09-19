(* ============================================================================
 * Title:       PROGRAM TrafficControlApp
 * Description: Dual-Phase Roadway Intersection Controller with Conflict Monitoring.
 * Features:
 *   - 6-Phase state sequence: NS Green/Yellow/All-Red, EW Green/Yellow/All-Red
 *   - Vehicle inductive loop detector demand extension
 *   - Pedestrian crosswalk call buttons with Walk / Don't Walk signals
 *   - Failsafe green-conflict hardware interlock detecting conflicting greens
 *   - Emergency yellow/red flashing fault mode
 * Language:    IEC 61131-3 Structured Text (Pure ST)
 * ============================================================================ *)

PROGRAM TrafficControlApp
VAR_INPUT
    VehicleCall_NS : BOOL := FALSE;       (* Inductive loop: Vehicle waiting on North-South *)
    VehicleCall_EW : BOOL := FALSE;       (* Inductive loop: Vehicle waiting on East-West *)
    PedCall_NS : BOOL := FALSE;           (* Push button: Pedestrian crossing East-West (NS Walk) *)
    PedCall_EW : BOOL := FALSE;           (* Push button: Pedestrian crossing North-South (EW Walk) *)
    ResetConflict : BOOL := FALSE;        (* Technician key switch to reset conflict monitor *)
END_VAR

VAR_OUTPUT
    Light_NS_Red : BOOL := TRUE;          (* North-South signal: Red lamp *)
    Light_NS_Yellow : BOOL := FALSE;      (* North-South signal: Yellow lamp *)
    Light_NS_Green : BOOL := FALSE;       (* North-South signal: Green lamp *)
    Light_EW_Red : BOOL := TRUE;          (* East-West signal: Red lamp *)
    Light_EW_Yellow : BOOL := FALSE;      (* East-West signal: Yellow lamp *)
    Light_EW_Green : BOOL := FALSE;       (* East-West signal: Green lamp *)
    Ped_NS_Walk : BOOL := FALSE;          (* North-South pedestrian Walk illuminated *)
    Ped_EW_Walk : BOOL := FALSE;          (* East-West pedestrian Walk illuminated *)
    ActivePhase : INT := 1;               (* Current traffic phase step code *)
    ConflictFault : BOOL := FALSE;        (* Emergency: Conflicting greens detected *)
END_VAR

VAR
    ScanSec : REAL := 0.1;                (* Cyclic scan time (seconds) *)
    PhaseTimer : REAL := 0.0;             (* Elapsed time in active phase *)
    MinGreenSec : REAL := 10.0;           (* Minimum green interval *)
    MaxGreenSec : REAL := 30.0;           (* Maximum green interval *)
    YellowTimeSec : REAL := 3.5;          (* Yellow clearance interval *)
    AllRedTimeSec : REAL := 2.0;          (* All-red clearance safety interval *)
    PedLatched_NS : BOOL := FALSE;        (* Latched pedestrian call *)
    PedLatched_EW : BOOL := FALSE;        (* Latched pedestrian call *)
    FlashTimer : REAL := 0.0;             (* Flasher timer during conflict fault *)
    FlashState : BOOL := FALSE;           (* Flashing toggle signal *)
END_VAR

(* 1. Conflict Fault Reset and Safety Interlock *)
IF ResetConflict THEN
    ConflictFault := FALSE;
END_IF;

(* Green Conflict Monitor: Conflicting greens must never be TRUE together *)
IF Light_NS_Green AND Light_EW_Green THEN
    ConflictFault := TRUE;
END_IF;

(* 2. Latch Pedestrian Calls *)
IF PedCall_NS THEN PedLatched_NS := TRUE; END_IF;
IF PedCall_EW THEN PedLatched_EW := TRUE; END_IF;

(* 3. Conflict Fault Emergency Flashing (All Red flashing at 1 Hz) *)
IF ConflictFault THEN
    FlashTimer := FlashTimer + ScanSec;
    IF FlashTimer >= 0.5 THEN
        FlashTimer := 0.0;
        FlashState := NOT FlashState;
    END_IF;

    Light_NS_Green := FALSE;
    Light_NS_Yellow := FALSE;
    Light_NS_Red := FlashState;
    Light_EW_Green := FALSE;
    Light_EW_Yellow := FALSE;
    Light_EW_Red := FlashState;
    Ped_NS_Walk := FALSE;
    Ped_EW_Walk := FALSE;
    RETURN;
END_IF;

(* 4. Sequential Phase State Machine *)
PhaseTimer := PhaseTimer + ScanSec;

CASE ActivePhase OF

    1: (* PHASE_NS_GREEN: North-South Flowing *)
        Light_NS_Red := FALSE;
        Light_NS_Yellow := FALSE;
        Light_NS_Green := TRUE;
        Light_EW_Red := TRUE;
        Light_EW_Yellow := FALSE;
        Light_EW_Green := FALSE;
        Ped_NS_Walk := PedLatched_NS AND (PhaseTimer <= 7.0);
        Ped_EW_Walk := FALSE;

        (* Transition to NS Yellow if min green expired and opposing demand exists, or max green reached *)
        IF (PhaseTimer >= MinGreenSec AND (VehicleCall_EW OR PedLatched_EW)) OR (PhaseTimer >= MaxGreenSec) THEN
            PedLatched_NS := FALSE;
            PhaseTimer := 0.0;
            ActivePhase := 2;
        END_IF;

    2: (* PHASE_NS_YELLOW: North-South Clearance *)
        Light_NS_Green := FALSE;
        Light_NS_Yellow := TRUE;
        Light_NS_Red := FALSE;
        Light_EW_Red := TRUE;
        Ped_NS_Walk := FALSE;

        IF PhaseTimer >= YellowTimeSec THEN
            PhaseTimer := 0.0;
            ActivePhase := 3;
        END_IF;

    3: (* PHASE_ALL_RED_1: Safety Buffer before EW Green *)
        Light_NS_Yellow := FALSE;
        Light_NS_Red := TRUE;
        Light_EW_Red := TRUE;

        IF PhaseTimer >= AllRedTimeSec THEN
            PhaseTimer := 0.0;
            ActivePhase := 4;
        END_IF;

    4: (* PHASE_EW_GREEN: East-West Flowing *)
        Light_NS_Red := TRUE;
        Light_NS_Yellow := FALSE;
        Light_NS_Green := FALSE;
        Light_EW_Red := FALSE;
        Light_EW_Yellow := FALSE;
        Light_EW_Green := TRUE;
        Ped_EW_Walk := PedLatched_EW AND (PhaseTimer <= 7.0);
        Ped_NS_Walk := FALSE;

        (* Transition to EW Yellow if min green expired and opposing demand exists, or max green reached *)
        IF (PhaseTimer >= MinGreenSec AND (VehicleCall_NS OR PedLatched_NS)) OR (PhaseTimer >= MaxGreenSec) THEN
            PedLatched_EW := FALSE;
            PhaseTimer := 0.0;
            ActivePhase := 5;
        END_IF;

    5: (* PHASE_EW_YELLOW: East-West Clearance *)
        Light_EW_Green := FALSE;
        Light_EW_Yellow := TRUE;
        Light_EW_Red := FALSE;
        Light_NS_Red := TRUE;
        Ped_EW_Walk := FALSE;

        IF PhaseTimer >= YellowTimeSec THEN
            PhaseTimer := 0.0;
            ActivePhase := 6;
        END_IF;

    6: (* PHASE_ALL_RED_2: Safety Buffer before NS Green *)
        Light_EW_Yellow := FALSE;
        Light_EW_Red := TRUE;
        Light_NS_Red := TRUE;

        IF PhaseTimer >= AllRedTimeSec THEN
            PhaseTimer := 0.0;
            ActivePhase := 1;
        END_IF;

    ELSE
        ActivePhase := 1;
END_CASE;

END_PROGRAM
