import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai.types import GenerateContentResponse
from loguru import logger

from .model import RebaseCommit

load_dotenv()


def join_diff(diff: list[str], remove_files: bool = False) -> str:
    """Join a git diff into a single string."""
    if not remove_files:
        return "\n".join(diff)

    cleaned_diff = []
    skip_lines = False

    for line in diff:
        if line.startswith("File added: "):
            skip_lines = True
            cleaned_diff.append(line)
            continue
        if skip_lines and (line.startswith("+") or line.startswith("@")):
            continue
        skip_lines = False
        cleaned_diff.append(line)

    return "\n".join(cleaned_diff)


def build_commit_prompt(
    commit: dict[str, str | list[list[str]]], skip_ids: list[str]
) -> str:
    """Build a commit string for the LLM prompt."""
    prompt = [
        f"Commit Hash: {commit['id']}",
        f"Commit Message: {commit['message']}",
        f"Diff: ({len(commit['diff'])} files changed)",
    ]
    prompt.extend(
        join_diff(diff, remove_files=(commit["id"] in skip_ids))
        for diff in commit["diff"]
        if type(diff) is list
    )
    prompt.append("-------------------------")
    return "\n".join(prompt)


def build_prompt(
    commits: list[dict[str, str | list[list[str]]]],
    instructions: str,
    skip_ids: list[str],
) -> str:
    """Build the prompt for the LLM."""
    prompt = [instructions]
    prompt.extend(
        build_commit_prompt(commit, skip_ids=skip_ids) for commit in commits
    )
    return "\n\n".join(prompt)


def call_llm(prompt: str) -> list[RebaseCommit]:
    """Call the LLM to generate rebase commands."""
    logger.debug(f"Prompt: {prompt}")
    client = genai.Client(api_key=os.environ["gemini_key"])
    tokens = client.models.count_tokens(
        model=os.environ["model"], contents=prompt
    )
    logger.debug(f"Tokens: {tokens}")
    response: GenerateContentResponse = client.models.generate_content(
        model=os.environ["model"],
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": list[RebaseCommit],
        },
    )
    logger.info("Response:\n")
    output: list[RebaseCommit] = response.parsed  # type: ignore
    for action in output:
        logger.info(action)
    return output


def ask_llm(
    commits: list[dict[str, str | list[list[str]]]],
    instruction_file: Path,
    skip_ids: list[str],
) -> list[RebaseCommit]:
    """Ask the LLM to generate rebase commands."""
    instructions = instruction_file.read_text(encoding="utf-8").replace(
        "\n", " "
    )
    logger.debug("Prompt instructions read from file")

    prompt = build_prompt(commits, instructions, skip_ids)

    prompt_file = Path(__file__).parent / "prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8", newline="\n")
    logger.debug("Prompt written to prompt.txt")

    return call_llm(prompt)
