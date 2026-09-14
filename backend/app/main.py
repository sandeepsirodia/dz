from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import deliveries, ingestion, metrics

app = FastAPI(title="Campaign Data Hub")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingestion.router,  prefix="/api")
app.include_router(metrics.router,    prefix="/api")
app.include_router(deliveries.router, prefix="/api")


@app.get("/api/health", tags=["service"])
def service_health():
    """Liveness of the API itself. Data health lives under /api/deliveries."""
    return {"status": "ok"}
