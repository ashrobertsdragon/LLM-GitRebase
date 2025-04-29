import os
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from mcp.types import Tool as MCPTool
from google.genai.client import AsyncClient, BaseApiClient
from google.genai.chats import AsyncChat
from google.genai.types import (
    FunctionDeclarationDict,
    GenerateContentConfigDict,
    SchemaDict,
)

from rebaser.clean_schema import clean_schema

load_dotenv()
api_client = BaseApiClient(api_key=os.environ["gemini_key"])
client = AsyncClient(api_client=api_client)


def create_config(
    tools: list[MCPTool],
) -> tuple[GenerateContentConfigDict, dict[str, SchemaDict]]:
    """Create a config for the agent."""
    function_declarations: list[FunctionDeclarationDict] = []
    schemas: dict[str, SchemaDict] = {}

    logger.debug("Initializing config...")
    for i, tool in enumerate(tools, 1):
        function: FunctionDeclarationDict = {
            "name": tool.name,
            "description": tool.description,
        }
        if schema := clean_schema(tool.inputSchema):
            function["parameters"] = schema
            schemas[tool.name] = schema
        function_declarations.append(function)

    return {
        "tools": [{"function_declarations": function_declarations}]
    }, schemas


def create_initial_query(
    initial_query_file: Path,
    plan_file: Path,
    base_commit: str,
    schemas: dict[str, SchemaDict],
):
    tool_schemas = "\n".join(
        f"{name}: {schema}" for name, schema in schemas.items()
    )
    initial_query_text = initial_query_file.read_text()
    return initial_query_text.format(
        plan_file=str(plan_file),
        base_ref=base_commit,
        tool_schemas=tool_schemas,
    )


def build(
    tools: list[MCPTool],
    base_commit: str,
    plan_file: Path,
    initial_query_file: Path,
) -> tuple[AsyncChat, str]:
    config, schemas = create_config(tools)
    initial_query = create_initial_query(
        initial_query_file, plan_file, base_commit, schemas
    )
    logger.debug("Creating agent")
    return client.chats.create(
        model=os.environ["model"], config=config
    ), initial_query
