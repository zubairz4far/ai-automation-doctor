import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.models.schemas import ExecutionFailure
from app.services.incidents import DryRunRequiredError, IncidentService
from app.services.remediation import (
    ControlledRemediationService,
    StaleWorkflowError,
    WorkflowVerificationError,
    serialize_workflow_for_update,
)

FIXTURE = Path(__file__).parent / "fixtures/http_retry_workflow.json"


def load_workflow() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


def build_approved_incident(workflow: dict[str, Any]) -> tuple[IncidentService, str]:
    incidents = IncidentService()
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
    proposal_id = analysis.patch.proposal_id
    incidents.dry_run(proposal_id, workflow)
    incidents.approve(proposal_id, "Zubair", "validated retry patch")
    return incidents, proposal_id


class FakeN8N:
    def __init__(
        self,
        workflow: dict[str, Any],
        *,
        allow_mutation: bool = True,
        allow_retry: bool = True,
        persist_exactly: bool = True,
        retry_status: str = "success",
    ):
        self.settings = Settings(
            allow_workflow_mutation=allow_mutation,
            allow_execution_retry=allow_retry,
        )
        self.workflow = deepcopy(workflow)
        self.persist_exactly = persist_exactly
        self.retry_status = retry_status
        self.update_calls: list[dict[str, Any]] = []
        self.retry_calls: list[tuple[str, bool]] = []

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
        self.update_calls.append(
            {
                "workflow": deepcopy(workflow),
                "publish_if_active": publish_if_active,
            }
        )
        updated = deepcopy(workflow)
        updated["id"] = workflow_id
        updated["active"] = True
        updated["versionId"] = "version-next"
        updated["tags"] = []
        if not self.persist_exactly:
            target = next(node for node in updated["nodes"] if node["name"] == "CRM / HTTP Request")
            target.pop("maxTries", None)
        self.workflow = updated
        return deepcopy(updated)

    def retry_execution(
        self,
        execution_id: str,
        *,
        load_workflow: bool = True,
    ) -> dict[str, Any]:
        self.retry_calls.append((execution_id, load_workflow))
        return {"id": "retry-execution-2", "status": self.retry_status}

    def get_execution(self, execution_id: str) -> dict[str, Any]:
        assert execution_id == "retry-execution-2"
        return {"id": execution_id, "workflowId": "workflow-7", "status": self.retry_status}


def test_approval_requires_successful_dry_run():
    incidents = IncidentService()
    analysis = incidents.analyze(
        ExecutionFailure(
            execution_id="e1",
            workflow_id="workflow-7",
            failed_node="CRM / HTTP Request",
            error_message="429 Too Many Requests",
            status_code=429,
        )
    )
    assert analysis.patch is not None

    with pytest.raises(DryRunRequiredError):
        incidents.approve(analysis.patch.proposal_id, "Zubair", None)


def test_new_dry_run_invalidates_previous_approval():
    workflow = load_workflow()
    incidents, proposal_id = build_approved_incident(workflow)
    assert incidents.get_approval(proposal_id).approved is True

    incidents.dry_run(proposal_id, workflow)

    with pytest.raises(ValueError, match="approval"):
        incidents.get_approval(proposal_id)


def test_controlled_remediation_updates_draft_retries_once_and_verifies_success():
    workflow = load_workflow()
    incidents, proposal_id = build_approved_incident(workflow)
    n8n = FakeN8N(workflow)

    result = ControlledRemediationService(incidents, n8n).apply_retry_verify(proposal_id)

    assert result.update_applied is True
    assert result.publish_if_active is False
    assert result.retry_started is True
    assert result.retry_execution_id == "retry-execution-2"
    assert result.verification == "success"
    assert n8n.retry_calls == [("failed-execution-1", True)]
    assert len(n8n.update_calls) == 1
    assert n8n.update_calls[0]["publish_if_active"] is False

    payload = n8n.update_calls[0]["workflow"]
    assert "id" not in payload
    assert "active" not in payload
    assert "versionId" not in payload
    assert "tags" not in payload
    target = next(node for node in payload["nodes"] if node["name"] == "CRM / HTTP Request")
    assert target["retryOnFail"] is True
    assert target["maxTries"] == 3
    assert target["waitBetweenTries"] == 2000
    assert target["credentials"]["httpHeaderAuth"]["id"] == "credential-id-123"


def test_stale_version_blocks_update_and_retry():
    workflow = load_workflow()
    incidents, proposal_id = build_approved_incident(workflow)
    stale = deepcopy(workflow)
    stale["versionId"] = "someone-else-saved"
    n8n = FakeN8N(stale)

    with pytest.raises(StaleWorkflowError, match="version changed"):
        ControlledRemediationService(incidents, n8n).apply_retry_verify(proposal_id)

    assert n8n.update_calls == []
    assert n8n.retry_calls == []


def test_stale_snapshot_blocks_update_even_without_version_change():
    workflow = load_workflow()
    incidents, proposal_id = build_approved_incident(workflow)
    stale = deepcopy(workflow)
    target = next(node for node in stale["nodes"] if node["name"] == "CRM / HTTP Request")
    target["parameters"]["url"] = "https://changed.example.com/leads"
    n8n = FakeN8N(stale)

    with pytest.raises(StaleWorkflowError, match="snapshot changed"):
        ControlledRemediationService(incidents, n8n).apply_retry_verify(proposal_id)

    assert n8n.update_calls == []
    assert n8n.retry_calls == []


def test_retry_gate_is_preflighted_before_any_workflow_write():
    workflow = load_workflow()
    incidents, proposal_id = build_approved_incident(workflow)
    n8n = FakeN8N(workflow, allow_mutation=True, allow_retry=False)

    with pytest.raises(PermissionError, match="ALLOW_EXECUTION_RETRY=false"):
        ControlledRemediationService(incidents, n8n).apply_retry_verify(proposal_id)

    assert n8n.update_calls == []
    assert n8n.retry_calls == []


def test_persistence_mismatch_blocks_retry_after_update():
    workflow = load_workflow()
    incidents, proposal_id = build_approved_incident(workflow)
    n8n = FakeN8N(workflow, persist_exactly=False)

    with pytest.raises(WorkflowVerificationError, match="did not persist"):
        ControlledRemediationService(incidents, n8n).apply_retry_verify(proposal_id)

    assert len(n8n.update_calls) == 1
    assert n8n.retry_calls == []


def test_nonterminal_retry_status_is_reported_as_pending():
    workflow = load_workflow()
    incidents, proposal_id = build_approved_incident(workflow)
    n8n = FakeN8N(workflow, retry_status="running")

    result = ControlledRemediationService(incidents, n8n).apply_retry_verify(proposal_id)

    assert result.verification == "pending"
    assert result.retry_status == "running"


def test_workflow_serializer_strips_read_only_workflow_and_node_fields():
    workflow = load_workflow()
    workflow["createdAt"] = "2026-08-17T00:00:00Z"
    workflow["updatedAt"] = "2026-08-17T00:01:00Z"
    workflow["meta"] = {"instanceId": "secret-ish-metadata"}
    workflow["nodes"][0]["createdAt"] = "2026-08-17T00:00:00Z"
    workflow["nodes"][0]["updatedAt"] = "2026-08-17T00:01:00Z"

    payload = serialize_workflow_for_update(workflow)

    for forbidden in ("id", "active", "versionId", "createdAt", "updatedAt", "tags", "meta"):
        assert forbidden not in payload
    assert "createdAt" not in payload["nodes"][0]
    assert "updatedAt" not in payload["nodes"][0]
