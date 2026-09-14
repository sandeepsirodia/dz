from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Delivery
from ..schemas import DeliveryListResponse, DeliveryReportResponse, DeliverySummary, QualityCheckResult

router = APIRouter(prefix="/deliveries", tags=["data health"])


def _summary(delivery: Delivery) -> DeliverySummary:
    return DeliverySummary(
        id=delivery.id,
        platform=delivery.platform,
        week_start=delivery.week_start,
        filename=delivery.filename,
        status=delivery.status,
        rows_received=delivery.rows_received,
        rows_loaded=delivery.rows_loaded,
        rows_excluded=delivery.rows_received - delivery.rows_loaded,
        ingested_at=delivery.ingested_at.isoformat(),
    )


@router.get("", response_model=DeliveryListResponse)
def list_deliveries(db: Session = Depends(get_db)):
    deliveries = db.query(Delivery).order_by(Delivery.platform, Delivery.week_start).all()
    return DeliveryListResponse(deliveries=[_summary(delivery) for delivery in deliveries])


@router.get("/{delivery_id}", response_model=DeliveryReportResponse)
def get_delivery_report(delivery_id: int, db: Session = Depends(get_db)):
    delivery = db.get(Delivery, delivery_id)
    if delivery is None:
        raise HTTPException(status_code=404, detail=f"Delivery {delivery_id} not found")
    return DeliveryReportResponse(
        delivery=_summary(delivery),
        transformations=delivery.transformations,
        checks=[QualityCheckResult(name=check.check_name, outcome=check.outcome, details=check.detail_json)
                for check in delivery.checks],
    )
