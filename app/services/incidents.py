from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.config import get_settings
from app.models.schemas import (
    AnalyzeResponse,
    ApprovalRecord,
    Diagnosis,
    ExecutionFailure,
    PatchProposal,
    WorkflowDryRunResponse,
)
from app.services.diagnoser import DiagnosisEngine
from app.services.patcher import PatchPlanner
from app.services.validator import PatchValidator
from app.services.workflow_dry_run import WorkflowDryRunEngine


class DryRunRequiredError(ValueError):
    pass


class ApprovalRequiredError(ValueError):
    pass


class IncidentService:
    def __init__(self):
        settings = get_settings()
        self.diagnoser = DiagnosisEngine()
        self.patcher = PatchPlanner()
        self.validator = PatchValidator(settings.max_patch_operations)
        self.dry_runner = WorkflowDryRunEngine(self.validator)
        self.proposals: dict[str, PatchProposal] = {}
        self.proposal_execution_ids: dict[str, str] = {}
        self.dry_runs: dict[str, WorkflowDryRunResponse] = {}
        self.approvals: dict[str, ApprovalRecord] = {}

    def analyze(self, failure: ExecutionFailure) -> AnalyzeResponse:
        diagnosis: Diagnosis = self.diagnoser.diagnose(failure)
        patch = self.patcher.propose(failure, diagnosis)
        if patch:
            self.validator.validate(patch)
            self.proposals[patch.proposal_id] = patch
            self.proposal_execution_ids[patch.proposal_id] = failure.execution_id
        return AnalyzeResponse(
            incident_id=str(uuid4()),
            diagnosis=diagnosis,
            patch=patch,
        )

    def get_proposal(self, proposal_id: str) -> PatchProposal:
        if proposal_id not in self.proposals:
            raise KeyError(proposal_id)
        return self.proposals[proposal_id]

    def get_execution_id(self, proposal_id: str) -> str:
        self.get_proposal(proposal_id)
        if proposal_id not in self.proposal_execution_ids:
            raise KeyError(proposal_id)
        return self.proposal_execution_ids[proposal_id]

    def get_dry_run(self, proposal_id: str) -> WorkflowDryRunResponse:
        self.get_proposal(proposal_id)
        if proposal_id not in self.dry_runs:
            raise DryRunRequiredError("A successful dry run is required before approval or apply.")
        return self.dry_runs[proposal_id]

    def get_approval(self, proposal_id: str) -> ApprovalRecord:
        self.get_proposal(proposal_id)
        if proposal_id not in self.approvals:
            raise ApprovalRequiredError("Explicit human approval is required before apply.")
        return self.approvals[proposal_id]

    def dry_run(self, proposal_id: str, workflow: dict[str, Any]) -> WorkflowDryRunResponse:
        proposal = self.get_proposal(proposal_id)
        response, _ = self.dry_runner.dry_run(workflow, proposal)
        self.dry_runs[proposal_id] = response
        # A new validation snapshot invalidates approval of any older snapshot.
        self.approvals.pop(proposal_id, None)
        return response

    def approve(self, proposal_id: str, approved_by: str, note: str | None) -> ApprovalRecord:
        dry_run = self.get_dry_run(proposal_id)
        record = ApprovalRecord(
            proposal_id=proposal_id,
            approved=True,
            approved_by=approved_by,
            note=note,
            workflow_version_id=dry_run.workflow_version_id,
            workflow_snapshot_fingerprint=dry_run.workflow_snapshot_fingerprint,
            approved_at=datetime.now(timezone.utc),
        )
        self.approvals[proposal_id] = record
        return record
