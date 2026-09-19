import asyncio
import json
import sys
from pathlib import Path

WORKSPACE = Path(r"C:\Users\ArmandoSilva").resolve()
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from src.mcp.server import server

async def dump_schemas():
    tools = await server.list_tools()
    for t in tools:
        print(f"TOOL: {t.name}")
        schema = t.input_schema if hasattr(t, "input_schema") else getattr(t, "parameters", {})
        print(f"  Required: {schema.get('required', []) if isinstance(schema, dict) else getattr(schema, 'required', [])}")
        props = schema.get("properties", {}) if isinstance(schema, dict) else getattr(schema, "properties", {})
        print(f"  Properties: {list(props.keys())}")

if __name__ == "__main__":
    asyncio.run(dump_schemas())
