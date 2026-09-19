(* ============================================================================
   PROGRAM: HydroelectricGovernorHeadLevelControl
   Standard: IEC 61131-3 Structured Text (ST Only)
   Target: Horner APG Cscape 10.2 / OCS Controller
   Description: Hydroelectric Francis/Kaplan Turbine Speed Governing,
                Penstock Water Hammer Pressure Relief, and Forebay Head Level
                Control. Pure Structured Text with zero ladder contacts/coils.
   ============================================================================ *)

PROGRAM HydroelectricGovernorHeadLevelControl
VAR
    (* Analog Inputs (OCS %R Registers) *)
    TurbineSpeed_RPM           AT %R180 : REAL;    (* Turbine shaft speed in RPM *)
    GridFrequency_Hz           AT %R181 : REAL;    (* Electrical grid frequency in Hz *)
    PenstockPressure_psig      AT %R182 : REAL;    (* Penstock static/dynamic hydraulic pressure *)
    ForebayWaterLevel_ft       AT %R183 : REAL;    (* Upstream reservoir forebay water level *)
    TailraceWaterLevel_ft      AT %R184 : REAL;    (* Downstream tailrace discharge water level *)
    WicketGatePosition_pct     AT %R185 : REAL;    (* Wicket gate opening position (0.0 to 100.0%) *)
    GeneratorActivePower_MW    AT %R186 : REAL;    (* Electrical active power output in MW *)
    RunnerBladeTilt_deg        AT %R187 : REAL;    (* Kaplan runner blade tilt angle in degrees *)

    (* Digital Inputs (OCS %I Bits) *)
    GeneratorBreakerClosed     AT %I32  : BOOL;    (* Main generator circuit breaker aux contact *)
    ShearPinIntactAux          AT %I33  : BOOL;    (* Wicket gate linkage shear pin healthy contact *)
    GovernorAutoModeSelect     AT %I34  : BOOL;    (* Operator governor auto mode selection *)
    EmergencyTripResetCmd      AT %I35  : BOOL;    (* Operator latched emergency trip reset push-button *)

    (* Digital Outputs (OCS %Q Bits) *)
    GovernorOnlineIndicator    AT %Q62  : BOOL;    (* Governor operating online indicator *)
    PenstockSurgeReliefValveCmd AT %Q63 : BOOL;    (* Hydraulic pressure relief bypass valve open *)
    JetDeflectorEmergencyDropCmd AT %Q64 : BOOL;   (* Fast jet deflector / wicket drop trip actuator *)
    GovernorCommonAlarmOut     AT %Q65  : BOOL;    (* Governor protective annunciator common alarm *)

    (* Internal Flags (OCS %M Bits) *)
    FrequencyDroopActive       AT %M85  : BOOL;    (* Droop governor response active on frequency deviation *)
    WaterHammerReliefActive    AT %M86  : BOOL;    (* Penstock surge pressure transient relief active *)
    MechanicalOverspeedDetected AT %M87 : BOOL;    (* Overspeed > 115% rated detected *)
    TurbineEmergencyLatched    AT %M88  : BOOL;    (* Latched turbine safety trip state *)

    (* Setpoints & Design Thresholds *)
    RatedSpeed_RPM             : REAL := 1800.0;   (* Nominal rated speed in RPM *)
    RatedFrequency_Hz          : REAL := 60.00;    (* Nominal grid frequency in Hz *)
    SpeedDeadband_Hz           : REAL := 0.03;     (* Governor frequency deadband *)
    SpeedDroopPercent          : REAL := 4.0;      (* Speed regulation droop slope (4%) *)
    OverspeedTripThreshold_RPM : REAL := 2070.0;   (* 115% rated speed emergency overspeed trip *)
    MaxPenstockPressure_psig   : REAL := 420.0;    (* Maximum allowable penstock transient surge *)
    MaxGateSlewRate_pct_per_sec: REAL := 5.0;      (* Anti-water-hammer maximum gate slew rate *)

    (* Internal Process Calculation Variables *)
    FrequencyDeviation_Hz      : REAL := 0.0;
    SpeedDeviation_pct         : REAL := 0.0;
    TargetGatePosition_pct     : REAL := 65.0;
    NetHydraulicHead_ft        : REAL := 150.0;
END_VAR

(* ----------------------------------------------------------------------------
   Section 1: Operator Safety Reset Interlock
   ---------------------------------------------------------------------------- *)
IF EmergencyTripResetCmd AND ShearPinIntactAux THEN
    TurbineEmergencyLatched := FALSE;
    MechanicalOverspeedDetected := FALSE;
    GovernorCommonAlarmOut := FALSE;
    JetDeflectorEmergencyDropCmd := FALSE;
END_IF;

(* ----------------------------------------------------------------------------
   Section 2: Mechanical Overspeed & Shear Pin Breakage Protection
   Emergency shutdown initiated if speed > 115% or wicket gate linkage breaks.
   ---------------------------------------------------------------------------- *)
IF (TurbineSpeed_RPM > OverspeedTripThreshold_RPM) OR (NOT ShearPinIntactAux) THEN
    MechanicalOverspeedDetected := (TurbineSpeed_RPM > OverspeedTripThreshold_RPM);
    TurbineEmergencyLatched := TRUE;
    JetDeflectorEmergencyDropCmd := TRUE;
    GovernorCommonAlarmOut := TRUE;
    GovernorOnlineIndicator := FALSE;
    TargetGatePosition_pct := 0.0;
END_IF;

(* ----------------------------------------------------------------------------
   Section 3: Hydraulic Penstock Water Hammer Relief Monitoring
   When rapid gate movement causes hydraulic surge > 420 psig, bypass valve opens.
   ---------------------------------------------------------------------------- *)
IF PenstockPressure_psig > MaxPenstockPressure_psig THEN
    PenstockSurgeReliefValveCmd := TRUE;
    WaterHammerReliefActive := TRUE;
ELSE
    PenstockSurgeReliefValveCmd := FALSE;
    WaterHammerReliefActive := FALSE;
END_IF;

(* ----------------------------------------------------------------------------
   Section 4: Speed Governing & Frequency Droop Control
   ---------------------------------------------------------------------------- *)
IF GovernorAutoModeSelect AND (NOT TurbineEmergencyLatched) THEN
    GovernorOnlineIndicator := TRUE;
    
    (* Calculate Net Head across dam *)
    NetHydraulicHead_ft := ForebayWaterLevel_ft - TailraceWaterLevel_ft;
    
    (* Grid Frequency Deviation Calculation *)
    FrequencyDeviation_Hz := RatedFrequency_Hz - GridFrequency_Hz;
    
    IF ABS(FrequencyDeviation_Hz) > SpeedDeadband_Hz THEN
        FrequencyDroopActive := TRUE;
        SpeedDeviation_pct := (FrequencyDeviation_Hz / RatedFrequency_Hz) * 100.0;
        
        (* Target Gate opening modulated by Droop Slope *)
        TargetGatePosition_pct := 65.0 + (SpeedDeviation_pct / (SpeedDroopPercent / 100.0));
        
        (* Clamp gate position between 10% minimum flow and 100% full gate *)
        IF TargetGatePosition_pct < 10.0 THEN
            TargetGatePosition_pct := 10.0;
        ELSIF TargetGatePosition_pct > 100.0 THEN
            TargetGatePosition_pct := 100.0;
        END_IF;
    ELSE
        FrequencyDroopActive := FALSE;
        TargetGatePosition_pct := 65.0;
    END_IF;
ELSE
    GovernorOnlineIndicator := FALSE;
    FrequencyDroopActive := FALSE;
END_IF;

END_PROGRAM
