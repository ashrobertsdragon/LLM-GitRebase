import asyncio
import os

from dotenv import load_dotenv
from pathlib import Path


from loguru import logger
from google.genai.client import AsyncClient, BaseApiClient
from google.genai.chats import AsyncChat
from google.genai.types import (
    GenerateContentConfig,
)
from google.genai.errors import APIError
from mcp import StdioServerParameters

from rebaser.mcp_client import MCPClient

load_dotenv()
api_client = BaseApiClient(api_key=os.environ["gemini_key"])
client = AsyncClient(api_client=api_client)


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
    user = input("Continue? (y/n) or offer feedback (f): ")
    while True:
        if user.lower() in ["y", "n", "f"]:
            return user.lower()
        print(f"Invalid input {user}. Please enter 'y', 'n', or 'f'.")


async def query_user(response: str, agent: AsyncChat) -> None:
    while True:
        print(response)
        user = prompt_user()
        if user == "n":
            break
        elif user == "f":
            query = input("Please provide feedback: ")
        else:
            query = "Continue"
        response = await agent_loop(query, agent)


async def initialize(
    repo_path: str,
    base_commit: str,
    plan_file: Path,
    initial_query_file: Path,
) -> None:
    """
    Initializes the MCP client, connects to the MCP server,and runs the agent.

    Args:
        repo_path: The path to the repository (originally URL)
        plan_file: The path to the plan file
        initial_query_file: The path to the initial query file
    """
    rebase_server = StdioServerParameters(
        command="uv",
        args=[
            "run",
            "rebase-mcp-server",
            repo_path,
        ],
        env=None,
    )
    rebase_client = MCPClient()

    git_server = StdioServerParameters(
        command="uv",
        args=[
            "run",
            "git_mcp_server",
            repo_path,
        ],
        env=None,
    )
    git_client = MCPClient()

    try:
        logger.debug("Connecting to MCP servers...")
        await rebase_client.connect_to_server(rebase_server)
        await git_client.connect_to_server(git_server)
        logger.debug("Connected to MCP servers.")

        config = create_config(rebase_client.tools + git_client.tools)
        agent = client.chats.create(model=os.environ["model"], config=config)

        rebase_tool_schemas = "\n".join([
            f'{tool["name"]: tool["input_schema"]}'
            for tool in rebase_client.tools
        ])

        git_tool_schemas = "\n".join([
            f'{tool["name"]: tool["input_schema"]}'
            for tool in git_client.tools
        ])

        tool_schemas = f"{rebase_tool_schemas}\n{git_tool_schemas}"
        initial_query_text = initial_query_file.read_text()
        initial_query = initial_query_text.format(
            plan_file=str(plan_file),
            base_ref=base_commit,
            tool_schemas=tool_schemas,
        )

        response = await agent_loop(initial_query, agent)

        await query_user(response, agent)

    finally:
        await rebase_client.exit_stack.aclose()
        await git_client.exit_stack.aclose()
        logger.debug("MCP client resources closed.")


def main(repo_path: str, base_commit: str, plan_file: Path, query_file: Path):
    logger.debug("Initializing MCP client...")
    asyncio.run(initialize(repo_path, base_commit, plan_file, query_file))
