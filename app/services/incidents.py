from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.models.schemas import (
    AnalyzeResponse,
    ApprovalRecord,
    Diagnosis,
    ExecutionFailure,
    IncidentTimelineResponse,
    PatchProposal,
    SystemStats,
    TimelineEvent,
    WorkflowDryRunResponse,
)
from app.services.diagnoser import DiagnosisEngine
from app.services.patcher import PatchPlanner
from app.services.state_store import SQLiteStateStore
from app.services.validator import PatchValidator
from app.services.workflow_dry_run import WorkflowDryRunEngine


class DryRunRequiredError(ValueError):
    pass


class ApprovalRequiredError(ValueError):
    pass


class IncidentService:
    def __init__(
        self,
        settings: Settings | None = None,
        store: SQLiteStateStore | None = None,
    ):
        self.settings = settings or get_settings()
        self.store = store or SQLiteStateStore(self.settings.state_db_path)
        self.diagnoser = DiagnosisEngine()
        self.patcher = PatchPlanner()
        self.validator = PatchValidator(self.settings.max_patch_operations)
        self.dry_runner = WorkflowDryRunEngine(self.validator)

        # Hot-process caches preserve the simple V0 API while SQLite is the source
        # of truth for restart recovery.
        self.proposals: dict[str, PatchProposal] = {}
        self.proposal_execution_ids: dict[str, str] = {}
        self.dry_runs: dict[str, WorkflowDryRunResponse] = {}
        self.approvals: dict[str, ApprovalRecord] = {}

    def analyze(self, failure: ExecutionFailure) -> AnalyzeResponse:
        diagnosis: Diagnosis = self.diagnoser.diagnose(failure)
        patch = self.patcher.propose(failure, diagnosis)
        incident_id = str(uuid4())
        if patch:
            self.validator.validate(patch)
            self.proposals[patch.proposal_id] = patch
            self.proposal_execution_ids[patch.proposal_id] = failure.execution_id

        # Raw item data and workflow snapshots can contain credentials or customer
        # payloads. They may be used transiently by callers, but never enter durable state.
        durable_failure = failure.model_copy(
            update={"input_snapshot": None, "workflow_snapshot": None}
        )
        self.store.save_incident(incident_id, durable_failure, diagnosis, patch)
        if patch:
            self.store.append_event(
                patch.proposal_id,
                "diagnosed",
                {
                    "failure_class": diagnosis.failure_class,
                    "confidence": diagnosis.confidence,
                    "retry_safe": diagnosis.retry_safe,
                    "workflow_id": failure.workflow_id,
                    "execution_id": failure.execution_id,
                    "patch_operations": len(patch.operations),
                },
            )

        return AnalyzeResponse(
            incident_id=incident_id,
            diagnosis=diagnosis,
            patch=patch,
        )

    def get_proposal(self, proposal_id: str) -> PatchProposal:
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            proposal = self.store.load_proposal(proposal_id)
            if proposal is None:
                raise KeyError(proposal_id)
            self.proposals[proposal_id] = proposal
        return proposal

    def get_execution_id(self, proposal_id: str) -> str:
        self.get_proposal(proposal_id)
        execution_id = self.proposal_execution_ids.get(proposal_id)
        if execution_id is None:
            execution_id = self.store.load_execution_id(proposal_id)
            if execution_id is None:
                raise KeyError(proposal_id)
            self.proposal_execution_ids[proposal_id] = execution_id
        return execution_id

    def get_dry_run(self, proposal_id: str) -> WorkflowDryRunResponse:
        self.get_proposal(proposal_id)
        dry_run = self.dry_runs.get(proposal_id)
        if dry_run is None:
            dry_run = self.store.load_dry_run(proposal_id)
            if dry_run is None:
                raise DryRunRequiredError("A successful dry run is required before approval or apply.")
            self.dry_runs[proposal_id] = dry_run
        return dry_run

    def get_approval(self, proposal_id: str) -> ApprovalRecord:
        self.get_proposal(proposal_id)
        approval = self.approvals.get(proposal_id)
        if approval is None:
            approval = self.store.load_approval(proposal_id)
            if approval is None:
                raise ApprovalRequiredError("Explicit human approval is required before apply.")
            self.approvals[proposal_id] = approval
        return approval

    def dry_run(self, proposal_id: str, workflow: dict[str, Any]) -> WorkflowDryRunResponse:
        proposal = self.get_proposal(proposal_id)
        response, _ = self.dry_runner.dry_run(workflow, proposal)
        self.dry_runs[proposal_id] = response
        self.approvals.pop(proposal_id, None)
        self.store.save_dry_run(proposal_id, response)
        self.store.append_event(
            proposal_id,
            "dry_run_validated",
            {
                "workflow_version_id": response.workflow_version_id,
                "workflow_snapshot_fingerprint": response.workflow_snapshot_fingerprint,
                "target_nodes": response.target_nodes,
                "changes": len(response.changes),
            },
        )
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
            approved_at=datetime.now(UTC),
        )
        self.approvals[proposal_id] = record
        self.store.save_approval(proposal_id, record)
        self.store.append_event(
            proposal_id,
            "approved",
            {
                "approved_by": approved_by,
                "workflow_version_id": dry_run.workflow_version_id,
                "workflow_snapshot_fingerprint": dry_run.workflow_snapshot_fingerprint,
            },
        )
        return record

    def timeline(self, proposal_id: str) -> IncidentTimelineResponse:
        self.get_proposal(proposal_id)
        events = [TimelineEvent.model_validate(item) for item in self.store.load_timeline(proposal_id)]
        return IncidentTimelineResponse(
            proposal_id=proposal_id,
            incident_id=self.store.load_incident_id(proposal_id),
            events=events,
        )

    def stats(self) -> SystemStats:
        return SystemStats.model_validate(self.store.stats())
