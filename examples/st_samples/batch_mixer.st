(* ============================================================================
 * Title:       Prog_BatchMixer
 * Author:      Horner Cscape MCP Specialist
 * Description:
 *   Industrial Food & Beverage Recipe Batch Mixing Sequence Program.
 *   Sequencer States:
 *     - State 0:  IDLE / READY: Awaiting Start Command
 *     - State 10: CHARGE WATER: Metering liquid phase to tare weight
 *     - State 20: FEED SYRUP: High-viscosity ingredient feed with slow agitation
 *     - State 30: HIGH SPEED BLEND: Dual-blade homogenizer timed mix
 *     - State 40: COOK / HEAT: Steam jacket heating to reaction temperature
 *     - State 50: HOLD REACTION: Controlled thermal dwell period
 *     - State 60: TRANSFER / DRAIN: Discharging product to holding tanks
 *     - State 70: CIP FLUSH: Clean-in-Place hot spray wash
 *     - State 99: SAFE ABORT: Immediate actuator lockout on interlock trip
 * Target:      Horner OCS / Straton K5 IEC 61131-3 Runtime
 * Language:    IEC 61131-3 Structured Text (ST) ONLY
 * ============================================================================ *)

PROGRAM Prog_BatchMixer
VAR
    (* Operator Commands *)
    StartBatchCmd : BOOL := FALSE;
    AbortBatchCmd : BOOL := FALSE;
    ResetFaultCmd : BOOL := FALSE;
    SkipToCipCmd  : BOOL := FALSE;

    (* Safety & Sensor Inputs *)
    LidInterlockClosed : BOOL := TRUE;
    VesselHighLevel    : BOOL := FALSE;
    LiquidWeightKg     : REAL := 0.0;
    BatchTemperatureC  : REAL := 22.5;

    (* Recipe Setpoints *)
    RecipeWaterKg      : REAL := 600.0;
    RecipeSyrupKg      : REAL := 250.0;
    RecipeTargetTempC  : REAL := 75.0;
    RecipeMixDuration  : TIME := T#3m;
    RecipeHoldDuration : TIME := T#5m;

    (* Actuator Digital Outputs *)
    ValveWaterSupply   : BOOL := FALSE;
    ValveSyrupSupply   : BOOL := FALSE;
    AgitatorLowSpeed   : BOOL := FALSE;
    AgitatorHighSpeed  : BOOL := FALSE;
    ValveSteamJacket   : BOOL := FALSE;
    ValveBottomDrain   : BOOL := FALSE;
    PumpCIPSpray       : BOOL := FALSE;

    (* Status Flags *)
    BatchRunning       : BOOL := FALSE;
    BatchComplete      : BOOL := FALSE;
    SystemInterlockTrip: BOOL := FALSE;

    (* Sequencer State & Timers *)
    CurrentStep        : INT := 0;
    PreviousStep       : INT := -1;
    TimerMixBlend      : TON;
    TimerReactionHold  : TON;
    TimerCIPWash       : TON;
END_VAR

(* 1. Safety Interlock Supervision *)
SystemInterlockTrip := NOT LidInterlockClosed OR VesselHighLevel OR AbortBatchCmd;

IF SystemInterlockTrip AND CurrentStep <> 0 AND CurrentStep <> 99 THEN
    CurrentStep := 99; (* Transition directly to safe shutdown state *)
END_IF;

(* 2. Main Sequencer State Machine *)
CASE CurrentStep OF
    0: (* IDLE State *)
        ValveWaterSupply  := FALSE;
        ValveSyrupSupply  := FALSE;
        AgitatorLowSpeed  := FALSE;
        AgitatorHighSpeed := FALSE;
        ValveSteamJacket  := FALSE;
        ValveBottomDrain  := FALSE;
        PumpCIPSpray      := FALSE;
        BatchRunning      := FALSE;

        IF StartBatchCmd AND NOT SystemInterlockTrip THEN
            BatchComplete := FALSE;
            BatchRunning  := TRUE;
            CurrentStep   := 10; (* Advance to Charge Water *)
        END_IF;

    10: (* CHARGE WATER *)
        ValveWaterSupply := TRUE;
        IF LiquidWeightKg >= RecipeWaterKg THEN
            ValveWaterSupply := FALSE;
            CurrentStep := 20; (* Advance to Feed Syrup *)
        END_IF;

    20: (* FEED SYRUP WITH LOW SPEED MIXING *)
        ValveSyrupSupply := TRUE;
        AgitatorLowSpeed := TRUE;
        IF LiquidWeightKg >= (RecipeWaterKg + RecipeSyrupKg) THEN
            ValveSyrupSupply := FALSE;
            CurrentStep := 30; (* Advance to High Speed Blend *)
        END_IF;

    30: (* HIGH SPEED BLEND *)
        AgitatorLowSpeed  := FALSE;
        AgitatorHighSpeed := TRUE;
        TimerMixBlend(IN := TRUE, PT := RecipeMixDuration);
        IF TimerMixBlend.Q THEN
            TimerMixBlend(IN := FALSE);
            AgitatorHighSpeed := FALSE;
            CurrentStep := 40; (* Advance to Cooking / Heating *)
        END_IF;

    40: (* STEAM JACKET HEATING *)
        AgitatorLowSpeed := TRUE; (* Keep product moving to prevent scorching *)
        ValveSteamJacket := BatchTemperatureC < RecipeTargetTempC;
        IF BatchTemperatureC >= RecipeTargetTempC THEN
            ValveSteamJacket := FALSE;
            CurrentStep := 50; (* Advance to Reaction Dwell *)
        END_IF;

    50: (* REACTION DWELL HOLD *)
        AgitatorLowSpeed := TRUE;
        ValveSteamJacket := BatchTemperatureC < (RecipeTargetTempC - 1.5);
        TimerReactionHold(IN := TRUE, PT := RecipeHoldDuration);
        IF TimerReactionHold.Q THEN
            TimerReactionHold(IN := FALSE);
            ValveSteamJacket := FALSE;
            CurrentStep := 60; (* Advance to Transfer *)
        END_IF;

    60: (* PRODUCT TRANSFER / VESSEL DRAIN *)
        AgitatorLowSpeed := FALSE;
        ValveBottomDrain := TRUE;
        IF LiquidWeightKg <= 8.0 THEN (* Vessel empty tare threshold *)
            ValveBottomDrain := FALSE;
            CurrentStep := 70; (* Advance to CIP Wash *)
        END_IF;

    70: (* CLEAN-IN-PLACE (CIP) SPRAY WASH *)
        PumpCIPSpray     := TRUE;
        ValveBottomDrain := TRUE;
        TimerCIPWash(IN := TRUE, PT := T#90s);
        IF TimerCIPWash.Q THEN
            TimerCIPWash(IN := FALSE);
            PumpCIPSpray     := FALSE;
            ValveBottomDrain := FALSE;
            BatchComplete    := TRUE;
            BatchRunning     := FALSE;
            CurrentStep      := 0; (* Cycle completed, return to IDLE *)
        END_IF;

    99: (* EMERGENCY SAFE ABORT *)
        ValveWaterSupply  := FALSE;
        ValveSyrupSupply  := FALSE;
        AgitatorLowSpeed  := FALSE;
        AgitatorHighSpeed := FALSE;
        ValveSteamJacket  := FALSE;
        ValveBottomDrain  := FALSE;
        PumpCIPSpray      := FALSE;
        BatchRunning      := FALSE;

        IF ResetFaultCmd AND NOT SystemInterlockTrip THEN
            CurrentStep := 0; (* Cleared to IDLE *)
        END_IF;

    ELSE
        CurrentStep := 0;
END_CASE;

END_PROGRAM
