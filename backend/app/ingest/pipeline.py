"""Ingestion: discover -> parse -> delivery, row and file checks -> store.

A "slot" is one (platform_key, week_start) pair - one expected weekly delivery.
"""
import json
import os
import re
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from statistics import median
from typing import Callable, NamedTuple, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ..db import Base
from ..models import CampaignMetric, Delivery, Platform, QualityCheck
from .parsers import parse_meta_file, parse_google_file, parse_linkedin_file
from .checks.types import CheckResult, DeliveryContext
from .checks.delivery import DELIVERY_CHECKS
from .checks.file import FILE_CHECKS, compute_cpm
from .checks.row import apply_row_rules, canonical_names

EXCHANGE_RATES_PATH = Path(__file__).parents[3] / "data" / "exchange_rates.json"


class PlatformSpec(NamedTuple):
    name:                 str
    extension:            str
    parse_file:           Callable[[str], list[dict]]
    transformation_rules: tuple[str, ...]   # recorded on every delivery for traceability


# keyed by filename prefix
PLATFORMS: dict[str, PlatformSpec] = {
    "meta_ads": PlatformSpec(Platform.META.value, "csv", parse_meta_file, (
        "date: MM/DD/YYYY (ISO also accepted) -> ISO date",
        "spend_usd: taken as USD",
    )),
    "google_ads": PlatformSpec(Platform.GOOGLE.value, "csv", parse_google_file, (
        "Day: YYYY-MM-DD",
        "Cost (micros): divided by 1,000,000",
        "Currency: converted to USD with exchange_rates.json",
    )),
    "linkedin_ads": PlatformSpec(Platform.LINKEDIN.value, "json", parse_linkedin_file, (
        "date_ts: epoch milliseconds -> UTC date",
        "spend.amount: converted from spend.currency to USD with exchange_rates.json",
    )),
}
DELIVERY_FILENAME = re.compile(
    r"^(?P<platform_key>meta_ads|google_ads|linkedin_ads)_(?P<week>\d{4}-\d{2}-\d{2})"
    r"(?P<resend>_resend)?\.(?P<extension>csv|json)$"
)


def _load_exchange_rates() -> dict[str, float]:
    rates_path = Path(os.getenv("EXCHANGE_RATES_PATH", EXCHANGE_RATES_PATH))
    return json.loads(rates_path.read_text())["rates"]


def classify_health(check_results: list[CheckResult]) -> str:
    outcomes = {result.outcome for result in check_results}
    return "fail" if "fail" in outcomes else "warn" if "warn" in outcomes else "pass"


def _week_from_filename(match: re.Match) -> Optional[date]:
    """None when the extension doesn't fit the platform or the date is impossible."""
    if match["extension"] != PLATFORMS[match["platform_key"]].extension:
        return None
    try:
        return date.fromisoformat(match["week"])
    except ValueError:
        return None


def discover_deliveries(data_dir: Path) -> tuple[dict, list[str]]:
    """Map every expected slot to its files ({"original": Path, "resend": Path}) and list files that don't fit.

    Every platform is expected every week from the first week seen to the last, so a missing file -
    or a week missing for all platforms - shows up as an empty slot.
    """
    files_by_slot: dict[tuple[str, date], dict[str, Path]] = {}
    ignored_files: list[str] = []
    for file_path in sorted(data_dir.iterdir()):
        if not file_path.is_file() or file_path.name.startswith("."):
            continue
        match = DELIVERY_FILENAME.match(file_path.name)
        week = _week_from_filename(match) if match else None
        if week is None:
            ignored_files.append(file_path.name)
            continue
        file_kind = "resend" if match["resend"] else "original"
        files_by_slot.setdefault((match["platform_key"], week), {})[file_kind] = file_path

    seen_weeks = {week for _, week in files_by_slot}
    weekly_cadence = set()
    if seen_weeks:
        first_week, last_week = min(seen_weeks), max(seen_weeks)
        weekly_cadence = {first_week + timedelta(weeks=n) for n in range((last_week - first_week).days // 7 + 1)}
    weeks = sorted(seen_weeks | weekly_cadence)
    all_slots = {(platform_key, week): files_by_slot.get((platform_key, week), {})
                 for platform_key in PLATFORMS for week in weeks}
    return all_slots, ignored_files


def _transformation_rules(platform_key: str, raw_rows: list[dict], context: DeliveryContext) -> list[str]:
    rules = list(PLATFORMS[platform_key].transformation_rules)
    foreign_currencies = sorted({row["spend_currency"] for row in raw_rows if row.get("spend_currency")} - {"USD"})
    rules += [f"{currency} -> USD at {context.exchange_rates[currency]}"
              for currency in foreign_currencies if currency in context.exchange_rates]
    rules.append("campaign: trimmed and matched case-insensitively to the platform's most common spelling")
    if context.original_file and context.resend_file:
        rules.append(f"{context.resend_file.name} used in place of {context.original_file.name}")
    return rules


def _metric_fields(row: dict) -> dict:
    return {"campaign": row["campaign"], "date": row["date"].isoformat(), "spend_usd": row["spend_usd"],
            "impressions": row["impressions"], "clicks": row["clicks"]}


def run_pipeline(data_dir: str, db_url: str, dry_run: bool = False,
                 platform: Optional[str] = None, week_start: Optional[date] = None) -> dict:
    """Ingest every expected delivery, or with platform + week_start rewrite just that one.

    A single-delivery run still reads every file, because campaign spellings and the CPM baseline
    span the platform's other weeks - so it produces exactly what a full run would for that delivery.
    """
    exchange_rates = _load_exchange_rates()
    files_by_slot, ignored_files = discover_deliveries(Path(data_dir))

    # 1. Parse. An unreadable file fails its own delivery, never the run.
    raw_rows_by_slot: dict[tuple, list[dict]] = {}
    parse_error_by_slot: dict[tuple, str] = {}
    for slot, slot_files in files_by_slot.items():
        source_file = slot_files.get("resend") or slot_files.get("original")
        if source_file is None:
            continue
        try:
            raw_rows_by_slot[slot] = PLATFORMS[slot[0]].parse_file(str(source_file))
        except Exception as error:
            parse_error_by_slot[slot] = f"{type(error).__name__}: {error}"

    # 2. Row rules. Campaign names are canonicalized across all of a platform's files.
    spellings_by_platform = {
        platform_key: canonical_names([row for (row_platform, _), rows in raw_rows_by_slot.items()
                                       if row_platform == platform_key for row in rows])
        for platform_key in PLATFORMS
    }
    contexts = {
        (platform_key, week): DeliveryContext(
            platform=PLATFORMS[platform_key].name,
            week_start=week,
            expected_filename=f"{platform_key}_{week}.{PLATFORMS[platform_key].extension}",
            original_file=slot_files.get("original"),
            resend_file=slot_files.get("resend"),
            exchange_rates=exchange_rates,
            canonical_spellings=spellings_by_platform[platform_key],
        )
        for (platform_key, week), slot_files in files_by_slot.items()
    }
    kept_rows_by_slot: dict[tuple, list[dict]] = {}
    row_results_by_slot: dict[tuple, list[CheckResult]] = {}
    for slot, raw_rows in raw_rows_by_slot.items():
        kept_rows_by_slot[slot], row_results_by_slot[slot] = apply_row_rules(raw_rows, contexts[slot])

    # 3. Delivery and file checks. Spend is judged against the platform's median CPM over its other weeks.
    cpm_by_slot = {slot: compute_cpm(rows) for slot, rows in kept_rows_by_slot.items()}
    deliveries = []
    for slot, context in contexts.items():
        platform_key = slot[0]
        other_week_cpms = [cpm for other_slot, cpm in cpm_by_slot.items()
                           if other_slot[0] == platform_key and other_slot != slot and cpm]
        context = replace(context, platform_median_cpm=median(other_week_cpms) if other_week_cpms else None)

        check_results = [delivery_check(context) for delivery_check in DELIVERY_CHECKS]
        raw_rows = raw_rows_by_slot.get(slot, [])
        rows: list[dict] = []
        if slot in parse_error_by_slot:
            check_results.append(CheckResult("file readable", "fail", {"message": parse_error_by_slot[slot]}))
        elif slot in raw_rows_by_slot:
            check_results.append(CheckResult("file readable", "pass", {"message": f"{len(raw_rows)} rows read"}))
            check_results += row_results_by_slot[slot]
            rows = kept_rows_by_slot[slot]
            for file_check in FILE_CHECKS:
                result, rows = file_check(rows, context)
                check_results.append(result)

        deliveries.append({
            "platform":        context.platform,
            "week":            context.week_start.isoformat(),
            "filename":        context.source_file.name if context.source_file else None,
            "status":          classify_health(check_results),
            "check_results":   check_results,
            "rows":            [_metric_fields(row) for row in rows],
            "rows_received":   len(raw_rows),
            "transformations": _transformation_rules(platform_key, raw_rows, context) if slot in raw_rows_by_slot else [],
        })

    if platform or week_start:
        deliveries = [delivery for delivery in deliveries
                      if delivery["platform"] == platform and delivery["week"] == str(week_start)]
        if not deliveries:
            raise LookupError(f"No expected delivery for {platform} week {week_start}")

    summary = {
        "files_processed": sum(1 for delivery in deliveries if delivery["filename"]),
        "rows_written":    0,
        "rows_excluded":   sum(delivery["rows_received"] - len(delivery["rows"]) for delivery in deliveries),
        "deliveries":      [{"platform": delivery["platform"], "week": delivery["week"], "status": delivery["status"],
                             "filename": delivery["filename"], "rows_received": delivery["rows_received"],
                             "rows_loaded": len(delivery["rows"])}
                            for delivery in deliveries],
        "ignored_files":   ignored_files,
        "errors":          [],
    }
    if dry_run:
        summary["rows_written"] = sum(len(delivery["rows"]) for delivery in deliveries)
    else:
        summary["rows_written"], summary["errors"] = _store_deliveries(deliveries, db_url)
    return summary


def _store_deliveries(deliveries: list[dict], db_url: str) -> tuple[int, list[str]]:
    """Delete-then-insert per delivery keeps re-runs idempotent; a failed write only loses that delivery."""
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    rows_written, write_errors = 0, []
    with Session(engine) as session:
        for delivery in deliveries:
            try:
                previous_run = session.query(Delivery).filter_by(
                    platform=delivery["platform"], week_start=delivery["week"]).first()
                if previous_run:
                    session.delete(previous_run)
                    session.flush()
                session.add(Delivery(
                    platform=delivery["platform"],
                    week_start=delivery["week"],
                    filename=delivery["filename"],
                    status=delivery["status"],
                    rows_received=delivery["rows_received"],
                    rows_loaded=len(delivery["rows"]),
                    transformations=delivery["transformations"],
                    checks=[QualityCheck(check_name=result.check_name, outcome=result.outcome, detail_json=result.detail)
                            for result in delivery["check_results"]],
                    metrics=[CampaignMetric(platform=delivery["platform"], **row) for row in delivery["rows"]],
                ))
                session.commit()
                rows_written += len(delivery["rows"])
            except Exception as error:
                session.rollback()
                write_errors.append(f"{delivery['platform']} {delivery['week']}: {error}")
    engine.dispose()
    return rows_written, write_errors
