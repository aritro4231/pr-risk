"""Regression tests for temporal isolation and outcome accounting (no network)."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import validate
from pr_risk.git_history import get_file_history, get_repo_churn_distribution
from pr_risk.models import FileStats
from pr_risk.scoring import score_file


class HistoricalValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Benchmark Test")
        self.git("config", "user.email", "benchmark@example.invalid")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args, date=None):
        env = dict(os.environ)
        if date:
            env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
        return subprocess.check_output(
            ["git", *args], cwd=self.repo, env=env, text=True, encoding="utf-8",
        ).strip()

    def commit(self, date, subject, changes):
        for path, content in changes.items():
            target = self.repo / path
            if content is None:
                target.unlink()
            else:
                target.write_text(content, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", subject, date=date)
        return self.git("rev-parse", "HEAD")

    def test_production_parity_and_future_isolation(self):
        self.commit("2023-06-01T00:00:00Z", "initial", {"old.py": "a\n", "idle.py": "idle\n"})
        self.commit("2023-08-01T00:00:00Z", "fix old bug", {"old.py": "b\n"})
        self.git("mv", "old.py", "renamed.py")
        self.git("commit", "-q", "-m", "rename", date="2023-09-01T00:00:00Z")
        base = self.commit("2023-12-01T00:00:00Z", "feature", {"renamed.py": "c\n"})
        before = validate.score_snapshot(self.repo, base, "2023-07-01T00:00:00Z")
        distribution = get_repo_churn_distribution(
            self.repo, since="2023-07-01T00:00:00Z", revision=base,
        )
        for row in before:
            history = get_file_history(
                row["path"], self.repo, since="2023-07-01T00:00:00Z", revision=base,
            )
            expected = score_file(FileStats(additions=0, deletions=0, **history), distribution)
            self.assertEqual(row, validate.asdict(expected))
        self.commit("2024-01-01T00:00:00Z", "fix future", {"renamed.py": "d\n", "future.py": "x\n"})
        end = self.commit("2024-02-01T00:00:00Z", "revert feature", {"renamed.py": "e\n"})
        after = validate.score_snapshot(self.repo, base, "2023-07-01T00:00:00Z")
        self.assertEqual(before, after)
        self.assertNotIn("future.py", [row["path"] for row in after])
        cutoff = validate.timestamp("2024-01-01T00:00:00Z")
        self.assertEqual(validate.snapshot_before(self.repo, end, cutoff), base)
        counts, details = validate.future_labels(
            self.repo, base, end, cutoff, validate.timestamp("2024-07-01T00:00:00Z"),
            {row["path"] for row in after},
        )
        self.assertEqual(counts, {"renamed.py": 2, "idle.py": 0})
        self.assertEqual(details["bugfix_like_commits"], 2)

    def test_rejects_post_cutoff_ancestor_even_with_backdated_tip(self):
        self.commit("2023-12-01T00:00:00Z", "base", {"a": "one"})
        self.commit("2024-02-01T00:00:00Z", "fix future", {"a": "two"})
        tip = self.commit("2023-12-30T00:00:00Z", "backdated tip", {"a": "three"})
        cutoff = validate.timestamp("2024-01-01T00:00:00Z")
        self.assertEqual(validate.snapshot_before(self.repo, tip, cutoff), tip)
        with self.assertRaisesRegex(ValueError, "Leakage"):
            validate.validate_snapshot(self.repo, tip, cutoff)

    def test_outcome_boundaries_backdating_and_deleted_paths(self):
        base = self.commit("2023-12-01T00:00:00Z", "base", {"a": "a", "b": "b"})
        self.commit("2023-12-20T00:00:00Z", "fix backdated", {"a": "changed"})
        self.commit("2024-01-01T00:00:00Z", "fix at cutoff", {"a": "fixed"})
        self.commit("2024-02-01T00:00:00Z", "prefix fixture", {"a": "unlabeled"})
        end = self.commit("2024-06-30T23:59:59Z", "revert b", {"b": None})
        anchor = self.commit("2024-07-01T00:00:00Z", "fix at end", {"a": "outside"})
        cutoff = validate.timestamp("2024-01-01T00:00:00Z")
        end_time = validate.timestamp("2024-07-01T00:00:00Z")
        self.assertEqual(validate.snapshot_before(self.repo, anchor, end_time), end)
        counts, details = validate.future_labels(self.repo, base, end, cutoff, end_time, {"a", "b"})
        self.assertEqual(counts, {"a": 1, "b": 1})
        self.assertEqual(details["excluded_pre_cutoff_nonmerge_commits"], 1)
        self.assertEqual(details["eligible_nonmerge_commits"], 3)

    def test_merge_labels_are_not_double_counted(self):
        base = self.commit("2023-12-01T00:00:00Z", "base", {"a": "a"})
        self.git("checkout", "-q", "-b", "topic")
        self.commit("2024-01-10T00:00:00Z", "fix topic", {"a": "fixed"})
        self.git("checkout", "-q", "-b", "mainline", base)
        self.commit("2024-01-11T00:00:00Z", "feature", {"b": "b"})
        self.git("merge", "--no-ff", "topic", "-m", "fix merge", date="2024-01-12T00:00:00Z")
        end = self.git("rev-parse", "HEAD")
        counts, details = validate.future_labels(
            self.repo, base, end, validate.timestamp("2024-01-01T00:00:00Z"),
            validate.timestamp("2024-07-01T00:00:00Z"), {"a"},
        )
        self.assertEqual(counts, {"a": 1})
        self.assertEqual(details["eligible_nonmerge_commits"], 2)

    def test_group_denominators_empty_groups_and_macro_average(self):
        def row(level, count):
            return {"risk_level": level, "future_bugfix_commit_count": count,
                    "historical_commit_count": 1}
        first = [row("high", 4), row("high", 0), row("low", 0)]
        second = [row("high", 0)] * 8 + [row("low", 1)]
        third = [row("low", 0)]
        repos = [
            {"groups": validate.group_metrics(rows), "history_window_commits": 2,
             "history_audit": {"reachable_commits": 5}}
            for rows in (first, second, third)
        ]
        metrics = validate.aggregate(repos, first + second + third)
        self.assertEqual(metrics["pooled"]["high_risk_precision"], 0.1)
        self.assertEqual(metrics["repository_mean_high_risk_precision"], 0.25)
        self.assertEqual(metrics["repositories_with_nonempty_group"]["high"], 2)
        self.assertIsNone(metrics["pooled"]["medium"]["future_bugfix_file_rate"])
        self.assertEqual(metrics["total_historical_commits_analyzed"], 15)

    def test_utf8_paths_with_benchmark_git_settings(self):
        path = "caf\u00e9 space.txt"
        base = self.commit("2023-08-01T00:00:00Z", "fix initial bug", {path: "text"})
        env = dict(os.environ)
        env.update(
            GIT_CONFIG_COUNT="2", GIT_CONFIG_KEY_0="log.showSignature",
            GIT_CONFIG_VALUE_0="false", GIT_CONFIG_KEY_1="core.quotepath",
            GIT_CONFIG_VALUE_1="false",
        )
        code = (
            "import sys,json; from pathlib import Path; "
            "sys.path.insert(0,'benchmarks'); import validate; "
            "print(json.dumps(validate.score_snapshot("
            "Path(sys.argv[1]),sys.argv[2],'2023-07-01T00:00:00Z')))"
        )
        output = subprocess.check_output(
            [validate.sys.executable, "-X", "utf8", "-B", "-c", code, str(self.repo), base],
            cwd=validate.ROOT, env=env, text=True, encoding="utf-8",
        )
        rows = validate.json.loads(output)
        self.assertEqual(rows[0]["path"], path)
        self.assertEqual(rows[0]["historical_bugfix_count"], 1)

    def test_window_must_be_absolute_and_match_production(self):
        valid = {"history_start": "2023-07-01T00:00:00Z", "cutoff": "2024-01-01T00:00:00Z",
                 "outcome_end": "2024-07-01T00:00:00Z"}
        validate.check_windows(valid)
        with self.assertRaises(ValueError):
            validate.check_windows({**valid, "history_start": "2023-06-01T00:00:00Z"})
        with self.assertRaises(ValueError):
            validate.timestamp("2024-01-01")


if __name__ == "__main__":
    unittest.main()
