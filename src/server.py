# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "gitpython",
#     "pydantic",
#     "mcp[cli]"
# ]
# ///


import sys
from pathlib import Path
from typing import Literal, TypedDict

import git
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

mcp = FastMCP(name="GitRebase-MCP")


class GitStatus(BaseModel):
    repo_path: str


class GitDiffUnstaged(BaseModel):
    repo_path: str


class GitDiffStaged(BaseModel):
    repo_path: str


class GitDiff(BaseModel):
    repo_path: str
    target: str


class GitCommit(BaseModel):
    repo_path: str
    message: str


class GitAdd(BaseModel):
    repo_path: str
    files: list[str]


class GitReset(BaseModel):
    repo_path: str


class GitLog(BaseModel):
    repo_path: str
    max_count: int = 10


class GitCreateBranch(BaseModel):
    repo_path: str
    branch_name: str
    base_branch: str | None = None


class GitCheckout(BaseModel):
    repo_path: str
    branch_name: str


class GitShow(BaseModel):
    repo_path: str
    revision: str


class GitInit(BaseModel):
    repo_path: str


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
        self.repo_path = Path(repo_path)
        try:
            self.repo = git.Repo(repo_path)
        except (git.InvalidGitRepositoryError, git.NoSuchPathError) as e:
            raise ValueError(f"{repo_path} is not a valid repository") from e

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

    @mcp.tool(
        name="git_start_rebase", description="Starts an interactive Git rebase"
    )
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
        rebase_command = ["rebase", "-i", "--autosquash", base_commit]
        env = {"GIT_SEQUENCE_EDITOR": f"cat {rebase_plan.name} >"}

        try:
            self.repo.git.execute(
                rebase_command,
                with_extended_output=False,
                with_exceptions=True,
                env=env,
            )

            if self.repo.index.conflicts:
                return {
                    "success": True,
                    "message": f"Rebase started with conflicts: {self.repo.index.conflicts}",
                }

            return {"success": True, "message": "Rebase started successfully."}

        except git.GitCommandError as e:
            return {"success": False, "message": f"Rebase failed: {e.stderr}"}
        except Exception as e:
            return {
                "success": False,
                "message": f"An unexpected error occurred: {e}",
            }

    def _get_diff(self, arg: str | None = None) -> MCPToolOutput:
        try:
            return {
                "success": True,
                "message": self.repo.git.diff(arg)
                if arg
                else self.repo.git.diff(),
            }
        except git.GitCommandError as e:
            return {
                "success": False,
                "message": f"Failed to get diff: {e.stderr}",
            }

    @mcp.tool(name="git_edit_commit", description="Edits a Git commit")
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
        except git.GitCommandError:
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

        except git.GitCommandError as e:
            return {"success": False, "message": f"Edit failed: {e.stderr}"}
        except Exception as e:
            return {
                "success": False,
                "message": f"An unexpected error occurred: {e}",
            }

    @mcp.tool(
        name="git_resolve_conflicts", description="Resolves Git conflicts"
    )
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

        except git.GitCommandError as e:
            return {
                "success": False,
                "message": f"Conflict resolution failed: {e.stderr}",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"An unexpected error occurred: {e}",
            }

    @mcp.tool(
        name="git_resume_rebase", description="Continues a paused Git rebase"
    )
    def git_resume_rebase(self) -> MCPToolOutput:
        """
        Continues a paused Git rebase operation.

        Returns:
            A dictionary containing the success status and a message.
        """
        try:
            self.repo.git.rebase("--continue")
        except git.GitCommandError as e:
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

    @mcp.tool(
        name="git_abort_rebase", description="Aborts an in-progress Git rebase"
    )
    def git_abort_rebase(self) -> MCPToolOutput:
        """
        Aborts an in-progress Git rebase operation.

        Returns:
            A dictionary containing the success status and a message.
        """
        try:
            self.repo.git.rebase("--abort")
        except git.GitCommandError as e:
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

    @mcp.tool(name="git_finish_rebase", description="Completes a Git rebase")
    def git_finish_rebase(self) -> MCPToolOutput:
        """
        Completes a Git rebase operation, ensuring all steps are finished.

        Returns:
            A dictionary containing the success status and a message.
        """
        if self._rebase_dir_exists():
            try:
                self.repo.git.rebase("--continue")
            except git.GitCommandError as e:
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

    @mcp.tool(
        name="git_status",
        description="Returns the status of the Git repository",
    )
    def git_status(self) -> MCPToolOutput:
        try:
            status = self.repo.git.status()
        except git.GitCommandError as e:
            return {
                "success": False,
                "message": f"Failed to get status: {e.stderr}",
            }
        if self._rebase_dir_exists():
            status += "\nRebase in progress"
        return {"success": True, "message": status}

    @mcp.tool(
        name="git_diff_unstaged",
        description="Returns the unstaged changes in the Git repository",
    )
    def git_diff_unstaged(self) -> MCPToolOutput:
        """
        Returns the unstaged changes in the Git repository.

        Returns:
            A dictionary containing the success status and a message.
        """
        return self._get_diff()

    @mcp.tool(
        name="git_diff_staged",
        description="Returns the staged changes in the Git repository",
    )
    def git_diff_staged(self) -> MCPToolOutput:
        """
        Returns the staged changes in the Git repository.

        Returns:
            A dictionary containing the success status and a message.
        """
        return self._get_diff("--cached")

    @mcp.tool(
        name="git_diff",
        description="Returns the changes between two commits in the Git repository",
    )
    def git_diff(self, target: str) -> MCPToolOutput:
        return self._get_diff(target)

    @mcp.tool(
        name="git_commit",
        description="Commits the staged changes in the Git repository",
    )
    def git_commit(self, message: str) -> MCPToolOutput:
        """
        Commits the staged changes in the Git repository.

        Args:
            message (str): The commit message.

        Returns:
            A dictionary containing the success status and a message."""
        try:
            commit = self.repo.index.commit(message)
        except git.GitCommandError as e:
            return {
                "success": False,
                "message": f"Failed to commit changes: {e.stderr}",
            }
        return {
            "success": True,
            "message": f"Changes committed successfully with hash {commit.hexsha}",
        }

    @mcp.tool(
        name="git_add",
        description="Stages files for commit in the Git repository",
    )
    def git_add(self, files: list[str]) -> MCPToolOutput:
        """
        Stages files for commit in the Git repository.

        Args:
            files (list[str]): A list of file paths to stage for commit.

        Returns:
            A dictionary containing the success status and a message.
        """
        if not files:
            return {"success": False, "message": "No files specified to add."}
        try:
            self.repo.git.add(files)
        except git.GitCommandError as e:
            return {
                "success": False,
                "message": f"Failed to stage files: {e.stderr}",
            }
        return {
            "success": True,
            "message": "Files staged successfully",
        }

    @mcp.tool(
        name="git_reset",
        description="Resets the staged changes in the Git repository",
    )
    def git_reset(self) -> MCPToolOutput:
        """
        Resets the staged changes in the Git repository.

        Returns:
            A dictionary containing the success status and a message.
        """
        try:
            self.repo.index.reset()
        except git.GitCommandError as e:
            return {
                "success": False,
                "message": f"Failed to reset staged changes: {e.stderr}",
            }
        return {
            "success": True,
            "message": "All staged changes reset",
        }

    @mcp.tool(
        name="git_log",
        description="Returns the commit log for the Git repository",
    )
    def git_log(self, max_count: int = 10) -> MCPToolOutput:
        """
        Returns the commit log for the Git repository.

        Args:
            max_count (int, optional): The maximum number of commits to return. Defaults to 10.

        Returns:
            dict: A dictionary containing the success status and message
        """
        try:
            commits = list(self.repo.iter_commits(max_count=max_count))
        except git.GitCommandError as e:
            return {
                "success": False,
                "message": f"Failed to get commit log: {e.stderr}",
            }
        if not commits:
            return {"success": False, "message": "No commits found for "}
        log = []
        log.extend(
            f"Commit: {commit.hexsha}\nAuthor: {commit.author}\nDate: {commit.authored_datetime}\nMessage: {commit.message}\n"
            for commit in commits
        )
        return {"success": True, "message": "\n".join(log)}

    @mcp.tool(
        name="git_create_branch",
        description="Creates a new branch in the Git repository",
    )
    def git_create_branch(
        self, branch_name: str, base_branch: str | None = None
    ) -> MCPToolOutput:
        """
        Creates a new branch in the Git repository.

        Args:
            branch_name (str): The name of the branch to create.
            base_branch (str, optional): The name of the branch to base the new branch on.

        Returns:
            dict: A dictionary containing the success status and a message.
        """
        if branch_name in self.repo.heads:
            return {
                "success": False,
                "message": f"Branch '{branch_name}' already exists",
            }
        try:
            base = (
                self.repo.refs[base_branch]
                if base_branch
                else self.repo.active_branch
            )
            self.repo.create_head(branch_name, base)
        except git.GitCommandError as e:
            return {
                "success": False,
                "message": f"Failed to create branch: {e.stderr}",
            }
        return {
            "success": True,
            "message": f"Created branch '{branch_name}' from '{base.name}'",
        }

    @mcp.tool(
        name="git_checkout",
        description="Switches to a branch in the Git repository",
    )
    def git_checkout(self, branch_name: str) -> MCPToolOutput:
        """
        Switches to a branch in the Git repository.

        Args:
            branch_name (str): The name of the branch to switch to.

        Returns:
            dict: A dictionary containing the success status and a message.
        """
        try:
            self.repo.git.checkout(branch_name)
        except git.GitCommandError as e:
            return {
                "success": False,
                "message": f"Failed to checkout branch: {e.stderr}",
            }
        return {
            "success": True,
            "message": f"Switched to branch '{branch_name}'",
        }

    @mcp.tool(name="git_init", description="Initializes a new Git repository")
    def git_init(self, repo_path: str) -> MCPToolOutput:
        """Initializes a new Git repository."""
        try:
            self.repo = git.Repo.init(path=repo_path, mkdir=True)
            return {
                "success": True,
                "message": f"Initialized empty Git repository in {self.repo.git_dir}",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error initializing repository: {str(e)}",
            }

    @mcp.tool(
        name="git_show",
        description="Displays the contents of a commit in the Git repository",
    )
    def git_show(self, revision: str) -> MCPToolOutput:
        try:
            commit = self.repo.commit(revision)
            if commit.parents:
                parent = commit.parents[0]
                diff = parent.diff(commit, create_patch=True)
            else:
                diff = commit.diff(git.NULL_TREE, create_patch=True)
        except git.GitCommandError as e:
            return {
                "success": False,
                "message": f"Failed to show commit: {e.stderr}",
            }

        output = [
            f"Commit: {commit.hexsha}\n"
            f"Author: {commit.author}\n"
            f"Date: {commit.authored_datetime}\n"
            f"Message: {commit.message}\n"
        ]
        for d in diff:
            output.extend((
                f"\n--- {d.a_path}\n+++ {d.b_path}\n",
                d.diff.decode("utf-8"),  # type: ignore
            ))
        return {"success": True, "message": "".join(output)}


def main():
    manager = GitRebaseMCPToolManager(repo_path=sys.argv[1])  # noqa: F841
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
