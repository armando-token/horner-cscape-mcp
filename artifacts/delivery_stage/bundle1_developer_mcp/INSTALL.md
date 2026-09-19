# Installation & Client Configuration Guide

## 1. System Requirements & Prerequisites
- **Operating System**: Microsoft Windows 10 or Windows 11 (64-bit).
- **Python Version**: Python 3.10, 3.11, or 3.12 (64-bit) with `pip` and `venv`.
- **Target Software**: Horner APG Cscape 10.2 (Build 10.2.751.4) installed under `C:\Program Files (x86)\Cscape 10.2\`.

## 2. Environment Setup
Open PowerShell or Command Prompt in this directory and execute:

```powershell
# Create isolated virtual environment
python -m venv .venv

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Upgrade pip and install pinned dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 3. Verifying Installation
Run the server self-test to verify tools registration:

```powershell
python -c "from src.mcp.server import server; print(f'Successfully loaded {len(server._tool_manager.list_tools())} FastMCP tools.')"
```
Expected output:
```text
Successfully loaded 40 FastMCP tools.
```

## 4. MCP Client Configuration

### Claude Desktop Configuration (`claude_desktop_config.json`)
Add the server entry to `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "horner-cscape": {
      "command": "C:\\path\\to\\bundle\\.venv\\Scripts\\python.exe",
      "args": [
        "C:\\path\\to\\bundle\\run_mcp_server.py",
        "--transport",
        "stdio"
      ]
    }
  }
}
```

### Cursor / Antigravity / Generic FastMCP JSON Configuration
```json
{
  "name": "horner-cscape-mcp",
  "command": ".venv\\Scripts\\python.exe",
  "args": ["run_mcp_server.py", "--transport", "stdio"],
  "transport": "stdio"
}
```

## 5. Security Invariants
- **Offline / Emulated Simulation**: All scan cycle simulations run in-memory (`SimulationBackend.EMULATED`).
- **Physical Lockout**: Physical serial ports (`COM1`–`COM256`), industrial fieldbuses (`CAN`, `CsCAN`), USB download dongles, and Win32 download command IDs (`32827`, `33149`) are unconditionally blocked.
