import enum
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Integer, String, Float, DateTime, ForeignKey, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


class Platform(str, enum.Enum):
    META     = "Meta Ads"
    GOOGLE   = "Google Ads"
    LINKEDIN = "LinkedIn Ads"


class Delivery(Base):
    """One expected weekly delivery (platform + week), whether or not a file arrived."""
    __tablename__ = "deliveries"
    __table_args__ = (UniqueConstraint("platform", "week_start"),)
    id:              Mapped[int]           = mapped_column(Integer, primary_key=True)
    platform:        Mapped[str]           = mapped_column(String)
    week_start:      Mapped[str]           = mapped_column(String)
    filename:        Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status:          Mapped[str]           = mapped_column(String)
    rows_received:   Mapped[int]           = mapped_column(Integer, default=0)
    rows_loaded:     Mapped[int]           = mapped_column(Integer, default=0)
    transformations: Mapped[list]          = mapped_column(JSON, default=list)   # rules applied to this file's values
    ingested_at:     Mapped[datetime]      = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    checks:  Mapped[list["QualityCheck"]]   = relationship(back_populates="delivery", cascade="all, delete-orphan",
                                                           order_by="QualityCheck.id")
    metrics: Mapped[list["CampaignMetric"]] = relationship(back_populates="delivery", cascade="all, delete-orphan")


class QualityCheck(Base):
    __tablename__ = "quality_checks"
    id:          Mapped[int]  = mapped_column(Integer, primary_key=True)
    delivery_id: Mapped[int]  = mapped_column(ForeignKey("deliveries.id"))
    check_name:  Mapped[str]  = mapped_column(String)
    outcome:     Mapped[str]  = mapped_column(String)
    detail_json: Mapped[dict] = mapped_column(JSON)
    delivery:    Mapped["Delivery"] = relationship(back_populates="checks")


class CampaignMetric(Base):
    __tablename__ = "campaign_metrics"
    __table_args__ = (UniqueConstraint("platform", "campaign", "date"),)
    id:          Mapped[int]           = mapped_column(Integer, primary_key=True)
    delivery_id: Mapped[int]           = mapped_column(ForeignKey("deliveries.id"))
    platform:    Mapped[str]           = mapped_column(String)
    campaign:    Mapped[str]           = mapped_column(String)
    date:        Mapped[str]           = mapped_column(String)
    spend_usd:   Mapped[float]         = mapped_column(Float)
    impressions: Mapped[int]           = mapped_column(Integer)
    clicks:      Mapped[Optional[int]] = mapped_column(Integer, nullable=True)   # null = not reported
    delivery:    Mapped["Delivery"]    = relationship(back_populates="metrics")
