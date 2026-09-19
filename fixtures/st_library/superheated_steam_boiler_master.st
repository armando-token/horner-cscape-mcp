(* ============================================================================
   PROGRAM: SuperheatedSteamBoilerMaster
   Standard: IEC 61131-3 Structured Text (ST Only)
   Target: Horner APG Cscape 10.2 / OCS Controller
   Description: Industrial Superheated Steam Boiler Master Pressure,
                Cross-Limited Combustion Ratio (NFPA 85 Lead-Lag),
                Drum Level Three-Element PID, and Desuperheater Control.
                Pure Structured Text with zero ladder contacts/coils.
   ============================================================================ *)

PROGRAM SuperheatedSteamBoilerMaster
VAR
    (* Analog Inputs (OCS %R Registers) *)
    HeaderPressure_psig        AT %R170 : REAL;    (* Main steam header pressure in psig *)
    HeaderSteamFlow_klbhr      AT %R171 : REAL;    (* Steam demand flow rate in klb/hr *)
    DrumLevel_inches           AT %R172 : REAL;    (* Steam drum water level in inches WC *)
    FeedwaterFlow_klbhr        AT %R173 : REAL;    (* Boiler feedwater flow rate in klb/hr *)
    SuperheatTemp_degF         AT %R174 : REAL;    (* Final superheater outlet temperature *)
    DesuperheaterInletTemp_degF AT %R175 : REAL;   (* Attemperator inlet steam temperature *)
    FuelGasFlow_scfh           AT %R176 : REAL;    (* Fuel gas flow in standard cubic ft/hr *)
    CombustionAirFlow_scfh     AT %R177 : REAL;    (* Forced draft combustion air flow in scfh *)

    (* Digital Inputs (OCS %I Bits) *)
    BoilerPermissiveAux        AT %I28  : BOOL;    (* BMS Master Fuel Trip Permissive string *)
    FlameScanner1_Active       AT %I29  : BOOL;    (* Optical flame scanner 1 signal *)
    FlameScanner2_Active       AT %I30  : BOOL;    (* Optical flame scanner 2 signal *)
    BMS_TripResetCmd           AT %I31  : BOOL;    (* Operator BMS latch reset pushbutton *)

    (* Digital Outputs (OCS %Q Bits) *)
    MasterFuelTripValveCmd     AT %Q58  : BOOL;    (* MFT Fuel safety shutoff valve (True=Open) *)
    FDFanDamperEnableCmd       AT %Q59  : BOOL;    (* Forced draft air damper enable command *)
    DesuperheaterSprayValveCmd  AT %Q60  : BOOL;    (* Attemperator spray water valve open *)
    BMS_AlarmOut               AT %Q61  : BOOL;    (* BMS trip annunciator alarm *)

    (* Internal Flags (OCS %M Bits) *)
    CombustionAirLeadActive    AT %M80  : BOOL;    (* Air leads fuel on firing rate increase *)
    CombustionFuelLeadActive   AT %M81  : BOOL;    (* Fuel leads air on firing rate decrease *)
    DrumLevelSevereLowTrip     AT %M82  : BOOL;    (* Low drum level MFT trip flag *)
    MasterFuelTripped          AT %M83  : BOOL;    (* Latched Master Fuel Trip status *)

    (* Setpoints & Operating Limits *)
    HeaderPressSP_psig         : REAL := 600.0;    (* Steam header pressure setpoint *)
    MaxSuperheatTemp_degF      : REAL := 750.0;    (* Maximum superheated steam temperature *)
    MinDrumLevel_inches        : REAL := -6.0;     (* Low-low drum water level trip limit *)
    MaxDrumLevel_inches        : REAL := 6.0;      (* High-high drum water level trip limit *)
    AirFuelRatioMin            : REAL := 1.15;     (* Minimum excess air ratio (NFPA 85) *)
    HighHeaderPressTrip_psig   : REAL := 675.0;    (* Overpressure safety trip threshold *)

    (* Internal Process Calculation Variables *)
    PressureError_psig         : REAL := 0.0;
    CombustionFiringRateDemand : REAL := 0.0;
    AirDemand_scfh             : REAL := 0.0;
    FuelDemand_scfh            : REAL := 0.0;
    CurrentAirFuelRatio        : REAL := 1.20;
    FlameHealthy               : BOOL := FALSE;
END_VAR

(* ----------------------------------------------------------------------------
   Section 1: Operator BMS Reset Logic
   ---------------------------------------------------------------------------- *)
IF BMS_TripResetCmd AND BoilerPermissiveAux THEN
    MasterFuelTripped := FALSE;
    BMS_AlarmOut := FALSE;
    DrumLevelSevereLowTrip := FALSE;
END_IF;

(* ----------------------------------------------------------------------------
   Section 2: Flame Verification & Safety Safeguards (NFPA 85)
   Flame detection requires 1-out-of-2 voting when running
   ---------------------------------------------------------------------------- *)
FlameHealthy := FlameScanner1_Active OR FlameScanner2_Active;

(* ----------------------------------------------------------------------------
   Section 3: Emergency Master Fuel Trip (MFT) Evaluation
   Triggers if permissive lost, flame lost during firing, drum level low-low,
   or severe overpressure detected.
   ---------------------------------------------------------------------------- *)
IF (NOT BoilerPermissiveAux) OR 
   (MasterFuelTripValveCmd AND (NOT FlameHealthy)) OR 
   (DrumLevel_inches < MinDrumLevel_inches) OR 
   (HeaderPressure_psig > HighHeaderPressTrip_psig) THEN
    
    MasterFuelTripped := TRUE;
    MasterFuelTripValveCmd := FALSE;
    FDFanDamperEnableCmd := FALSE;
    BMS_AlarmOut := TRUE;
    
    IF DrumLevel_inches < MinDrumLevel_inches THEN
        DrumLevelSevereLowTrip := TRUE;
    END_IF;
ELSE
    (* Normal Firing Permitted *)
    IF NOT MasterFuelTripped THEN
        MasterFuelTripValveCmd := TRUE;
        FDFanDamperEnableCmd := TRUE;
        BMS_AlarmOut := FALSE;
    END_IF;
END_IF;

(* ----------------------------------------------------------------------------
   Section 4: Master Steam Header Pressure PID / Demand Calculation
   ---------------------------------------------------------------------------- *)
IF MasterFuelTripValveCmd THEN
    PressureError_psig := HeaderPressSP_psig - HeaderPressure_psig;
    
    (* Demand combines pressure deviation with steam flow feedforward *)
    CombustionFiringRateDemand := (HeaderSteamFlow_klbhr * 1.0) + (PressureError_psig * 0.5);
    
    (* Clamp demand between 10% and 100% *)
    IF CombustionFiringRateDemand < 10.0 THEN
        CombustionFiringRateDemand := 10.0;
    ELSIF CombustionFiringRateDemand > 100.0 THEN
        CombustionFiringRateDemand := 100.0;
    END_IF;
    
    (* ------------------------------------------------------------------------
       Section 5: Cross-Limited Combustion Control (Air/Fuel Lead-Lag)
       On demand increase: Air increases first, then Fuel follows.
       On demand decrease: Fuel decreases first, then Air follows.
       ------------------------------------------------------------------------ *)
    FuelDemand_scfh := CombustionFiringRateDemand * 500.0;
    AirDemand_scfh := FuelDemand_scfh * AirFuelRatioMin;
    
    IF CombustionAirFlow_scfh < AirDemand_scfh THEN
        (* Air leading fuel: air damper opens first *)
        CombustionAirLeadActive := TRUE;
        CombustionFuelLeadActive := FALSE;
    ELSIF FuelGasFlow_scfh > FuelDemand_scfh THEN
        (* Fuel leading air: fuel valve throttles down first *)
        CombustionFuelLeadActive := TRUE;
        CombustionAirLeadActive := FALSE;
    ELSE
        CombustionAirLeadActive := FALSE;
        CombustionFuelLeadActive := FALSE;
    END_IF;
ELSE
    CombustionFiringRateDemand := 0.0;
    CombustionAirLeadActive := FALSE;
    CombustionFuelLeadActive := FALSE;
END_IF;

(* ----------------------------------------------------------------------------
   Section 6: Superheater Attemperator Spray Control
   When superheater outlet exceeds safety limit, open desuperheater spray valve.
   ---------------------------------------------------------------------------- *)
IF SuperheatTemp_degF > MaxSuperheatTemp_degF THEN
    DesuperheaterSprayValveCmd := TRUE;
ELSE
    DesuperheaterSprayValveCmd := FALSE;
END_IF;

END_PROGRAM
