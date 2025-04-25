from contextlib import asynccontextmanager
from pathlib import Path

from loguru import logger
from mcp.types import Tool as MCPTool

from rebaser.mcp_client import MCPClient


@asynccontextmanager
async def get_server(repo_path: Path):
    command = "uv"
    args = ["run", "server", str(repo_path)]
    logger.debug(f"running command: {command} {args}")
    client = MCPClient()
    try:
        await client.connect_to_server(command, args, env=None)
        yield client
    finally:
        await client.aclose()


async def get_tools(server_client: MCPClient) -> list[MCPTool]:
    return await server_client._list_tools()
