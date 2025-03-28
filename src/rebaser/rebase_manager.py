import tempfile

from git import Repo, GitCommandError
from loguru import logger


class GitRebaseManager:
    def __init__(self, repo: Repo):
        self.repo = repo
        self.git = self.repo.git

    def start_interactive_rebase(self, base_ref: str) -> None:
        """Start an interactive rebase session."""
        try:
            self.git.rebase("-I", base_ref)
        except GitCommandError as e:
            logger.error(f"Interactive rebase failed: {e}")
            raise

    def squash_commit(self, commit_sha: str) -> None:
        """Squash the specified commit into the previous one."""
        self._edit_rebase_plan(["squash", commit_sha])

    def drop_commit(self, commit_sha: str) -> None:
        """Drop the specified commit from history."""
        self._edit_rebase_plan(["drop", commit_sha])

    def reword_commit(self, commit_sha: str, new_message: str) -> None:
        """Change the commit message of a specific commit."""
        try:
            with tempfile.NamedTemporaryFile(mode="w+") as msg_file:
                msg_file.write(new_message)
                msg_file.flush()

                self.git.commit("—amend", "-F", msg_file.name, "—no-edit")
        except GitCommandError as e:
            logger.error(f"Failed to reword commit {commit_sha[:7]}: {e}")
            raise

    def edit_commit(self, commit_sha: str) -> None:
        """Stop at the specified commit for editing."""
        self._edit_rebase_plan(["edit", commit_sha])

    def continue_rebase(self) -> None:
        """Continue the rebase after resolving conflicts."""
        self.git.rebase("—continue")

    def abort_rebase(self) -> None:
        """Abort the current rebase operation."""
        self.git.rebase("—abort")

    def _edit_rebase_plan(self, actions: list[str]) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w+", encoding="utf-8"
        ) as plan_file:
            plan = self.git.rebase("-i", "--show-current-patch").splitlines()
            new_plan = []

            for line in plan:
                if not line.strip():
                    continue
                parts = line.split()
                if (
                    len(parts) >= 2
                    and parts[0] == "pick"
                    and parts[1] in actions[1:]
                ):
                    new_plan.append(
                        f"{actions[0]} {parts[1]} {"".join(parts[2:])}"
                    )
                else:
                    plan.append(line)

                plan_file.write("\n".join(new_plan))
                plan_file.flush()
                self.git.rebase(
                    "-i",
                    "--autosquash",
                    "--autostash",
                    "--onto",
                    "HEAD",
                    "--keep-empty",
                    plan_file.name,
                )
