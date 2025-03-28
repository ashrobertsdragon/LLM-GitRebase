from typing import Literal
from pydantic import BaseModel, Field


class RebaseCommit(BaseModel):
    """A rebasing action."""

    sha: str = Field(..., min_length=7, max_length=40)
    action: Literal["pick", "reword", "edit", "squash", "fixup", "drop"]
    message: str | None = Field(None, min_length=1)
