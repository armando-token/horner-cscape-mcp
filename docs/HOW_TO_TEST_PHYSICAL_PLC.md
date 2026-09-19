# How to Test on Physical Windows + Horner OCS Hardware (Phase P7 Manual Commissioning)

**Operational Policy**: `DEFERRED_MANUAL (Zero Automated PLC Download)`  
**Assigned Commissioning Engineer**: Armando Silva (Lead Controls Engineer)  
**Target Controller**: Horner APG XL4 Prime OCS Series, Model **`HE-XPCE2`**  
**Engineering Software**: Horner APG Cscape 10.2 (Build `10.2.751.4`)  
**Approved Project File**: `TankLevel_P5_Dedicated.csp`  
**Governing Standard Operating Procedure**: [`P7_MANUAL_COMMISSIONING_PROCEDURE.md`](file:///C:/Users/ArmandoSilva/Downloads/P7_MANUAL_COMMISSIONING_PROCEDURE.md) (`SOP-P7-HORNER-COMMISSIONING-001`)  
**Safety Checklist**: [`P7_MANUAL_LOAD_CHECKLIST.md`](file:///C:/Users/ArmandoSilva/Downloads/P7_MANUAL_LOAD_CHECKLIST.md)  
**Supervisor Sign-Off**: [`SUPERVISOR_OFFLINE_ACCEPTANCE.md`](file:///C:/Users/ArmandoSilva/Downloads/SUPERVISOR_OFFLINE_ACCEPTANCE.md)  

---

> [!CAUTION]
> **STRICTLY MANUAL LOADING ONLY — ZERO AUTOMATED DOWNLOADS**  
> All physical controller connections and program downloads must be performed 100% manually by commissioning engineer Armando Silva via the Cscape 10.2 GUI when physical hardware is present in the plant or laboratory. All AI agents, FastMCP servers, and background scripts remain permanently locked out fail-closed from physical communication ports and Win32 download commands (`32827`, `33149`).

---

## 1. Prerequisites & Field Safety (Steps 1–3)

Before attaching any programming cable or applying control power:

1. **Pre-Commissioning Controller Backup**:
   - If servicing or replacing an active controller, back up current program, system registers, and hardware configuration to removable media.
2. **Hardware Nameplate & Power Inspection**:
   - Confirm controller model: Horner APG **`HE-XPCE2`** (XL4 Prime, CsCAN, Dual Serial, LAN).
   - Verify clean 24VDC control power (`+24V`, `0V`) and proper earth ground.
   - Confirm controller powers up cleanly without hardware watchdog faults.
3. **Lockout / Tagout (LOTO) & Electrical Isolation**:
   - Execute LOTO on field actuators: inlet pump contactor `%Q1` (480VAC) and solenoid drain valve `%Q2` (24VDC).
   - Verify zero energy state on all field output circuits before connecting to the PLC.

---

## 2. Workstation Setup & Project Verification (Steps 4–5)

1. **Verify Approved Project Container**:
   - Locate `TankLevel_P5_Dedicated.csp` on the engineering workstation.
   - Verify SHA-256 matches: `9f69f6a2ee12dab54087ab27bb839f40e01d6d65544a546139788519acd80ab1` (or reference build `2da72f913d80a13346452ba5c3dbb9f2bf61a0c4f8d22d64a2f8bdf969e6b66b`).
   - Open project in Cscape 10.2 (`Ctrl+O`).
   - Verify Project Navigator hierarchy:
     - **Hardware Configuration**: `HE-XPCE2`
     - **Logic Modules**: Pure ST POUs (`TankLevelControl`, `FB_ModbusScaleQuality`, `TankLevelModbusBridge`)
     - **Protocol Configuration**: Port `MJ1` set to `MJ1 CT RTU Modbus CMP v5.05` (`CTRtu.dll v5.5.0.0`, RS-485 Half-Duplex, 19200-8-N-1).
   - **Confirm Scan List Table: Empty until live**:
     - The native scan list on `MJ1` is deliberately empty offline (`count: 0`) to prevent CFBF corruption without an active bus.
     - The planned slave device inventory is documented in [`modbus_protocol_inventory.json`](file:///C:/Users/ArmandoSilva/Downloads/modbus_protocol_inventory.json) for live manual configuration:
       - `DEV_LT01` (Unit 1): Buffer Tank Level Transmitter (`%AI1`, Modicon `40001`, 0..100.0 %)
       - `DEV_FT01` (Unit 2): Inflow Coriolis Flowmeter (`%AI2`, Modicon `40002`, 0..500.0 L/min)
       - `DEV_PT01` (Unit 3): Discharge Pressure Transmitter (`%AI3`, Modicon `40003`, 0..10.0 bar)

2. **Clean Single-Pass Error Check**:
   - In Cscape 10.2, dispatch **Program -> Error Check** (`Ctrl+F8` / Win32 ID `32826`).
   - Confirm Output Window reports exactly **`0 errors`** and **`0 warnings`**.
   - Do not use background compiler loops (`no_error_check_loop: true`).

---

## 3. Communication & Manual Download (Steps 6–7)

1. **Physical Cable Connection**:
   - Connect USB Type-A to Mini-B programming cable between workstation and OCS Mini-B port (or serial MJ1 programming cable `HE-XCK`/`HE-CPK`).
   - In Cscape, open **Controller -> Communication...**; select **USB (Auto Detect)** or the assigned COM port.
   - Confirm status bar transitions to **`Local: Connected (Node 253)`** or **`Target: OK`**.

2. **Strictly Manual Cscape Download**:
   - Armando Silva manually initiates **Controller -> Download** (`Ctrl+F9`).
   - Select: **Logic Program**, **System/Hardware Configuration**, **Protocol Configuration** (`MJ1 CT RTU Modbus CMP v5.05`), and **Screens/Graphics**.
   - Click **OK / Download** and wait for completion (100%).
   - When prompted to transition to RUN mode, select **No** (remain in STOP for initial I/O audit).

---

## 4. Post-Download Telemetry & Mode Transition (Steps 8–9)

1. **Transition to RUN Mode & Loop Check**:
   - In Cscape, open **View -> Data Watch** and add `%AI1..%AI3`, `%R1`, `%R3`, `%M10..%M15`, `%Q1`, and IEC bridge registers `%R101`, `%R103`, `%R105`.
   - Transition controller to **RUN** mode via Cscape menu **Controller -> Run** or OCS System Menu.
   - Once field transmitters are connected to the `MJ1` RS-485 bus:
     - Verify `%AI1` receives raw counts (0..32000) and `%R101` calculates scaled level (0.0..100.0%).
     - Verify `%AI2` receives raw counts and `%R103` calculates flow rate (0.0..500.0 L/min).
     - Verify `%AI3` receives raw counts and `%R105` calculates pressure (0.0..10.0 bar).
     - Verify health flags: `%M10 = 0`, `%M12 = 0`, `%M14 = 0` (All Healthy).
   - Test fail-safe disconnect: Unplug `MJ1` serial cable for > 2.0s; verify `%M10 = 1`, `%M11 = 1`, and `%R101` clamps to `0.0%`. Reconnect and confirm recovery.

2. **Sign-Off & Hand-off to Subsequent Field Milestones**:
   - Sign the physical validation sheet in Section 9 of [`P7_MANUAL_COMMISSIONING_PROCEDURE.md`](file:///C:/Users/ArmandoSilva/Downloads/P7_MANUAL_COMMISSIONING_PROCEDURE.md).
   - Advance to:
     - **Milestone CORE-09**: Physical touchscreen HMI & WebMI remote screen verification.
     - **Milestone CORE-10**: 24-hour hardware telemetry soak test under plant pumping load.
