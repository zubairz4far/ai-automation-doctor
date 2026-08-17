from functools import lru_cache
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, status

from app.core.config import get_settings
from app.models.schemas import AnalyzeResponse, ApprovalRecord, ApprovalRequest, ExecutionFailure
from app.services.incidents import IncidentService
from app.services.n8n_client import N8NClient
from app.services.n8n_normalizer import N8NExecutionNormalizationError, N8NExecutionNormalizer

router = APIRouter()


@lru_cache
def get_incident_service() -> IncidentService:
    return IncidentService()


@lru_cache
def get_n8n_normalizer() -> N8NExecutionNormalizer:
    return N8NExecutionNormalizer()


@lru_cache
def get_n8n_client() -> N8NClient:
    return N8NClient(get_settings())


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "workflow_mutation_enabled": settings.allow_workflow_mutation,
    }


@router.post("/v1/incidents/analyze", response_model=AnalyzeResponse)
def analyze_failure(failure: ExecutionFailure) -> AnalyzeResponse:
    return get_incident_service().analyze(failure)


@router.post("/v1/incidents/ingest/n8n", response_model=AnalyzeResponse)
def ingest_n8n_execution(payload: dict[str, Any]) -> AnalyzeResponse:
    try:
        failure = get_n8n_normalizer().normalize(payload)
    except N8NExecutionNormalizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return get_incident_service().analyze(failure)


@router.post("/v1/incidents/n8n/{execution_id}/analyze", response_model=AnalyzeResponse)
def analyze_n8n_execution(execution_id: str) -> AnalyzeResponse:
    settings = get_settings()
    if not settings.n8n_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="N8N_API_KEY is not configured.",
        )

    try:
        payload = get_n8n_client().get_execution(execution_id)
        failure = get_n8n_normalizer().normalize(payload)
    except N8NExecutionNormalizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to retrieve the n8n execution.",
        ) from exc

    return get_incident_service().analyze(failure)


@router.post("/v1/patches/{proposal_id}/approve", response_model=ApprovalRecord)
def approve_patch(proposal_id: str, request: ApprovalRequest) -> ApprovalRecord:
    try:
        return get_incident_service().approve(proposal_id, request.approved_by, request.note)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patch proposal not found.",
        ) from exc
