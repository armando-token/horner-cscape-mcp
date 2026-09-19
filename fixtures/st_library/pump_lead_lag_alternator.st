(* ============================================================================
 * Title:       FB_PumpLeadLagAlternator
 * Description: Industrial Duplex Lead-Lag Alternating Pump Controller with
 *              Wear-Leveling, Sub-Second Failover, Dual-Pump Boost, and
 *              Anti-Hunting Debounce Timers.
 * Features:
 *   - Lead/Lag pump duty alternation based on accumulated runtime hours (%R151, %R152)
 *   - Automatic sub-second failover to standby pump if lead pump trips or faults (%M83, %M84)
 *   - High-demand dual-pump boost mode when system pressure falls below low setpoint
 *   - Manual pump force/override switches for maintenance
 *   - Pump start/stop anti-hunting debouncing and minimum run/rest timers
 * Language:    IEC 61131-3 Structured Text (Pure ST Only)
 * OCS Mapping:
 *   %R151: Pump1_Runtime_Hours (REAL: Accumulated runtime hours for Pump 1)
 *   %R152: Pump2_Runtime_Hours (REAL: Accumulated runtime hours for Pump 2)
 *   %R153: System_Pressure_PSI (REAL: Current system discharge header pressure)
 *   %R154: Lead_Start_SP (REAL: Pressure threshold to start lead pump)
 *   %R155: Boost_Start_SP (REAL: Pressure threshold for dual-pump boost mode)
 *   %R156: Stop_SP (REAL: Pressure threshold to stop pumps)
 *   %M81:  Manual_Mode_Select (BOOL: TRUE = Manual, FALSE = Auto)
 *   %M82:  Auto_Enable (BOOL: Master automatic staging permissive)
 *   %M83:  Pump1_Trip_Fault (BOOL: Pump 1 thermal overload / drive trip)
 *   %M84:  Pump2_Trip_Fault (BOOL: Pump 2 thermal overload / drive trip)
 *   %M85:  Pump1_Manual_Override (BOOL: Manual force run command for Pump 1)
 *   %M86:  Pump2_Manual_Override (BOOL: Manual force run command for Pump 2)
 *   %M87:  Pump1_Lockout (BOOL: Maintenance lockout switch for Pump 1)
 *   %M88:  Pump2_Lockout (BOOL: Maintenance lockout switch for Pump 2)
 *   %M89:  Fault_Reset (BOOL: Latch clear / fault reset push button)
 *   %Q51:  Pump1_Run_Cmd (BOOL: Digital output contactor / VFD run for Pump 1)
 *   %Q52:  Pump2_Run_Cmd (BOOL: Digital output contactor / VFD run for Pump 2)
 *   %M91:  Boost_Mode_Active (BOOL: Dual-pump boost mode active)
 *   %M92:  Failover_Active (BOOL: Sub-second failover active)
 * ============================================================================ *)

FUNCTION_BLOCK FB_PumpLeadLagAlternator
VAR_INPUT
    Auto_Enable : BOOL := TRUE;                    (* Master automatic staging permissive (%M82) *)
    System_Pressure_PSI : REAL := 55.0;            (* System header pressure measurement (%R153) *)
    Lead_Start_SP : REAL := 45.0;                  (* Header pressure threshold to start lead pump (%R154) *)
    Boost_Start_SP : REAL := 35.0;                 (* Low pressure threshold for dual-pump boost mode (%R155) *)
    Stop_SP : REAL := 60.0;                        (* High pressure threshold to stop running pumps (%R156) *)
    Pump1_Trip_Fault : BOOL := FALSE;              (* Pump 1 thermal overload / drive trip (%M83) *)
    Pump2_Trip_Fault : BOOL := FALSE;              (* Pump 2 thermal overload / drive trip (%M84) *)
    Manual_Mode_Select : BOOL := FALSE;            (* Mode selector: TRUE = Manual Hand, FALSE = Auto (%M81) *)
    Pump1_Manual_Override : BOOL := FALSE;         (* Manual force run switch for Pump 1 (%M85) *)
    Pump2_Manual_Override : BOOL := FALSE;         (* Manual force run switch for Pump 2 (%M86) *)
    Pump1_Lockout : BOOL := FALSE;                 (* Maintenance lockout switch for Pump 1 (%M87) *)
    Pump2_Lockout : BOOL := FALSE;                 (* Maintenance lockout switch for Pump 2 (%M88) *)
    Fault_Reset : BOOL := FALSE;                   (* Latch clear / fault reset push button (%M89) *)
    Debounce_Time_Sec : REAL := 2.0;               (* Anti-hunting pressure qualification debounce delay *)
    Min_Run_Time_Sec : REAL := 15.0;               (* Minimum run time to prevent short cycling *)
    Min_Rest_Time_Sec : REAL := 20.0;              (* Minimum resting delay before motor restart *)
    Cycle_Time_Sec : REAL := 0.1;                  (* Scan execution period in seconds *)
END_VAR

VAR_OUTPUT
    Pump1_Run_Cmd : BOOL := FALSE;                 (* Command contactor / VFD run for Pump 1 (%Q51) *)
    Pump2_Run_Cmd : BOOL := FALSE;                 (* Command contactor / VFD run for Pump 2 (%Q52) *)
    Lead_Pump_Id : INT := 1;                       (* Current lead pump assignment (1 or 2) *)
    Lag_Pump_Id : INT := 2;                        (* Current lag / standby pump assignment (1 or 2) *)
    Boost_Mode_Active : BOOL := FALSE;             (* Dual-pump boost mode active due to high demand (%M91) *)
    Failover_Active : BOOL := FALSE;               (* Sub-second failover active due to lead pump trip (%M92) *)
    Pump1_Runtime_Hours : REAL := 0.0;             (* Accumulated running hours for Pump 1 (%R151) *)
    Pump2_Runtime_Hours : REAL := 0.0;             (* Accumulated running hours for Pump 2 (%R152) *)
    Pump1_Starts_Count : DINT := 0;                (* Total start cycles on Pump 1 *)
    Pump2_Starts_Count : DINT := 0;                (* Total start cycles on Pump 2 *)
    Pump1_Fault_Latched : BOOL := FALSE;           (* Latched trip status for Pump 1 *)
    Pump2_Fault_Latched : BOOL := FALSE;           (* Latched trip status for Pump 2 *)
    System_Fault_Alarm : BOOL := FALSE;            (* Alarm: No healthy pumps available to service demand *)
END_VAR

VAR
    P1_Run_Timer : REAL := 0.0;                    (* Current cycle run timer for Pump 1 *)
    P2_Run_Timer : REAL := 0.0;                    (* Current cycle run timer for Pump 2 *)
    P1_Rest_Timer : REAL := 30.0;                  (* Time elapsed since Pump 1 stopped *)
    P2_Rest_Timer : REAL := 30.0;                  (* Time elapsed since Pump 2 stopped *)
    Lead_Debounce_Timer : REAL := 0.0;             (* Accumulator for lead start debounce *)
    Boost_Debounce_Timer : REAL := 0.0;            (* Accumulator for boost start debounce *)
    Stop_Debounce_Timer : REAL := 0.0;             (* Accumulator for stop debounce *)
    P1_Prev_Run : BOOL := FALSE;                   (* Previous scan run state for edge detection *)
    P2_Prev_Run : BOOL := FALSE;                   (* Previous scan run state for edge detection *)
    Lead_Req_Debounced : BOOL := FALSE;            (* Anti-hunting debounced lead start demand *)
    Boost_Req_Debounced : BOOL := FALSE;           (* Anti-hunting debounced boost start demand *)
    Stop_Req_Debounced : BOOL := FALSE;            (* Anti-hunting debounced stop demand *)
    P1_Available : BOOL := TRUE;                   (* Pump 1 ready and healthy *)
    P2_Available : BOOL := TRUE;                   (* Pump 2 ready and healthy *)
END_VAR

(* 1. Fault Handling and Maintenance Lockout *)
IF Fault_Reset THEN
    Pump1_Fault_Latched := FALSE;
    Pump2_Fault_Latched := FALSE;
    Failover_Active := FALSE;
END_IF;

IF Pump1_Trip_Fault THEN
    Pump1_Fault_Latched := TRUE;
END_IF;

IF Pump2_Trip_Fault THEN
    Pump2_Fault_Latched := TRUE;
END_IF;

P1_Available := (NOT Pump1_Fault_Latched) AND (NOT Pump1_Lockout);
P2_Available := (NOT Pump2_Fault_Latched) AND (NOT Pump2_Lockout);
System_Fault_Alarm := (NOT P1_Available) AND (NOT P2_Available);

(* 2. Anti-Hunting Pressure Signal Debouncing *)
IF System_Pressure_PSI <= Lead_Start_SP THEN
    Lead_Debounce_Timer := Lead_Debounce_Timer + Cycle_Time_Sec;
    IF Lead_Debounce_Timer >= Debounce_Time_Sec THEN
        Lead_Req_Debounced := TRUE;
    END_IF;
ELSE
    Lead_Debounce_Timer := 0.0;
END_IF;

IF System_Pressure_PSI <= Boost_Start_SP THEN
    Boost_Debounce_Timer := Boost_Debounce_Timer + Cycle_Time_Sec;
    IF Boost_Debounce_Timer >= Debounce_Time_Sec THEN
        Boost_Req_Debounced := TRUE;
    END_IF;
ELSE
    Boost_Debounce_Timer := 0.0;
    Boost_Req_Debounced := FALSE;
END_IF;

IF System_Pressure_PSI >= Stop_SP THEN
    Stop_Debounce_Timer := Stop_Debounce_Timer + Cycle_Time_Sec;
    IF Stop_Debounce_Timer >= Debounce_Time_Sec THEN
        Stop_Req_Debounced := TRUE;
        Lead_Req_Debounced := FALSE;
        Boost_Req_Debounced := FALSE;
    END_IF;
ELSE
    Stop_Debounce_Timer := 0.0;
    Stop_Req_Debounced := FALSE;
END_IF;

(* 3. Lead/Lag Alternation and Sub-Second Failover *)
IF (NOT Pump1_Run_Cmd) AND (NOT Pump2_Run_Cmd) THEN
    IF P1_Available AND P2_Available THEN
        IF Pump1_Runtime_Hours <= Pump2_Runtime_Hours THEN
            Lead_Pump_Id := 1;
            Lag_Pump_Id := 2;
        ELSE
            Lead_Pump_Id := 2;
            Lag_Pump_Id := 1;
        END_IF;
    ELSIF P1_Available THEN
        Lead_Pump_Id := 1;
        Lag_Pump_Id := 2;
    ELSIF P2_Available THEN
        Lead_Pump_Id := 2;
        Lag_Pump_Id := 1;
    END_IF;
ELSIF Lead_Pump_Id = 1 AND (NOT P1_Available) AND P2_Available THEN
    Lead_Pump_Id := 2;
    Lag_Pump_Id := 1;
    Failover_Active := TRUE;
ELSIF Lead_Pump_Id = 2 AND (NOT P2_Available) AND P1_Available THEN
    Lead_Pump_Id := 1;
    Lag_Pump_Id := 2;
    Failover_Active := TRUE;
END_IF;

(* 4. Automatic / Manual Control Execution with Minimum Run/Rest Timers *)
IF Manual_Mode_Select THEN
    Pump1_Run_Cmd := Pump1_Manual_Override AND P1_Available;
    Pump2_Run_Cmd := Pump2_Manual_Override AND P2_Available;
    Boost_Mode_Active := Pump1_Run_Cmd AND Pump2_Run_Cmd;
ELSIF Auto_Enable AND (NOT System_Fault_Alarm) THEN
    IF Lead_Req_Debounced THEN
        IF Lead_Pump_Id = 1 THEN
            IF P1_Available AND (P1_Rest_Timer >= Min_Rest_Time_Sec OR Pump1_Run_Cmd) THEN
                Pump1_Run_Cmd := TRUE;
            ELSE
                Pump1_Run_Cmd := FALSE;
            END_IF;

            IF Boost_Req_Debounced OR Failover_Active OR (NOT P1_Available) THEN
                IF P2_Available AND (P2_Rest_Timer >= Min_Rest_Time_Sec OR Pump2_Run_Cmd) THEN
                    Pump2_Run_Cmd := TRUE;
                ELSE
                    Pump2_Run_Cmd := FALSE;
                END_IF;
            ELSE
                IF P2_Run_Timer >= Min_Run_Time_Sec THEN
                    Pump2_Run_Cmd := FALSE;
                END_IF;
            END_IF;
        ELSE
            IF P2_Available AND (P2_Rest_Timer >= Min_Rest_Time_Sec OR Pump2_Run_Cmd) THEN
                Pump2_Run_Cmd := TRUE;
            ELSE
                Pump2_Run_Cmd := FALSE;
            END_IF;

            IF Boost_Req_Debounced OR Failover_Active OR (NOT P2_Available) THEN
                IF P1_Available AND (P1_Rest_Timer >= Min_Rest_Time_Sec OR Pump1_Run_Cmd) THEN
                    Pump1_Run_Cmd := TRUE;
                ELSE
                    Pump1_Run_Cmd := FALSE;
                END_IF;
            ELSE
                IF P1_Run_Timer >= Min_Run_Time_Sec THEN
                    Pump1_Run_Cmd := FALSE;
                END_IF;
            END_IF;
        END_IF;
    ELSIF Stop_Req_Debounced THEN
        IF P1_Run_Timer >= Min_Run_Time_Sec THEN
            Pump1_Run_Cmd := FALSE;
        END_IF;
        IF P2_Run_Timer >= Min_Run_Time_Sec THEN
            Pump2_Run_Cmd := FALSE;
        END_IF;
    END_IF;

    Boost_Mode_Active := Pump1_Run_Cmd AND Pump2_Run_Cmd;
ELSE
    Pump1_Run_Cmd := FALSE;
    Pump2_Run_Cmd := FALSE;
    Boost_Mode_Active := FALSE;
END_IF;

(* Safety interlock override: unavailable pumps cannot run *)
IF NOT P1_Available THEN
    Pump1_Run_Cmd := FALSE;
END_IF;
IF NOT P2_Available THEN
    Pump2_Run_Cmd := FALSE;
END_IF;
Boost_Mode_Active := Pump1_Run_Cmd AND Pump2_Run_Cmd;

(* 5. Runtime, Rest-Time, and Cycle Accumulation *)
IF Pump1_Run_Cmd THEN
    P1_Run_Timer := P1_Run_Timer + Cycle_Time_Sec;
    P1_Rest_Timer := 0.0;
    Pump1_Runtime_Hours := Pump1_Runtime_Hours + (Cycle_Time_Sec / 3600.0);
    IF NOT P1_Prev_Run THEN
        Pump1_Starts_Count := Pump1_Starts_Count + 1;
    END_IF;
ELSE
    P1_Run_Timer := 0.0;
    P1_Rest_Timer := P1_Rest_Timer + Cycle_Time_Sec;
END_IF;
P1_Prev_Run := Pump1_Run_Cmd;

IF Pump2_Run_Cmd THEN
    P2_Run_Timer := P2_Run_Timer + Cycle_Time_Sec;
    P2_Rest_Timer := 0.0;
    Pump2_Runtime_Hours := Pump2_Runtime_Hours + (Cycle_Time_Sec / 3600.0);
    IF NOT P2_Prev_Run THEN
        Pump2_Starts_Count := Pump2_Starts_Count + 1;
    END_IF;
ELSE
    P2_Run_Timer := 0.0;
    P2_Rest_Timer := P2_Rest_Timer + Cycle_Time_Sec;
END_IF;
P2_Prev_Run := Pump2_Run_Cmd;

END_FUNCTION_BLOCK
