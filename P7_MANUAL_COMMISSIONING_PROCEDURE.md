# Phase P7 Manual PLC Loading & Commissioning Standard Operating Procedure (SOP)

**Document ID**: `SOP-P7-HORNER-COMMISSIONING-001`  
**Project Container**: `TankLevel_P5_Dedicated.csp` (Active Disk SHA-256: `574875b9237a2190ad010bc20041fc993ffd32393d256075430ef50c1a6d4f10` [MJ1 restored]; Zip Baseline SHA-256: `9f69f6a2ee12dab54087ab27bb839f40e01d6d65544a546139788519acd80ab1`)  
**Target Hardware**: Horner APG XL4 Prime OCS Series, Model `HE-XPCE2`  
**Programming Software**: Horner APG Cscape 10.2 (Build `10.2.751.4`)  
**Operational Invariant**: **STRICTLY MANUAL LOADING ONLY — ZERO AUTOMATED DOWNLOADS**  
**State Contract**: `CORE-08 CONFIG_AND_TEST_OK RUNTIME_PENDING_P7`, `verified_live: false`, `P7 deferred manual`

---

## 1. Safety Lockout Mandate & Operational Boundary

> [!CAUTION]
> **DO NOT ATTEMPT AUTOMATED PLC DOWNLOADS**  
> All automation scripts, FastMCP servers, and background watchdog processes are locked out fail-closed from physical communication ports (`COM1` through `COM256`), companion flash binaries (`PGMUpdateUtility.exe`), and Win32 download command IDs (`ID_PROGRAM_DOWNLOAD = 32827`, `ID_CONTROLLER_DOWNLOAD = 33149`). Any automated attempt to flash or download will raise an immediate, non-recoverable `SecurityError` / `HardwareLockoutError`.
> 
> **Phase P7 physical controller loading must be executed 100% manually by a certified controls/commissioning engineer.**

---

## 2. Pre-Commissioning Safety Checklist (LOTO & Hardware Verification)

Before connecting any physical cables to the Horner OCS controller:
1. **Lockout / Tagout (LOTO)**:
   - Ensure the field power supply to final control elements (inlet pump contactor `%Q1`, solenoid valve `%Q2`) is locked out and tagged.
   - Verify zero energy state on all 24VDC actuator loops and 480VAC pump motors.
2. **Controller Model & Power Check**:
   - Confirm target hardware nameplate: Horner APG Model **`HE-XPCE2`** (XL4 Prime, CsCAN Model).
   - Confirm 24VDC control power (`+24V`, `0V`) is clean and properly grounded.
   - Power up the controller; ensure the OCS boots cleanly to its system splash screen without hardware watchdog fault codes.
3. **Backup Existing Project**:
   - If commissioning a replacement or field-serviced unit, back up any existing program or removable media (`Removable Media Manager`) before overwriting memory.

---

## 3. Physical Cabling Setup

### 3.1 Programming Connection (Engineering PC to OCS)
Connect the engineering workstation to the Horner OCS controller using **one** of the following approved physical connections:
- **Option A (Recommended - Direct USB)**:
  - Connect a standard USB Type-A to Mini-B cable from the PC USB port to the OCS Mini-B USB programming port (located behind the access door on the bottom of the XL4).
  - Verify Windows Device Manager recognizes `Horner APG USB Communication Device` under Ports (COM & LPT).
- **Option B (Serial MJ1 Cable)**:
  - Connect Horner programming cable (`HE-XCK` / `HE-CPK`) from PC serial port to `MJ1` (8-pin modular RJ45).

### 3.2 Modbus Fieldbus Network Connection (Serial MJ1 / MJ2 RS-485)
- **Port MJ1 (Primary Serial)**:
  - Pin 4: `RS-485 Tx/Rx + (B)`
  - Pin 5: `RS-485 Tx/Rx - (A)`
  - Pin 8: `Signal Ground (GND)`
- **Termination**: If this OCS controller is at the physical end of the RS-485 bus, terminate with a 120-ohm resistor between lines A and B.
- **Ethernet LAN1 (Alternative Modbus TCP)**:
  - Connect standard Cat5e/Cat6 patch cable to RJ45 `LAN1` port.
  - Verify static IP assignment: `192.168.254.128` (Subnet `255.255.255.0`).

---

## 4. Workstation Preparation & Opening the Project

1. **Locate Authentic Project Container**:
   - Extract the project from the handoff distribution bundle:
     `projects/TankLevel_P5_Dedicated/TankLevel_P5_Dedicated.csp`
   - Verify SHA-256 hash matches `574875b9237a2190ad010bc20041fc993ffd32393d256075430ef50c1a6d4f10` (active disk with MJ1 CT RTU driver) or `9f69f6a2ee12dab54087ab27bb839f40e01d6d65544a546139788519acd80ab1` (zip baseline archive).
2. **Launch Cscape 10.2**:
   - Open **Cscape 10.2** from the Start Menu or desktop shortcut.
   - Dismiss any "Tip of the Day" dialog.
3. **Open Project Container**:
   - Select **File -> Open...** (`Ctrl+O`).
   - Browse to and open `TankLevel_P5_Dedicated.csp`.
4. **Audit Project Navigator Hierarchy**:
   - In the Project Navigator dockable tree on the left, expand the root node `TankLevel_P5_Dedicated`:
     - **Hardware Configuration**: Confirm controller shows `XL4 Prime (HE-XPCE2)`.
     - **Control -> Logic Modules**: Confirm `[ST] STBlock1` (Structured Text POU `TankLevelControl`).
     - **Networking -> Protocols**: Confirm `Protocols` configuration is present.

---

## 5. Manual Error Check & Clean Compilation Verification

Before connecting to the target controller, verify compilation integrity:
1. Select top menu: **Program -> Error Check** (or press keyboard shortcut `Ctrl+F8`).
2. Observe the bottom **Output Window**:
   ```text
   Compiler V12.0.200.82
   Loading application symbols...
   EnhancedDisplayAttributes
   No error detected
   Loading application symbols...
   STBlock1
   Building application data...
   Relocating code...
   No error detected
   Online Change is disabled
   Generate OCS code...
   No error detected
   ```
3. **Acceptance Criteria**: Verify exactly **`0 errors`** and **`0 warnings`**. Do NOT proceed if any syntax or semantic error is indicated.

---

## 6. Establishing Manual Controller Communication

1. Select top menu: **Controller -> Communication...**
2. In the Communication Setup dialog:
   - For USB Mini-B connection: Select **USB (Auto Detect)** or assign the virtual COM port allocated to Horner APG.
   - For Serial connection: Select the appropriate COM port (e.g., `COM3`), set Baud Rate to `19200` or `115200`, Data Bits `8`, Parity `None`, Stop Bits `1`.
3. Click **OK**.
4. Check the Cscape bottom status bar:
   - Target Controller: Should transition from `Local: Disconnected (?)` to `Local: Connected (Node 253)` or `Target: OK`.
   - Controller Status: Reports current state (`STOP` or `RUN`).

---

## 7. Manual Project Download (Step-by-Step)

> [!IMPORTANT]
> **THIS STEP MUST BE INITIATED MANUALLY BY CLICKING THE CSCAPE MENU**

1. Select top menu: **Controller -> Download** (or press keyboard shortcut `Ctrl+F9`).
2. The **Download** dialog window will appear:
   - Ensure the following checkboxes are **checked**:
     - [x] **Logic Program**
     - [x] **System Configuration** / **Hardware Configuration**
     - [x] **Protocol Configuration** (`CT RTU Modbus CMP  v 5.05`)
     - [x] **Screens / Graphics**
   - Target selection: Verify Target Node matches local controller node ID.
3. Click **OK** (or **Download**) to begin transfer.
4. **Monitor Transfer Progress**:
   - A progress modal will display transferring sectors, application data, and graphics blocks.
   - Wait until progress bar reaches `100%`.
   - If prompted: *"Controller will be placed in STOP mode to download. Continue?"* Click **Yes**.
5. **Download Completion**:
   - Cscape will report *"Download Complete"* or dismiss the transfer modal cleanly.
   - If prompted: *"Put controller into RUN mode?"*, select **No** for now (remain in STOP for initial I/O audit).

---

## 8. Mode Transition & Field Validation Procedure

1. **Initial Register Inspection (STOP Mode)**:
   - Open **View -> Data Watch** (or **Watch Window**).
   - Add monitor registers:
     - `%AI1` (Raw ADC Level Input, 0..32000 counts)
     - `%R1` (`TankLevelPV`, 0.0..100.0 %)
     - `%R3` (`Setpoint`, default 50.0 %)
     - `%M10` (`CommFailureAlarm`)
     - `%M11` (`TankLevelPV_Stale`)
     - `%Q1` (`PumpRunCmd`)
2. **Transition Controller to RUN Mode**:
   - Select top menu: **Controller -> Run** (or turn physical key-switch / touchscreen System Menu to `RUN`).
   - Confirm status bar indicates `RUN` in green.
3. **Verify Fieldbus Telemetry Acquisition**:
   - With field Modbus level transmitter connected to `MJ1` (or test server on LAN1):
     - Confirm `%AI1` receives live counts (e.g. `17600` counts for nominal 55.0% buffer level).
     - Confirm `%R1` (`TankLevelPV`) computes: `(17600 / 32000.0) * 100.0 = 55.0 %`.
     - Confirm communication heartbeat watchdog (`CommWatchdogReg`) is dynamically updating.
     - Confirm `%M10 = 0` (Healthy) and `%M11 = 0` (Quality Good).
4. **Verify Fail-Safe Quality Clamp (Emergency Comm Loss Test)**:
   - Disconnect the Modbus communication cable from `MJ1` for 3 seconds.
   - Verify that within `T#2s` (`2000 ms` timeout):
     - `%M10` (`CommFailureAlarm`) latches `TRUE` (1).
     - `%M11` (`TankLevelPV_Stale`) latches `TRUE` (1).
     - `%R1` (`TankLevelPV`) immediately clamps to **`0.0 %`** (safe lower bound).
     - Pump command `%Q1` is suppressed / forced `FALSE`.
   - Reconnect the Modbus communication cable:
     - Verify heartbeat advances, `%M10` and `%M11` clear to `FALSE`, and `%R1` recovers to live sensed level.

---

## 9. Commissioning Engineer Sign-Off Sheet

| Parameter | Required Specification | Measured / Verified Value | Sign-Off Initials |
| :--- | :--- | :--- | :--- |
| **Controller Model** | Horner APG `HE-XPCE2` | | |
| **Controller Serial No.** | Verified on physical label | | |
| **Firmware Revision** | Cscape 10.2 compatible (Build 15.40+) | | |
| **Cscape CSP File** | `TankLevel_P5_Dedicated.csp` | SHA-256 verified | |
| **Compiler Output** | Clean build (0 errors, 0 warnings) | 0 errors, 0 warnings | |
| **MJ1 Modbus Driver** | `CT RTU Modbus CMP  v 5.05` | Verified in Protocols | |
| **Raw Telemetry (%AI1)** | 0..32000 counts linear | | |
| **Engineering Level (%R1)**| 0.0 .. 100.0 % | | |
| **Comm Loss Alarm (%M10)** | Latches on > 2.0s silence | Latched TRUE | |
| **Stale Quality (%M11)** | Latches on > 2.0s silence | Latched TRUE | |
| **Fail-Safe Clamp** | Clamps level to 0.0 % on loss | Clamped to 0.0 % | |

**Commissioning Engineer Name**: ______________________________________  
**Signature**: ______________________________________  
**Date (YYYY-MM-DD)**: ____________________  
**Site Location**: ______________________________________  
