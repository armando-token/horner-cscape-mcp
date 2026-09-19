# Horner Cscape MCP - Contrato Formal del Producto

**Versión del Contrato**: `1.0.0`  
**Servidor MCP**: `horner-cscape-mcp`  
**Protocolo**: Model Context Protocol (FastMCP) sobre `stdio` (JSON-RPC 2.0)  
**Host Destino**: Horner APG Cscape 10.2 (Build 10.2.751.4, x86 PE)  
**Regla Rectora**: `RULE[C:\Users\ArmandoSilva\AGENTS.md]`  
**Entorno de Ejecución**: Windows 11 Enterprise (64-bit) / Python 3.12.10 (`.venv`)  
**Modo Operativo**: `offline/DEV if Disconnected` (Air-Gapped, Fail-Closed)

---

## 1. Misión y Propósito del Producto

El servidor **Horner Cscape MCP** proporciona un puente de integración robusto, determinista y seguro entre agentes de ingeniería de inteligencia artificial y la plataforma de automatización industrial **Horner APG Cscape 10.2**.

El producto implementa las siguientes garantías inviolables:
1. **Puro IEC 61131-3 Structured Text (ST)**: Todo código generado o validado se analiza mediante AST en Structured Text puro. Cualquier intento de inyección de lógica de escalera (contactos, bobinas, rungs, nemónicos ladder) es rechazado inmediatamente con `ERR_LADDER_FORBIDDEN` con cero mutación en disco.
2. **Aislamiento y Bloqueo de Hardware Físico (Fail-Closed)**: Queda terminantemente bloqueada toda comunicación con puertos físicos seriales (`COM1`..`COM256`), CAN, USB o JTAG, así como la invocación de utilidades de flasheo (`PGMUpdateUtility.exe`, etc.) o comandos de descarga al controlador (`32827`, `33149`).
3. **Contenedores Nativos CFBF / OLE2**: Manipulación de archivos nativos de proyecto `.csp` y `.cpj` sin dependencia de formatos de terceros obsoletos.
4. **Cuarentena Estricta de Straton K5**: Cero dependencias activas de Straton K5 (`appli.k5p`, `T5RTI`, `T5SIMUL`). Los activos heredados permanecen aislados bajo `quarantine/straton_k5_legacy/`.

---

## 2. Contrato Canónico de 4 Estados

Toda herramienta MCP, endpoint de recurso y runner de verificación responde obligatoriamente bajo el esquema canónico de 4 estados:

```json
{
  "status": "success | failed | blocked | inconclusive",
  "error_code": "STRING_ENUM_OPTIONAL",
  "details": "Descripción factual del resultado",
  "data": {}
}
```

### Definición de Estados
- **`success`**: Operación ejecutada determinísticamente, sin advertencias no controladas, cumpliendo todas las aserciones y generando evidencia comprobable.
- **`failed`**: Operación fallida por causas de dominio del código: error de sintaxis ST (`ST_SYNTAX_ERROR`), violación de restricción ladder (`ERR_LADDER_FORBIDDEN`), o fallo en aserción de compilación/simulación.
- **`blocked`**: Operación interceptada activamente por las políticas de seguridad (intento de apertura de puertos COM, comandos de descarga Win32 `32827`/`33149`, ejecución de utilidades de flasheo) o limitaciones físicas/arquitectónicas documentadas (conversión nativa ST->LD no disponible en Cscape 10.2: `BLOCKED_NATIVE: DOCUMENT_ONLY`).
- **`inconclusive`**: Entorno no preparado, GUI de Cscape no responsiva o precondiciones no verificadas.
- **Prohibición Expresa**: Queda terminantemente prohibido emitir o aceptar pseudo-estados subjetivos como `VERIFIED`, `100%`, `PERFECT` o `DONE`.

---

## 3. Modelo de Registros y Memoria Horner OCS

El servidor soporta el mapeo estandarizado de la arquitectura de memoria del controlador Horner OCS:

| Prefijo OCS | Tipo de Registro | Tipo de Dato | Rango Habitual | Semántica / Uso |
| :--- | :--- | :--- | :--- | :--- |
| `%R` | Holding Registers | `WORD` / `INT` / `REAL` | `%R1` – `%R9999` | Registros analógicos generales y retentivos |
| `%AI` | Analog Inputs | `INT` / `WORD` | `%AI1` – `%AI512` | Entradas analógicas directas de hardware |
| `%AQ` | Analog Outputs | `INT` / `WORD` | `%AQ1` – `%AQ512` | Salidas analógicas directas |
| `%I` | Digital Inputs | `BOOL` | `%I1` – `%I2048` | Entradas discretas de campo |
| `%Q` | Digital Outputs | `BOOL` | `%Q1` – `%Q2048` | Salidas discretas de control |
| `%M` | Internal Markers | `BOOL` | `%M1` – `%M2048` | Banderas booleanas de memoria interna |
| `%T` | Timer/Counter Bits| `BOOL` | `%T1` – `%T2048` | Banderas de estado de temporizadores |
| `%SR` | System Registers | `WORD` | `%SR1` – `%SR255` | Estado del sistema OCS, reloj y diagnósticos |
| `%S` | System Bits | `BOOL` | `%S1` – `%S16` | Banderas del sistema (ej. `%S1` primer escaneo) |
| `%IG`, `%QG`| Global Digital | `BOOL` | `%IG1`, `%QG1` | E/S global compartida en red CsCAN |
| `%AIG`, `%AQG`| Global Analog | `WORD` | `%AIG1`, `%AQG1` | Analógicas compartidas en red CsCAN |

---

## 4. Superficie de Herramientas FastMCP (42 Tools)

### 4.1 Ciclo de Vida y Gestión de Proyectos
1. `cscape_launch_ide`: Lanza o localiza la instancia de Cscape 10.2 en el escritorio interactivo `winsta0\Default`.
2. `cscape_new_iec_project`: Genera la estructura de un proyecto nativo `.csp` / `.cpj`.
3. `cscape_open_project`: Abre un proyecto nativo verificando la cabecera OLE2 CFBF (`0xE11AB0A1E011CFD0`).
4. `cscape_create_project`: Wrapper transaccional para inicialización de proyecto seguro.
5. `cscape_export_project`: Exporta las estructuras de proyecto y POUs a esquemas estructurados JSON.

### 4.2 Lógica Structured Text y Compilación
6. `cscape_insert_st`: Inserción de código ST plano validado.
7. `cscape_insert_st_pou`: Inserción transaccional de POU Structured Text con rollback ante error.
8. `cscape_add_st_pou`: Wrapper de conveniencia para inyección de POU validada.
9. `cscape_validate_st`: Validación sintáctica rigurosa; detecta y rechaza construcciones ladder (`ERR_LADDER_FORBIDDEN`).
10. `cscape_compile`: Envía el comando de compilación Error Check (`ID_PROGRAM_ERRORCHECK = 32826` / `Ctrl+F7`) a la GUI de Cscape.
11. `cscape_compile_project`: Compilación offline por AST y verificación de tipos.
12. `cscape_get_build_output`: Raspa y analiza las líneas de salida del ListBox de compilación en Cscape.
13. `cscape_get_diagnostics`: Extrae marcadores de error y advertencia con número de línea y columna.

### 4.3 Manejo de Variables y Tags
14. `cscape_read_variables`: Lee variables mapeadas al OCS en entorno desacoplado.
15. `cscape_write_variables`: Escribe variables en la memoria emulada del simulador.
16. `cscape_import_variables`: Importa catálogo de variables desde CSV o XML nativo.
17. `cscape_export_variables`: Exporta la tabla de símbolos del proyecto a CSV o XML.
18. `cscape_inspect_variables`: Inspecciona mapeos de variables contra registros `%R`, `%AI`, `%AQ`, etc.

### 4.4 Simulación y Registro Horner
19. `cscape_run_simulation`: Ejecuta ciclos de scan en memoria (`SimulationBackend.EMULATED`).
20. `cscape_simulate_pou`: Simulación determinista de un POU específico con seguimiento de registros.
21. `cscape_simulate_cycle`: Ejecuta exactamente un ciclo de scan elemental.
22. `cscape_read_register`: Lee el valor actual de un registro emulado (`%R`, `%M`, etc.).
23. `cscape_write_register`: Escribe directamente sobre un registro en el entorno de simulación.

### 4.5 Integración HMI Nativa Cscape (Fase P3)
24. `cscape_hmi_inventory`: Inventario estructurado de pantallas y controles gráficos HMI nativos.
25. `cscape_hmi_apply_group`: Aplicación transaccional de agrupaciones de controles en pantalla HMI.
26. `cscape_hmi_read_properties`: Lectura de propiedades y parámetros de objetos gráficos.
27. `cscape_hmi_verify_bindings`: Verificación bidireccional de bindings entre variables OCS y controles HMI.
28. `cscape_hmi_save_close_reopen`: Test de durabilidad de persistencia HMI (Guardar, Cerrar, Reabrir).

### 4.6 Evolución y Fixtures de Proyectos (Fase P4)
29. `cscape_fixture_request_to_spec`: Traducción determinista de solicitudes en lenguaje natural a especificaciones AST.
30. `cscape_fixture_create`: Creación de proyectos fixture dedicados a partir de especificaciones.
31. `cscape_fixture_selective_edit`: Edición quirúrgica de umbrales/etiquetas preservando elementos no afectados.
32. `cscape_fixture_revision_impact`: Análisis de impacto localizado de revisiones sobre variables y lógica.
33. `cscape_fixture_durability_check`: Verificación de integridad CFBF y compilación limpia post-edición.
34. `cscape_fixture_detect_conflict`: Detección de colisiones concurrentes y desajuste de hashes.

### 4.7 Proveedor y Configuración Modbus PV (Fase P5 / CORE-08)
35. `cscape_modbus_create_config`: Creación de configuraciones normalizadas Modbus RTU / TCP (0..32000 a 0..100.0%).
36. `cscape_modbus_persist_config`: Persistencia atómica de configuración sidecar `modbus_pv_config.json`.
37. `cscape_modbus_read_config`: Lectura e inspección de configuración Modbus asociada al proyecto.
38. `cscape_modbus_protocol_check`: Verificación de protocolo contra servidor de pruebas etiquetado `[TEST_MODBUS_PV_PROVIDER]`.
39. `cscape_modbus_conversion_doc`: Generación de documentación técnica de conversión analógica a unidades de ingeniería.

### 4.8 Distribución y Validación Offline (Fase P9 & Scan List)
40. `cscape_package_offline_bundle`: Empaquetado de entregable air-gapped con binarios, ST, Modbus y manifiesto SHA-256.
41. `cscape_validate_scan_list_evidence`: Validación determinista de evidencia de scan list Modbus / MJ1 bajo contrato de 4 estados.
42. `cscape_inspect_scan_list`: Inspección de lista de escaneo de puerto (MJ1 / Modbus) con comportamiento fail-closed de lista vacía en offline.

---

## 5. Política Inviolable de Seguridad y Bloqueo Físico (Fail-Closed)

```
[BLOQUEO DE PUERTOS FÍSICOS]
  COM1 .. COM256 | \\.\COM* | /dev/tty* | CAN* | USB* | JTAG
  Acción: Intercepción inmediata -> Lanza SecurityError / HardwareLockoutError (status: blocked)

[BLOQUEO DE COMANDOS WIN32 DE DESCARGA]
  ID_PROGRAM_DOWNLOAD    (32827) -> BLOCKED
  ID_CONTROLLER_DOWNLOAD (33149) -> BLOCKED
  Acción: Filtro en envío de mensajes WM_COMMAND -> Lanza CscapeSafetyViolationError

[BLOQUEO DE UTILIDADES DE FLASHEO Y DESCARGA]
  PGMUpdateUtility.exe | DfuSeCommand.exe | STMFlashLoader.exe | WinJTAG.exe
  Acción: Prohibición de ejecución -> Bloqueo preventivo y terminación

[BLOQUEO DE INFILTRACIÓN LADDER EN ST]
  ---[ ]--- | ---[/]--- | ---[S]--- | ---[R]--- | RUNG | NETWORK | XIC | OTE
  Acción: Análisis léxico/AST -> Rechazo fail-closed con ERR_LADDER_FORBIDDEN
```

---

## 6. Recursos MCP Expuestos (`cscape://`)

- `cscape://projects`: Catálogo JSON de todos los proyectos gestionados bajo `artifacts/projects/`.
- `cscape://project/{project_name}/state`: Estado detallado del proyecto, metadatos y POUs asociadas.
- `cscape://project/{project_name}/diagnostics`: Reporte de diagnósticos de compilación y salida de build.
- `cscape://templates`: Inventario de plantillas estandarizadas IEC 61131-3 Structured Text.
- `cscape://template/{template_name}`: Código fuente de la plantilla seleccionada.
- `cscape://safety/status`: Reporte del estado de bloqueo de hardware y cumplimiento fail-closed.
- `cscape://registers/state`: Snapshot en tiempo real del estado de los registros emulados en memoria.
