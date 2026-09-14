"""Per-platform readers.

Parsers only map each file format onto one raw row shape. They never drop, fix
or coerce values - that happens in checks/row.py, so every defect is recorded
in the quality report before it is cleaned.

Raw row shape:
    source_ref      where the row came from, e.g. "line 23" or "record 4"
    campaign        campaign name exactly as delivered
    date            date string exactly as delivered (LinkedIn: converted from epoch ms)
    spend_amount    spend as delivered, in spend_currency / spend_divisor units
    spend_currency  ISO currency code
    spend_divisor   1, or 1_000_000 when the platform reports micros
    impressions     as delivered
    clicks          as delivered, None when absent
"""
import csv
import json
from datetime import datetime, timezone

META_COLUMNS    = {"campaign_name", "date", "spend_usd", "impressions", "clicks"}
GOOGLE_COLUMNS  = {"Campaign", "Day", "Cost (micros)", "Currency", "Impr.", "Clicks"}
FIRST_DATA_LINE = 2   # line 1 of every CSV is the header


def _read_csv(path: str, required_columns: set[str]) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        missing_columns = required_columns - set(reader.fieldnames or [])
        if missing_columns:
            raise ValueError(f"Missing columns: {', '.join(sorted(missing_columns))}")
        return list(reader)


def parse_meta_file(path: str) -> list[dict]:
    return [{
        "source_ref":     f"line {line_number}",
        "campaign":       record["campaign_name"],
        "date":           record["date"],
        "spend_amount":   record["spend_usd"],
        "spend_currency": "USD",
        "spend_divisor":  1,
        "impressions":    record["impressions"],
        "clicks":         record["clicks"],
    } for line_number, record in enumerate(_read_csv(path, META_COLUMNS), start=FIRST_DATA_LINE)]


def parse_google_file(path: str) -> list[dict]:
    return [{
        "source_ref":     f"line {line_number}",
        "campaign":       record["Campaign"],
        "date":           record["Day"],
        "spend_amount":   record["Cost (micros)"],
        "spend_currency": record["Currency"],
        "spend_divisor":  1_000_000,
        "impressions":    record["Impr."],
        "clicks":         record["Clicks"],
    } for line_number, record in enumerate(_read_csv(path, GOOGLE_COLUMNS), start=FIRST_DATA_LINE)]


def _epoch_ms_to_iso_date(epoch_ms) -> str:
    try:
        return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError, OSError):
        return str(epoch_ms)  # left unparseable so date validation reports the raw value


def parse_linkedin_file(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as json_file:
        records = json.load(json_file)
    if not isinstance(records, list):
        raise ValueError("Expected a JSON array of rows")

    raw_rows = []
    for record_number, record in enumerate(records, start=1):
        record = record if isinstance(record, dict) else {}
        spend = record.get("spend") if isinstance(record.get("spend"), dict) else {}
        raw_rows.append({
            "source_ref":     f"record {record_number}",
            "campaign":       record.get("campaign"),
            "date":           _epoch_ms_to_iso_date(record.get("date_ts")),
            "spend_amount":   spend.get("amount"),
            "spend_currency": spend.get("currency"),
            "spend_divisor":  1,
            "impressions":    record.get("impressions"),
            "clicks":         record.get("clicks"),
        })
    return raw_rows
