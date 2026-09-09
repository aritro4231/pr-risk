from .config import (
    BUGFIX_WEIGHT,
    CHURN_WEIGHT,
    LOW_RISK_MAX,
    MEDIUM_RISK_MAX,
)
from .models import (
    FileRiskResult,
    FileStats,
    PRRiskResult,
)


def get_risk_level(score: float) -> str:
    """
    Convert a 0-100 score into a human-readable risk level.
    """

    if score <= LOW_RISK_MAX:
        return "low"

    if score <= MEDIUM_RISK_MAX:
        return "medium"

    return "high"


def calculate_percentile_rank(
    value: int,
    values: list[int],
) -> float:
    """
    Calculate the percentile rank of a value relative
    to the supplied distribution.

    Returns a number between 0 and 1.

    Example:
        values = [2, 5, 10, 20]
        value = 10

        Values lower than 10:
            2, 5

        percentile ~= 0.67
    """

    if not values:
        return 0.0

    if len(values) == 1:
        return 0.5

    lower_count = sum(
        1
        for item in values
        if item < value
    )

    equal_count = sum(
        1
        for item in values
        if item == value
    )

    percentile = (
        lower_count
        + 0.5 * equal_count
    ) / len(values)

    return min(max(percentile, 0.0), 1.0)


def calculate_file_risk(
    churn_percentile: float,
    bugfix_ratio: float,
) -> float:
    """
    Calculate file risk on a 0-1 scale.

    Historical bugfix activity receives more weight
    than raw churn.
    """

    risk = (
        CHURN_WEIGHT * churn_percentile
        + BUGFIX_WEIGHT * bugfix_ratio
    )

    return min(max(risk, 0.0), 1.0)


def score_file(
    file_stats: FileStats,
    churn_distribution: list[int],
) -> FileRiskResult:
    """
    Calculate risk for one file.
    """

    churn_percentile = calculate_percentile_rank(
        file_stats.historical_commit_count,
        churn_distribution,
    )

    file_risk = calculate_file_risk(
        churn_percentile=churn_percentile,
        bugfix_ratio=file_stats.bugfix_ratio,
    )

    score = round(file_risk * 100, 2)

    return FileRiskResult(
        path=file_stats.path,
        risk_score=score,
        risk_level=get_risk_level(score),
        churn_percentile=round(churn_percentile, 4),
        bugfix_ratio=round(file_stats.bugfix_ratio, 4),
        lines_changed=file_stats.lines_changed,
        historical_commit_count=(
            file_stats.historical_commit_count
        ),
        historical_bugfix_count=(
            file_stats.historical_bugfix_count
        ),
    )


def score_pr(files: list[FileStats]) -> PRRiskResult:
    """
    Calculate the overall PR risk score.

    Each file contributes proportionally to how much
    of the PR it represents.

    Example:

        payment.py = 80 lines changed
        README.md   = 20 lines changed

    payment.py contributes 80% of the PR score.
    """

    if not files:
        return PRRiskResult(
            risk_score=0.0,
            risk_level="low",
            contributing_files=[],
        )

    churn_distribution = [
        file.historical_commit_count
        for file in files
    ]

    file_results = [
        score_file(
            file_stats=file,
            churn_distribution=churn_distribution,
        )
        for file in files
    ]

    total_lines_changed = sum(
        file.lines_changed
        for file in files
    )

    if total_lines_changed == 0:
        overall_score = 0.0

    else:
        overall_score = 0.0

        for file, result in zip(
            files,
            file_results,
        ):
            change_weight = (
                file.lines_changed
                / total_lines_changed
            )

            overall_score += (
                change_weight
                * result.risk_score
            )

    overall_score = round(overall_score, 2)

    return PRRiskResult(
        risk_score=overall_score,
        risk_level=get_risk_level(overall_score),
        contributing_files=file_results,
    )