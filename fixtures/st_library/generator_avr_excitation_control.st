(* ============================================================================
 * Title:       FB_GeneratorAvrExcitationControl
 * Description: Synchronous Generator Excitation & Automatic Voltage Regulator (AVR),
 *              Under-Excitation Limiter (UEL), Over-Excitation Limiter (OEL),
 *              Volts-Per-Hertz (V/Hz) Overfluxing & Loss-of-Field (40) Trip Interlock.
 * IEC 61131-3: Pure Structured Text (ST) Only. Ladder logic strictly rejected.
 * OCS Mapping:
 *   %R137: Generator_Terminal_Voltage_kV (INT: tenths of kV, e.g. 138 = 13.8 kV)
 *   %R138: Generator_Reactive_Power_MVAR (INT: tenths of MVAR, e.g. 150 = 15.0 MVAR)
 *   %R139: Excitation_Field_Current_Amps (INT: tenths of Amps, e.g. 420 = 42.0 A)
 *   %R140: Excitation_Field_Voltage_Volts (INT: Volts DC, e.g. 125 VDC)
 *   %R141: Grid_Bus_Voltage_kV (INT: tenths of kV, e.g. 138 = 13.8 kV)
 *   %R142: Generator_Frequency_Hz (INT: hundredths of Hz, e.g. 6000 = 60.00 Hz)
 *   %Q44:  AVR_Automatic_Mode_Active (BOOL: True = Auto AVR, False = Manual FCR)
 *   %Q45:  Field_Breaker_Close_Command (BOOL: Field contactor/breaker permit)
 *   %Q46:  Under_Excitation_Limiter_Active (BOOL: UEL active)
 *   %Q47:  Over_Excitation_Limiter_Active (BOOL: OEL active)
 *   %M58:  Volts_Per_Hertz_Overfluxing_Trip (BOOL: V/Hz overfluxing trip)
 *   %M59:  Generator_Loss_of_Field_Trip (BOOL: 40 relay loss of field trip)
 *   %M60:  Field_Overcurrent_Trip_Latched (BOOL: Latched field overcurrent)
 * ============================================================================ *)

FUNCTION_BLOCK FB_GeneratorAvrExcitationControl
VAR_INPUT
    Generator_Terminal_Voltage_kV : INT := 138;   (* Tenths kV (138 = 13.8 kV) *)
    Generator_Reactive_Power_MVAR : INT := 150;   (* Tenths MVAR (150 = 15.0 MVAR lag) *)
    Excitation_Field_Current_Amps : INT := 420;   (* Tenths A (420 = 42.0 A) *)
    Grid_Bus_Voltage_kV : INT := 138;             (* Tenths kV (138 = 13.8 kV) *)
    Generator_Frequency_Hz : INT := 6000;         (* Hundredths Hz (6000 = 60.00 Hz) *)
    AVR_Auto_Select : BOOL := TRUE;               (* Auto / Manual selector *)
    Master_Trip_Reset : BOOL := FALSE;            (* Trip reset PB *)
    Generator_Breaker_Closed : BOOL := TRUE;      (* Main generator breaker *)
END_VAR

VAR_OUTPUT
    AVR_Automatic_Mode_Active : BOOL := TRUE;
    Field_Breaker_Close_Command : BOOL := TRUE;
    Under_Excitation_Limiter_Active : BOOL := FALSE;
    Over_Excitation_Limiter_Active : BOOL := FALSE;
    Excitation_Field_Voltage_Volts : INT := 125;  (* Field VDC *)
    Volts_Per_Hertz_Overfluxing_Trip : BOOL := FALSE;
    Generator_Loss_of_Field_Trip : BOOL := FALSE;
    Field_Overcurrent_Trip_Latched : BOOL := FALSE;
END_VAR

VAR
    Rated_Voltage_kV : INT := 138;
    OEL_Threshold_Amps : INT := 700;              (* 70.0 A ceiling *)
    UEL_Threshold_MVAR : INT := -100;             (* -10.0 MVAR leading clamp *)
    Loss_of_Field_Threshold_MVAR : INT := -200;   (* -20.0 MVAR leading trip *)
    V_Per_Hz_Limit_Ratio : INT := 110;            (* 110% V/Hz *)
END_VAR

(* 0. Master Trip Reset *)
IF Master_Trip_Reset THEN
    Volts_Per_Hertz_Overfluxing_Trip := FALSE;
    Generator_Loss_of_Field_Trip := FALSE;
    Field_Overcurrent_Trip_Latched := FALSE;
END_IF;

(* 1. Volts-per-Hertz (Overfluxing) Protection: V / Hz ratio check *)
(* Ratio = (V / 138) / (Hz / 6000) * 100 *)
IF (Generator_Frequency_Hz > 1000) THEN
    IF ((Generator_Terminal_Voltage_kV * 6000) / (Generator_Frequency_Hz * 138) * 100) >= V_Per_Hz_Limit_Ratio THEN
        Volts_Per_Hertz_Overfluxing_Trip := TRUE;
    END_IF;
END_IF;

(* 2. Loss of Field (40 Relay) Protection *)
IF Generator_Breaker_Closed AND (Generator_Reactive_Power_MVAR <= Loss_of_Field_Threshold_MVAR) AND (Excitation_Field_Current_Amps < 50) THEN
    Generator_Loss_of_Field_Trip := TRUE;
END_IF;

(* 3. Field Overcurrent Protection *)
IF Excitation_Field_Current_Amps >= 850 THEN
    Field_Overcurrent_Trip_Latched := TRUE;
END_IF;

(* 4. Active Trip Enforcement *)
IF Volts_Per_Hertz_Overfluxing_Trip OR Generator_Loss_of_Field_Trip OR Field_Overcurrent_Trip_Latched THEN
    Field_Breaker_Close_Command := FALSE;
    AVR_Automatic_Mode_Active := FALSE;
    Under_Excitation_Limiter_Active := FALSE;
    Over_Excitation_Limiter_Active := FALSE;
    Excitation_Field_Voltage_Volts := 0;
ELSE
    Field_Breaker_Close_Command := TRUE;
    IF AVR_Auto_Select THEN
        AVR_Automatic_Mode_Active := TRUE;

        (* 5. Over-Excitation Limiter (OEL) *)
        IF Excitation_Field_Current_Amps >= OEL_Threshold_Amps THEN
            Over_Excitation_Limiter_Active := TRUE;
            Excitation_Field_Voltage_Volts := 140;
        ELSE
            Over_Excitation_Limiter_Active := FALSE;
        END_IF;

        (* 6. Under-Excitation Limiter (UEL) *)
        IF Generator_Reactive_Power_MVAR <= UEL_Threshold_MVAR THEN
            Under_Excitation_Limiter_Active := TRUE;
            Excitation_Field_Voltage_Volts := 110;
        ELSE
            Under_Excitation_Limiter_Active := FALSE;
        END_IF;

        (* Normal AVR closed-loop voltage regulation *)
        IF NOT Over_Excitation_Limiter_Active AND NOT Under_Excitation_Limiter_Active THEN
            Excitation_Field_Voltage_Volts := 125;
        END_IF;
    ELSE
        AVR_Automatic_Mode_Active := FALSE;
    END_IF;
END_IF;

END_FUNCTION_BLOCK
