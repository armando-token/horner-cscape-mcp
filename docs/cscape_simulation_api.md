# Horner Cscape 10.2 Software Simulation & Win32 Runtime API Reference

## 1. Executive Architecture Summary

This document provides a comprehensive technical reference for interfacing with the **Horner Cscape 10.2 software simulation environment and Win32 simulation automation**.

The automation system provides a **100% software-isolated, zero-hardware simulation interface** in [`src/cscape/simulation.py`](file:///C:/HornerAI/horner-cscape-mcp/src/cscape/simulation.py), enabling automated, deterministic verification of Structured Text (ST) programs without any physical PLC hardware. 

> [!NOTE]
> Standalone Copa-Data Straton K5 project generation (`appli.CPO`, `appli.k5p`, `K5DBXS.INI`) has been confirmed non-native to authentic Cscape and is **quarantined legacy** under `quarantine/straton_k5_legacy/`. The primary simulation engine is the pure-Python AST simulator (`SimulationBackend.EMULATED`) with full Horner OCS register mapping and Win32 UI command automation.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             CscapeSimulator Facade                              │
│          (src/cscape/simulation.py - create_cscape_simulation)                   │
└────────┬─────────────────────────┬────────────────────────────┬──────────────────┘
         │                         │                            │
         ▼                         ▼                            ▼
┌──────────────────┐     ┌─────────────────────┐     ┌─────────────────────────────┐
│  SecurityGuard   │     │ HornerRegisterTable │     │   VariableRegisterMapping   │
│ 100% Isolation   │     │ %R, %AI, %AQ, %SR   │     │  IEC Variables <-> Registers│
│ Zero Hardware    │     │ %I, %Q, %M, %T, %S  │     │   AT %... Sanitization      │
└──────────────────┘     └─────────┬───────────┘     └──────────────┬──────────────┘
                                   │                                │
                                   ▼                                ▼
                         ┌─────────────────────────────────────────────────────────┐
                         │              Simulation Execution Engine                │
                         │   - EMULATED: Pure-Software IEC 61131-3 AST Simulator   │
                         │   - CSCAPE_UI: Headless Win32 WM_COMMAND Automation     │
                         │   - [LEGACY]: 32-bit K5NETSim.dll (Quarantined)         │
                         └─────────────────────────────────────────────────────────┘
```

---

## 2. Cscape 10.2 Simulator Activation & Command Reverse Engineering

Analysis of the 32-bit MFC binary `Cscape.exe` (Version `10.2.751.4`, 17.6 MB) and its Win32 resource tables (specifically Menu Resource `550`, String Tables, and Dialog resources) reveals the internal command IDs and menus used by Cscape to control the simulator:

### 2.1 Discovered Win32 / MFC Command IDs

| Constant Name | Command ID (Dec) | Command ID (Hex) | Menu / UI Path | Description |
| :--- | :--- | :--- | :--- | :--- |
| `START_SIMULATION` | `38367` | `0x95DF` | Menu 550 -> `Debug Option Selection Menu` -> `&Start Simulation` | Starts enhanced IEC simulation session (`ID_STRATON_RUNTIME_DEBUG_SIMULATION`). |
| `STOP_DEBUG_SIMULATION` | `38037` | `0x9495` | Menu 550 -> `&Stop Debugging Programs` | Terminates active simulation or debug session. |
| `EXECUTE_SINGLE_CYCLE` | `38357` | `0x95D5` | Menu 550 -> `Execute a single cycle` | Advances simulation by exactly 1 scan cycle (`ID_STRATON_RUNTIME_DEBUG_EXECUTESINGLE`). |
| `RESUME_CYCLE_MODE` | `38365` | `0x95DD` | Menu 550 -> `Resume cycle to cycle mode ` | Resumes continuous scan cycle execution (`ID_STRATON_RUNTIME_DEBUG_RESUME`). |
| `STEP_IN` | `38358` | `0x95D6` | Menu 550 -> `Step In` | Steps into POU or function block call. |
| `STEP_OVER` | `38359` | `0x95D7` | Menu 550 -> `Step Over` | Steps over statement or function block call. |
| `STEP_OUT` | `38360` | `0x95D8` | Menu 550 -> `Step Out` | Steps out of current subroutine/POU. |
| `PROFILER` | `38362` | `0x95DA` | Menu 550 -> `Profiler` | Toggles execution profiler. |
| `ENHANCED_IEC_DEBUG` | `38411` | `0x960B` | Menu 550 -> `Enhanced IEC Debug` | Opens Enhanced IEC debug window and toolbar. |
| `SIMULATE_LOCAL` | `32812` | `0x802C` | Tools / Debug | "Simulate controller program locally". |
| `DEBUG_MONITOR` | `32838` | `0x8046` | Menu 3 & 550 -> `&Debug/Monitor` | Enters online/offline monitor mode. |
| `OFFLINE_MODE` | `62660` | `0xF4C4` | Status / Mode | Forces Cscape into purely offline state. |

### 2.2 Quarantined Legacy: Straton K5 Compiler Options (`appli.CPO`)

> [!WARNING]
> Generating standalone `appli.CPO` files with `Target=T5SIMUL` is part of the **quarantined legacy** toolchain (`quarantine/straton_k5_legacy/`). Production Cscape 10.2 simulation operates via `SimulationBackend.EMULATED` and live Win32 command dispatch.

### 2.3 Legacy Copa-Data Straton K5NETSim Runtime Module (Quarantined Reference)

Cscape bundles Copa-Data's standalone software simulation engine at:
`C:\Program Files (x86)\Cscape 10.2\K5NETSim.dll` (3.78 MB, 32-bit x86 PE).

#### Export Table Inspection:
```
Ordinal 15: K5SIM_Cycle          (RVA 0x000089E0) -> int K5SIM_Cycle(void* app_handle)
Ordinal 16: K5SIM_FreeApp        (RVA 0x00008A00) -> int K5SIM_FreeApp(void* app_handle)
Ordinal 18: K5SIM_LoadApp        (RVA 0x00008A30) -> void* K5SIM_LoadApp(const char* app_name)
Ordinal 19: K5SIM_SetPath        (RVA 0x0000AF90) -> int K5SIM_SetPath(const char* path)
Ordinal  4: K5NETDRV_Connect     (RVA 0x0000AE20)
Ordinal  5: K5NETDRV_Disconnect  (RVA 0x0000B020)
Ordinal 20: PARSEOLS             (RVA 0x000491D0)
Ordinal 21: RUNOLSCRIPT          (RVA 0x00049370)
```

#### Architecture & Bitness Bridge Strategy:
Because `K5NETSim.dll` is a 32-bit (x86) Windows DLL:
1. When running under a **32-bit Python interpreter**, `ctypes.WinDLL` can link directly to `K5NETSim.dll` to call `K5SIM_SetPath`, `K5SIM_LoadApp`, and `K5SIM_Cycle`.
2. When running under a **64-bit Python interpreter** (e.g. `Python 3.12 64-bit`), Windows 64-bit processes cannot directly load 32-bit DLLs into their address space. The simulation architecture provides a **transparent pure-software emulation bridge (`SimulationBackend.EMULATED`)** that replicates the exact scan cycle, timer/counter mechanics, and Horner register semantics in-memory with zero compilation latency and zero external dependency risk.

---

## 3. Horner OCS Register Memory Architecture

Horner OCS controllers employ a dedicated memory map distinguishing 16-bit word registers from discrete 1-bit boolean registers.

### 3.1 Memory Map & Limits

| Register Type | Prefix | Nature | Valid Index Range | Description |
| :--- | :--- | :--- | :--- | :--- |
| **General Registers** | `%R` | 16-bit Word | `%R1` - `%R9999` | General purpose storage, setpoints, timers, recipes, counters. |
| **Analog Inputs** | `%AI` | 16-bit Word | `%AI1` - `%AI512` | Analog inputs from sensors, transmitters, thermocouple/RTD. |
| **Analog Outputs** | `%AQ` | 16-bit Word | `%AQ1` - `%AQ512` | Analog outputs to actuators, VFD speed references, valves. |
| **Discrete Inputs** | `%I` | 1-bit Boolean | `%I1` - `%I2048` | Physical digital input states (pushbuttons, limit switches). |
| **Discrete Outputs** | `%Q` | 1-bit Boolean | `%Q1` - `%Q2048` | Physical digital output coils (contactors, indicator lamps). |
| **Marker Bits** | `%M` | 1-bit Boolean | `%M1` - `%M2048` | Internal boolean control relays and memory flags. |
| **Temporary Bits** | `%T` | 1-bit Boolean | `%T1` - `%T2048` | Temporary execution scratchpad bits (local POU scope). |
| **System Bits** | `%S` | 1-bit Boolean | `%S1` - `%S16` | System status and pulse clock flags. |
| **System Registers**| `%SR` | 16-bit Word | `%SR1` - `%SR256` | Operating metrics, scan rate, network health, diagnostics. |

### 3.2 System Bits & System Clock Generators

The simulator updates standard Horner system flags per cycle:

| Address | Signal Name | Behavior in Simulation |
| :--- | :--- | :--- |
| `%S1` | **First Scan Pulse** | **`TRUE` exclusively on Cycle 0** (initialization scan); transitions to **`FALSE` on Cycle 1 and all subsequent cycles**. |
| `%S7` | **10ms Clock Pulse** | 20ms period square wave; toggles state every 10ms of accumulated simulation time. |
| `%S8` | **100ms Clock Pulse**| 200ms period square wave; toggles state every 100ms of accumulated simulation time. |
| `%S9` | **1000ms Clock Pulse**| 2000ms period (1Hz) square wave; toggles state every 1000ms (1s) of accumulated simulation time. |
| `%SR1` | **Scan Time** | Reflects the scan delta (`dt_ms`) in integer milliseconds (e.g., `10`). |
| `%SR2` | **System Status** | Set to `1` (Simulation Mode Active). |
| `%SR3` | **Scan Counter (Low)** | Low 16 bits of the cumulative cycle counter (`cycle & 0xFFFF`). |
| `%SR4` | **Scan Counter (High)**| High 16 bits of the cumulative cycle counter (`(cycle >> 16) & 0xFFFF`). |

### 3.3 Multi-Word & Bit-Level Access

Horner OCS programs frequently store 32-bit values across two consecutive 16-bit `%R` registers:
- **32-Bit DINT / DWORD**: Stored as Little-Endian words across `%R[N]` (Low word) and `%R[N+1]` (High word).
- **32-Bit REAL (IEEE 754 float)**: Stored as Little-Endian words across `%R[N]` and `%R[N+1]`.
- **Bit of Word**: Word registers can be addressed at the bit level via `%R[N].[bit]` where `bit` is `0` to `15` (e.g. `%R100.0` or `%R100.15`).

---

## 4. Variable-to-Register Mapping (`VariableRegisterMapping`)

IEC 61131-3 Structured Text represents variables symbolically, whereas Horner OCS controllers link these variables to physical register addresses.

### 4.1 Automatic `AT %...` Extraction & AST Sanitization

In Structured Text source code:
```iec
PROGRAM ConveyorLogic
VAR
    bStart  AT %I1   : BOOL := FALSE;
    bStop   AT %I2   : BOOL := FALSE;
    bMotor  AT %Q1   : BOOL := FALSE;
    nSpeed  AT %R100 : INT  := 0;
    fTemp   AT %R200 : REAL := 25.0;
END_VAR
...
```

The simulator's [`VariableRegisterMapping`](file:///C:/HornerAI/horner-cscape-mcp/src/cscape/simulation.py) automatically:
1. Detects `AT %...` declarations and pragma comments (`(* @%R100 *)`).
2. Registers the variable binding in the memory mapping table.
3. Sanitizes the code into clean standard IEC variable declarations (`bStart : BOOL := FALSE;`) so AST parsers process the code cleanly without syntax errors.
4. Synchronizes variables to registers on every simulation scan cycle.

### 4.2 Cyclic Synchronization Order

During each invocation of `step_cycle()`:
1. **Apply Inputs**: External register writes or variable overrides are written to the `HornerRegisterTable`.
2. **Update System Registers**: `%S1`, `%S7`, `%S8`, `%S9`, and `%SR1..%SR4` are computed.
3. **Synchronize Inputs -> Variables**: `%I`, `%AI`, and bound `%R` registers are propagated into the ST variable context.
4. **Execute Logic Cycle**: ST statements and function blocks (`TON`, `TOF`, `TP`, `CTU`, `CTD`, `CTUD`) execute.
5. **Synchronize Variables -> Outputs**: Updated output variables are written back to `%Q`, `%AQ`, `%R`, and `%M`.
6. **Capture Snapshot**: A `SimulationSnapshot` records timing, variable dictionary, and register state.

---

## 5. 100% Software Isolation & Safety Enforcement

To ensure **zero risk of unintentional controller modification or hardware interference**, the simulator strictly enforces the project security policy:

### 5.1 Enforced Safety Invariants

```python
policy = SafetyPolicy(
    simulation_only=True,
    allow_hardware_communication=False,
    allow_controller_download=False,
    allow_firmware_flash=False,
    enforce_file_sandbox=True,
)
```

### 5.2 Intercepted and Blocked Targets

1. **Hardware Communication Ports**:
   Any attempt to bind or pass serial/COM ports (`COM1` - `COM256`, `\\.\COM*`), Linux serial devices (`/dev/tty*`), CAN bus interfaces (`CAN0`, `PCAN`, `KVASER`), or USB devices raises [`HardwareLockoutError`](file:///C:/HornerAI/horner-cscape-mcp/src/security/exceptions.py).
2. **Controller Download Commands**:
   Any call to `download_to_controller()`, download CLI flags (`/d`, `--download`), or UI commands (`ID_CONTROLLER_DOWNLOAD = 32827`) raises [`UnauthorizedDownloadError`](file:///C:/HornerAI/horner-cscape-mcp/src/security/exceptions.py).
3. **Dangerous Update Executables**:
   Firmware flashing tools (`PGMUpdateUtility.exe`, `DfuSeCommand.exe`, `STMFlashLoader.exe`, `WinJTAG.exe`) are intercepted and blocked before execution.

---

## 6. Python API Reference & Usage Examples

### 6.1 Quick Start: Simulating a Structured Text POU

```python
from src.cscape.simulation import create_cscape_simulation

st_code = """
PROGRAM ConveyorStation
VAR
    bStart AT %I1 : BOOL := FALSE;
    bStop  AT %I2 : BOOL := FALSE;
    bMotor AT %Q1 : BOOL := FALSE;
    nSpeed AT %R100 : INT := 0;
END_VAR

IF bStart AND NOT bStop THEN
    bMotor := TRUE;
    nSpeed := 1750;
ELSIF bStop THEN
    bMotor := FALSE;
    nSpeed := 0;
END_IF;
END_PROGRAM
"""

# 1. Initialize simulation session
sim = create_cscape_simulation(st_code=st_code)
sim.start_simulation()

# 2. Cycle 0: First scan initialization
snap0 = sim.step_cycle()
assert sim.read_bit("%Q1") is False
assert snap0.system_bits["%S1"] is True  # First scan flag set

# 3. Cycle 1: Press Start button (%I1)
sim.write_bit("%I1", True)
snap1 = sim.step_cycle()
assert sim.read_bit("%Q1") is True       # Motor turned on
assert sim.read_register("%R100") == 1750 # Speed set to 1750 RPM
assert snap1.system_bits["%S1"] is False # First scan flag cleared

# 4. Cycle 2: Release Start button, verify motor stays latched
sim.write_bit("%I1", False)
sim.step_cycle()
assert sim.read_bit("%Q1") is True

# 5. Cycle 3: Press Stop button (%I2)
sim.write_bit("%I2", True)
sim.step_cycle()
assert sim.read_bit("%Q1") is False      # Motor turned off
assert sim.read_register("%R100") == 0   # Speed reset
```

### 6.2 Working with Real Numbers (IEEE 754) & Timer Function Blocks

```python
from src.cscape.simulation import create_cscape_simulation

st_code = """
PROGRAM AnalogTimerStation
VAR
    bTrigger AT %I1 : BOOL := FALSE;
    fTemp    AT %R101 : REAL := 25.0;
    tDelay   : TON;
    bDone    AT %Q1 : BOOL := FALSE;
END_VAR

fTemp := fTemp + 0.5;
tDelay(IN := bTrigger, PT := T#50ms);
bDone := tDelay.Q;
END_PROGRAM
"""

sim = create_cscape_simulation(st_code=st_code, default_dt_ms=10.0)
sim.start_simulation()

# Write initial real value
sim.write_real("%R101", 20.0)
sim.write_bit("%I1", True)

# Run 6 cycles (60ms)
for c in range(6):
    snap = sim.step_cycle(dt_ms=10.0)
    print(f"Cycle {c}: bDone={sim.read_bit('%Q1')}, fTemp={sim.read_real('%R101'):.1f}")

assert sim.read_bit("%Q1") is True       # Timer expired after 50ms
assert round(sim.read_real("%R101"), 1) == 23.0
```

### 6.3 Register Range Operations & Direct Memory Access

```python
from src.cscape.simulation import CscapeSimulator, RegisterType

sim = CscapeSimulator()
sim.start_simulation()

# Write a block of recipes to %R1..%R5
sim.register_table.write_range(RegisterType.R, start_idx=1, values=[100, 250, 500, 750, 1000])

# Read back range
vals = sim.register_table.read_range(RegisterType.R, start_idx=1, count=5)
assert vals == [100, 250, 500, 750, 1000]

# Write signed 16-bit negative values
sim.write_register("%R10", -150)
assert sim.read_register("%R10") == -150

# Bit-of-word access
sim.register_table.write_word(RegisterType.R, 20, 0x0001)
assert sim.read_bit("%R20.0") is True
assert sim.read_bit("%R20.1") is False
```

### 6.4 Verifying Hardware Lockout & Isolation

```python
import pytest
from src.cscape.simulation import CscapeSimulator
from src.security.exceptions import HardwareLockoutError, UnauthorizedDownloadError

sim = CscapeSimulator()

# Hardware port lockout
with pytest.raises(HardwareLockoutError):
    sim.connect_hardware("COM1")

# Download lockout
with pytest.raises(UnauthorizedDownloadError):
    sim.download_to_controller()
```

---

## 7. Diagnostics & Status Verification

The `get_status()` method returns real-time diagnostic telemetry:

```python
status = sim.get_status()
```

Sample telemetry dictionary:
```json
{
  "state": "RUNNING",
  "backend": "EMULATED",
  "cycle_count": 5,
  "elapsed_time_ms": 50.0,
  "default_dt_ms": 10.0,
  "software_isolation_enforced": true,
  "has_program_loaded": true,
  "bound_variables_count": 4,
  "k5netsim": {
    "installed": true,
    "dll_path": "C:\\Program Files (x86)\\Cscape 10.2\\K5NETSim.dll",
    "can_load_directly": false
  },
  "cscape_ui_commands": {
    "start_simulation_id": 38367,
    "stop_simulation_id": 38037,
    "execute_single_cycle_id": 38357,
    "resume_cycle_mode_id": 38365
  }
}
```
