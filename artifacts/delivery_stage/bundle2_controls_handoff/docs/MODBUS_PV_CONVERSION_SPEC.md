# Modbus PV Provider Technical Conversion Specification

## 1. Full Technical Inventory
- **Transport**: `MODBUS_TCP` (Primary) & `MODBUS_RTU` (Secondary on `MJ1_RS485`)
- **Role**: `CLIENT_MASTER_READ_ONLY` (Horner OCS acts as Master/Client; writes prohibited)
- **Unit ID**: `1`
- **Function Code**: `0x03` (Read Holding Registers) / `0x04` (Read Input Registers)
- **Modicon Address (1-based)**: `40001`
- **Wire Offset (0-based)**: `0x0000`
- **Horner Internal Target Register**: `%AI1` (Analog Input 1) / `%R101` (Word 101)
- **Raw Data Type**: `UINT16` (Range 0..32000 counts)
- **Internal PV Type**: `REAL` (Range 0.0..100.0 %)
- **Byte Order**: `BIG_ENDIAN_AB` (Standard high byte first)
- **Scan Polling Rate**: `100 ms`
- **Timeout**: `1000 ms`
- **Stale Timeout**: `2000 ms` (Sets `%M10` Comm Failure, `%M11` Stale Data)

## 2. Mathematical Scaling Formula
$$PV_{EU} = \frac{Raw - Raw_{Min}}{Raw_{Max} - Raw_{Min}} \times (EU_{Max} - EU_{Min}) + EU_{Min}$$

With Horner APG standard 15-bit ADC parameters:
$$PV_{EU} = \frac{Raw}{32000.0} \times 100.0$$

Example with raw count 17600:
$$PV_{EU} = \frac{17600.0}{32000.0} \times 100.0 = 55.0\%$$

## 3. Protocol Frame Byte Breakdown
### Modbus TCP Request ADU (12 bytes)
`00 01 00 00 00 06 01 03 00 00 00 01`
- `00 01`: Transaction ID (1)
- `00 00`: Protocol ID (0 = Modbus)
- `00 06`: Length (6 bytes following)
- `01`: Unit ID (1)
- `03`: Function Code (Read Holding Registers)
- `00 00`: Register Address (0x0000 = Modicon 40001)
- `00 01`: Register Count (1 register)

### Modbus TCP Response ADU (11 bytes)
`00 01 00 00 00 05 01 03 02 44 C0`
- `00 01`: Transaction ID (1)
- `00 00`: Protocol ID (0)
- `00 05`: Length (5 bytes following)
- `01`: Unit ID (1)
- `03`: Function Code (0x03)
- `02`: Byte Count (2 bytes)
- `44 C0`: Register Data (0x44C0 = 17600 counts -> 55.0% level)
