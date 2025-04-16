from contextlib import AsyncExitStack
from datetime import timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, Tool


class MCPClient:
    """A client class for interacting with the MCP (Model Control Protocol) server"""

    def __init__(self):
        """Initialize session and client objects"""
        self.session: ClientSession | None = None
        self.exit_stack = AsyncExitStack()
        self._tools: list[Tool] = []

    async def connect_to_server(
        self, command: str, args: list[str], env: dict[str, str] | None
    ) -> None:
        """Establishes connection to MCP server."""
        server_params = StdioServerParameters(
            command=command, args=args, env=env
        )

        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(
                self.stdio,
                self.write,
                read_timeout_seconds=timedelta(seconds=30),
            )
        )

        await self.session.initialize()

    @property
    async def tools(self) -> list[Tool]:
        if not self._tools:
            self._tools = await self._list_tools()
        return self._tools

    async def _list_tools(self) -> list[Tool]:
        """Exposes the session's list_tools method."""
        if self.session is None:
            raise ValueError("Server is not initialized")
        tool_result = await self.session.list_tools()
        return tool_result.tools

    async def call_tool(
        self, name: str, args: dict | None = None
    ) -> CallToolResult:
        """Exposes the session's call_tool method."""
        if self.session is None:
            raise ValueError("Server is not initialized")
        return await self.session.call_tool(name, args)

    async def aclose(self):
        """Clean up resources"""
        await self.exit_stack.aclose()
