import os
import subprocess
import sys
from pathlib import Path

from git import GitError, GitCommandError, Repo
from loguru import logger

from .model import RebaseCommit
from .rebase_manager import GitRebaseManager


def write_plan(plan: list[RebaseCommit]) -> Path:
    """Write a rebase plan to a file."""
    plan_file = Path(__file__).parent / "plan_file.txt"
    commands = []
    for command in plan:
        line = f"{command.action} {command.sha}"
        if command.action == "reword" and command.message:
            line += f" # {command.message}"
            commands.append(line)
    plan_file.write_text("\n".join(commands), encoding="utf-8")
    logger.info(f"{len(plan)} commands written to plan file")
    return plan_file


def execute_rebase_plan(
    repo: Repo, base_ref: str, plan: list[RebaseCommit]
) -> None:
    """Execute a rebase plan using Pydantic-validated commands."""
    manager = GitRebaseManager(repo)
    original_branch = manager.repo.active_branch.name
    temp_branch = f"rebase-{base_ref[:7]}"
    manager.git.checkout("-b", temp_branch, base_ref)

    try:
        plan_file = write_plan(plan)
        plan_file.open("r", encoding="utf-8")
        env = os.environ.copy()
        env["GIT_SEQUENCE_EDITOR"] = f"cat {plan_file.name} >"

        result = subprocess.run(
            ["git", "rebase", "-i", "--autosquash", base_ref],
            cwd=manager.repo.working_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        logger.info(result.stdout)

        if result.returncode != 0:
            logger.error("Rebase failed with output:")
            logger.error(result.stderr)
            manager.abort_rebase()
            raise GitCommandError(
                result.args, result.returncode, result.stderr
            )

        for command in plan:
            if command.action == "reword" and command.message:
                manager.reword_commit(command.sha, command.message)

    except GitError as e:
        logger.error(f"Rebase failed: {e}")
        manager.abort_rebase()
        raise
    finally:
        manager.git.checkout(original_branch)
        manager.git.branch("-D", temp_branch)
        plan_file.close()  # type: ignore


def rebase(commands: list[RebaseCommit], repo: Repo, base_ref: str) -> None:
    """Rebase the repository based on the provided commands."""
    try:
        execute_rebase_plan(repo, base_ref, commands)
    except Exception as e:
        logger.error(str(e))
        sys.exit(1)
