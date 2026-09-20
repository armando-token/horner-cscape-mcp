# Contributing to Horner Cscape MCP Server

Welcome to the **Horner Cscape Model Context Protocol (MCP) Server** project! We are excited to welcome contributors from industrial automation, software engineering, and artificial intelligence disciplines.

This document outlines the engineering directives, safety policies, development workflows, and coding standards required to contribute effectively to this repository.

---

## 1. Welcome & Mission Statement

### Mission Statement
The mission of **Horner Cscape MCP Server** is to provide a deterministic, industrial-grade Model Context Protocol (MCP) bridge connecting modern AI engineering clients with **Horner APG Cscape 10.2 (Build 10.2.751.4)** and native **`.csp`** / **`.cpj`** Compound File Binary Format (CFBF) project containers.

Our goal is to enable AI-assisted logic generation, offline syntax validation, and deterministic simulation while strictly preserving **air-gapped industrial safety**, **fail-closed hardware lockout**, and **zero physical PLC risk**.

### Engineering Philosophy
1. **Safety Over Convenience**: In industrial automation, an incorrect command or unauthorized controller download can damage physical machinery or endanger personnel. Our safety guards are immutable and fail-closed.
2. **Deterministic & Cycle-Accurate**: Software verification and simulation must yield predictable, repeatable results without relying on unverified runtime processes.
3. **Evidence-Gated Progression**: Every assertion, compilation, and simulation result must produce verifiable deliverables and honest status reporting. Premature victory declarations or silent mocks are prohibited.
4. **Clean Architectural Boundaries**: High-level AI tools must interact through standardized MCP protocols without corrupting GUI state or bypassing safety boundaries.

---

## 2. Core Safety & Architectural Invariants (Non-Negotiable)

All contributors must adhere to the following four core invariants. Pull requests that violate any of these rules will be rejected immediately without exception.

### 2.1 Fail-Closed Hardware Lockout Policy
To guarantee air-gapped industrial safety, the codebase enforces an absolute ban on automated hardware communication and flashing:

* **Physical Communication Port Lockout**: Code must never open, probe, or scan physical serial ports (`COM1`–`COM256`, `\\.\COM*`, `/dev/tty*`), industrial fieldbuses (`CAN*`, `CsCAN`, `DeviceNet`, `Profibus`), USB debuggers, or hardware bridges. Any attempt will immediately raise `HardwareLockoutError`.
* **Zero Automated PLC Downloads**: Automated controller downloading, firmware updating, and flash operations are barred. Physical downloads are deferred exclusively to manual execution by authorized commissioning engineers in Phase P7.
* **Companion Flashing Utility Lockout**: Execution of controller flashing binaries (`PGMUpdateUtility.exe`, `DfuSeCommand.exe`, `STMFlashLoader.exe`, `WinJTAG.exe`) is intercepted and prohibited.
* **CLI Switch Lockout**: Passing download/flash flags (`/d`, `/download`, `/flash`, `/burn`, `/write-flash`) raises `DangerousArgumentError`.
* **Win32 Download Message Lockout**: The GUI automation layer intercepts and blocks Win32 download command IDs:
  * `ID_PROGRAM_DOWNLOAD = 32827` (BLOCKED)
  * `ID_CONTROLLER_DOWNLOAD = 33149` (BLOCKED)
* **Honest Telemetry (`verified_live = false`)**: Never generate synthetic live confirmations or declare `VERIFIED_LIVE` without genuine, signed physical hardware telemetry.

### 2.2 Pure Structured Text (ST) Invariant & `ERR_LADDER_FORBIDDEN`
* **Pure IEC 61131-3 Structured Text**: All logic Program Organization Units (POUs) must be written exclusively in standard IEC 61131-3 Structured Text (`.st`).
* **Ladder Logic Construct Interception**: Any ladder logic artifacts introduced into `.st` files are rejected fail-closed with error code `ERR_LADDER_FORBIDDEN` (`LadderConstructRejectedError`).
  * Prohibited constructs include: ASCII contacts (`---[ ]---`, `---[/]---`), coils (`---( )---`, `---(S)---`, `---(R)---`, `---(L)---`), rung markers (`RUNG`, `END_RUNG`, `NETWORK`), and instruction mnemonics (`XIC`, `XIO`, `OTE`, `OTL`, `OTU`).
* **ST→LD Language Conversion Reality (`BLOCKED_NATIVE: DOCUMENT_ONLY`)**:
  * Horner Cscape 10.2 maintains an architectural separation between its legacy Advanced Ladder solver and its IEC 61131-3 engine.
  * Cscape 10.2 contains **zero** GUI menus, commands, or DLL exports for ST→LD conversion.
  * Offline AST-based translation and ASCII diagram synthesis are supported via `STLadderInteropGuard` for engineering analysis, but in-GUI language conversion is permanently blocked (`BLOCKED_NATIVE`).

### 2.3 Single GUI Agent Boundary (`winsta0\Default`)
* **Exclusive Window Handle Ownership**: Exactly **ONE** designated automation or watchdog process may drive live Cscape GUI window handles (`HWND`) on the interactive desktop (`winsta0\Default`).
* **Headless Concurrency**: All other subagents, automated test suites, linters, and background jobs MUST execute headlessly or perform non-intrusive read-only queries.
* **Keep Cscape Visible**: During live GUI test runs, `Cscape.exe` must remain open and visible with `TankLevelClosedLoop.csp` and the Project Navigator loaded.
* **Fail-Closed GUI State**: If Cscape is closed, hidden, minimized, or its main window handle is unavailable, live GUI tools must fail closed immediately (`status: blocked` or `status: failed`). Simulating synthetic GUI successes is strictly forbidden.

### 2.4 Straton K5 Quarantine & Deterministic Simulation
* **Straton K5 Quarantine**: Standalone Straton K5 templates (`appli.k5p`, `appli.CPO`, `K5DBXS.INI`) remain strictly quarantined under `quarantine/straton_k5_legacy/`. Never import, execute, or reintroduce dependencies on quarantined files.
* **Pure-Software Simulation**: POUs simulate cycle-by-cycle in pure software (`SimulationBackend.EMULATED`) without requiring proprietary runtime processes (`T5SIMUL`, `T5RTI`).

---

## 3. Strict 4-State Status Contract

Every MCP tool, test suite assertion, and API payload must adhere to the 4-state status specification:

```json
{
  "status": "success | failed | blocked | inconclusive",
  "error_code": "STRING_ENUM_OPTIONAL",
  "details": "Factual description of outcome",
  "data": {}
}
```

| Status | Definition |
| :--- | :--- |
| `success` | All assertions passed deterministically, valid deliverables created, and verifiable evidence logged. |
| `failed` | Execution failed due to syntax error (`ST_SYNTAX_ERROR`), ladder injection (`ERR_LADDER_FORBIDDEN`), simulation mismatch, or compiler failure. |
| `blocked` | Operation actively prevented by safety policy (hardware port ban, download lockout) or native platform limitation (`BLOCKED_NATIVE`). |
| `inconclusive` | Preconditions unverified, environment unready, or outcome cannot be validated deterministically. |

> [!WARNING]
> Never invent or return subjective statuses such as `VERIFIED`, `100%`, `PERFECT`, or `ALL_TESTS_PASSING`. Always use the strict 4-state contract.

---

## 4. Development Environment Setup

### 4.1 Prerequisites
* **Operating System**:
  * **Windows 10 / 11 (64-bit)**: Required for live Cscape Win32 GUI automation (`pywinauto`, `ctypes`).
  * **Linux / macOS**: Fully supported for headless development, pure-ST parsing, AST validation, security guard testing, and software simulation.
* **Python**: Version **3.10** or higher (tested on 3.10, 3.11, and 3.12).
* **Cscape IDE** (Optional for offline development; required for live GUI gate tests):
  * Horner APG Cscape 10.2 (Build 10.2.751.4).

### 4.2 Setting Up the Virtual Environment

We recommend using either `venv` or `uv` for environment management.

#### Using Standard Python `venv`:
```powershell
# Clone the repository
git clone https://github.com/your-org/horner-cscape-mcp.git
cd horner-cscape-mcp

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1   # On Windows
# source .venv/bin/activate  # On Linux/macOS

# Upgrade packaging tools
pip install --upgrade pip setuptools wheel
```

#### Using `uv` (Fastest):
```powershell
# Create virtual environment with uv
uv venv .venv
.venv\Scripts\Activate.ps1

# Install project and development dependencies
uv pip install -e .
uv pip install pytest pytest-cov mypy ruff black
```

### 4.3 Installing Development Dependencies
Install the package in editable mode with development tooling:
```powershell
pip install -e .
pip install pytest pytest-cov mypy ruff black
```

### 4.4 Dual-Root Workspace Synchronization
To maintain developer convenience across local environments, core configuration files, agent rules, and test suites are synchronized between:
1. **Primary Workspace**: `C:\HornerAI\horner-cscape-mcp\`
2. **User Environment**: `C:\Users\ArmandoSilva\`

*Note: Dual-root parity is an environment synchronization task and is not an acceptance gate for milestone closure.*

---

## 5. Coding Standards & Quality Guidelines

### 5.1 Python Code Style & Typing
* **PEP 8 Conformance**: Follow standard PEP 8 formatting conventions.
* **Type Annotations**: All function signatures, methods, and module-level constants must have complete, explicit type annotations. Use Python's `typing` module and standard collections.
* **Pydantic Models**: FastMCP tool schemas and data exchange objects must be defined using Pydantic v2 `BaseModel` with explicit field validation and documentation.
* **Path Sandboxing & Hygiene**:
  * Always use `pathlib.Path` instead of string operations for filesystem paths.
  * Validate all paths through `src.security.sandbox.PathSandbox` to prevent directory traversal (`..`), Alternate Data Streams (`:stream`), and DOS reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`).
* **Exception Hierarchy**: Derive custom exceptions from `src.security.exceptions.SecurityError` or `src.cscape.exceptions.CscapeError`. Never use bare `except:` clauses.

### 5.2 Structured Text & IEC 61131-3 Standards
* All Structured Text files must strictly conform to IEC 61131-3 3rd Edition.
* Data types must be standard: `BOOL`, `INT`, `DINT`, `REAL`, `TIME`, `STRING`, etc.
* Variables must follow standard Horner OCS memory mapping conventions (`%R`, `%AI`, `%AQ`, `%I`, `%Q`, `%M`, `%SR`) when bound to hardware registers.
* No silent fallback: If an ST POU contains syntax or ladder anomalies, reject immediately with precise line and column diagnostic markers.

### 5.3 Testing Standards (`pytest`)
All contributions must include thorough unit and integration tests under the `tests/` directory.

* **Deterministic Tests Only**: Tests must run deterministically without race conditions or non-deterministic `time.sleep()` calls.
* **Running the Test Suite**:
  ```powershell
  # Run the full test suite
  pytest -v --strict-markers --basetemp=.pytest_temp

  # Run security lockout validation
  pytest -v tests/test_security.py

  # Run Pure ST vs Ladder interop guard tests
  pytest -v tests/test_st_ld_interop.py

  # Run FastMCP status contract verification
  pytest -v tests/test_mcp_status_contract.py

  # Run PLC simulation tests
  pytest -v tests/test_simulation.py
  ```
* **No Silent Mocks**: Mocks must never simulate successful live physical controller interactions or bypass safety gates. If physical hardware is required and absent, the test must yield `status: blocked` or cleanly skip.
* **Temporary Directories**: Always isolate file generation during tests using pytest's `tmp_path` fixture or `--basetemp=.pytest_temp`.

---

## 6. Git Workflow, Commit & PR Guidelines

### 6.1 Branching Strategy
* `main`: The default, production-ready branch. Must always pass all security and unit tests.
* `feature/<feature-name>`: New capabilities, MCP tools, or simulation features.
* `fix/<bug-name>`: Bug fixes and issue resolutions.
* `docs/<topic>`: Documentation updates, guides, and specification updates.
* `safety/<policy>`: Security guardrails and lockout policy hardening.

### 6.2 Conventional Commit Messages
We enforce [Conventional Commits v1.0.0](https://www.conventionalcommits.org/). Each commit message should follow this format:

```
<type>(<optional scope>): <description>

[optional body]

[optional footer(s)]
```

#### Allowed Types:
* `feat`: A new feature or MCP tool.
* `fix`: A bug fix.
* `safety`: Hardening of security policies, port bans, or download lockouts.
* `docs`: Documentation-only changes.
* `test`: Adding or correcting tests; no production code changes.
* `refactor`: A code change that neither fixes a bug nor adds a feature.
* `chore`: Maintenance tasks, dependency updates, or build configuration.

#### Examples:
```
feat(mcp): implement cscape_validate_st with AST diagnostic markers
safety(lockout): intercept Win32 controller download command ID 33149
test(st-guard): add unit tests for ERR_LADDER_FORBIDDEN detection
docs(contributing): align contributing guide with enterprise open-source standards
```

### 6.3 Pull Request (PR) Checklist
Before submitting a pull request, ensure you have completed each item:

- [ ] **Core Invariants Preserved**:
  - [ ] Zero physical port connections or hardware communications.
  - [ ] Zero automated download or flashing commands.
  - [ ] Pure ST enforcement verified (`ERR_LADDER_FORBIDDEN`).
  - [ ] Single GUI Owner boundary (`winsta0\Default`) respected.
- [ ] **Tests Pass**: `pytest -v --strict-markers` passes with 0 failures.
- [ ] **Type & Style Check**: Code passes `mypy` and `ruff`/`black` formatting.
- [ ] **Status Contract**: All new MCP tool responses adhere to the 4-state contract (`success | failed | blocked | inconclusive`).
- [ ] **No Large Binary Archives**: Large zip archives (`*.zip`), `.bin`, `.hex`, or core memory dumps are excluded from git.
- [ ] **Secrets Scrubbed**: No API tokens, passwords, private keys, or personal credentials are included in code or commit history.

---

## 7. Code of Conduct

We are committed to providing a welcoming, inclusive, and harassment-free experience for everyone, regardless of age, body size, disability, ethnicity, gender identity, level of experience, nationality, personal appearance, race, religion, or sexual identity.

This project has adopted the **Contributor Covenant (version 2.1)**. By participating in this project, you agree to abide by its terms.

For complete details, please read our [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

### Enforcement & Reporting
Instances of abusive, harassing, or otherwise unacceptable behavior may be reported to the project maintainers. All complaints will be reviewed and investigated promptly and fairly, with full respect for the confidentiality of the reporter.

---

## 8. Summary of Quick Commands

```powershell
# 1. Activate environment
.venv\Scripts\Activate.ps1

# 2. Run core security verification
pytest -v tests/test_security.py

# 3. Run Structured Text guard verification
pytest -v tests/test_st_ld_interop.py

# 4. Run MCP status contract tests
pytest -v tests/test_mcp_status_contract.py

# 5. Run full test suite
pytest -v --strict-markers --basetemp=.pytest_temp
```

Thank you for helping build a safe, robust, and deterministic bridge between artificial intelligence and industrial automation!
