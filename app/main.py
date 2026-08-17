from fastapi import FastAPI

from app.api.routes import router
from app.core.config import get_settings

settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Durable n8n automation reliability service with privacy-minimized diagnosis, "
        "constrained human-approved remediation, idempotency, and crash-safe recovery."
    ),
)
app.include_router(router)
