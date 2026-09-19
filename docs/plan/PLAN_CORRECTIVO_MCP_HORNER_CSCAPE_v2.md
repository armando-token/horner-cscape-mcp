# PLAN_CORRECTIVO MCP Horner/Cscape v2.0 (correctivo)

**MISSION_ID**: C0_THEN_C1  
**Target Workspace**: C:\HornerAI\horner-cscape-mcp  
**Run ID**: 
un_20260906_120831  
**Creation Timestamp**: 2026-09-06T19:12:00Z  
**Governing Rule**: RULE[C:\Users\ArmandoSilva\AGENTS.md]  
**Execution Mode**: Headless / Offline DEV for C0 and C1 (Zero Live GUI mutation; Leave Cscape alone)

---

## 1. Executive Summary & Corrective Principles

This corrective plan (*PLAN_CORRECTIVO MCP Horner/Cscape v2.0*) supersedes arbitrary step iteration and focuses on strict architectural integrity, evidence preservation, and fail-closed safety.

### Core Corrective Mandates:
1. **Preserve Original Definitions**: Megaplan v1 **H01-H13** (False-Success dismantling) and **G0-G5** (Gates 0 through 5) definitions remain immutable. They are NOT to be redefined or diluted by inventory size, uptime records, or repetitive parity claims.
2. **Work Only in Target Root**: Confine all activities strictly to C:\HornerAI\horner-cscape-mcp.
3. **Preserve Originals**: All baseline code, configurations, and test assets are archived in rtifacts/recovery/<run_id>/ with full SHA-256 cryptographic manifests prior to mutation.
4. **No Hardware / Physical PLC Access**: Maintain unconditional fail-closed hardware port lockout (COM1-COM256, CAN, USB, JTAG) and companion flasher lockout.
5. **Halt Step Missions**: Eliminate speculative Step iterations (e.g. Step 188/189/190 step theater). Progression is guided strictly by verifiable corrective phases (C0, C1, ...).
6. **Execution Bottleneck Control**: At most one critical-path implementation task at a time.
7. **Single GUI Ownership**: At most one GUI owner, with preference for **ZERO GUI** during offline/DEV phases C0 and C1. Leave live Cscape instance alone.

---

## 2. Phase C0 Deliverables (Completed)

Phase C0 establishes the immutable baseline and traceability:
- **Recovery Vault**: Established at rtifacts/recovery/run_20260906_120831/ and docs/recovery/.
- **Baseline Archive**: Preserved in rtifacts/recovery/run_20260906_120831/baseline_archive.zip (210 files tracked with SHA-256).
- **Baseline Hashes Manifest**: Documented in rtifacts/recovery/run_20260906_120831/baseline_hashes.json.
- **Original H/G Definitions Vault**: Preserved in rtifacts/recovery/run_20260906_120831/h_g_definitions.json.
- **Traceability Matrix (
equirements.csv)**: Mapped H01-H13 and G0-G5 to requirements R01-R12 in both rtifacts/recovery/run_20260906_120831/requirements.csv and docs/recovery/requirements.csv.

---

## 3. Phase C1 Objectives & Implementation Scope

Phase C1 focuses on a single, focused critical-path implementation task:
1. **Scope**: Strengthen offline FastMCP tool contract validation in src/mcp/tools.py and safety guardrails in src/security/guard.py.
2. **Contract Rigor**: Guarantee that every MCP tool adheres strictly to the canonical 4-state contract (success | failed | blocked | inconclusive), eliminating any unhandled exceptions or invalid return schemas.
3. **Fail-Closed Verification**: Verify fail-closed behavior for all restricted operations (COM ports, download command IDs 32827/33149, ladder constructs).
4. **Headless / Offline Execution**: Execute all tests strictly headlessly using the virtual environment .venv\Scripts\python.exe. Zero Win32 GUI calls; leave Cscape PID 16564 untouched.
5. **Deliverables**:
   - Single unified diff of code modifications.
   - Targeted pytest verification log across core unit tests (	est_security.py, 	est_compiler.py, 	est_iec_parser.py, 	est_mcp_tools.py).
   - Audit report logged to rtifacts/recovery/run_20260906_120831/c1_execution_log.json.

---

## 4. Requirements Traceability (R01-R12)

| Req ID | Category | Name | Mapped Gates | Mapped False Successes | Contract Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **R01** | Container | Fail-Closed Project Container & CFBF Integrity | G0 | H01, H02 | success |
| **R02** | Compiler | Honest Compiler Diagnostics & AST Metrics Pipeline | G1, G3 | H03 | success |
| **R03** | Simulation | Explicit Mock Classification & Offline Taxonomy | G4 | H04 | success |
| **R04** | GUI Automation | Modal Dialog Interception & Window State Inspection | G2 | H05 | success |
| **R05** | Quarantine | Straton K5 Legacy Quarantine Isolation | G0 | H06 | success |
| **R06** | Liveness | Dynamic Gate Liveness & Ephemeral PID Decoupling | G1, G2 | H07 | success |
| **R07** | IEC Standard | Pure IEC 61131-3 ST Enforcement & Ladder Lockout | G1 | H08 | success |
| **R08** | Interoperability | Native Language Conversion Reality Documentation | G1 | H08 | success |
| **R09** | Supervision | Process Supervision & Execution Watchdog Enforcement | G2 | H09, H12 | success |
| **R10** | Safety Lockout | Physical Port & Companion Flasher Fail-Closed Lockout | G3 | H10, H11 | blocked |
| **R11** | Protocol | FastMCP Protocol & Canonical 4-State Status Contract | G4, G5 | H13 | success |
| **R12** | Verification | Evidence-Gated Final Signoff & Dual-Root Parity | G5 | G5 | success |
