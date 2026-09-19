(* ============================================================================
   PROGRAM: SubstationSynchrocheckAutoReclose
   Standard: IEC 61131-3 Structured Text (ST Only)
   Target: Horner APG Cscape 10.2 / OCS Controller
   Description: ANSI 25 Synchrocheck & ANSI 79 Multi-Shot Auto-Reclosing
                Transmission Feeder Protection Logic.
                Pure Structured Text with zero ladder contacts/coils.
   ============================================================================ *)

PROGRAM SubstationSynchrocheckAutoReclose
VAR
    (* Analog Inputs (OCS %R Registers) *)
    BusVoltage_kV        AT %R150 : REAL;    (* Bus Voltage in kV *)
    LineVoltage_kV       AT %R151 : REAL;    (* Line Voltage in kV *)
    BusFreq_Hz           AT %R152 : REAL;    (* Bus Frequency in Hz *)
    LineFreq_Hz          AT %R153 : REAL;    (* Line Frequency in Hz *)
    PhaseAngleDiff_deg   AT %R154 : REAL;    (* Voltage phase angle diff (deg) *)
    RecloseShotCount     AT %R155 : INT;     (* Current Auto-Reclose Shot (0..4) *)
    RecloseTimer_sec     AT %R156 : REAL;    (* Elapsed Reclose Wait Time *)

    (* Digital Inputs (OCS %I Bits) *)
    ResetLockoutCmd      AT %I20  : BOOL;    (* Operator Reset Lockout *)
    ManualCloseCmd       AT %I21  : BOOL;    (* Manual Breaker Close Request *)
    BreakerClosedAux     AT %I22  : BOOL;    (* 52a Auxiliary Switch (Closed=TRUE) *)
    ProtectiveTripIn     AT %I23  : BOOL;    (* Feeder Protection Trip Pulse *)

    (* Digital Outputs (OCS %Q Bits) *)
    BreakerCloseOutput   AT %Q50  : BOOL;    (* Close Coil Command Pulse *)
    LockoutStateOutput   AT %Q51  : BOOL;    (* 86 Lockout Relayed State *)
    RecloseActiveOutput  AT %Q52  : BOOL;    (* Auto-Reclosing Cycle In Progress *)
    SynchrocheckOKOutput AT %Q53  : BOOL;    (* ANSI 25 Synchrocheck Permissive *)

    (* Internal Flags (OCS %M Bits) *)
    DeadBusLiveLinePerm  AT %M71  : BOOL;    (* DBLL condition satisfied *)
    LiveBusDeadLinePerm  AT %M72  : BOOL;    (* LBDL condition satisfied *)
    SyncPermissive       AT %M73  : BOOL;    (* Synchrocheck parameters in window *)
    TripLatched          AT %M74  : BOOL;    (* Trip condition latched *)

    (* Configuration Parameters *)
    MaxVoltDiff_kV       : REAL := 5.0;      (* Maximum acceptable delta V in kV *)
    MaxFreqDiff_Hz       : REAL := 0.20;     (* Maximum acceptable delta F in Hz *)
    MaxAngleDiff_deg     : REAL := 15.0;     (* Maximum acceptable phase angle diff *)
    DeadVoltageThresh_kV : REAL := 15.0;     (* Dead bus/line voltage threshold *)
    LiveVoltageThresh_kV : REAL := 95.0;     (* Live bus/line voltage threshold *)
    MaxRecloseShots      : INT := 3;         (* Maximum auto-reclose shots before 86 Lockout *)
    Shot1WaitTime_sec    : REAL := 2.0;      (* High-speed auto-reclose delay *)
    Shot2WaitTime_sec    : REAL := 15.0;     (* Delayed second shot *)
    Shot3WaitTime_sec    : REAL := 60.0;     (* Final third shot *)

    (* Internal Variables *)
    DeltaV               : REAL;
    DeltaF               : REAL;
    DeltaAngleAbs        : REAL;
    TargetWaitTime_sec   : REAL;
    ScanDeltaT_sec       : REAL := 0.050;    (* 50 ms task execution interval *)
END_VAR

(* Reset Lockout Handling *)
IF ResetLockoutCmd THEN
    LockoutStateOutput := FALSE;
    TripLatched := FALSE;
    RecloseShotCount := 0;
    RecloseTimer_sec := 0.0;
    RecloseActiveOutput := FALSE;
END_IF;

(* Delta Calculations *)
IF BusVoltage_kV >= LineVoltage_kV THEN
    DeltaV := BusVoltage_kV - LineVoltage_kV;
ELSE
    DeltaV := LineVoltage_kV - BusVoltage_kV;
END_IF;

IF BusFreq_Hz >= LineFreq_Hz THEN
    DeltaF := BusFreq_Hz - LineFreq_Hz;
ELSE
    DeltaF := LineFreq_Hz - BusFreq_Hz;
END_IF;

IF PhaseAngleDiff_deg >= 0.0 THEN
    DeltaAngleAbs := PhaseAngleDiff_deg;
ELSE
    DeltaAngleAbs := -PhaseAngleDiff_deg;
END_IF;

(* ANSI 25 Synchrocheck Evaluation *)
IF (BusVoltage_kV >= LiveVoltageThresh_kV) AND (LineVoltage_kV >= LiveVoltageThresh_kV) THEN
    IF (DeltaV <= MaxVoltDiff_kV) AND (DeltaF <= MaxFreqDiff_Hz) AND (DeltaAngleAbs <= MaxAngleDiff_deg) THEN
        SyncPermissive := TRUE;
    ELSE
        SyncPermissive := FALSE;
    END_IF;
ELSE
    SyncPermissive := FALSE;
END_IF;

(* Dead-Bus / Live-Line and Live-Bus / Dead-Line Conditions *)
DeadBusLiveLinePerm := (BusVoltage_kV < DeadVoltageThresh_kV) AND (LineVoltage_kV >= LiveVoltageThresh_kV);
LiveBusDeadLinePerm := (BusVoltage_kV >= LiveVoltageThresh_kV) AND (LineVoltage_kV < DeadVoltageThresh_kV);

SynchrocheckOKOutput := SyncPermissive OR DeadBusLiveLinePerm OR LiveBusDeadLinePerm;

(* Trip Initiation *)
IF ProtectiveTripIn AND NOT LockoutStateOutput THEN
    TripLatched := TRUE;
    IF NOT RecloseActiveOutput AND (RecloseShotCount < MaxRecloseShots) THEN
        RecloseActiveOutput := TRUE;
        RecloseTimer_sec := 0.0;
    END_IF;
END_IF;

(* Auto-Reclose Shot Progression (ANSI 79) *)
IF RecloseActiveOutput AND NOT LockoutStateOutput THEN
    RecloseTimer_sec := RecloseTimer_sec + ScanDeltaT_sec;

    (* Select Shot Delay *)
    IF RecloseShotCount = 0 THEN
        TargetWaitTime_sec := Shot1WaitTime_sec;
    ELSIF RecloseShotCount = 1 THEN
        TargetWaitTime_sec := Shot2WaitTime_sec;
    ELSE
        TargetWaitTime_sec := Shot3WaitTime_sec;
    END_IF;

    (* When wait delay is satisfied and synchrocheck permits *)
    IF (RecloseTimer_sec >= TargetWaitTime_sec) AND SynchrocheckOKOutput THEN
        BreakerCloseOutput := TRUE;
        RecloseShotCount := RecloseShotCount + 1;
        RecloseActiveOutput := FALSE;
        RecloseTimer_sec := 0.0;
        TripLatched := FALSE;
    ELSE
        BreakerCloseOutput := FALSE;
    END_IF;

    (* Lockout check if max shots exhausted *)
    IF RecloseShotCount >= MaxRecloseShots THEN
        LockoutStateOutput := TRUE;
        RecloseActiveOutput := FALSE;
        BreakerCloseOutput := FALSE;
    END_IF;
ELSE
    BreakerCloseOutput := FALSE;
END_IF;

(* Manual Close Authorization *)
IF ManualCloseCmd AND SynchrocheckOKOutput AND NOT LockoutStateOutput THEN
    BreakerCloseOutput := TRUE;
END_IF;

END_PROGRAM
