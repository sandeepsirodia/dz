import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from app.db import Base


@pytest.fixture(scope="module")
def client(tmp_path_factory, real_data_dir_module):
    from sqlalchemy.orm import sessionmaker
    db_path = tmp_path_factory.mktemp("db") / "test.db"
    db_url  = f"sqlite:///{db_path}"
    engine  = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    from app.ingest.pipeline import run_pipeline
    run_pipeline(real_data_dir_module, db_url)

    from app.main import app
    from app.db import get_db

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def ingestion_db(monkeypatch, tmp_path):
    """POST /api/ingestions writes through DB_URL, so point it at a throwaway database."""
    monkeypatch.setenv("DB_URL", f"sqlite:///{tmp_path}/ingestion.db")


def test_service_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


# ── POST /api/ingestions ─────────────────────────────────────────────────────

def test_full_ingestion_is_idempotent(client, ingestion_db):
    first_run  = client.post("/api/ingestions")
    second_run = client.post("/api/ingestions")
    assert first_run.status_code == 200
    assert first_run.json()["rows_written"] == second_run.json()["rows_written"] == 367
    assert first_run.json()["errors"] == []


def test_single_delivery_reingestion(client, ingestion_db):
    response = client.post("/api/ingestions", json={"platform": "Meta Ads", "week_start": "2026-06-08"})
    assert response.status_code == 200
    assert [delivery["week"] for delivery in response.json()["deliveries"]] == ["2026-06-08"]
    assert response.json()["rows_written"] == 35


@pytest.mark.parametrize("scope, expected_status", [
    ({"platform": "Meta Ads"}, 422),                                  # week_start missing
    ({"platform": "TikTok Ads", "week_start": "2026-06-08"}, 422),    # unknown platform
    ({"platform": "Meta Ads", "week_start": "2026-07-06"}, 404),      # no such delivery slot
])
def test_ingestion_scope_errors(client, ingestion_db, scope, expected_status):
    assert client.post("/api/ingestions", json=scope).status_code == expected_status


# ── GET /api/metrics/* ───────────────────────────────────────────────────────

def test_campaign_metrics_lists_every_campaign(client):
    response = client.get("/api/metrics/campaigns")
    assert response.status_code == 200
    assert len(response.json()["campaigns"]) == 13
    assert response.json()["totals"]["spend_usd"] == 54277.3


def test_platform_filter(client):
    campaigns = client.get("/api/metrics/campaigns?platform=Google+Ads").json()["campaigns"]
    assert {campaign["platform"] for campaign in campaigns} == {"Google Ads"}
    assert len(campaigns) == 5


@pytest.mark.parametrize("query", ["platform=TikTok+Ads", "date_from=not-a-date"])
def test_invalid_filters_rejected(client, query):
    assert client.get(f"/api/metrics/campaigns?{query}").status_code == 422


def test_reversed_date_range_rejected(client):
    response = client.get("/api/metrics/campaigns?date_from=2026-06-30&date_to=2026-06-01")
    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == "date_to must be on or after date_from"


def test_date_range_filter(client):
    first_week = client.get("/api/metrics/campaigns?date_from=2026-06-01&date_to=2026-06-07").json()
    assert 0 < first_week["totals"]["spend_usd"] < 54277.3


def test_date_range_without_data_returns_empty(client):
    response = client.get("/api/metrics/campaigns?date_from=2020-01-01&date_to=2020-01-07")
    assert response.status_code == 200
    assert response.json()["campaigns"] == []
    assert response.json()["totals"] == {"spend_usd": 0, "impressions": 0, "clicks": 0, "ctr": None, "cpc": None}


def test_ctr_and_cpc_ignore_rows_without_clicks():
    from app.routers.metrics import _kpis_from_sums
    # 1,000 impressions total but only 500 came from rows that reported clicks
    kpis = _kpis_from_sums({"spend": 100.0, "impressions": 1000, "clicks": 10,
                            "clicked_impressions": 500, "clicked_spend": 50.0})
    assert kpis["ctr"] == pytest.approx(0.02)
    assert kpis["cpc"] == pytest.approx(5.0)
    no_clicks = _kpis_from_sums({"spend": 1.0, "impressions": 10, "clicks": 0,
                                 "clicked_impressions": 0, "clicked_spend": 0})
    assert no_clicks["cpc"] is None


def test_platform_metrics_match_campaign_totals(client):
    by_platform = client.get("/api/metrics/platforms").json()
    by_campaign = client.get("/api/metrics/campaigns").json()
    assert len(by_platform["platforms"]) == 3
    assert by_platform["totals"] == by_campaign["totals"]


def test_campaign_trace_shows_deliveries_rules_and_notes(client):
    weeks = {week["week_start"]: week for week in
             client.get("/api/metrics/campaigns/trace?platform=Meta+Ads&campaign=Summer+Sale").json()["weeks"]}
    assert len(weeks) == 5
    cents_week = weeks["2026-06-08"]
    assert cents_week["filename"] == "meta_ads_2026-06-08.csv"
    assert cents_week["delivery_status"] == "warn"
    assert cents_week["spend_usd"] < 3 * weeks["2026-06-15"]["spend_usd"]
    assert "spend_usd: taken as USD" in cents_week["transformations"]
    assert any(note.startswith("spend sanity: Spend looks reported in cents") for note in cents_week["quality_notes"])


def test_trace_unknown_campaign_returns_empty(client):
    response = client.get("/api/metrics/campaigns/trace?platform=Meta+Ads&campaign=Nonexistent")
    assert response.status_code == 200
    assert response.json()["weeks"] == []


# ── GET /api/deliveries ──────────────────────────────────────────────────────

def _find_delivery(client, platform, week_start):
    return next(delivery for delivery in client.get("/api/deliveries").json()["deliveries"]
                if delivery["platform"] == platform and delivery["week_start"] == week_start)


def test_deliveries_list_every_expected_slot(client):
    deliveries = client.get("/api/deliveries").json()["deliveries"]
    assert len(deliveries) == 15
    assert {delivery["status"] for delivery in deliveries} == {"pass", "warn", "fail"}
    missing = _find_delivery(client, "LinkedIn Ads", "2026-06-22")
    assert (missing["status"], missing["filename"], missing["rows_received"]) == ("fail", None, 0)
    assert _find_delivery(client, "Google Ads", "2026-06-15")["status"] == "warn"


def test_delivery_report_says_what_is_wrong_and_how_badly(client):
    meta_first_week = _find_delivery(client, "Meta Ads", "2026-06-01")
    report = client.get(f"/api/deliveries/{meta_first_week['id']}").json()
    assert (report["delivery"]["rows_received"], report["delivery"]["rows_loaded"],
            report["delivery"]["rows_excluded"]) == (35, 34, 1)
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["date validity"]["outcome"] == "warn"
    assert checks["date validity"]["details"]["examples"] == ["line 23: App Install Push '06/31/2026' is not a valid date"]
    assert "date: MM/DD/YYYY (ISO also accepted) -> ISO date" in report["transformations"]


def test_unknown_delivery_returns_404(client):
    response = client.get("/api/deliveries/99999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Delivery 99999 not found"}
