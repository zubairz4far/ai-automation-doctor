from __future__ import annotations

from uuid import uuid4

from app.core.config import get_settings
from app.models.schemas import AnalyzeResponse, ApprovalRecord, Diagnosis, ExecutionFailure, PatchProposal
from app.services.diagnoser import DiagnosisEngine
from app.services.patcher import PatchPlanner
from app.services.validator import PatchValidator


class IncidentService:
    def __init__(self):
        self.diagnoser = DiagnosisEngine()
        self.patcher = PatchPlanner()
        self.validator = PatchValidator(get_settings().max_patch_operations)
        self.proposals: dict[str, PatchProposal] = {}
        self.approvals: dict[str, ApprovalRecord] = {}

    def analyze(self, failure: ExecutionFailure) -> AnalyzeResponse:
        diagnosis: Diagnosis = self.diagnoser.diagnose(failure)
        patch = self.patcher.propose(failure, diagnosis)
        if patch:
            self.validator.validate(patch)
            self.proposals[patch.proposal_id] = patch
        return AnalyzeResponse(
            incident_id=str(uuid4()),
            diagnosis=diagnosis,
            patch=patch,
        )

    def approve(self, proposal_id: str, approved_by: str, note: str | None) -> ApprovalRecord:
        if proposal_id not in self.proposals:
            raise KeyError(proposal_id)
        record = ApprovalRecord(
            proposal_id=proposal_id,
            approved=True,
            approved_by=approved_by,
            note=note,
        )
        self.approvals[proposal_id] = record
        return record
