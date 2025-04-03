from pathlib import Path


from loguru import logger

from . import mcp_client
from .model import RebasePlan


def write_plan(plan: RebasePlan) -> Path:
    """Write a rebase plan to a file."""
    plan_file = Path(__file__).parent / "plan_file.txt"
    commands = []
    for command in plan.plan:
        line = f"{command.action} {command.sha}"
        if command.action == "reword" and command.message:
            line += f" # {command.message}"
            commands.append(line)
    plan_file.write_text("\n".join(commands), encoding="utf-8")
    logger.info(f"{len(plan.plan)} commands written to plan file")
    return plan_file


def rebase(
    commands: RebasePlan,
    repo_url: str,
    base_ref: str,
    query_file: Path,
) -> None:
    """Rebase the repository based on the provided commands."""
    plan_file = write_plan(commands)
    mcp_client.main(repo_url, base_ref, plan_file, query_file)
