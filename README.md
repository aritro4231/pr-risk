# PR Risk Signal

PR Risk Signal is a pull request risk analyzer that combines current code changes with historical Git behavior to identify files and code regions that may deserve additional review.

Rather than treating every changed file equally, PR Risk Signal analyzes how frequently code has changed in the past, how often those changes were associated with bug fixes, and how much of the current pull request touches each file. The analysis runs automatically through GitHub Actions and persists results through an AWS serverless backend backed by PostgreSQL.

## How It Works

When a pull request is opened or updated, PR Risk Signal:

1. Extracts the files and line regions modified by the pull request.
2. Analyzes the previous six months of Git history for each changed file.
3. Measures historical **code churn** based on how frequently each file has changed.
4. Identifies **bug-fix-related commits** using commit-message signals such as `fix`, `bug`, `hotfix`, `revert`, and `patch`.
5. Normalizes file churn against the repository's own history using percentile ranking.
6. Calculates a risk score for each changed file.
7. Weights file scores by the amount of code changed to produce an overall PR risk score.
8. Examines the history of individual changed regions to highlight areas that may deserve additional reviewer attention.
9. Sends the completed analysis to the AWS backend for persistent storage.

The result is classified as:

|  Score | Risk Level |
| -----: | ---------- |
|   0–39 | Low        |
|  40–69 | Medium     |
| 70–100 | High       |

PR Risk Signal is designed as a **review-prioritization signal**, not as a prediction that a pull request contains a bug.

## Risk Model

For each changed file, the current scoring model combines two historical signals:

```text
File Risk =
    0.40 × Churn Percentile
  + 0.60 × Historical Bugfix Ratio
```

**Churn percentile** measures how frequently a file has changed relative to other files in the same repository.

**Historical bugfix ratio** measures the proportion of the file's historical commits whose commit messages contain bug-fix-related signals.

The resulting value is scaled to a score from `0–100`.

The overall pull request score is then calculated by weighting each file's risk by its share of the lines changed in the current PR.

The weights and thresholds are intentionally heuristic starting points rather than a trained prediction model.

## Changed-Region Analysis

PR Risk Signal also analyzes individual diff regions.

For modified or deleted code, the analyzer traces the corresponding lines in the base revision using Git line history. This allows the output to identify changed regions that have historically experienced repeated modifications or bug fixes.

Purely new lines have no corresponding historical lines in the base revision, so they do not receive historical region-level signals.

This region analysis is kept separate from the primary file-level score and is used to help prioritize reviewer attention rather than artificially increasing the overall risk score.

## Architecture

```text
Pull Request
     |
     v
GitHub Actions
     |
     v
PR Risk Analyzer
  |        |
  |        +--> Git diff + repository history
  |
  v
API Gateway
     |
     v
AWS Lambda
     |
     v
PostgreSQL (Amazon RDS)
```

### CI/CD Integration

GitHub Actions automatically runs the analyzer when a pull request is:

* opened
* synchronized with new commits
* reopened

The workflow checks out the repository with full Git history so the analyzer can evaluate historical behavior rather than only the latest snapshot.

### AWS Backend

The backend is deployed using **AWS SAM / CloudFormation** and consists of:

* **Amazon API Gateway** — exposes the analysis API
* **AWS Lambda** — processes and persists analysis results
* **Amazon RDS for PostgreSQL** — stores repository, PR, and file-level analysis history
* **Amazon VPC** — isolates backend database resources
* **Security Groups** — restrict PostgreSQL access to the Lambda function

The PostgreSQL database is deployed in private subnets and is not publicly accessible.

## API Security

The `/score` endpoint requires an API key.

The GitHub workflow stores the key using **GitHub Actions Secrets** and sends it through the `x-api-key` request header. The key is never stored directly in the repository.

API Gateway also applies usage controls to limit abuse:

```text
Rate limit:    1 request / second
Burst limit:   2 requests
Monthly quota: 1000 requests
```

Requests without a valid API key are rejected by API Gateway before reaching the Lambda function or database.

## Tech Stack

**Language:** Python 3.11

**Developer tooling:** Git, GitHub Actions

**Cloud:** AWS Lambda, API Gateway, Amazon RDS, VPC, IAM

**Database:** PostgreSQL

**Infrastructure as Code:** AWS SAM, CloudFormation

## Repository Structure

```text
pr-risk/
├── .github/
│   └── workflows/
│       └── pr-risk-signal.yml
├── scripts/
│   └── analyze_pr.py
├── src/
│   ├── pr_risk/
│   │   ├── aws_handler.py
│   │   ├── config.py
│   │   ├── git_history.py
│   │   ├── models.py
│   │   └── scoring.py
│   └── requirements.txt
├── action.yml
├── template.yml
├── LICENSE
└── README.md
```

## GitHub Actions Integration

PR Risk Signal is packaged as a composite GitHub Action.

A workflow checks out the target repository with its complete history and invokes the analyzer using the configured API endpoint and API key.

```yaml
- name: Checkout repository
  uses: actions/checkout@v4
  with:
    fetch-depth: 0

- name: Run PR Risk Signal
  uses: ./
  with:
    api-url: ${{ vars.PR_RISK_API_URL }}
    api-key: ${{ secrets.PR_RISK_API_KEY }}
```

`fetch-depth: 0` is required because the risk model depends on historical Git data.

## Analysis Output

A completed analysis includes:

* overall PR risk score and classification
* per-file risk scores
* additions and deletions
* historical commit counts
* historical bug-fix counts
* repository-relative churn percentiles
* historical bug-fix ratios
* changed-region history
* prioritized review areas

Analysis results are also written to the GitHub Actions job summary for quick inspection during the pull request workflow.

## Database Model

PR Risk Signal persists analysis history using a relational PostgreSQL schema:

```text
repositories
     |
     | 1:N
     v
pr_analyses
     |
     | 1:N
     v
file_analyses
```

This allows multiple pull request analyses to be associated with a repository while retaining the file-level signals that contributed to each result.

## Design Goals

PR Risk Signal focuses on a few specific goals:

* use repository-specific historical behavior instead of generic code-size thresholds
* integrate directly into existing pull request workflows
* provide explainable signals rather than an opaque score
* highlight both risky files and specific changed regions
* keep cloud infrastructure isolated and reproducible through Infrastructure as Code
* remain lightweight enough to run automatically during code review

## Current Scope

PR Risk Signal currently uses deterministic Git-history heuristics rather than machine learning.

The project intentionally does **not** attempt to automatically approve or reject pull requests, prove that code contains defects, or replace human code review.

Potential future improvements include per-user API credentials, stronger request validation, configurable scoring policies, duplicate-analysis handling, and expanded repository-level analytics.

## License

This project is licensed under the MIT License.
