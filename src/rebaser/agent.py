import asyncio
import os

from contextlib import asynccontextmanager
from dotenv import load_dotenv
from pathlib import Path


from loguru import logger
from mcp.types import Tool as MCPTool
from google.genai.client import AsyncClient, BaseApiClient
from google.genai.chats import AsyncChat, GenerateContentResponse
from google.genai.errors import APIError
from google.genai.types import (
    FunctionCall,
    FunctionDeclarationDict,
    GenerateContentConfigDict,
    SchemaDict,
)

from rebaser.mcp_client import MCPClient
from rebaser.model import MCPToolOutput, convert_to_schema, clean_schema

load_dotenv()
api_client = BaseApiClient(api_key=os.environ["gemini_key"])
client = AsyncClient(api_client=api_client)


async def get_function_call(
    response: GenerateContentResponse, agent: AsyncChat
) -> FunctionCall:
    if calls := response.function_calls:
        function = calls[0]
        if function.name:
            return function
    response = await agent.send_message("Function must have a name")
    return await get_function_call(response, agent)


async def agent_loop(
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
    try:
        response = await agent.send_message(message=query)
        function = await get_function_call(response, agent)
        result = await server.call_tool(function.name, function.args)  # type: ignore Dumbest error ever
        response_text = response.text or ""
        return (
            response_text + result.content[0].text
            if result.content[0].type == "text"
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
        return await agent_loop(query, agent, server, attempt + 1)


def create_config(
    tools: list[MCPTool],
) -> tuple[GenerateContentConfigDict, dict[str, SchemaDict]]:
    """Create a config for the agent."""
    function_declarations: list[FunctionDeclarationDict] = []
    schemas: dict[str, SchemaDict] = {}
    for tool in tools:
        schema = clean_schema(tool.inputSchema)
        function: FunctionDeclarationDict = {
            "name": tool.name,
            "description": tool.description,
            "response": convert_to_schema(MCPToolOutput),
        }
        if schema:
            function["parameters"] = schema
        function_declarations.append(function)

        schemas[tool.name] = schema

    return {
        "tools": [{"function_declarations": function_declarations}]
    }, schemas


def prompt_user() -> str:
    """Prompt the user to continue or exit."""
    user = input("Continue? (y/n) or offer feedback (f): ")
    while True:
        if user.lower() in ["y", "n", "f"]:
            return user.lower()
        print(f"Invalid input {user}. Please enter 'y', 'n', or 'f'.")


async def query_user(
    response: str, agent: AsyncChat, server: MCPClient
) -> None:
    while True:
        print(response)
        user = prompt_user()
        if user == "n":
            break
        elif user == "f":
            query = input("Please provide feedback: ")
        else:
            query = "Continue"
        response = await agent_loop(query, agent, server)


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
    async with get_server(repo_path) as server_client:
        tools = await get_tools(server_client)

        logger.debug("Initializing config...")
        config, schemas = create_config(tools)
        logger.debug(config)
        tool_schemas = "\n".join(
            f"{name}: {schema}" for name, schema in schemas.items()
        )
        logger.debug(tool_schemas)
        initial_query_text = initial_query_file.read_text()
        initial_query = initial_query_text.format(
            plan_file=str(plan_file),
            base_ref=base_commit,
            tool_schemas=tool_schemas,
        )
        logger.debug("Creating agent")
        agent = client.chats.create(model=os.environ["model"], config=config)
        logger.debug("Sending initial query...")
        response = await agent_loop(initial_query, agent, server_client)

        await query_user(response, agent, server_client)


def main(repo_path: Path, base_commit: str, plan_file: Path, query_file: Path):
    logger.debug("Initializing MCP client...")
    asyncio.run(initialize(repo_path, base_commit, plan_file, query_file))
