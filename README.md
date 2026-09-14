# PR Risk Signal

PR Risk Signal is a pull request risk analyzer that combines current code changes with historical Git behavior to identify files and code regions that may deserve additional review.

Rather than treating every changed file equally, PR Risk Signal analyzes historical code churn, bug-fix activity, and the size of the current change. It runs automatically through GitHub Actions and persists analysis results through an AWS backend backed by PostgreSQL.

## How It Works

When a pull request is opened or updated, PR Risk Signal:

1. Detects changed files and diff regions.
2. Analyzes the previous six months of Git history.
3. Measures historical **code churn** for each changed file.
4. Identifies **bug-fix-related commits** using signals such as `fix`, `bug`, `hotfix`, `revert`, and `patch`.
5. Normalizes churn relative to the repository using percentile ranking.
6. Calculates a risk score for each changed file.
7. Weights file scores by lines changed to produce an overall PR risk score.
8. Examines changed regions to highlight areas that may deserve additional reviewer attention.
9. Sends the completed analysis to AWS for persistent storage.

Risk scores are classified as:

| Score | Risk Level |
| ---: | --- |
| 0–39 | Low |
| 40–69 | Medium |
| 70–100 | High |

PR Risk Signal is designed as a **review-prioritization signal**, not as a prediction that a pull request contains a bug.

## Risk Model

Each changed file is scored using two historical signals:

```text
File Risk =
    0.40 × Churn Percentile
  + 0.60 × Historical Bugfix Ratio
```

**Churn percentile** measures how frequently a file changes relative to other files in the repository.

**Historical bugfix ratio** measures the proportion of historical commits associated with bug-fix-related commit messages.

The resulting value is scaled from `0–100`. The overall PR score is then calculated by weighting each file's risk by its share of the lines changed in the current pull request.

The weights and thresholds are heuristic starting points, keeping the model deterministic and explainable rather than presenting it as a trained defect predictor.

## Changed-Region Analysis

PR Risk Signal also examines individual diff regions.

For modified or deleted code, the analyzer traces the corresponding lines in the base revision using Git line history. This helps identify changed regions that have historically experienced repeated modifications or bug fixes.

Region history is kept separate from the primary file-level score and is used to prioritize reviewer attention.

## Architecture

```text
Pull Request
     |
     v
GitHub Actions
     |
     v
PR Risk Analyzer
     |
     +----> Git Diff + Repository History
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

GitHub Actions checks out the repository with full Git history and runs the analyzer whenever a pull request is opened, updated, or reopened.

The completed analysis is sent through Amazon API Gateway to AWS Lambda and persisted in PostgreSQL.

The cloud infrastructure is defined and deployed using **AWS SAM / CloudFormation**.

## Tech Stack

- **Python 3.11**
- **Git / GitHub Actions**
- **AWS Lambda**
- **Amazon API Gateway**
- **Amazon RDS for PostgreSQL**
- **Amazon VPC / Security Groups / IAM**
- **AWS SAM / CloudFormation**

## Security & Infrastructure

The `/score` endpoint requires an API key stored using **GitHub Actions Secrets**. Requests without a valid key are rejected by API Gateway before reaching Lambda or PostgreSQL.

The hosted API also uses conservative usage controls:

```text
Rate limit:     1 request / second
Burst limit:    2 requests
Monthly quota:  1000 requests
```

PostgreSQL is deployed inside private VPC subnets with public access disabled. Its security group permits PostgreSQL traffic only from the Lambda security group.

## Repository Structure

```text
pr-risk/
├── .github/
│   └── workflows/
│       └── pr-risk-signal.yml
├── scripts/
│   └── analyze_pr.py
├── src/
│   └── pr_risk/
│       ├── aws_handler.py
│       ├── config.py
│       ├── git_history.py
│       ├── models.py
│       └── scoring.py
├── action.yml
├── template.yml
└── README.md
```

## GitHub Actions Integration

PR Risk Signal is packaged as a composite GitHub Action and runs directly within the pull request workflow.

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

`fetch-depth: 0` provides the historical Git data required by the analyzer.

## Analysis Output

Each analysis includes:

- overall PR risk score and classification
- per-file risk scores
- historical commit and bug-fix counts
- repository-relative churn percentiles
- historical bug-fix ratios
- changed-region history
- prioritized review areas

Results are also written to the GitHub Actions job summary so reviewers can inspect the analysis directly from the pull request workflow.

Analysis history is persisted in PostgreSQL using repository, PR-analysis, and file-analysis records.

## Current Limitations & Access

PR Risk Signal is currently an early-stage deployment intended for demonstration, testing, and small-scale use.

The hosted deployment intentionally uses conservative API limits and currently relies on shared API-key access rather than a multi-user authentication system. The scoring model also uses deterministic Git-history heuristics rather than a trained machine-learning model.

For **larger-scale integration, extended testing, collaboration, or questions about the project**, please reach out to **aritro@vt.edu**.

I am also happy to discuss the architecture, implementation decisions, and future direction of PR Risk Signal with engineers, recruiters, or others interested in the project.

## Future Improvements

Potential extensions include:

- per-user or per-repository authentication
- configurable scoring weights and thresholds
- stronger API request validation
- duplicate-analysis handling
- expanded repository-level analytics
- additional historical risk signals
- larger-scale multi-repository deployment

## License

This project is licensed under the MIT License.