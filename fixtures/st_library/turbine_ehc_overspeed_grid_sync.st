(* ============================================================================
 * Title:       FB_TurbineEhcOverspeedGridSync
 * Description: Turbine Electro-Hydraulic Governor (EHC) Speed/Load Control,
 *              110% Mechanical/Electrical Overspeed Trip, Anti-Motoring Protection
 *              & Automatic Grid Synchronizer Interlock.
 * IEC 61131-3: Pure Structured Text (ST) Only. Ladder logic strictly rejected.
 * OCS Mapping:
 *   %R131: Turbine_Speed_RPM (INT: 0..4500 RPM, rated 3600 RPM)
 *   %R132: Generator_Active_Power_MW (INT: tenths of MW, e.g. 500 = 50.0 MW)
 *   %R133: Main_Stop_Valves_CV (INT: 0..100% position)
 *   %R134: Governor_Control_Valves_CV (INT: 0..100% position)
 *   %R135: Grid_Frequency_Hz (INT: hundredths of Hz, e.g. 6000 = 60.00 Hz)
 *   %R136: Phase_Angle_Error_Deg (INT: tenths of degree, e.g. 15 = 1.5 deg)
 *   %Q40:  ETS_Trip_Solenoid_Deenergize (BOOL: Emergency Trip System fail-safe)
 *   %Q41:  Generator_Breaker_Close_Permit (BOOL: Synch-check permit)
 *   %Q42:  EHC_Hydraulic_Pump_Run (BOOL: EHC fluid pump)
 *   %Q43:  Turbine_Turning_Gear_Engaged (BOOL: Rotor anti-sag turning gear)
 *   %M55:  Turbine_Overspeed_Trip_Latched (BOOL: Latched 110% overspeed trip)
 *   %M56:  Generator_Reverse_Power_Trip (BOOL: Latched reverse power trip)
 *   %M57:  Grid_Sync_Ready (BOOL: Speed, freq, phase angle in sync window)
 * ============================================================================ *)

FUNCTION_BLOCK FB_TurbineEhcOverspeedGridSync
VAR_INPUT
    Turbine_Speed_RPM : INT := 3600;            (* RPM (rated 3600) *)
    Generator_Active_Power_MW : INT := 500;     (* Tenths MW (500 = 50.0 MW) *)
    Grid_Frequency_Hz : INT := 6000;            (* Hundredths Hz (6000 = 60.00 Hz) *)
    Phase_Angle_Error_Deg : INT := 15;          (* Tenths deg (15 = 1.5 deg) *)
    EHC_Fluid_Pressure_OK : BOOL := TRUE;       (* Header pressure >= 1600 PSI *)
    Generator_Breaker_Closed : BOOL := TRUE;    (* Breaker auxiliary contact *)
    Master_Trip_Reset : BOOL := FALSE;          (* Operator trip reset PB *)
    Turning_Gear_Auto_Enable : BOOL := TRUE;    (* Auto turning gear permit *)
END_VAR

VAR_OUTPUT
    Main_Stop_Valves_CV : INT := 100;           (* 0..100% MSV position *)
    Governor_Control_Valves_CV : INT := 85;     (* 0..100% CV position *)
    ETS_Trip_Solenoid_Deenergize : BOOL := FALSE; (* Fail-safe trip *)
    Generator_Breaker_Close_Permit : BOOL := FALSE;
    EHC_Hydraulic_Pump_Run : BOOL := TRUE;
    Turbine_Turning_Gear_Engaged : BOOL := FALSE;
    Turbine_Overspeed_Trip_Latched : BOOL := FALSE;
    Generator_Reverse_Power_Trip : BOOL := FALSE;
    Grid_Sync_Ready : BOOL := FALSE;
END_VAR

VAR
    Overspeed_Setpoint_RPM : INT := 3960;       (* 110% of 3600 RPM *)
    Sync_Min_RPM : INT := 3595;
    Sync_Max_RPM : INT := 3605;
    Sync_Max_Phase_Deg : INT := 50;             (* 5.0 degrees *)
END_VAR

(* 0. Reset Latches *)
IF Master_Trip_Reset THEN
    Turbine_Overspeed_Trip_Latched := FALSE;
    Generator_Reverse_Power_Trip := FALSE;
    ETS_Trip_Solenoid_Deenergize := FALSE;
END_IF;

(* 1. Hydraulic Fluid Header Supervision *)
IF EHC_Fluid_Pressure_OK THEN
    EHC_Hydraulic_Pump_Run := TRUE;
ELSE
    EHC_Hydraulic_Pump_Run := FALSE;
    ETS_Trip_Solenoid_Deenergize := TRUE;
END_IF;

(* 2. Emergency Overspeed Protection (110% = 3960 RPM) *)
IF Turbine_Speed_RPM >= Overspeed_Setpoint_RPM THEN
    Turbine_Overspeed_Trip_Latched := TRUE;
    ETS_Trip_Solenoid_Deenergize := TRUE;
    Main_Stop_Valves_CV := 0;
    Governor_Control_Valves_CV := 0;
    Generator_Breaker_Close_Permit := FALSE;
    Grid_Sync_Ready := FALSE;
END_IF;

(* 3. Anti-Motoring / Reverse Power Protection (< -2.0 MW) *)
IF Generator_Breaker_Closed AND (Generator_Active_Power_MW <= -20) THEN
    Generator_Reverse_Power_Trip := TRUE;
    Generator_Breaker_Close_Permit := FALSE;
END_IF;

(* 4. Active Trip Enforcement *)
IF Turbine_Overspeed_Trip_Latched OR ETS_Trip_Solenoid_Deenergize THEN
    Main_Stop_Valves_CV := 0;
    Governor_Control_Valves_CV := 0;
    Generator_Breaker_Close_Permit := FALSE;
    Grid_Sync_Ready := FALSE;
END_IF;

(* 5. Automatic Grid Synchronizer Interlock *)
IF NOT Turbine_Overspeed_Trip_Latched AND NOT ETS_Trip_Solenoid_Deenergize THEN
    IF (Turbine_Speed_RPM >= Sync_Min_RPM) AND (Turbine_Speed_RPM <= Sync_Max_RPM) AND (Grid_Frequency_Hz >= 5990) AND (Grid_Frequency_Hz <= 6010) AND (Phase_Angle_Error_Deg <= Sync_Max_Phase_Deg) AND (Phase_Angle_Error_Deg >= -Sync_Max_Phase_Deg) THEN
        Grid_Sync_Ready := TRUE;
        Generator_Breaker_Close_Permit := TRUE;
    ELSE
        Grid_Sync_Ready := FALSE;
        IF NOT Generator_Breaker_Closed THEN
            Generator_Breaker_Close_Permit := FALSE;
        END_IF;
    END_IF;
END_IF;

(* 6. Cooldown Turning Gear Auto-Engagement (< 100 RPM) *)
IF Turning_Gear_Auto_Enable AND (Turbine_Speed_RPM < 100) AND (Main_Stop_Valves_CV = 0) THEN
    Turbine_Turning_Gear_Engaged := TRUE;
ELSE
    Turbine_Turning_Gear_Engaged := FALSE;
END_IF;

END_FUNCTION_BLOCK
