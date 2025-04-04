import asyncio
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google.genai.errors import APIError
from google import genai
from loguru import logger

from .model import RebasePlan, RebaseCommit

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


def validate_llm_response(response_text: str) -> RebasePlan:
    """
    Convert the LLM response text.

    The response text is expected to be a JSON array of RebaseCommit objects
    wrapped with some extra info.

    Args:
        response_text (str): The LLM response text.

    Returns:
        RebasePlan: The parsed RebasePlan object.
    """
    json_start = response_text.find("[]")
    json_end = response_text.rfind("]") + 1
    if json_start == -1 or json_end <= json_start:
        raise ValueError("Cannot validate response")
    json_text = response_text[json_start:json_end]
    logger.debug(json_text)
    return RebasePlan.model_validate_json(json_text, strict=False)


async def call_llm(
    client: genai.Client, prompt: str, attempt: int = 0
) -> RebasePlan:
    """Call the LLM to generate rebase commands."""
    try:
        response = await client.aio.models.generate_content(
            model=os.environ["model"],
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": list[RebaseCommit],
            },
        )
        if parsed := response.parsed:
            logger.debug("Parsed response")
            logger.debug(parsed)
            return RebasePlan(plan=parsed)  # type: ignore
        elif text := response.text:
            logger.debug("Parsing failed, using raw text")
            return validate_llm_response(text)

        raise ValueError("Cannot validate response")
    except APIError as e:
        if attempt > 3:
            raise APIError(e.code, e.details, e.response) from e
        sleep_time = attempt**2
        logger.info(
            f"Error {e.code}: {e.status} - {e.message}. Retrying in {sleep_time} seconds"
        )
        time.sleep(sleep_time)
        return await call_llm(client, prompt, attempt + 1)


async def call_llm_with_spinner(
    client: genai.Client, prompt: str
) -> RebasePlan:
    """Run the LLM call with a spinner animation."""
    llm_call = asyncio.create_task(call_llm(client, prompt))
    while not llm_call.done():
        for frame in ["|", "/", "-", "\\"]:
            print(f"\r{frame}", end="", flush=True)
            await asyncio.sleep(0.1)
    print("\r ", end="\n", flush=True)
    return llm_call.result()


def call_llm_with_animation(client: genai.Client, prompt: str) -> RebasePlan:
    """Run the async function in a new event loop."""
    return asyncio.run(call_llm_with_spinner(client, prompt))


def ask_llm(
    commits: list[dict[str, str | list[list[str]]]],
    instruction_file: Path,
    skip_ids: list[str],
) -> RebasePlan:
    """Ask the LLM to generate rebase commands."""
    instructions = instruction_file.read_text(encoding="utf-8").replace(
        "\n", " "
    )
    logger.debug("Prompt instructions read from file")

    prompt = build_prompt(commits, instructions, skip_ids)
    logger.debug(f"Prompt: {prompt}")

    client = genai.Client(api_key=os.environ["gemini_key"])
    tokens = client.models.count_tokens(
        model=os.environ["model"], contents=prompt
    )

    logger.debug(f"Tokens: {tokens}")
    response: RebasePlan = call_llm_with_animation(client, prompt)

    logger.info("Response:\n")
    for action in response.plan:
        logger.debug(action)
    return response
