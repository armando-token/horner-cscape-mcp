(* ============================================================================
 * Program exercising all 16 specified IEC 61131-3 elementary data types:
 * BOOL, BYTE, WORD, DWORD, SINT, INT, DINT, LINT, USINT, UINT, UDINT, ULINT,
 * REAL, LREAL, TIME, STRING
 * ============================================================================ *)

PROGRAM AllTypesProgram
VAR
    (* 1. Bit strings *)
    var_bool   : BOOL := TRUE;
    var_byte   : BYTE := 16#FF;
    var_word   : WORD := 16#ABCD;
    var_dword  : DWORD := 16#12345678;

    (* 2. Signed Integers *)
    var_sint   : SINT := -128;
    var_int    : INT := -32000;
    var_dint   : DINT := -2147483648;
    var_lint   : LINT := -9223372036854775807;

    (* 3. Unsigned Integers *)
    var_usint  : USINT := 255;
    var_uint   : UINT := 65535;
    var_udint  : UDINT := 4294967295;
    var_ulint  : ULINT := 18446744073709551615;

    (* 4. Floating Point Numbers *)
    var_real   : REAL := 3.14159;
    var_lreal  : LREAL := 2.718281828459045;

    (* 5. Time and Strings *)
    var_time   : TIME := T#1h30m15s500ms;
    var_string : STRING := 'Horner Cscape IEC 61131-3 Pure Structured Text';
END_VAR

(* Logic manipulating all 16 variables *)
IF var_bool THEN
    var_byte := var_byte AND 16#0F;
    var_word := var_word OR 16#00FF;
    var_dword := var_dword XOR 16#0000FFFF;

    var_sint := var_sint + 1;
    var_int := var_int + 10;
    var_dint := var_dint + 100;
    var_lint := var_lint + 1000;

    var_usint := var_usint - 1;
    var_uint := var_uint - 10;
    var_udint := var_udint - 100;
    var_ulint := var_ulint - 1000;

    var_real := var_real * 1.5;
    var_lreal := var_lreal * 2.0;

    var_time := T#5s;
    var_string := 'Updated Status String';
END_IF;

END_PROGRAM
