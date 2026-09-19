(* ============================================================================
 * Title:       FB_ValveActuator
 * Description: Industrial Process Valve Actuator Controller with End-Position Watchdog.
 * Features:
 *   - Open and Close commanding with pulse or continuous solenoid output
 *   - Dual limit switch position feedback (Open and Closed end-stops)
 *   - Transit time watchdog timer detecting jammed or slow-stroking valves
 *   - Process safety interlock permissives inhibiting valve motion
 *   - Valve cycle counter and accumulated running transit time monitoring
 *   - Inconsistent limit switch fault detection (both open and closed active)
 * Language:    IEC 61131-3 Structured Text (Pure ST)
 * ============================================================================ *)

FUNCTION_BLOCK FB_ValveActuator
VAR_INPUT
    OpenCmd : BOOL := FALSE;              (* Request valve open command *)
    CloseCmd : BOOL := FALSE;             (* Request valve close command *)
    LimitOpen : BOOL := FALSE;            (* End-switch: Valve is fully open *)
    LimitClosed : BOOL := TRUE;           (* End-switch: Valve is fully closed *)
    InterlockOpen : BOOL := TRUE;         (* Safety permissive to permit opening (TRUE = OK) *)
    InterlockClose : BOOL := TRUE;        (* Safety permissive to permit closing (TRUE = OK) *)
    PulseMode : BOOL := FALSE;            (* TRUE = momentary solenoid pulse, FALSE = continuous *)
    PulseDurationSec : REAL := 2.0;       (* Pulse output hold duration (seconds) *)
    TransitTimeoutSec : REAL := 12.0;     (* Max permitted travel duration before travel fault *)
    ResetFault : BOOL := FALSE;           (* Push button to clear latched faults *)
    CycleTimeSec : REAL := 0.1;           (* Execution period of calling cyclic task (seconds) *)
END_VAR

VAR_OUTPUT
    SolOpen : BOOL := FALSE;              (* Physical digital output: Open solenoid / actuator *)
    SolClose : BOOL := FALSE;             (* Physical digital output: Close solenoid / actuator *)
    IsOpen : BOOL := FALSE;               (* Confirmed fully open state *)
    IsClosed : BOOL := TRUE;              (* Confirmed fully closed state *)
    IsTraveling : BOOL := FALSE;          (* Valve is currently in intermediate travel *)
    TravelFault : BOOL := FALSE;          (* Valve failed to reach target limit switch within timeout *)
    SwitchFault : BOOL := FALSE;          (* Sensor fault: Both open and closed limits are active simultaneously *)
    TotalCycles : DINT := 0;              (* Total full open-and-close cycles completed *)
    TransitTimeSec : REAL := 0.0;         (* Actual time taken during last complete stroke *)
END_VAR

VAR
    TargetOpen : BOOL := FALSE;           (* Desired position: TRUE = Open, FALSE = Closed *)
    TravelTimer : REAL := 0.0;            (* Elapsed stroke timer in seconds *)
    PulseTimer : REAL := 0.0;             (* Solenoid pulse energization timer *)
    PrevIsOpen : BOOL := FALSE;           (* Edge detection memory for cycle count *)
END_VAR

(* 1. Fault Reset *)
IF ResetFault THEN
    TravelFault := FALSE;
    SwitchFault := FALSE;
END_IF;

(* 2. Limit Switch Integrity Check *)
IF LimitOpen AND LimitClosed THEN
    SwitchFault := TRUE;
END_IF;

(* 3. Command Evaluation & Interlock Supervision *)
IF OpenCmd AND (NOT CloseCmd) THEN
    IF InterlockOpen AND (NOT TravelFault) AND (NOT SwitchFault) THEN
        TargetOpen := TRUE;
    END_IF;
ELSIF CloseCmd AND (NOT OpenCmd) THEN
    IF InterlockClose AND (NOT TravelFault) AND (NOT SwitchFault) THEN
        TargetOpen := FALSE;
    END_IF;
END_IF;

(* 4. Motion and Travel Timer Execution *)
IF TargetOpen THEN
    (* Commanding Open *)
    IF LimitOpen THEN
        (* Target reached *)
        SolOpen := FALSE;
        SolClose := FALSE;
        IsTraveling := FALSE;
        IF TravelTimer > 0.0 THEN
            TransitTimeSec := TravelTimer;
        END_IF;
        TravelTimer := 0.0;
        PulseTimer := 0.0;
    ELSE
        (* Currently in transit toward Open *)
        IsTraveling := TRUE;
        TravelTimer := TravelTimer + CycleTimeSec;

        IF TravelTimer >= TransitTimeoutSec THEN
            TravelFault := TRUE;
            SolOpen := FALSE;
            IsTraveling := FALSE;
        ELSE
            IF PulseMode THEN
                PulseTimer := PulseTimer + CycleTimeSec;
                SolOpen := PulseTimer <= PulseDurationSec;
            ELSE
                SolOpen := TRUE;
            END_IF;
            SolClose := FALSE;
        END_IF;
    END_IF;
ELSE
    (* Commanding Close *)
    IF LimitClosed THEN
        (* Target reached *)
        SolOpen := FALSE;
        SolClose := FALSE;
        IsTraveling := FALSE;
        IF TravelTimer > 0.0 THEN
            TransitTimeSec := TravelTimer;
        END_IF;
        TravelTimer := 0.0;
        PulseTimer := 0.0;
    ELSE
        (* Currently in transit toward Close *)
        IsTraveling := TRUE;
        TravelTimer := TravelTimer + CycleTimeSec;

        IF TravelTimer >= TransitTimeoutSec THEN
            TravelFault := TRUE;
            SolClose := FALSE;
            IsTraveling := FALSE;
        ELSE
            IF PulseMode THEN
                PulseTimer := PulseTimer + CycleTimeSec;
                SolClose := PulseTimer <= PulseDurationSec;
            ELSE
                SolClose := TRUE;
            END_IF;
            SolOpen := FALSE;
        END_IF;
    END_IF;
END_IF;

(* 5. Status Decoding *)
IsOpen := LimitOpen AND (NOT LimitClosed);
IsClosed := LimitClosed AND (NOT LimitOpen);

(* 6. Cycle Counter on confirmed full opening edge *)
IF IsOpen AND (NOT PrevIsOpen) THEN
    TotalCycles := TotalCycles + 1;
END_IF;
PrevIsOpen := IsOpen;

END_FUNCTION_BLOCK
