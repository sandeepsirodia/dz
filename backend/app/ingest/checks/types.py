from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

MAX_EXAMPLES = 5   # affected rows listed per check in the quality report


@dataclass
class CheckResult:
    check_name: str
    outcome:    str             # pass | warn | fail
    detail:     dict[str, Any]


@dataclass
class DeliveryContext:
    """Everything a check may need to know about the delivery under review."""
    platform:            str
    week_start:          date
    expected_filename:   str
    original_file:       Optional[Path]   = None
    resend_file:         Optional[Path]   = None
    exchange_rates:      dict[str, float] = field(default_factory=dict)
    canonical_spellings: dict[str, str]   = field(default_factory=dict)   # casefolded name -> preferred spelling
    platform_median_cpm: Optional[float]  = None                          # across this platform's other weeks

    @property
    def week_end(self) -> date:
        return self.week_start + timedelta(days=7)

    @property
    def source_file(self) -> Optional[Path]:
        """A resend supersedes the original."""
        return self.resend_file or self.original_file


def result_from_issues(check_name: str, issues: list[str], summary: str) -> CheckResult:
    """pass when there are no issues, otherwise warn with a count and the first few affected rows."""
    if not issues:
        return CheckResult(check_name, "pass", {"message": "No issues"})
    return CheckResult(check_name, "warn", {
        "message":  summary.format(count=len(issues)),
        "count":    len(issues),
        "examples": issues[:MAX_EXAMPLES],
    })
