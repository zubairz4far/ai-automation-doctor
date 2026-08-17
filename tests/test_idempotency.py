import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.models.schemas import ExecutionFailure
from app.services.incidents import IncidentService
from app.services.remediation import (
    ControlledRemediationService,
    RetryRecoveryRequiredError,
    workflow_definition_fingerprint,
)
from app.services.state_store import SQLiteStateStore

FIXTURE = Path(__file__).parent / "fixtures/http_retry_workflow.json"


def load_workflow() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


def build_approved(tmp_path) -> tuple[IncidentService, str, dict[str, Any], Settings]:
    db_path = tmp_path / "doctor.db"
    settings = Settings(
        state_db_path=str(db_path),
        allow_workflow_mutation=True,
        allow_execution_retry=True,
    )
    incidents = IncidentService(settings=settings, store=SQLiteStateStore(str(db_path)))
    analysis = incidents.analyze(
        ExecutionFailure(
            execution_id="failed-execution-1",
            workflow_id="workflow-7",
            failed_node="CRM / HTTP Request",
            node_type="n8n-nodes-base.httpRequest",
            error_message="429 Too Many Requests",
            status_code=429,
        )
    )
    assert analysis.patch is not None
    workflow = load_workflow()
    proposal_id = analysis.patch.proposal_id
    incidents.dry_run(proposal_id, workflow)
    incidents.approve(proposal_id, "operator", "approved")
    return incidents, proposal_id, workflow, settings


class RecoveryN8N:
    def __init__(
        self,
        workflow: dict[str, Any],
        settings: Settings,
        *,
        existing_retry: dict[str, Any] | None = None,
    ):
        self.workflow = deepcopy(workflow)
        self.settings = settings
        self.existing_retry = existing_retry
        self.update_calls = 0
        self.retry_calls = 0
        self.retry_status = "success"

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        assert workflow_id == "workflow-7"
        return deepcopy(self.workflow)

    def update_workflow(
        self,
        workflow_id: str,
        workflow: dict[str, Any],
        *,
        publish_if_active: bool = False,
    ) -> dict[str, Any]:
        assert workflow_id == "workflow-7"
        assert publish_if_active is False
        self.update_calls += 1
        persisted = deepcopy(workflow)
        persisted.update(
            {
                "id": workflow_id,
                "active": True,
                "versionId": "version-next",
                "tags": [],
            }
        )
        self.workflow = persisted
        return deepcopy(persisted)

    def retry_execution(
        self,
        execution_id: str,
        *,
        load_workflow: bool = True,
    ) -> dict[str, Any]:
        assert execution_id == "failed-execution-1"
        assert load_workflow is True
        self.retry_calls += 1
        self.existing_retry = {
            "id": "retry-execution-2",
            "workflowId": "workflow-7",
            "retryOf": execution_id,
            "status": self.retry_status,
        }
        return deepcopy(self.existing_retry)

    def find_retry_execution(
        self,
        original_execution_id: str,
        workflow_id: str,
        limit: int = 100,
    ) -> dict[str, Any] | None:
        assert original_execution_id == "failed-execution-1"
        assert workflow_id == "workflow-7"
        assert limit == 100
        return deepcopy(self.existing_retry)

    def get_execution(self, execution_id: str) -> dict[str, Any]:
        assert self.existing_retry is not None
        assert execution_id == self.existing_retry["id"]
        return deepcopy(self.existing_retry)


def patched_workflow(incidents: IncidentService, proposal_id: str, workflow: dict[str, Any]):
    proposal = incidents.get_proposal(proposal_id)
    _, patched = incidents.dry_runner.dry_run(workflow, proposal)
    patched["versionId"] = "version-next"
    return patched


def seed_stage(
    incidents: IncidentService,
    proposal_id: str,
    workflow: dict[str, Any],
    stage: str,
) -> None:
    proposal = incidents.get_proposal(proposal_id)
    _, patched = incidents.dry_runner.dry_run(workflow, proposal)
    expected = workflow_definition_fingerprint(patched)
    claim = incidents.store.claim_remediation(proposal_id, 30)
    owner = str(claim["lease_owner"])
    incidents.store.set_remediation_stage(
        proposal_id,
        owner,
        "workflow_update_starting",
        expected_update_fingerprint=expected,
        workflow_version_before="version-abc",
    )
    if stage in {"workflow_verified", "retry_starting"}:
        incidents.store.set_remediation_stage(proposal_id, owner, "workflow_verified")
    if stage == "retry_starting":
        incidents.store.set_remediation_stage(proposal_id, owner, "retry_starting")
    incidents.store.release_remediation(proposal_id, owner, "simulated process stop")


def test_completed_remediation_is_replayed_without_second_side_effect(tmp_path):
    incidents, proposal_id, workflow, settings = build_approved(tmp_path)
    n8n = RecoveryN8N(workflow, settings)

    first = ControlledRemediationService(incidents, n8n).apply_retry_verify(proposal_id)
    assert first.verification == "success"
    assert n8n.update_calls == 1
    assert n8n.retry_calls == 1

    restarted = IncidentService(
        settings=settings,
        store=SQLiteStateStore(settings.state_db_path),
    )
    second = ControlledRemediationService(restarted, n8n).apply_retry_verify(proposal_id)

    assert second.idempotent_replay is True
    assert second.retry_execution_id == first.retry_execution_id
    assert n8n.update_calls == 1
    assert n8n.retry_calls == 1


def test_crash_after_workflow_update_is_recovered_without_second_update(tmp_path):
    incidents, proposal_id, workflow, settings = build_approved(tmp_path)
    seed_stage(incidents, proposal_id, workflow, "workflow_update_starting")
    n8n = RecoveryN8N(patched_workflow(incidents, proposal_id, workflow), settings)

    result = ControlledRemediationService(incidents, n8n).apply_retry_verify(proposal_id)

    assert result.verification == "success"
    assert result.resumed_from_stage == "workflow_update_starting"
    assert n8n.update_calls == 0
    assert n8n.retry_calls == 1


def test_crash_after_retry_is_recovered_from_retryof_without_duplicate_retry(tmp_path):
    incidents, proposal_id, workflow, settings = build_approved(tmp_path)
    seed_stage(incidents, proposal_id, workflow, "retry_starting")
    existing = {
        "id": "retry-existing",
        "workflowId": "workflow-7",
        "retryOf": "failed-execution-1",
        "status": "success",
    }
    n8n = RecoveryN8N(
        patched_workflow(incidents, proposal_id, workflow),
        settings,
        existing_retry=existing,
    )

    result = ControlledRemediationService(incidents, n8n).apply_retry_verify(proposal_id)

    assert result.retry_execution_id == "retry-existing"
    assert result.verification == "success"
    assert n8n.update_calls == 0
    assert n8n.retry_calls == 0


def test_ambiguous_retry_recovery_fails_closed_instead_of_retrying_again(tmp_path):
    incidents, proposal_id, workflow, settings = build_approved(tmp_path)
    seed_stage(incidents, proposal_id, workflow, "retry_starting")
    n8n = RecoveryN8N(patched_workflow(incidents, proposal_id, workflow), settings)

    with pytest.raises(RetryRecoveryRequiredError, match="duplicate execution"):
        ControlledRemediationService(incidents, n8n).apply_retry_verify(proposal_id)

    assert n8n.update_calls == 0
    assert n8n.retry_calls == 0
