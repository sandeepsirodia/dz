"""File checks: judge a delivery's rows as a whole.

Adding a file check = write one `(rows, context) -> (CheckResult, rows)` function and add it to FILE_CHECKS.
A check that fixes something (dropping duplicates, correcting units) returns the fixed rows; the others
return rows unchanged. They run in list order on the rows that passed the row rules.
"""
from collections import Counter
from typing import Optional

from .types import MAX_EXAMPLES, CheckResult, DeliveryContext, result_from_issues

CENTS_CPM_RATIO_RANGE = (50, 200)   # CPM this far above the platform norm, with whole-number spend -> spend sent in cents
REVIEW_CPM_RATIO      = 3           # any other CPM outside 1/3x..3x is flagged for review, not changed


def compute_cpm(rows: list[dict]) -> Optional[float]:
    """Spend per 1,000 impressions."""
    total_impressions = sum(row["impressions"] for row in rows)
    if not total_impressions:
        return None
    return sum(row["spend_usd"] for row in rows) / total_impressions * 1000


def check_date_format(rows: list[dict], context: DeliveryContext) -> tuple[CheckResult, list[dict]]:
    formats = Counter(row["date_format"] for row in rows)
    dominant_format = formats.most_common(1)[0][0] if formats else None
    issues = [f"{row['source_ref']}: {row['date_format']} (file uses {dominant_format})"
              for row in rows if row["date_format"] != dominant_format]
    summary = "{count} row(s) use a different date format from the rest of the file (normalized)"
    return result_from_issues("date format", issues, summary), rows


def check_duplicate_rows(rows: list[dict], context: DeliveryContext) -> tuple[CheckResult, list[dict]]:
    """Keeps the first row per campaign-day."""
    def metric_values(row):
        return row["campaign"], row["date"], row["spend_usd"], row["impressions"], row["clicks"]

    first_row_by_campaign_day: dict[tuple, dict] = {}
    unique_rows, issues = [], []
    for row in rows:
        campaign_day = (row["campaign"], row["date"])
        first_row = first_row_by_campaign_day.get(campaign_day)
        if first_row is None:
            first_row_by_campaign_day[campaign_day] = row
            unique_rows.append(row)
            continue
        # ponytail: conflicting duplicates keep the first row; a real feed needs a tie-break rule agreed with the platform
        duplicate_kind = "exact duplicate" if metric_values(first_row) == metric_values(row) else "conflicting values, kept first"
        issues.append(f"{row['source_ref']}: {row['campaign']} {row['date']} {duplicate_kind}")
    return result_from_issues("duplicate rows", issues, "{count} duplicate campaign-day row(s) dropped"), unique_rows


def check_coverage(rows: list[dict], context: DeliveryContext) -> tuple[CheckResult, list[dict]]:
    """Every campaign in the file should report every day the file covers."""
    if not rows:
        return CheckResult("coverage", "fail", {"message": "No usable rows in file"}), rows
    campaigns     = sorted({row["campaign"] for row in rows})
    report_dates  = sorted({row["date"] for row in rows})
    reported_days = {(row["campaign"], row["date"]) for row in rows}
    missing_days  = [f"{campaign} {report_date}" for campaign in campaigns for report_date in report_dates
                     if (campaign, report_date) not in reported_days]
    if missing_days:
        return CheckResult("coverage", "warn", {
            "message":  f"{len(missing_days)} campaign-day(s) missing "
                        f"({len(campaigns)} campaigns x {len(report_dates)} days)",
            "count":    len(missing_days),
            "examples": missing_days[:MAX_EXAMPLES],
        }), rows
    return CheckResult("coverage", "pass", {
        "message": f"All {len(campaigns)} campaigns report all {len(report_dates)} days"}), rows


def check_spend_sanity(rows: list[dict], context: DeliveryContext) -> tuple[CheckResult, list[dict]]:
    """Compare this delivery's CPM with the platform's median CPM across its other weeks.

    CPM doesn't depend on volume or week length, so partial weeks and budget changes don't
    trip it - but a unit error in spend moves it by orders of magnitude.
    """
    delivery_cpm, platform_median_cpm = compute_cpm(rows), context.platform_median_cpm
    if delivery_cpm is None or not platform_median_cpm:
        return CheckResult("spend sanity", "pass", {"message": "No baseline to compare against"}), rows

    cpm_ratio   = delivery_cpm / platform_median_cpm
    total_spend = sum(row["spend_usd"] for row in rows)
    detail      = {"cpm": round(delivery_cpm, 2), "baseline_cpm": round(platform_median_cpm, 2),
                   "ratio": round(cpm_ratio, 1)}

    min_cents_ratio, max_cents_ratio = CENTS_CPM_RATIO_RANGE
    looks_like_cents = (min_cents_ratio <= cpm_ratio <= max_cents_ratio
                        and all(float(row["spend_usd"]).is_integer() for row in rows))
    # ponytail: heuristic fix; once the platform confirms, replace with an explicit per-delivery unit override
    if looks_like_cents:
        corrected_rows = [{**row, "spend_usd": row["spend_usd"] / 100} for row in rows]
        return CheckResult("spend sanity", "warn", {**detail, "corrected": True, "message": (
            f"Spend looks reported in cents: CPM ${delivery_cpm:,.2f} vs platform median "
            f"${platform_median_cpm:.2f} ({cpm_ratio:.0f}x) and every value is a whole number. "
            f"Divided by 100: ${total_spend:,.2f} -> ${total_spend / 100:,.2f}. Confirm with the platform.")}), corrected_rows

    if cpm_ratio > REVIEW_CPM_RATIO or cpm_ratio < 1 / REVIEW_CPM_RATIO:
        return CheckResult("spend sanity", "warn", {**detail, "message": (
            f"CPM ${delivery_cpm:.2f} is {cpm_ratio:.1f}x the platform median ${platform_median_cpm:.2f}; "
            f"ingested unchanged, needs review")}), rows

    return CheckResult("spend sanity", "pass", {**detail, "message": (
        f"CPM ${delivery_cpm:.2f} in line with platform median ${platform_median_cpm:.2f}")}), rows


FILE_CHECKS = [check_date_format, check_duplicate_rows, check_coverage, check_spend_sanity]
