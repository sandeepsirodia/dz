import json
import shutil
from datetime import date

import pytest
from sqlalchemy import create_engine, text

from app.ingest.pipeline import run_pipeline


def _query(db_url: str, sql: str) -> list:
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    with engine.connect() as connection:
        result_rows = connection.execute(text(sql)).fetchall()
    engine.dispose()
    return result_rows


def test_idempotency(tmp_db, real_data_dir):
    """Running twice produces the same rows, the same spend and the same quality results."""
    snapshot_sql = ("SELECT (SELECT COUNT(*) FROM campaign_metrics), (SELECT COUNT(*) FROM deliveries), "
                    "(SELECT COUNT(*) FROM quality_checks), (SELECT ROUND(SUM(spend_usd), 2) FROM campaign_metrics)")
    run_pipeline(real_data_dir, tmp_db)
    first_run = _query(tmp_db, snapshot_sql)
    run_pipeline(real_data_dir, tmp_db)
    assert _query(tmp_db, snapshot_sql) == first_run


def test_real_data_defects_are_surfaced(tmp_db, real_data_dir):
    """The Health page must show every defect planted in the provided files - and nothing else."""
    run_pipeline(real_data_dir, tmp_db)
    flagged_checks_by_delivery: dict = {}
    for platform, week, check_name in _query(tmp_db,
            "SELECT d.platform, d.week_start, q.check_name FROM quality_checks q "
            "JOIN deliveries d ON d.id = q.delivery_id WHERE q.outcome != 'pass'"):
        flagged_checks_by_delivery.setdefault((platform, week), set()).add(check_name)

    assert flagged_checks_by_delivery == {
        ("Meta Ads", "2026-06-01"):     {"date validity", "date format", "campaign name", "coverage"},
        ("Meta Ads", "2026-06-08"):     {"spend sanity"},
        ("Meta Ads", "2026-06-15"):     {"campaign name", "missing clicks"},
        ("Meta Ads", "2026-06-22"):     {"required values", "coverage"},
        ("Google Ads", "2026-06-01"):   {"duplicate rows"},
        ("Google Ads", "2026-06-15"):   {"duplicate delivery"},
        ("LinkedIn Ads", "2026-06-08"): {"missing clicks"},
        ("LinkedIn Ads", "2026-06-22"): {"delivery presence"},
    }


def test_meta_cents_week_is_corrected(tmp_db, real_data_dir):
    run_pipeline(real_data_dir, tmp_db)
    meta_spend_by_week = dict(_query(tmp_db,
        "SELECT d.week_start, SUM(m.spend_usd) FROM campaign_metrics m "
        "JOIN deliveries d ON d.id = m.delivery_id WHERE d.platform = 'Meta Ads' GROUP BY d.week_start"))
    assert meta_spend_by_week["2026-06-08"] == pytest.approx(4800.70)
    assert meta_spend_by_week["2026-06-08"] < 2 * meta_spend_by_week["2026-06-15"]


def test_google_micros_duplicates_and_resend(tmp_db, real_data_dir):
    run_pipeline(real_data_dir, tmp_db)
    rows_by_file = dict(_query(tmp_db,
        "SELECT d.filename, COUNT(*) FROM campaign_metrics m JOIN deliveries d ON d.id = m.delivery_id "
        "WHERE d.platform = 'Google Ads' GROUP BY d.filename"))
    assert rows_by_file["google_ads_2026-06-01.csv"] == 35          # 43 rows minus 8 exact duplicates
    assert rows_by_file["google_ads_2026-06-15_resend.csv"] == 35   # resend used, original not double-counted
    assert "google_ads_2026-06-15.csv" not in rows_by_file
    search_brand_spend = _query(tmp_db, "SELECT SUM(spend_usd) FROM campaign_metrics "
                                        "WHERE platform = 'Google Ads' AND campaign = 'Search - Brand'")[0][0]
    assert 1_000 < search_brand_spend < 100_000


def test_missing_clicks_stored_as_null(tmp_db, real_data_dir):
    """5 LinkedIn 06-08 records without a clicks key + 3 Meta 06-15 rows with a blank clicks cell."""
    run_pipeline(real_data_dir, tmp_db)
    assert _query(tmp_db, "SELECT COUNT(*) FROM campaign_metrics WHERE clicks IS NULL")[0][0] == 8


def test_deliveries_record_volume_and_transformation_rules(tmp_db, real_data_dir):
    run_pipeline(real_data_dir, tmp_db)
    by_slot = {f"{platform} {week}": (received, loaded, json.loads(rules))
               for platform, week, received, loaded, rules in _query(tmp_db,
                   "SELECT platform, week_start, rows_received, rows_loaded, transformations FROM deliveries")}
    assert by_slot["Meta Ads 2026-06-01"][:2] == (35, 34)
    assert by_slot["Google Ads 2026-06-01"][:2] == (43, 35)
    assert by_slot["LinkedIn Ads 2026-06-22"] == (0, 0, [])
    assert "Cost (micros): divided by 1,000,000" in by_slot["Google Ads 2026-06-15"][2]
    assert "google_ads_2026-06-15_resend.csv used in place of google_ads_2026-06-15.csv" in by_slot["Google Ads 2026-06-15"][2]
    assert "EUR -> USD at 1.08" in by_slot["LinkedIn Ads 2026-06-08"][2]


def test_missing_delivery_is_a_clean_fail(tmp_db, real_data_dir):
    """LinkedIn 06-22 fails on presence alone - no knock-on noise from other checks."""
    run_pipeline(real_data_dir, tmp_db)
    check_rows = _query(tmp_db,
        "SELECT d.status, d.filename, q.check_name, q.outcome FROM deliveries d "
        "JOIN quality_checks q ON q.delivery_id = d.id "
        "WHERE d.platform = 'LinkedIn Ads' AND d.week_start = '2026-06-22'")
    assert {(status, filename) for status, filename, _, _ in check_rows} == {("fail", None)}
    assert {(check_name, outcome) for _, _, check_name, outcome in check_rows} == {
        ("delivery presence", "fail"), ("duplicate delivery", "pass")}


def test_single_delivery_reingestion_rewrites_only_that_delivery(tmp_db, real_data_dir):
    run_pipeline(real_data_dir, tmp_db)
    ids_before = dict(_query(tmp_db, "SELECT platform || ' ' || week_start, id FROM deliveries"))

    summary = run_pipeline(real_data_dir, tmp_db, platform="Meta Ads", week_start=date(2026, 6, 8))

    ids_after = dict(_query(tmp_db, "SELECT platform || ' ' || week_start, id FROM deliveries"))
    assert {slot for slot in ids_before if ids_before[slot] != ids_after[slot]} == {"Meta Ads 2026-06-08"}
    assert summary["rows_written"] == 35
    assert _query(tmp_db, "SELECT COUNT(*), ROUND(SUM(spend_usd), 2) FROM campaign_metrics")[0] == (367, 54277.3)


def test_reingesting_an_unexpected_delivery_is_rejected(tmp_db, real_data_dir):
    with pytest.raises(LookupError):
        run_pipeline(real_data_dir, tmp_db, platform="Meta Ads", week_start=date(2026, 7, 6))


def test_week_missing_for_every_platform_is_still_expected(tmp_db, fixture_dir, tmp_path):
    data_dir = tmp_path / "deliveries"
    data_dir.mkdir()
    shutil.copy(f"{fixture_dir}/meta_ads_2026-06-01.csv", data_dir / "meta_ads_2026-06-01.csv")
    shutil.copy(f"{fixture_dir}/meta_ads_2026-06-01.csv", data_dir / "meta_ads_2026-06-15.csv")

    summary = run_pipeline(str(data_dir), tmp_db, dry_run=True)
    assert {delivery["week"] for delivery in summary["deliveries"]} == {"2026-06-01", "2026-06-08", "2026-06-15"}
    assert {delivery["status"] for delivery in summary["deliveries"] if delivery["week"] == "2026-06-08"} == {"fail"}


def test_bad_row_does_not_abort_file(tmp_db, fixture_dir):
    """Fixture has 5 rows, one with June 31: 4 land, and the exclusion is on record."""
    summary = run_pipeline(fixture_dir, tmp_db)
    assert _query(tmp_db, "SELECT COUNT(*) FROM campaign_metrics")[0][0] == 4
    assert _query(tmp_db, "SELECT outcome FROM quality_checks WHERE check_name = 'date validity'")[0][0] == "warn"
    assert set(summary["ignored_files"]) == {"google_sample.csv", "linkedin_sample.json"}


def test_unreadable_file_fails_only_its_delivery(tmp_db, fixture_dir, tmp_path):
    data_dir = tmp_path / "deliveries"
    data_dir.mkdir()
    shutil.copy(f"{fixture_dir}/meta_ads_2026-06-01.csv", data_dir)
    (data_dir / "google_ads_2026-06-01.csv").write_text("foo,bar\n1,2\n")

    summary = run_pipeline(str(data_dir), tmp_db)
    status_by_platform = {delivery["platform"]: delivery["status"] for delivery in summary["deliveries"]}
    assert status_by_platform["Google Ads"] == "fail"
    assert summary["rows_written"] == 4
    readable_outcomes = _query(tmp_db, "SELECT outcome FROM quality_checks WHERE check_name = 'file readable'")
    assert ("fail",) in readable_outcomes
