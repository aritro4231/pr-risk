"""Frozen-history, file-level validation using the unchanged production model."""

from __future__ import annotations

import argparse
import calendar
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pr_risk import config
from pr_risk.git_history import get_file_history, get_tracked_files, is_bugfix_commit
from pr_risk.models import FileStats
from pr_risk.scoring import score_file


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=repo, text=True, encoding="utf-8",
    )


def timestamp(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("All dates must include an explicit timezone.")
    return int(parsed.timestamp())


def check_windows(manifest: dict) -> None:
    start, cutoff, end = (
        timestamp(manifest[key])
        for key in ("history_start", "cutoff", "outcome_end")
    )
    if not start < cutoff < end:
        raise ValueError("Expected history_start < cutoff < outcome_end.")
    match = re.fullmatch(r"(\d+) months ago", config.HISTORY_WINDOW)
    if not match:
        raise ValueError("Review benchmark window handling: HISTORY_WINDOW changed.")
    date = datetime.fromtimestamp(cutoff, timezone.utc)
    months = date.year * 12 + date.month - 1 - int(match[1])
    year, month = divmod(months, 12)
    month += 1
    expected = date.replace(
        year=year, month=month,
        day=min(date.day, calendar.monthrange(year, month)[1]),
    )
    if start != int(expected.timestamp()):
        raise ValueError("history_start must match the production calendar-month window.")


def prepare_repo(spec: dict, cache: Path, offline: bool) -> Path:
    repo = cache / (spec["name"].replace("/", "-") + ".git")
    if not repo.exists():
        if offline:
            raise ValueError(f"Missing offline cache: {repo}")
        repo.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--bare", "--single-branch", "--branch",
             spec["ref"].removeprefix("refs/tags/"), spec["url"], str(repo)],
            check=True,
        )
    if git(repo, "rev-parse", "--is-shallow-repository").strip() != "false":
        raise ValueError(f"Full history required: {repo}")
    # Do not silently substitute a changed tag or a moving branch.
    resolved = git(repo, "rev-parse", spec["ref"] + "^{commit}").strip()
    if resolved != spec["anchor"]:
        raise ValueError(f"Anchor mismatch for {spec['name']}: {resolved}")
    return repo


def snapshot_before(repo: Path, anchor: str, boundary: int) -> str:
    # First-parent traversal fixes the selected release lineage. Date selection
    # alone is not sufficient; validate_snapshot checks ALL reachable ancestors.
    for line in git(repo, "log", "--first-parent", "--format=%H %ct", anchor).splitlines():
        sha, date = line.split()
        if int(date) < boundary:
            return sha
    raise ValueError("No snapshot exists before the boundary.")


def validate_snapshot(repo: Path, revision: str, boundary: int) -> dict:
    records = git(repo, "log", "--format=%H %ct", revision).splitlines()
    for line in records:
        sha, date = line.split()
        if int(date) >= boundary:
            raise ValueError(
                f"Leakage: ancestor {sha} of {revision} is at/after the boundary."
            )
    return {
        "reachable_commits": len(records),
        "max_committer_timestamp": max(int(line.split()[1]) for line in records),
    }


def score_snapshot(repo: Path, revision: str, since: str) -> list[dict]:
    # Preserve production Git --follow and --since behavior exactly. Cache the
    # resulting counts to construct the same repo-wide churn distribution as
    # get_repo_churn_distribution without running each file's Git log twice.
    paths = get_tracked_files(repo_path=repo, revision=revision)
    literal_paths = git(repo, "ls-tree", "-r", "--name-only", "-z", revision).split("\0")[:-1]
    if paths != literal_paths:
        raise ValueError("Paths cannot be represented by production get_tracked_files.")
    histories = [
        get_file_history(path, repo_path=repo, since=since, revision=revision)
        for path in paths
    ]
    distribution = [item["historical_commit_count"] for item in histories]
    return [
        asdict(score_file(FileStats(additions=0, deletions=0, **item), distribution))
        for item in histories
    ]


def future_labels(
    repo: Path, base: str, end: str, cutoff: int, end_time: int, paths: set[str],
) -> tuple[dict, dict]:
    counts = dict.fromkeys(paths, 0)
    labeled = []
    eligible = 0
    excluded_backdated = 0
    # Non-merge commits avoid labeling both a merge and its constituent changes.
    # Only subjects are classified, using the very same production keyword regex.
    lines = git(
        repo, "log", "--no-merges", "--format=%H%x00%ct%x00%s", f"{base}..{end}",
    ).splitlines()
    for line in lines:
        sha, date, subject = line.split("\0", 2)
        date = int(date)
        if date < cutoff:
            excluded_backdated += 1
            continue
        if date >= end_time:
            raise ValueError(f"Outcome commit outside its window: {sha}")
        eligible += 1
        if not is_bugfix_commit(subject):
            continue
        # Fixed cutoff paths are the observation units. With --no-renames a
        # rename touches both the old and new paths; subsequent new-path changes
        # do not count against the old path (documented censoring limitation).
        touched = set(git(
            repo, "diff-tree", "--root", "-r", "--no-commit-id",
            "--no-renames", "--name-only", "-z", sha,
        ).split("\0")) - {""}
        matched = sorted(touched & paths)
        for path in matched:
            counts[path] += 1
        labeled.append({"sha": sha, "subject": subject, "scored_paths": matched})
    return counts, {
        "eligible_nonmerge_commits": eligible,
        "excluded_pre_cutoff_nonmerge_commits": excluded_backdated,
        "bugfix_like_commits": len(labeled),
        "labeled_commits": labeled,
    }


def group_metrics(rows: list[dict]) -> dict:
    result = {}
    for level in ("low", "medium", "high"):
        group = [row for row in rows if row["risk_level"] == level]
        positive = sum(row["future_bugfix_commit_count"] > 0 for row in group)
        touches = sum(row["future_bugfix_commit_count"] for row in group)
        result[level] = {
            "files": len(group),
            "files_with_future_bugfix": positive,
            "future_bugfix_file_rate": positive / len(group) if group else None,
            "mean_future_bugfix_commits_per_file": touches / len(group) if group else None,
        }
    result["high_risk_precision"] = result["high"]["future_bugfix_file_rate"]
    return result


def aggregate(repositories: list[dict], rows: list[dict]) -> dict:
    macro = {}
    coverage = {}
    for level in ("low", "medium", "high"):
        rates = [
            repo["groups"][level]["future_bugfix_file_rate"]
            for repo in repositories
            if repo["groups"][level]["files"]
        ]
        macro[level] = sum(rates) / len(rates) if rates else None
        coverage[level] = len(rates)
    return {
        "repositories_tested": len(repositories),
        "total_historical_commits_analyzed": sum(
            repo["history_audit"]["reachable_commits"] for repo in repositories
        ),
        "total_history_window_commits": sum(repo["history_window_commits"] for repo in repositories),
        "files_scored": len(rows),
        "pooled": group_metrics(rows),
        "repository_mean_future_bugfix_file_rate": macro,
        "repositories_with_nonempty_group": coverage,
        "repository_mean_high_risk_precision": macro["high"],
        "historically_active_only": group_metrics(
            [row for row in rows if row["historical_commit_count"] > 0]
        ),
    }


def percentage(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2%}"


def markdown(report: dict) -> str:
    overall = report["summary"]
    macro = overall["repository_mean_future_bugfix_file_rate"]
    pooled = overall["pooled"]
    lines = [
        "# PR Risk Signal historical validation", "",
        f"- Repositories tested: **{overall['repositories_tested']}**",
        f"- Unique pre-cutoff commits inspected: **{overall['total_historical_commits_analyzed']:,}**",
        f"- Commits in the scoring history window: **{overall['total_history_window_commits']:,}**",
        f"- Files scored: **{overall['files_scored']:,}**",
        f"- Mean repository future bug-fix file rate: high **{percentage(macro['high'])}**, low **{percentage(macro['low'])}**",
        f"- Pooled future bug-fix file rate: high **{percentage(pooled['high']['future_bugfix_file_rate'])}**, low **{percentage(pooled['low']['future_bugfix_file_rate'])}**",
        f"- High-risk precision (pooled): **{percentage(pooled['high_risk_precision'])}**", "",
        "Each rate is the fraction of files with at least one future bug-fix-like commit.",
        "Precision is the same fraction among files classified high risk. Empty groups are N/A;",
        "repository means exclude them and JSON reports the number of contributing repositories.", "",
        "| Repository | Pre-cutoff commits | Window commits | Files | High: positive / total | High rate | Low: positive / total | Low rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for repo in report["repositories"]:
        high, low = repo["groups"]["high"], repo["groups"]["low"]
        lines.append(
            f"| {repo['name']} | {repo['history_audit']['reachable_commits']:,} | "
            f"{repo['history_window_commits']:,} | {repo['files_scored']} | "
            f"{high['files_with_future_bugfix']} / {high['files']} | "
            f"{percentage(high['future_bugfix_file_rate'])} | "
            f"{low['files_with_future_bugfix']} / {low['files']} | "
            f"{percentage(low['future_bugfix_file_rate'])} |"
        )
    lines.extend([
        "", f"History: [{report['windows']['history_start']}, {report['windows']['cutoff']}).",
        f"Outcomes: [{report['windows']['cutoff']}, {report['windows']['outcome_end']}).",
        f"Production thresholds: low <= {config.LOW_RISK_MAX}; "
        f"medium > {config.LOW_RISK_MAX} and <= {config.MEDIUM_RISK_MAX}; high > {config.MEDIUM_RISK_MAX}.",
        "", "These are message-based maintenance labels, not verified defects or bug-inducing PRs.",
        "All tracked cutoff paths are scored, including inactive files, tests, docs, and binaries.",
        "Future outcomes omit merge commits and do not follow paths forward after renames.",
        "The selected release lineages and single time split limit generalization.",
        "See README.md for the protocol and summary.json / files.csv for auditable results.", "",
    ])
    return "\n".join(lines)


def run(manifest: dict, cache: Path, offline: bool) -> tuple[list[dict], list[dict]]:
    check_windows(manifest)
    specs = manifest["repositories"]
    if not 3 <= len(specs) <= 5 or len({spec["name"] for spec in specs}) != len(specs):
        raise ValueError("Choose 3-5 distinct repositories.")
    rows, results = [], []
    cutoff = timestamp(manifest["cutoff"])
    end_time = timestamp(manifest["outcome_end"])
    for spec in specs:
        print(f"Evaluating {spec['name']}...", flush=True)
        repo = prepare_repo(spec, cache, offline)
        if int(git(repo, "show", "-s", "--format=%ct", spec["anchor"])) < end_time:
            raise ValueError("Anchor must extend beyond the outcome window.")
        base = snapshot_before(repo, spec["anchor"], cutoff)
        end = snapshot_before(repo, spec["anchor"], end_time)
        if base != spec["cutoff_revision"] or end != spec["outcome_revision"]:
            raise ValueError("Selected snapshots differ from the locked manifest.")
        git(repo, "merge-base", "--is-ancestor", base, end)
        history_audit = validate_snapshot(repo, base, cutoff)
        outcome_audit = validate_snapshot(repo, end, end_time)
        window_count = int(git(
            repo, "rev-list", "--count", f"--since={manifest['history_start']}", base,
        ))
        # Freeze every feature and the complete churn reference population before
        # looking at future subjects or file changes.
        scores = score_snapshot(repo, base, manifest["history_start"])
        counts, outcomes = future_labels(
            repo, base, end, cutoff, end_time, {row["path"] for row in scores},
        )
        for row in scores:
            row["repository"] = spec["name"]
            row["future_bugfix_commit_count"] = counts[row["path"]]
        rows.extend(scores)
        results.append({
            **spec, "history_audit": history_audit, "outcome_audit": outcome_audit,
            "history_window_commits": window_count, "files_scored": len(scores),
            "groups": group_metrics(scores), "outcomes": outcomes,
        })
    return results, rows


def main() -> None:
    # Production Git helpers use Python's default text encoding. Make UTF-8
    # explicit on Windows too, so non-ASCII Git paths round-trip correctly.
    if not sys.flags.utf8_mode:
        subprocess.run(
            [sys.executable, "-X", "utf8", "-B", str(Path(__file__).resolve()), *sys.argv[1:]],
            check=True,
        )
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "benchmarks/repositories.json")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "benchmarks/.cache")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "benchmarks/results")
    parser.add_argument("--offline", action="store_true", help="Require existing clones; do not use network.")
    args = parser.parse_args()
    # Git subprocesses, including production helpers, inherit stable locale and
    # date settings. Disable replace refs and accidental caller revision filters.
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_SHALLOW_FILE"):
        os.environ.pop(key, None)
    os.environ.update(
        TZ="UTC", LC_ALL="C.UTF-8", GIT_NO_REPLACE_OBJECTS="1",
        GIT_CONFIG_COUNT="2", GIT_CONFIG_KEY_0="log.showSignature", GIT_CONFIG_VALUE_0="false",
        GIT_CONFIG_KEY_1="core.quotepath", GIT_CONFIG_VALUE_1="false",
    )
    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    repositories, rows = run(manifest, args.cache_dir.resolve(), args.offline)
    hashed_files = [
        "src/pr_risk/config.py", "src/pr_risk/models.py",
        "src/pr_risk/scoring.py", "src/pr_risk/git_history.py", "benchmarks/validate.py",
    ]
    report = {
        "schema_version": 1,
        "windows": {key: manifest[key] for key in ("history_start", "cutoff", "outcome_end")},
        "protocol": {
            "date_field": "committer timestamp, UTC; start inclusive, end exclusive",
            "cohort": "all tracked paths at cutoff revision",
            "labels": "at least one non-merge future commit matching production subject regex",
            "path_identity": "fixed cutoff path; no forward rename tracking",
            "thresholds": {"low_max": config.LOW_RISK_MAX, "medium_max": config.MEDIUM_RISK_MAX},
            "bugfix_keywords": list(config.BUGFIX_KEYWORDS),
            "churn_weight": config.CHURN_WEIGHT, "bugfix_weight": config.BUGFIX_WEIGHT,
        },
        "provenance": {
            "python": platform.python_version(),
            "git": subprocess.check_output(["git", "--version"], text=True).strip(),
            "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
            # Normalize line endings for checkout portability.
            "source_sha256": {
                path: hashlib.sha256((ROOT / path).read_text(encoding="utf-8").encode()).hexdigest()
                for path in hashed_files
            },
        },
        "summary": aggregate(repositories, rows),
        "repositories": repositories,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8",
    )
    with (args.output_dir / "files.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = markdown(report)
    (args.output_dir / "summary.md").write_text(summary, encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()
