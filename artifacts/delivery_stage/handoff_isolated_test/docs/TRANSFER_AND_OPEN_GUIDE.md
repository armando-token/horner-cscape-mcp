# Engineering Transfer and Open Guide (Cscape 10.2)

## 1. Project Container Overview
- **Target File**: `projects/TankLevel_P5_Dedicated/TankLevel_P5_Dedicated.csp`
- **Container Format**: Authentic Compound File Binary Format (CFBF OLE2).
- **Target Hardware**: Horner APG XL Prime OCS Series, Model XL4 Prime (`HE-XPCE2`).
- **Target Software**: Horner APG Cscape 10.2 (Build 10.2.751.4).

## 2. Transferring to Engineering Workstation
1. Copy the `projects/TankLevel_P5_Dedicated` folder to your local engineering projects directory (e.g. `C:\HornerProjects\TankLevel_P5_Dedicated`).
2. Verify file integrity using `MANIFEST-SHA256.json`.

## 3. Opening in Horner Cscape 10.2
1. Launch **Cscape 10.2** on the engineering desktop.
2. Select **File -> Open...** (`Ctrl+O`) and browse to `TankLevel_P5_Dedicated.csp`.
3. In Project Navigator, expand the controller tree:
   - Verify **Hardware Configuration**: XL4 Prime (`HE-XPCE2`).
   - Verify **I/O & Network Configuration**:
     - Serial `MJ1`: `CT RTU Modbus CMP  v 5.05` (Baud 19200, 8-N-1, RS-485 mode).
     - CAN1: `CsCAN` (Network ID 1).
     - LAN1: `ETN300` (IP 192.168.254.128/24).
   - Verify **Logic Programs**: `TankLevelControl` (IEC 61131-3 Structured Text).

## 4. Compiling & Syntax Verification
1. Press **Error Check** (`ID_PROGRAM_ERRORCHECK = 32826`) or top menu **Program -> Error Check**.
2. Confirm Output Window reports:
   ```text
   Compiler V12.0.200.82
   Loading application symbols...
   EnhancedDisplayAttributes
   No error detected
   ```

## 5. Offline Protocol Simulation Testing
Before deploying to physical field networks, run the labeled pure-Python test server to validate communications logic:
```powershell
python test_tools/test_modbus_server.py --port 15502
```
