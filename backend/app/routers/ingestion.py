import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

from ..ingest.pipeline import run_pipeline
from ..schemas import IngestionRequest, IngestionResult

router = APIRouter(tags=["ingestion"])

DATA_DIR = os.getenv("DATA_DIR", str(Path(__file__).parents[3] / "data" / "deliveries"))


@router.post("/ingestions", response_model=IngestionResult)
def run_ingestion(scope: Optional[IngestionRequest] = None):
    """Run ingestion synchronously and return the run summary.

    No body: every delivery is (re-)ingested. `{"platform", "week_start"}`: only that delivery is rewritten.
    """
    db_url = os.getenv("DB_URL", "sqlite:///./campaign_hub.db")
    platform = scope.platform.value if scope and scope.platform else None
    week_start = scope.week_start if scope else None
    try:
        return run_pipeline(DATA_DIR, db_url, platform=platform, week_start=week_start)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error))
