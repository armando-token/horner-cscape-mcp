(* ============================================================================
 * Title:       FB_CondenserHotwellVacuumControl
 * Description: Turbine Surface Condenser Hotwell Level, Vacuum Deaeration & 
 *              Circulating Water Cooling Tower Control.
 * IEC 61131-3: Pure Structured Text (ST) Only. Ladder logic strictly rejected.
 * OCS Mapping:
 *   %R125: Hotwell_Level_PV (tenths of inches: 0..1000, normal 500 = 50.0 in)
 *   %R126: Condenser_Vacuum_PV (hundredths of inHg abs: normal 150 = 1.50 inHg abs)
 *   %R127: Condensate_Dump_CV (0..100% dump valve to Condensate Storage Tank)
 *   %R128: Condensate_Makeup_CV (0..100% makeup valve from CST)
 *   %R129: Cooling_Tower_Basin_Temp_PV (tenths of deg F: normal 850 = 85.0 deg F)
 *   %R130: Cation_Conductivity_PV (hundredths of uS/cm: normal 20 = 0.20 uS/cm)
 *   %Q35:  Condensate_Pumps_Run (Digital output: Condensate extraction pumps)
 *   %Q36:  SJAE_Aux_Vacuum_Ejector (Digital output: Steam-jet air ejector / hogger)
 *   %Q37:  Cooling_Tower_Fan1 (Digital output: Stage 1 cooling fan)
 *   %Q38:  Cooling_Tower_Fan2 (Digital output: Stage 2 cooling fan)
 *   %Q39:  Condensate_Polisher_Bypass_Permit (Digital output: Polisher bypass)
 *   %M51:  Hotwell_Level_LowLow_Trip (Marker: Pump cavitation protection trip)
 *   %M52:  Condenser_Vacuum_HighHigh_Trip (Marker: Turbine backpressure trip)
 *   %M53:  Hotwell_Level_High_Alarm (Marker: Hotwell high level alarm)
 *   %M54:  Condenser_Tube_Leak_Alarm (Marker: Tube leak / cooling water ingress)
 * ============================================================================ *)

FUNCTION_BLOCK FB_CondenserHotwellVacuumControl
VAR_INPUT
    Hotwell_Level_PV : REAL := 500.0;            (* Tenths of inches (500.0 = 50.0 in) *)
    Condenser_Vacuum_PV : REAL := 150.0;         (* Hundredths inHg abs (150.0 = 1.50 inHg) *)
    Cooling_Tower_Basin_Temp_PV : REAL := 850.0; (* Tenths deg F (850.0 = 85.0 deg F) *)
    Cation_Conductivity_PV : REAL := 20.0;       (* Hundredths uS/cm (20.0 = 0.20 uS/cm) *)
    Permissive_Run : BOOL := TRUE;               (* Plant master permissive *)
    Reset_Alarms : BOOL := FALSE;                (* Operator alarm reset *)
END_VAR

VAR_OUTPUT
    Condensate_Dump_CV : REAL := 0.0;            (* 0.0 to 100.0 % *)
    Condensate_Makeup_CV : REAL := 0.0;          (* 0.0 to 100.0 % *)
    Condensate_Pumps_Run : BOOL := TRUE;
    SJAE_Aux_Vacuum_Ejector : BOOL := FALSE;
    Cooling_Tower_Fan1 : BOOL := FALSE;
    Cooling_Tower_Fan2 : BOOL := FALSE;
    Condensate_Polisher_Bypass_Permit : BOOL := TRUE;
    Hotwell_Level_LowLow_Trip : BOOL := FALSE;
    Condenser_Vacuum_HighHigh_Trip : BOOL := FALSE;
    Hotwell_Level_High_Alarm : BOOL := FALSE;
    Condenser_Tube_Leak_Alarm : BOOL := FALSE;
END_VAR

VAR
    Level_Error : REAL := 0.0;
END_VAR

(* Reset Latches if requested *)
IF Reset_Alarms THEN
    Hotwell_Level_LowLow_Trip := FALSE;
    Condenser_Vacuum_HighHigh_Trip := FALSE;
    Hotwell_Level_High_Alarm := FALSE;
    Condenser_Tube_Leak_Alarm := FALSE;
END_IF;

(* 1. Hotwell Level Control & Cavitation Protection *)
IF Hotwell_Level_PV <= 100.0 THEN
    (* Low-Low Level: Trip Condensate Extraction Pumps immediately *)
    Hotwell_Level_LowLow_Trip := TRUE;
    Condensate_Pumps_Run := FALSE;
    Condensate_Makeup_CV := 100.0;
    Condensate_Dump_CV := 0.0;
ELSIF Hotwell_Level_PV >= 750.0 THEN
    (* High Level: Open Dump Valve to CST, Inhibit Makeup *)
    Hotwell_Level_High_Alarm := TRUE;
    Condensate_Dump_CV := (Hotwell_Level_PV - 750.0) * 0.4;
    IF Condensate_Dump_CV > 100.0 THEN
        Condensate_Dump_CV := 100.0;
    END_IF;
    Condensate_Makeup_CV := 0.0;
    IF Permissive_Run AND NOT Hotwell_Level_LowLow_Trip THEN
        Condensate_Pumps_Run := TRUE;
    END_IF;
ELSIF Hotwell_Level_PV <= 300.0 THEN
    (* Low Level: Open Makeup Valve from CST, Close Dump *)
    Condensate_Makeup_CV := (300.0 - Hotwell_Level_PV) * 0.5;
    IF Condensate_Makeup_CV > 100.0 THEN
        Condensate_Makeup_CV := 100.0;
    END_IF;
    Condensate_Dump_CV := 0.0;
    IF Permissive_Run AND NOT Hotwell_Level_LowLow_Trip THEN
        Condensate_Pumps_Run := TRUE;
    END_IF;
ELSE
    (* Normal Hotwell Equilibrium *)
    Condensate_Dump_CV := 0.0;
    Condensate_Makeup_CV := 0.0;
    Hotwell_Level_High_Alarm := FALSE;
    IF Permissive_Run AND NOT Hotwell_Level_LowLow_Trip THEN
        Condensate_Pumps_Run := TRUE;
    END_IF;
END_IF;

(* 2. Condenser Vacuum & Air Ejection Control *)
IF Condenser_Vacuum_PV >= 500.0 THEN
    (* Vacuum Loss High-High Trip (5.0 inHg abs) *)
    Condenser_Vacuum_HighHigh_Trip := TRUE;
    SJAE_Aux_Vacuum_Ejector := TRUE;
ELSIF Condenser_Vacuum_PV >= 350.0 THEN
    (* Vacuum Deteriorating: Engage Auxiliary Air Ejector / Hogger *)
    SJAE_Aux_Vacuum_Ejector := TRUE;
ELSE
    (* Normal Vacuum (<= 3.50 inHg abs) *)
    SJAE_Aux_Vacuum_Ejector := FALSE;
END_IF;

(* 3. Circulating Water Cooling Tower Fan Staging *)
IF Cooling_Tower_Basin_Temp_PV >= 980.0 THEN
    (* High Temp: Stage 1 and Stage 2 Fans Running *)
    Cooling_Tower_Fan1 := TRUE;
    Cooling_Tower_Fan2 := TRUE;
ELSIF Cooling_Tower_Basin_Temp_PV >= 920.0 THEN
    (* Moderate Temp: Stage 1 Fan Running *)
    Cooling_Tower_Fan1 := TRUE;
    Cooling_Tower_Fan2 := FALSE;
ELSE
    (* Normal / Cool Basin Temp *)
    Cooling_Tower_Fan1 := FALSE;
    Cooling_Tower_Fan2 := FALSE;
END_IF;

(* 4. Tube Leak / Raw Cooling Water Ingress Detection *)
IF Cation_Conductivity_PV >= 200.0 THEN
    (* Water Ingress Alert: Trip Polisher Bypass, Latch Alarm *)
    Condenser_Tube_Leak_Alarm := TRUE;
    Condensate_Polisher_Bypass_Permit := FALSE;
ELSE
    Condensate_Polisher_Bypass_Permit := TRUE;
END_IF;

END_FUNCTION_BLOCK
