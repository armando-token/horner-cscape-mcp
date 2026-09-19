"""
Standalone FastMCP Server Runner for Horner Cscape MCP Integration.
Conforms to Model Context Protocol (MCP) over stdio transport using JSON-RPC 2.0.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Add bundle root to sys.path
BUNDLE_ROOT = Path(__file__).parent.resolve()
if str(BUNDLE_ROOT) not in sys.path:
    sys.path.insert(0, str(BUNDLE_ROOT))

from src.mcp.server import SERVER_NAME, SERVER_VERSION, server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],  # Keep stdout clean for stdio JSON-RPC
)
logger = logging.getLogger("horner_mcp_server")


def main() -> None:
    parser = argparse.ArgumentParser(description="Horner APG Cscape FastMCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio", help="MCP transport protocol")
    parser.add_argument("--host", default="127.0.0.1", help="SSE host binding")
    parser.add_argument("--port", type=int, default=8000, help="SSE port binding")
    args = parser.parse_args()

    logger.info(f"Starting {SERVER_NAME} v{SERVER_VERSION} (Transport: {args.transport})...")
    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(transport="sse", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
