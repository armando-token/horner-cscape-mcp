(* ============================================================================
 * Title:       PROGRAM PumpAlternationApp
 * Description: Duplex Sump Pump Level Control with Automatic Wear Alternation.
 * Features:
 *   - Quad float switch monitoring: Stop, Lead Start, Lag Start, High Alarm
 *   - Automatic lead/lag pump duty rotation based on running hours
 *   - Pump thermal overload fault trip and automatic standby switchover
 *   - Anti-short-cycling timers protecting contactors and motor windings
 * Language:    IEC 61131-3 Structured Text (Pure ST)
 * ============================================================================ *)

PROGRAM PumpAlternationApp
VAR_INPUT
    FloatStop : BOOL := FALSE;            (* Low-level stop float (TRUE = Water above stop level) *)
    FloatLead : BOOL := FALSE;            (* Mid-level lead start float (TRUE = Start lead pump) *)
    FloatLag : BOOL := FALSE;             (* High-level lag start float (TRUE = Start lag pump) *)
    FloatHighAlarm : BOOL := FALSE;       (* Emergency wet-well overflow float *)
    Pump1_Overload : BOOL := FALSE;       (* Pump 1 motor protection trip switch *)
    Pump2_Overload : BOOL := FALSE;       (* Pump 2 motor protection trip switch *)
    AutoMode : BOOL := TRUE;              (* System automatic control mode select *)
    ResetFaults : BOOL := FALSE;          (* Fault reset push button *)
END_VAR

VAR_OUTPUT
    Pump1_Run : BOOL := FALSE;            (* Contactor digital output: Pump 1 *)
    Pump2_Run : BOOL := FALSE;            (* Contactor digital output: Pump 2 *)
    LeadPump : INT := 1;                  (* Active lead pump indicator (1 or 2) *)
    LagActive : BOOL := FALSE;            (* Secondary pump actively assisting *)
    AlarmHighLevel : BOOL := FALSE;       (* High-high overflow warning beacon *)
    Pump1_Tripped : BOOL := FALSE;        (* Pump 1 locked out on overload *)
    Pump2_Tripped : BOOL := FALSE;        (* Pump 2 locked out on overload *)
    Pump1_RunHours : REAL := 0.0;         (* Accumulated operational hours: Pump 1 *)
    Pump2_RunHours : REAL := 0.0;         (* Accumulated operational hours: Pump 2 *)
END_VAR

VAR
    ScanTimeSec : REAL := 0.1;            (* Task scan interval in seconds *)
    P1_Available : BOOL := TRUE;          (* Ready status: Pump 1 *)
    P2_Available : BOOL := TRUE;          (* Ready status: Pump 2 *)
    P1_RunTimer : REAL := 0.0;            (* Anti-short-cycle timer: Pump 1 *)
    P2_RunTimer : REAL := 0.0;            (* Anti-short-cycle timer: Pump 2 *)
    MinRunSec : REAL := 10.0;             (* Minimum run time in seconds *)
    DemandLead : BOOL := FALSE;           (* Lead pump demand latch *)
    DemandLag : BOOL := FALSE;            (* Lag pump demand latch *)
END_VAR

(* 1. Overload Fault Management *)
IF ResetFaults THEN
    Pump1_Tripped := FALSE;
    Pump2_Tripped := FALSE;
END_IF;

IF Pump1_Overload THEN
    Pump1_Tripped := TRUE;
END_IF;

IF Pump2_Overload THEN
    Pump2_Tripped := TRUE;
END_IF;

P1_Available := NOT Pump1_Tripped;
P2_Available := NOT Pump2_Tripped;
AlarmHighLevel := FloatHighAlarm;

(* 2. Level Demand Logic with Float Hysteresis *)
IF FloatLead THEN
    DemandLead := TRUE;
ELSIF NOT FloatStop THEN
    DemandLead := FALSE;
    DemandLag := FALSE;
END_IF;

IF FloatLag THEN
    DemandLag := TRUE;
END_IF;

(* 3. Lead Selection and Duty Alternation on Empty *)
IF (NOT Pump1_Run) AND (NOT Pump2_Run) THEN
    IF P1_Available AND P2_Available THEN
        IF Pump1_RunHours <= Pump2_RunHours THEN
            LeadPump := 1;
        ELSE
            LeadPump := 2;
        END_IF;
    ELSIF P1_Available THEN
        LeadPump := 1;
    ELSIF P2_Available THEN
        LeadPump := 2;
    END_IF;
ELSIF LeadPump = 1 AND (NOT P1_Available) AND P2_Available THEN
    LeadPump := 2;
ELSIF LeadPump = 2 AND (NOT P2_Available) AND P1_Available THEN
    LeadPump := 1;
END_IF;

(* 4. Pump Execution Sequencing *)
IF AutoMode THEN
    IF DemandLead THEN
        IF LeadPump = 1 THEN
            Pump1_Run := P1_Available;
            Pump2_Run := (DemandLag OR (NOT P1_Available)) AND P2_Available;
        ELSE
            Pump2_Run := P2_Available;
            Pump1_Run := (DemandLag OR (NOT P2_Available)) AND P1_Available;
        END_IF;
    ELSE
        (* Below stop level: enforce minimum runtime before shutdown *)
        IF P1_RunTimer >= MinRunSec THEN
            Pump1_Run := FALSE;
        END_IF;
        IF P2_RunTimer >= MinRunSec THEN
            Pump2_Run := FALSE;
        END_IF;
    END_IF;
ELSE
    Pump1_Run := FALSE;
    Pump2_Run := FALSE;
END_IF;

LagActive := Pump1_Run AND Pump2_Run;

(* 5. Runtime and Hour Meter Accumulation *)
IF Pump1_Run THEN
    P1_RunTimer := P1_RunTimer + ScanTimeSec;
    Pump1_RunHours := Pump1_RunHours + (ScanTimeSec / 3600.0);
ELSE
    P1_RunTimer := 0.0;
END_IF;

IF Pump2_Run THEN
    P2_RunTimer := P2_RunTimer + ScanTimeSec;
    Pump2_RunHours := Pump2_RunHours + (ScanTimeSec / 3600.0);
ELSE
    P2_RunTimer := 0.0;
END_IF;

END_PROGRAM
