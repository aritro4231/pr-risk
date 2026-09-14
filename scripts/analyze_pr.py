import json
import os
import re
import subprocess
import urllib.request

from pr_risk.git_history import (
    get_file_history,
    get_line_history,
    get_repo_churn_distribution,
)
from pr_risk.models import FileStats
from pr_risk.scoring import score_pr


HUNK_PATTERN = re.compile(
    r"@@ -(\d+)(?:,(\d+))? "
    r"\+(\d+)(?:,(\d+))? @@"
)


def run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=True,
    )

    return result.stdout.strip()


def get_changed_files(
    base_sha: str,
    head_sha: str,
) -> list[dict]:

    output = run_git(
        [
            "diff",
            "--numstat",
            base_sha,
            head_sha,
        ]
    )

    files = []

    if not output:
        return files

    for line in output.splitlines():
        parts = line.split("\t", 2)

        if len(parts) != 3:
            continue

        additions_raw, deletions_raw, path = parts

        # Binary files show "-" instead of numbers.
        if additions_raw == "-" or deletions_raw == "-":
            continue

        files.append(
            {
                "path": path,
                "additions": int(additions_raw),
                "deletions": int(deletions_raw),
            }
        )

    return files


def get_changed_regions(
    file_path: str,
    base_sha: str,
    head_sha: str,
) -> list[dict]:

    output = run_git(
        [
            "diff",
            "--unified=0",
            base_sha,
            head_sha,
            "--",
            file_path,
        ]
    )

    regions = []

    for line in output.splitlines():
        match = HUNK_PATTERN.search(line)

        if not match:
            continue

        old_start = int(match.group(1))
        old_count = int(match.group(2) or 1)

        new_start = int(match.group(3))
        new_count = int(match.group(4) or 1)

        regions.append(
            {
                "old_start": old_start,
                "old_count": old_count,
                "new_start": new_start,
                "new_count": new_count,
            }
        )

    return regions


def analyze_region(
    file_path: str,
    region: dict,
    base_sha: str,
) -> dict:

    old_count = region["old_count"]

    # Purely added lines have no matching historical
    # lines in the base revision.
    if old_count == 0:
        return {
            **region,
            "historical_commit_count": 0,
            "historical_bugfix_count": 0,
            "bugfix_ratio": 0.0,
        }

    start_line = region["old_start"]
    end_line = start_line + old_count - 1

    history = get_line_history(
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        revision=base_sha,
    )

    return {
        **region,
        "historical_commit_count":
            history["historical_commit_count"],
        "historical_bugfix_count":
            history["historical_bugfix_count"],
        "bugfix_ratio":
            history["bugfix_ratio"],
    }


def build_analysis(
    base_sha: str,
    head_sha: str,
) -> dict:

    changed_files = get_changed_files(
        base_sha,
        head_sha,
    )

    file_stats = []
    detailed_files = []

    for changed_file in changed_files:

        path = changed_file["path"]

        history = get_file_history(
            file_path=path,
            revision=base_sha,
        )

        stats = FileStats(
            path=path,
            additions=changed_file["additions"],
            deletions=changed_file["deletions"],
            historical_commit_count=history[
                "historical_commit_count"
            ],
            historical_bugfix_count=history[
                "historical_bugfix_count"
            ],
        )

        file_stats.append(stats)

        regions = get_changed_regions(
            file_path=path,
            base_sha=base_sha,
            head_sha=head_sha,
        )

        region_results = []

        for region in regions:
            try:
                result = analyze_region(
                    file_path=path,
                    region=region,
                    base_sha=base_sha,
                )

                region_results.append(result)

            except subprocess.CalledProcessError:
                region_results.append(
                    {
                        **region,
                        "historical_commit_count": 0,
                        "historical_bugfix_count": 0,
                        "bugfix_ratio": 0.0,
                    }
                )

        detailed_files.append(
            {
                "path": path,
                "additions": changed_file["additions"],
                "deletions": changed_file["deletions"],
                "historical_commit_count": history[
                    "historical_commit_count"
                ],
                "historical_bugfix_count": history[
                    "historical_bugfix_count"
                ],
                "regions": region_results,
            }
        )

    # Build repo-wide churn distribution using the base commit.
    churn_distribution = get_repo_churn_distribution(
        revision=base_sha,
    )

    score = score_pr(
        file_stats,
        churn_distribution,
    )

    score_lookup = {
        result.path: result
        for result in score.contributing_files
    }

    for file_data in detailed_files:
        result = score_lookup[file_data["path"]]

        file_data["risk_score"] = result.risk_score
        file_data["risk_level"] = result.risk_level
        file_data["churn_percentile"] = (
            result.churn_percentile
        )
        file_data["bugfix_ratio"] = result.bugfix_ratio

    return {
        "risk_score": score.risk_score,
        "risk_level": score.risk_level,
        "files": detailed_files,
    }


def post_to_api(
    api_url: str,
    payload: dict,
) -> None:

    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        api_url,
        data=data,
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(request) as response:
        body = response.read().decode("utf-8")

        print()
        print("AWS response:")
        print(body)

def write_github_summary(payload: dict) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")

    if not summary_path:
        return

    lines = []

    lines.append("# PR Risk Signal")
    lines.append("")
    lines.append(
        f"**Overall risk:** "
        f"{payload['risk_level'].upper()} — "
        f"{payload['risk_score']}"
    )
    lines.append("")

    lines.append(
        "| File | Risk | Level | Lines changed | "
        "Churn percentile | Bugfix ratio |"
    )
    lines.append(
        "|---|---:|---|---:|---:|---:|"
    )

    for file_data in payload.get("files", []):
        lines_changed = (
            file_data["additions"]
            + file_data["deletions"]
        )

        lines.append(
            f"| `{file_data['path']}` "
            f"| {file_data['risk_score']} "
            f"| {file_data['risk_level']} "
            f"| {lines_changed} "
            f"| {file_data['churn_percentile']} "
            f"| {file_data['bugfix_ratio']} |"
        )

    lines.append("")
    lines.append("## Review focus")
    lines.append("")

    review_regions = []

    for file_data in payload.get("files", []):
        for region in file_data.get("regions", []):
            old_start = region["old_start"]
            old_count = region["old_count"]
            new_start = region["new_start"]
            new_count = region["new_count"]

            if old_count > 0:
                start_line = old_start
                end_line = old_start + old_count - 1
                line_label = f"old lines {start_line}-{end_line}"
            elif new_count > 0:
                start_line = new_start
                end_line = new_start + new_count - 1
                line_label = f"new lines {start_line}-{end_line}"
            else:
                continue

            review_regions.append(
                {
                    "path": file_data["path"],
                    "line_label": line_label,
                    "historical_commit_count": region[
                        "historical_commit_count"
                    ],
                    "historical_bugfix_count": region[
                        "historical_bugfix_count"
                    ],
                    "bugfix_ratio": region["bugfix_ratio"],
                    "file_risk_score": file_data["risk_score"],
                }
            )

    review_regions.sort(
        key=lambda region: (
            region["historical_bugfix_count"],
            region["historical_commit_count"],
            region["file_risk_score"],
        ),
        reverse=True,
    )

    if review_regions:
        for region in review_regions:
            lines.append(
                f"- `{region['path']}` — {region['line_label']}  \n"
                f"  history: "
                f"{region['historical_commit_count']} commits, "
                f"{region['historical_bugfix_count']} bugfix commits, "
                f"bugfix ratio {region['bugfix_ratio']:.2f}"
            )
    else:
        lines.append(
            "No changed regions were available for review focus."
        )

    with open(
        summary_path,
        "a",
        encoding="utf-8",
    ) as summary_file:
        summary_file.write("\n".join(lines))
        summary_file.write("\n")
        
def main():

    base_sha = os.environ.get("PR_BASE_SHA")
    head_sha = os.environ.get("PR_HEAD_SHA")

    if not base_sha or not head_sha:
        raise RuntimeError(
            "PR_BASE_SHA and PR_HEAD_SHA must be set."
        )

    analysis = build_analysis(
        base_sha=base_sha,
        head_sha=head_sha,
    )

    payload = {
        "repository": os.environ.get(
            "GITHUB_REPOSITORY",
            "local",
        ),
        "pull_request_number": int(
            os.environ.get(
                "PR_NUMBER",
                "0",
            )
        ),
        **analysis,
    }

    print(
        json.dumps(
            payload,
            indent=2,
        )
    )

    write_github_summary(payload)

    api_url = os.environ.get(
        "PR_RISK_API_URL"
    )

    if api_url:
        post_to_api(
            api_url=api_url,
            payload=payload,
        )
    else:
        print()
        print(
            "PR_RISK_API_URL not set. "
            "Skipping AWS POST."
        )


if __name__ == "__main__":
    main()