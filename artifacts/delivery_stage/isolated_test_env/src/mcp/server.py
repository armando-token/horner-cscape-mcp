"""Horner Cscape Model Context Protocol (MCP) Server.

Standard FastMCP / Server instance exposing tools, resources, and prompts
over stdio transport for integration with AI coding agents and IDEs.
"""

from typing import Optional
from mcp.server import MCPServer

from .prompts import register_prompts
from .resources import register_resources
from .tools import (
    cscape_insert_st,
    cscape_insert_st_pou,
    cscape_read_variables,
    cscape_write_variables,
    cscape_import_variables,
    cscape_export_variables,
    cscape_export_project,
    cscape_simulate_cycle,
    cscape_read_register,
    cscape_write_register,
    cscape_hmi_inventory,
    cscape_hmi_apply_group,
    cscape_hmi_read_properties,
    cscape_hmi_verify_bindings,
    cscape_hmi_save_close_reopen,
    register_tools,
)

# Alias for standard FastMCP compatibility
FastMCP = MCPServer

SERVER_NAME = "horner-cscape-mcp"
SERVER_VERSION = "1.0.0"
SERVER_INSTRUCTIONS = """Horner Cscape Model Context Protocol (MCP) Server.
Specializes in IEC 61131-3 Structured Text (ST) engineering, Horner Cscape 10.2 integration,
syntax validation, software simulation, variable inspection, and project lifecycle management.
Pure Structured Text ONLY; Advanced Ladder is strictly avoided.
Hardware lockout active: Local compile and software simulation only; zero physical PLC downloads.
"""


def create_mcp_server(
    name: str = SERVER_NAME,
    instructions: str = SERVER_INSTRUCTIONS,
) -> MCPServer:
    """Factory function creating and configuring the Horner Cscape MCP server."""
    server = MCPServer(
        name=name,
        instructions=instructions,
        version=SERVER_VERSION,
    )

    # Register tools, resources, and prompts
    register_tools(server)
    register_resources(server)
    register_prompts(server)

    return server


# Default server instance
server: MCPServer = create_mcp_server()


def run(transport: str = "stdio") -> None:
    """Runs the MCP server with the specified transport (defaults to stdio)."""
    server.run(transport=transport)


if __name__ == "__main__":
    run("stdio")
