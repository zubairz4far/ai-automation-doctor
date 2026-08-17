from functools import lru_cache

from fastapi import APIRouter, HTTPException, status

from app.core.config import get_settings
from app.models.schemas import AnalyzeResponse, ApprovalRecord, ApprovalRequest, ExecutionFailure
from app.services.incidents import IncidentService

router = APIRouter()


@lru_cache
def get_incident_service() -> IncidentService:
    return IncidentService()


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


@router.post("/v1/patches/{proposal_id}/approve", response_model=ApprovalRecord)
def approve_patch(proposal_id: str, request: ApprovalRequest) -> ApprovalRecord:
    try:
        return get_incident_service().approve(proposal_id, request.approved_by, request.note)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patch proposal not found.",
        ) from exc
