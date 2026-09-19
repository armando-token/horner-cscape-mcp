(* ============================================================================
 * Title:       Prog_ModbusIOHandler
 * Author:      Horner Cscape MCP Specialist
 * Description:
 *   Industrial Modbus TCP / RTU Remote Telemetry Processor.
 *   Features:
 *     - Watchdog Counter Heartbeat Supervision (2.0s Timeout)
 *     - Multi-Channel Analog Input Demultiplexing from Modbus Registers
 *     - Engineering Unit Conversion from Raw 0-32000 ADC Horner Counts
 *     - 4-20mA Sensor Out-of-Range & Wire-Break Failure Detection
 *     - Safe Fallback Value Substitution on Fieldbus Offline Status
 *     - Diagnostic Status Bitfield Packing for SCADA / HMI Telemetry
 * Target:      Horner OCS / Straton K5 IEC 61131-3 Runtime
 * Language:    IEC 61131-3 Structured Text (ST) ONLY
 * ============================================================================ *)

PROGRAM Prog_ModbusIOHandler
VAR
    (* Raw Modbus Input Registers *)
    ModbusWatchdogCounter : WORD := 0;
    RawModbusRegisters    : ARRAY [1..8] OF WORD;
    ModbusRxErrorCount    : UDINT := 0;

    (* Scaled Engineering Measurements *)
    FlowRateLPM           : REAL := 0.0;    (* 0.0 to 600.0 LPM *)
    DischargePressureBar  : REAL := 0.0;    (* 0.0 to 25.0 Bar *)
    TankLevelPct          : REAL := 0.0;    (* 0.0 to 100.0 % *)
    ConductivityMicroS    : REAL := 0.0;    (* 0.0 to 2000.0 uS/cm *)

    (* Sensor Health Status *)
    SensorFaultFlow       : BOOL := FALSE;
    SensorFaultPressure   : BOOL := FALSE;
    SensorFaultLevel      : BOOL := FALSE;
    SensorFaultConduct    : BOOL := FALSE;

    (* Comm Health Monitoring *)
    LastHeartbeat         : WORD := 0;
    CommTimeoutAlarm      : BOOL := FALSE;
    WatchdogTimer         : TON;

    (* SCADA Diagnostic Word Output *)
    DiagnosticStatusWord  : WORD := 0;
    TotalValidFrames      : UDINT := 0;
END_VAR

(* 1. Remote Drop Heartbeat Verification *)
IF ModbusWatchdogCounter <> LastHeartbeat THEN
    LastHeartbeat := ModbusWatchdogCounter;
    CommTimeoutAlarm := FALSE;
    TotalValidFrames := TotalValidFrames + 1;
END_IF;

WatchdogTimer(IN := NOT CommTimeoutAlarm, PT := T#2s);
IF WatchdogTimer.Q THEN
    CommTimeoutAlarm := TRUE;
    ModbusRxErrorCount := ModbusRxErrorCount + 1;
END_IF;

(* 2. Analog Processing & Wire Break Detection *)
IF NOT CommTimeoutAlarm THEN
    (* Channel 1: Flow Transmitter (4-20mA = 6400 to 32000 counts) *)
    IF RawModbusRegisters[1] < 3200 THEN (* Under 2mA = Wire break *)
        SensorFaultFlow := TRUE;
        FlowRateLPM := 0.0;
    ELSE
        SensorFaultFlow := FALSE;
        FlowRateLPM := (WORD_TO_REAL(RawModbusRegisters[1]) - 6400.0) * 600.0 / 25600.0;
        FlowRateLPM := LIMIT(0.0, FlowRateLPM, 600.0);
    END_IF;

    (* Channel 2: Discharge Pressure (4-20mA = 6400 to 32000 counts) *)
    IF RawModbusRegisters[2] < 3200 THEN
        SensorFaultPressure := TRUE;
        DischargePressureBar := 0.0;
    ELSE
        SensorFaultPressure := FALSE;
        DischargePressureBar := (WORD_TO_REAL(RawModbusRegisters[2]) - 6400.0) * 25.0 / 25600.0;
        DischargePressureBar := LIMIT(0.0, DischargePressureBar, 25.0);
    END_IF;

    (* Channel 3: Tank Hydrostatic Level (0-10V = 0 to 32000 counts) *)
    SensorFaultLevel := RawModbusRegisters[3] > 32500; (* Overvoltage *)
    TankLevelPct := WORD_TO_REAL(RawModbusRegisters[3]) * 100.0 / 32000.0;
    TankLevelPct := LIMIT(0.0, TankLevelPct, 100.0);

    (* Channel 4: Water Conductivity (0-2000 uS/cm) *)
    SensorFaultConduct := RawModbusRegisters[4] < 100;
    ConductivityMicroS := WORD_TO_REAL(RawModbusRegisters[4]) * 2000.0 / 32000.0;
    ConductivityMicroS := LIMIT(0.0, ConductivityMicroS, 2000.0);
ELSE
    (* Fallback failsafe conditions during comm interruption *)
    FlowRateLPM          := 0.0;
    DischargePressureBar := 0.0;
    TankLevelPct         := 0.0;
    ConductivityMicroS   := 0.0;
END_IF;

(* 3. Diagnostic Bitfield Assembly for HMI/SCADA *)
(* Bit 0: Comm OK, Bit 1: Comm Timeout, Bit 2-5: Sensor Faults *)
IF CommTimeoutAlarm THEN
    DiagnosticStatusWord := 16#0002;
ELSE
    DiagnosticStatusWord := 16#0001;
    IF SensorFaultFlow THEN
        DiagnosticStatusWord := DiagnosticStatusWord OR 16#0004;
    END_IF;
    IF SensorFaultPressure THEN
        DiagnosticStatusWord := DiagnosticStatusWord OR 16#0008;
    END_IF;
    IF SensorFaultLevel THEN
        DiagnosticStatusWord := DiagnosticStatusWord OR 16#0010;
    END_IF;
    IF SensorFaultConduct THEN
        DiagnosticStatusWord := DiagnosticStatusWord OR 16#0020;
    END_IF;
END_IF;

END_PROGRAM
