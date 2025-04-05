import argparse
import sys
import time
from pathlib import Path

from loguru import logger

from . import get_commits
from . import llm
from . import agent
from .model import RebasePlan


def set_logger(verbose: bool, silent: bool) -> None:
    """Set up the Loguru logger."""
    logger.remove()
    logger.add(
        sink=sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{message}</level>",
        level="INFO",
    )

    if verbose:
        logger.remove()
        logger.add(
            sink=sys.stdout,
            format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{message}</level>",
            level="DEBUG",
        )
        logger.add(
            sink="logs/rebaser.log",
            format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{message}</level>",
            level="DEBUG",
        )
    elif silent:
        logger.remove()
        logger.add(
            sink="logs/rebaser.log",
            format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{message}</level>",
            level="ERROR",
        )


def parse_local_path(local_path: str) -> Path:
    """Parse a local path to a directory."""
    path = Path(local_path)
    if not path.parent.is_dir():
        raise argparse.ArgumentTypeError(f"{path} is not a valid directory")
    full_path = path if path.is_absolute() else Path.cwd() / path
    full_path.mkdir(parents=True, exist_ok=True)
    return full_path


def create_parser() -> argparse.Namespace:
    """Create a parser for the command line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "repo_url",
        metavar="REPO_URL",
        type=str,
        help="URL of the repository to clone and rebase",
    )
    parser.add_argument(
        "local_path",
        metavar="LOCAL_PATH",
        type=parse_local_path,
        help="Local path to clone the repository to",
    )
    parser.add_argument(
        "start_sha",
        metavar="START_SHA",
        type=str,
        help="SHA of the first commit to rebase",
    )
    parser.add_argument(
        "-e",
        "--end-sha",
        metavar="END_SHA",
        type=str,
        default="HEAD",
        help="SHA of the last commit to rebase. Defaults to HEAD",
        dest="end_sha",
    )
    parser.add_argument(
        "-s",
        "--skip-diff",
        type=list,
        default=[],
        help="List of commit SHAs to skip adding the diff to LLM context",
        metavar="COMMIT_SHA",
        action="append",
        dest="skip",
        nargs="+",
    )
    parser.add_argument(
        "-i",
        "--instruction-file",
        default=Path(__file__).parent / "prompts" / "instruction.txt",
        type=Path,
        help="Path to text file containing LLM prompt base",
        dest="instruction_file",
    )
    parser.add_argument(
        "--query-file",
        default=Path(__file__).parent / "prompts" / "initial_query.txt",
        type=Path,
        help="Path to text file containing MCP initial prompt",
        dest="query_file",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    parser.add_argument(
        "-q", "--silent", action="store_true", help="Disable logging to stdout"
    )

    return parser.parse_args()


def write_plan(plan: RebasePlan) -> Path:
    """Write a rebase plan to a file."""
    plan_file = Path(__file__).parent / "plan_file.txt"
    commands: list[str] = []
    for command in plan.plan:
        line = f"{command.action} {command.sha}"
        if command.action == "REWORD" and command.message:
            line += f" # {command.message}"
        commands.append(line)
    plan_file.write_text("\n".join(commands))
    logger.info(f"{len(plan.plan)} commands written to plan file")
    return plan_file


def main() -> None:
    """
    Gemini-Rebaser

    This application parses command line arguments to determine the repository URL,
    local path, start and end commit SHAs. It retrieves the commit history and
    uses a language model to generate rebase commands based on the commit history
    and instructions. Finally, it performs the rebase operation on the repository.

    Raises:
        argparse.ArgumentTypeError: If the provided paths or lists are invalid.
    """

    args = create_parser()

    set_logger(args.verbose, args.silent)

    plan_file = Path(__file__).parent / "plan_file.txt"
    if not plan_file.exists():
        commit_history = get_commits.run(
            repo_url=args.repo_url,
            local_dir=args.local_path,
            start_sha=args.start_sha,
            end_sha=args.end_sha,
        )
        rebase_commands = llm.ask_llm(
            commits=commit_history,
            instruction_file=args.instruction_file,
            skip_ids=args.skip,
        )
        plan_file = write_plan(rebase_commands)

    agent.main(args.repo_url, args.start_sha, plan_file, args.query_file)


if __name__ == "__main__":
    start = time.time()
    try:
        main()
        logger.debug(f"Execution time: {time.time() - start:.2f} seconds")
    except Exception as e:
        logger.error(e)
        logger.debug(f"Execution time: {time.time() - start:.2f} seconds")
        exit(1)
