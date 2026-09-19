"""Pure IEC 61131-3 Modbus Register Scaling & Telemetry Quality Function Block Bridge.

Provides deterministic, offline bridging between raw Modbus RTU telemetry registers
(%AI1..%AI3, 0..32000 counts) and Horner OCS engineering unit variables
(TankLevelPV, InflowRatePV, DischargePressPV) with automated communication health
watchdog gating (%M10..%M15 comm/stale alarms), fail-safe zero clamping, and quality flags.

Strict Operational Invariants:
- Pure IEC 61131-3 Structured Text ONLY (zero ladder logic; ERR_LADDER_FORBIDDEN fail-closed).
- Zero physical PLC download or communication port access.
- 100% offline software simulation and AST validation.
- Classification: TESTED_MOCK [offline/DEV only].
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import logging
from typing import Any, Dict, List, Optional, Tuple, Union

from src.cscape.st_ld_interop import STLadderInteropGuard, LadderConstructRejectedError
from src.iec.validator import IECValidator
from src.iec.parser import Parser

logger = logging.getLogger(__name__)

# Strict taxonomy classification
CLASSIFICATION: str = "TESTED_MOCK [offline/DEV only]"
VERIFICATION_CLASSIFICATION: str = "TESTED_MOCK [offline/DEV only]"

# Canonical IEC 61131-3 Structured Text source for FB_ModbusScaleQuality
FB_MODBUS_SCALE_QUALITY_ST: str = """FUNCTION_BLOCK FB_ModbusScaleQuality
VAR_INPUT
    RawInput : INT;
    RawMin : INT := 0;
    RawMax : INT := 32000;
    EUMin : REAL := 0.0;
    EUMax : REAL := 100.0;
    CommFailure : BOOL := FALSE;
    StaleQuality : BOOL := FALSE;
    FailSafeValue : REAL := 0.0;
END_VAR
VAR_OUTPUT
    ScaledOutput : REAL;
    QualityGood : BOOL;
    AlarmActive : BOOL;
    Underflow : BOOL;
    Overflow : BOOL;
END_VAR
VAR
    RawSpan : REAL;
    EUSpan : REAL;
    Normalized : REAL;
    CalculatedEU : REAL;
END_VAR

(* 1. Out-of-bounds Detection *)
IF RawInput < RawMin THEN
    Underflow := TRUE;
ELSE
    Underflow := FALSE;
END_IF;

IF RawInput > RawMax THEN
    Overflow := TRUE;
ELSE
    Overflow := FALSE;
END_IF;

(* 2. Communication Health & Telemetry Quality Gating *)
IF CommFailure OR StaleQuality THEN
    AlarmActive := TRUE;
    QualityGood := FALSE;
    ScaledOutput := FailSafeValue;
ELSE
    AlarmActive := FALSE;
    QualityGood := TRUE;

    (* 3. Linear Interpolation & Clamping *)
    RawSpan := INT_TO_REAL(RawMax - RawMin);
    EUSpan := EUMax - EUMin;

    IF RawSpan <> 0.0 THEN
        Normalized := INT_TO_REAL(RawInput - RawMin) / RawSpan;
        CalculatedEU := EUMin + (Normalized * EUSpan);
    ELSE
        CalculatedEU := EUMin;
    END_IF;

    IF EUMin <= EUMax THEN
        IF CalculatedEU < EUMin THEN
            ScaledOutput := EUMin;
        ELSIF CalculatedEU > EUMax THEN
            ScaledOutput := EUMax;
        ELSE
            ScaledOutput := CalculatedEU;
        END_IF;
    ELSE
        IF CalculatedEU < EUMax THEN
            ScaledOutput := EUMax;
        ELSIF CalculatedEU > EUMin THEN
            ScaledOutput := EUMin;
        ELSE
            ScaledOutput := CalculatedEU;
        END_IF;
    END_IF;
END_IF;

END_FUNCTION_BLOCK
"""

# Canonical IEC 61131-3 Structured Text source for TankLevelModbusBridge
TANK_LEVEL_MODBUS_BRIDGE_ST: str = """PROGRAM TankLevelModbusBridge
VAR
    (* Raw Modbus Telemetry Inputs *)
    AI_TankLevelRaw AT %AI1 : INT := 0;
    AI_InflowRaw AT %AI2 : INT := 0;
    AI_DischargeRaw AT %AI3 : INT := 0;

    (* Telemetry Health & Communication Flags *)
    M_LevelCommFail AT %M10 : BOOL := FALSE;
    M_LevelStale AT %M11 : BOOL := FALSE;
    M_InflowCommFail AT %M12 : BOOL := FALSE;
    M_InflowStale AT %M13 : BOOL := FALSE;
    M_DischargeCommFail AT %M14 : BOOL := FALSE;
    M_DischargeStale AT %M15 : BOOL := FALSE;

    (* Engineering Unit Scaled Process Outputs *)
    TankLevelPV AT %R101 : REAL := 0.0;
    InflowRatePV AT %R103 : REAL := 0.0;
    DischargePressPV AT %R105 : REAL := 0.0;

    (* Quality & Status Output Flags *)
    LevelQualityGood AT %M21 : BOOL := FALSE;
    LevelAlarmActive AT %M20 : BOOL := FALSE;
    LevelUnderflow AT %M26 : BOOL := FALSE;
    LevelOverflow AT %M27 : BOOL := FALSE;

    InflowQualityGood AT %M23 : BOOL := FALSE;
    InflowAlarmActive AT %M22 : BOOL := FALSE;
    InflowUnderflow AT %M28 : BOOL := FALSE;
    InflowOverflow AT %M29 : BOOL := FALSE;

    DischargeQualityGood AT %M25 : BOOL := FALSE;
    DischargeAlarmActive AT %M24 : BOOL := FALSE;
    DischargeUnderflow AT %M30 : BOOL := FALSE;
    DischargeOverflow AT %M31 : BOOL := FALSE;

    (* Function Block Instances *)
    fbLevelScale : FB_ModbusScaleQuality;
    fbInflowScale : FB_ModbusScaleQuality;
    fbDischargeScale : FB_ModbusScaleQuality;
END_VAR

(* Channel 1: Tank Level PV (0..32000 -> 0.0..100.0 %) *)
fbLevelScale(RawInput := AI_TankLevelRaw, RawMin := 0, RawMax := 32000, EUMin := 0.0, EUMax := 100.0, CommFailure := M_LevelCommFail, StaleQuality := M_LevelStale, FailSafeValue := 0.0);
TankLevelPV := fbLevelScale.ScaledOutput;
LevelQualityGood := fbLevelScale.QualityGood;
LevelAlarmActive := fbLevelScale.AlarmActive;
LevelUnderflow := fbLevelScale.Underflow;
LevelOverflow := fbLevelScale.Overflow;

(* Channel 2: Inflow Rate PV (0..32000 -> 0.0..500.0 L/min) *)
fbInflowScale(RawInput := AI_InflowRaw, RawMin := 0, RawMax := 32000, EUMin := 0.0, EUMax := 500.0, CommFailure := M_InflowCommFail, StaleQuality := M_InflowStale, FailSafeValue := 0.0);
InflowRatePV := fbInflowScale.ScaledOutput;
InflowQualityGood := fbInflowScale.QualityGood;
InflowAlarmActive := fbInflowScale.AlarmActive;
InflowUnderflow := fbInflowScale.Underflow;
InflowOverflow := fbInflowScale.Overflow;

(* Channel 3: Discharge Pressure PV (0..32000 -> 0.0..10.0 bar) *)
fbDischargeScale(RawInput := AI_DischargeRaw, RawMin := 0, RawMax := 32000, EUMin := 0.0, EUMax := 10.0, CommFailure := M_DischargeCommFail, StaleQuality := M_DischargeStale, FailSafeValue := 0.0);
DischargePressPV := fbDischargeScale.ScaledOutput;
DischargeQualityGood := fbDischargeScale.QualityGood;
DischargeAlarmActive := fbDischargeScale.AlarmActive;
DischargeUnderflow := fbDischargeScale.Underflow;
DischargeOverflow := fbDischargeScale.Overflow;

END_PROGRAM
"""


@dataclass
class ModbusScaleQualityChannel:
    """Channel configuration for Modbus register scaling and quality governance."""
    channel_id: str
    name: str
    unit_id: int
    modicon_address: int
    wire_offset: int
    ocs_input_register: str
    ocs_output_register: str
    raw_min: int = 0
    raw_max: int = 32000
    eu_min: float = 0.0
    eu_max: float = 100.0
    engineering_unit: str = "%"
    comm_failure_register: str = "%M10"
    stale_quality_register: str = "%M11"
    alarm_active_register: str = "%M20"
    quality_good_register: str = "%M21"
    underflow_register: str = "%M26"
    overflow_register: str = "%M27"
    fail_safe_value: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "name": self.name,
            "unit_id": self.unit_id,
            "modicon_address": self.modicon_address,
            "wire_offset": self.wire_offset,
            "ocs_input_register": self.ocs_input_register,
            "ocs_output_register": self.ocs_output_register,
            "raw_min": self.raw_min,
            "raw_max": self.raw_max,
            "eu_min": self.eu_min,
            "eu_max": self.eu_max,
            "engineering_unit": self.engineering_unit,
            "comm_failure_register": self.comm_failure_register,
            "stale_quality_register": self.stale_quality_register,
            "alarm_active_register": self.alarm_active_register,
            "quality_good_register": self.quality_good_register,
            "underflow_register": self.underflow_register,
            "overflow_register": self.overflow_register,
            "fail_safe_value": self.fail_safe_value,
        }


def create_default_channels() -> Dict[str, ModbusScaleQualityChannel]:
    """Returns the three canonical Modbus RTU telemetry channels for TankLevel_P5_Dedicated."""
    return {
        "TX01_LEVEL_PV": ModbusScaleQualityChannel(
            channel_id="TX01_LEVEL_PV",
            name="TankLevelPV",
            unit_id=1,
            modicon_address=40001,
            wire_offset=0,
            ocs_input_register="%AI1",
            ocs_output_register="%R101",
            raw_min=0,
            raw_max=32000,
            eu_min=0.0,
            eu_max=100.0,
            engineering_unit="%",
            comm_failure_register="%M10",
            stale_quality_register="%M11",
            alarm_active_register="%M20",
            quality_good_register="%M21",
            underflow_register="%M26",
            overflow_register="%M27",
            fail_safe_value=0.0,
        ),
        "TX02_INFLOW_RATE": ModbusScaleQualityChannel(
            channel_id="TX02_INFLOW_RATE",
            name="InflowRatePV",
            unit_id=2,
            modicon_address=40002,
            wire_offset=1,
            ocs_input_register="%AI2",
            ocs_output_register="%R103",
            raw_min=0,
            raw_max=32000,
            eu_min=0.0,
            eu_max=500.0,
            engineering_unit="L/min",
            comm_failure_register="%M12",
            stale_quality_register="%M13",
            alarm_active_register="%M22",
            quality_good_register="%M23",
            underflow_register="%M28",
            overflow_register="%M29",
            fail_safe_value=0.0,
        ),
        "TX03_DISCHARGE_PRESS": ModbusScaleQualityChannel(
            channel_id="TX03_DISCHARGE_PRESS",
            name="DischargePressPV",
            unit_id=3,
            modicon_address=40003,
            wire_offset=2,
            ocs_input_register="%AI3",
            ocs_output_register="%R105",
            raw_min=0,
            raw_max=32000,
            eu_min=0.0,
            eu_max=10.0,
            engineering_unit="bar",
            comm_failure_register="%M14",
            stale_quality_register="%M15",
            alarm_active_register="%M24",
            quality_good_register="%M25",
            underflow_register="%M30",
            overflow_register="%M31",
            fail_safe_value=0.0,
        ),
    }


class ModbusScaleQualityBridge:
    """Offline deterministic bridge evaluating Modbus register telemetry and IEC FB logic."""

    def __init__(
        self,
        channels: Optional[Dict[str, ModbusScaleQualityChannel]] = None,
    ) -> None:
        self.channels = channels or create_default_channels()

    @staticmethod
    def get_function_block_st() -> str:
        """Returns the pure ST source for FB_ModbusScaleQuality."""
        return FB_MODBUS_SCALE_QUALITY_ST

    @staticmethod
    def get_bridge_program_st() -> str:
        """Returns the pure ST source for TankLevelModbusBridge."""
        return TANK_LEVEL_MODBUS_BRIDGE_ST

    @staticmethod
    def scale_raw_to_eu(
        raw_input: int,
        raw_min: int = 0,
        raw_max: int = 32000,
        eu_min: float = 0.0,
        eu_max: float = 100.0,
        comm_failure: bool = False,
        stale_quality: bool = False,
        fail_safe_value: float = 0.0,
    ) -> Dict[str, Any]:
        """Pure-Python deterministic simulation of FB_ModbusScaleQuality algorithm."""
        # 1. Out-of-bounds detection
        underflow = bool(raw_input < raw_min)
        overflow = bool(raw_input > raw_max)

        # 2. Health & Quality Gating
        alarm_active = bool(comm_failure or stale_quality)
        quality_good = not alarm_active

        if alarm_active:
            scaled_output = float(fail_safe_value)
            raw_span = 0.0
            eu_span = 0.0
            normalized = 0.0
            calculated_eu = 0.0
        else:
            raw_span = float(raw_max - raw_min)
            eu_span = float(eu_max - eu_min)

            if raw_span != 0.0:
                normalized = float(raw_input - raw_min) / raw_span
                calculated_eu = float(eu_min) + (normalized * eu_span)
            else:
                normalized = 0.0
                calculated_eu = float(eu_min)

            # Clamping
            if eu_min <= eu_max:
                if calculated_eu < eu_min:
                    scaled_output = float(eu_min)
                elif calculated_eu > eu_max:
                    scaled_output = float(eu_max)
                else:
                    scaled_output = float(calculated_eu)
            else:
                if calculated_eu < eu_max:
                    scaled_output = float(eu_max)
                elif calculated_eu > eu_min:
                    scaled_output = float(eu_min)
                else:
                    scaled_output = float(calculated_eu)

            scaled_output = round(scaled_output, 6)
            calculated_eu = round(calculated_eu, 6)
            normalized = round(normalized, 6)

        return {
            "raw_input": raw_input,
            "raw_min": raw_min,
            "raw_max": raw_max,
            "eu_min": eu_min,
            "eu_max": eu_max,
            "comm_failure": comm_failure,
            "stale_quality": stale_quality,
            "fail_safe_value": fail_safe_value,
            "scaled_output": scaled_output,
            "quality_good": quality_good,
            "alarm_active": alarm_active,
            "underflow": underflow,
            "overflow": overflow,
            "raw_span": raw_span,
            "eu_span": eu_span,
            "normalized": normalized,
            "calculated_eu": calculated_eu,
        }

    def scale_channel(
        self,
        channel_id: str,
        raw_input: int,
        comm_failure: bool = False,
        stale_quality: bool = False,
    ) -> Dict[str, Any]:
        """Scales a specific channel using its configured parameters."""
        if channel_id not in self.channels:
            raise KeyError(f"Unknown channel '{channel_id}'. Available: {list(self.channels.keys())}")

        ch = self.channels[channel_id]
        res = self.scale_raw_to_eu(
            raw_input=raw_input,
            raw_min=ch.raw_min,
            raw_max=ch.raw_max,
            eu_min=ch.eu_min,
            eu_max=ch.eu_max,
            comm_failure=comm_failure,
            stale_quality=stale_quality,
            fail_safe_value=ch.fail_safe_value,
        )
        res["channel_id"] = ch.channel_id
        res["variable_name"] = ch.name
        res["ocs_input_register"] = ch.ocs_input_register
        res["ocs_output_register"] = ch.ocs_output_register
        res["engineering_unit"] = ch.engineering_unit
        res["comm_failure_register"] = ch.comm_failure_register
        res["stale_quality_register"] = ch.stale_quality_register
        res["alarm_active_register"] = ch.alarm_active_register
        res["quality_good_register"] = ch.quality_good_register
        return res

    def scale_all_channels(
        self,
        raw_inputs: Dict[str, int],
        comm_failures: Optional[Dict[str, bool]] = None,
        stale_qualities: Optional[Dict[str, bool]] = None,
    ) -> Dict[str, Any]:
        """Scales all three Modbus RTU telemetry channels in a single pass."""
        comm_failures = comm_failures or {}
        stale_qualities = stale_qualities or {}

        results: Dict[str, Any] = {}
        for ch_id, ch in self.channels.items():
            raw_val = raw_inputs.get(ch_id, raw_inputs.get(ch.name, raw_inputs.get(ch.ocs_input_register, 0)))
            c_fail = comm_failures.get(ch_id, comm_failures.get(ch.name, False))
            s_qual = stale_qualities.get(ch_id, stale_qualities.get(ch.name, False))
            results[ch_id] = self.scale_channel(ch_id, raw_val, c_fail, s_qual)

        return results

    @classmethod
    def validate_ast(cls, code: Optional[str] = None) -> Dict[str, Any]:
        """Validates pure ST compliance and AST construction for the Function Block."""
        target_code = code or FB_MODBUS_SCALE_QUALITY_ST
        # 1. STLadderInteropGuard check
        STLadderInteropGuard.enforce_st_code(target_code)

        # 2. IECValidator check
        val = IECValidator.validate(target_code)

        # 3. Recursive-descent AST Parser check
        ast = Parser.from_source(target_code).parse()

        return {
            "valid": val.get("valid", False),
            "errors": val.get("errors", []),
            "pou_name": ast.name,
            "statements_count": len(ast.body),
            "variables_count": len(val.get("variables", [])),
            "status": "success" if val.get("valid", False) else "failed",
        }
