from dataclasses import dataclass
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Delivery, Platform, QualityCheck
from ..schemas import CampaignMetricsResponse, CampaignTraceResponse, PlatformMetricsResponse, TraceWeek

router = APIRouter(prefix="/metrics", tags=["metrics"])

# CTR and CPC only count rows that reported clicks, so a missing clicks value
# (LinkedIn sometimes omits it) never reads as zero engagement.
_AGGREGATE_COLUMNS = (
    "SUM(spend_usd) AS spend, SUM(impressions) AS impressions, "
    "COALESCE(SUM(clicks), 0) AS clicks, "
    "COALESCE(SUM(CASE WHEN clicks IS NOT NULL THEN impressions END), 0) AS clicked_impressions, "
    "COALESCE(SUM(CASE WHEN clicks IS NOT NULL THEN spend_usd END), 0) AS clicked_spend"
)
_SUM_FIELDS = ("spend", "impressions", "clicks", "clicked_impressions", "clicked_spend")


@dataclass
class MetricFilters:
    platform:  Optional[Platform]
    date_from: Optional[date]
    date_to:   Optional[date]


def metric_filters(platform: Optional[Platform] = None, date_from: Optional[date] = None,
                   date_to: Optional[date] = None) -> MetricFilters:
    """Filters shared by the metrics endpoints. Unknown platforms, bad dates and reversed ranges return 422."""
    if date_from and date_to and date_from > date_to:
        raise RequestValidationError([{
            "type": "value_error", "loc": ("query", "date_to"),
            "msg": "date_to must be on or after date_from", "input": str(date_to),
        }])
    return MetricFilters(platform, date_from, date_to)


def _aggregate(db: Session, group_by: str, filters: MetricFilters) -> list[dict]:
    """Sums per group. group_by is an internal constant, never user input."""
    conditions, params = [], {}
    if filters.platform:
        conditions.append("platform = :platform")
        params["platform"] = filters.platform.value
    if filters.date_from:
        conditions.append("date >= :date_from")
        params["date_from"] = str(filters.date_from)
    if filters.date_to:
        conditions.append("date <= :date_to")
        params["date_to"] = str(filters.date_to)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = (f"SELECT {group_by}, {_AGGREGATE_COLUMNS} FROM campaign_metrics {where_clause} "
           f"GROUP BY {group_by} ORDER BY spend DESC")
    return [dict(result_row._mapping) for result_row in db.execute(text(sql), params)]


def _kpis_from_sums(sums: dict) -> dict:
    return {
        "spend_usd":   round(sums["spend"], 2),
        "impressions": sums["impressions"],
        "clicks":      sums["clicks"],
        "ctr":         sums["clicks"] / sums["clicked_impressions"] if sums["clicked_impressions"] else None,
        "cpc":         sums["clicked_spend"] / sums["clicks"] if sums["clicks"] else None,
    }


def _totals_across(groups: list[dict]) -> dict:
    return _kpis_from_sums({field: sum(group[field] for group in groups) for field in _SUM_FIELDS})


@router.get("/campaigns", response_model=CampaignMetricsResponse)
def get_campaign_metrics(filters: MetricFilters = Depends(metric_filters), db: Session = Depends(get_db)):
    campaign_groups = _aggregate(db, "platform, campaign", filters)
    return {
        "campaigns": [{"platform": group["platform"], "campaign": group["campaign"], **_kpis_from_sums(group)}
                      for group in campaign_groups],
        "totals":    _totals_across(campaign_groups),
    }


@router.get("/platforms", response_model=PlatformMetricsResponse)
def get_platform_metrics(filters: MetricFilters = Depends(metric_filters), db: Session = Depends(get_db)):
    platform_groups = _aggregate(db, "platform", filters)
    return {
        "platforms": [{"platform": group["platform"], **_kpis_from_sums(group)} for group in platform_groups],
        "totals":    _totals_across(platform_groups),
    }


@router.get("/campaigns/trace", response_model=CampaignTraceResponse)
def trace_campaign(platform: Platform, campaign: str, db: Session = Depends(get_db)):
    """Where a campaign's numbers come from: each source delivery, the rules applied to it, and its quality notes."""
    week_rows = db.execute(text(
        "SELECT delivery.id AS delivery_id, delivery.week_start, delivery.filename, "
        "       delivery.status AS delivery_status, SUM(metric.spend_usd) AS spend_usd, "
        "       SUM(metric.impressions) AS impressions, COALESCE(SUM(metric.clicks), 0) AS clicks "
        "FROM campaign_metrics AS metric JOIN deliveries AS delivery ON metric.delivery_id = delivery.id "
        "WHERE metric.platform = :platform AND metric.campaign = :campaign "
        "GROUP BY delivery.id "
        "ORDER BY delivery.week_start"
    ), {"platform": platform.value, "campaign": campaign}).fetchall()

    delivery_ids = [week.delivery_id for week in week_rows]
    rules_by_delivery = {delivery.id: delivery.transformations
                         for delivery in db.query(Delivery).filter(Delivery.id.in_(delivery_ids))}
    notes_by_delivery: dict[int, list[str]] = {}
    failing_checks = (db.query(QualityCheck)
                      .filter(QualityCheck.delivery_id.in_(delivery_ids), QualityCheck.outcome != "pass")
                      .order_by(QualityCheck.id))
    for check in failing_checks:
        notes_by_delivery.setdefault(check.delivery_id, []).append(
            f"{check.check_name}: {check.detail_json.get('message', '')}")

    weeks = [
        TraceWeek(
            **{**week._mapping, "spend_usd": round(week.spend_usd, 2)},
            transformations=rules_by_delivery.get(week.delivery_id, []),
            quality_notes=notes_by_delivery.get(week.delivery_id, []),
        )
        for week in week_rows
    ]
    return CampaignTraceResponse(platform=platform.value, campaign=campaign, weeks=weeks)
