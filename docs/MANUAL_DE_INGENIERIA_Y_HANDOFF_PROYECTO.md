# Horner Cscape 10.2 MCP: Manual de Ingeniería, Arquitectura y Handoff Técnico

> **Destinatario**: Ingeniero de Automatización / Desarrollador Sucesor  
> **Fecha de Emisión**: 2026-10-01  
> **Ubicación del Documento**: `C:\Users\ArmandoSilva\Downloads\MANUAL_DE_INGENIERIA_Y_HANDOFF_PROYECTO.md`  
> **Repositorio Local**: `C:\HornerAI\horner-cscape-mcp`  
> **Commit HEAD Verificado**: `291123abae996aef6821473676b26431f2c411e8` (Rama: `main`)  
> **Entorno Operativo**: Windows 10/11 x64 | Cscape 10.2 (Build 10.2.751.4) | Python 3.12 (64-bit)  
> **Estado de Aceptación**: Plan v3 **Aceptado por Supervisor** (`supervisor_offline_accepted = true`)  

---

## 1. Ficha Técnica y Resumen Ejecutivo

Bienvenido al proyecto **Horner Cscape Model Context Protocol (MCP) Server**. Este sistema es una plataforma de integración de grado industrial que conecta modelos de lenguaje e inteligencia artificial generativa (Antigravity, Claude Desktop, Cursor, u otros clientes compatibles con MCP) con el entorno de ingeniería para controladores lógicos programables (PLC/OCS) de **Horner Automation: Cscape 10.2**.

El propósito fundamental del proyecto es permitir que un agente de IA realice **ingeniería de control autónoma y asistida**: creación de proyectos, redacción de lógica de control en texto estructurado (IEC 61131-3 Structured Text), verificación estática de sintaxis, inyección de programas (POUs), compilación real dentro del entorno gráfico de Cscape (GUI Error Check), auditoría de pantallas HMI, simulación discreta de ciclos de scan en memoria y generación de pasarelas de telemetría Modbus, **todo bajo una estricta política de seguridad fail-closed** que imposibilita descargas no autorizadas a hardware físico.

```mermaid
flowchart LR
    subgraph AI_CLIENTS["Clientes de IA (FastMCP stdio)"]
        A1["Antigravity CLI / IDE"]
        A2["Claude Desktop"]
        A3["Cursor / VSCode MCP"]
    end

    subgraph MCP_CORE["Horner Cscape MCP Server (src/)"]
        M1["FastMCP JSON-RPC (43 Herramientas)"]
        M2["SecurityGuard (Fail-Closed)"]
        M3["AST Lexer & Parser (IEC 61131-3)"]
        M4["CFBF / OLE2 Engine (.csp / .cpj)"]
        M5["In-Memory OCS Scan Engine"]
    end

    subgraph TARGETS["Entornos de Ejecución"]
        T1["Cscape 10.2 Live GUI (winsta0\\Default)"]
        T2["Simulación en Memoria (%R, %M, %S)"]
        T3["Hardware Físico XL4 Prime (Fase P7 Manual)"]
    end

    AI_CLIENTS <==>|"JSON-RPC 2.0"| M1
    M1 --> M2
    M2 --> M3
    M2 --> M4
    M2 --> M5
    M1 -.->|"Win32 / UIAutomation"| T1
    M5 --> T2
    M2 -.x|"BLOQUEO FAIL-CLOSED (Sin descarga directa)"| T3
```

---

## 2. Lo que se Logró Construir desde Cero

Al iniciar este proyecto, no existía ninguna API, SDK ni interfaz programática moderna para interactuar con Horner Cscape. Cscape 10.2 es una aplicación monolítica Win32 de 32 bits basada en Microsoft Foundation Classes (MFC), diseñada exclusivamente para interacción humana mediante ratón y teclado, y cuyos archivos de proyecto (`.csp` y `.cpj`) son contenedores binarios propietarios estructurados en formato OLE2 / Compound File Binary Format (CFBF).

A partir de ingeniería inversa, instrumentación Win32 y diseño de software modular en Python, se construyeron los siguientes pilares:

### 2.1 Servidor FastMCP con 43 Herramientas Industriales
El servidor expone **43 herramientas registradas** sobre el protocolo estándar Model Context Protocol (FastMCP sobre transporte `stdio` con JSON-RPC 2.0). Las herramientas cubren 7 dominios funcionales:
1. **Automatización de Cscape 10.2 en Vivo (12 herramientas)**: Apertura y creación de proyectos, inyección de código ST mediante portapapeles y mensajes Win32, disparo de compilación (`ID_PROGRAM_ERRORCHECK = 32826` / `Ctrl+F7`), extracción y parseo del pane de salida MFC (ListBox 372).
2. **Gestión Offline de Proyectos y AST (8 herramientas)**: Creación de espacios de trabajo, adición transaccional de POUs con rollback ante fallo, validación estática profunda de sintaxis IEC 61131-3, categorización de variables y ámbitos globales.
3. **Simulación de Ciclos de Scan en Memoria (3 herramientas)**: Avance de ciclos de scan discretos, emulación de registros analógicos (`%R`, `%AI`, `%AQ`), bits discretos (`%I`, `%Q`, `%M`, `%T`) y flags de sistema (`%S1` primer scan, `%S7` pulso 10ms, `%S8` pulso 100ms, `%S9` pulso 1s).
4. **Gestión de Pantallas HMI Nativas (5 herramientas - Fase P3)**: Inspección de widgets gráficos en flujos binarios CFBF, aplicación de grupos de controles, verificación de enlaces (*bindings*) con registros OCS y pruebas de durabilidad (*save/close/reopen*).
5. **Suite de Evolución de Fixtures (6 herramientas - Fase P4)**: Síntesis de especificaciones a partir de requisitos textuales, generación de proyectos de prueba automatizados, edición selectiva de POUs, análisis de impacto en grafos de dependencias y detección de colisiones de memoria.
6. **Pasarela Modbus RTU/TCP y Lista de Escaneo (8 herramientas - Fase P5)**: Generación y persistencia de especificaciones de escalado de registros con SHA-256, cálculo de factores de conversión lineal, verificación de protocolos de cableado e inspección de lista de escaneo (*Scan List*).
7. **Empaquetado de Distribución Air-Gapped (1 herramienta)**: Generación de paquetes de distribución con manifiestos criptográficos para auditoría en plantas aisladas.

### 2.2 Motor Forense de Contenedores CFBF / OLE2
Se desarrolló un analizador e inyector de bajo nivel capaz de:
- Leer y escribir estructuras OLE2 Compound File Binary Format (`0xD0CF11E0A1B11AE1`).
- Navegar la tabla de asignación de sectores (SAT), la tabla de sectores cortos (SSAT) y el árbol de directorio interno.
- Extraer e inyectar flujos de lógica IEC (`Logic\POUs`), definiciones de variables y pantallas gráficas sin corromper la integridad referencial que Cscape exige al abrir proyectos.

### 2.3 Lexer, Parser y Validador AST IEC 61131-3 en Python Puro
Se implementó un analizador sintáctico completo para Structured Text (ST) que no depende de ningún compilador externo:
- Valida tipos de datos estándar: `BOOL`, `BYTE`, `WORD`, `DWORD`, `INT`, `DINT`, `UINT`, `UDINT`, `REAL`, `LREAL`, `TIME`, `STRING`.
- Soporta bloques de función temporizadores y contadores de la norma: `TON`, `TOF`, `TP`, `CTU`, `CTD`, `CTUD`.
- Control de flujo estructurado: `IF ... THEN ... ELSIF ... ELSE ... END_IF`, `CASE ... OF`, `FOR ... TO ... BY ... DO`, `WHILE ... DO`.
- **Filtro Anti-Ladder Estricto (`STLadderInteropGuard`)**: Detecta y rechaza inmediatamente cualquier intento de introducir artefactos de lenguaje de contactos / Ladder (como bobinas `---( )---`, contactos `---[ ]---`, etiquetas `RUNG` o mnemónicos `OTE`, `XIC`) emitiendo el código de error `ERR_LADDER_FORBIDDEN`.

### 2.4 Caso de Estudio Insigne: `TankLevel_P5_Dedicated.csp`
Se implementó y verificó un proyecto completo de control de proceso de una estación de bombeo y nivel de tanque:
- **Controlador Principal**: Bloque de función PID en texto estructurado puro ([`TankLevelControl.st`](file:///C:/HornerAI/horner-cscape-mcp/artifacts/projects/TankLevel_P5_Dedicated/pous/TankLevelControl.st)) con histéresis, enclavamientos de seguridad por sobrepresión y conmutación automática de bombas de vaciado.
- **Puente de Escalado Modbus**: Bloque de función ([`FB_ModbusScaleQuality.st`](file:///C:/HornerAI/horner-cscape-mcp/artifacts/projects/TankLevel_P5_Dedicated/pous/FB_ModbusScaleQuality.st)) que realiza escalado analógico con validación de calidad de señal ($0..32000 \to 0.0..100.0\%$, $0..500\text{ L/min}$, $0..10\text{ bar}$) y banderas de fallo de transductor.
- **Pantallas HMI Integradas**: 3 pantallas nativas (Pantalla 1: Visión general de planta; Pantalla 2: Control detallado de proceso y alarmas; Pantalla 3: Gráfica de tendencias de doble pluma en tiempo real).
- **Compilación en Cscape**: Verificado en Cscape 10.2 con **0 errores y 0 advertencias**.

### 2.5 Arquitectura de Seguridad Fail-Closed (`SecurityGuard`)
- Más de **227 pruebas automatizadas** de seguridad y regresión passing (`tests/test_security.py`).
- Cero fugas de credenciales, secretos, API keys o URLs privadas en los 2,750 archivos del repositorio.

---

## 3. Dificultades Técnicas Encontradas y Cómo se Superaron

Durante el desarrollo nos enfrentamos a peculiaridades profundas del software legacy de Horner y de la arquitectura de Windows:

### 3.1 El Crash Fatal de Cscape en `0x0051a4cd` (Sesiones No Interactivas)
* **El Problema**: Al intentar ejecutar pruebas en segundo plano mediante servicios de Windows, tareas programadas o conexiones SSH/headless, `Cscape.exe` crasheaba instantáneamente durante el arranque en la dirección `0x0051a4cd` con una violación de acceso (`PUSH DWORD PTR [EAX + 20h]` donde `EAX == NULL`).
* **La Causa**: Cscape utiliza una librería MFC de barras acoplables (docking panes) que asume la existencia incondicional de una estación de ventana interactiva con escritorio gráfico (`winsta0\Default`). En sesiones no interactivas, la llamada a la API de Windows para obtener el contexto de dibujo falla silenciosamente y el puntero de la barra es nulo.
* **La Solución**: Se estableció el principio arquitectónico de **Supervisor Dedicado en Escritorio Interactivo**. Cscape debe ser ejecutado bajo la sesión del usuario interactivo conectándose explícitamente a `winsta0\Default` mediante `user32.OpenDesktopW("Default", ...)` y `user32.SetThreadDesktop(...)`. Todo el resto del backend (FastMCP, AST, simulación) corre headless.

### 3.2 El Diálogo Modal "Failed to Save Document" (Error 32: `ERROR_SHARING_VIOLATION`)
* **El Problema**: En flujos de trabajo automatizados, Cscape mostraba esporádicamente un cuadro de diálogo modal `#32770` que decía *"Failed to save document."*, bloqueando la ventana principal (`EnableWindow(main_hwnd, FALSE)`).
* **La Causa Forense**: Se realizó una auditoría completa documentada en [`cscape_save_failed_diagnosis.md`](file:///C:/HornerAI/horner-cscape-mcp/docs/cscape_save_failed_diagnosis.md). Cuando Cscape abre un proyecto `.csp`, el motor de almacenamiento estructurado de Windows (`StgOpenStorage` / `CFile::Open`) retiene un bloqueo exclusivo o con permisos de compartición restringidos (`dwShareMode = 0`). Si un script externo intenta leer o sobrescribir el archivo en ese instante, MFC captura la excepción y dispara `AfxMessageBox(AFX_IDP_FAILED_TO_SAVE_DOC)`.
* **La Solución**:
  1. El supervisor implementa un barredor (*sweeper*) de diálogos modales que detecta ventanas emergentes `#32770` y las cierra de forma segura enviando `WM_COMMAND` con `IDOK` o `IDCANCEL`.
  2. Implementación de la estrategia **"Save As / Archivos en Staging"**: Cscape nunca guarda directamente sobre un archivo que esté siendo indexado concurrentemente; las mutaciones se realizan en copias con sufijos temporales únicos y se sincronizan transaccionalmente.

### 3.3 Imposibilidad Nativa de Conversión ST a Ladder (`BLOCKED_NATIVE`)
* **El Problema**: Existía el requerimiento inicial de convertir programas escritos en Texto Estructurado a diagramas de escalera (Ladder) nativos dentro de Cscape.
* **La Causa Forense**: Tras una auditoría exhaustiva de los ejecutables y DLLs de Cscape (`Cscape.exe`, `K5Cmp.dll`, `W5EditST.dll`), se demostró que Cscape 10.2 mantiene una separación arquitectónica estricta e infranqueable entre su motor de contactos tradicional y el compilador de texto estructurado de Straton K5. Cscape no posee menús, comandos de acelerador, funciones OLE ni exports en DLL que permitan convertir ST en Ladder.
* **La Solución**: Se documentó formalmente el estado como `BLOCKED_NATIVE: DOCUMENT_ONLY` (ver [`docs/st_to_ld_conversion_blocked.md`](file:///C:/HornerAI/horner-cscape-mcp/docs/st_to_ld_conversion_blocked.md)). El servidor MCP genera diagramas ASCII externos y modelos de datos JSON para auditoría humana, pero rechaza estrictamente cualquier intento de inyectar sintaxis de contactos en archivos `.st` bajo la regla `ERR_LADDER_FORBIDDEN`.

### 3.4 Bloqueo de la Lista de Escaneo Modbus Offline (*Scan List Lockout*)
* **El Problema**: Al intentar configurar la tabla de dispositivos esclavos Modbus (*Scan List*) en el contenedor binario de Cscape de forma offline, Cscape marcaba el proyecto como inconsistente.
* **La Causa**: El configurador de protocolos de Cscape 10.2 valida la existencia física y la respuesta serial del esclavo en tiempo de configuración para calcular longitudes de trama y timeouts. Sin un PLC físico conectado a la red RS-485, Cscape deja la tabla interna vacía (`count: 0`).
* **La Solución**: Se creó la herramienta de inspección fail-closed `cscape_inspect_scan_list` y la herramienta de reconciliación `cscape_reconcile_scan_list`. Se implementó la pasarela en Texto Estructurado [`FB_ModbusScaleQuality.st`](file:///C:/HornerAI/horner-cscape-mcp/artifacts/projects/TankLevel_P5_Dedicated/pous/FB_ModbusScaleQuality.st), que permite vincular variables a registros `%AI` directamente en lógica de control sin depender de la inicialización obligatoria de la tabla gráfica en modo offline.

### 3.5 Cuarentena de Straton K5 Legacy
* **El Problema**: Archivos antiguos del motor Straton K5 (`appli.k5p`, `appli.CPO`, `K5DBXS.INI`) generaban falsos positivos en verificaciones de integridad y riesgo de acoplamiento a librerías obsoletas.
* **La Solución**: Se aisló todo ese contenido bajo `quarantine/straton_k5_legacy/`, asegurando que el código de producción en `src/` tenga **cero dependencias** sobre dicha carpeta.

---

## 4. Estado Actual del Proyecto: ¿Qué se PUEDE hacer hoy?

El proyecto se encuentra en un estado sumamente maduro, estable y probado para ingeniería asistida por software. Actualmente puedes realizar las siguientes operaciones sin ninguna restricción:

| Capacidad | Descripción Técnica | Modo de Ejecución |
| :--- | :--- | :---: |
| **Conexión con Clientes IA** | Conectar Antigravity, Claude Desktop o Cursor al servidor FastMCP vía stdio (`scripts/run_mcp_server.py`). | Automático / Online stdio |
| **Generación de Lógica IEC 61131-3** | Generar POUs industriales complejas (control PID, bombas, alarmas, escalado, interlocks) en Structured Text puro. | Offline / Generativo |
| **Validación Sintáctica Estática** | Validar código ST antes de tocar Cscape, comprobando balanceo de bloques, tipos y ausencia de contactos ladder (`cscape_validate_st`). | In-Memory (ms) |
| **Creación e Inyección en Proyectos .csp** | Crear proyectos limpios y agregar POUs con rollback transaccional ante errores de sintaxis (`cscape_new_iec_project`, `cscape_add_st_pou`). | CFBF Binario OLE2 |
| **Compilación Real en Cscape 10.2** | Disparar el *Error Check* nativo de Cscape (`Ctrl+F7`) y leer los errores con número de línea y severidad desde el ListBox 372 (`cscape_compile`). | Live GUI (winsta0) |
| **Simulación de Ciclos de Scan** | Probar algoritmos ejecutando ciclos secuenciales con estímulos en `%I`, `%AI` y verificando salidas en `%Q`, `%AQ`, `%R` con pulsos de reloj `%S`. | Simulación Determinista |
| **Ingeniería de Telemetría Modbus** | Definir mapeos de registros Modbus RTU/TCP, generar factores de escala matemáticos y generar documentación técnica. | Herramientas Modbus |
| **Auditoría de Pantallas HMI** | Analizar pantallas de operador, verificar enlaces a variables de PLC y comprobar durabilidad de guardado. | Herramientas HMI |
| **Empaquetado para Despliegue** | Ensamblar archivos comprimidos o bundles de Git con hashes criptográficos SHA-256 para transferencia segura. | Air-Gapped Release |

---

## 5. Limitaciones Actuales y lo que NO se Puede Hacer Todavía

Es fundamental que el nuevo ingeniero conozca exactamente las fronteras del sistema para no intentar automatizaciones que violen las directivas de seguridad o que excedan las capacidades actuales:

```
+-------------------------------------------------------------------------------+
|                      MATRIZ DE FRONTERAS OPERATIVAS                          |
+---------------------------------------+---------------------------------------+
|        LO QUE SÍ ESTÁ SOPORTADO       |      LO QUE NO ESTÁ PERMITIDO / GAPS  |
+---------------------------------------+---------------------------------------+
| Simulación offline de scan OCS        | Descarga automática a PLC físico (P7) |
| Validación de sintaxis IEC 61131-3 ST | Conversión nativa ST a Ladder en GUI  |
| Compilación GUI Error Check (Ctrl+F7) | Flashing de firmware por USB / Serie  |
| Modbus loopback / emulación de red    | Polling en bus RS-485 físico en vivo  |
| 1 proceso supervisor de Cscape        | Múltiples procesos GUI en paralelo    |
| Ejecución en escritorio interactivo   | Ejecución headless como Servicio/SSH  |
+---------------------------------------+---------------------------------------+
```

### 5.1 Bloqueo Fail-Closed de Descarga a PLC Físico (Fase P7 Diferida)
* **Limitación**: El servidor MCP **NO descargará jamás código automáticamente a un controlador físico**.
* **Motivo**: Los puertos seriales `COM1` a `COM256`, los controladores USB, las herramientas de flasheo (`PGMUpdateUtility.exe`, `DfuSeCommand.exe`) y los comandos Win32 de descarga (`ID_PROGRAM_DOWNLOAD = 32827`, `ID_CONTROLLER_DOWNLOAD = 33149`) están interceptados y arrojan `SecurityError` / `HardwareLockoutError`.
* **Cómo se procede**: La carga del archivo `.csp` al PLC físico (Horner XL4 Prime) debe ser realizada **manualmente por el ingeniero de campo** mediante cable de programación USB o tarjeta MicroSD (ver [docs/HOW_TO_TEST_PHYSICAL_PLC.md](file:///C:/HornerAI/horner-cscape-mcp/docs/HOW_TO_TEST_PHYSICAL_PLC.md)).

### 5.2 Brechas de Hardware Físico en Planta (Hitos CORE-08, CORE-09, CORE-10)
Existen tres hitos que están completamente especificados y preparados en software, pero que requieren hardware real para su cierre definitivo (detallados en [`docs/CORE_08_09_10_RUNTIME_GAPS_AND_ROADMAP.md`](file:///C:/HornerAI/horner-cscape-mcp/docs/CORE_08_09_10_RUNTIME_GAPS_AND_ROADMAP.md)):
1. **CORE-08 Runtime (Bus Serial RS-485 Físico)**: Requiere conectar los sensores reales (transmisor de nivel `DEV_LT01`, flujómetro `DEV_FT01`, manómetro `DEV_PT01`) al puerto `MJ1`, verificar resistencia de terminación de $120\ \Omega$ y habilitar el escaneo en vivo.
2. **CORE-09 HMI & WebMI Físico**: Requiere calibrar la pantalla táctil resistiva de 3.5" del OCS XL4 en hardware real y probar la visualización del servidor web embebido (WebMI) en la red LAN1.
3. **CORE-10 Prueba de Telemetría Extendida (Soak Test)**: Requiere someter el PLC a 24 horas continuas de bombeo real para evaluar estabilidad térmica y derivas de memoria.

### 5.3 Concurrencia de GUI en Cscape
* **Limitación**: No es posible ejecutar dos scripts de automatización gráfica en paralelo contra Cscape.
* **Motivo**: Windows gestiona el foco de ventanas, el portapapeles y los mensajes de teclado a nivel de sesión interactiva. Si dos agentes envían clics o teclas simultáneamente, se produce robo de foco y corrupción del código pegado.
* **Regla**: Un único proceso (`scripts/cscape_supervisor.py`) debe ser el dueño del HWND de Cscape.

---

## 6. Estructura del Repositorio y Archivos Clave

```
C:\HornerAI\horner-cscape-mcp\
├── .git/                                # Historial completo de Git (HEAD: 291123a)
├── .gitignore                           # Exclusiones de nivel de producción
├── README.md                            # Guía general del proyecto y catálogo MCP
├── CONTRIBUTING.md                      # Reglas de contribución, ST puro y seguridad
├── CODE_OF_CONDUCT.md                   # Código de conducta para ingeniería
├── LICENSE                              # Licencia MIT
├── pyproject.toml                       # Manifiesto y dependencias del paquete Python
│
├── src/                                 # CÓDIGO FUENTE PRINCIPAL
│   ├── automation/                      # Automatización Win32 / UIAutomation Cscape
│   │   ├── cscape_win32.py              # Envoltorio de mensajes Win32 y HWNDs
│   │   └── supervisor.py                # Watchdog de proceso y barredor modal
│   ├── cscape/                          # Lógica interna de Cscape y Modbus
│   ├── iec/ & iec61131/                 # Analizador sintáctico AST y Lexer ST
│   ├── mcp/                             # Implementación del Servidor FastMCP
│   │   ├── server.py                    # Registro de herramientas y recursos JSON-RPC
│   │   └── schemas.py                   # Modelos Pydantic de entrada/salida (39+ esquemas)
│   ├── parser/                          # Forensia binaria de archivos CFBF (.csp/.cpj)
│   ├── security/                        # Guardas de seguridad fail-closed
│   │   └── guard.py                     # Bloqueo de puertos COM y utilidades de flash
│   └── simulation/                      # Motor emulador de scan OCS (%R, %M, %S)
│
├── tests/                               # SUITE DE PRUEBAS AUTOMATIZADAS
│   ├── test_security.py                 # 227+ tests de seguridad y aislamiento
│   ├── test_ast.py                      # Pruebas del parser IEC 61131-3
│   └── test_cfbf.py                     # Pruebas del contenedor OLE2
│
├── scripts/                             # SCRIPTS DE EJECUCIÓN
│   ├── run_mcp_server.py                # Punto de entrada para el servidor FastMCP stdio
│   └── cscape_supervisor.py             # Lanzador y supervisor del GUI de Cscape
│
├── docs/                                # DOCUMENTACIÓN TÉCNICA DETALLADA
│   ├── HOW_TO_TEST_MCP.md               # Guía de prueba del servidor FastMCP
│   ├── HOW_TO_TEST_PHYSICAL_PLC.md      # Procedimiento de carga manual a PLC físico
│   ├── cscape_save_failed_diagnosis.md  # Forensia del error de guardado
│   ├── st_to_ld_conversion_blocked.md   # Explicación de la barrera ST->Ladder
│   ├── P8_HARDENING_AND_KNOWN_LIMITATIONS.md # Auditoría de robustez y límites
│   └── CORE_08_09_10_RUNTIME_GAPS_AND_ROADMAP.md # Hoja de ruta para hardware
│
└── Downloads/ & User Downloads/         # ARCHIVOS DE ENTREGA
    ├── GITHUB_LOCAL_READY.md            # Guía de preparación y verificación local
    ├── GITHUB_LOCAL_VERIFY.md           # Reporte de auditoría determinística
    ├── horner-cscape-mcp-github-ready.zip # Paquete completo con .git listo para Drive
    └── horner-cscape-mcp.bundle         # Bundle nativo de Git ultraligero
```

---

## 7. Guía Rápida para el Nuevo Ingeniero (Quickstart)

### 7.1 Preparar el Entorno en una Nueva Máquina
Si estás clonando el repositorio o extrayendo el archivo `horner-cscape-mcp-github-ready.zip`:

```powershell
# 1. Navegar a la carpeta del proyecto
cd C:\HornerAI\horner-cscape-mcp

# 2. Crear entorno virtual con Python 3.12 (64-bit)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Instalar dependencias en modo editable
pip install -e .
pip install pytest pydantic fastmcp psutil
```

### 7.2 Ejecutar las Pruebas de Seguridad y Regresión
Antes de tocar cualquier línea de código, verifica que la suite base pase al 100%:

```powershell
# Ejecutar suite de pruebas de seguridad y bloqueo fail-closed
.\.venv\Scripts\python.exe -m pytest tests/test_security.py -v

# Ejecutar suite completa en modo silencioso
.\.venv\Scripts\pytest.exe -q
```
*Resultado esperado: Todos los tests deben pasar en modo verde (cero errores).*

### 7.3 Probar el Servidor FastMCP
Para probar el servidor manualmente desde consola:

```powershell
# Verificar versión del servidor
.\.venv\Scripts\python.exe scripts\run_mcp_server.py --version

# Ejecutar servidor en modo stdio (responderá a comandos JSON-RPC)
.\.venv\Scripts\python.exe scripts\run_mcp_server.py
```

### 7.4 Configurar Claude Desktop o Cursor
Agrega la siguiente configuración a tu archivo `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "horner-cscape": {
      "command": "C:\\HornerAI\\horner-cscape-mcp\\.venv\\Scripts\\python.exe",
      "args": [
        "C:\\HornerAI\\horner-cscape-mcp\\scripts\\run_mcp_server.py"
      ],
      "env": {
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

---

## 8. Recomendaciones de Buenas Prácticas para Continuar el Proyecto

1. **Nunca intentes saltarte el `SecurityGuard`**:
   Si necesitas probar con hardware físico, no intentes habilitar puertos COM dentro de scripts automáticos. Utiliza el procedimiento de carga manual documentado en [`docs/HOW_TO_TEST_PHYSICAL_PLC.md`](file:///C:/HornerAI/horner-cscape-mcp/docs/HOW_TO_TEST_PHYSICAL_PLC.md).
2. **Conserva la Pureza de Texto Estructurado (IEC 61131-3)**:
   No intentes programar bloques en Ladder mediante este MCP. Toda la arquitectura está optimizada para generar lógica determinista, testeable y modular en Structured Text.
3. **Control de Concurrencia al Probar el GUI**:
   Si vas a correr pruebas que involucren abrir Cscape y compilar (`cscape_compile`), asegúrate de que no haya otra instancia de Cscape abierta en segundo plano que interfiera con los identificadores de ventana (`HWND`).
4. **Respeta el Contrato de 4 Estados**:
   Cualquier nueva herramienta de MCP que implementes debe responder estrictamente con uno de los 4 estados canónicos: `status: "success" | "failed" | "blocked" | "inconclusive"`. No inventes estados intermedios.

---
*Fin del documento de transferencia técnica. ¡Mucho éxito en la siguiente fase de comisionamiento de hardware!*
