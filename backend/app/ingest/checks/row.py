"""Row rules: judge each row on its own.

Adding a row check = write one `(row, context) -> issue | None` function and add a RowRule to ROW_RULES.
Rules run in list order and the first rule that excludes a row stops it, so rules that only
note an issue (and keep the row) go after the excluding ones.
"""
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Optional

from .types import CheckResult, DeliveryContext, result_from_issues

# strptime pattern -> label shown in reports
DATE_FORMATS = {"%m/%d/%Y": "MM/DD/YYYY", "%Y-%m-%d": "YYYY-MM-DD"}


def canonical_names(raw_rows: list[dict]) -> dict[str, str]:
    """Map each case-insensitive campaign name to its most common spelling, preferring capitalized on ties."""
    spelling_counts = Counter(
        name for name in (str(row.get("campaign") or "").strip() for row in raw_rows) if name)
    preferred_spelling: dict[str, str] = {}
    for spelling, count in spelling_counts.items():
        name_key = spelling.casefold()
        current = preferred_spelling.get(name_key)
        if current is None or (count, spelling != spelling.lower()) > (spelling_counts[current], current != current.lower()):
            preferred_spelling[name_key] = spelling
    return preferred_spelling


def _parse_date(raw_value) -> tuple[Optional[date], Optional[str]]:
    """Returns (date, format label), or (None, None) when no known format matches."""
    for pattern, label in DATE_FORMATS.items():
        try:
            return datetime.strptime(str(raw_value).strip(), pattern).date(), label
        except ValueError:
            continue
    return None, None


def _parse_optional_number(raw_value, number_type):
    """None when blank or absent; ValueError when present but not a number."""
    if raw_value is None or str(raw_value).strip() == "":
        return None
    return number_type(str(raw_value).strip())


def coerce_row(raw_row: dict, context: DeliveryContext) -> dict:
    """Turn raw values into typed ones without judging them. Unparseable numbers become None and are listed."""
    parse_errors: list[str] = []

    def number(field_name, number_type):
        try:
            return _parse_optional_number(raw_row.get(field_name), number_type)
        except ValueError:
            parse_errors.append(f"{field_name} {raw_row.get(field_name)!r} is not a number")
            return None

    raw_campaign = str(raw_row.get("campaign") or "")
    row_date, date_format = _parse_date(raw_row.get("date"))
    spend_amount = number("spend_amount", float)
    exchange_rate = context.exchange_rates.get(raw_row.get("spend_currency"))
    can_convert = spend_amount is not None and exchange_rate is not None
    return {
        "source_ref":     raw_row["source_ref"],
        "raw_campaign":   raw_campaign,
        "campaign":       context.canonical_spellings.get(raw_campaign.strip().casefold(), raw_campaign.strip()),
        "raw_date":       raw_row.get("date"),
        "date":           row_date,
        "date_format":    date_format,
        "spend_amount":   spend_amount,
        "spend_currency": raw_row.get("spend_currency"),
        "spend_usd":      spend_amount / raw_row["spend_divisor"] * exchange_rate if can_convert else None,
        "impressions":    number("impressions", int),
        "clicks":         number("clicks", int),
        "parse_errors":   parse_errors,
    }


# ── Rules ────────────────────────────────────────────────────────────────────

def invalid_date(row: dict, context: DeliveryContext) -> Optional[str]:
    if row["date"] is None:
        return f"{row['campaign']} {row['raw_date']!r} is not a valid date"
    if not context.week_start <= row["date"] < context.week_end:
        return f"{row['campaign']} {row['date']} is outside the week of {context.week_start}"
    return None


def invalid_required_value(row: dict, context: DeliveryContext) -> Optional[str]:
    label = f"{row['campaign']} {row['date']}"
    if row["parse_errors"]:
        return f"{label}: {'; '.join(row['parse_errors'])}"
    if not row["campaign"]:
        return f"{label}: missing campaign"
    if row["spend_amount"] is None:
        return f"{label}: missing spend"
    if row["impressions"] is None:
        return f"{label}: missing impressions"
    if row["spend_usd"] is None:
        return f"{label}: unknown currency {row['spend_currency']!r}"
    if row["spend_amount"] < 0:
        return f"{label}: negative spend {row['spend_amount']}"
    if row["impressions"] < 0:
        return f"{label}: negative impressions"
    if row["clicks"] is not None and row["clicks"] < 0:
        return f"{label}: negative clicks"
    return None


def clicks_exceed_impressions(row: dict, context: DeliveryContext) -> Optional[str]:
    # impressions is always set here: invalid_required_value runs first and excludes rows without it
    if row["clicks"] is not None and row["clicks"] > row["impressions"]:
        return f"{row['campaign']} {row['date']}: {row['clicks']} clicks > {row['impressions']} impressions"
    return None


def inconsistent_campaign_name(row: dict, context: DeliveryContext) -> Optional[str]:
    if row["raw_campaign"] != row["campaign"]:
        return f"{row['raw_campaign']!r} -> {row['campaign']!r}"
    return None


def missing_clicks(row: dict, context: DeliveryContext) -> Optional[str]:
    if row["clicks"] is None:
        return f"{row['campaign']} {row['date']}"
    return None


@dataclass(frozen=True)
class RowRule:
    check_name:   str
    summary:      str                                               # report message; {count} = affected rows
    excludes_row: bool                                              # True: drop the row; False: keep it, note the issue
    find_issue:   Callable[[dict, DeliveryContext], Optional[str]]  # None when the row is fine


ROW_RULES = [
    RowRule("date validity",         "{count} row(s) excluded: date is invalid or outside the delivery week",
            True,  invalid_date),
    RowRule("required values",       "{count} row(s) excluded: missing, non-numeric or negative values",
            True,  invalid_required_value),
    RowRule("clicks vs impressions", "{count} row(s) excluded: clicks exceed impressions",
            True,  clicks_exceed_impressions),
    RowRule("campaign name",         "{count} row(s) with inconsistent campaign name casing or whitespace (normalized)",
            False, inconsistent_campaign_name),
    RowRule("missing clicks",        "{count} row(s) have no clicks value (stored as null, left out of CTR/CPC)",
            False, missing_clicks),
]


def apply_row_rules(raw_rows: list[dict], context: DeliveryContext) -> tuple[list[dict], list[CheckResult]]:
    issues_by_check: dict[str, list[str]] = {rule.check_name: [] for rule in ROW_RULES}
    kept_rows = []
    for raw_row in raw_rows:
        row = coerce_row(raw_row, context)
        is_excluded = False
        for rule in ROW_RULES:
            issue = rule.find_issue(row, context)
            if issue is None:
                continue
            issues_by_check[rule.check_name].append(f"{row['source_ref']}: {issue}")
            if rule.excludes_row:
                is_excluded = True
                break
        if not is_excluded:
            kept_rows.append(row)

    results = [result_from_issues(rule.check_name, issues_by_check[rule.check_name], rule.summary)
               for rule in ROW_RULES]
    return kept_rows, results
