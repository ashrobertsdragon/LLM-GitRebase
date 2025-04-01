import subprocess
import sys
from pathlib import Path

from git import Repo, GitCommandError

from .model import MCPToolOutput, MergeStrategy
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="GitRebase-MCP")


class GitRebaseMCPToolManager:
    """MCP Tools for Git Rebasing"""

    def __init__(self, repo_path: str) -> None:
        self.repo = Repo(repo_path)
        self.repo_path = Path(repo_path)

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
        self, commit_hash: str, merge_strategy: list[MergeStrategy]
    ) -> MCPToolOutput:
        """
        Edits the contents of a commit.

        Args:
            commit_hash: The hash of the commit to edit.
            updated_content: A dictionary of file paths and their updated content.

        Returns:
            A dictionary containing the success status and a message.
        """

        try:
            self.repo.rev_parse(commit_hash)
        except GitCommandError:
            return {
                "success": False,
                "message": f"Error: Commit '{commit_hash}' not found.",
            }

        try:
            self.repo.git.checkout(commit_hash)

            for strategy in merge_strategy:
                file_path = self.repo_path / strategy.file_path
                file_path.write_text(strategy.content)
                self.repo.git.add(strategy.file_path)

            self.repo.git.commit("--amend", "--no-edit")
            self.repo.git.checkout("-")
            return {"success": True, "message": "Commit edited successfully."}

        except GitCommandError as e:
            return {"success": False, "message": f"Edit failed: {e.stderr}"}
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
            rebase_apply_dir = self.repo_path / ".git" / "rebase-apply"
            rebase_merge_dir = self.repo_path / ".git" / "rebase-merge"

            if not (rebase_apply_dir.exists() or rebase_merge_dir.exists()):
                return {
                    "success": False,
                    "message": "Error: No rebase in progress.",
                }

            try:
                self.repo.git.rebase("--continue")
                return {
                    "success": True,
                    "message": "Rebase continued successfully.",
                }
            except GitCommandError as e:
                if "conflicts" in e.stderr:
                    return {
                        "success": False,
                        "message": f"Rebase paused due to conflicts: {e.stderr}",
                    }
                return {
                    "success": False,
                    "message": f"Rebase paused due to: {e.stderr}",
                }

        except Exception as e:
            return {
                "success": False,
                "message": f"An unexpected error occurred: {e}",
            }


if __name__ == "__main__":
    manager = GitRebaseMCPToolManager(repo_path=sys.argv[1])
    mcp.run(transport="stdio")
