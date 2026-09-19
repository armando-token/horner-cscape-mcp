# Horner APG Cscape FastMCP Server (v1.0.0)

Autonomous Model Context Protocol (MCP) server providing deterministic, safe, fail-closed integration with **Horner APG Cscape 10.2 (Build 10.2.751.4)** and native **`.csp`** Compound File Binary Format (CFBF) project containers.

## Features
- **FastMCP Protocol**: Standard JSON-RPC 2.0 transport over `stdio`.
- **40 Announced & Enabled Tools**: Project creation, pure IEC 61131-3 Structured Text validation, compiler Error Check (`32826`), OCS memory variable mapping, deterministic scan cycle simulation, native HMI verification, air-gapped distribution bundler, and Modbus PV provider sidecar configuration.
- **Fail-Closed Safety Policy**: Complete hardware port lockout (`COM1`–`COM256`, CAN, USB, JTAG) and Win32 download command interception (`32827`/`33149`).
- **4-State Status Contract**: Every tool response deterministically adheres to `{"status": "success | failed | blocked | inconclusive"}`.
- **Native CFBF Integrity**: Pure Compound File Binary Format (OLE2) preservation with zero Straton K5 quarantine contamination.

## Requirements
- Windows 10 / Windows 11 (x64)
- Python 3.10, 3.11, or 3.12 (64-bit)
- Horner APG Cscape 10.2 (Build 10.2.751.4) installed at standard system path
