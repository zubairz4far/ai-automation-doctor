import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.models.schemas import ExecutionFailure, PatchOperation, PatchProposal
from app.services.diagnoser import DiagnosisEngine
from app.services.patcher import PatchPlanner
from app.services.validator import PatchValidationError, PatchValidator
from app.services.workflow_dry_run import WorkflowDryRunEngine, WorkflowDryRunError

FIXTURE = Path(__file__).parent / "fixtures/http_retry_workflow.json"


def load_workflow() -> dict:
    return json.loads(FIXTURE.read_text())


def make_rate_limit_proposal() -> PatchProposal:
    failure = ExecutionFailure(
        execution_id="execution-1",
        workflow_id="workflow-7",
        failed_node="CRM / HTTP Request",
        node_type="n8n-nodes-base.httpRequest",
        error_message="429 Too Many Requests",
        status_code=429,
    )
    diagnosis = DiagnosisEngine().diagnose(failure)
    proposal = PatchPlanner().propose(failure, diagnosis)
    assert proposal is not None
    return proposal


def test_dry_run_changes_only_allowlisted_retry_options():
    workflow = load_workflow()
    original = deepcopy(workflow)
    proposal = make_rate_limit_proposal()

    response, patched = WorkflowDryRunEngine().dry_run(workflow, proposal)

    assert workflow == original
    assert response.valid is True
    assert response.target_nodes == ["CRM / HTTP Request"]
    assert len(response.changes) == 3
    assert response.structural_fingerprint_before == response.structural_fingerprint_after

    target = next(node for node in patched["nodes"] if node["name"] == "CRM / HTTP Request")
    original_target = next(
        node for node in original["nodes"] if node["name"] == "CRM / HTTP Request"
    )
    assert target["parameters"]["options"]["retryOnFail"] is True
    assert target["parameters"]["options"]["maxTries"] == 3
    assert target["parameters"]["options"]["waitBetweenTries"] == 2000
    assert target["credentials"] == original_target["credentials"]
    assert target["id"] == original_target["id"]
    assert target["type"] == original_target["type"]
    assert target["typeVersion"] == original_target["typeVersion"]
    assert patched["connections"] == original["connections"]
    assert patched["settings"] == original["settings"]


def test_patch_planner_escapes_slash_in_node_name():
    proposal = make_rate_limit_proposal()

    assert all("CRM ~1 HTTP Request" in operation.path for operation in proposal.operations)


def test_dry_run_rejects_workflow_id_mismatch():
    workflow = load_workflow()
    workflow["id"] = "different-workflow"

    with pytest.raises(WorkflowDryRunError, match="workflow ID"):
        WorkflowDryRunEngine().dry_run(workflow, make_rate_limit_proposal())


def test_dry_run_rejects_duplicate_node_names():
    workflow = load_workflow()
    duplicate = deepcopy(workflow["nodes"][1])
    duplicate["id"] = "duplicate-id"
    workflow["nodes"].append(duplicate)

    with pytest.raises(WorkflowDryRunError, match="not unique"):
        WorkflowDryRunEngine().dry_run(workflow, make_rate_limit_proposal())


def test_validator_rejects_credential_mutation_path():
    proposal = make_rate_limit_proposal()
    proposal.operations = [
        PatchOperation(
            op="add",
            path="/nodes/CRM ~1 HTTP Request/credentials/httpHeaderAuth/id",
            value="replacement-secret-id",
            reason="unsafe test",
        )
    ]

    with pytest.raises(PatchValidationError, match="Unsupported mutation path"):
        PatchValidator().validate(proposal)


def test_validator_rejects_excessive_retry_count():
    proposal = make_rate_limit_proposal()
    proposal.operations = [
        PatchOperation(
            op="add",
            path="/nodes/CRM ~1 HTTP Request/parameters/options/maxTries",
            value=99,
            reason="unsafe test",
        )
    ]

    with pytest.raises(PatchValidationError, match="between 1 and 5"):
        PatchValidator().validate(proposal)


def test_replace_requires_existing_option():
    proposal = make_rate_limit_proposal()
    proposal.operations = [
        PatchOperation(
            op="replace",
            path="/nodes/CRM ~1 HTTP Request/parameters/options/maxTries",
            value=2,
            reason="replace test",
        )
    ]

    with pytest.raises(WorkflowDryRunError, match="requires an existing option"):
        WorkflowDryRunEngine().dry_run(load_workflow(), proposal)
