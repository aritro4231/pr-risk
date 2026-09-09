import re
import subprocess
from pathlib import Path

from .config import BUGFIX_KEYWORDS, HISTORY_WINDOW


BUGFIX_PATTERN = re.compile(
    r"\b(" + "|".join(BUGFIX_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def run_git_command(
    args: list[str],
    repo_path: str | Path = ".",
) -> str:
    """
    Run a git command inside repo_path and return stdout.

    Example:
        run_git_command(["log", "--oneline"])
    """

    repo_path = Path(repo_path)

    result = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )

    return result.stdout.strip()


def get_file_commit_messages(
    file_path: str,
    repo_path: str | Path = ".",
    since: str = HISTORY_WINDOW,
) -> list[str]:
    """
    Return commit messages for commits that touched a file
    during the configured history window.

    --follow helps preserve history when a file has been renamed.
    """

    output = run_git_command(
        [
            "log",
            f"--since={since}",
            "--follow",
            "--format=%s",
            "--",
            file_path,
        ],
        repo_path=repo_path,
    )

    if not output:
        return []

    return [
        line.strip()
        for line in output.splitlines()
        if line.strip()
    ]


def is_bugfix_commit(message: str) -> bool:
    """
    Return True if the commit message contains one
    of our bug-fix keywords.
    """

    return bool(BUGFIX_PATTERN.search(message))


def get_file_history(
    file_path: str,
    repo_path: str | Path = ".",
    since: str = HISTORY_WINDOW,
) -> dict:
    """
    Return historical commit statistics for a single file.
    """

    messages = get_file_commit_messages(
        file_path=file_path,
        repo_path=repo_path,
        since=since,
    )

    bugfix_messages = [
        message
        for message in messages
        if is_bugfix_commit(message)
    ]

    return {
        "path": file_path,
        "historical_commit_count": len(messages),
        "historical_bugfix_count": len(bugfix_messages),
    }