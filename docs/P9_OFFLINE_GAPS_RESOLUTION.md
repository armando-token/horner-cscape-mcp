# Phase P9: Plan v3 Remaining Offline Gaps Resolution

## Executive Summary

Phase P9 resolves the documented remaining offline gaps from **Plan v3** ([PLAN_v3_P0_RECONCILIATION.md](file:///C:/HornerAI/horner-cscape-mcp/docs/plan/PLAN_v3_P0_RECONCILIATION.md)), the Product Contract ([PRODUCT_CONTRACT.md](file:///C:/HornerAI/horner-cscape-mcp/docs/product/PRODUCT_CONTRACT.md)), and Known Limitations ([P8_HARDENING_AND_KNOWN_LIMITATIONS.md](file:///C:/HornerAI/horner-cscape-mcp/docs/P8_HARDENING_AND_KNOWN_LIMITATIONS.md)).

All gaps were addressed purely in offline/DEV mode under strict fail-closed security invariants:
- **Zero PLC Download**: Physical communication ports (`COM1`–`COM256`, CAN, USB, JTAG) and Win32 download command IDs (`32827`, `33149`) remain unconditionally blocked.
- **Phase P7 Deferred**: Physical hardware loading is strictly reserved for manual loading by the commissioning engineer.
- **Strict Invariant**: **NO CLAIM OF `VERIFIED_LIVE`** and **NO CLAIM OF `CORE-09` OR `CORE-10`**.
- **FastMCP 4-State Contract**: All tools deterministically return `status: "success" | "failed" | "blocked" | "inconclusive"`.

---

## 1. Resolved Offline Gaps & Architecture

### 1.1 IEC 61131-3 `TYPE ... END_TYPE`, `STRUCT`, `ENUM`, and Subrange AST Extension
- **Prior Limitation**: The pure-ST parser and AST nodes supported `PROGRAM`, `FUNCTION_BLOCK`, `FUNCTION`, variable blocks, and expressions, but did not support custom type definitions (`TYPE ... END_TYPE`), `STRUCT ... END_STRUCT`, enumerated types `(VAL1, VAL2, ...)`, or subranges `INT (0..100)`.
- **Engineering Solution**:
  - Added AST node classes to [src/iec/ast_nodes.py](file:///C:/HornerAI/horner-cscape-mcp/src/iec/ast_nodes.py): `TypeDefNode`, `StructTypeNode`, `EnumTypeNode`, `SubrangeTypeNode`, `AliasTypeNode`, `TypeDeclNode`, `TypeBlockNode`.
  - Updated `ProgramNode` to store `type_blocks` with roundtrip serialization via `.to_st()` and `.to_dict()`.
  - Implemented `_parse_type_block()` in [src/iec/parser.py](file:///C:/HornerAI/horner-cscape-mcp/src/iec/parser.py) to support full recursive descent parsing of `TYPE ... END_TYPE` sections.
  - Enhanced [src/iec/validator.py](file:///C:/HornerAI/horner-cscape-mcp/src/iec/validator.py) nesting validator to verify `TYPE`/`END_TYPE` and `STRUCT`/`END_STRUCT` pairs.
  - Verified clean syntax validation and AST roundtrip emission.

### 1.2 Semantic Range & Multi-Word Footprint Bounds Checking for Horner OCS Registers
- **Prior Limitation**: Variable registration checked prefix syntax and single index limits, but did not detect multi-word data type footprint overflow (e.g. `%R9999` with `REAL`, which spans `%R9999` and `%R10000`, exceeding the 9999 register boundary).
- **Engineering Solution**:
  - Enhanced `parse_variables()` in [src/iec/validator.py](file:///C:/HornerAI/horner-cscape-mcp/src/iec/validator.py) with `IEC_TYPE_WORD_SIZE` footprint calculation.
  - Added `is_within_bounds()` and `spans_within_bounds(data_type)` helper methods directly to `HornerRegister` in [src/cscape/variables.py](file:///C:/HornerAI/horner-cscape-mcp/src/cscape/variables.py).
  - Out-of-bounds registers (e.g. `%R10000`, `%AI600`) and multi-word footprint overflows (`%R9999` with `REAL`, `%SR256` with `DINT`) now fail closed deterministically with error code `ERR_REGISTER_OUT_OF_BOUNDS`.
  - Integrated into `cscape_validate_st` with exact line-number failure localization.

### 1.3 Structured Modal Dialog Diagnostics Harvester
- **Prior Limitation**: When modal dialogs appeared during Win32 automation (e.g., `#32770` error prompts, compilation summaries, save-dirty prompts), dialog suppression dismissed them without capturing structured error text for diagnostics.
- **Engineering Solution**:
  - Implemented `harvest_modal_dialog_diagnostics(hwnd)` and `harvest_all_modal_diagnostics()` in [src/cscape/lifecycle.py](file:///C:/HornerAI/horner-cscape-mcp/src/cscape/lifecycle.py).
  - Extracts title, window class, static text messages, list box items, edit boxes, buttons, and semantic classifications (`is_error`, `is_warning`, `is_compilation`, `is_dirty_prompt`).
  - Fails closed safely on invalid or zero window handles (`hwnd=0`) without corrupting desktop handles.

### 1.4 Air-Gapped Offline Packaging MCP Tool (`cscape_package_offline_bundle`)
- **Prior Limitation**: Plan v3 delivery was performed via ad-hoc scripts rather than a first-class, callable FastMCP tool conforming to JSON-RPC 2.0.
- **Engineering Solution**:
  - Implemented `cscape_package_offline_bundle` in [src/mcp/tools.py](file:///C:/HornerAI/horner-cscape-mcp/src/mcp/tools.py).
  - Bundles project binaries (`.csp`/`.cpj`), ST POUs (`.st`), variable mappings (`variables.csv`/`.xml`), Modbus configuration (`modbus_pv_config.json`), a field engineer guide (`docs/MANUAL_LOADING_INSTRUCTIONS.md`), and a cryptographic `MANIFEST-SHA256.json`.
  - Added Pydantic schemas `CscapePackageOfflineBundleInput` and `CscapePackageOfflineBundleOutput` in [src/mcp/schemas.py](file:///C:/HornerAI/horner-cscape-mcp/src/mcp/schemas.py).
  - Registered in `TOOL_SCHEMAS`, bringing total FastMCP tools to **exactly 40** with 100% schema parity and package exports.
  - Verified packaging on `TankLevel_P5_Dedicated` (bundle SHA-256 verified) and verified fail-closed error handling on path traversal and missing projects.

### 1.5 Explicit Emulated Provenance Headers across Simulation & Variables Tools
- **Prior Limitation**: Offline simulation tools returned register snapshots, but lacked explicit machine-readable metadata declaring their mock/emulated provenance to LLM clients.
- **Engineering Solution**:
  - Added `"provenance": "TESTED_MOCK [offline/DEV only]"` and `"hardware_connected": False` to:
    - `cscape_read_register`
    - `cscape_write_register`
    - `cscape_simulate_cycle`
    - `cscape_simulate_pou`
    - `cscape_read_variables`
    - `cscape_write_variables`
    - `cscape_inspect_variables`
  - Added `provenance`, `hardware_connected`, and `isolation_enforced` to `CscapeOutputBase` in [src/mcp/schemas.py](file:///C:/HornerAI/horner-cscape-mcp/src/mcp/schemas.py), ensuring clean schema validation with `extra="forbid"`.

---

## 2. FastMCP Tool Registry Parity (40 Tools)

With the addition of `cscape_package_offline_bundle`, the FastMCP server now exposes exactly **40 tools**:

| Category | Tool Count | Tools |
| :--- | :---: | :--- |
| **Core Lifecycle & CFBF** | 12 | `cscape_create_project`, `cscape_open_project`, `cscape_save_project`, `cscape_close_project`, `cscape_compile_project`, `cscape_get_diagnostics`, `cscape_validate_st`, `cscape_add_st_pou`, `cscape_inspect_variables`, `cscape_read_variables`, `cscape_write_variables`, `cscape_export_project` |
| **Simulation & Emulation** | 2 | `cscape_simulate_pou`, `cscape_simulate_cycle` |
| **Register Word & Bit Memory** | 2 | `cscape_read_register`, `cscape_write_register` |
| **Variable Database Import/Export** | 2 | `cscape_import_variables`, `cscape_export_variables` |
| **Native HMI Automation** | 5 | `cscape_hmi_inventory`, `cscape_hmi_apply_group`, `cscape_hmi_read_properties`, `cscape_hmi_verify_bindings`, `cscape_hmi_save_close_reopen` |
| **Fixture Engine** | 6 | `cscape_fixture_request_to_spec`, `cscape_fixture_create`, `cscape_fixture_selective_edit`, `cscape_fixture_revision_impact`, `cscape_fixture_durability_check`, `cscape_fixture_detect_conflict` |
| **Modbus PV Provider** | 5 | `cscape_modbus_create_config`, `cscape_modbus_persist_config`, `cscape_modbus_read_config`, `cscape_modbus_protocol_check`, `cscape_modbus_conversion_doc` |
| **Project Creation & Compatibility** | 5 | `cscape_new_iec_project`, `cscape_inject_st_pou`, `cscape_build_project`, `cscape_get_build_output`, `cscape_inspect_project_structure` |
| **Offline Distribution Packaging** | 1 | `cscape_package_offline_bundle` |
| **Total** | **40** | **100% Matched in `TOOL_SCHEMAS` and exported in `src.mcp`** |

---

## 3. Test Verification & Safety Directives

All 251 tests pass cleanly across the regression suites:
- `tests/test_p9_offline_gaps.py`: **9/9 passed**
- `tests/test_p8_expand_and_harden.py`: **15/15 passed**
- `tests/test_security.py`: **227/227 passed**

### Safety Directives Maintained:
1. **Unconditional Download Lockout**: No automated downloading or serial flashing is permitted (`COM1`-`COM256`, CAN, USB, JTAG, Win32 command IDs `32827`/`33149`).
2. **Phase P7 Deferred**: Physical runtime commissioning is strictly deferred to field engineers.
3. **No Claim of `VERIFIED_LIVE`**: Live Cscape integration remains categorized honestly as `PARTIAL / SUPERVISOR-DEPENDENT`.
4. **No Claim of `CORE-09` / `CORE-10`**: Zero invented gates.
