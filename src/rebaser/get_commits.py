import sys
from collections.abc import Iterator
from pathlib import Path

from loguru import logger
from git import Commit, Diff, Repo, GitError

type CommitInfo = dict[str, str | list[list[str]]]


def decode_bytes(str_or_bytes: bytes | str) -> str:
    """Decode bytestring to string."""
    if isinstance(str_or_bytes, bytes):
        str_or_bytes = str_or_bytes.decode(encoding="utf-8", errors="replace")
    return str_or_bytes  # type: ignore # mypy bug


def process_diff(diff: Diff) -> list[str]:
    """
    Process a git diff object to handle deleted files specially.
    For deleted or added files, return a simple message. For other diffs, return the unified diff.
    """
    message = []
    if diff.deleted_file:
        return [f"{diff.b_path} deleted"]
    elif not diff.diff:
        return message

    if diff.new_file:
        message.append(f"File added: {diff.b_path}")
    elif diff.copied_file:
        message.append(f"File copied from {diff.a_path} to {diff.b_path}")
    elif diff.renamed:
        message.append(f"File renamed:{diff.rename_from} -> {diff.rename_to}")
    else:
        message.append(f"File changed: {diff.b_path}")

    message.append("" if diff.b_path == "uv.lock" else decode_bytes(diff.diff))
    return message


def get_diffs(commit: Commit) -> list[list[str]]:
    """
    Get the diffs for a commit.
    If the commit has no parent, return an empty list.
    """
    if not commit.parents:
        return [["Initial commit - no diff available"]]
    parent = commit.parents[0]
    diffs = []
    for i, diff in enumerate(parent.diff(commit)):
        processed_diff = process_diff(diff)
        diffs.append(
            processed_diff
            or process_diff(parent.diff(commit, create_patch=True)[i])
        )
    return diffs


def get_commits(repo: Repo, start_sha: str, end_sha: str) -> Iterator[Commit]:
    """Get the commit history between the start and end commits."""
    if start_sha == end_sha:
        raise ValueError("Start and end commits cannot be the same")
    try:
        repo.commit(start_sha)
        return repo.iter_commits(f"{start_sha}..{end_sha}")
    except GitError as e:
        raise ValueError(f"Commit {start_sha} not found in repository") from e


def build_commit_data(commits: Iterator[Commit]) -> list[CommitInfo]:
    """Process the commit history and parse the commit data."""
    commit_history: list[CommitInfo] = []
    for commit in commits:
        diffs: list[list[str]] = get_diffs(commit)
        commit_info: CommitInfo = {
            "id": commit.hexsha,
            "message": decode_bytes(commit.message).split("\n")[0],
            "diff": diffs,
        }
        logger.info(f"{commit_info["id"][-6:]} - {commit_info["message"]}")
        logger.info(f"{len(diffs)} diffs in commit")
        for diff in diffs:
            logger.debug(diff)
        commit_history.append(commit_info)

    commit_history.reverse()

    return commit_history


def clone(repo_url: str, local_dir: Path) -> Repo:
    """Clone the repository."""
    try:
        repo = Repo.clone_from(repo_url, local_dir)
        logger.info(f"Repo cloned to {local_dir}")
        return repo
    except Exception as e:
        logger.exception(str(e))
        sys.exit(1)


def run(
    repo_url: str, local_dir: Path, start_sha: str, end_sha: str
) -> list[CommitInfo]:
    """Initialize the repository and get the commit history."""
    git_dir = local_dir / ".git"

    try:
        repo = (
            Repo(local_dir) if git_dir.exists() else clone(repo_url, local_dir)
        )
    except Exception as e:
        logger.exception(str(e))
        sys.exit(1)
    commits = get_commits(repo, start_sha, end_sha)
    return build_commit_data(commits)
