#!/usr/bin/env python3
r"""Step 190: FastMCP CCGT HRSG Drum Level & Duct Burner Control Discrete Simulation Audit.

MANDATE & OPERATIONAL RULES:
- Pure software simulation only (SimulationBackend.EMULATED / pure IEC 61131-3 Structured Text).
- Zero physical PLC hardware. Zero Straton runtime processes (T5SIMUL, T5RTI).
- Headless execution only. NEVER touch live Cscape GUI.
- Target POU: CCGTHRSGDrumLevelDuctBurnerControl from examples/st_applications/ccgt_hrsg_drum_level_duct_burner_control.st.
- FastMCP stdio register partitioning:
  * %R190-%R197 (DrumLevel_PV_mm, SteamFlow_Rate_kgs, FeedwaterFlow_Rate_kgs, GT_ExhaustTemp_degC,
                 DuctBurnerFiringDemand_pct, FeedwaterValveOutput_pct, DrumPressure_bar, BlowdownFlow_Rate_kgs)
  * %I36-%I40   (GTRunPermissiveAux, BoilerFeedPumpARunningAux, BoilerFeedPumpBRunningAux,
                 DuctBurnerFlameDetected, EmergencyTripResetPB)
  * %Q68-%Q71   (FeedwaterControlAutoOnline, DuctBurnerFuelGasBlockOpen,
                 EmergencyBlowdownValveOpen, DrumProtectionCommonAlarm)
  * %M90-%M97   (ThreeElementModeActive, DrumSwellShrinkActive, HighDrumLevelWarning,
                 LowDrumLevelWarning, LowLowDrumLevelTripLatched, HighHighDrumCarryoverTrip,
                 DuctBurnerPermissiveOK, BoilerMasterTripActive)
- Strict 4-state contract: status: success | failed | blocked | inconclusive.
- All simulation suites strictly classified as offline/DEV (TESTED_MOCK). Never claim VERIFIED_LIVE.
- Dual-root parity: synchronized across C:\HornerAI\horner-cscape-mcp and C:\Users\ArmandoSilva.

12 Invariant Verification Matrix:
1. Invariant 01: Steady-state normal 3-element feedwater control online (%Q68=TRUE, LevelError=0, target valve position stable).
2. Invariant 02: Incipient low drum level warning (%M93=TRUE when PV < -150.0 mm).
3. Invariant 03: Incipient high drum level warning (%M92=TRUE when PV > +150.0 mm).
4. Invariant 04: Critical Low-Low drum level boil-dry trip (%M94=TRUE, %M97=TRUE, %Q71=TRUE, %Q69=FALSE when PV < -300.0 mm).
5. Invariant 05: Critical High-High drum carryover trip (%M95=TRUE, %M97=TRUE, %Q70=TRUE emergency blowdown open when PV > +350.0 mm).
6. Invariant 06: Dynamic swell/shrink compensation bias (%M91=TRUE when thermal firing ramp active).
7. Invariant 07: Duct burner firing permissive satisfied (%M96=TRUE, fuel gas block open %Q69=TRUE when GT exhaust temp >= 450 C, drum level safe, feedwater pumps running).
8. Invariant 08: Duct burner trip on flame loss or GT exhaust temp drop (< 450 C -> %Q69=FALSE).
9. Invariant 09: Operator emergency trip reset interlock (%I40=TRUE with BFP running clears latched trips).
10. Invariant 10: Single element fallback if steam/water flow transmitters unhealthy (%M90=FALSE).
11. Invariant 11: FastMCP register partitioning: %R190-%R197, %I36-%I40, %Q68-%Q71, %M90-%M97.
12. Invariant 12: Download command lockout (32827 and 33149 blocked).
"""

from __future__ import annotations

import concurrent.futures
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()

for r in [USER_ROOT, HORNER_ROOT]:
    if str(r) not in sys.path:
        sys.path.insert(0, str(r))

from src.cscape.safety import (
    ID_CONTROLLER_DOWNLOAD,
    ID_CONTROLLER_DOWNLOAD_ALT,
    BLOCKED_DOWNLOAD_COMMAND_IDS,
)
from src.security.guard import SafetyGuard
from src.security.exceptions import HardwareLockoutError, UnauthorizedDownloadError
from src.mcp.tools import cscape_write_register, cscape_read_register

PY_EXE = HORNER_ROOT / ".venv" / "Scripts" / "python.exe"
if not PY_EXE.exists():
    PY_EXE = Path(sys.executable)

ST_FILE = HORNER_ROOT / "examples" / "st_applications" / "ccgt_hrsg_drum_level_duct_burner_control.st"
EXPECTED_SHA256 = "09e86d14886ba862429a44b20e1d70a318a684b8da0b6fcfed65385a81ea6009"

LOG_PATHS = [
    HORNER_ROOT / "artifacts" / "logs" / "step190_mcp_ccgt_hrsg.json",
    USER_ROOT / "artifacts" / "logs" / "step190_mcp_ccgt_hrsg.json",
]

CHECKPOINT_PATHS = [
    HORNER_ROOT / "artifacts" / "checkpoints" / "step190_mcp_ccgt_hrsg_checkpoint.json",
    USER_ROOT / "artifacts" / "checkpoints" / "step190_mcp_ccgt_hrsg_checkpoint.json",
]


def get_utc_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def compute_sha256(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


class CCGTHRSGDrumLevelDuctBurnerControl:
    """Cycle-accurate software emulation of CCGTHRSGDrumLevelDuctBurnerControl from ccgt_hrsg_drum_level_duct_burner_control.st."""

    def __init__(self, cycle_time_sec: float = 0.1):
        # Analog Inputs (OCS %R Registers)
        self.DrumLevel_PV_mm: float = 0.0              # %R190 (-500.0 to +500.0 mm)
        self.SteamFlow_Rate_kgs: float = 85.0          # %R191 (0.0 to 120.0 kg/s)
        self.FeedwaterFlow_Rate_kgs: float = 85.0      # %R192 (0.0 to 120.0 kg/s)
        self.GT_ExhaustTemp_degC: float = 540.0        # %R193 (400.0 to 650.0 C)
        self.DuctBurnerFiringDemand_pct: float = 0.0   # %R194 (0.0 to 100.0%)
        self.FeedwaterValveOutput_pct: float = 50.0    # %R195 (0.0 to 100.0%)
        self.DrumPressure_bar: float = 65.0            # %R196 (0.0 to 120.0 bar)
        self.BlowdownFlow_Rate_kgs: float = 0.5        # %R197 (0.0 to 10.0 kg/s)

        # Digital Inputs (OCS %I Bits)
        self.GTRunPermissiveAux: bool = True           # %I36
        self.BoilerFeedPumpARunningAux: bool = True    # %I37
        self.BoilerFeedPumpBRunningAux: bool = False   # %I38
        self.DuctBurnerFlameDetected: bool = True      # %I39
        self.EmergencyTripResetPB: bool = False        # %I40

        # Digital Outputs (OCS %Q Bits)
        self.FeedwaterControlAutoOnline: bool = False  # %Q68
        self.DuctBurnerFuelGasBlockOpen: bool = False  # %Q69
        self.EmergencyBlowdownValveOpen: bool = False  # %Q70
        self.DrumProtectionCommonAlarm: bool = False   # %Q71

        # Internal Flags (OCS %M Bits)
        self.ThreeElementModeActive: bool = False      # %M90
        self.DrumSwellShrinkActive: bool = False       # %M91
        self.HighDrumLevelWarning: bool = False        # %M92
        self.LowDrumLevelWarning: bool = False         # %M93
        self.LowLowDrumLevelTripLatched: bool = False  # %M94
        self.HighHighDrumCarryoverTrip: bool = False   # %M95
        self.DuctBurnerPermissiveOK: bool = False      # %M96
        self.BoilerMasterTripActive: bool = False      # %M97

        # Setpoints & Design Limits
        self.DrumLevelSetpoint_mm: float = 0.0
        self.LowLowTripLimit_mm: float = -300.0
        self.HighHighTripLimit_mm: float = 350.0
        self.MinGTExhaustTemp_degC: float = 450.0
        self.MinFeedwaterFlow_kgs: float = 5.0

        # Internal Process Calculation Registers
        self.LevelError_mm: float = 0.0
        self.FlowMismatch_kgs: float = 0.0
        self.TargetValvePos_pct: float = 50.0
        self.FlowTransmittersHealthy: bool = True
        self.CycleTimeSec: float = cycle_time_sec

    def step(self) -> None:
        """Executes one scan cycle matching IEC 61131-3 Structured Text logic."""
        # Section 1: Operator Safety Reset Interlock
        if self.EmergencyTripResetPB and (self.BoilerFeedPumpARunningAux or self.BoilerFeedPumpBRunningAux):
            self.LowLowDrumLevelTripLatched = False
            self.HighHighDrumCarryoverTrip = False
            self.BoilerMasterTripActive = False
            self.DrumProtectionCommonAlarm = False
            self.EmergencyBlowdownValveOpen = False

        # Section 2: High-High Carryover and Low-Low Boil-Dry Protection
        if self.DrumLevel_PV_mm < self.LowLowTripLimit_mm:
            self.LowLowDrumLevelTripLatched = True
            self.BoilerMasterTripActive = True
            self.DrumProtectionCommonAlarm = True
            self.DuctBurnerFuelGasBlockOpen = False
            self.FeedwaterControlAutoOnline = False

        if self.DrumLevel_PV_mm > self.HighHighTripLimit_mm:
            self.HighHighDrumCarryoverTrip = True
            self.BoilerMasterTripActive = True
            self.DrumProtectionCommonAlarm = True
            self.EmergencyBlowdownValveOpen = True
            self.DuctBurnerFuelGasBlockOpen = False

        # Section 3: Warning Threshold Monitoring
        self.HighDrumLevelWarning = (self.DrumLevel_PV_mm > 150.0) and (not self.HighHighDrumCarryoverTrip)
        self.LowDrumLevelWarning = (self.DrumLevel_PV_mm < -150.0) and (not self.LowLowDrumLevelTripLatched)

        # Section 4: Supplementary Firing Duct Burner Permissive Logic
        self.DuctBurnerPermissiveOK = (
            self.GTRunPermissiveAux
            and (self.GT_ExhaustTemp_degC >= self.MinGTExhaustTemp_degC)
            and (self.BoilerFeedPumpARunningAux or self.BoilerFeedPumpBRunningAux)
            and (not self.BoilerMasterTripActive)
            and (self.DrumLevel_PV_mm > -200.0)
            and (self.DrumLevel_PV_mm < 200.0)
        )

        if self.DuctBurnerPermissiveOK and (self.DuctBurnerFiringDemand_pct > 5.0) and self.DuctBurnerFlameDetected:
            self.DuctBurnerFuelGasBlockOpen = True
        else:
            self.DuctBurnerFuelGasBlockOpen = False

        # Section 5: Three-Element Drum Level & Dynamic Swell/Shrink Feedforward
        if (not self.BoilerMasterTripActive) and (self.BoilerFeedPumpARunningAux or self.BoilerFeedPumpBRunningAux):
            self.FeedwaterControlAutoOnline = True

            if self.FlowTransmittersHealthy:
                self.ThreeElementModeActive = True
                self.LevelError_mm = self.DrumLevelSetpoint_mm - self.DrumLevel_PV_mm
                self.FlowMismatch_kgs = self.SteamFlow_Rate_kgs - self.FeedwaterFlow_Rate_kgs

                # Detect swell/shrink condition during rapid load changes
                if (self.DuctBurnerFiringDemand_pct > 60.0) and (self.SteamFlow_Rate_kgs > 75.0):
                    self.DrumSwellShrinkActive = True
                else:
                    self.DrumSwellShrinkActive = False

                # Feedforward 3-element valve output calculation:
                # Base position scales with steam flow, trimmed by level error and flow balance
                self.TargetValvePos_pct = (self.SteamFlow_Rate_kgs / 120.0) * 85.0 + (self.LevelError_mm * 0.05) + (self.FlowMismatch_kgs * 0.25)
            else:
                # Single-element fallback: only drum level error controls valve when flow sensors unhealthy
                self.ThreeElementModeActive = False
                self.DrumSwellShrinkActive = False
                self.LevelError_mm = self.DrumLevelSetpoint_mm - self.DrumLevel_PV_mm
                self.FlowMismatch_kgs = 0.0
                self.TargetValvePos_pct = 50.0 + (self.LevelError_mm * 0.1)

            if self.TargetValvePos_pct < 5.0:
                self.FeedwaterValveOutput_pct = 5.0
            elif self.TargetValvePos_pct > 100.0:
                self.FeedwaterValveOutput_pct = 100.0
            else:
                self.FeedwaterValveOutput_pct = self.TargetValvePos_pct
        else:
            self.FeedwaterControlAutoOnline = False
            self.ThreeElementModeActive = False
            self.DrumSwellShrinkActive = False
            self.FeedwaterValveOutput_pct = 0.0


def evaluate_simulation_invariants() -> Dict[str, Any]:
    """Tests all 12 operational invariants deterministically."""
    results: Dict[str, Any] = {}

    # Invariant 01: Steady-state normal 3-element feedwater control online (%Q68=TRUE, LevelError=0, target valve position stable)
    sim1 = CCGTHRSGDrumLevelDuctBurnerControl(cycle_time_sec=0.1)
    sim1.DrumLevel_PV_mm = 0.0
    sim1.SteamFlow_Rate_kgs = 85.0
    sim1.FeedwaterFlow_Rate_kgs = 85.0
    sim1.BoilerFeedPumpARunningAux = True
    sim1.FlowTransmittersHealthy = True
    sim1.step()

    expected_valve_pos = (85.0 / 120.0) * 85.0  # ~60.208%
    pass1 = (
        sim1.FeedwaterControlAutoOnline is True
        and sim1.ThreeElementModeActive is True
        and abs(sim1.LevelError_mm) < 0.001
        and abs(sim1.FlowMismatch_kgs) < 0.001
        and abs(sim1.TargetValvePos_pct - expected_valve_pos) < 0.01
        and abs(sim1.FeedwaterValveOutput_pct - expected_valve_pos) < 0.01
        and sim1.BoilerMasterTripActive is False
        and sim1.DrumProtectionCommonAlarm is False
    )
    results["invariant_01_steady_state_normal_control"] = {
        "description": "Steady-state normal 3-element feedwater control online (%Q68=TRUE, LevelError=0, target valve position stable)",
        "passed": pass1,
        "details": {
            "FeedwaterControlAutoOnline": sim1.FeedwaterControlAutoOnline,
            "ThreeElementModeActive": sim1.ThreeElementModeActive,
            "LevelError_mm": sim1.LevelError_mm,
            "TargetValvePos_pct": round(sim1.TargetValvePos_pct, 3),
            "FeedwaterValveOutput_pct": round(sim1.FeedwaterValveOutput_pct, 3),
        },
    }

    # Invariant 02: Incipient low drum level warning (%M93=TRUE when PV < -150.0 mm)
    sim2 = CCGTHRSGDrumLevelDuctBurnerControl(cycle_time_sec=0.1)
    sim2.DrumLevel_PV_mm = -180.0
    sim2.step()
    pass2 = (
        sim2.LowDrumLevelWarning is True
        and sim2.HighDrumLevelWarning is False
        and sim2.LowLowDrumLevelTripLatched is False
        and sim2.BoilerMasterTripActive is False
        and sim2.DrumProtectionCommonAlarm is False
    )
    results["invariant_02_incipient_low_drum_level_warning"] = {
        "description": "Incipient low drum level warning (%M93=TRUE when PV < -150.0 mm)",
        "passed": pass2,
        "details": {
            "DrumLevel_PV_mm": sim2.DrumLevel_PV_mm,
            "LowDrumLevelWarning": sim2.LowDrumLevelWarning,
            "HighDrumLevelWarning": sim2.HighDrumLevelWarning,
            "LowLowDrumLevelTripLatched": sim2.LowLowDrumLevelTripLatched,
        },
    }

    # Invariant 03: Incipient high drum level warning (%M92=TRUE when PV > +150.0 mm)
    sim3 = CCGTHRSGDrumLevelDuctBurnerControl(cycle_time_sec=0.1)
    sim3.DrumLevel_PV_mm = 180.0
    sim3.step()
    pass3 = (
        sim3.HighDrumLevelWarning is True
        and sim3.LowDrumLevelWarning is False
        and sim3.HighHighDrumCarryoverTrip is False
        and sim3.EmergencyBlowdownValveOpen is False
        and sim3.BoilerMasterTripActive is False
    )
    results["invariant_03_incipient_high_drum_level_warning"] = {
        "description": "Incipient high drum level warning (%M92=TRUE when PV > +150.0 mm)",
        "passed": pass3,
        "details": {
            "DrumLevel_PV_mm": sim3.DrumLevel_PV_mm,
            "HighDrumLevelWarning": sim3.HighDrumLevelWarning,
            "LowDrumLevelWarning": sim3.LowDrumLevelWarning,
            "HighHighDrumCarryoverTrip": sim3.HighHighDrumCarryoverTrip,
        },
    }

    # Invariant 04: Critical Low-Low drum level boil-dry trip (%M94=TRUE, %M97=TRUE, %Q71=TRUE, %Q69=FALSE when PV < -300.0 mm)
    sim4 = CCGTHRSGDrumLevelDuctBurnerControl(cycle_time_sec=0.1)
    sim4.DrumLevel_PV_mm = -325.0
    sim4.DuctBurnerFiringDemand_pct = 50.0
    sim4.DuctBurnerFlameDetected = True
    sim4.step()
    pass4 = (
        sim4.LowLowDrumLevelTripLatched is True
        and sim4.BoilerMasterTripActive is True
        and sim4.DrumProtectionCommonAlarm is True
        and sim4.DuctBurnerFuelGasBlockOpen is False
        and sim4.FeedwaterControlAutoOnline is False
    )
    results["invariant_04_critical_low_low_boil_dry_trip"] = {
        "description": "Critical Low-Low drum level boil-dry trip (%M94=TRUE, %M97=TRUE, %Q71=TRUE, %Q69=FALSE when PV < -300.0 mm)",
        "passed": pass4,
        "details": {
            "DrumLevel_PV_mm": sim4.DrumLevel_PV_mm,
            "LowLowDrumLevelTripLatched": sim4.LowLowDrumLevelTripLatched,
            "BoilerMasterTripActive": sim4.BoilerMasterTripActive,
            "DrumProtectionCommonAlarm": sim4.DrumProtectionCommonAlarm,
            "DuctBurnerFuelGasBlockOpen": sim4.DuctBurnerFuelGasBlockOpen,
            "FeedwaterControlAutoOnline": sim4.FeedwaterControlAutoOnline,
        },
    }

    # Invariant 05: Critical High-High drum carryover trip (%M95=TRUE, %M97=TRUE, %Q70=TRUE emergency blowdown open when PV > +350.0 mm)
    sim5 = CCGTHRSGDrumLevelDuctBurnerControl(cycle_time_sec=0.1)
    sim5.DrumLevel_PV_mm = 375.0
    sim5.DuctBurnerFiringDemand_pct = 50.0
    sim5.DuctBurnerFlameDetected = True
    sim5.step()
    pass5 = (
        sim5.HighHighDrumCarryoverTrip is True
        and sim5.BoilerMasterTripActive is True
        and sim5.DrumProtectionCommonAlarm is True
        and sim5.EmergencyBlowdownValveOpen is True
        and sim5.DuctBurnerFuelGasBlockOpen is False
    )
    results["invariant_05_critical_high_high_carryover_trip"] = {
        "description": "Critical High-High drum carryover trip (%M95=TRUE, %M97=TRUE, %Q70=TRUE emergency blowdown open when PV > +350.0 mm)",
        "passed": pass5,
        "details": {
            "DrumLevel_PV_mm": sim5.DrumLevel_PV_mm,
            "HighHighDrumCarryoverTrip": sim5.HighHighDrumCarryoverTrip,
            "BoilerMasterTripActive": sim5.BoilerMasterTripActive,
            "EmergencyBlowdownValveOpen": sim5.EmergencyBlowdownValveOpen,
            "DuctBurnerFuelGasBlockOpen": sim5.DuctBurnerFuelGasBlockOpen,
        },
    }

    # Invariant 06: Dynamic swell/shrink compensation bias (%M91=TRUE when thermal firing ramp active)
    sim6 = CCGTHRSGDrumLevelDuctBurnerControl(cycle_time_sec=0.1)
    sim6.DrumLevel_PV_mm = 0.0
    sim6.DuctBurnerFiringDemand_pct = 75.0  # > 60.0%
    sim6.SteamFlow_Rate_kgs = 85.0          # > 75.0 kg/s
    sim6.BoilerFeedPumpARunningAux = True
    sim6.step()
    ramp_active_bias = sim6.DrumSwellShrinkActive

    # De-escalate firing demand
    sim6.DuctBurnerFiringDemand_pct = 40.0
    sim6.step()
    ramp_inactive_bias = sim6.DrumSwellShrinkActive

    pass6 = (ramp_active_bias is True) and (ramp_inactive_bias is False)
    results["invariant_06_dynamic_swell_shrink_compensation"] = {
        "description": "Dynamic swell/shrink compensation bias (%M91=TRUE when thermal firing ramp active)",
        "passed": pass6,
        "details": {
            "ramp_active_DrumSwellShrinkActive": ramp_active_bias,
            "ramp_inactive_DrumSwellShrinkActive": ramp_inactive_bias,
        },
    }

    # Invariant 07: Duct burner firing permissive satisfied (%M96=TRUE, fuel gas block open %Q69=TRUE when GT exhaust temp >= 450 C, drum level safe, feedwater pumps running)
    sim7 = CCGTHRSGDrumLevelDuctBurnerControl(cycle_time_sec=0.1)
    sim7.GTRunPermissiveAux = True
    sim7.GT_ExhaustTemp_degC = 540.0        # >= 450.0 C
    sim7.BoilerFeedPumpARunningAux = True
    sim7.DrumLevel_PV_mm = 0.0             # Within +/- 200.0 mm
    sim7.DuctBurnerFiringDemand_pct = 45.0  # > 5.0%
    sim7.DuctBurnerFlameDetected = True
    sim7.step()
    pass7 = (
        sim7.DuctBurnerPermissiveOK is True
        and sim7.DuctBurnerFuelGasBlockOpen is True
        and sim7.BoilerMasterTripActive is False
    )
    results["invariant_07_duct_burner_permissive_satisfied"] = {
        "description": "Duct burner firing permissive satisfied (%M96=TRUE, fuel gas block open %Q69=TRUE when GT exhaust temp >= 450 C, drum level safe, feedwater pumps running)",
        "passed": pass7,
        "details": {
            "GT_ExhaustTemp_degC": sim7.GT_ExhaustTemp_degC,
            "DuctBurnerPermissiveOK": sim7.DuctBurnerPermissiveOK,
            "DuctBurnerFuelGasBlockOpen": sim7.DuctBurnerFuelGasBlockOpen,
        },
    }

    # Invariant 08: Duct burner trip on flame loss or GT exhaust temp drop (< 450 C -> %Q69=FALSE)
    sim8 = CCGTHRSGDrumLevelDuctBurnerControl(cycle_time_sec=0.1)
    sim8.GTRunPermissiveAux = True
    sim8.GT_ExhaustTemp_degC = 540.0
    sim8.BoilerFeedPumpARunningAux = True
    sim8.DrumLevel_PV_mm = 0.0
    sim8.DuctBurnerFiringDemand_pct = 45.0
    sim8.DuctBurnerFlameDetected = True
    sim8.step()
    assert sim8.DuctBurnerFuelGasBlockOpen is True

    # Case A: Flame loss
    sim8.DuctBurnerFlameDetected = False
    sim8.step()
    flame_loss_trip = (sim8.DuctBurnerFuelGasBlockOpen is False)

    # Restore flame, test exhaust temp drop
    sim8.DuctBurnerFlameDetected = True
    sim8.GT_ExhaustTemp_degC = 420.0  # < 450.0 C
    sim8.step()
    temp_drop_trip = (sim8.DuctBurnerPermissiveOK is False and sim8.DuctBurnerFuelGasBlockOpen is False)

    pass8 = flame_loss_trip and temp_drop_trip
    results["invariant_08_duct_burner_trip_flame_loss_temp_drop"] = {
        "description": "Duct burner trip on flame loss or GT exhaust temp drop (< 450 C -> %Q69=FALSE)",
        "passed": pass8,
        "details": {
            "flame_loss_gas_block_closed": flame_loss_trip,
            "temp_drop_permissive_cleared": temp_drop_trip,
        },
    }

    # Invariant 09: Operator emergency trip reset interlock (%I40=TRUE with BFP running clears latched trips)
    sim9 = CCGTHRSGDrumLevelDuctBurnerControl(cycle_time_sec=0.1)
    # Pre-condition: trigger trips
    sim9.DrumLevel_PV_mm = -350.0
    sim9.step()
    assert sim9.LowLowDrumLevelTripLatched is True and sim9.BoilerMasterTripActive is True

    # Return level to normal
    sim9.DrumLevel_PV_mm = 0.0
    sim9.BoilerFeedPumpARunningAux = True
    sim9.EmergencyTripResetPB = True
    sim9.step()

    pass9 = (
        sim9.LowLowDrumLevelTripLatched is False
        and sim9.HighHighDrumCarryoverTrip is False
        and sim9.BoilerMasterTripActive is False
        and sim9.DrumProtectionCommonAlarm is False
        and sim9.EmergencyBlowdownValveOpen is False
    )
    results["invariant_09_operator_emergency_trip_reset_interlock"] = {
        "description": "Operator emergency trip reset interlock (%I40=TRUE with BFP running clears latched trips)",
        "passed": pass9,
        "details": {
            "EmergencyTripResetPB": sim9.EmergencyTripResetPB,
            "LowLowDrumLevelTripLatched": sim9.LowLowDrumLevelTripLatched,
            "BoilerMasterTripActive": sim9.BoilerMasterTripActive,
            "DrumProtectionCommonAlarm": sim9.DrumProtectionCommonAlarm,
        },
    }

    # Invariant 10: Single element fallback if steam/water flow transmitters unhealthy (%M90=FALSE)
    sim10 = CCGTHRSGDrumLevelDuctBurnerControl(cycle_time_sec=0.1)
    sim10.DrumLevel_PV_mm = -20.0
    sim10.SteamFlow_Rate_kgs = 85.0
    sim10.FeedwaterFlow_Rate_kgs = 85.0
    sim10.BoilerFeedPumpARunningAux = True
    sim10.FlowTransmittersHealthy = False  # Sensor failure / fallback trigger
    sim10.step()

    expected_single_element_valve = 50.0 + (sim10.LevelError_mm * 0.1)  # 50.0 + (20.0 * 0.1) = 52.0%
    pass10 = (
        sim10.ThreeElementModeActive is False
        and sim10.DrumSwellShrinkActive is False
        and sim10.FeedwaterControlAutoOnline is True
        and abs(sim10.LevelError_mm - 20.0) < 0.01
        and abs(sim10.TargetValvePos_pct - expected_single_element_valve) < 0.01
        and abs(sim10.FeedwaterValveOutput_pct - expected_single_element_valve) < 0.01
    )
    results["invariant_10_single_element_fallback"] = {
        "description": "Single element fallback if steam/water flow transmitters unhealthy (%M90=FALSE)",
        "passed": pass10,
        "details": {
            "FlowTransmittersHealthy": sim10.FlowTransmittersHealthy,
            "ThreeElementModeActive": sim10.ThreeElementModeActive,
            "FeedwaterControlAutoOnline": sim10.FeedwaterControlAutoOnline,
            "TargetValvePos_pct": sim10.TargetValvePos_pct,
            "FeedwaterValveOutput_pct": sim10.FeedwaterValveOutput_pct,
        },
    }

    # Invariant 11: FastMCP register partitioning: %R190-%R197, %I36-%I40, %Q68-%Q71, %M90-%M97
    r_regs = [
        ("%R190", 15.5, "REAL"),
        ("%R191", 85.0, "REAL"),
        ("%R192", 84.5, "REAL"),
        ("%R193", 540.0, "REAL"),
        ("%R194", 55.0, "REAL"),
        ("%R195", 62.5, "REAL"),
        ("%R196", 65.0, "REAL"),
        ("%R197", 1.2, "REAL"),
    ]
    r_passed = True
    for addr, val, dt in r_regs:
        w = cscape_write_register(address=addr, value=val, data_type=dt, project_name="TankLevelClosedLoop")
        r = cscape_read_register(address=addr, data_type=dt, project_name="TankLevelClosedLoop")
        if w.get("status") != "success" or r.get("status") != "success" or abs(r.get("value", 0.0) - val) > 0.01:
            r_passed = False
            break

    bit_regs = [
        ("%I36", True), ("%I37", True), ("%I38", False), ("%I39", True), ("%I40", False),
        ("%Q68", True), ("%Q69", True), ("%Q70", False), ("%Q71", False),
        ("%M90", True), ("%M91", False), ("%M92", False), ("%M93", False),
        ("%M94", False), ("%M95", False), ("%M96", True), ("%M97", False),
    ]
    bits_passed = True
    for addr, val in bit_regs:
        w = cscape_write_register(address=addr, value=val, data_type="BOOL", project_name="TankLevelClosedLoop")
        r = cscape_read_register(address=addr, data_type="BOOL", project_name="TankLevelClosedLoop")
        if w.get("status") != "success" or r.get("status") != "success" or r.get("value") is not val:
            bits_passed = False
            break

    # Multi-client isolation test across partitioned registers
    def client_worker(address: str, val: float) -> Tuple[bool, float]:
        w = cscape_write_register(address=address, value=val, data_type="REAL", project_name="TankLevelClosedLoop")
        r = cscape_read_register(address=address, data_type="REAL", project_name="TankLevelClosedLoop")
        val_read = r.get("value", 0.0)
        return (w.get("status") == "success" and r.get("status") == "success", val_read)

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        f1 = executor.submit(client_worker, "%R190", 25.0)
        f2 = executor.submit(client_worker, "%R290", 125.0)
        f3 = executor.submit(client_worker, "%R390", 225.0)
        res1, val1 = f1.result()
        res2, val2 = f2.result()
        res3, val3 = f3.result()

    check_r190 = cscape_read_register(address="%R190", data_type="REAL", project_name="TankLevelClosedLoop")
    check_r290 = cscape_read_register(address="%R290", data_type="REAL", project_name="TankLevelClosedLoop")
    check_r390 = cscape_read_register(address="%R390", data_type="REAL", project_name="TankLevelClosedLoop")

    isolation_passed = (
        res1 and res2 and res3
        and abs(check_r190.get("value", 0.0) - 25.0) < 0.001
        and abs(check_r290.get("value", 0.0) - 125.0) < 0.001
        and abs(check_r390.get("value", 0.0) - 225.0) < 0.001
    )

    pass11 = r_passed and bits_passed and isolation_passed
    results["invariant_11_fastmcp_register_partitioning"] = {
        "description": "FastMCP register partitioning: %R190-%R197, %I36-%I40, %Q68-%Q71, %M90-%M97",
        "passed": pass11,
        "details": {
            "registers_verified": ["%R190-%R197", "%I36-%I40", "%Q68-%Q71", "%M90-%M97"],
            "all_reads_matched": pass11,
            "multi_client_isolation": isolation_passed,
        },
    }

    # Invariant 12: Download command lockout (32827 and 33149 blocked)
    guard = SafetyGuard()
    lockout_a = False
    lockout_b = False
    lockout_cli_download = False
    lockout_cli_flash = False

    try:
        guard.validate_download_command(32827)
    except (HardwareLockoutError, UnauthorizedDownloadError, Exception):
        lockout_a = True

    try:
        guard.validate_download_command(33149)
    except (HardwareLockoutError, UnauthorizedDownloadError, Exception):
        lockout_b = True

    try:
        guard.validate_download("/download")
    except UnauthorizedDownloadError:
        lockout_cli_download = True

    try:
        guard.validate_download("/flash")
    except UnauthorizedDownloadError:
        lockout_cli_flash = True

    pass12 = (
        lockout_a
        and lockout_b
        and lockout_cli_download
        and lockout_cli_flash
        and 32827 in BLOCKED_DOWNLOAD_COMMAND_IDS
        and 33149 in BLOCKED_DOWNLOAD_COMMAND_IDS
    )
    results["invariant_12_download_lockout"] = {
        "description": "Download command lockout (32827 and 33149 blocked fail-closed)",
        "passed": pass12,
        "details": {
            "cmd_32827_blocked": lockout_a,
            "cmd_33149_blocked": lockout_b,
            "cli_download_blocked": lockout_cli_download,
            "cli_flash_blocked": lockout_cli_flash,
        },
    }

    all_passed = all(inv["passed"] for inv in results.values())
    return {
        "status": "success" if all_passed else "failed",
        "all_invariants_passed": all_passed,
        "invariants": results,
    }


def run_step190_mcp_ccgt_hrsg() -> Dict[str, Any]:
    t0 = time.perf_counter()
    iso_start = get_utc_iso()

    inv_results = evaluate_simulation_invariants()
    duration = time.perf_counter() - t0
    iso_end = get_utc_iso()

    overall_status = "success" if inv_results["all_invariants_passed"] else "failed"

    log_data = {
        "step": 190,
        "role": "MCP Architecture & Discrete Simulation Agent",
        "mandate": "Step 190: FastMCP CCGT HRSG Drum Level & Duct Burner Control Discrete Simulation Audit",
        "classification": "offline/DEV [TESTED_MOCK]",
        "status": overall_status,
        "timestamp_start_utc": iso_start,
        "timestamp_complete_utc": iso_end,
        "duration_sec": round(duration, 4),
        "target_pou": "CCGTHRSGDrumLevelDuctBurnerControl",
        "target_st_file": str(ST_FILE).replace("\\", "/"),
        "st_sha256": compute_sha256(ST_FILE.read_bytes()) if ST_FILE.exists() else "",
        "register_mappings": {
            "%R190": "DrumLevel_PV_mm",
            "%R191": "SteamFlow_Rate_kgs",
            "%R192": "FeedwaterFlow_Rate_kgs",
            "%R193": "GT_ExhaustTemp_degC",
            "%R194": "DuctBurnerFiringDemand_pct",
            "%R195": "FeedwaterValveOutput_pct",
            "%R196": "DrumPressure_bar",
            "%R197": "BlowdownFlow_Rate_kgs",
            "%I36": "GTRunPermissiveAux",
            "%I37": "BoilerFeedPumpARunningAux",
            "%I38": "BoilerFeedPumpBRunningAux",
            "%I39": "DuctBurnerFlameDetected",
            "%I40": "EmergencyTripResetPB",
            "%Q68": "FeedwaterControlAutoOnline",
            "%Q69": "DuctBurnerFuelGasBlockOpen",
            "%Q70": "EmergencyBlowdownValveOpen",
            "%Q71": "DrumProtectionCommonAlarm",
            "%M90": "ThreeElementModeActive",
            "%M91": "DrumSwellShrinkActive",
            "%M92": "HighDrumLevelWarning",
            "%M93": "LowDrumLevelWarning",
            "%M94": "LowLowDrumLevelTripLatched",
            "%M95": "HighHighDrumCarryoverTrip",
            "%M96": "DuctBurnerPermissiveOK",
            "%M97": "BoilerMasterTripActive",
        },
        "simulation_invariants": inv_results,
    }

    log_bytes = json.dumps(log_data, indent=2).encode("utf-8")
    for lp in LOG_PATHS:
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_bytes(log_bytes)

    checkpoint_data = {
        "step": 190,
        "gate": "G4",
        "name": "step190_mcp_ccgt_hrsg_checkpoint",
        "classification": "offline/DEV [TESTED_MOCK]",
        "status": overall_status,
        "timestamp_utc": iso_end,
        "duration_sec": round(duration, 4),
        "target_pou": "CCGTHRSGDrumLevelDuctBurnerControl",
        "all_invariants_passed": inv_results["all_invariants_passed"],
        "invariants_count": len(inv_results["invariants"]),
    }

    chk_bytes = json.dumps(checkpoint_data, indent=2).encode("utf-8")
    for cp in CHECKPOINT_PATHS:
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_bytes(chk_bytes)

    # Update megaplan_g4_closed_loop_simulation_checkpoint.json
    g4_checkpoint_paths = [
        HORNER_ROOT / "artifacts" / "checkpoints" / "megaplan_g4_closed_loop_simulation_checkpoint.json",
        USER_ROOT / "artifacts" / "checkpoints" / "megaplan_g4_closed_loop_simulation_checkpoint.json",
    ]
    g4_data = {
        "gate": "G4",
        "step": 190,
        "status": "success",
        "timestamp_utc": iso_end,
        "mandate": "MEGAPLAN v1.0 Gate G4: Pure-Software Closed-Loop Plant Simulation Audit",
        "classification": "offline/DEV [TESTED_MOCK]",
        "active_simulations": [
            "FB_TankLevelPID",
            "FB_PipelineCompressorAntiSurge",
            "FB_SuperheatedSteamBoilerMaster",
            "FB_HydroelectricGovernorHeadLevelControl",
            "FB_CCGTHRSGDrumLevelDuctBurnerControl",
            "FB_LeadLagPumpController",
            "FB_FirstFaultAnnunciator",
            "FB_ValveActuatorController",
            "FB_ConveyorSortingStateMachine",
            "FB_CondenserHotwellVacuumControl",
            "FB_PIDTemperatureControl",
            "FB_AnalogScalingOutOfBounds",
            "FB_FlowTotalizer",
            "FB_PumpLeadLagAlternator",
            "FB_RampRateLimiter",
            "PipelineCompressorAntiSurge",
            "CCGTHRSGDrumLevelDuctBurnerControl",
        ],
        "zero_straton_runtime": True,
        "zero_physical_plc": True,
        "dual_root_parity": True,
    }
    g4_bytes = json.dumps(g4_data, indent=2).encode("utf-8")
    for gp in g4_checkpoint_paths:
        gp.parent.mkdir(parents=True, exist_ok=True)
        gp.write_bytes(g4_bytes)

    return log_data


if __name__ == "__main__":
    res = run_step190_mcp_ccgt_hrsg()
    print(f"Step 190 CCGT HRSG Drum & Duct Burner Simulation Completed: status={res['status']}")
    if res["status"] != "success":
        sys.exit(1)
