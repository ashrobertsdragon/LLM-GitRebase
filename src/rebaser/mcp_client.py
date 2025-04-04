import asyncio
import os
from contextlib import AsyncExitStack
from collections.abc import Callable
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from google.genai.client import AsyncClient, BaseApiClient
from google.genai.chats import AsyncChat
from google.genai.types import (
    GenerateContentConfig,
)
from google.genai.errors import APIError
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


load_dotenv()
api_client = BaseApiClient(api_key=os.environ["gemini_key"])
client = AsyncClient(api_client=api_client)


class MCPClient:
    """A client class for interacting with the MCP (Model Control Protocol) server"""

    def __init__(self):
        """Initialize the MCP client"""
        self.session: ClientSession | None = None
        self.exit_stack = AsyncExitStack()

        self.tools: list[dict] = []

    async def connect_to_server(self, server_params: StdioServerParameters):
        """Establishes connection to MCP server"""
        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(self.stdio, self.write)
        )

        await self.session.initialize()

        response = await self.session.list_tools()
        self.tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema,
            }
            for tool in response.tools
        ]
        logger.debug(f"Server initialized with tools: {self.tools}")

    def call_tool(self, tool_name: str) -> Callable:
        """
        Create a callable function for a specific tool.
        Args:
            tool_name: The name of the tool to create a callable for
        Returns:
            A callable async function that executes the specified tool
        """

        async def tool(**kwargs):
            if not self.session:
                raise RuntimeError("Not connected to MCP server")
            response = await self.session.call_tool(
                tool_name, arguments=kwargs
            )
            return response

        return tool


async def agent_loop(query: str, agent: AsyncChat, attempt: int = 0) -> str:
    """
    Run a single interaction with the agent.
    Args:
        query: The query to send to the agent
        agent: The agent to use for the interaction
    Returns:
        The response from the agent
    """
    try:
        response = await agent.send_message(message=query)
        return response.text or ""
    except APIError as e:
        if attempt > 3:
            raise APIError(e.code, e.details, e.response) from e
        sleep_time = attempt**2
        logger.info(
            f"Error {e.code}: {e.status} - {e.message}. Retrying in {sleep_time} seconds"
        )
        await asyncio.sleep(sleep_time)
        return await agent_loop(query, agent, attempt + 1)


def create_config(tools: list[dict]) -> GenerateContentConfig:
    _tools = [tool["name"] for tool in tools]
    return GenerateContentConfig(tools=_tools)  # type: ignore


def prompt_user() -> str:
    """Prompt the user to continue or exit."""
    user = input("Continue? (y/n): ")
    while True:
        if user in ["y", "n"]:
            return user
        print("Invalid input. Please enter 'y' or 'n'.")


async def initialize(
    repo_path: str, base_commit, plan_file: Path, initial_query_file: Path
):
    """
    Main function that initializes the MCP client, connects to the MCP server, and runs the agent.
    Args:
        repo_path: The path to the repository
        plan: The rebasing plan
    """
    server = StdioServerParameters(
        command="uv", args=["run", "rebase_mcp_server", repo_path]
    )
    mcp_client = MCPClient()
    await mcp_client.connect_to_server(server)

    config = create_config(mcp_client.tools)
    agent = client.chats.create(model=os.environ["model"], config=config)

    initial_query_text = initial_query_file.read_text()
    initial_query = initial_query_text.format(
        plan_file=plan_file, base_ref=base_commit
    )

    response = await agent_loop(initial_query, agent)

    while True:
        print(response)
        if prompt_user() == "n":
            break
        response = await agent_loop(response, agent)


def main(repo_path: str, base_commit: str, plan_file: Path, query_file: Path):
    logger.debug("Initializing MCP client...")
    asyncio.run(initialize(repo_path, base_commit, plan_file, query_file))
