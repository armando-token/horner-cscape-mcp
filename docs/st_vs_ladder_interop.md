# Cscape 10.2 Structured Text (ST) vs. Ladder Diagram (LD) Interop Reference

## 1. Executive Summary & Mandatory Standard

Horner APG Cscape 10.2 historically provides two divergent programming paradigms:
1. **Legacy Advanced Ladder**: A proprietary binary ladder logic representation embedded in `.csp` and `.cpj` project files. Advanced Ladder relies on direct memory register addressing (`%R`, `%M`, `%T`, `%I`, `%Q`), graphical rung layouts, and legacy solver mechanics.
2. **IEC 61131-3 Structured Text**: Strongly typed, symbolic programming across standard IEC data types and algorithms, centered exclusively on **Structured Text (ST)**.

### The Mandatory Mandate: IEC 61131-3 Structured Text ONLY via Win32/CFBF/AST/Simulation
The **Horner Cscape MCP Server** automates **real Horner Cscape 10.2** via **Win32 UI/accelerators**, native Compound File Binary Format (**CFBF** / `.csp` & `.cpj`), pure-Python **AST** parsing and validation, and software **simulation**. Advanced Ladder constructs and graphical Ladder (LD) are categorically rejected.

> [!NOTE]
> Standalone Copa-Data Straton K5 workspace generation (`appli.k5p`, `appli.CPO`, `K5DBXS.INI`) has been confirmed non-native to authentic Cscape and is **quarantined legacy** under `quarantine/straton_k5_legacy/`.

```
                  ┌──────────────────────────────────────────────┐
                  │          Horner Cscape 10.2 Dual Mode        │
                  └──────────────────────┬───────────────────────┘
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 ▼                                               ▼
   ┌───────────────────────────┐                   ┌───────────────────────────┐
   │  Legacy Advanced Ladder   │                   │  IEC 61131-3 ST Subsystem │
   │  • Untyped %R, %M memory  │                   │  • Native CFBF .csp / .cpj│
   │  • Graphical rungs        │                   │  • Win32 / UIA Automation │
   │  • No text determinism    │                   │  • Pure-Python AST parser │
   │                           │                   │  • OCS Software Simulator │
   │   ❌ REJECTED & BLOCKED   │                   └─────────────┬─────────────┘
   └───────────────────────────┘                                 │
                                                                 │
                                ┌────────────────────────────────┴────────────────┐
                                ▼                                                 ▼
                  ┌───────────────────────────┐                     ┌───────────────────────────┐
                  │   Ladder Diagram (LD)     │                     │   Structured Text (ST)    │
                  │   • Graphical UI grid     │                     │   • Pure ASCII/UTF-8 .st  │
                  │   • Binary/XML nets       │                     │   • Win32 live compile    │
                  │   • Fragile headless CI   │                     │   • Deterministic AST     │
                  │                           │                     │   • Fast software sim     │
                  │   ❌ REJECTED & BLOCKED   │                     │   ✅ MANDATORY STANDARD   │
                  └───────────────────────────┘                     └───────────────────────────┘
```

---

## 2. How Cscape 10.2 Handles Projects Containing Ladder and ST

### 2.1 Mutual Exclusivity at the Root Project Level
In Cscape 10.2, a project cannot interleave legacy Advanced Ladder rungs and the IEC 61131-3 engine within the same execution cycle:
- **Project Paradigm Separation**: When a developer creates a project in Cscape, the system designates it as either an "Advanced Ladder" project or an "IEC 61131-3" project (via Radio button 1461 in the startup dialog).
- **Runtime Incompatibility**: Legacy Advanced Ladder executes through Cscape's internal interpreter targeting physical Horner OCS memory tables directly. IEC 61131-3 logic runs through strongly-typed symbolic POU compilation. They cannot be mixed without risking variable corruption.

### 2.2 Quarantined Legacy Straton K5 Multi-Language Handling
Within the historical Straton K5 engine, five IEC languages were defined (ST, LD, FBD, SFC, IL).
- Standalone Straton K5 project files (`appli.k5p`, `appli.CPO`) have been **quarantined** under `quarantine/straton_k5_legacy/`.
- Graphical Ladder Diagram (`.ld`) files are rejected by the MCP server's AST parser and interop guard because they introduce non-deterministic binary formats and cannot be verified headlessly.

### 2.3 Failure Modes When Injecting Ladder into Structured Text
When developers or AI models attempt to mix ladder logic into Structured Text files:
1. **Compiler Syntax Errors**: Live Cscape compilation (`ID_PROGRAM_ERRORCHECK = 32826`) and the pure-Python AST validator will immediately fail with syntax errors upon encountering contact symbols (`--[ ]--`), coil markers (`--( )--`), or ladder mnemonics (`XIC`, `OTE`).
2. **Direct Memory Corruption**: Legacy Advanced Ladder uses untyped memory offsets (e.g. `%R0100`). In IEC 61131-3, mixing `%R` registers with typed variables (`INT`, `REAL`, `DINT`) bypasses alignment checks, causing silent word-boundary collisions and variable corruption.
3. **Execution Semantics Mismatch**: Ladder logic relies on continuous left-to-right power flow propagation across parallel rungs on every scan. Structured Text uses procedural algorithmic control flow (`IF...THEN`, `CASE`, `FOR`, `WHILE`).

---

## 3. The Interop Guard Architecture (`src/cscape/st_ld_interop.py`)

The `STLadderInteropGuard` module provides dual-layer protection:

### 3.1 Project-Level Guard (`validate_project` & `enforce_project_st_mode`)
Audits the entire project directory tree to ensure strict IEC 61131-3 Structured Text compliance:
- **Detects Legacy Files**: Flags `.csp` or legacy `.cpj` files.
- **Audits `appli.k5p`**: Scans `/P,name,type,lang` entries. Rejects any POU registered with `LD`, `FBD`, `SFC`, or `IL`.
- **Audits `appli.CPO`**: Verifies compiler option `Language=ST`.
- **Audits `pous/` Directory**: Flags any graphical `.ld` files.
- **Inspects Manifest (`cscape_project.json`)**: Verifies POU metadata and engine type.
- **Raises `NonIECProjectError`**: Halts automation with explicit remediation steps.

### 3.2 Source Code Guard (`detect_ladder_constructs` & `enforce_st_code`)
Inspects ST source code prior to saving or compilation:
- **Comment-Safe**: Strips IEC comments (`(* ... *)`, `// ...`, `/* ... */`) before scanning so explanatory comments are not falsely flagged.
- **Detects ASCII Contacts & Coils**: Identifies `--[ ]--`, `--[/]--`, `--( )--`, `-- ( ) --`, `---(S)---`, `---(R)---`, `---[P]---`, `---[N]---`.
- **Detects Ladder Mnemonics**: Identifies `XIC(...)`, `XIO(...)`, `OTE(...)`, `OTL(...)`, `OTU(...)`.
- **Detects Power Rails, Rungs & Network Labels**: Identifies `|---`, `---|`, `RUNG 1:`, `END_RUNG`, `NETWORK 1:`, `NETWORK 1`, `NETWORK: <title>`, `NET 1:`, `NET 1`, `NETWORK_LABEL`, `END_NETWORK`.
- **Detects Legacy Registers**: Flags untyped `%R\d+`, `%M\d+`, `%T\d+`, `%I\d+`, `%Q\d+` registers and recommends symbolic variable declarations.
- **Strict Pure-ST Preservation**: Ensures valid IEC 61131-3 array subscripts (`arr[i]`), zero-argument function calls (`GetTickCount()`), and parenthesized logic expressions are never falsely rejected.
- **Raises `LadderConstructRejectedError`**: Returns line numbers, matched snippets, and actionable copy-pasteable ST replacement code.

### 3.3 Automated Migration Engine (`convert_ladder_to_st`)
Includes an intelligent heuristic translator that automatically converts common ladder patterns and mnemonics into valid IEC 61131-3 Structured Text.

---

## 4. Comprehensive Ladder to Structured Text Conversion Reference

### 4.1 Contacts & Conditions

| Ladder Construct | Ladder Representation | Structured Text Equivalent | Notes |
| :--- | :--- | :--- | :--- |
| **Normally Open (NO / XIC)** | `---[ Sensor ]---` or `XIC(Sensor)` | `Sensor` or `IF Sensor THEN` | Evaluates to TRUE when bit is active. |
| **Normally Closed (NC / XIO)** | `---[/ Sensor ]---` or `XIO(Sensor)` | `NOT Sensor` or `IF NOT Sensor THEN` | Evaluates to TRUE when bit is inactive. |
| **Series Contacts (AND)** | `---[ In1 ]---[ In2 ]---` | `In1 AND In2` | Logical conjunction along a single rung path. |
| **Parallel Branch (OR)** | `+---[ Auto ]---+`<br>`+---[ Man  ]---+` | `Auto OR Man` | Logical disjunction between parallel rungs. |
| **Complex Branching** | `---[ Stop ]---(+---[ Start ]---+ )---`<br>`              (+---[ Run   ]---+)` | `Stop AND (Start OR Run)` | Group parallel branches with parentheses. |

#### Example: Start/Stop Motor Latch
**Ladder Rung:**
```
|---[ Start ]---+---[/ Stop ]---( Motor )---|
|---[ Motor ]---+
```
**Structured Text:**
```iec
Motor := (Start OR Motor) AND NOT Stop;
```

---

### 4.2 Coils & Output Logic

| Ladder Construct | Ladder Representation | Structured Text Equivalent |
| :--- | :--- | :--- |
| **Normal Coil (OTE)** | `---( Valve )---` or `OTE(Valve)` | `Valve := Condition;` |
| **Set / Latch Coil (OTL)** | `---(S Valve )---` or `OTL(Valve)` | `IF Condition THEN Valve := TRUE; END_IF;` |
| **Reset / Unlatch Coil (OTU)** | `---(R Valve )---` or `OTU(Valve)` | `IF Condition THEN Valve := FALSE; END_IF;` |

#### Example: Set / Reset Latch
**Structured Text:**
```iec
// Set Condition
IF StartCommand AND SafetyOK THEN
    PumpActive := TRUE;
END_IF;

// Reset Condition
IF StopCommand OR FaultDetected THEN
    PumpActive := FALSE;
END_IF;
```

---

### 4.3 Edge Detection (One-Shots)

| Ladder Construct | Ladder Syntax | Structured Text Equivalent |
| :--- | :--- | :--- |
| **One-Shot Rising (OSR / POS)** | `---[P]---` or `[OSR Tag]` | Declare `fbTrig : R_TRIG;`<br>`fbTrig(CLK := InputSignal);`<br>`IF fbTrig.Q THEN ... END_IF;` |
| **One-Shot Falling (OSF / NEG)** | `---[N]---` or `[OSF Tag]` | Declare `fbTrig : F_TRIG;`<br>`fbTrig(CLK := InputSignal);`<br>`IF fbTrig.Q THEN ... END_IF;` |

#### Structured Text Example:
```iec
PROGRAM POU_EdgeDetect
VAR
    bButton : BOOL;
    fbRise : R_TRIG;
    nCounter : INT := 0;
END_VAR

// Call function block
fbRise(CLK := bButton);

// Execute on rising edge pulse
IF fbRise.Q THEN
    nCounter := nCounter + 1;
END_IF;
END_PROGRAM
```

---

### 4.4 Timers & Counters

| Ladder Function | Structured Text Implementation | Instance Declaration |
| :--- | :--- | :--- |
| **TON (On-Delay Timer)** | `fbTON(IN := RunSignal, PT := T#5S);`<br>`bTimerDone := fbTON.Q;`<br>`tElapsed := fbTON.ET;` | `VAR fbTON : TON; END_VAR` |
| **TOF (Off-Delay Timer)** | `fbTOF(IN := StopSignal, PT := T#10S);`<br>`bMotorCoast := fbTOF.Q;` | `VAR fbTOF : TOF; END_VAR` |
| **TP (Pulse Timer)** | `fbTP(IN := Trigger, PT := T#2S);`<br>`bPulseOutput := fbTP.Q;` | `VAR fbTP : TP; END_VAR` |
| **CTU (Up Counter)** | `fbCTU(CU := Pulse, RESET := ResetCmd, PV := 100);`<br>`bCountDone := fbCTU.Q;`<br>`nCount := fbCTU.CV;` | `VAR fbCTU : CTU; END_VAR` |

---

### 4.5 Math, Moves, & Comparisons

| Operation | Ladder Box | Structured Text Equivalent |
| :--- | :--- | :--- |
| **Move** | `[MOV Source -> Dest]` | `Dest := Source;` |
| **Addition** | `[ADD In1, In2 -> Dest]` | `Dest := In1 + In2;` |
| **Subtraction** | `[SUB In1, In2 -> Dest]` | `Dest := In1 - In2;` |
| **Multiplication**| `[MUL In1, In2 -> Dest]` | `Dest := In1 * In2;` |
| **Division** | `[DIV In1, In2 -> Dest]` | `Dest := In1 / In2;` |
| **Compare Equal**| `[EQU In1, In2]` | `IF In1 = In2 THEN ... END_IF;` |
| **Compare Greater**| `[GRT In1, In2]` | `IF In1 > In2 THEN ... END_IF;` |

---

### 4.6 Register Addressing to Strongly Typed Variables

In Legacy Advanced Ladder, memory is mapped to raw register offsets. In Structured Text, variables MUST be declared with explicit IEC data types.

| Legacy Horner Register | Typical Usage | IEC 61131-3 ST Variable Declaration |
| :--- | :--- | :--- |
| `%R0001` | Integer register | `nTargetSpeed : INT := 0;` |
| `%R0002` .. `%R0003` | Double integer / Float | `rProcessTemp : REAL := 25.0;` |
| `%M0001` | Internal marker bit | `bAutoModeSelected : BOOL := FALSE;` |
| `%T0001` | Temporary coil | `bCycleStepValid : BOOL;` |
| `%I0001` | Digital input | `bEmergencyStop : BOOL;` |
| `%Q0001` | Digital output | `bConveyorRun : BOOL;` |
| `%AI0001` | Analog input | `nAnalogSensorRaw : INT;` |
| `%AQ0001` | Analog output | `nValveDriveCommand : INT;` |

---

### 4.7 Network Labels & Rung Markers

In graphical Ladder Diagram, logic is segmented into numbered or named networks and rungs. In IEC 61131-3 Structured Text, program statements execute procedurally from top to bottom. Networks and rung dividers are not part of the IEC 61131-3 ST grammar.

| Ladder Segment / Marker | Ladder Representation | Structured Text Equivalent | Actionable Migration Guidance |
| :--- | :--- | :--- | :--- |
| **Network Header** | `NETWORK 1: Motor Control`<br>`NET 1:` | `// --- Network 1: Motor Control ---` | Convert network headers to clear descriptive section comments or modular subprograms/functions. |
| **Network End Marker** | `END_NETWORK` | `// --- End of network ---` | Remove boundary marker; ST execution flows procedurally. |
| **Rung Marker** | `RUNG 1: Start Conveyor`<br>`LADDER_RUNG` | `// --- Rung 1: Start Conveyor ---`<br>`Motor := Start AND NOT Stop;` | Replace rung markers with sequential assignment statements terminated by semicolons (`;`). |
| **Rung End Marker** | `END_RUNG` | `// --- End of rung ---` | Remove delimiter; statements are bounded by `;`. |
| **Empty Contact** | `--[ ]--` | `// Assign boolean condition`<br>`IF bCondition THEN ...` | Replace empty contact brackets with a symbolic boolean variable or expression. |
| **Empty Coil** | `--( )--` or `-- ( ) --` | `bTargetOutput := bCondition;` | Replace empty coil parentheses with a boolean target assignment (`:=`). |

---

## 5. Automated Interop Testing & Quality Assurance

The `tests/test_st_ld_interop.py` test suite validates:
1. **Detection Accuracy**: Verifies all ASCII contacts, coils, power rails, and mnemonics are caught.
2. **Comment Safety**: Confirms ladder descriptions inside comments (`(* ... *)`, `//`) do not cause false positives.
3. **Automated Conversion**: Asserts that ladder rungs convert to mathematically equivalent Structured Text expressions.
4. **Project Integrity**: Asserts that projects containing `.csp`, `.cpj`, `.ld`, or non-ST `appli.k5p` entries are rejected with `NonIECProjectError`.
5. **Clean Structured Text**: Asserts that valid IEC 61131-3 ST programs pass without warnings or errors.

---

## 6. Cscape 10.2 In-GUI ST→LD Conversion Reality (H12: BLOCKED_NATIVE)

### 6.1 IDE Separation & Absence of Native Conversion Tools
Horner APG Cscape 10.2 (Build `10.2.751.4`) maintains a fundamental architectural separation between its legacy Advanced Ladder solver and its IEC 61131-3 multi-language engine:
- **No Native Conversion**: Cscape 10.2 contains **zero GUI menus, menu items, dialog controls, toolbar buttons, Win32 accelerator commands, COM interfaces, or DLL exports** for converting Structured Text POUs into Advanced Ladder rungs or vice versa.
- **Classification**: Native in-GUI ST→LD conversion is permanently classified as **`BLOCKED_NATIVE: DOCUMENT_ONLY`** (see [`docs/st_to_ld_conversion_blocked.md`](file:///C:/HornerAI/horner-cscape-mcp/docs/st_to_ld_conversion_blocked.md)).
- **Runtime Lockout**: Any attempt to request in-GUI ST→LD conversion via `STLadderInteropGuard.request_in_gui_conversion()` returns `status: blocked` with error code `BLOCKED_NATIVE`.

### 6.2 Verified Offline AST Transpilation Alternative
While in-GUI conversion is blocked natively, the MCP server provides an offline AST-based transpiler:
- **AST Parser & Transpiler**: `STLadderInteropGuard.convert_st_to_ladder()` decomposes IEC 61131-3 Structured Text AST nodes into abstract ladder representations (`LadderProgram`), series/parallel contact networks, and coil operations.
- **Verification Proofs**: Synthesizes verified ASCII ladder diagrams and structured JSON AST models for documentation, visual inspection, and verification without touching physical PLC hardware.

