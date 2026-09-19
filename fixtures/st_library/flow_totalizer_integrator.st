(* ============================================================================
 * Title:       FB_FlowTotalizer
 * Description: Industrial Fluid Flow Numerical Integrator & Telemetry Pulse Generator.
 * Features:
 *   - Trapezoidal numerical integration of instant flow rates to total volume
 *   - Low-flow cutoff threshold preventing measurement drift at near-zero flow
 *   - Triple accumulation tiers: Master Total, Daily Total, and Batch Total
 *   - Telemetry pulse generation: Fixed duration pulses for every N volume units
 *   - Forward and reverse flow direction qualification
 * Language:    IEC 61131-3 Structured Text (Pure ST)
 * ============================================================================ *)

FUNCTION_BLOCK FB_FlowTotalizer
VAR_INPUT
    FlowRate : REAL := 0.0;               (* Instantaneous fluid flow rate (e.g. m3/h, GPM, L/min) *)
    TimeBaseSec : REAL := 3600.0;         (* Time unit of flow rate in seconds (3600.0=hr, 60.0=min, 1.0=sec) *)
    LowFlowCutoff : REAL := 0.5;          (* Low flow threshold below which rate is forced to 0.0 *)
    ResetBatch : BOOL := FALSE;           (* Reset command for Batch Totalizer *)
    ResetDaily : BOOL := FALSE;           (* Reset command for Daily Totalizer *)
    ResetMaster : BOOL := FALSE;          (* Protected reset command for Master Totalizer *)
    PulseVolume : REAL := 10.0;           (* Volume units per telemetry pulse (e.g. 10.0 Liters) *)
    PulseDurationSec : REAL := 0.2;       (* Duration of each digital output pulse (seconds) *)
    CycleTimeSec : REAL := 0.1;           (* Execution scan period (seconds) *)
END_VAR

VAR_OUTPUT
    TotalMaster : LREAL := 0.0;           (* High-precision Master Total accumulated volume *)
    TotalDaily : REAL := 0.0;             (* Daily Resettable Total accumulated volume *)
    TotalBatch : REAL := 0.0;             (* Batch / Job Resettable Total volume *)
    NetFlowRate : REAL := 0.0;            (* Flow rate after low-flow cutoff qualification *)
    PulseOut : BOOL := FALSE;             (* Digital output pulse for remote telemetry / RTU *)
    PulseCount : DINT := 0;               (* Total number of volume pulses generated *)
END_VAR

VAR
    PrevRate : REAL := 0.0;               (* Previous scan flow rate for trapezoidal integration *)
    IncrementalVol : REAL := 0.0;         (* Volume accumulated during current scan cycle *)
    PulseVolumeAcc : REAL := 0.0;         (* Sub-pulse volume accumulator *)
    PulseTimer : REAL := 0.0;             (* Active pulse duration timer *)
END_VAR

(* 1. Manual and Automated Totalizer Resets *)
IF ResetMaster THEN
    TotalMaster := 0.0;
END_IF;

IF ResetDaily THEN
    TotalDaily := 0.0;
END_IF;

IF ResetBatch THEN
    TotalBatch := 0.0;
END_IF;

(* 2. Low-Flow Cutoff Evaluation *)
IF ABS(FlowRate) < LowFlowCutoff THEN
    NetFlowRate := 0.0;
ELSE
    NetFlowRate := FlowRate;
END_IF;

(* 3. Trapezoidal Numerical Integration: V = ((R1 + R0) / 2) * (dt / TimeBase) *)
IF TimeBaseSec > 0.001 THEN
    IncrementalVol := ((NetFlowRate + PrevRate) * 0.5) * (CycleTimeSec / TimeBaseSec);
ELSE
    IncrementalVol := 0.0;
END_IF;
PrevRate := NetFlowRate;

(* 4. Volume Accumulation Across Tiers *)
TotalMaster := TotalMaster + IncrementalVol;
TotalDaily := TotalDaily + IncrementalVol;
TotalBatch := TotalBatch + IncrementalVol;

(* 5. Telemetry Pulse Train Generation *)
IF PulseVolume > 0.001 THEN
    PulseVolumeAcc := PulseVolumeAcc + IncrementalVol;

    (* Trigger pulse when accumulated volume meets pulse threshold *)
    IF PulseVolumeAcc >= PulseVolume AND (NOT PulseOut) THEN
        PulseVolumeAcc := PulseVolumeAcc - PulseVolume;
        PulseOut := TRUE;
        PulseTimer := 0.0;
        PulseCount := PulseCount + 1;
    END_IF;

    (* Maintain pulse width for configured duration *)
    IF PulseOut THEN
        PulseTimer := PulseTimer + CycleTimeSec;
        IF PulseTimer >= PulseDurationSec THEN
            PulseOut := FALSE;
            PulseTimer := 0.0;
        END_IF;
    END_IF;
ELSE
    PulseOut := FALSE;
    PulseTimer := 0.0;
END_IF;

END_FUNCTION_BLOCK
