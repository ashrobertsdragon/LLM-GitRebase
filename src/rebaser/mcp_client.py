from contextlib import AsyncExitStack

from loguru import logger
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPClient:
    """A client class for interacting with the MCP (Model Control Protocol) server"""

    def __init__(self):
        """Initialize the MCP client"""
        self.session: ClientSession | None = None
        self.exit_stack = AsyncExitStack()
        self.tools: list[dict] = []

    async def connect_to_server(self, server_params: StdioServerParameters):
        """Establishes connection to MCP server using AsyncExitStack for persistence."""

        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        self.stdio, self.write = stdio_transport

        self.session = await self.exit_stack.enter_async_context(
            ClientSession(self.stdio, self.write)
        )

        await self.session.initialize()
        logger.debug("MCP session initialized.")

        list_tools = await self.session.list_tools()
        self.tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema,
            }
            for tool in list_tools.tools
        ]
        logger.debug(f"Server initialized with tools: {self.tools}")
