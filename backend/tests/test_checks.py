from dataclasses import replace
from datetime import date

import pytest

from app.ingest.checks import row as row_rules_module
from app.ingest.checks.delivery import check_delivery_presence, check_duplicate_delivery
from app.ingest.checks.file import check_coverage, check_date_format, check_duplicate_rows, check_spend_sanity
from app.ingest.checks.row import RowRule, apply_row_rules, canonical_names
from app.ingest.checks.types import CheckResult, DeliveryContext
from app.ingest.pipeline import classify_health

BASE_CONTEXT = DeliveryContext(platform="Meta Ads", week_start=date(2026, 6, 1),
                               expected_filename="meta_ads_2026-06-01.csv",
                               exchange_rates={"USD": 1.0, "EUR": 1.08})


def _raw_row(campaign="Summer Sale", row_date="06/01/2026", spend_amount="100.00", impressions="1000",
             clicks="10", spend_currency="USD", spend_divisor=1, source_ref="line 2"):
    return dict(source_ref=source_ref, campaign=campaign, date=row_date, spend_amount=spend_amount,
                spend_currency=spend_currency, spend_divisor=spend_divisor, impressions=impressions, clicks=clicks)


def _apply_rules(raw_rows):
    context = replace(BASE_CONTEXT, canonical_spellings=canonical_names(raw_rows))
    kept_rows, check_results = apply_row_rules(raw_rows, context)
    return kept_rows, {result.check_name: result for result in check_results}


# ── Row rules ────────────────────────────────────────────────────────────────

def test_clean_rows_pass_every_rule():
    kept_rows, results = _apply_rules([_raw_row(), _raw_row(row_date="06/02/2026")])
    assert len(kept_rows) == 2
    assert all(result.outcome == "pass" for result in results.values())


def test_impossible_and_out_of_week_dates_excluded():
    kept_rows, results = _apply_rules([_raw_row(row_date="06/31/2026"), _raw_row(row_date="06/09/2026"), _raw_row()])
    assert len(kept_rows) == 1
    assert results["date validity"].detail["examples"] == [
        "line 2: Summer Sale '06/31/2026' is not a valid date",
        "line 2: Summer Sale 2026-06-09 is outside the week of 2026-06-01",
    ]


def test_campaign_names_normalized_to_majority_spelling():
    raw_rows = [_raw_row("Brand Awareness Q2"), _raw_row("Brand Awareness Q2  ", row_date="06/02/2026"),
                _raw_row("brand awareness q2", row_date="06/03/2026")]
    kept_rows, results = _apply_rules(raw_rows)
    assert {row["campaign"] for row in kept_rows} == {"Brand Awareness Q2"}
    assert results["campaign name"].detail["count"] == 2


@pytest.mark.parametrize("invalid_fields", [
    {"spend_amount": "-111.41"}, {"spend_amount": ""}, {"impressions": "abc"},
    {"spend_currency": "GBP"}, {"clicks": "-1"},
])
def test_invalid_values_excluded(invalid_fields):
    kept_rows, results = _apply_rules([_raw_row(**invalid_fields)])
    assert kept_rows == []
    assert results["required values"].outcome == "warn"


def test_clicks_over_impressions_excluded():
    kept_rows, results = _apply_rules([_raw_row(clicks="1500", impressions="1000")])
    assert kept_rows == []
    assert results["clicks vs impressions"].outcome == "warn"


def test_missing_clicks_kept_as_null():
    kept_rows, results = _apply_rules([_raw_row(clicks=None)])
    assert kept_rows[0]["clicks"] is None
    assert results["missing clicks"].outcome == "warn"


def test_micros_and_eur_conversion():
    kept_rows, _ = _apply_rules([_raw_row(spend_amount="117410000", spend_divisor=1_000_000),
                                 _raw_row(spend_amount="92.37", spend_currency="EUR", row_date="06/02/2026")])
    assert kept_rows[0]["spend_usd"] == pytest.approx(117.41)
    assert kept_rows[1]["spend_usd"] == pytest.approx(92.37 * 1.08)


def test_new_row_rule_needs_no_refactoring(monkeypatch):
    """A teammate adds a check by writing one function and registering it - nothing else changes."""
    def zero_impressions(row, context):
        return "no impressions" if row["impressions"] == 0 else None

    extra_rule = RowRule("zero impressions", "{count} row(s) with zero impressions", False, zero_impressions)
    monkeypatch.setattr(row_rules_module, "ROW_RULES", [*row_rules_module.ROW_RULES, extra_rule])
    kept_rows, results = _apply_rules([_raw_row(impressions="0", clicks="0"), _raw_row(row_date="06/02/2026")])
    assert len(kept_rows) == 2
    assert results["zero impressions"].outcome == "warn"
    assert results["zero impressions"].detail["count"] == 1


# ── File checks ──────────────────────────────────────────────────────────────

def _kept_row(campaign="A", day=1, spend_usd=10.0, impressions=3000, date_format="MM/DD/YYYY", source_ref="line 2"):
    return {"source_ref": source_ref, "campaign": campaign, "date": date(2026, 6, day), "date_format": date_format,
            "spend_usd": spend_usd, "impressions": impressions, "clicks": 1}


def test_minority_date_format_flagged():
    rows = [_kept_row(day=1), _kept_row(day=2), _kept_row(day=3, date_format="YYYY-MM-DD", source_ref="line 9")]
    result, _ = check_date_format(rows, BASE_CONTEXT)
    assert result.detail["examples"] == ["line 9: YYYY-MM-DD (file uses MM/DD/YYYY)"]


def test_exact_duplicates_dropped():
    result, unique_rows = check_duplicate_rows([_kept_row(), _kept_row(source_ref="line 3")], BASE_CONTEXT)
    assert len(unique_rows) == 1
    assert result.detail["examples"] == ["line 3: A 2026-06-01 exact duplicate"]


def test_coverage_reports_missing_campaign_day():
    result, _ = check_coverage([_kept_row("A", 1), _kept_row("A", 2), _kept_row("B", 1)], BASE_CONTEXT)
    assert result.outcome == "warn"
    assert result.detail["examples"] == ["B 2026-06-02"]


def test_coverage_fails_when_nothing_usable():
    assert check_coverage([], BASE_CONTEXT)[0].outcome == "fail"


def test_spend_in_cents_is_corrected():
    rows = [_kept_row(spend_usd=17334.0, impressions=50_000) for _ in range(5)]   # CPM ~$347
    result, corrected_rows = check_spend_sanity(rows, replace(BASE_CONTEXT, platform_median_cpm=3.4))
    assert result.outcome == "warn" and result.detail["corrected"]
    assert corrected_rows[0]["spend_usd"] == pytest.approx(173.34)


def test_spend_spike_without_cents_signature_is_flagged_not_changed():
    rows = [_kept_row(spend_usd=20.5, impressions=1000)]                          # CPM $20.50, ~6x
    result, stored_rows = check_spend_sanity(rows, replace(BASE_CONTEXT, platform_median_cpm=3.4))
    assert result.outcome == "warn" and "corrected" not in result.detail
    assert stored_rows[0]["spend_usd"] == 20.5


def test_spend_in_line_or_without_baseline_passes():
    assert check_spend_sanity([_kept_row()], replace(BASE_CONTEXT, platform_median_cpm=3.4))[0].outcome == "pass"
    assert check_spend_sanity([_kept_row()], BASE_CONTEXT)[0].outcome == "pass"


# ── Delivery checks ──────────────────────────────────────────────────────────

def test_missing_delivery_fails_with_expected_filename():
    result = check_delivery_presence(replace(BASE_CONTEXT, expected_filename="linkedin_ads_2026-06-22.json"))
    assert result.outcome == "fail"
    assert result.detail["expected_filename"] == "linkedin_ads_2026-06-22.json"


def test_two_files_for_one_week_warn_even_when_identical(tmp_path):
    original_file, resend_file = tmp_path / "g.csv", tmp_path / "g_resend.csv"
    original_file.write_text("a,b\n1,2\n")
    resend_file.write_text("a,b\n1,2\n")
    two_files = replace(BASE_CONTEXT, original_file=original_file, resend_file=resend_file)
    assert check_duplicate_delivery(two_files).outcome == "warn"
    assert check_duplicate_delivery(two_files).detail["identical"] is True
    resend_file.write_text("a,b\n1,3\n")
    assert check_duplicate_delivery(two_files).detail["identical"] is False
    assert check_duplicate_delivery(replace(BASE_CONTEXT, original_file=original_file)).outcome == "pass"


def test_classify_health():
    def result(outcome):
        return CheckResult("any check", outcome, {})

    assert classify_health([result("pass"), result("warn"), result("fail")]) == "fail"
    assert classify_health([result("pass"), result("warn")]) == "warn"
    assert classify_health([result("pass")]) == "pass"
