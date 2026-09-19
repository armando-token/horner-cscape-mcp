(* ============================================================================
 * Title:       FB_FirstFaultAnnunciator
 * Description: ISA-18.2 8-Point First-Out Alarm Annunciator with Visual & Audio Logic.
 * Features:
 *   - First-out discrimination: Identifies root-cause trip in cascading outages
 *   - Visual flashing states: Fast flash (First-Out), Slow flash (Subsequent)
 *   - Steady illumination upon operator acknowledgment
 *   - Audible horn driving with silence/acknowledge push button
 *   - Reset interlock: Alarms clear only when field conditions return to normal
 *   - Lamp Test pushbutton to verify panel indicators and audible sounder
 * Language:    IEC 61131-3 Structured Text (Pure ST)
 * ============================================================================ *)

FUNCTION_BLOCK FB_FirstFaultAnnunciator
VAR_INPUT
    AlarmIn1 : BOOL := FALSE;             (* Point 1: e.g. Emergency Stop tripped *)
    AlarmIn2 : BOOL := FALSE;             (* Point 2: e.g. High-High Vessel Pressure *)
    AlarmIn3 : BOOL := FALSE;             (* Point 3: e.g. High-High Reactor Temperature *)
    AlarmIn4 : BOOL := FALSE;             (* Point 4: e.g. Low-Low Lube Oil Pressure *)
    AlarmIn5 : BOOL := FALSE;             (* Point 5: e.g. Motor Overload Breaker *)
    AlarmIn6 : BOOL := FALSE;             (* Point 6: e.g. Sump High Spill Level *)
    AlarmIn7 : BOOL := FALSE;             (* Point 7: e.g. Instrument Air Low Pressure *)
    AlarmIn8 : BOOL := FALSE;             (* Point 8: e.g. Combustible Gas Detector *)
    AckPB : BOOL := FALSE;                (* Operator Acknowledge push button *)
    ResetPB : BOOL := FALSE;              (* Operator Reset push button *)
    TestPB : BOOL := FALSE;               (* Lamp / Horn Test push button *)
    CycleTimeSec : REAL := 0.1;           (* Scan delta time (seconds) *)
END_VAR

VAR_OUTPUT
    Horn : BOOL := FALSE;                 (* Digital output: Audible alarm sounder *)
    Beacon1 : BOOL := FALSE;              (* Digital output: Lamp for Point 1 *)
    Beacon2 : BOOL := FALSE;              (* Digital output: Lamp for Point 2 *)
    Beacon3 : BOOL := FALSE;              (* Digital output: Lamp for Point 3 *)
    Beacon4 : BOOL := FALSE;              (* Digital output: Lamp for Point 4 *)
    Beacon5 : BOOL := FALSE;              (* Digital output: Lamp for Point 5 *)
    Beacon6 : BOOL := FALSE;              (* Digital output: Lamp for Point 6 *)
    Beacon7 : BOOL := FALSE;              (* Digital output: Lamp for Point 7 *)
    Beacon8 : BOOL := FALSE;              (* Digital output: Lamp for Point 8 *)
    FirstOutId : INT := 0;                (* ID of the root-cause first alarm (1 to 8, 0=None) *)
    AnyAlarmActive : BOOL := FALSE;       (* TRUE if any alarm is currently in alarm state *)
    AnyUnack : BOOL := FALSE;             (* TRUE if any alarm remains unacknowledged *)
END_VAR

VAR
    FlashTimerFast : REAL := 0.0;         (* Accumulator for 2.0 Hz fast flasher *)
    FlashTimerSlow : REAL := 0.0;         (* Accumulator for 1.0 Hz slow flasher *)
    FlashFastState : BOOL := FALSE;       (* Fast flash toggle signal *)
    FlashSlowState : BOOL := FALSE;       (* Slow flash toggle signal *)
    Latched1 : BOOL := FALSE;             (* Latched alarm state for Point 1 *)
    Latched2 : BOOL := FALSE;             (* Latched alarm state for Point 2 *)
    Latched3 : BOOL := FALSE;             (* Latched alarm state for Point 3 *)
    Latched4 : BOOL := FALSE;             (* Latched alarm state for Point 4 *)
    Latched5 : BOOL := FALSE;             (* Latched alarm state for Point 5 *)
    Latched6 : BOOL := FALSE;             (* Latched alarm state for Point 6 *)
    Latched7 : BOOL := FALSE;             (* Latched alarm state for Point 7 *)
    Latched8 : BOOL := FALSE;             (* Latched alarm state for Point 8 *)
    Ack1 : BOOL := FALSE;                 (* Acknowledged state for Point 1 *)
    Ack2 : BOOL := FALSE;                 (* Acknowledged state for Point 2 *)
    Ack3 : BOOL := FALSE;                 (* Acknowledged state for Point 3 *)
    Ack4 : BOOL := FALSE;                 (* Acknowledged state for Point 4 *)
    Ack5 : BOOL := FALSE;                 (* Acknowledged state for Point 5 *)
    Ack6 : BOOL := FALSE;                 (* Acknowledged state for Point 6 *)
    Ack7 : BOOL := FALSE;                 (* Acknowledged state for Point 7 *)
    Ack8 : BOOL := FALSE;                 (* Acknowledged state for Point 8 *)
END_VAR

(* 1. Flasher Oscillators (Fast = 250ms half-period, Slow = 500ms half-period) *)
FlashTimerFast := FlashTimerFast + CycleTimeSec;
IF FlashTimerFast >= 0.25 THEN
    FlashTimerFast := 0.0;
    FlashFastState := NOT FlashFastState;
END_IF;

FlashTimerSlow := FlashTimerSlow + CycleTimeSec;
IF FlashTimerSlow >= 0.50 THEN
    FlashTimerSlow := 0.0;
    FlashSlowState := NOT FlashSlowState;
END_IF;

(* 2. First-Out Latching and Point Alarm Acquisition *)
IF AlarmIn1 THEN Latched1 := TRUE; END_IF;
IF AlarmIn2 THEN Latched2 := TRUE; END_IF;
IF AlarmIn3 THEN Latched3 := TRUE; END_IF;
IF AlarmIn4 THEN Latched4 := TRUE; END_IF;
IF AlarmIn5 THEN Latched5 := TRUE; END_IF;
IF AlarmIn6 THEN Latched6 := TRUE; END_IF;
IF AlarmIn7 THEN Latched7 := TRUE; END_IF;
IF AlarmIn8 THEN Latched8 := TRUE; END_IF;

IF FirstOutId = 0 THEN
    IF AlarmIn1 THEN FirstOutId := 1;
    ELSIF AlarmIn2 THEN FirstOutId := 2;
    ELSIF AlarmIn3 THEN FirstOutId := 3;
    ELSIF AlarmIn4 THEN FirstOutId := 4;
    ELSIF AlarmIn5 THEN FirstOutId := 5;
    ELSIF AlarmIn6 THEN FirstOutId := 6;
    ELSIF AlarmIn7 THEN FirstOutId := 7;
    ELSIF AlarmIn8 THEN FirstOutId := 8;
    END_IF;
END_IF;

(* 3. Operator Acknowledge PB *)
IF AckPB THEN
    IF Latched1 THEN Ack1 := TRUE; END_IF;
    IF Latched2 THEN Ack2 := TRUE; END_IF;
    IF Latched3 THEN Ack3 := TRUE; END_IF;
    IF Latched4 THEN Ack4 := TRUE; END_IF;
    IF Latched5 THEN Ack5 := TRUE; END_IF;
    IF Latched6 THEN Ack6 := TRUE; END_IF;
    IF Latched7 THEN Ack7 := TRUE; END_IF;
    IF Latched8 THEN Ack8 := TRUE; END_IF;
END_IF;

(* 4. Operator Reset PB (clears points only if field sensor is normal AND acknowledged) *)
IF ResetPB THEN
    IF Ack1 AND (NOT AlarmIn1) THEN Latched1 := FALSE; Ack1 := FALSE; END_IF;
    IF Ack2 AND (NOT AlarmIn2) THEN Latched2 := FALSE; Ack2 := FALSE; END_IF;
    IF Ack3 AND (NOT AlarmIn3) THEN Latched3 := FALSE; Ack3 := FALSE; END_IF;
    IF Ack4 AND (NOT AlarmIn4) THEN Latched4 := FALSE; Ack4 := FALSE; END_IF;
    IF Ack5 AND (NOT AlarmIn5) THEN Latched5 := FALSE; Ack5 := FALSE; END_IF;
    IF Ack6 AND (NOT AlarmIn6) THEN Latched6 := FALSE; Ack6 := FALSE; END_IF;
    IF Ack7 AND (NOT AlarmIn7) THEN Latched7 := FALSE; Ack7 := FALSE; END_IF;
    IF Ack8 AND (NOT AlarmIn8) THEN Latched8 := FALSE; Ack8 := FALSE; END_IF;

    (* Reset FirstOutId if all latches have cleared *)
    IF (NOT Latched1) AND (NOT Latched2) AND (NOT Latched3) AND (NOT Latched4) AND (NOT Latched5) AND (NOT Latched6) AND (NOT Latched7) AND (NOT Latched8) THEN
        FirstOutId := 0;
    END_IF;
END_IF;

(* 5. Supervisory Summary Flags *)
AnyAlarmActive := Latched1 OR Latched2 OR Latched3 OR Latched4 OR Latched5 OR Latched6 OR Latched7 OR Latched8;

AnyUnack := (Latched1 AND NOT Ack1) OR (Latched2 AND NOT Ack2) OR (Latched3 AND NOT Ack3) OR (Latched4 AND NOT Ack4) OR (Latched5 AND NOT Ack5) OR (Latched6 AND NOT Ack6) OR (Latched7 AND NOT Ack7) OR (Latched8 AND NOT Ack8);

(* 6. Audible Horn Logic *)
IF TestPB THEN
    Horn := TRUE;
ELSIF AnyUnack THEN
    Horn := TRUE;
ELSE
    Horn := FALSE;
END_IF;

(* 7. Visual Beacon Illumination Logic *)
IF TestPB THEN
    Beacon1 := TRUE; Beacon2 := TRUE; Beacon3 := TRUE; Beacon4 := TRUE;
    Beacon5 := TRUE; Beacon6 := TRUE; Beacon7 := TRUE; Beacon8 := TRUE;
ELSE
    (* Point 1 *)
    IF NOT Latched1 THEN Beacon1 := FALSE;
    ELSIF FirstOutId = 1 AND (NOT Ack1) THEN Beacon1 := FlashFastState;
    ELSIF NOT Ack1 THEN Beacon1 := FlashSlowState;
    ELSE Beacon1 := TRUE;
    END_IF;

    (* Point 2 *)
    IF NOT Latched2 THEN Beacon2 := FALSE;
    ELSIF FirstOutId = 2 AND (NOT Ack2) THEN Beacon2 := FlashFastState;
    ELSIF NOT Ack2 THEN Beacon2 := FlashSlowState;
    ELSE Beacon2 := TRUE;
    END_IF;

    (* Point 3 *)
    IF NOT Latched3 THEN Beacon3 := FALSE;
    ELSIF FirstOutId = 3 AND (NOT Ack3) THEN Beacon3 := FlashFastState;
    ELSIF NOT Ack3 THEN Beacon3 := FlashSlowState;
    ELSE Beacon3 := TRUE;
    END_IF;

    (* Point 4 *)
    IF NOT Latched4 THEN Beacon4 := FALSE;
    ELSIF FirstOutId = 4 AND (NOT Ack4) THEN Beacon4 := FlashFastState;
    ELSIF NOT Ack4 THEN Beacon4 := FlashSlowState;
    ELSE Beacon4 := TRUE;
    END_IF;

    (* Point 5 *)
    IF NOT Latched5 THEN Beacon5 := FALSE;
    ELSIF FirstOutId = 5 AND (NOT Ack5) THEN Beacon5 := FlashFastState;
    ELSIF NOT Ack5 THEN Beacon5 := FlashSlowState;
    ELSE Beacon5 := TRUE;
    END_IF;

    (* Point 6 *)
    IF NOT Latched6 THEN Beacon6 := FALSE;
    ELSIF FirstOutId = 6 AND (NOT Ack6) THEN Beacon6 := FlashFastState;
    ELSIF NOT Ack6 THEN Beacon6 := FlashSlowState;
    ELSE Beacon6 := TRUE;
    END_IF;

    (* Point 7 *)
    IF NOT Latched7 THEN Beacon7 := FALSE;
    ELSIF FirstOutId = 7 AND (NOT Ack7) THEN Beacon7 := FlashFastState;
    ELSIF NOT Ack7 THEN Beacon7 := FlashSlowState;
    ELSE Beacon7 := TRUE;
    END_IF;

    (* Point 8 *)
    IF NOT Latched8 THEN Beacon8 := FALSE;
    ELSIF FirstOutId = 8 AND (NOT Ack8) THEN Beacon8 := FlashFastState;
    ELSIF NOT Ack8 THEN Beacon8 := FlashSlowState;
    ELSE Beacon8 := TRUE;
    END_IF;
END_IF;

END_FUNCTION_BLOCK
