import json
from pathlib import Path

import pytest

from app.ingest.parsers import parse_google_file, parse_linkedin_file, parse_meta_file

FIXTURES = Path(__file__).parent / "fixtures"


def test_meta_keeps_every_row_raw():
    """Nothing is dropped or fixed at parse time, so the checks can see every defect."""
    raw_rows = parse_meta_file(str(FIXTURES / "meta_ads_2026-06-01.csv"))
    assert len(raw_rows) == 5
    assert raw_rows[2]["date"] == "06/31/2026"
    assert raw_rows[3]["campaign"] == "brand awareness q2"
    assert raw_rows[0]["source_ref"] == "line 2"


def test_google_spend_marked_as_micros():
    raw_rows = parse_google_file(str(FIXTURES / "google_sample.csv"))
    assert len(raw_rows) == 4                          # duplicate still present
    assert raw_rows[0]["spend_amount"] == "117410000"
    assert raw_rows[0]["spend_divisor"] == 1_000_000


def test_linkedin_timestamp_currency_and_missing_clicks():
    raw_rows = parse_linkedin_file(str(FIXTURES / "linkedin_sample.json"))
    assert raw_rows[0]["date"] == "2026-06-01"
    assert raw_rows[0]["spend_currency"] == "EUR"
    assert raw_rows[1]["clicks"] is None


def test_csv_missing_column_raises(tmp_path):
    broken_file = tmp_path / "google_ads_2026-06-01.csv"
    broken_file.write_text("Campaign,Day,Currency,Impr.,Clicks\nX,2026-06-01,USD,1,1\n")
    with pytest.raises(ValueError, match="Cost"):
        parse_google_file(str(broken_file))


def test_linkedin_bad_timestamp_left_for_validation(tmp_path):
    bad_timestamp_file = tmp_path / "linkedin_ads_2026-06-01.json"
    bad_timestamp_file.write_text(json.dumps([{"campaign": "X", "date_ts": "oops",
                                               "spend": {"amount": "1", "currency": "EUR"}, "impressions": 1}]))
    assert parse_linkedin_file(str(bad_timestamp_file))[0]["date"] == "oops"
