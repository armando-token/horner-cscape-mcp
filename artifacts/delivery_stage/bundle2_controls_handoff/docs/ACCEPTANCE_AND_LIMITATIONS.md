# Acceptance Results and Platform Limitations

## 1. Acceptance Traceability
- **Phase P0**: Reconciliation and Contract Audit — **ACCEPTED**
- **Phase P1**: Diagnostics Air-Gapped Export and Negative Tests — **ACCEPTED**
- **Phase P2**: Native Mutation and Correlated Integration — **ACCEPTED**
- **Phase P3**: Native Cscape HMI and Object Group Bindings — **ACCEPTED**
- **Phase P4**: LLM/MCP Fixture Evolution and Selective Edit — **EVIDENCE ON RECORD**
- **Phase P5**: Native Cscape Modbus PV Provider Configuration — **ACCEPTED BY SUPERVISOR**
  - Persistence verified on `MJ1 CT RTU Modbus CMP  v 5.05` / `Modbus Master  v 5.07`.
  - Durability confirmed across Cscape live save, close, reopen, and compile.
- **Phase P6**: Standalone Delivery and Distribution Outside DEV Session — **IN PROGRESS**
- **Phase P7 / CORE-08**: Physical PLC runtime and live sensor verification — **PENDING_P7**
  - Invariant: Zero PLC download; physical runtime verification strictly deferred to Phase P7.
  - Invariant: CORE-08 remains incomplete pending physical hardware verification.

## 2. Documented Platform Limitations
1. **In-GUI ST-to-Ladder Conversion**: Horner Cscape 10.2 contains zero menu items, accelerator commands, or DLL exports for ST-to-Ladder conversion (`BLOCKED_NATIVE: DOCUMENT_ONLY`). Offline AST translation is supported via `STLadderInteropGuard`, but GUI conversion is permanently blocked.
2. **Fail-Closed Hardware Lockouts**: Physical port access (`COM1`–`COM256`, CAN, USB, JTAG) and Win32 download command IDs (`32827`, `33149`) are permanently blocked by safety guardrails.
3. **Pure Structured Text Scope**: Ladder constructs inside `.st` POUs are rejected with `ERR_LADDER_FORBIDDEN`.
