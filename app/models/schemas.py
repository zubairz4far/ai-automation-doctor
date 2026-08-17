from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class FailureClass(StrEnum):
    AUTH = "authentication"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    NETWORK = "network"
    DATA_MAPPING = "data_mapping"
    WEBHOOK = "webhook"
    CONFIGURATION = "configuration"
    UNKNOWN = "unknown"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExecutionFailure(BaseModel):
    execution_id: str
    workflow_id: str
    workflow_name: str | None = None
    failed_node: str | None = None
    node_type: str | None = None
    error_message: str
    error_stack: str | None = None
    error_code: str | None = None
    status_code: int | None = None
    input_snapshot: dict[str, Any] | None = None
    workflow_snapshot: dict[str, Any] | None = None


class Diagnosis(BaseModel):
    failure_class: FailureClass
    confidence: float = Field(ge=0, le=1)
    root_cause: str
    evidence: list[str]
    recommended_action: str
    retry_safe: bool


class PatchOperation(BaseModel):
    op: Literal["replace", "add"]
    path: str
    value: Any
    reason: str


class PatchProposal(BaseModel):
    proposal_id: str
    workflow_id: str
    diagnosis: Diagnosis
    operations: list[PatchOperation]
    risk: RiskLevel
    requires_human_approval: bool = True
    auto_apply_allowed: bool = False
    validation_notes: list[str] = Field(default_factory=list)


class AnalyzeResponse(BaseModel):
    incident_id: str
    diagnosis: Diagnosis
    patch: PatchProposal | None = None


class ApprovalRequest(BaseModel):
    approved_by: str = Field(min_length=2, max_length=120)
    note: str | None = Field(default=None, max_length=500)


class ApprovalRecord(BaseModel):
    proposal_id: str
    approved: bool
    approved_by: str
    note: str | None = None
    workflow_version_id: str | None = None
    workflow_snapshot_fingerprint: str
    approved_at: datetime


class WorkflowDryRunRequest(BaseModel):
    workflow: dict[str, Any]


class WorkflowPatchChange(BaseModel):
    node_name: str
    path: str
    before: Any = None
    after: Any
    reason: str


class WorkflowDryRunResponse(BaseModel):
    proposal_id: str
    workflow_id: str
    valid: bool = True
    target_nodes: list[str]
    changes: list[WorkflowPatchChange]
    workflow_version_id: str | None = None
    workflow_snapshot_fingerprint: str
    structural_fingerprint_before: str
    structural_fingerprint_after: str
    validation_notes: list[str]


class RemediationResponse(BaseModel):
    proposal_id: str
    workflow_id: str
    original_execution_id: str
    workflow_version_before: str | None = None
    workflow_version_after: str | None = None
    update_applied: bool
    publish_if_active: bool = False
    retry_started: bool
    retry_execution_id: str | None = None
    retry_status: str | None = None
    verification: Literal["success", "failure", "pending"]
    idempotent_replay: bool = False
    resumed_from_stage: str | None = None
    evidence: list[str] = Field(default_factory=list)


class TimelineEvent(BaseModel):
    event_type: str
    created_at: datetime
    details: dict[str, Any] = Field(default_factory=dict)


class IncidentTimelineResponse(BaseModel):
    proposal_id: str
    incident_id: str | None = None
    events: list[TimelineEvent]


class SystemStats(BaseModel):
    incidents: int
    proposals: int
    approvals: int
    remediations: int
    completed_remediations: int
