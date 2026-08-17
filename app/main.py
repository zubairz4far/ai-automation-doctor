from fastapi import FastAPI

from app.api.routes import router
from app.core.config import get_settings

settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.3.0",
    description="Ingest n8n failures, diagnose root causes, and dry-run human-approved safe workflow patches.",
)
app.include_router(router)
