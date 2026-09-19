# Security & Safety Guard Directives

The Horner Cscape MCP Server implements strict fail-closed safety invariants to prevent unauthorized hardware writes, communication disruption, or firmware corruption:

1. **Hardware Communication Port Lockout**: Access to all physical serial ports (`COM1` through `COM256`), `/dev/tty*`, `CAN*`, `CsCAN`, `USB*`, and `JTAG` hardware interfaces is unconditionally blocked. Any attempt raises `SecurityError: COM port access blocked by safety policy`.
2. **Download & Flash Lockout**: Invocation of Win32 download command IDs (`ID_PROGRAM_DOWNLOAD = 32827`, `ID_CONTROLLER_DOWNLOAD = 33149`), CLI switches (`/download`, `/flash`), and companion utilities (`PGMUpdateUtility.exe`, `DfuSeCommand.exe`, `STMFlashLoader.exe`) is permanently blocked.
3. **Pure Structured Text Enforcement**: Legacy ladder logic syntax (contacts `---[ ]---`, coils `---( )---`, rung headers `RUNG`, `NETWORK`, mnemonics `XIC`, `XIO`, `OTE`) injected into `.st` POUs is rejected with `ERR_LADDER_FORBIDDEN`.
4. **Read-Only Fieldbus Provider**: Write command codes (`FC06`, `FC16`) directed to process variable providers are rejected fail-closed with Modbus Exception `0x01` (`ILLEGAL_FUNCTION`).
