from enum import StrEnum
from typing import Literal, TypedDict
from pydantic import BaseModel, Field


class RebaseCommit(BaseModel):
    """A rebasing action."""

    sha: str = Field(..., min_length=7, max_length=40)
    action: Literal["PICK", "REWORD", "EDIT", "SQUASH", "FIXUP", "DROP"]
    message: str | None = Field(None, min_length=1)


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
