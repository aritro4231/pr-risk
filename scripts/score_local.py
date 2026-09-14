from pr_risk.git_history import (
    get_file_history,
    get_line_history,
)
from pr_risk.models import FileStats
from pr_risk.scoring import score_pr


repo_path = r"C:\Users\tld\flask"
file_path = "src/flask/app.py"


# Get history for the entire file
history = get_file_history(
    file_path=file_path,
    repo_path=repo_path,
)


# Temporary test range.
# Later this will come from the actual PR diff.
line_history = get_line_history(
    file_path=file_path,
    start_line=100,
    end_line=130,
    repo_path=repo_path,
)


file_stats = FileStats(
    path=file_path,
    additions=20,
    deletions=5,
    historical_commit_count=history["historical_commit_count"],
    historical_bugfix_count=history["historical_bugfix_count"],
)


result = score_pr([file_stats])


print("PR Risk Score:", result.risk_score)
print("Risk Level:", result.risk_level)


for file in result.contributing_files:
    print()
    print(file.path)
    print("  Risk:", file.risk_score)
    print("  Churn percentile:", file.churn_percentile)
    print("  Bugfix ratio:", file.bugfix_ratio)
    print(
        "  Historical commits:",
        file.historical_commit_count,
    )
    print(
        "  Bugfix-like commits:",
        file.historical_bugfix_count,
    )


print()
print("Changed Region History")
print(
    f"  Lines: "
    f"{line_history['start_line']}-"
    f"{line_history['end_line']}"
)
print(
    "  Historical commits:",
    line_history["historical_commit_count"],
)
print(
    "  Bugfix-like commits:",
    line_history["historical_bugfix_count"],
)
print(
    "  Bugfix ratio:",
    round(line_history["bugfix_ratio"], 2),
)