# PR Risk Signal historical validation

- Repositories tested: **4**
- Unique pre-cutoff commits inspected: **19,521**
- Commits in the scoring history window: **223**
- Files scored: **730**
- Mean repository future bug-fix file rate: high **0.00%**, low **2.76%**
- Pooled future bug-fix file rate: high **0.00%**, low **2.61%**
- High-risk precision (pooled): **0.00%**

Each rate is the fraction of files with at least one future bug-fix-like commit.
Precision is the same fraction among files classified high risk. Empty groups are N/A;
repository means exclude them and JSON reports the number of contributing repositories.

| Repository | Pre-cutoff commits | Window commits | Files | High: positive / total | High rate | Low: positive / total | Low rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pallets/flask | 5,214 | 102 | 250 | 0 / 3 | 0.00% | 5 / 239 | 2.09% |
| pallets/click | 2,294 | 45 | 146 | 0 / 14 | 0.00% | 4 / 128 | 3.12% |
| psf/requests | 6,230 | 72 | 103 | 0 / 4 | 0.00% | 3 / 94 | 3.19% |
| expressjs/express | 5,783 | 4 | 231 | 0 / 0 | N/A | 6 / 228 | 2.63% |

History: [2023-07-01T00:00:00Z, 2024-01-01T00:00:00Z).
Outcomes: [2024-01-01T00:00:00Z, 2024-07-01T00:00:00Z).
Production thresholds: low <= 39; medium > 39 and <= 69; high > 69.

These are message-based maintenance labels, not verified defects or bug-inducing PRs.
All tracked cutoff paths are scored, including inactive files, tests, docs, and binaries.
Future outcomes omit merge commits and do not follow paths forward after renames.
The selected release lineages and single time split limit generalization.
See README.md for the protocol and summary.json / files.csv for auditable results.
