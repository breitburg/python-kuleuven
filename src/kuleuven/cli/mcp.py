import asyncio
import os
import shutil
import subprocess
import warnings
from typing import Annotated

import typer

# claude_desktop_config 0.2.1 has a non-raw docstring with `\C` in impl.py:30
# that triggers SyntaxWarning on Python 3.12+. Suppress only during its
# import; remove once the upstream library ships a fix.
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=SyntaxWarning)
    from claude_desktop_config.api import (
        ClaudeDesktopConfig,
        disable_mcp_server,
        enable_mcp_server,
    )
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequest,
    CallToolResult,
    ListToolsRequest,
    ListToolsResult,
    ServerResult,
    TextContent,
    Tool,
)
from pycli_mcp import CommandMCPServer, CommandQuery

from kuleuven.cli.output import emit

mcp_app = typer.Typer(
    no_args_is_help=True,
    help="Run the KU Leuven MCP server and manage Claude Desktop integration",
)

# files.sync and files.fetch write to local disk, which is meaningless from
# Claude Desktop (use files.resolve to get a fetchable URL instead); the
# mcp.* commands manage the server itself.
EXCLUDE_PATTERN = r"^(toledo courses files sync|toledo courses files fetch|mcp .*)$"


@mcp_app.command()
def start() -> None:
    """Run a stdio MCP server exposing the Toledo CLI to Claude Desktop."""
    from kuleuven.cli import app as toledo_app

    query = CommandQuery(
        toledo_app,
        aggregate="none",
        name="kuleuven",
        exclude=EXCLUDE_PATTERN,
    )
    mcp_server = CommandMCPServer(commands=[query])
    low_level = mcp_server.server

    # Claude Desktop validates tool names against ^[a-zA-Z0-9_-]{1,64}$, but
    # pycli-mcp produces dotted names like `toledo.courses.list`. Build a
    # rename table and override the list/call handlers to use underscores.
    by_safe_name = {
        dotted.replace(".", "_"): command
        for dotted, command in mcp_server.commands.items()
    }
    safe_tools = [
        Tool(
            name=name,
            description=command.tool.description,
            inputSchema=command.tool.inputSchema,
        )
        for name, command in by_safe_name.items()
    ]

    async def list_tools_handler(_request: ListToolsRequest) -> ServerResult:
        return ServerResult(ListToolsResult(tools=safe_tools))

    async def call_tool_handler(request: CallToolRequest) -> ServerResult:
        name = request.params.name
        arguments = request.params.arguments or {}
        command = by_safe_name.get(name)
        if command is None:
            return ServerResult(
                CallToolResult(
                    content=[TextContent(type="text", text=f"Unknown tool: {name}")],
                    isError=True,
                )
            )
        argv = command.metadata.construct(arguments)
        env = {**os.environ, "PYCLI_MCP_TOOL_NAME": name}
        process = await asyncio.to_thread(
            subprocess.run,
            argv,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        if process.returncode:
            text = (
                f"{process.stdout}\nThis command exited with non-zero exit code "
                f"`{process.returncode}`: {argv}"
            )
            return ServerResult(
                CallToolResult(
                    content=[TextContent(type="text", text=text)], isError=True
                )
            )
        return ServerResult(
            CallToolResult(content=[TextContent(type="text", text=process.stdout)])
        )

    low_level.request_handlers[ListToolsRequest] = list_tools_handler
    low_level.request_handlers[CallToolRequest] = call_tool_handler

    async def serve() -> None:
        async with stdio_server() as (read, write):
            await low_level.run(
                read, write, low_level.create_initialization_options()
            )

    asyncio.run(serve())


@mcp_app.command()
def install(
    name: Annotated[
        str,
        typer.Option(help="Name of the MCP server entry in Claude Desktop."),
    ] = "kuleuven",
) -> None:
    """Register the KU Leuven MCP server in Claude Desktop's config."""
    kuleuven_path = shutil.which("kuleuven")
    if not kuleuven_path:
        emit(
            {
                "status": "error",
                "code": "kuleuven_not_on_path",
                "message": "Could not find the `kuleuven` executable on PATH; install with `uv tool install python-toledo` or activate the relevant environment.",
            },
            exit_code=1,
        )

    cdc = ClaudeDesktopConfig()
    config = cdc.read()
    changed = enable_mcp_server(
        config, name, {"command": kuleuven_path, "args": ["mcp", "start"]}
    )
    if changed:
        cdc.write(config)

    emit(
        {
            "status": "ok",
            "config_path": str(cdc.path),
            "name": name,
            "command": kuleuven_path,
            "changed": changed,
            "restart_required": changed,
        }
    )


@mcp_app.command()
def uninstall(
    name: Annotated[
        str,
        typer.Option(help="Name of the MCP server entry to remove."),
    ] = "kuleuven",
) -> None:
    """Remove the KU Leuven MCP server from Claude Desktop's config."""
    cdc = ClaudeDesktopConfig()
    config = cdc.read()
    changed = disable_mcp_server(config, name)
    if changed:
        cdc.write(config)

    emit(
        {
            "status": "ok",
            "config_path": str(cdc.path),
            "name": name,
            "removed": changed,
        }
    )
