from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, model_validator

from .models import Platform


# ── Metrics ──────────────────────────────────────────────────────────────────

class MetricTotals(BaseModel):
    spend_usd:   float
    impressions: int
    clicks:      int
    ctr:         Optional[float]   # null when no impressions came with a clicks value
    cpc:         Optional[float]   # null when clicks = 0


class CampaignMetrics(MetricTotals):
    platform: str
    campaign: str


class PlatformMetrics(MetricTotals):
    platform: str


class CampaignMetricsResponse(BaseModel):
    campaigns: list[CampaignMetrics]
    totals:    MetricTotals


class PlatformMetricsResponse(BaseModel):
    platforms: list[PlatformMetrics]
    totals:    MetricTotals


class TraceWeek(BaseModel):
    delivery_id:     int
    week_start:      str
    filename:        Optional[str]
    delivery_status: str
    spend_usd:       float
    impressions:     int
    clicks:          int
    transformations: list[str]   # rules that turned the file's values into these numbers
    quality_notes:   list[str]   # non-passing checks for that delivery (exclusions, corrections, gaps)


class CampaignTraceResponse(BaseModel):
    platform: str
    campaign: str
    weeks:    list[TraceWeek]


# ── Deliveries (data health) ─────────────────────────────────────────────────

class DeliverySummary(BaseModel):
    id:            int
    platform:      str
    week_start:    str
    filename:      Optional[str]
    status:        str
    rows_received: int
    rows_loaded:   int
    rows_excluded: int
    ingested_at:   str


class DeliveryListResponse(BaseModel):
    deliveries: list[DeliverySummary]


class QualityCheckResult(BaseModel):
    name:    str
    outcome: str
    details: dict[str, Any]


class DeliveryReportResponse(BaseModel):
    delivery:        DeliverySummary
    transformations: list[str]
    checks:          list[QualityCheckResult]


# ── Ingestion ────────────────────────────────────────────────────────────────

class IngestionRequest(BaseModel):
    """Empty body re-ingests everything; platform + week_start re-ingests one delivery."""
    platform:   Optional[Platform] = None
    week_start: Optional[date]     = None

    @model_validator(mode="after")
    def platform_and_week_given_together(self):
        if (self.platform is None) != (self.week_start is None):
            raise ValueError("platform and week_start must be given together")
        return self


class IngestionResult(BaseModel):
    files_processed: int
    rows_written:    int
    rows_excluded:   int
    deliveries:      list[dict]
    ignored_files:   list[str]
    errors:          list[str]
