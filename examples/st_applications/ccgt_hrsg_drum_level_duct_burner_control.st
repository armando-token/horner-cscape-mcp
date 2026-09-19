(* ============================================================================
   PROGRAM: CCGTHRSGDrumLevelDuctBurnerControl
   Standard: IEC 61131-3 Structured Text (ST Only)
   Target: Horner APG Cscape 10.2 / OCS Controller
   Description: Combined Cycle Gas Turbine (CCGT) Heat Recovery Steam Generator (HRSG)
                Three-Element Drum Level Control, Shrink/Swell Compensation, and
                Supplementary Firing Duct Burner Permissive Management.
                Pure Structured Text with zero ladder contacts/coils.
   ============================================================================ *)

PROGRAM CCGTHRSGDrumLevelDuctBurnerControl
VAR
    (* Analog Inputs (OCS %R Registers) *)
    DrumLevel_PV_mm            AT %R190 : REAL;    (* Drum level process variable (-500.0 to +500.0 mm) *)
    SteamFlow_Rate_kgs         AT %R191 : REAL;    (* Main high-pressure steam flow rate (0.0 to 120.0 kg/s) *)
    FeedwaterFlow_Rate_kgs     AT %R192 : REAL;    (* Boiler feedwater mass flow rate (0.0 to 120.0 kg/s) *)
    GT_ExhaustTemp_degC        AT %R193 : REAL;    (* Gas turbine exhaust gas temperature (400.0 to 650.0 C) *)
    DuctBurnerFiringDemand_pct AT %R194 : REAL;    (* Supplementary firing thermal demand (0.0 to 100.0%) *)
    FeedwaterValveOutput_pct   AT %R195 : REAL;    (* Feedwater control valve command (0.0 to 100.0%) *)
    DrumPressure_bar           AT %R196 : REAL;    (* Drum saturation operating pressure (0.0 to 120.0 bar) *)
    BlowdownFlow_Rate_kgs      AT %R197 : REAL;    (* Continuous/intermittent blowdown rate (0.0 to 10.0 kg/s) *)

    (* Digital Inputs (OCS %I Bits) *)
    GTRunPermissiveAux         AT %I36  : BOOL;    (* Gas turbine running permissive aux contact *)
    BoilerFeedPumpARunningAux  AT %I37  : BOOL;    (* Boiler feed pump A operational contact *)
    BoilerFeedPumpBRunningAux  AT %I38  : BOOL;    (* Boiler feed pump B operational contact *)
    DuctBurnerFlameDetected    AT %I39  : BOOL;    (* Duct burner scanner optical flame detected *)
    EmergencyTripResetPB       AT %I40  : BOOL;    (* Operator control room trip reset push-button *)

    (* Digital Outputs (OCS %Q Bits) *)
    FeedwaterControlAutoOnline AT %Q68  : BOOL;    (* Three-element feedwater control online *)
    DuctBurnerFuelGasBlockOpen AT %Q69  : BOOL;    (* Duct burner double block & bleed fuel valve open *)
    EmergencyBlowdownValveOpen AT %Q70  : BOOL;    (* High-level emergency blowdown dump valve open *)
    DrumProtectionCommonAlarm  AT %Q71  : BOOL;    (* HRSG drum protective annunciator common alarm *)

    (* Internal Flags (OCS %M Bits) *)
    ThreeElementModeActive     AT %M90  : BOOL;    (* True when steam and feedwater flow transmitters healthy *)
    DrumSwellShrinkActive      AT %M91  : BOOL;    (* Dynamic swell/shrink compensation bias applied *)
    HighDrumLevelWarning       AT %M92  : BOOL;    (* Level > +150.0 mm warning state *)
    LowDrumLevelWarning        AT %M93  : BOOL;    (* Level < -150.0 mm warning state *)
    LowLowDrumLevelTripLatched AT %M94  : BOOL;    (* Latched low-low level MFT trip (< -300.0 mm) *)
    HighHighDrumCarryoverTrip  AT %M95  : BOOL;    (* Latched high-high level carryover trip (> +350.0 mm) *)
    DuctBurnerPermissiveOK     AT %M96  : BOOL;    (* Supplementary firing interlocks satisfied *)
    BoilerMasterTripActive     AT %M97  : BOOL;    (* Common HRSG master trip state *)

    (* Setpoints & Design Limits *)
    DrumLevelSetpoint_mm       : REAL := 0.0;      (* Normal water level setpoint at centerline *)
    LowLowTripLimit_mm         : REAL := -300.0;   (* MFT low-low drum level trip point *)
    HighHighTripLimit_mm       : REAL := 350.0;    (* Steam turbine carryover high-high trip point *)
    MinGTExhaustTemp_degC      : REAL := 450.0;    (* Minimum GT exhaust temperature for duct firing *)
    MinFeedwaterFlow_kgs       : REAL := 5.0;      (* Minimum feedwater pump recirculation threshold *)

    (* Internal Process Calculation Registers *)
    LevelError_mm              : REAL := 0.0;
    FlowMismatch_kgs           : REAL := 0.0;
    TargetValvePos_pct         : REAL := 50.0;
END_VAR

(* ----------------------------------------------------------------------------
   Section 1: Operator Safety Reset Interlock
   ---------------------------------------------------------------------------- *)
IF EmergencyTripResetPB AND (BoilerFeedPumpARunningAux OR BoilerFeedPumpBRunningAux) THEN
    LowLowDrumLevelTripLatched := FALSE;
    HighHighDrumCarryoverTrip := FALSE;
    BoilerMasterTripActive := FALSE;
    DrumProtectionCommonAlarm := FALSE;
    EmergencyBlowdownValveOpen := FALSE;
END_IF;

(* ----------------------------------------------------------------------------
   Section 2: High-High Carryover and Low-Low Boil-Dry Protection
   ---------------------------------------------------------------------------- *)
IF DrumLevel_PV_mm < LowLowTripLimit_mm THEN
    LowLowDrumLevelTripLatched := TRUE;
    BoilerMasterTripActive := TRUE;
    DrumProtectionCommonAlarm := TRUE;
    DuctBurnerFuelGasBlockOpen := FALSE;
    FeedwaterControlAutoOnline := FALSE;
END_IF;

IF DrumLevel_PV_mm > HighHighTripLimit_mm THEN
    HighHighDrumCarryoverTrip := TRUE;
    BoilerMasterTripActive := TRUE;
    DrumProtectionCommonAlarm := TRUE;
    EmergencyBlowdownValveOpen := TRUE;
    DuctBurnerFuelGasBlockOpen := FALSE;
END_IF;

(* ----------------------------------------------------------------------------
   Section 3: Warning Threshold Monitoring
   ---------------------------------------------------------------------------- *)
HighDrumLevelWarning := (DrumLevel_PV_mm > 150.0) AND (NOT HighHighDrumCarryoverTrip);
LowDrumLevelWarning := (DrumLevel_PV_mm < -150.0) AND (NOT LowLowDrumLevelTripLatched);

(* ----------------------------------------------------------------------------
   Section 4: Supplementary Firing Duct Burner Permissive Logic
   Requires: GT running, exhaust temp > 450 C, at least 1 feed pump, no trips.
   ---------------------------------------------------------------------------- *)
DuctBurnerPermissiveOK := GTRunPermissiveAux 
                          AND (GT_ExhaustTemp_degC >= MinGTExhaustTemp_degC)
                          AND (BoilerFeedPumpARunningAux OR BoilerFeedPumpBRunningAux)
                          AND (NOT BoilerMasterTripActive)
                          AND (DrumLevel_PV_mm > -200.0)
                          AND (DrumLevel_PV_mm < 200.0);

IF DuctBurnerPermissiveOK AND (DuctBurnerFiringDemand_pct > 5.0) THEN
    DuctBurnerFuelGasBlockOpen := TRUE;
ELSE
    DuctBurnerFuelGasBlockOpen := FALSE;
END_IF;

(* ----------------------------------------------------------------------------
   Section 5: Three-Element Drum Level & Dynamic Swell/Shrink Feedforward
   ---------------------------------------------------------------------------- *)
IF (NOT BoilerMasterTripActive) AND (BoilerFeedPumpARunningAux OR BoilerFeedPumpBRunningAux) THEN
    FeedwaterControlAutoOnline := TRUE;
    ThreeElementModeActive := TRUE;

    LevelError_mm := DrumLevelSetpoint_mm - DrumLevel_PV_mm;
    FlowMismatch_kgs := SteamFlow_Rate_kgs - FeedwaterFlow_Rate_kgs;

    (* Detect swell/shrink condition during rapid load changes *)
    IF (DuctBurnerFiringDemand_pct > 60.0) AND (SteamFlow_Rate_kgs > 75.0) THEN
        DrumSwellShrinkActive := TRUE;
    ELSE
        DrumSwellShrinkActive := FALSE;
    END_IF;

    (* Feedforward 3-element valve output calculation:
       Base position scales with steam flow, trimmed by level error and flow balance *)
    TargetValvePos_pct := (SteamFlow_Rate_kgs / 120.0) * 85.0 + (LevelError_mm * 0.05) + (FlowMismatch_kgs * 0.25);

    IF TargetValvePos_pct < 5.0 THEN
        FeedwaterValveOutput_pct := 5.0;
    ELSIF TargetValvePos_pct > 100.0 THEN
        FeedwaterValveOutput_pct := 100.0;
    ELSE
        FeedwaterValveOutput_pct := TargetValvePos_pct;
    END_IF;
ELSE
    FeedwaterControlAutoOnline := FALSE;
    ThreeElementModeActive := FALSE;
    FeedwaterValveOutput_pct := 0.0;
END_IF;

END_PROGRAM
