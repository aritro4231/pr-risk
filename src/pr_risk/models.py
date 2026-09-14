from dataclasses import dataclass


@dataclass
class FileStats:
    path: str
    additions: int
    deletions: int
    historical_commit_count: int
    historical_bugfix_count: int

    @property
    def lines_changed(self) -> int:
        return self.additions + self.deletions

    @property
    def bugfix_ratio(self) -> float:
        if self.historical_commit_count == 0:
            return 0.0

        return (
            self.historical_bugfix_count
            / self.historical_commit_count
        )


@dataclass
class FileRiskResult:
    path: str
    risk_score: float
    risk_level: str

    churn_percentile: float
    bugfix_ratio: float

    lines_changed: int
    historical_commit_count: int
    historical_bugfix_count: int


@dataclass
class PRRiskResult:
    risk_score: float
    risk_level: str
    contributing_files: list[FileRiskResult]