from pr_risk.models import FileStats
from pr_risk.scoring import score_pr

files = [
    FileStats(
        path="src/payment.py",
        additions=80,
        deletions=20,
        historical_commit_count=30,
        historical_bugfix_count=12,
    ),
    FileStats(
        path="README.md",
        additions=10,
        deletions=0,
        historical_commit_count=4,
        historical_bugfix_count=0,
    ),
]

result = score_pr(files)

print("PR Risk Score:", result.risk_score)
print("Risk Level:", result.risk_level)

for file in result.contributing_files:
    print()
    print(file.path)
    print("  Risk:", file.risk_score)
    print("  Churn percentile:", file.churn_percentile)
    print("  Bugfix ratio:", file.bugfix_ratio)