# Contributing to Horner Cscape MCP Server

Thank you for contributing to the Horner Cscape MCP Server project. To ensure deterministic operations, air-gapped industrial safety, and native compatibility with Horner APG Cscape 10.2, all contributors must strictly adhere to the following directives:

---

## 1. Safety & Lockout Invariants (Non-Negotiable)

1. **Zero PLC Download Policy**:
   - Automated controller flashing, programming cable polling, and download command dispatch are permanently barred fail-closed.
   - All physical controller downloads are deferred exclusively to manual execution by authorized commissioning engineers (Phase P7).
2. **Physical Port Lockout**:
   - Code must never attempt to open or probe physical serial ports (`COM1`–`COM256`), industrial fieldbuses (`CAN`, `CsCAN`), or USB debuggers. Any attempt must raise `HardwareLockoutError` fail-closed.
3. **`verified_live = false`**:
   - Never generate synthetic live confirmations or declare `VERIFIED_LIVE` without genuine, signed physical hardware telemetry.

---

## 2. IEC 61131-3 Logic Standards

1. **Pure Structured Text (ST) Only**:
   - All controller logic must be written in standard IEC 61131-3 Structured Text.
   - Any ladder logic constructs (contacts `---[ ]---`, coils `---( )---`, rung markers `RUNG`/`NETWORK`) introduced into `.st` files must be rejected immediately with `ERR_LADDER_FORBIDDEN`.
2. **Deterministic Simulation**:
   - Logic POUs must simulate cycle-by-cycle in pure software without requiring proprietary runtime processes (`T5SIMUL`, `T5RTI`).
3. **Straton K5 Quarantine**:
   - Standalone Straton K5 templates remain permanently quarantined under `quarantine/straton_k5_legacy/`. Never reintroduce dependencies on quarantined files.

---

## 3. FastMCP Tooling & Status Contract

Every MCP tool result and API endpoint must conform to the 4-state status contract:
```json
{
  "status": "success | failed | blocked | inconclusive",
  "error_code": "STRING_ENUM_OPTIONAL",
  "details": "Factual description",
  "data": {}
}
```
Never invent arbitrary status strings such as `VERIFIED` or `100%`.

---

## 4. Single GUI Owner Boundary

- Live interaction with `Cscape.exe` is restricted to exactly **ONE** dedicated process on `winsta0\Default`.
- All background tests, linters, and batch runners must execute headlessly.
- Never initiate keep-alive polling loops or repetitive Error Check routines.

---

## 5. Repository Packaging & Release Assets

- **Do Not Commit Large Binary Archives**: Large offline bundles (`offline_evidence_bundle_*.zip`, `TankLevel_P5_Dedicated_offline_bundle_*.zip`) and memory dumps must be managed as external release assets or placed in `Downloads/`.
- Maintain `.gitignore` rules preventing bytecode, virtual environments (`.venv`), `.env` files, and local logs from entering source control.
- All secrets, tokens, passwords, and private paths must be completely scrubbed before creating pull requests or commits.
