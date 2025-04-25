import os

from typing import overload
from dotenv import load_dotenv
from pathlib import Path


from loguru import logger
from mcp.types import Tool as MCPTool
from google.genai.client import AsyncClient, BaseApiClient
from google.genai.chats import AsyncChat
from google.genai.types import (
    FunctionDeclarationDict,
    GenerateContentConfigDict,
    SchemaDict,
)


load_dotenv()
api_client = BaseApiClient(api_key=os.environ["gemini_key"])
client = AsyncClient(api_client=api_client)


def clean_schema(schema: dict) -> SchemaDict:
    """Inlines Pydantic $ref definitions within a JSON schema."""
    definitions = schema.get("$defs", {})

    def _resolve_ref(ref: str) -> dict:
        ref_path = ref.replace("#/$defs/", "").split("/")
        current = definitions

        for part in ref_path:
            if part not in current:
                return {"$ref": ref}
            current = current[part]
        return current

    @overload
    def _inline(obj: dict) -> dict: ...
    @overload
    def _inline(obj: list) -> list: ...
    @overload
    def _inline(obj: str) -> str: ...
    def _inline(obj: dict | list | str) -> dict | list | str:
        if isinstance(obj, dict):
            new_obj = {}
            for k, v in obj.items():
                if k in ["additionalProperties", "$schema", "default"]:
                    continue
                if (
                    k == "$ref"
                    and isinstance(v, str)
                    and v.startswith("#/$defs/")
                ):
                    ref_value = _resolve_ref(v)
                    inlined = _inline(ref_value)
                    new_obj.update(inlined)
                else:
                    new_obj[k] = _inline(v)
            return new_obj
        elif isinstance(obj, list):
            return [_inline(item) for item in obj]
        return obj

    updated_schema = _inline(schema)
    updated_schema["properties"].pop("self")
    updated_schema["required"].remove("self")
    for key in ["$defs", "title"]:
        if key in updated_schema:
            updated_schema.pop(key)

    return SchemaDict(**updated_schema)


def create_config(
    tools: list[MCPTool],
) -> tuple[GenerateContentConfigDict, dict[str, SchemaDict]]:
    """Create a config for the agent."""
    function_declarations: list[FunctionDeclarationDict] = []
    schemas: dict[str, SchemaDict] = {}

    logger.debug("Initializing config...")
    for tool in tools:
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
    logger.debug(tool_schemas)
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
