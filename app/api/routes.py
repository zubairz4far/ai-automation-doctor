from functools import lru_cache
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, status

from app.core.config import get_settings
from app.models.schemas import (
    AnalyzeResponse,
    ApprovalRecord,
    ApprovalRequest,
    ExecutionFailure,
    RemediationResponse,
    WorkflowDryRunRequest,
    WorkflowDryRunResponse,
)
from app.services.incidents import (
    ApprovalRequiredError,
    DryRunRequiredError,
    IncidentService,
)
from app.services.n8n_client import N8NClient
from app.services.n8n_normalizer import N8NExecutionNormalizationError, N8NExecutionNormalizer
from app.services.remediation import (
    ControlledRemediationService,
    RemediationError,
    StaleWorkflowError,
    WorkflowVerificationError,
)
from app.services.workflow_dry_run import WorkflowDryRunError

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


@lru_cache
def get_remediation_service() -> ControlledRemediationService:
    return ControlledRemediationService(get_incident_service(), get_n8n_client())


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "workflow_mutation_enabled": settings.allow_workflow_mutation,
        "execution_retry_enabled": settings.allow_execution_retry,
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


@router.post(
    "/v1/patches/{proposal_id}/dry-run",
    response_model=WorkflowDryRunResponse,
)
def dry_run_patch(proposal_id: str, request: WorkflowDryRunRequest) -> WorkflowDryRunResponse:
    try:
        return get_incident_service().dry_run(proposal_id, request.workflow)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patch proposal not found.",
        ) from exc
    except WorkflowDryRunError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.post(
    "/v1/patches/{proposal_id}/dry-run/n8n",
    response_model=WorkflowDryRunResponse,
)
def dry_run_current_n8n_workflow(proposal_id: str) -> WorkflowDryRunResponse:
    settings = get_settings()
    if not settings.n8n_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="N8N_API_KEY is not configured.",
        )

    try:
        proposal = get_incident_service().get_proposal(proposal_id)
        workflow = get_n8n_client().get_workflow(proposal.workflow_id)
        return get_incident_service().dry_run(proposal_id, workflow)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patch proposal not found.",
        ) from exc
    except WorkflowDryRunError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to retrieve the current n8n workflow.",
        ) from exc


@router.post("/v1/patches/{proposal_id}/approve", response_model=ApprovalRecord)
def approve_patch(proposal_id: str, request: ApprovalRequest) -> ApprovalRecord:
    try:
        return get_incident_service().approve(proposal_id, request.approved_by, request.note)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patch proposal not found.",
        ) from exc
    except DryRunRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post(
    "/v1/patches/{proposal_id}/apply-retry",
    response_model=RemediationResponse,
)
def apply_retry_patch(proposal_id: str) -> RemediationResponse:
    try:
        return get_remediation_service().apply_retry_verify(proposal_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patch proposal not found.",
        ) from exc
    except (DryRunRequiredError, ApprovalRequiredError, StaleWorkflowError, RemediationError) as exc:
        if isinstance(exc, WorkflowVerificationError):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="n8n remediation request failed; no further retry was attempted.",
        ) from exc
