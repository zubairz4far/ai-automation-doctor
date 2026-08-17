from fastapi import FastAPI

from app.api.routes import router
from app.core.config import get_settings

settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.4.0",
    description=(
        "Diagnose n8n failures, validate constrained workflow patches, and execute "
        "human-approved stale-safe remediation behind explicit mutation and retry gates."
    ),
)
app.include_router(router)
