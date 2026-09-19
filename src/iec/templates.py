"""IEC 61131-3 Structured Text Templates for Horner Cscape.

Contains standardized, industrial-grade Structured Text templates:
- motor_starter: Motor start/stop with safety interlocks, run feedback, and overload trip
- pid_controller: PID algorithm with manual override, anti-reset windup, and clamping
- analog_scaling: 4-20mA / 0-10V raw analog to engineering units with high/low alarms
- traffic_light_fsm: Multi-phase finite state machine sequence
- cyclic_task: Standard Horner Cscape main cyclic program with heartbeat and health monitoring
- conveyor_system: Multi-sensor conveyor cell with jam detection and downstream handshaking
"""

from typing import Any, Dict, List, Optional


TEMPLATES: Dict[str, Dict[str, Any]] = {
    "motor_starter": {
        "id": "motor_starter",
        "name": "Motor Starter with Interlocks",
        "pou_type": "FUNCTION_BLOCK",
        "description": "Industrial motor control with Start/Stop pushbuttons, run feedback confirmation, thermal overload trip, and fault reset.",
        "code": """FUNCTION_BLOCK FB_MotorStarter
VAR_INPUT
    StartCmd : BOOL;        (* Operator Start Pushbutton (NO) *)
    StopCmd : BOOL;         (* Operator Stop Pushbutton (NC) *)
    SafetyInterlock : BOOL; (* Emergency stop / Safety guard ok *)
    OverloadTrip : BOOL;    (* Thermal overload trip input (NC) *)
    RunFeedback : BOOL;     (* Contactor auxiliary feedback *)
    ResetCmd : BOOL;        (* Fault reset pushbutton *)
END_VAR
VAR_OUTPUT
    MotorRun : BOOL;        (* Output to contactor coil *)
    FaultActive : BOOL;     (* Latched fault status *)
    StatusRun : BOOL;       (* Operating run status *)
END_VAR
VAR
    FeedbackTimeout : INT := 0; (* Feedback monitoring scan counter *)
END_VAR

(* Safety & Overload trip condition *)
IF NOT SafetyInterlock OR OverloadTrip THEN
    MotorRun := FALSE;
    FaultActive := TRUE;
END_IF;

(* Fault reset *)
IF ResetCmd AND NOT OverloadTrip AND SafetyInterlock THEN
    FaultActive := FALSE;
    FeedbackTimeout := 0;
END_IF;

(* Start / Stop control logic *)
IF NOT FaultActive AND SafetyInterlock THEN
    IF StartCmd AND NOT StopCmd THEN
        MotorRun := TRUE;
    ELSIF StopCmd THEN
        MotorRun := FALSE;
    END_IF;
END_IF;

(* Feedback verification *)
IF MotorRun AND NOT RunFeedback THEN
    FeedbackTimeout := FeedbackTimeout + 1;
    IF FeedbackTimeout > 50 THEN
        MotorRun := FALSE;
        FaultActive := TRUE;
    END_IF;
ELSE
    FeedbackTimeout := 0;
END_IF;

StatusRun := MotorRun AND RunFeedback;
END_FUNCTION_BLOCK
""",
    },

    "pid_controller": {
        "id": "pid_controller",
        "name": "PID Closed Loop Controller",
        "pou_type": "FUNCTION_BLOCK",
        "description": "Proportional-Integral-Derivative algorithm with manual override, anti-reset windup, and output clamping.",
        "code": """FUNCTION_BLOCK FB_PIDController
VAR_INPUT
    Setpoint : REAL;        (* Target process setpoint *)
    ProcessVariable : REAL; (* Current feedback measurement *)
    ManualMode : BOOL;      (* TRUE = Manual override, FALSE = Auto *)
    ManualOutput : REAL;    (* Manual output percentage (0.0 - 100.0) *)
    Kp : REAL := 2.0;       (* Proportional gain *)
    Ki : REAL := 0.5;       (* Integral gain *)
    Kd : REAL := 0.1;       (* Derivative gain *)
    OutMin : REAL := 0.0;   (* Minimum output limit *)
    OutMax : REAL := 100.0; (* Maximum output limit *)
END_VAR
VAR_OUTPUT
    ControlOutput : REAL;   (* Calculated control action (0.0 - 100.0) *)
    Error : REAL;           (* Current error (SP - PV) *)
END_VAR
VAR
    LastError : REAL := 0.0;
    IntegralSum : REAL := 0.0;
    DerivTerm : REAL := 0.0;
    P_Term : REAL := 0.0;
    I_Term : REAL := 0.0;
    RawOutput : REAL := 0.0;
END_VAR

IF ManualMode THEN
    ControlOutput := ManualOutput;
    IntegralSum := ManualOutput;
    LastError := 0.0;
ELSE
    (* Calculate error *)
    Error := Setpoint - ProcessVariable;

    (* Proportional term *)
    P_Term := Kp * Error;

    (* Integral term with anti-windup clamping *)
    IntegralSum := IntegralSum + (Ki * Error);
    IF IntegralSum > OutMax THEN
        IntegralSum := OutMax;
    ELSIF IntegralSum < OutMin THEN
        IntegralSum := OutMin;
    END_IF;
    I_Term := IntegralSum;

    (* Derivative term *)
    DerivTerm := Kd * (Error - LastError);
    LastError := Error;

    (* Total output *)
    RawOutput := P_Term + I_Term + DerivTerm;

    (* Clamp output to limits *)
    IF RawOutput > OutMax THEN
        ControlOutput := OutMax;
    ELSIF RawOutput < OutMin THEN
        ControlOutput := OutMin;
    ELSE
        ControlOutput := RawOutput;
    END_IF;
END_IF;
END_FUNCTION_BLOCK
""",
    },

    "analog_scaling": {
        "id": "analog_scaling",
        "name": "Analog Scaling & Alarm Monitoring",
        "pou_type": "FUNCTION_BLOCK",
        "description": "Linear scaling of raw ADC values (0-32767) to engineering units with high/low limit alarms.",
        "code": """FUNCTION_BLOCK FB_AnalogScaling
VAR_INPUT
    RawInput : INT;          (* Raw analog input from hardware (0 - 32767) *)
    RawMin : REAL := 0.0;    (* Raw low count *)
    RawMax : REAL := 32767.0;(* Raw high count *)
    EUMin : REAL := 0.0;     (* Engineering unit low (e.g. 0.0 PSI) *)
    EUMax : REAL := 100.0;   (* Engineering unit high (e.g. 100.0 PSI) *)
    HighAlarmLimit : REAL := 90.0;
    LowAlarmLimit : REAL := 10.0;
END_VAR
VAR_OUTPUT
    ScaledValue : REAL;      (* Process variable in engineering units *)
    HighAlarm : BOOL;        (* High alarm active flag *)
    LowAlarm : BOOL;         (* Low alarm active flag *)
    SensorFault : BOOL;      (* Out of range signal wire break check *)
END_VAR
VAR
    RawReal : REAL;
    SpanRaw : REAL;
    SpanEU : REAL;
END_VAR

RawReal := INT_TO_REAL(RawInput);
SpanRaw := RawMax - RawMin;
SpanEU := EUMax - EUMin;

(* Range fault detection *)
IF RawReal < (RawMin - 1000.0) OR RawReal > (RawMax + 1000.0) THEN
    SensorFault := TRUE;
ELSE
    SensorFault := FALSE;
END_IF;

(* Linear interpolation *)
IF SpanRaw <> 0.0 THEN
    ScaledValue := EUMin + ((RawReal - RawMin) / SpanRaw) * SpanEU;
ELSE
    ScaledValue := EUMin;
END_IF;

(* Alarm monitoring *)
IF ScaledValue >= HighAlarmLimit THEN
    HighAlarm := TRUE;
ELSE
    HighAlarm := FALSE;
END_IF;

IF ScaledValue <= LowAlarmLimit THEN
    LowAlarm := TRUE;
ELSE
    LowAlarm := FALSE;
END_IF;
END_FUNCTION_BLOCK
""",
    },

    "traffic_light_fsm": {
        "id": "traffic_light_fsm",
        "name": "Traffic Light Sequencer FSM",
        "pou_type": "PROGRAM",
        "description": "Finite State Machine (FSM) controlling 4-phase traffic sequence using CASE statement.",
        "code": """PROGRAM PRG_TrafficLightFSM
VAR_INPUT
    Enable : BOOL := TRUE;
    TickTimer : BOOL;
END_VAR
VAR_OUTPUT
    RedLamp : BOOL;
    YellowLamp : BOOL;
    GreenLamp : BOOL;
    CurrentState : INT := 0;
END_VAR
VAR
    StateTimer : INT := 0;
END_VAR

IF NOT Enable THEN
    RedLamp := TRUE;
    YellowLamp := FALSE;
    GreenLamp := FALSE;
    CurrentState := 0;
    StateTimer := 0;
ELSE
    StateTimer := StateTimer + 1;

    CASE CurrentState OF
        0: (* RED state: hold for 30 cycles *)
            RedLamp := TRUE;
            YellowLamp := FALSE;
            GreenLamp := FALSE;
            IF StateTimer >= 30 THEN
                CurrentState := 1;
                StateTimer := 0;
            END_IF;

        1: (* GREEN state: hold for 25 cycles *)
            RedLamp := FALSE;
            YellowLamp := FALSE;
            GreenLamp := TRUE;
            IF StateTimer >= 25 THEN
                CurrentState := 2;
                StateTimer := 0;
            END_IF;

        2: (* YELLOW state: hold for 5 cycles *)
            RedLamp := FALSE;
            YellowLamp := TRUE;
            GreenLamp := FALSE;
            IF StateTimer >= 5 THEN
                CurrentState := 0;
                StateTimer := 0;
            END_IF;

        ELSE
            CurrentState := 0;
            StateTimer := 0;
    END_CASE;
END_IF;
END_PROGRAM
""",
    },

    "cyclic_task": {
        "id": "cyclic_task",
        "name": "Standard Cyclic Main Task",
        "pou_type": "PROGRAM",
        "description": "Standard Horner Cscape cyclic execution task with heartbeat toggle, scan counter, and system diagnostic tracking.",
        "code": """PROGRAM PRG_MainCyclic
VAR_INPUT
    SystemEnable : BOOL := TRUE;
    ResetAlarms : BOOL := FALSE;
END_VAR
VAR_OUTPUT
    HeartbeatLED : BOOL := FALSE;
    ScanCount : DINT := 0;
    SystemHealthy : BOOL := TRUE;
END_VAR
VAR
    HeartbeatCounter : INT := 0;
END_VAR

ScanCount := ScanCount + 1;

(* Heartbeat toggle every 50 scan cycles *)
HeartbeatCounter := HeartbeatCounter + 1;
IF HeartbeatCounter >= 50 THEN
    HeartbeatLED := NOT HeartbeatLED;
    HeartbeatCounter := 0;
END_IF;

(* Diagnostic health rollup *)
IF SystemEnable THEN
    SystemHealthy := TRUE;
ELSE
    SystemHealthy := FALSE;
END_IF;
END_PROGRAM
""",
    },

    "conveyor_system": {
        "id": "conveyor_system",
        "name": "Conveyor Zone Control with Jam Detection",
        "pou_type": "FUNCTION_BLOCK",
        "description": "Automated conveyor segment with entry and exit photo-eyes, upstream request, jam timer, and downstream handover.",
        "code": """FUNCTION_BLOCK FB_ConveyorZone
VAR_INPUT
    StartCmd : BOOL;
    StopCmd : BOOL;
    PhotoEyeEntry : BOOL;
    PhotoEyeExit : BOOL;
    DownstreamReady : BOOL;
    EmergencyStop : BOOL;
END_VAR
VAR_OUTPUT
    MotorForward : BOOL;
    ZoneOccupied : BOOL;
    JamAlarm : BOOL;
    UpstreamReady : BOOL;
END_VAR
VAR
    JamCounter : INT := 0;
    AutoRun : BOOL := FALSE;
END_VAR

IF NOT EmergencyStop THEN
    MotorForward := FALSE;
    AutoRun := FALSE;
    JamAlarm := FALSE;
    UpstreamReady := FALSE;
    RETURN;
END_IF;

IF StartCmd THEN
    AutoRun := TRUE;
ELSIF StopCmd THEN
    AutoRun := FALSE;
END_IF;

ZoneOccupied := PhotoEyeEntry OR PhotoEyeExit;
UpstreamReady := AutoRun AND NOT ZoneOccupied AND NOT JamAlarm;

IF AutoRun AND NOT JamAlarm THEN
    IF ZoneOccupied AND DownstreamReady THEN
        MotorForward := TRUE;
    ELSIF NOT ZoneOccupied THEN
        MotorForward := FALSE;
    END_IF;
ELSE
    MotorForward := FALSE;
END_IF;

(* Jam detection when exit sensor blocked continuously *)
IF MotorForward AND PhotoEyeExit THEN
    JamCounter := JamCounter + 1;
    IF JamCounter > 100 THEN
        JamAlarm := TRUE;
        MotorForward := FALSE;
    END_IF;
ELSE
    JamCounter := 0;
END_IF;
END_FUNCTION_BLOCK
""",
    },

    "modbus_scale_quality": {
        "id": "modbus_scale_quality",
        "name": "Modbus Register Scaling & Telemetry Quality Gating",
        "pou_type": "FUNCTION_BLOCK",
        "description": "Pure IEC 61131-3 Function Block bridging raw Modbus RTU telemetry (0..32000 counts) to engineering units with communication watchdog fault gating, stale quality indicator, underflow/overflow bounds checking, and fail-safe clamp fallback.",
        "code": """FUNCTION_BLOCK FB_ModbusScaleQuality
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
""",
    },
}


def get_template_catalog() -> List[Dict[str, Any]]:
    """Returns metadata for all available templates."""
    catalog = []
    for tid, info in TEMPLATES.items():
        catalog.append({
            "id": tid,
            "name": info["name"],
            "pou_type": info["pou_type"],
            "description": info["description"],
        })
    return catalog


def get_template(template_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves a template by its ID."""
    return TEMPLATES.get(template_id.strip().lower())


def get_template_code(template_id: str) -> Optional[str]:
    """Retrieves template code by ID."""
    t = get_template(template_id)
    return t["code"] if t else None
