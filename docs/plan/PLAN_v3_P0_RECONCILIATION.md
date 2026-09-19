# Plan v3 - Fase P0: Reconciliación Dual-Root, Contrato del Producto y Diagnóstico de Evolución

**MISSION_ID**: `P0_RECONCILIATION_CONTRACT_AUDIT`  
**Run ID**: `run_20260915_p0`  
**Fecha de Ejecución**: 2026-09-15  
**Repositorio Real**: `C:\HornerAI\horner-cscape-mcp`  
**Snapshot / Entorno Usuario**: `C:\Users\ArmandoSilva`  
**Regla Rectora**: `RULE[C:\Users\ArmandoSilva\AGENTS.md]`  
**Estado de Puerta**: **G2+/G5 estrictamente NO RUN / NO APROBADAS (Invariante histórico preservado)**  
**Modo Operativo**: `offline/DEV if Disconnected` (Fail-Closed Air-Gapped)

---

## 1. Reconciliación Dual-Root (Sin Sobrescribir Cambios)

Se auditó de manera no destructiva la estructura entre el repositorio real (`C:\HornerAI\horner-cscape-mcp`) y el snapshot (`C:\Users\ArmandoSilva`).

### 1.1 Uniones NTFS (Directory Junctions) Verificadas
Las siguientes rutas en `C:\Users\ArmandoSilva\` son uniones NTFS directas hacia `C:\HornerAI\horner-cscape-mcp`, garantizando cero desfase y sincronización instantánea a nivel de sistema de archivos:
- `src` -> `C:\HornerAI\horner-cscape-mcp\src`
- `scripts` -> `C:\HornerAI\horner-cscape-mcp\scripts`
- `.venv` -> `C:\HornerAI\horner-cscape-mcp\.venv`

### 1.2 Paridad de Archivos Raíz y Subdirectorios
- **Archivos Raíz** (`AGENTS.md`, `README.md`, `CAPABILITY_MATRIX.md`, `CHANGELOG.md`, `FINAL_REPORT.md`, `TASKS.md`, `pyproject.toml`, `C1_ACCEPTANCE.md`, `C6_ACCEPTANCE.md`): **100% idénticos byte por byte** (SHA-256 idénticos, 0 diferencias).
- **Test Suites (`tests/`)**: 230 archivos Python de pruebas unitarias y de integración son **100% idénticos** (0 diferencias).
- **Documentación (`docs/`)**: 16 archivos markdown en paridad criptográfica 100% (0 diferencias).
- **Ejemplos (`examples/`)**: 22 archivos en paridad criptográfica 100% (0 diferencias).
- **Cuarentena K5 (`quarantine/`)**: 30 archivos en cuarentena estricta en paridad criptográfica 100% (0 diferencias).
- **Estado Interno (`.state/`)**: `phase_status.json` y `progress.json` en paridad criptográfica 100% (0 diferencias).
- **Fixtures (`fixtures/`)**: Se reconcilió `fixtures/st_library/pump_lead_lag_alternator.st` hacia el snapshot sin sobrescribir ningún archivo existente.
- **Artefactos (`artifacts/`)**:
  - Los 89 artefactos de auditoría de recuperación de `run_20260906_120831` se encuentran sincronizados.
  - Los artefactos de telemetría y capturas de pantalla de ejecuciones GUI recientes se preservan intactos sin sobrescrituras en ambos árboles.

---

## 2. Publicación del Contrato del Producto

El servidor **Horner Cscape MCP** proporciona una pasarela automatizada entre modelos de lenguaje / agentes de ingeniería y el entorno Horner APG Cscape 10.2, operando bajo las siguientes especificaciones contractuales formales:

### 2.1 Protocolo y Arquitectura
- **Protocolo**: FastMCP / Model Context Protocol (MCP) sobre transporte `stdio` conforme a JSON-RPC 2.0.
- **Servidor**: `horner-cscape-mcp` v1.0.0.
- **Entrada Principal**: `scripts/run_mcp_server.py`.

### 2.2 Contrato Canónico de 4 Estados
Toda respuesta de herramienta MCP y aserción de prueba debe retornar estrictamente el esquema de 4 estados:
```json
{
  "status": "success | failed | blocked | inconclusive",
  "error_code": "STRING_ENUM_OPTIONAL",
  "details": "Descripción factual del resultado",
  "data": {}
}
```
- **`success`**: Operación ejecutada determinísticamente sin errores de sintaxis, violaciones de política ni advertencias no gestionadas.
- **`failed`**: Error de sintaxis ST (`ST_SYNTAX_ERROR`), inyección de lógica ladder (`ERR_LADDER_FORBIDDEN`), o fallo en aserciones de compilación/simulación.
- **`blocked`**: Operación interceptada por guardas de seguridad fail-closed (puertos COM/USB/CAN, comandos Win32 de descarga `32827`/`33149`, utilidades de flasheo) o limitaciones de la plataforma (conversión ST->LD nativa no existente).
- **`inconclusive`**: Precondiciones del entorno no verificadas o GUI no lista.
- **Invariante**: Queda prohibido inventar o reportar pseudo-estados tales como `VERIFIED`, `100%` o `PERFECT`.

### 2.3 Modelo de Memoria OCS Horner
Soporta formalmente el direccionamiento y mapeo de registros del OCS:
- Registros analógicos y de retención: `%R` (ej. `%R100`)
- Entradas analógicas: `%AI` (ej. `%AI1`)
- Salidas analógicas: `%AQ` (ej. `%AQ1`)
- Entradas digitales: `%I` (ej. `%I1`)
- Salidas digitales: `%Q` (ej. `%Q1`)
- Bits internos (markers): `%M` (ej. `%M1`)
- Temporizadores / Contadores: `%T`
- Registros del sistema: `%SR` (ej. `%SR43`)
- Banderas del sistema: `%S` (ej. `%S1` first scan)
- Red global CsCAN: `%IG`, `%QG`, `%AIG`, `%AQG`

### 2.4 Catálogo de 23 Herramientas MCP
1. `cscape_launch_ide`: Lanzamiento y supervisión de Cscape 10.2 en `winsta0\Default`.
2. `cscape_new_iec_project`: Creación de contenedor nativo CFBF `.csp`/`.cpj`.
3. `cscape_open_project`: Apertura y verificación de integridad CFBF OLE2.
4. `cscape_insert_st`: Inserción de código ST puro con validación AST.
5. `cscape_insert_st_pou`: Inserción transaccional de POU Structured Text con rollback.
6. `cscape_compile`: Ejecución de Error Check (`ID_PROGRAM_ERRORCHECK = 32826`).
7. `cscape_get_build_output`: Raspado y análisis de líneas del ListBox de salida.
8. `cscape_read_variables`: Inspección de variables mapeadas OCS en modo offline/mock.
9. `cscape_write_variables`: Escritura de variables mapeadas OCS en modo offline/mock.
10. `cscape_import_variables`: Importación de catálogo de tags (CSV/XML).
11. `cscape_export_variables`: Exportación de catálogo de tags (CSV/XML).
12. `cscape_run_simulation`: Simulación multi-ciclo en memoria.
13. `cscape_create_project`: Wrapper de inicialización de proyecto nativo.
14. `cscape_add_st_pou`: Wrapper de adición de POU ST.
15. `cscape_validate_st`: Validación sintáctica estricta y bloqueo de ladder (`ERR_LADDER_FORBIDDEN`).
16. `cscape_inspect_variables`: Inspección estructurada de tags y registros.
17. `cscape_compile_project`: Compilación de proyecto y diagnóstico AST offline.
18. `cscape_get_diagnostics`: Localización de diagnósticos sintácticos y semánticos.
19. `cscape_simulate_pou`: Simulación determinista de POU con snapshot de registros.
20. `cscape_export_project`: Exportación de proyecto a formato estructurado JSON/CFBF.
21. `cscape_simulate_cycle`: Ejecución de un único ciclo de scan de simulación.
22. `cscape_read_register`: Lectura aislada de registro Horner simulado.
23. `cscape_write_register`: Escritura aislada de registro Horner simulado.

---

## 3. Detección de Instrucciones ST-Only y No-Download que Requieren Evolución Explícita

### 3.1 Instrucciones ST-Only
1. **Rechazo de Construcciones Ladder en Código Fuente**:
   - *Estado Actual*: El parser ST rechaza cualquier constructo ladder (`---[ ]---`, `---[/]---`, `---( )---`, `---(S)---`, `---(R)---`, `RUNG`, `NETWORK`, `XIC`, `OTE`) con el código `ERR_LADDER_FORBIDDEN`.
   - *Realidad Nativa*: Cscape 10.2 no posee comandos de menú, aceleradores ni DLL exports para conversión ST->LD (`BLOCKED_NATIVE: DOCUMENT_ONLY`).
   - *Evolución Requerida*: 
     - Extender la gramática AST de ST para admitir declaraciones formales de tipos derivados (`TYPE ... END_TYPE`, `STRUCT`, `ENUM`).
     - Separar explícitamente el validador AST offline de la síntesis de diagramas de contactos (la cual debe quedar exclusivamente como visualización read-only sin alterar el archivo `.st` ni el contenedor CFBF).
     - Inyección directa de streams binarios ST en contenedores CFBF sin depender de la automatización frágil de portapapeles/ventanas MFC.

### 3.2 Instrucciones No-Download
1. **Bloqueo Incondicional de Puertos Físicos y Flasheo**:
   - *Estado Actual*: Todo acceso a puertos `COM1`..`COM256`, `\\.\COM*`, `/dev/tty*`, `CAN*`, `USB*`, comandos Win32 `32827` (`ID_PROGRAM_DOWNLOAD`) y `33149` (`ID_CONTROLLER_DOWNLOAD`), o utilidades de flasheo (`PGMUpdateUtility.exe`) es interceptado y retorna `status: blocked` con `SecurityError` / `HardwareLockoutError`.
   - *Evolución Requerida*:
     - **Modo Dual Explícito (`offline/DEV [TESTED_MOCK]`)**: Las herramientas de lectura/escritura de variables deben proveer telemetría explícita de procedencia (encabezados `provenance: emulated_in_memory`), diferenciando de forma inequívoca entre una lectura de hardware bloqueada y una lectura en entorno de simulación desacoplado.
     - **Empaquetado de Exportación Air-Gapped**: Generar un pipeline de empaquetado para distribución física fuera de línea (manifiesto SHA-256 de archivos CFBF compilados), permitiendo a un operador humano transferir el binario vía medios extraíbles sin que el agente interactúe con puertos de comunicación.
     - **Captura Estructurada de Diálogos Modales de Error**: En lugar de limitarse a cerrar diálogos `#32770` con `IDNO` (7) de forma reactiva, implementar un recolector de texto que extraiga la lista de advertencias y errores no fatales antes del descarte seguro.

---

## 4. Política de Bloqueo de Operaciones Físicas (Fail-Closed)

Se reitera la vigencia inquebrantable de la política de seguridad:

| Entidad Restringida | Rango / Identificadores | Acción de Cumplimiento |
| :--- | :--- | :--- |
| **Puertos Serie / COM** | `COM1`–`COM256`, `\\.\COM*`, `/dev/tty*` | Bloqueo duro; lanza `SecurityError` |
| **Buses de Campo** | `CAN*`, `CsCAN`, `DeviceNet`, `Profibus` | Bloqueo duro de sockets y adaptadores |
| **Depuradores / USB** | `USB*`, `JTAG`, `SWD`, Dongles hardware | Bloqueo a nivel de argumentos y llamadas |
| **Binarios de Flasheo** | `PGMUpdateUtility.exe`, `DfuSeCommand.exe`, `STMFlashLoader.exe`, `WinJTAG.exe` | Prohibida su ejecución; monitored and killed |
| **Switches CLI Descarga** | `/d`, `/download`, `/flash`, `/burn`, `/write-flash` | Invocación rechazada |
| **Comandos Win32 Descarga** | `ID_PROGRAM_DOWNLOAD` (32827), `ID_CONTROLLER_DOWNLOAD` (33149) | Intercepción de mensajes Win32; retorno `blocked` |
| **Infiltración Ladder en ST** | Rungs, contactos, bobinas (`---[ ]---`, `---( )---`, `NETWORK`, `RUNG`) | Rechazo con `ERR_LADDER_FORBIDDEN` |

---

## 5. Inventario de Versiones, Sesión, Recursos y Transporte MCP

### 5.1 Versiones de Software y Entorno
- **Sistema Operativo**: Microsoft Windows 11 Enterprise (Build 26200, 64-bit)
- **Host Cscape IDE**: Horner APG Cscape 10.2 (Build 10.2.751.4, x86 PE)
- **Ruta Cscape**: `C:\Program Files (x86)\Cscape 10.2\Cscape.exe`
- **Entorno Python**: Python 3.12.10 en `.venv` (`C:\HornerAI\horner-cscape-mcp\.venv`)
- **Versión FastMCP / Protocolo**: Servidor `horner-cscape-mcp` v1.0.0, protocolo JSON-RPC 2.0
- **Dependencias Clave**: pytest 9.1.1, pluggy 1.6.0, anyio 4.15.0, pydantic 2.x

### 5.2 Sesión y Estado GUI en Vivo
- **Escritorio Interactivo**: `winsta0\Default` (Sesión de usuario interactiva 2)
- **Procesos Cscape Activos Detectados**:
  - PID: `9340` | HWND: `0x00070088` | Título: `Cscape - Logged In : "armando@controlnautas.com" - [TankLevelClosedLoop.csp]`
  - PID: `5156` | HWND: `0x00010460` | Título: `Cscape - Logged In : "armando@controlnautas.com" - [TankLevelClosedLoop.csp]`
- **Estado de Conexión en Barra de Estado**: `Disconnected`
- **Clasificación Operativa**: `offline/DEV if Disconnected` (sin enlace a hardware físico)

### 5.3 Catálogo de Recursos MCP (`cscape://`)
- `cscape://projects`: Inventario JSON de proyectos OLE2 CFBF bajo gestión.
- `cscape://project/{project_name}/state`: Estado interno, metadatos y lista de POUs del proyecto.
- `cscape://project/{project_name}/diagnostics`: Diagnósticos AST offline y registros de compilación.
- `cscape://templates`: Catálogo de plantillas estandarizadas IEC 61131-3 Structured Text.
- `cscape://template/{template_name}`: Código fuente ST de la plantilla seleccionada.
- `cscape://safety/status`: Estado de verificación de aislamiento y bloqueo de puertos físicos.
- `cscape://registers/state`: Snapshot en tiempo real de la tabla de registros Horner OCS emulados.

### 5.4 Transporte MCP
- **Canal de Transporte**: `stdio` (Standard Input / Standard Output)
- **Encapsulación**: JSON-RPC 2.0
- **Punto de Ejecución**: `scripts/run_mcp_server.py` invocando `server.run(transport="stdio")`

---

## 6. Estado de Puertas e Invariantes Históricos

- **Puertas Históricas**: Todas las puertas pasadas (G0..G5 de Megaplan) se reconocen estrictamente como **registros históricos archivados**.
- **Invariante de Cierre**: Las puertas **G2+, G3, G4 y G5 permanecen formalmente cerradas / no ejecutadas** en el contexto de este ciclo. No se declara victoria ni estado 100% de puertas históricas sin pruebas activas y evidencia formal generada en la corrida actual.
- **Sin Simulador Adicional**: Se preserva exclusivamente el motor de ciclo de scan en memoria (`src/cscape/simulation.py`, `src/simulation/simulator.py`); no se ha creado ningún simulador secundario ni dependencias Straton K5.
- **Cero Descargas al PLC**: Todas las operaciones permanecen aisladas del hardware.

---

## 7. Única Próxima Tarea

**Tarea P1 del Plan v3**:
`P1: Evolución explícita del pipeline de diagnósticos ST AST y empaquetado de exportación air-gapped (sin bypass de seguridad ni mutación no autorizada)`
- **Alcance**: 
  1. Extensión del validador AST de Structured Text para dar soporte a estructuras de tipos definidas por el usuario (`STRUCT`, `ENUM`) y verificación semántica de rangos en variables OCS.
  2. Implementación de una herramienta MCP formal de empaquetado air-gapped (`cscape_package_offline_bundle`) que genere manifiestos SHA-256 sin requerir ni permitir descarga directa a PLC.
  3. Integración de extracción de diagnósticos de error en diálogos modales `#32770` previo a su cierre fail-closed con `IDNO`.
