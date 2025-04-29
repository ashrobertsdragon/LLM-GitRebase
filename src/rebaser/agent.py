import asyncio
from pathlib import Path


from loguru import logger
from google.genai.chats import AsyncChat, GenerateContentResponse
from google.genai.errors import APIError
from google.genai.types import (
    FunctionCall,
)

from rebaser import client
from rebaser.create_agent import build
from rebaser.mcp_client import MCPClient

logger.disable("google.genai.types")  # Disable unnecessary warnings


async def get_function_call(
    response: GenerateContentResponse, agent: AsyncChat
) -> FunctionCall:
    if calls := response.function_calls:
        function = calls[0]
        if function.name:
            return function
    response = await agent.send_message("Function must have a name")
    return await get_function_call(response, agent)


async def run_agent(
    query: str, agent: AsyncChat, server: MCPClient, attempt: int = 0
) -> str:
    """
    Run a single interaction with the agent.
    Args:
        query: The query to send to the agent
        agent: The agent to use for the interaction
    Returns:
        The response from the agent
    """
    result = None
    try:
        response = await agent.send_message(message=query)
        if function := await get_function_call(response, agent):
            result = await server.call_tool(function.name, function.args)  # type: ignore
        # TODO: Figure out how to get MyPy to recognize that get_function_call only returns if function.name
        response_text = response.text or ""
        return (
            response_text + result.content[0].text
            if result and result.content[0].type == "text"
            else response_text
        )
    except APIError as e:
        if attempt > 3:
            raise
        sleep_time = attempt**2
        logger.info(
            f"Error {e.code}: {e.status} - {e.message}. Retrying in {sleep_time} seconds"
        )
        await asyncio.sleep(sleep_time)
        return await run_agent(query, agent, server, attempt + 1)


def prompt_user() -> str:
    """Prompt the user to continue or exit."""
    user = input("Continue? (y/n) or offer feedback (f): ")
    while True:
        if user.lower() in ["y", "n", "f"]:
            return user.lower()
        print(f"Invalid input {user}. Please enter 'y', 'n', or 'f'.")
        user = input("> ")


async def agent_loop(query: str, agent: AsyncChat, server: MCPClient) -> None:
    while True:
        response = await run_agent(query, agent, server)
        print(response)
        logger.llm(response)  # type: ignore
        user = prompt_user()
        if user == "n":
            break
        elif user == "f":
            query = input("Please provide feedback: ")
            logger.user(query)  # type: ignore
        else:
            query = "Continue"


async def initialize(
    repo_path: Path,
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

    logger.debug("Connecting to MCP server...")
    async with client.get_server(repo_path) as server_client:
        tools = await client.get_tools(server_client)

        agent, initial_query = build(
            tools, base_commit, plan_file, initial_query_file
        )

        logger.debug("Sending initial query...")
        await agent_loop(initial_query, agent, server_client)


def main(repo_path: Path, base_commit: str, plan_file: Path, query_file: Path):
    logger.debug("Initializing MCP client...")
    asyncio.run(initialize(repo_path, base_commit, plan_file, query_file))
