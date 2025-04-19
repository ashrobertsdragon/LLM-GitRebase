from enum import StrEnum
from typing import Literal, TypedDict, overload
from pydantic import BaseModel, Field
from google.genai.types import SchemaDict


class RebaseCommit(BaseModel):
    """A rebasing action."""

    sha: str = Field(..., min_length=7, max_length=40)
    action: Literal["PICK", "REWORD", "EDIT", "SQUASH", "FIXUP", "DROP"]
    message: str | None = Field(None, min_length=1)


class RebasePlan(BaseModel):
    plan: list[RebaseCommit] = Field(default_factory=list)


class GitCommand(BaseModel):
    """A validated git command."""

    command: Literal["add", "checkout", "reset", "rebase", "commit"]
    args: list[str] = Field(default_factory=list)

    def to_command_list(self) -> list[str]:
        """Convert the command to a list suitable for subprocess."""
        return [self.command] + self.args


class RebaseState(StrEnum):
    """The state of the rebase process."""

    UN_STARTED = "un_started"
    IN_PROGRESS = "in_progress"
    CONFLICT = "conflict"
    FINISHED = "finished"


class MCPToolOutput(TypedDict):
    """The output of the MCP tool."""

    success: bool
    message: str


class MergeStrategy(BaseModel):
    """A merge strategy."""

    file_path: str
    content: str


class GitRebaseTools(StrEnum):
    START_REBASE = "git_start_rebase"
    EDIT_COMMIT = "git_edit_commit"
    RESUME_REBASE = "git_resume_rebase"


class GitStartRebase(BaseModel):
    branch: str
    base_commit: str = Field(..., min_length=7, max_length=40)
    rebase_plan: list[RebaseCommit] = Field(default_factory=list)


class GitEditCommit(BaseModel):
    commit_sha: str = Field(..., min_length=7, max_length=40)
    merge_strategy: list[MergeStrategy] = Field(default_factory=list)


class FileOperation(BaseModel):
    """Model for file operations during rebasing"""

    commit_sha: str
    file_path: str
    operation_type: Literal["modify", "restore", "delete", "rename"]
    content: str | None = Field(default=None, min_length=1)
    new_file_path: str | None = Field(default=None, min_length=1)

    class Config:
        extra = "forbid"


FileOperation.model_json_schema()


def convert_to_schema(
    typed_dict: type[TypedDict],  # type: ignore[valid-type]
) -> SchemaDict:
    py_json_map = {
        "str": "string",
        "int": "integer",
        "float": "number",
        "bool": "boolean",
        "list": "array",
        "dict": "object",
    }

    properties = {}
    required = []

    for key, type_ in typed_dict.__annotations__.items():
        properties[key] = {"type": py_json_map[type_.__name__]}
        required.append(key)

    return {"properties": properties, "required": required}


def clean_inline_schema(schema: dict) -> SchemaDict:
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
                if k in ["additionalProperties", "$schema"]:
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
    for key in ["$defs", "title", "type"]:
        if key in updated_schema:
            updated_schema.pop(key)

    return SchemaDict(**updated_schema)
