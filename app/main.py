import hmac

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import get_settings
from app.demo import router as demo_router

settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="1.3.0",
    description=(
        "Durable n8n automation reliability service with privacy-minimized diagnosis, "
        "bounded AI advisory analysis, constrained human-approved remediation, "
        "idempotency, crash-safe recovery, and a read-only interactive demo."
    ),
)

PUBLIC_DEMO_PATHS = {
    "/demo",
    "/v1/demo/analyze",
    "/health",
    "/ready",
}


@app.middleware("http")
async def enforce_runtime_boundaries(request: Request, call_next):
    if settings.public_demo_only and request.url.path not in PUBLIC_DEMO_PATHS:
        return JSONResponse(
            status_code=404,
            content={"detail": "This deployment exposes only the read-only public demo."},
        )

    sensitive = request.method == "POST" and request.url.path.endswith(("/approve", "/apply-retry"))
    side_effects_enabled = settings.allow_workflow_mutation or settings.allow_execution_retry
    if sensitive and side_effects_enabled:
        if not settings.operator_token:
            return JSONResponse(
                status_code=503,
                content={"detail": "OPERATOR_TOKEN is required when side-effect gates are enabled."},
            )
        supplied = request.headers.get("x-doctor-operator-token", "")
        if not hmac.compare_digest(supplied, settings.operator_token):
            return JSONResponse(
                status_code=401,
                content={"detail": "Valid operator credentials are required."},
            )
    return await call_next(request)


app.include_router(router)
app.include_router(demo_router)
