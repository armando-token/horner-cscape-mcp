"""IEC 61131-3 Structured Text (ST) Generator for Horner Cscape.

Generates standardized, clean, industrial-grade Structured Text POUs:
- PROGRAM, FUNCTION_BLOCK, and FUNCTION generation
- Proper scope groupings (VAR_INPUT, VAR_OUTPUT, VAR_IN_OUT, VAR, VAR_TEMP, VAR_GLOBAL)
- Variable dictionaries in ST format, Straton appli.txt format, CSV, and Markdown tables
- Built-in generators for common industrial automation patterns:
  * Finite State Machines (CASE ... OF)
  * Direct-On-Line / VFD Motor Controllers
  * Closed-Loop Process PID Loops
  * Multi-Stage Recipe Batch Mixers
  * Modbus TCP / RTU Fieldbus IO Handlers
  * Analog Signal Scaling & Alarm Monitors
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional, Sequence, Union

from .st_parser import (
    POUKind,
    STPOU,
    STVariable,
    VarScope,
)


class STGenerator:
    """Generates standardized IEC 61131-3 Structured Text code and variable dictionaries."""

    INDENT = "    "

    # ------------------------------------------------------------------------
    # Variable Declarations Formatting
    # ------------------------------------------------------------------------

    @classmethod
    def format_variable(cls, var: STVariable, indent_level: int = 1) -> str:
        """Formats a single variable declaration line."""
        pad = cls.INDENT * indent_level
        decl = f"{pad}{var.name}"

        if var.address:
            decl += f" AT {var.address}"

        decl += f" : "

        if var.is_array:
            bounds = var.array_bounds or "0..10"
            decl += f"ARRAY [{bounds}] OF {var.data_type}"
        else:
            decl += var.data_type

        if var.initial_value is not None and var.initial_value != "":
            decl += f" := {var.initial_value}"

        decl += ";"

        if var.comment:
            decl += f" (* {var.comment} *)"

        return decl

    @classmethod
    def format_var_block(
        cls,
        scope: Union[VarScope, str],
        variables: Sequence[STVariable],
        is_retain: bool = False,
        is_constant: bool = False,
        indent_level: int = 1,
    ) -> str:
        """Formats an entire VAR...END_VAR block for a given scope."""
        if not variables:
            return ""

        pad = cls.INDENT * indent_level
        scope_str = scope.value if isinstance(scope, VarScope) else str(scope).upper()

        modifiers = []
        if is_retain:
            modifiers.append("RETAIN")
        if is_constant:
            modifiers.append("CONSTANT")

        header = f"{pad}{scope_str}"
        if modifiers:
            header += " " + " ".join(modifiers)

        lines = [header]
        for v in variables:
            lines.append(cls.format_variable(v, indent_level + 1))
        lines.append(f"{pad}END_VAR")

        return "\n".join(lines)

    # ------------------------------------------------------------------------
    # POU Generation
    # ------------------------------------------------------------------------

    @classmethod
    def generate_header_comment(
        cls,
        title: str,
        description: str = "",
        author: str = "Horner Cscape MCP",
    ) -> str:
        """Generates an IEC 61131-3 block header comment."""
        date_str = datetime.date.today().isoformat()
        desc_lines = "\n".join(f" * {line}" for line in description.strip().splitlines()) if description else " * Standard IEC 61131-3 Structured Text POU."
        return (
            f"(* ============================================================================\n"
            f" * Title:       {title}\n"
            f" * Author:      {author}\n"
            f" * Date:        {date_str}\n"
            f" * Description:\n"
            f"{desc_lines}\n"
            f" * Target:      Horner OCS / Straton K5 IEC 61131-3 Runtime\n"
            f" * Language:    IEC 61131-3 Structured Text (ST) ONLY\n"
            f" * ============================================================================ *)\n"
        )

    @classmethod
    def generate_pou(cls, pou: STPOU) -> str:
        """Generates full Structured Text for an STPOU AST node."""
        parts: List[str] = []

        # Header comment
        parts.append(cls.generate_header_comment(pou.name, pou.description))

        # POU Declaration Line
        if pou.kind == POUKind.FUNCTION:
            ret = pou.return_type or "BOOL"
            parts.append(f"FUNCTION {pou.name} : {ret}")
        else:
            parts.append(f"{pou.kind.value} {pou.name}")

        # Group variables by scope
        scope_order = [
            VarScope.VAR_INPUT,
            VarScope.VAR_OUTPUT,
            VarScope.VAR_IN_OUT,
            VarScope.VAR_EXTERNAL,
            VarScope.VAR,
            VarScope.VAR_TEMP,
        ]

        # Separate retain / regular
        for scope in scope_order:
            scope_vars = pou.get_variables_by_scope(scope)
            if not scope_vars:
                continue

            regular_vars = [v for v in scope_vars if not v.is_retain and not v.is_constant]
            retain_vars = [v for v in scope_vars if v.is_retain and not v.is_constant]
            const_vars = [v for v in scope_vars if v.is_constant]

            if regular_vars:
                parts.append(cls.format_var_block(scope, regular_vars, is_retain=False, indent_level=1))
            if retain_vars:
                parts.append(cls.format_var_block(scope, retain_vars, is_retain=True, indent_level=1))
            if const_vars:
                parts.append(cls.format_var_block(scope, const_vars, is_constant=True, indent_level=1))

        parts.append("")

        # Body logic
        if pou.body.strip():
            # Indent body if not indented
            body_lines = []
            for line in pou.body.splitlines():
                body_lines.append(f"{cls.INDENT}{line}" if line.strip() and not line.startswith(cls.INDENT) else line)
            parts.append("\n".join(body_lines))
        else:
            parts.append(f"{cls.INDENT}; (* Empty statement *)")

        parts.append("")
        parts.append(f"END_{pou.kind.value}\n")

        return "\n".join(parts)

    @classmethod
    def generate_program(
        cls,
        name: str,
        variables: Sequence[STVariable],
        body_lines: Sequence[str],
        description: str = "",
    ) -> str:
        """Helper to create a PROGRAM POU."""
        pou = STPOU(
            kind=POUKind.PROGRAM,
            name=name,
            variables=list(variables),
            body="\n".join(body_lines),
            description=description,
        )
        return cls.generate_pou(pou)

    @classmethod
    def generate_function_block(
        cls,
        name: str,
        inputs: Sequence[STVariable],
        outputs: Sequence[STVariable],
        locals_: Sequence[STVariable],
        body_lines: Sequence[str],
        in_outs: Sequence[STVariable] = (),
        description: str = "",
    ) -> str:
        """Helper to create a FUNCTION_BLOCK POU."""
        all_vars: List[STVariable] = []
        for v in inputs:
            v.scope = VarScope.VAR_INPUT
            all_vars.append(v)
        for v in outputs:
            v.scope = VarScope.VAR_OUTPUT
            all_vars.append(v)
        for v in in_outs:
            v.scope = VarScope.VAR_IN_OUT
            all_vars.append(v)
        for v in locals_:
            v.scope = VarScope.VAR
            all_vars.append(v)

        pou = STPOU(
            kind=POUKind.FUNCTION_BLOCK,
            name=name,
            variables=all_vars,
            body="\n".join(body_lines),
            description=description,
        )
        return cls.generate_pou(pou)

    @classmethod
    def generate_function(
        cls,
        name: str,
        return_type: str,
        inputs: Sequence[STVariable],
        locals_: Sequence[STVariable],
        body_lines: Sequence[str],
        description: str = "",
    ) -> str:
        """Helper to create a FUNCTION POU."""
        all_vars: List[STVariable] = []
        for v in inputs:
            v.scope = VarScope.VAR_INPUT
            all_vars.append(v)
        for v in locals_:
            v.scope = VarScope.VAR
            all_vars.append(v)

        pou = STPOU(
            kind=POUKind.FUNCTION,
            name=name,
            return_type=return_type,
            variables=all_vars,
            body="\n".join(body_lines),
            description=description,
        )
        return cls.generate_pou(pou)

    # ------------------------------------------------------------------------
    # Variable Dictionaries (ST, Straton appli.txt, Markdown, CSV)
    # ------------------------------------------------------------------------

    @classmethod
    def generate_appli_txt(
        cls,
        project_name: str,
        variables: Sequence[STVariable],
        description: str = "",
    ) -> str:
        """Generates the Straton K5 appli.txt variable and project dictionary file."""
        lines = [
            "",
            "",
            "[long]",
            f"A-<PROJECT>={description or project_name}",
        ]

        # In Straton appli.txt, variable descriptions and properties are stored
        for v in variables:
            desc = v.comment or f"Variable {v.name}"
            lines.append(f"V-{v.name}={desc}")

        lines.append("")
        lines.append("[variables]")
        for v in variables:
            # Format: Name:TYPE[:=init][@addr]
            type_decl = v.data_type
            if v.is_array:
                type_decl = f"ARRAY[{v.array_bounds or '0..10'}] OF {v.data_type}"
            entry = f"{v.name}:{type_decl}"
            if v.initial_value is not None:
                entry += f":={v.initial_value}"
            if v.address:
                entry += f"@{v.address}"
            if v.is_retain:
                entry += ":RETAIN"
            lines.append(entry)

        lines.append("")
        return "\n".join(lines)

    @classmethod
    def generate_markdown_dictionary(
        cls,
        variables: Sequence[STVariable],
        title: str = "Variable Dictionary",
    ) -> str:
        """Generates a GitHub-flavored markdown table documenting variables."""
        lines = [
            f"### {title}",
            "",
            "| Variable Name | Scope | Data Type | Initial Value | Address | Description |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for v in variables:
            init_val = f"`{v.initial_value}`" if v.initial_value is not None else "-"
            addr = f"`{v.address}`" if v.address else "-"
            scope_val = v.scope.value if isinstance(v.scope, VarScope) else str(v.scope)
            comment = v.comment or "-"
            lines.append(f"| **{v.name}** | `{scope_val}` | `{v.data_type}` | {init_val} | {addr} | {comment} |")
        lines.append("")
        return "\n".join(lines)

    @classmethod
    def generate_csv_dictionary(cls, variables: Sequence[STVariable]) -> str:
        """Generates a CSV export of variables."""
        lines = ["Name,Scope,DataType,InitialValue,Address,IsRetain,Comment"]
        for v in variables:
            scope_val = v.scope.value if isinstance(v.scope, VarScope) else str(v.scope)
            init_val = v.initial_value or ""
            addr = v.address or ""
            comment = (v.comment or "").replace('"', '""')
            lines.append(f'"{v.name}","{scope_val}","{v.data_type}","{init_val}","{addr}",{v.is_retain},"{comment}"')
        return "\n".join(lines)

    # ------------------------------------------------------------------------
    # Industrial Pattern Generators
    # ------------------------------------------------------------------------

    @classmethod
    def generate_state_machine(
        cls,
        name: str,
        states: Sequence[str],
        initial_state: str = "",
        description: str = "",
    ) -> str:
        """Generates an industrial finite state machine with entry actions, timeout supervision, and fault handling."""
        state_list = list(states)
        if not state_list:
            state_list = ["IDLE", "RUNNING", "STOPPING", "FAULT"]

        init_st = initial_state if initial_state in state_list else state_list[0]

        vars_: List[STVariable] = [
            STVariable(name="CurrentState", data_type="INT", initial_value="0", comment="Current active state ID"),
            STVariable(name="PreviousState", data_type="INT", initial_value="-1", comment="Previous cycle state ID"),
            STVariable(name="StateStepTimer", data_type="TIME", initial_value="T#0s", comment="Time spent in current state"),
            STVariable(name="StateTimeoutLimit", data_type="TIME", initial_value="T#30s", comment="Maximum duration allowed per state"),
            STVariable(name="StateFault", data_type="BOOL", initial_value="FALSE", comment="State machine watchdog timeout fault"),
            STVariable(name="ResetCmd", data_type="BOOL", initial_value="FALSE", comment="Operator fault reset command"),
            STVariable(name="TON_StateTimeout", data_type="TON", comment="IEC 61131-3 On-delay watchdog timer"),
        ]

        body: List[str] = [
            "(* Detect state transition *)",
            "IF CurrentState <> PreviousState THEN",
            "    PreviousState := CurrentState;",
            "    StateFault := FALSE;",
            "END_IF;",
            "",
            "(* State timeout watchdog supervision *)",
            "TON_StateTimeout(IN := (CurrentState <> 0 AND CurrentState <> 99), PT := StateTimeoutLimit);",
            "IF TON_StateTimeout.Q THEN",
            "    StateFault := TRUE;",
            "    CurrentState := 99; (* Transition to FAULT state *)",
            "END_IF;",
            "",
            "(* Fault reset override *)",
            "IF ResetCmd AND CurrentState = 99 THEN",
            "    CurrentState := 0; (* Return to IDLE *)",
            "    StateFault := FALSE;",
            "END_IF;",
            "",
            "(* Main Sequencer CASE *)",
            "CASE CurrentState OF",
        ]

        for idx, st_name in enumerate(state_list):
            num = idx * 10
            body.append(f"    {num}: (* State: {st_name} *)")
            body.append(f"        ; (* Execute actions for {st_name} *)")
            if idx < len(state_list) - 1:
                next_num = (idx + 1) * 10
                body.append(f"        (* To advance: CurrentState := {next_num}; *)")
            body.append("")

        body.extend([
            "    99: (* FAULT State *)",
            "        ; (* Safe shutdown actions *)",
            "        IF ResetCmd THEN",
            "            CurrentState := 0;",
            "        END_IF;",
            "",
            "    ELSE",
            "        CurrentState := 0; (* Fallback safe state *)",
            "END_CASE;",
        ])

        return cls.generate_program(
            name=name,
            variables=vars_,
            body_lines=body,
            description=description or f"Industrial Finite State Machine ({', '.join(state_list)})",
        )

    @classmethod
    def generate_motor_controller(cls, name: str = "FB_MotorController") -> str:
        """Generates a complete industrial motor starter / VFD controller function block."""
        inputs = [
            STVariable("StartCmd", "BOOL", VarScope.VAR_INPUT, comment="Operator Start pushbutton (NO)"),
            STVariable("StopCmd", "BOOL", VarScope.VAR_INPUT, comment="Operator Stop pushbutton (NC)"),
            STVariable("SafetyInterlock", "BOOL", VarScope.VAR_INPUT, comment="Safety circuit / E-Stop healthy"),
            STVariable("OverloadTrip", "BOOL", VarScope.VAR_INPUT, comment="Thermal overload relay trip (NC)"),
            STVariable("RunFeedback", "BOOL", VarScope.VAR_INPUT, comment="Contactor auxiliary run contact"),
            STVariable("ResetCmd", "BOOL", VarScope.VAR_INPUT, comment="Fault reset pushbutton"),
            STVariable("SpeedSetpoint", "REAL", VarScope.VAR_INPUT, "0.0", comment="VFD speed reference (0.0 to 100.0 %)"),
        ]
        outputs = [
            STVariable("MotorRun", "BOOL", VarScope.VAR_OUTPUT, "FALSE", comment="Contactor command output"),
            STVariable("SpeedRefOut", "REAL", VarScope.VAR_OUTPUT, "0.0", comment="Scaled analog speed output (0-100%)"),
            STVariable("FaultActive", "BOOL", VarScope.VAR_OUTPUT, "FALSE", comment="Latched trip / fault alarm"),
            STVariable("StatusRunning", "BOOL", VarScope.VAR_OUTPUT, "FALSE", comment="Verified motor running status"),
            STVariable("RunHours", "UDINT", VarScope.VAR_OUTPUT, "0", comment="Accumulated motor runtime in hours", is_retain=True),
        ]
        locals_ = [
            STVariable("FeedbackTimer", "TON", VarScope.VAR, comment="Run feedback verification timer"),
            STVariable("RunHourTimer", "TON", VarScope.VAR, comment="1-second accumulator timer"),
            STVariable("SecondCount", "UDINT", VarScope.VAR, "0", is_retain=True),
        ]

        body = [
            "(* 1. Safety interlock and thermal trip check *)",
            "IF NOT SafetyInterlock OR OverloadTrip THEN",
            "    MotorRun := FALSE;",
            "    FaultActive := TRUE;",
            "    SpeedRefOut := 0.0;",
            "END_IF;",
            "",
            "(* 2. Fault reset logic *)",
            "IF ResetCmd AND NOT OverloadTrip AND SafetyInterlock THEN",
            "    FaultActive := FALSE;",
            "END_IF;",
            "",
            "(* 3. Start / Stop command evaluation *)",
            "IF NOT FaultActive AND SafetyInterlock THEN",
            "    IF StartCmd AND NOT StopCmd THEN",
            "        MotorRun := TRUE;",
            "        SpeedRefOut := SpeedSetpoint;",
            "    ELSIF StopCmd THEN",
            "        MotorRun := FALSE;",
            "        SpeedRefOut := 0.0;",
            "    END_IF;",
            "END_IF;",
            "",
            "(* 4. Feedback confirmation with 3.0s timeout *)",
            "FeedbackTimer(IN := MotorRun, PT := T#3s);",
            "IF FeedbackTimer.Q AND NOT RunFeedback THEN",
            "    MotorRun := FALSE;",
            "    FaultActive := TRUE;",
            "    SpeedRefOut := 0.0;",
            "END_IF;",
            "",
            "StatusRunning := MotorRun AND RunFeedback;",
            "",
            "(* 5. Runtime hour accumulation *)",
            "RunHourTimer(IN := StatusRunning AND NOT RunHourTimer.Q, PT := T#1s);",
            "IF RunHourTimer.Q THEN",
            "    SecondCount := SecondCount + 1;",
            "    IF SecondCount >= 3600 THEN",
            "        RunHours := RunHours + 1;",
            "        SecondCount := 0;",
            "    END_IF;",
            "END_IF;",
        ]

        return cls.generate_function_block(
            name=name,
            inputs=inputs,
            outputs=outputs,
            locals_=locals_,
            body_lines=body,
            description="Industrial DOL/VFD Motor Controller with Safety Interlocks, Feedback Debounce, and Runtime Tracking",
        )

    @classmethod
    def generate_pid_controller(cls, name: str = "FB_TemperaturePID") -> str:
        """Generates a closed loop PID controller with anti-reset windup and PWM output."""
        inputs = [
            STVariable("Setpoint", "REAL", VarScope.VAR_INPUT, "100.0", comment="Target process temperature in Deg C"),
            STVariable("ProcessVariable", "REAL", VarScope.VAR_INPUT, "20.0", comment="Thermocouple / RTD temperature reading"),
            STVariable("ManualMode", "BOOL", VarScope.VAR_INPUT, "FALSE", comment="TRUE: Manual control, FALSE: Auto PID"),
            STVariable("ManualOutput", "REAL", VarScope.VAR_INPUT, "0.0", comment="Manual output % (0.0 to 100.0)"),
            STVariable("Kp", "REAL", VarScope.VAR_INPUT, "2.5", comment="Proportional gain"),
            STVariable("Ki", "REAL", VarScope.VAR_INPUT, "0.05", comment="Integral gain (1/sec)"),
            STVariable("Kd", "REAL", VarScope.VAR_INPUT, "0.20", comment="Derivative gain (sec)"),
            STVariable("CycleTimeSec", "REAL", VarScope.VAR_INPUT, "0.1", comment="Scan cycle time in seconds"),
        ]
        outputs = [
            STVariable("ControlOutput", "REAL", VarScope.VAR_OUTPUT, "0.0", comment="Calculated PID control effort 0-100%"),
            STVariable("PWM_HeaterOut", "BOOL", VarScope.VAR_OUTPUT, "FALSE", comment="Time-proportional PWM heater contactor output"),
            STVariable("Error", "REAL", VarScope.VAR_OUTPUT, "0.0", comment="Current regulation error (SP - PV)"),
            STVariable("HighAlarm", "BOOL", VarScope.VAR_OUTPUT, "FALSE", comment="Process high temperature alarm"),
            STVariable("LowAlarm", "BOOL", VarScope.VAR_OUTPUT, "FALSE", comment="Process low temperature alarm"),
        ]
        locals_ = [
            STVariable("LastError", "REAL", VarScope.VAR, "0.0"),
            STVariable("IntegralSum", "REAL", VarScope.VAR, "0.0"),
            STVariable("DerivTerm", "REAL", VarScope.VAR, "0.0"),
            STVariable("PropTerm", "REAL", VarScope.VAR, "0.0"),
            STVariable("RawOutput", "REAL", VarScope.VAR, "0.0"),
            STVariable("PwmAcc", "REAL", VarScope.VAR, "0.0"),
        ]

        body = [
            "(* 1. Calculate Error *)",
            "Error := Setpoint - ProcessVariable;",
            "",
            "(* 2. Alarm Evaluation *)",
            "HighAlarm := ProcessVariable >= (Setpoint + 15.0);",
            "LowAlarm := ProcessVariable <= (Setpoint - 15.0);",
            "",
            "(* 3. Auto / Manual Operation *)",
            "IF ManualMode THEN",
            "    ControlOutput := LIMIT(0.0, ManualOutput, 100.0);",
            "    IntegralSum := ControlOutput; (* Bumpless transfer *)",
            "    LastError := Error;",
            "ELSE",
            "    (* Proportional Term *)",
            "    PropTerm := Kp * Error;",
            "",
            "    (* Integral Term with Anti-Reset Windup *)",
            "    IntegralSum := IntegralSum + (Ki * Error * CycleTimeSec);",
            "    IntegralSum := LIMIT(0.0, IntegralSum, 100.0);",
            "",
            "    (* Derivative Term *)",
            "    DerivTerm := Kd * (Error - LastError) / CycleTimeSec;",
            "    LastError := Error;",
            "",
            "    (* Sum and Clamp to 0.0 - 100.0 % *)",
            "    RawOutput := PropTerm + IntegralSum + DerivTerm;",
            "    ControlOutput := LIMIT(0.0, RawOutput, 100.0);",
            "END_IF;",
            "",
            "(* 4. Time-Proportional PWM output (10-second base cycle) *)",
            "PwmAcc := PwmAcc + (CycleTimeSec / 10.0 * 100.0);",
            "IF PwmAcc >= 100.0 THEN",
            "    PwmAcc := 0.0;",
            "END_IF;",
            "PWM_HeaterOut := PwmAcc < ControlOutput;",
        ]

        return cls.generate_function_block(
            name=name,
            inputs=inputs,
            outputs=outputs,
            locals_=locals_,
            body_lines=body,
            description="Process Temperature PID Loop with Anti-Windup, Auto/Manual, and PWM Output",
        )

    @classmethod
    def generate_batch_mixer(cls, name: str = "Prog_BatchMixer") -> str:
        """Generates a multi-step recipe batch mixing sequence program."""
        vars_ = [
            # Inputs
            STVariable("StartBatch", "BOOL", VarScope.VAR, "FALSE", comment="Start batch sequence command"),
            STVariable("AbortBatch", "BOOL", VarScope.VAR, "FALSE", comment="Emergency abort batch sequence"),
            STVariable("LiquidWeightKg", "REAL", VarScope.VAR, "0.0", address="%AI1", comment="Vessel load cell gross weight"),
            STVariable("BatchTempC", "REAL", VarScope.VAR, "25.0", address="%AI2", comment="Batch temperature sensor"),
            # Recipe parameters
            STVariable("TargetWaterKg", "REAL", VarScope.VAR, "500.0", comment="Target recipe water charge"),
            STVariable("TargetSyrupKg", "REAL", VarScope.VAR, "150.0", comment="Target recipe syrup charge"),
            STVariable("MixTimeSetting", "TIME", VarScope.VAR, "T#2m", comment="Agitation duration"),
            STVariable("TargetTempC", "REAL", VarScope.VAR, "65.0", comment="Cooking temperature"),
            # Actuator outputs
            STVariable("ValveWaterIn", "BOOL", VarScope.VAR, "FALSE", address="%Q1", comment="Water inlet supply valve"),
            STVariable("ValveSyrupIn", "BOOL", VarScope.VAR, "FALSE", address="%Q2", comment="Syrup inlet supply valve"),
            STVariable("AgitatorLowSpeed", "BOOL", VarScope.VAR, "FALSE", address="%Q3", comment="Mixer agitator low speed contactor"),
            STVariable("AgitatorHighSpeed", "BOOL", VarScope.VAR, "FALSE", address="%Q4", comment="Mixer agitator high speed contactor"),
            STVariable("SteamHeaterValve", "BOOL", VarScope.VAR, "FALSE", address="%Q5", comment="Vessel jacket steam supply valve"),
            STVariable("ValveDischarge", "BOOL", VarScope.VAR, "FALSE", address="%Q6", comment="Bottom vessel drain/transfer valve"),
            # Sequence state
            STVariable("StepIndex", "INT", VarScope.VAR, "0", comment="0=Idle, 10=Water, 20=Syrup, 30=Agitate, 40=Heat, 50=Discharge, 99=Abort"),
            STVariable("BatchComplete", "BOOL", VarScope.VAR, "FALSE", comment="Batch completed pulse flag"),
            STVariable("AgitateTimer", "TON", VarScope.VAR, comment="Agitation stage timer"),
        ]

        body = [
            "(* Emergency abort supervisory check *)",
            "IF AbortBatch THEN",
            "    StepIndex := 99;",
            "END_IF;",
            "",
            "(* Batch Sequencer *)",
            "CASE StepIndex OF",
            "    0: (* IDLE: Awaiting Start Command *)",
            "        ValveWaterIn := FALSE;",
            "        ValveSyrupIn := FALSE;",
            "        AgitatorLowSpeed := FALSE;",
            "        AgitatorHighSpeed := FALSE;",
            "        SteamHeaterValve := FALSE;",
            "        ValveDischarge := FALSE;",
            "        BatchComplete := FALSE;",
            "        IF StartBatch AND NOT AbortBatch THEN",
            "            StepIndex := 10; (* Start Charging Water *)",
            "        END_IF;",
            "",
            "    10: (* CHARGE WATER *)",
            "        ValveWaterIn := TRUE;",
            "        IF LiquidWeightKg >= TargetWaterKg THEN",
            "            ValveWaterIn := FALSE;",
            "            StepIndex := 20; (* Proceed to Syrup *)",
            "        END_IF;",
            "",
            "    20: (* CHARGE SYRUP WITH LOW SPEED AGITATION *)",
            "        ValveSyrupIn := TRUE;",
            "        AgitatorLowSpeed := TRUE;",
            "        IF LiquidWeightKg >= (TargetWaterKg + TargetSyrupKg) THEN",
            "            ValveSyrupIn := FALSE;",
            "            StepIndex := 30; (* Proceed to High Speed Mix *)",
            "        END_IF;",
            "",
            "    30: (* HIGH SPEED BLEND *)",
            "        AgitatorLowSpeed := FALSE;",
            "        AgitatorHighSpeed := TRUE;",
            "        AgitateTimer(IN := TRUE, PT := MixTimeSetting);",
            "        IF AgitateTimer.Q THEN",
            "            AgitateTimer(IN := FALSE);",
            "            StepIndex := 40; (* Proceed to Heating *)",
            "        END_IF;",
            "",
            "    40: (* JACKET HEATING *)",
            "        AgitatorLowSpeed := TRUE;",
            "        AgitatorHighSpeed := FALSE;",
            "        SteamHeaterValve := BatchTempC < TargetTempC;",
            "        IF BatchTempC >= TargetTempC THEN",
            "            SteamHeaterValve := FALSE;",
            "            StepIndex := 50; (* Proceed to Discharge *)",
            "        END_IF;",
            "",
            "    50: (* VESSEL DISCHARGE TO HOLDING TANK *)",
            "        ValveDischarge := TRUE;",
            "        AgitatorLowSpeed := FALSE;",
            "        IF LiquidWeightKg <= 5.0 THEN (* Tank Empty Tare *)",
            "            ValveDischarge := FALSE;",
            "            BatchComplete := TRUE;",
            "            StepIndex := 0; (* Cycle complete *)",
            "        END_IF;",
            "",
            "    99: (* SAFE ABORT SHUTDOWN *)",
            "        ValveWaterIn := FALSE;",
            "        ValveSyrupIn := FALSE;",
            "        AgitatorLowSpeed := FALSE;",
            "        AgitatorHighSpeed := FALSE;",
            "        SteamHeaterValve := FALSE;",
            "        ValveDischarge := FALSE;",
            "        IF NOT AbortBatch THEN",
            "            StepIndex := 0;",
            "        END_IF;",
            "",
            "    ELSE",
            "        StepIndex := 0;",
            "END_CASE;",
        ]

        return cls.generate_program(
            name=name,
            variables=vars_,
            body_lines=body,
            description="Recipe Batch Mixing Controller: Water Charge -> Syrup Feed -> High Speed Mix -> Cook -> Drain",
        )

    @classmethod
    def generate_modbus_io_handler(cls, name: str = "Prog_ModbusIOHandler") -> str:
        """Generates a fieldbus Modbus RTU/TCP telemetry reader and analog converter."""
        vars_ = [
            # Raw hardware registers
            STVariable("RawAnalogRegisters", "WORD", VarScope.VAR, is_array=True, array_bounds="1..8", comment="Raw 16-bit Modbus input registers"),
            STVariable("CommWatchdogReg", "WORD", VarScope.VAR, "0", comment="Remote PLC heartbeat counter"),
            # Scaled telemetry values
            STVariable("FlowRateLPM", "REAL", VarScope.VAR, "0.0", comment="Channel 1 scaled flow (0-500 LPM)"),
            STVariable("HeaderPressureBar", "REAL", VarScope.VAR, "0.0", comment="Channel 2 scaled pressure (0-16 Bar)"),
            STVariable("TankLevelPct", "REAL", VarScope.VAR, "0.0", comment="Channel 3 tank level percentage (0-100 %)"),
            STVariable("TurbidityNTU", "REAL", VarScope.VAR, "0.0", comment="Channel 4 turbidity reading"),
            # Communication health monitoring
            STVariable("LastWatchdogReg", "WORD", VarScope.VAR, "0"),
            STVariable("WatchdogTimer", "TON", VarScope.VAR),
            STVariable("CommFailureAlarm", "BOOL", VarScope.VAR, "FALSE", comment="Remote I/O comm timeout fault"),
            STVariable("ChannelIdx", "INT", VarScope.VAR, "1"),
        ]

        body = [
            "(* 1. Remote Drop Comm Watchdog Verification *)",
            "IF CommWatchdogReg <> LastWatchdogReg THEN",
            "    LastWatchdogReg := CommWatchdogReg;",
            "    CommFailureAlarm := FALSE;",
            "END_IF;",
            "",
            "WatchdogTimer(IN := NOT CommFailureAlarm, PT := T#2s);",
            "IF WatchdogTimer.Q THEN",
            "    CommFailureAlarm := TRUE;",
            "END_IF;",
            "",
            "(* 2. Analog Register Scaling (Standard Horner 0-32000 ADC Count range) *)",
            "IF NOT CommFailureAlarm THEN",
            "    (* Channel 1: Flow meter 0-500 Liters/min *)",
            "    FlowRateLPM := WORD_TO_REAL(RawAnalogRegisters[1]) * 500.0 / 32000.0;",
            "    FlowRateLPM := LIMIT(0.0, FlowRateLPM, 500.0);",
            "",
            "    (* Channel 2: Pressure transmitter 0-16.0 Bar *)",
            "    HeaderPressureBar := WORD_TO_REAL(RawAnalogRegisters[2]) * 16.0 / 32000.0;",
            "    HeaderPressureBar := LIMIT(0.0, HeaderPressureBar, 16.0);",
            "",
            "    (* Channel 3: Hydrostatic Level Transmitter 0-100.0 % *)",
            "    TankLevelPct := WORD_TO_REAL(RawAnalogRegisters[3]) * 100.0 / 32000.0;",
            "    TankLevelPct := LIMIT(0.0, TankLevelPct, 100.0);",
            "",
            "    (* Channel 4: Optical Turbidity 0-100 NTU *)",
            "    TurbidityNTU := WORD_TO_REAL(RawAnalogRegisters[4]) * 100.0 / 32000.0;",
            "    TurbidityNTU := LIMIT(0.0, TurbidityNTU, 100.0);",
            "ELSE",
            "    (* Fallback safe values during fieldbus communication loss *)",
            "    FlowRateLPM := 0.0;",
            "    HeaderPressureBar := 0.0;",
            "    TankLevelPct := 0.0;",
            "    TurbidityNTU := 0.0;",
            "END_IF;",
        ]

        return cls.generate_program(
            name=name,
            variables=vars_,
            body_lines=body,
            description="Modbus Fieldbus Remote I/O Telemetry Processor with Watchdog and Engineering Unit Conversion",
        )
