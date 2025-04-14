# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "gitpython",
#     "loguru",
#     "pydantic",
#     "mcp[cli]"
# ]
# ///


import subprocess
import sys
from pathlib import Path
from typing import Literal, TypedDict

from loguru import logger
from git import Repo, GitCommandError
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

mcp = FastMCP(name="GitRebase-MCP")


class MCPToolOutput(TypedDict):
    """The output of the MCP tool."""

    success: bool
    message: str


class MergeStrategy(BaseModel):
    """A merge strategy."""

    file_path: str
    content: str


class FileOperation(BaseModel):
    """Model for file operations during rebasing"""

    commit_sha: str
    file_path: str
    operation_type: Literal["modify", "restore", "delete", "rename"]
    content: str | None = Field(default=None, min_length=1)
    new_file_path: str | None = Field(default=None, min_length=1)

    class Config:
        extra = "forbid"


class GitRebaseMCPToolManager:
    """MCP Tools for Git Rebasing"""

    def __init__(self, repo_path: str) -> None:
        self.repo = Repo(repo_path)
        self.repo_path = Path(repo_path)

    def _rebase_dir_exists(self) -> bool:
        """Check if the old or current rebase commit directory exists"""
        rebase_apply_dir = self.repo_path / ".git" / "rebase-apply"
        rebase_merge_dir = self.repo_path / ".git" / "rebase-merge"
        return rebase_apply_dir.exists() or rebase_merge_dir.exists()

    def _modify_file(
        self, file_path: Path, operation: FileOperation
    ) -> str | None:
        """Modify a file with new content"""
        if not operation.content:
            return f"Cannot modify {operation.file_path}: No content provided"
        file_path.write_text(operation.content)
        self.repo.git.add(operation.file_path)

    def _restore_file(
        self, file_path: Path, operation: FileOperation
    ) -> str | None:
        """Restore a deleted or modified file"""
        file_commit = self.repo.commit(operation.commit_sha)
        commit_parents = file_commit.parents
        if not commit_parents:
            return f"Cannot restore {operation.file_path}: No changes found"
        commit_parent = commit_parents[0]
        file_diffs = commit_parent.diff(file_commit, paths=operation.file_path)

        if not file_diffs:
            return f"Cannot restore {operation.file_path}: No changes found"

        file = file_diffs[0]
        if not file.a_rawpath:
            return f"Cannot restore {operation.file_path}: No changes found"
        with open(file.a_rawpath, "r", encoding="utf-8") as a:
            file_path.write_text(a.read())

        self.repo.git.add(operation.file_path)

    def _delete_file(
        self, file_path: Path, operation: FileOperation
    ) -> str | None:
        """Delete a file"""
        if not file_path.exists():
            return f"Cannot delete {operation.file_path}: file does not exist"
        self.repo.git.rm(operation.file_path)

    def _rename_file(
        self, file_path: Path, operation: FileOperation
    ) -> str | None:
        """Rename a file"""
        if not file_path.exists():
            return (
                f"Cannot rename {operation.file_path}: Source does not exist"
            )
        if not operation.new_file_path:
            return (
                f"Cannot rename {operation.file_path}: "
                "No new file path provided"
            )
        new_path = self.repo_path / operation.new_file_path
        if new_path.exists():
            return (
                f"Cannot rename {operation.file_path}: Target already exists"
            )
        self.repo.git.mv(operation.file_path, operation.new_file_path)

    @mcp.tool()
    def git_start_rebase(
        self, base_commit: str, rebase_plan: Path
    ) -> MCPToolOutput:
        """
        Initiates an interactive Git rebase using a provided plan.

        Args:
            base_commit: The commit hash to rebase onto.
            rebase_plan: The interactive rebase plan string.

        Returns:
            A dictionary containing the success status and a message.
        """
        rebase_command = ["git", "rebase", "-i", "--autosquash", base_commit]
        env = {"GIT_SEQUENCE_EDITOR": f"cat {rebase_plan.name} >"}

        try:
            process = subprocess.run(
                rebase_command,
                cwd=self.repo_path,
                env=env,
                capture_output=True,
                text=True,
                shell=False,
            )
            if process.returncode != 0:
                return {
                    "success": False,
                    "message": f"Error: Rebase failed.\n{process.stderr}",
                }

            if self.repo.index.conflicts:
                return {
                    "success": True,
                    "message": f"Rebase started with conflicts: {self.repo.index.conflicts}",
                }

            return {"success": True, "message": "Rebase started successfully."}

        except GitCommandError as e:
            return {"success": False, "message": f"Rebase failed: {e.stderr}"}
        except Exception as e:
            return {
                "success": False,
                "message": f"An unexpected error occurred: {e}",
            }

    @mcp.tool()
    def git_edit_commit(
        self, commit_hash: str, file_operations: list[FileOperation]
    ) -> MCPToolOutput:
        """
        Edits a commit with various file operations including content modification,
        file restoration, and file deletion.

        Args:
            commit_hash: The hash of the commit to edit.
            file_operations: A list of file operations to perform.

        Returns:
            A dictionary containing the success status and a message.
        """
        try:
            self.repo.rev_parse(commit_hash)
        except GitCommandError:
            return {
                "success": False,
                "message": f"Error: Commit '{commit_hash}' not found",
            }

        failures: list[str] = []
        try:
            self.repo.git.checkout(commit_hash)

            for operation in file_operations:
                file_path = self.repo_path / operation.file_path
                edit = {
                    "modify": self._modify_file,
                    "restore": self._restore_file,
                    "delete": self._delete_file,
                    "rename": self._rename_file,
                }
                if status := edit[operation.operation_type](
                    file_path, operation
                ):
                    failures.append(status)

            if failures:
                return {"success": False, "message": "\n".join(failures)}

            self.repo.git.commit("--amend", "--no-edit")
            self.repo.git.checkout("-")
            return {"success": True, "message": "Commit edited successfully"}

        except GitCommandError as e:
            return {"success": False, "message": f"Edit failed: {e.stderr}"}
        except Exception as e:
            return {
                "success": False,
                "message": f"An unexpected error occurred: {e}",
            }

    @mcp.tool()
    def git_resolve_conflicts(
        self, file_resolutions: list[MergeStrategy]
    ) -> MCPToolOutput:
        """
        Resolves conflicts during a rebase operation.

        Args:
            file_resolutions: A list of file paths and their resolved content.

        Returns:
            A dictionary containing the success status and a message.
        """
        if not self._rebase_dir_exists():
            return {
                "success": False,
                "message": "Error: No rebase in progress.",
            }

        if not self.repo.index.conflicts:
            return {
                "success": False,
                "message": "Error: No conflicts to resolve.",
            }
        try:
            for resolution in file_resolutions:
                file_path = self.repo_path / resolution.file_path
                file_path.write_text(resolution.content)
                self.repo.git.add(resolution.file_path)

            return {
                "success": True,
                "message": "Conflicts resolved successfully.",
            }

        except GitCommandError as e:
            return {
                "success": False,
                "message": f"Conflict resolution failed: {e.stderr}",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"An unexpected error occurred: {e}",
            }

    @mcp.tool()
    def git_resume_rebase(self) -> MCPToolOutput:
        """
        Continues a paused Git rebase operation.

        Returns:
            A dictionary containing the success status and a message.
        """
        try:
            self.repo.git.rebase("--continue")
        except GitCommandError as e:
            if "conflicts" not in e.stderr:
                return {
                    "success": False,
                    "message": f"Rebase paused due to: {e.stderr}",
                }
            return {
                "success": False,
                "message": f"Rebase paused due to conflicts: {e.stderr}",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"An unexpected error occurred: {e}",
            }

        if not self._rebase_dir_exists():
            return {
                "success": True,
                "message": "Rebase completed successfully.",
            }
        if self.repo.index.conflicts:
            return {
                "success": False,
                "message": f"Rebase paused due to new conflicts: {self.repo.index.conflicts}",
            }
        return {
            "success": True,
            "message": "Rebase continued, but there are more commits to process.",
        }

    @mcp.tool()
    def git_abort_rebase(self) -> MCPToolOutput:
        """
        Aborts an in-progress Git rebase operation.

        Returns:
            A dictionary containing the success status and a message.
        """
        try:
            self.repo.git.rebase("--abort")
        except GitCommandError as e:
            return {
                "success": False,
                "message": f"Failed to abort rebase: {e.stderr}",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"An unexpected error occurred: {e}",
            }
        return {
            "success": True,
            "message": "Rebase aborted successfully.",
        }

    @mcp.tool()
    def git_finish_rebase(self) -> MCPToolOutput:
        """
        Completes a Git rebase operation, ensuring all steps are finished.

        Returns:
            A dictionary containing the success status and a message.
        """
        if self._rebase_dir_exists():
            try:
                self.repo.git.rebase("--continue")
            except GitCommandError as e:
                return {
                    "success": False,
                    "message": f"Failed to finish rebase: {e.stderr}",
                }
            except Exception as e:
                return {
                    "success": False,
                    "message": f"An unexpected error occurred: {e}",
                }

            if self.repo.index.conflicts:
                return {
                    "success": False,
                    "message": f"Rebase paused due to new conflicts: {self.repo.index.conflicts}",
                }

        return {
            "success": True,
            "message": "Rebase completed successfully.",
        }


def main(path: str):
    logger.info("Starting MCP server...")
    manager = GitRebaseMCPToolManager(repo_path=path)  # noqa: F841
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main(sys.argv[1])
