(* ============================================================================
   PROGRAM: PipelineCompressorAntiSurge
   Standard: IEC 61131-3 Structured Text (ST Only)
   Target: Horner APG Cscape 10.2 / OCS Controller
   Description: Natural Gas Pipeline Centrifugal Compressor Anti-Surge
                Recycle & Decoupled Capacity Control.
                Pure Structured Text with zero ladder contacts/coils.
   ============================================================================ *)

PROGRAM PipelineCompressorAntiSurge
VAR
    (* Analog Inputs (OCS %R Registers) *)
    SuctionPressure_psig  AT %R160 : REAL;    (* Suction Pressure in psig *)
    DischargePressure_psig AT %R161 : REAL;   (* Discharge Pressure in psig *)
    DifferentialPress_inH2O AT %R162 : REAL;  (* Flow Orifice Differential Press *)
    SuctionTemp_degF      AT %R163 : REAL;    (* Suction Gas Temperature *)
    CompressorSpeed_RPM   AT %R164 : REAL;    (* Shaft Speed in RPM *)
    PressureRatio         AT %R165 : REAL;    (* Calculated Rc = Pd / Ps *)
    SurgeMargin_pct       AT %R166 : REAL;    (* Safety margin to Surge Line (%) *)

    (* Digital Inputs (OCS %I Bits) *)
    CompressorRunAux      AT %I24  : BOOL;    (* Compressor Running Aux Contact *)
    ESDInhibitCmd         AT %I25  : BOOL;    (* Emergency Shutdown Inhibit *)
    FastBlowoffTestCmd    AT %I26  : BOOL;    (* Operator Blowoff Test Command *)
    SurgeDetectorResetCmd AT %I27  : BOOL;    (* Reset Latched Surge Alarms *)

    (* Digital Outputs (OCS %Q Bits) *)
    RecycleValveOpenCmd   AT %Q54  : BOOL;    (* Anti-Surge Recycle Valve Open Command *)
    FastBlowoffValveCmd   AT %Q55  : BOOL;    (* Fast Emergency Blowoff Valve Command *)
    SurgeEventAlarmOut    AT %Q56  : BOOL;    (* Compressor In-Surge Active Alarm *)
    TripInterlockOut      AT %Q57  : BOOL;    (* Machine Protection Trip Interlock *)

    (* Internal Flags (OCS %M Bits) *)
    SurgeMarginLowWarn    AT %M75  : BOOL;    (* Margin < 10% Warning *)
    SurgeCycleLatched     AT %M76  : BOOL;    (* Surge cycle detected and latched *)
    RecycleModulating     AT %M77  : BOOL;    (* Recycle loop active *)
    CapacityClamped       AT %M78  : BOOL;    (* Discharge pressure limit clamped *)

    (* Safety & Control Setpoints *)
    MinSurgeMargin_pct    : REAL := 10.0;     (* Minimum operating surge margin % *)
    CriticalMargin_pct    : REAL := 3.0;      (* Critical surge onset threshold % *)
    MaxDischargePress_psig: REAL := 1200.0;   (* High discharge pressure limit *)
    MinSuctionPress_psig  : REAL := 200.0;    (* Low suction pressure limit *)
    SurgeLineSlope        : REAL := 2.50;     (* Empirical Surge Line Slope dP/Rc *)
    SurgeLineIntercept    : REAL := 20.0;     (* Surge line flow intercept *)

    (* Internal Computation Variables *)
    SurgeLineDeltaP       : REAL;
    SafeMarginDeltaP      : REAL;
    SurgeCount            : INT := 0;
    MaxPermissibleSurges  : INT := 2;
END_VAR

(* Reset Latched Surge Alarm Logic *)
IF SurgeDetectorResetCmd THEN
    SurgeEventAlarmOut := FALSE;
    SurgeCycleLatched := FALSE;
    SurgeCount := 0;
    TripInterlockOut := FALSE;
END_IF;

(* Compute Pressure Ratio Rc safely *)
IF SuctionPressure_psig > 10.0 THEN
    PressureRatio := (DischargePressure_psig + 14.7) / (SuctionPressure_psig + 14.7);
ELSE
    PressureRatio := 1.0;
END_IF;

(* Calculate Surge Line Dynamic DeltaP *)
SurgeLineDeltaP := (PressureRatio * SurgeLineSlope) + SurgeLineIntercept;

(* Calculate Surge Margin (%) *)
IF SurgeLineDeltaP > 1.0 THEN
    SurgeMargin_pct := ((DifferentialPress_inH2O - SurgeLineDeltaP) / SurgeLineDeltaP) * 100.0;
ELSE
    SurgeMargin_pct := 50.0;
END_IF;

(* Evaluate Warning and Control Regimes *)
IF CompressorRunAux THEN
    (* Low Margin Warning: margin drops below setpoint *)
    IF SurgeMargin_pct < MinSurgeMargin_pct THEN
        SurgeMarginLowWarn := TRUE;
        RecycleModulating := TRUE;
        RecycleValveOpenCmd := TRUE;
    ELSE
        SurgeMarginLowWarn := FALSE;
        RecycleModulating := FALSE;
        RecycleValveOpenCmd := FALSE;
    END_IF;

    (* Critical Surge Onset & Fast Blowoff Protection *)
    IF (SurgeMargin_pct < CriticalMargin_pct) OR FastBlowoffTestCmd THEN
        SurgeEventAlarmOut := TRUE;
        SurgeCycleLatched := TRUE;
        FastBlowoffValveCmd := TRUE;
        RecycleValveOpenCmd := TRUE;
        SurgeCount := SurgeCount + 1;
    ELSE
        FastBlowoffValveCmd := FALSE;
    END_IF;

    (* High Discharge Pressure Capacity Clamping *)
    IF DischargePressure_psig >= MaxDischargePress_psig THEN
        CapacityClamped := TRUE;
        RecycleValveOpenCmd := TRUE;
    ELSE
        CapacityClamped := FALSE;
    END_IF;

    (* Protective Trip Interlock: Multiple Surges or Extreme Pressure *)
    IF (SurgeCount >= MaxPermissibleSurges) OR (SuctionPressure_psig < MinSuctionPress_psig) THEN
        TripInterlockOut := TRUE;
        RecycleValveOpenCmd := TRUE;
        FastBlowoffValveCmd := TRUE;
    END_IF;
ELSE
    (* Machine stopped: valves safe open, alarms clear *)
    RecycleValveOpenCmd := TRUE;
    FastBlowoffValveCmd := FALSE;
    SurgeMarginLowWarn := FALSE;
    RecycleModulating := FALSE;
    CapacityClamped := FALSE;
END_IF;

END_PROGRAM
