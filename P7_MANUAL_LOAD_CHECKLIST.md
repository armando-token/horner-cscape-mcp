# Phase P7 Manual PLC Load Checklist / Lista de Verificación de Carga Manual P7

**Document ID**: `P7_MANUAL_LOAD_CHECKLIST`  
**Milestone / Release**: `Milestone CORE-08 / Supervisor Offline Accepted / Phase P7 Hand-off`  
**Supervisor Offline Accepted**: `true` (Signoff Timestamp: `2026-09-17T14:20:00-07:00`)  
**State Contract**: `STATE: RUNTIME_PENDING_P7`  
**Operational Scope**: `offline/DEV [PRODUCT_EVIDENCE]` $\to$ `P7_MANUAL` (Awaiting physical field commissioning; no new offline phases)  
**Target Hardware**: Horner APG XL4 Prime OCS Series, Model `HE-XPCE2`  
**Programming Software**: Horner APG Cscape 10.2 (Build `10.2.751.4`)  
**Active Project Container**: `TankLevel_P5_Dedicated.csp`  
**Container SHA-256**: `9f69f6a2ee12dab54087ab27bb839f40e01d6d65544a546139788519acd80ab1` (Reference build: `2da72f913d80a13346452ba5c3dbb9f2bf61a0c4f8d22d64a2f8bdf969e6b66b`)  
**Protocol Driver**: `MJ1 CT RTU Modbus CMP v5.05` (`CTRtu.dll v5.5.0.0`, Modbus Master RTU)  
**Scan List Status**: **`EMPTY_UNTIL_LIVE`** (`count: 0`; planned 3 devices in `modbus_protocol_inventory.json` scanned only upon live bus connection)  
**Compiler / Hygiene Invariant**: `no_error_check_loop: true` (Clean build verified: 0 errors, 0 warnings; zero periodic polling loops)  
**Commissioning Engineer**: Armando Silva (Lead Controls / Commissioning Engineer)  
**Single GUI Automation Owner**: Exclusively maintained on `winsta0\Default` (PID `12788` / `928`)  
**Hardware Lockout Policy**: `NO_PLC_DOWNLOAD_FAIL_CLOSED` (`COM1..COM256`, companion flash utilities, Win32 IDs `32827`/`33149` locked fail-closed; do not start P7 download)  
**Governing Standard Operating Procedure**: [`P7_MANUAL_COMMISSIONING_PROCEDURE.md`](file:///C:/Users/ArmandoSilva/Downloads/P7_MANUAL_COMMISSIONING_PROCEDURE.md) (`SOP-P7-HORNER-COMMISSIONING-001`)  
**Supervisor Acceptance Pointer**: [`SUPERVISOR_OFFLINE_ACCEPTANCE.md`](file:///C:/Users/ArmandoSilva/Downloads/SUPERVISOR_OFFLINE_ACCEPTANCE.md)  
**Offline Evidence Bundle Pointer**: [`offline_evidence_bundle_v1.0.0.zip`](file:///C:/Users/ArmandoSilva/Downloads/offline_evidence_bundle_v1.0.0.zip) (`335,933` bytes, SHA-256: `16a1ac91445a9067c24617b61063ddf9585ef272af6fa1c707fd83f1d8fec512`)  

---

> [!CAUTION]
> **STRICTLY MANUAL LOADING ONLY — ZERO AUTOMATED DOWNLOADS — DO NOT START P7 DOWNLOAD**  
> Physical controller loading must be performed 100% manually by commissioning engineer Armando Silva via the Cscape 10.2 GUI when physical hardware is present. All automated scripts, FastMCP servers, and background agents are permanently locked out fail-closed from physical communication ports and download commands.
> 
> **Governing Execution Invariants**:
> 1. **Do Not Start P7 Download**: Automated flashing, serial polling, and command injection are strictly prohibited fail-closed.
> 2. **No Error Check Loop**: Periodic keep-alive or repetitive Error Check polling loops are forbidden; single-pass verification is complete.
> 3. **No New Offline Phases**: All offline phases (P0–P6/P8) are closed, verified, and formally accepted by the Supervisor. The system remains strictly in `RUNTIME_PENDING_P7`.

---

## 1. Primary Offline Evidence & Acceptance Pointers

Prior to initiating any physical connection or manual download, verify the approved offline documentation and cryptographic packages:

| Document / Package | Path / Reference | Description & Digest |
| :--- | :--- | :--- |
| **Supervisor Offline Acceptance** | [`SUPERVISOR_OFFLINE_ACCEPTANCE.md`](file:///C:/Users/ArmandoSilva/Downloads/SUPERVISOR_OFFLINE_ACCEPTANCE.md) | Formal engineering supervisor acceptance of all offline deliverables (Signoff: `2026-09-17T14:20:00-07:00`, `supervisor_offline_accepted = true`). |
| **Offline Evidence Bundle v1.1.0** | [`offline_evidence_bundle_v1.1.0.zip`](file:///C:/Users/ArmandoSilva/Downloads/offline_evidence_bundle_v1.1.0.zip) | Authoritative air-gapped distribution package (42 assets, `364,842` bytes, SHA-256: `3ebfc66e7489954a243c630b6eff46da819104f44cefae78305e5669de72bed9`). |
| **Field Verification Test Matrix** | [`CORE_08_09_10_FIELD_VERIFICATION_MATRIX.md`](file:///C:/Users/ArmandoSilva/Downloads/CORE_08_09_10_FIELD_VERIFICATION_MATRIX.md) | Definitive 23-test field verification matrix covering CORE-08 runtime, CORE-09 HMI/WebMI, and CORE-10 24h soak (`17,523` bytes, SHA-256: `515f769f77584b3baab575ae8d253c3a2ede5abcc9ae89fe1664e0ffc3a5e7ba`). |
| **Fresh Dedicated Bundle v1.1.0** | [`TankLevel_P5_Dedicated_offline_bundle_v1.1.0.zip`](file:///C:/Users/ArmandoSilva/Downloads/TankLevel_P5_Dedicated_offline_bundle_v1.1.0.zip) | Updated air-gapped distribution package with 3 pure ST POUs (`FB_ModbusScaleQuality`, `TankLevelControl`, `TankLevelModbusBridge`), `TankLevel_P5_Dedicated.csp`, and configs (`72,977` bytes, SHA-256: `98e53eec68d3c657b511bfd075de05f9349b9e37b9228ef51c40884bc578a7f7`). |
| **Runtime Gaps & Roadmap** | [`CORE_08_09_10_RUNTIME_GAPS_AND_ROADMAP.md`](file:///C:/Users/ArmandoSilva/Downloads/CORE_08_09_10_RUNTIME_GAPS_AND_ROADMAP.md) | Technical audit and roadmap for CORE-08 live runtime (RS-485 MJ1), CORE-09 physical HMI/WebMI, and CORE-10 24h soak (`11,745` bytes). |
| **Evidence Bundle v1.1.0 Manifest** | [`offline_evidence_bundle_v1.1.0_manifest.md`](file:///C:/Users/ArmandoSilva/Downloads/offline_evidence_bundle_v1.1.0_manifest.md) | Cryptographic SHA-256 table and invariant audit for all 42 archived evidence assets (`9,297` bytes). |
| **Offline Evidence Bundle v1.0.0** | [`offline_evidence_bundle_v1.0.0.zip`](file:///C:/Users/ArmandoSilva/Downloads/offline_evidence_bundle_v1.0.0.zip) | Prior air-gapped distribution package (30 assets, `335,933` bytes, SHA-256: `16a1ac91445a9067c24617b61063ddf9585ef272af6fa1c707fd83f1d8fec512`). |
| **MJ1 Scan List Evidence** | [`mj1_devices_scan_list_state_evidence.md`](file:///C:/Users/ArmandoSilva/Downloads/mj1_devices_scan_list_state_evidence.md) | Baseline report confirming `MJ1 CT RTU Modbus CMP v5.05` configuration and empty scan list offline. |
| **P5 Native Reopen Proof** | [`tanklevel_p5_native_reopen_proof_evidence.md`](file:///C:/Users/ArmandoSilva/Downloads/tanklevel_p5_native_reopen_proof_evidence.md) | Verification of `TankLevel_P5_Dedicated.csp` active in Cscape GUI (`PID 12788`, HWND `3016360`) with pure ST scaling bridge. |
| **Manual Commissioning SOP** | [`P7_MANUAL_COMMISSIONING_PROCEDURE.md`](file:///C:/Users/ArmandoSilva/Downloads/P7_MANUAL_COMMISSIONING_PROCEDURE.md) | Standard Operating Procedure `SOP-P7-HORNER-COMMISSIONING-001` governing physical execution. |

---

## 2. English Checklist (Step-by-Step SOP Alignment)

### Pre-Connection & Electrical Safety (Steps 1–3)
- [ ] **Step 1 - Pre-Commissioning Project Backup**:
  - Connect to existing PLC (if replacing or servicing) or insert removable media.
  - Back up current controller program, system configuration, and register values prior to any memory write.
- [ ] **Step 2 - Hardware Model & Power Verification**:
  - Verify physical nameplate: Horner APG Model **`HE-XPCE2`** (XL4 Prime, CsCAN).
  - Verify clean 24VDC control power (`+24V`, `0V`) and proper earth grounding.
  - Confirm OCS boots cleanly to system splash screen without hardware watchdog fault codes.
  - Confirm OCS firmware compatibility with Cscape 10.2 (Build 15.40+).
- [ ] **Step 3 - LOTO & Field Output Electrical Safety**:
  - Execute Lockout/Tagout (LOTO) on field actuators: inlet pump contactor `%Q1` and solenoid drain valve `%Q2`.
  - Confirm zero-energy state on all 24VDC actuator loops and 480VAC pump power feeds.

### Workstation Setup & Protocol Configuration Audit (Steps 4–5)
- [ ] **Step 4 - Approved Project Container & Modbus Protocol Integrity**:
  - Locate `TankLevel_P5_Dedicated.csp` in workstation project root.
  - Verify container SHA-256 matches:  
    `9f69f6a2ee12dab54087ab27bb839f40e01d6d65544a546139788519acd80ab1` (or live mounted build: `2da72f913d80a13346452ba5c3dbb9f2bf61a0c4f8d22d64a2f8bdf969e6b66b`).
  - Open project in Cscape 10.2 (`Ctrl+O`) or verify active instance on `winsta0\Default`.
  - Confirm Project Navigator hierarchy:
    - Hardware Configuration: **`HE-XPCE2`**
    - Logic Modules: `[ST] STBlock1` (`TankLevelControl`), Scaling Bridge POUs (`FB_ModbusScaleQuality.st`, `TankLevelModbusBridge.st`)
    - Protocol Driver: **`MJ1 CT RTU Modbus CMP v5.05`** (`CTRtu.dll v5.5.0.0`, Modbus Master RTU, Half-Duplex RS-485, 19200 baud, 8-N-1)
  - **Confirm Scan List Table: Empty until live**:
    - Verify native scan list on `MJ1` is currently **empty** (`count: 0`, `scan_list_status: "empty"`).
    - Note: Native scan list population was blocked offline (`blocked_offline`) by design to prevent CFBF corruption and offline timeout faults.
    - Confirm planned device inventory is documented in [`modbus_protocol_inventory.json`](file:///C:/Users/ArmandoSilva/Downloads/modbus_protocol_inventory.json) for live configuration:
      - `DEV_LT01` (Unit ID 1): Buffer Tank Level Transmitter (`%AI1`, Modicon `40001`, 0..100.0 %)
      - `DEV_FT01` (Unit ID 2): Inflow Coriolis Flowmeter (`%AI2`, Modicon `40002`, 0..500.0 L/min)
      - `DEV_PT01` (Unit ID 3): Discharge Pressure Transmitter (`%AI3`, Modicon `40003`, 0..10.0 bar)
- [ ] **Step 5 - Clean Compilation Error Check (No Polling Loops)**:
  - In Cscape 10.2, dispatch single-pass **Program -> Error Check** (`Ctrl+F8` / Win32 ID `32826`).
  - Verify Output Window reports exactly **`0 errors`** and **`0 warnings`**.
  - Maintain rule: zero background Error Check polling loops (`no_error_check_loop: true`).
  - Do NOT proceed if any compiler error or warning is reported.

### Communication & Manual Download (Steps 6–7)
- [ ] **Step 6 - Physical Cable Connection**:
  - Connect USB Type-A to Mini-B programming cable from workstation to OCS Mini-B port (or serial MJ1 programming cable `HE-XCK`/`HE-CPK`).
  - Open **Controller -> Communication...**; select **USB (Auto Detect)** or valid serial port.
  - Confirm Cscape status bar transitions to **`Local: Connected (Node 253)`** or **`Target: OK`**.
- [ ] **Step 7 - Strictly Manual Cscape Download**:
  - Armando Silva manually initiates **Controller -> Download** (`Ctrl+F9`).
  - Ensure checked: **Logic Program**, **System/Hardware Configuration**, **Protocol Configuration** (`MJ1 CT RTU Modbus CMP v5.05`), and **Screens/Graphics**.
  - Click **OK / Download**; wait for progress bar to reach `100%`.
  - Confirm "Download Complete". When prompted to transition to RUN mode, select **No** (remain in STOP for initial I/O audit).

### Mode Transition & Post-Load Telemetry (Steps 8–9)
- [ ] **Step 8 - Transition to RUN Mode & Telemetry Loop Check**:
  - Open **View -> Data Watch** in Cscape; add `%AI1..%AI3`, `%R1`, `%R3`, `%M10..%M15`, `%Q1`, and IEC bridge registers `%R101`, `%R103`, `%R105`.
  - Transition controller to **RUN** mode via Cscape menu **Controller -> Run** or OCS System Menu.
  - Once live field devices are connected to `MJ1` RS-485 bus and scan list transactions are activated:
    - Verify live telemetry: `%AI1` receives raw counts (0..32000), `%R101` computes scaled percentage (0.0..100.0%).
    - Verify inflow rate: `%AI2` receives raw counts, `%R103` computes scaled flow (0.0..500.0 L/min).
    - Verify discharge pressure: `%AI3` receives raw counts, `%R105` computes scaled pressure (0.0..10.0 bar).
    - Verify communication health: `%M10 = 0`, `%M12 = 0`, `%M14 = 0` (All Healthy).
  - Execute fail-safe quality clamp test: Disconnect Modbus cable from `MJ1` for > 2.0s; verify `%M10 = 1`, `%M11 = 1`, and `%R101` clamps to `0.0%`. Reconnect and confirm recovery.
- [ ] **Step 9 - Formal Commissioning Sign-Off**:
  - Complete and sign the physical Sign-Off Sheet in Section 9 of `P7_MANUAL_COMMISSIONING_PROCEDURE.md`.
  - Advance to Milestone **CORE-09** (HMI & WebMI screen verification) and **CORE-10** (24h hardware telemetry soak).

---

## 3. Lista de Verificación en Español (Alineación Paso a Paso con SOP)

### Seguridad Eléctrica y Previa a la Conexión (Pasos 1–3)
- [ ] **Paso 1 - Respaldo Previo a la Puesta en Servicio**:
  - Conectar al PLC existente (si es reemplazo o mantenimiento) o insertar memoria extraíble.
  - Respaldar el programa actual, la configuración de hardware y los registros antes de sobrescribir memoria.
- [ ] **Paso 2 - Verificación de Modelo de Hardware y Alimentación**:
  - Verificar placa física del controlador: Horner APG Modelo **`HE-XPCE2`** (XL4 Prime, CsCAN).
  - Confirmar alimentación limpia de 24VDC (`+24V`, `0V`) y puesta a tierra adecuada.
  - Confirmar que el OCS arranca limpiamente en la pantalla de bienvenida sin códigos de falla de watchdog de hardware.
  - Confirmar compatibilidad de firmware con Cscape 10.2 (Build 15.40+).
- [ ] **Paso 3 - Bloqueo/Etiquetado (LOTO) y Seguridad Eléctrica de Salidas**:
  - Ejecutar Bloqueo y Etiquetado (LOTO) en actuadores de campo: contactor de bomba `%Q1` y válvula solenoide `%Q2`.
  - Confirmar estado de energía cero en lazos de 24VDC y líneas de fuerza de motores de 480VAC.

### Preparación de Estación y Auditoría de Protocolo Modbus (Pasos 4–5)
- [ ] **Paso 4 - Integridad del Contenedor de Proyecto y Configuración de Protocolo**:
  - Localizar `TankLevel_P5_Dedicated.csp`.
  - Verificar que el hash SHA-256 coincida con:  
    `9f69f6a2ee12dab54087ab27bb839f40e01d6d65544a546139788519acd80ab1` (o compilación activa: `2da72f913d80a13346452ba5c3dbb9f2bf61a0c4f8d22d64a2f8bdf969e6b66b`).
  - Abrir proyecto en Cscape 10.2 (`Ctrl+O`) o verificar sesión activa en `winsta0\Default`.
  - Confirmar estructura en Project Navigator:
    - Configuración de Hardware: **`HE-XPCE2`**
    - Módulos Lógicos: `[ST] STBlock1` (`TankLevelControl`), POUs de Puente de Escalamiento (`FB_ModbusScaleQuality.st`, `TankLevelModbusBridge.st`)
    - Controlador de Protocolo: **`MJ1 CT RTU Modbus CMP v5.05`** (`CTRtu.dll v5.5.0.0`, Modbus Master RTU, RS-485 Semidúplex, 19200 baudios, 8-N-1)
  - **Confirmar Lista de Escaneo: Vacía hasta conexión en vivo**:
    - Verificar que la lista de escaneo nativa en `MJ1` esté actualmente **vacía** (`count: 0`, `scan_list_status: "empty"`).
    - Nota: La población de la lista de escaneo se bloqueó de forma segura fuera de línea (`blocked_offline`) para evitar corrupción CFBF y fallas por timeout.
    - Confirmar que el inventario de dispositivos planeados esté registrado en [`modbus_protocol_inventory.json`](file:///C:/Users/ArmandoSilva/Downloads/modbus_protocol_inventory.json) para configuración en vivo:
      - `DEV_LT01` (Unit ID 1): Transmisor de Nivel de Tanque (`%AI1`, Modicon `40001`, 0..100.0 %)
      - `DEV_FT01` (Unit ID 2): Medidor de Flujo Coriolis (`%AI2`, Modicon `40002`, 0..500.0 L/min)
      - `DEV_PT01` (Unit ID 3): Transmisor de Presión de Descarga (`%AI3`, Modicon `40003`, 0..10.0 bar)
- [ ] **Paso 5 - Verificación de Compilación Limpia (Sin Bucles de Sondeo)**:
  - En Cscape 10.2, ejecutar una sola pasada de **Program -> Error Check** (`Ctrl+F8` / Win32 ID `32826`).
  - Confirmar que la ventana de salida reporte exactamente **`0 errores`** y **`0 advertencias`**.
  - Mantener la directiva: cero bucles de Error Check en segundo plano (`no_error_check_loop: true`).
  - NO proceder si se reporta algún error o advertencia de compilación.

### Comunicación y Descarga Manual (Pasos 6–7)
- [ ] **Paso 6 - Conexión Física del Cable de Programación**:
  - Conectar cable USB Tipo-A a Mini-B (o cable serial MJ1 `HE-XCK`/`HE-CPK`) desde la estación de ingeniería al OCS.
  - Abrir **Controller -> Communication...**; seleccionar **USB (Auto Detect)** o puerto COM correspondiente.
  - Confirmar que la barra de estado de Cscape cambie a **`Local: Connected (Node 253)`** o **`Target: OK`**.
- [ ] **Paso 7 - Descarga Estrictamente Manual en Cscape**:
  - Armando Silva ejecuta manualmente **Controller -> Download** (`Ctrl+F9`).
  - Asegurar selección de: **Programa Lógico**, **Configuración de Hardware**, **Configuración de Protocolo** (`MJ1 CT RTU Modbus CMP v5.05`) y **Pantallas/Gráficos**.
  - Hacer clic en **Aceptar / Download**; esperar que la barra de progreso alcance el `100%`.
  - Confirmar mensaje de descarga exitosa. Si el sistema solicita pasar a modo RUN, seleccionar **No** (permanecer en STOP para auditoría inicial de E/S).

### Transición de Modo y Telemetría Posterior a la Carga (Pasos 8–9)
- [ ] **Paso 8 - Transición a Modo RUN y Verificación de Telemetría**:
  - Abrir **View -> Data Watch** en Cscape; monitorear `%AI1..%AI3`, `%R1`, `%R3`, `%M10..%M15`, `%Q1`, y registros puente IEC `%R101`, `%R103`, `%R105`.
  - Pasar el controlador a modo **RUN** mediante el menú **Controller -> Run** o el Menú del Sistema en pantalla.
  - Una vez conectados los transmisores físicos a la red RS-485 del puerto `MJ1`:
    - Verificar telemetría en vivo: `%AI1` recibe cuentas crudas (0..32000), `%R101` calcula porcentaje escalado (0.0..100.0%).
    - Verificar caudal de entrada: `%AI2` recibe cuentas crudas, `%R103` calcula caudal (0.0..500.0 L/min).
    - Verificar presión de descarga: `%AI3` recibe cuentas crudas, `%R105` calcula presión (0.0..10.0 bar).
    - Verificar salud de comunicación: `%M10 = 0`, `%M12 = 0`, `%M14 = 0` (Todos Saludables).
  - Probar clamping seguro ante pérdida de comm: Desconectar cable Modbus en `MJ1` por > 2.0s; verificar que `%M10 = 1`, `%M11 = 1`, y `%R101` se fija inmediatamente en `0.0%`. Reconectar y confirmar recuperación.
- [ ] **Paso 9 - Firma Formal de Puesta en Servicio**:
  - Completar y firmar la Hoja de Validación Física en la Sección 9 de `P7_MANUAL_COMMISSIONING_PROCEDURE.md`.
  - Continuar con el Hito **CORE-09** (verificación de pantallas HMI y WebMI) y **CORE-10** (prueba de estabilidad de telemetría de 24 horas).

---

## 4. Operational Caveat: Cscape 10.2 Safe "Save As" Workaround

> [!WARNING]
> **Cscape Save Warning (`save_failed_caveat.txt`)**:
> In Cscape 10.2 (Build 10.2.751.4), direct `File -> Save` (`Ctrl+S` / Win32 ID `57603`) can intermittently trigger modal dialog:  
> **`"Failed to save document."`** (`AFX_IDP_FAILED_TO_SAVE_DOC = 0xF183`) due to CFBF storage locking.
> 
> **Safe Workaround**:
> - Never use blind `Ctrl+S` when modifying project files.
> - Always execute **File -> Save As...** (`ID_FILE_SAVEAS = 57604`) specifying a distinct versioned filename.

---

## 5. Modbus CORE-08 State & Governance Contract

```yaml
state_contract: "STATE: CORE-08 CONFIG_AND_TEST_OK RUNTIME_PENDING_P7"
supervisor_offline_accepted: true
supervisor_signoff_timestamp: "2026-09-17T14:20:00-07:00"
supervisor_acceptance_file: "Downloads/SUPERVISOR_OFFLINE_ACCEPTANCE.md"
offline_evidence_bundle: "Downloads/offline_evidence_bundle_v1.0.0.zip"
offline_evidence_bundle_sha256: "16a1ac91445a9067c24617b61063ddf9585ef272af6fa1c707fd83f1d8fec512"
operational_mode: "offline/DEV [PRODUCT_EVIDENCE]"
new_offline_phases_allowed: false
verified_live: false
plc_download: false
no_error_check_loop: true
phase_p7_status: "DEFERRED_MANUAL_ENGINEER_LOAD"
single_gui_owner: "winsta0\\Default (Cscape PID 12788)"
hardware_lockout: "BLOCKED_FAIL_CLOSED (COM1..COM256, companion binaries, Win32 32827/33149)"
approved_container: "TankLevel_P5_Dedicated.csp"
container_sha256: "9f69f6a2ee12dab54087ab27bb839f40e01d6d65544a546139788519acd80ab1"
container_live_sha256: "2da72f913d80a13346452ba5c3dbb9f2bf61a0c4f8d22d64a2f8bdf969e6b66b"
protocol_driver: "MJ1 CT RTU Modbus CMP v5.05 (CTRtu.dll v5.5.0.0)"
scan_list_status: "EMPTY_UNTIL_LIVE"
planned_devices_sidecar: "modbus_protocol_inventory.json (DEV_LT01, DEV_FT01, DEV_PT01)"
commissioning_engineer: "Armando Silva"
commissioning_sop: "P7_MANUAL_COMMISSIONING_PROCEDURE.md (SOP-P7-HORNER-COMMISSIONING-001)"
next_milestones:
  - "CORE-09: HMI & WebMI Physical Screen Verification"
  - "CORE-10: Hardware Telemetry Soak & Field Verification"
```
