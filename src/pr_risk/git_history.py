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
    revision: str = "HEAD",
) -> list[str]:
    output = run_git_command(
        [
            "log",
            revision,
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
    return bool(BUGFIX_PATTERN.search(message))


def get_file_history(
    file_path: str,
    repo_path: str | Path = ".",
    since: str = HISTORY_WINDOW,
    revision: str = "HEAD",
) -> dict:
    messages = get_file_commit_messages(
        file_path=file_path,
        repo_path=repo_path,
        since=since,
        revision=revision,
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


def get_line_commit_messages(
    file_path: str,
    start_line: int,
    end_line: int,
    repo_path: str | Path = ".",
    since: str = HISTORY_WINDOW,
    revision: str = "HEAD",
) -> list[str]:
    if start_line <= 0 or end_line < start_line:
        return []

    output = run_git_command(
        [
            "log",
            f"--since={since}",
            "--format=%s",
            "--no-patch",
            "-L",
            f"{start_line},{end_line}:{file_path}",
            revision,
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


def get_line_history(
    file_path: str,
    start_line: int,
    end_line: int,
    repo_path: str | Path = ".",
    since: str = HISTORY_WINDOW,
    revision: str = "HEAD",
) -> dict:
    messages = get_line_commit_messages(
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        repo_path=repo_path,
        since=since,
        revision=revision,
    )

    bugfix_messages = [
        message
        for message in messages
        if is_bugfix_commit(message)
    ]

    commit_count = len(messages)
    bugfix_count = len(bugfix_messages)

    bugfix_ratio = (
        bugfix_count / commit_count
        if commit_count > 0
        else 0.0
    )

    return {
        "path": file_path,
        "start_line": start_line,
        "end_line": end_line,
        "historical_commit_count": commit_count,
        "historical_bugfix_count": bugfix_count,
        "bugfix_ratio": bugfix_ratio,
    }


def get_tracked_files(
    repo_path: str | Path = ".",
    revision: str = "HEAD",
) -> list[str]:
    output = run_git_command(
        [
            "ls-tree",
            "-r",
            "--name-only",
            revision,
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


def get_repo_churn_distribution(
    repo_path: str | Path = ".",
    since: str = HISTORY_WINDOW,
    revision: str = "HEAD",
) -> list[int]:
    files = get_tracked_files(
        repo_path=repo_path,
        revision=revision,
    )

    churn_counts = []

    for file_path in files:
        messages = get_file_commit_messages(
            file_path=file_path,
            repo_path=repo_path,
            since=since,
            revision=revision,
        )

        churn_counts.append(len(messages))

    return churn_counts