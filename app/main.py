from fastapi import FastAPI

from app.api.routes import router
from app.core.config import get_settings

settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description="Ingest n8n execution failures, diagnose root causes, and propose human-approved safe patches.",
)
app.include_router(router)
