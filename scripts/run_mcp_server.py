#!/usr/bin/env python
"""Horner Cscape Model Context Protocol (MCP) Server Runner.

Executes the MCP server over stdio transport for communication with
AI assistant frontends, Claude Desktop, Cursor, and other MCP clients.
"""

import argparse
import os
import sys
from pathlib import Path

# Ensure workspace root is in sys.path
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from src.mcp.server import SERVER_NAME, SERVER_VERSION, server


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Horner Cscape Model Context Protocol (MCP) Server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport protocol to use",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{SERVER_NAME} v{SERVER_VERSION}",
    )
    args = parser.parse_args()

    try:
        # Standard MCP stdio server execution
        server.run(transport=args.transport)
    except KeyboardInterrupt:
        sys.stderr.write("\n[MCP] Server terminated by user.\n")
        sys.exit(0)
    except Exception as e:
        sys.stderr.write(f"\n[MCP ERROR] Server failed with exception: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
