# Cscape Native Project Samples Catalog (.csp)

This directory contains real, native Horner Cscape binary project files (`.csp`) harvested from the official Cscape 10.2 installation at `C:\Program Files (x86)\Cscape 10.2\Examples\`.

These sample files serve as reference test fixtures and reverse-engineering baselines for parser validation, ST-to-ladder transpilation, project migration, and MCP automation testing.

---

## 1. Binary Format Specification

Horner Cscape `.csp` files use the standard **Microsoft Compound File Binary Format (CFBF v3 / OLE2)** container architecture (also known as `DOCFILE`).

### 1.1 Outer Container (CFBF)
- **Signature (Magic Bytes)**: `D0 CF 11 E0 A1 B1 1A E1` (8 bytes)
- **Sector Size**: 512 bytes (v3)
- **Root Storage**: Holds internal streams and storage objects.
- **Primary Stream**: `/Contents` contains the complete serialized Cscape project database (logic, configuration, variables, and graphics).

### 1.2 Inner Stream (`/Contents`) Header Layout
The `/Contents` stream begins with a 12-byte header followed by serialized project modules:

| Offset | Type | Field | Description / Values |
|--------|------|-------|----------------------|
| `0x00 - 0x03` | `uint32` (LE) | **Magic Bytes** | `0x78563412` (`12 34 56 78` in byte order) |
| `0x04 - 0x07` | `uint32` (LE) | **File Format Version** | Version tag (e.g., `38`, `42`, `48`, `54`, `55`, `57`, `62`, `69`, `79`) |
| `0x08` | `uint8` | **Cscape Major Version** | Software major version (e.g., `2`, `3`, `5`) |
| `0x09` | `uint8` | **Cscape Minor Version** | Software minor version (e.g., `0x1E`=30, `0x28`=40, `0x50`=80) |
| `0x0A - 0x0B` | `uint16` (LE) | **Cscape Build Number** | Build release index (e.g., `1`, `20`, `250`, `252`, `253`) |

### 1.3 Internal Project Sections
Following the 12-byte header, the `/Contents` stream contains structured records:
1. **Subroutine Directory**: Count and length-prefixed identifiers for logic routines:
   - `main`: Primary ladder logic scanning routine.
   - `Receive_Q_AQ`: Distributed I/O receive subroutine (e.g., RCS116).
   - `Transmit_I_AI`: Distributed I/O transmit subroutine (e.g., RCS116).
2. **Network Rungs & Instructions**: Rung numbers, rung comments, contact coils, math blocks (`ADD`, `SUB`, `MUL`, `DIV`, `MOD`, `SQRT`, `ABS`), timers, and special function blocks.
3. **Register Table / Symbol Names**:
   - `%R`: 16-bit internal holding registers (%R1 - %R9999).
   - `%I` / `%Q`: Discrete inputs and outputs (%I1-%I64, %Q1-%Q64).
   - `%AI` / `%AQ`: Analog input and output registers (%AI1-%AI32, %AQ1-%AQ32).
   - `%M` / `%T`: Internal bit flags and temporary bits.
   - `%S` / `%SR`: System status bits and system registers (e.g., `%SR56` Network ID, `%SR1` Screen Number).
   - `%K`: Function keys (%K1 - %K12).
4. **HMI Screen & Graphics Data**: Screen definitions, text strings, numeric data fields, bar graphs, trend charts, and font records.
5. **Special Function Blocks**:
   - `ALRM`: Alarm handler and acknowledge manager.
   - `RECIPE`: Batch recipe storage, CompactFlash / microSD persistence.
   - `DATA_LOG`: Periodic / trigger-based CSV data logging.
   - `NET GET / NET PUT`: CsCAN peer-to-peer network messaging.
   - `COMM`: RS-232 / RS-485 serial communication handling.

---

## 2. Harvested Samples Catalog

A total of 25 native project files were selected and copied from `Cscape 10.2\Examples`, representing a broad spectrum of Horner automation functionality:

| File Name | Size (Bytes) | Stream Size | Format Ver | Cscape Software Version | Subroutines | Primary Functionality |
|-----------|--------------|-------------|------------|-------------------------|-------------|-----------------------|
| `alarm test.csp` | 12,288 | 4,118 | 54 | v3.40 (build 1) | `main` | Alarm Handler function block with acknowledgment, up/down scrolling, and LED indicators. |
| `all.csp` | 13,824 | 11,142 | 79 | v5.80 (build 1) | `main` | Comprehensive math & logic instructions testbed (`+`, `-`, `*`, `/`, `MOD`, `SQRT`, `ABS`). |
| `alpha keyboard.csp` | 124,416 | 59,968 | 57 | v3.40 (build 1) | `main` | Virtual on-screen QWERTY alphanumeric keyboard for OCS touchscreens. |
| `barcode length.csp` | 10,752 | 3,576 | 38 | v2.30 (build 1) | `main` | Serial barcode reader with fixed-character buffer length trigger and CRC/terminator check. |
| `barcode time.csp` | 15,872 | 4,278 | 38 | v2.30 (build 1) | `main` | Serial barcode reader with 250ms silence timeout detection for variable length codes. |
| `char replace.csp` | 6,144 | 3,020 | 43 | v3.40 (build 253) | `main` | String manipulation: scanning ASCII strings and replacing target characters (e.g. `*` with `$`). |
| `data_log.csp` | 11,264 | 4,667 | 48 | v3.40 (build 253) | `main` | CompactFlash data logging configuration, periodic logging, and CSV export. |
| `graph_example.csp` | 169,984 | 82,855 | 57 | v3.40 (build 253) | `main` | Real-time trend graphics, historical profile data loading (%R500-%R588), and buffer resets. |
| `ip_display.csp` | 7,680 | 1,967 | 49 | v3.40 (build 1) | `main` | Ethernet IP address octet formatting (%R1-%R4) and runtime packed display (%R6-%R7). |
| `Net_Get_Example.csp` | 8,192 | 2,496 | 48 | v3.40 (build 250) | `main` | CsCAN network communication using `NET GET WORD` across distributed nodes. |
| `ocs250 up-down.csp` | 207,360 | 44,947 | 54 | v3.40 (build 253) | `main` | Screen navigation control using Up/Down arrow keys and `%SR1` screen register increments. |
| `ocs250demo_old.csp` | 803,328 | 383,060 | 54 | v3.40 (build 253) | `main` | Comprehensive OCS250 demonstration project with multi-screen HMI and scaling calculations. |
| `prevent_sys.csp` | 4,608 | 1,381 | 42 | v3.02 (build 1) | `main` | System menu lock: suppresses OCS system menu button when ladder logic is running. |
| `random.csp` | 7,680 | 1,836 | 55 | v3.40 (build 1) | `main` | Linear congruential pseudo-random number generator implemented in 16-bit ladder logic. |
| `RCS116_IO.csp` | 7,168 | 4,567 | 69 | v5.80 (build 20) | `main`, `Receive_Q_AQ`, `Transmit_I_AI` | Remote CAN I/O base handling 64 digital outputs (%Q) and 32 analog outputs (%AQ). |
| `RCS116_IO_50mS_Analog.csp` | 11,776 | 4,580 | 69 | v5.80 (build 20) | `main`, `Receive_Q_AQ` | Remote CAN I/O optimized with high-speed 50ms periodic analog updates. |
| `RCS116_LX.csp` | 9,728 | 6,027 | 69 | v5.80 (build 1) | `main` | Host LX controller receiving remote digital/analog inputs (%I and %AI) from RCS116. |
| `recipe.csp` | 51,712 | 24,068 | 62 | v5.80 (build 1) | `main` | Batch recipe manager with CompactFlash file storage and indirect register pointer indexing. |
| `reg_min.csp` | 5,120 | 1,814 | 41 | v3.02 (build 1) | `main` | Register boundary checking: clamps value to minimum threshold (%R5) and triggers error message. |
| `scrolling_text.csp` | 7,680 | 1,630 | 42 | v3.40 (build 1) | `main` | Marquee scrolling text: rotates ASCII buffer right every 140ms across display registers. |
| `Serial Test OCS200.csp` | 8,704 | 5,847 | 55 | v3.40 (build 1) | `main` | RS-232 serial loopback test for OCS200 hardware with byte counters and transmit timers. |
| `Serial Test OCS250.csp` | 13,312 | 10,509 | 55 | v3.40 (build 252) | `main` | RS-232 serial loopback and protocol diagnostic test for OCS250 hardware. |
| `series coils.csp` | 4,608 | 1,325 | 38 | v2.30 (build 1) | `main` | Horner ladder logic power flow demonstration placing multiple output coils in series. |
| `submenu.csp` | 7,168 | 4,318 | 38 | v2.30 (build 1) | `main` | Screen navigation engine with 10 user screens and two 8-screen submenus (Screens 101-118). |
| `sys password.csp` | 9,216 | 3,223 | 42 | v3.02 (build 1) | `main` | Password gatekeeper (passcode `12345`) protecting OCS system configuration screens. |

---

## 3. Deep Dive into Key Samples

### 3.1 `alarm test.csp`
- **Application**: Industrial Alarm Monitoring and Dispatch.
- **Key Logic**:
  - Implements the Cscape **Alarm Handler** function block.
  - Inputs `%I1-%I8` trigger active alarm bits.
  - Arrow keys (Up/Down) navigate through active alarms in the alarm buffer.
  - Key `%K10` (F10) toggles the alarm banner display on/off.
  - Output `%Q8` and `%Q7` flash to indicate unacknowledged or pending alarms.
- **Registers Used**: `%SR56` (Network ID), `%I1-%I8`, `%Q1-%Q8`, `%R` alarm state words.

### 3.2 `data_log.csp`
- **Application**: CompactFlash / Removable Media Data Logging.
- **Key Logic**:
  - Configures periodic logging to CSV files on removable storage.
  - Uses system timers `%T_SEC`, `%T_100MS` and scan flags `%FST_SCN` to initialize logging queues.
  - Records sensor registers, timestamps, and process state variables.

### 3.3 `recipe.csp`
- **Application**: Multi-Product Batch Recipe Storage and Selection.
- **Key Logic**:
  - Manages batch setpoints stored in blocks of 15 registers per recipe.
  - Selects batch via `%R1000` (`batch_sel`), calculating indirect base offset:
    ```
    %R1002 = (batch_sel * 5) + 1500
    ```
  - Copies recipe values from CompactFlash or holding registers `%R1500+` to active working setpoints `%R900`.
  - Sets recipe object attributes to protect against unauthorized on-screen edits.

### 3.4 `RCS116_IO.csp` & `RCS116_IO_50mS_Analog.csp`
- **Application**: Distributed Fieldbus I/O Control over CsCAN.
- **Key Logic**:
  - Subroutine `Receive_Q_AQ`: Reads 64 digital outputs (`%Q1-%Q64`) and 32 analog outputs (`%AQ1-%AQ32`) broadcast by the master OCS.
  - Subroutine `Transmit_I_AI`: Broadcasts 64 digital inputs (`%I1-%I64`) and 32 analog inputs (`%AI1-%AI32`) back to the master OCS on change-of-state.
  - Health check logic monitors communication heartbeat; in event of bus interruption, outputs are immediately zeroed for safety.
  - Network ID configured via register `%R2001`.

### 3.5 `all.csp`
- **Application**: Math and Logic Instruction Reference.
- **Key Logic**:
  - Exercises full arithmetic instruction set: `ADD`, `SUB`, `MUL`, `DIV`, `MOD`, `SQRT`, `ABS`.
  - Complex multi-term ladder expressions (e.g. `%R1 = %R3 + 1234 / %R7`).
  - Useful for verifying ST-to-Ladder AST translation and register allocation.

---

## 4. Tooling & Verification

### 4.1 Reusable Inspector Tool
A standalone CLI utility `inspect_csp.py` is included in this directory to inspect any native `.csp` file or directory:

```bash
# Inspect all files in this directory:
C:\HornerAI\horner-cscape-mcp\.venv\Scripts\python.exe fixtures\cscape_native_samples\inspect_csp.py fixtures\cscape_native_samples

# Inspect a single file with full JSON output:
C:\HornerAI\horner-cscape-mcp\.venv\Scripts\python.exe fixtures\cscape_native_samples\inspect_csp.py "fixtures\cscape_native_samples\alarm test.csp"
```

### 4.2 Automated Test Suite
Pytest test coverage for all fixtures is provided in `tests/test_cscape_native_samples.py`:

```bash
C:\HornerAI\horner-cscape-mcp\.venv\Scripts\python.exe -m pytest tests\test_cscape_native_samples.py -v
```

All 5 test suites pass, verifying CFBF headers, `/Contents` stream integrity, Cscape magic bytes (`0x78563412`), and software version decoding.
