# Historical validation

This experiment tests whether production file scores predict subsequent
bug-fix-like maintenance, using four public repositories with substantial
history: [Flask](https://github.com/pallets/flask),
[Click](https://github.com/pallets/click),
[Requests](https://github.com/psf/requests), and
[Express](https://github.com/expressjs/express).
They were chosen as established, manageable projects across Python and
JavaScript, before examining outcomes. This is a convenience sample; Flask
and Click share an ecosystem.

## Run

Requires Python 3.11+ and Git; no Python packages, GitHub token, AWS access,
or execution of downloaded repository code is needed. From the project root:

```console
python -B benchmarks/validate.py
python -B benchmarks/validate.py --offline
python -B -m unittest discover -s benchmarks -p "test_*.py" -v
```

The first command clones complete Git histories into ignored `benchmarks/.cache/`.
The second reruns with those clones and no network. Download size and runtime
depend on the repositories; production performs one history traversal per file.
Use `--output-dir PATH` to write a separate comparison run.
`--manifest PATH` and `--cache-dir PATH` are also supported.
Existing caches are not fetched or updated. Tag/commit mismatches and shallow
clones fail explicitly.

Checked-in results:

- [summary.md](results/summary.md): readable results.
- [summary.json](results/summary.json): exact rates, group sizes, commit counts,
  locked revisions, ancestry audits, source hashes, runtime versions, and all
  future labeled commit IDs/subjects with matching scored paths.
- [files.csv](results/files.csv): every file's production score, historical
  features, classification, and future bug-fix commit count.

## Protocol and leakage controls

1. `repositories.json` locks public release tags, peeled commit IDs, and
   both snapshot IDs. For each release lineage, select the first commit in
   first-parent traversal whose **committer timestamp** is strictly before
   January 1, 2024 (cutoff), and similarly July 1, 2024 (outcome end).
   The anchor must extend beyond the outcome window. These are selected release
   lineages, not all branches or necessarily today's default branch.
2. Audit **every ancestor** of both snapshots. Abort if any is dated at or after
   its boundary. This prevents a backdated tip from hiding a future ancestor.
   Verify the cutoff revision is an ancestor of the outcome revision.
   Git timestamps are a reproducible proxy for availability; historical server
   push times cannot be reconstructed, so delayed pushes/backdating remain a
   limitation.
3. Enumerate all tracked paths at the cutoff with production
   `get_tracked_files`. Include inactive files, tests, docs, and binaries,
   without future-based sampling. Call production `get_file_history` with
   the **cutoff SHA** and absolute `since=2023-07-01T00:00:00Z`.
   This uses the same `git log --follow --since` and subject classifier.
   The six-calendar-month lookback is checked against `HISTORY_WINDOW`,
   and never interpreted relative to the day the benchmark runs.
4. Build the repository-wide churn distribution from those same cached counts
   (equivalent to production `get_repo_churn_distribution`). Call
   production `score_file` for every path. No scoring formula is copied
   or modified. Additions/deletions are zero because this is a file-level
   historical experiment, not a synthetic PR; they do not affect file scores.
   Freeze all scores before inspecting future commit subjects or changes.
5. Label non-merge commits reachable from the outcome SHA but not the cutoff
   SHA, with timestamps in [2024-01-01, 2024-07-01). Exclude and count
   pre-cutoff-dated commits newly reachable in this range. Use production
   `is_bugfix_commit` on subjects (`fix`, `bug`, `hotfix`, `revert`, `patch`
   as case-insensitive whole words). Each matching commit contributes once to
   each cutoff path it touches, using its parent diff. Omitting merge commits
   avoids counting both merges and their constituent commits; fixes made only
   in merge resolutions are consequently missed.
6. Apply production classes exactly: **low <= 39, medium > 39 and <= 69,
   high > 69** on the rounded score. These thresholds are set before outcomes;
   scores such as 69.5 are high in the current implementation. No threshold
   optimization uses the future labels.

## Metrics

A file is positive if at least one qualifying future commit touches it.
The **future bug-fix file rate** is positive files / all files in a risk group.
The high-group rate is also **precision**, treating high risk as a positive
prediction. Multiple fixes to one file do not inflate precision. JSON also
reports average future bug-fix commits per file as a separate measure.

The headline average is the arithmetic mean of repository rates (macro).
Pooled rates weight by number of files (micro). Both are reported; empty
groups are null / N/A and excluded from macro averages, with coverage counts
in JSON. Medium-risk files remain in the artifacts and total cohort, but
are not included in high-versus-low comparisons. JSON additionally reports
groups restricted to historically active files, without using future activity
to select that cohort.

**Total historical commits analyzed** counts unique commits reachable from each
cutoff revision, summed across repositories, inspected during the leakage audit.
**History-window commits** counts unique commits returned by the production
`--since` restriction on that revision; these are reported separately so
the full-history audit count is not confused with the six-month scoring window.
Per-file historical counts can sum above this number because one commit can
touch multiple paths. Git's production path traversal, merge simplification,
and `--since` early termination under non-monotonic dates are preserved.

## Interpretation and limits

Commit-message matching is a noisy maintenance proxy, not confirmed defects,
bug-introducing commits, causal evidence, or calibrated PR failure probability.
`patch` may describe non-bug work and real fixes may omit the keywords.
Active files have more opportunities for future fixes. The historically active
diagnostic helps expose, but does not remove, this confounding.

Observation units are **fixed cutoff paths**. Historical renames are followed
by production; future renames touch both paths, but later fixes at the new
path are not attributed to the old one. Deleted files remain in the denominator.
No survival/exposure correction is applied. Files introduced after cutoff
are excluded. Results do not generalize to arbitrary repositories from a
single six-month split across these four release lineages.

The JSON captures source SHA-256 hashes (normalized line endings), the manifest
hash, Python/Git versions, exact snapshot SHAs, and window dates. There is no
wall-clock generation timestamp or random sampling. Repeated runs on the
same inputs and tool versions produce identical artifacts; provenance may
differ on other tool versions. Changing the manifest constitutes a new
experiment, and outcome-driven selection of dates or repositories would bias
its results.

## Observed result

The checked-in split does **not** support higher future bug-fix incidence for
the production high-risk class: 0 of 21 high-risk files were positive, compared
with 18 of 689 low-risk files (2.61% pooled). Repository means are 0.00% high
and 2.76% low; the high mean covers three repositories because Express has
no high-risk files. Medium-risk files had 5 positives out of 20 (25.00%).
These small samples do not establish a monotonic score/outcome relationship.

The 19,521 historical commits audited include 223 commits in the six-month
scoring window; Express contributes only four window commits. Limited recent
activity, keyword labels, and the selected release lineages constrain the
interpretation. The thresholds and repository/date selections were retained
after observing these results.

The harness disables Git path quoting and runs Python in UTF-8 mode (restarting
itself if needed), allowing non-ASCII paths to reach the unchanged production
helpers correctly on Windows as well as Unix. It fails explicitly if a path
still cannot round-trip through the production path enumeration.
