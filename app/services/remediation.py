from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.models.schemas import RemediationResponse
from app.services.incidents import IncidentService
from app.services.n8n_client import N8NClient
from app.services.workflow_dry_run import WorkflowDryRunEngine


class RemediationError(RuntimeError):
    pass


class StaleWorkflowError(RemediationError):
    pass


class WorkflowVerificationError(RemediationError):
    pass


_WORKFLOW_WRITE_FIELDS = (
    "name",
    "description",
    "nodes",
    "connections",
    "nodeGroups",
    "settings",
    "staticData",
    "pinData",
)
_REQUIRED_WORKFLOW_WRITE_FIELDS = ("name", "nodes", "connections", "settings")
_NODE_READ_ONLY_FIELDS = {"createdAt", "updatedAt"}
_FAILURE_STATUSES = {"error", "crashed", "canceled", "cancelled"}
_SUCCESS_STATUSES = {"success"}


def serialize_workflow_for_update(workflow: dict[str, Any]) -> dict[str, Any]:
    """Build the narrow public-API update body instead of replaying a GET response."""
    missing = [key for key in _REQUIRED_WORKFLOW_WRITE_FIELDS if key not in workflow]
    if missing:
        raise RemediationError(f"Workflow is missing required update fields: {', '.join(missing)}")

    payload: dict[str, Any] = {}
    for key in _WORKFLOW_WRITE_FIELDS:
        if key not in workflow:
            continue
        payload[key] = deepcopy(workflow[key])

    nodes = payload.get("nodes")
    if not isinstance(nodes, list):
        raise RemediationError("Workflow nodes must be an array before update.")
    for node in nodes:
        if not isinstance(node, dict):
            raise RemediationError("Every workflow node must be an object before update.")
        for read_only_field in _NODE_READ_ONLY_FIELDS:
            node.pop(read_only_field, None)

    return payload


class ControlledRemediationService:
    """Apply one approved patch, verify persistence, retry once, and report the result."""

    def __init__(self, incidents: IncidentService, n8n: N8NClient):
        self.incidents = incidents
        self.n8n = n8n
        self.dry_runner: WorkflowDryRunEngine = incidents.dry_runner

    def apply_retry_verify(self, proposal_id: str) -> RemediationResponse:
        proposal = self.incidents.get_proposal(proposal_id)
        original_execution_id = self.incidents.get_execution_id(proposal_id)
        dry_run = self.incidents.get_dry_run(proposal_id)
        approval = self.incidents.get_approval(proposal_id)

        # Preflight both side-effect gates before the first write. This prevents a
        # partially remediated state where a workflow is changed but retry is blocked.
        if not self.n8n.settings.allow_workflow_mutation:
            raise PermissionError("Workflow mutation is disabled by ALLOW_WORKFLOW_MUTATION=false.")
        if not self.n8n.settings.allow_execution_retry:
            raise PermissionError("Execution retry is disabled by ALLOW_EXECUTION_RETRY=false.")

        if approval.workflow_snapshot_fingerprint != dry_run.workflow_snapshot_fingerprint:
            raise RemediationError("Approval is not bound to the latest validated dry-run snapshot.")
        if approval.workflow_version_id != dry_run.workflow_version_id:
            raise RemediationError("Approval is not bound to the latest validated workflow version.")

        current = self.n8n.get_workflow(proposal.workflow_id)
        current_version = self.dry_runner.workflow_version_id(current)
        current_fingerprint = self.dry_runner.snapshot_fingerprint(current)

        if dry_run.workflow_version_id is not None and current_version != dry_run.workflow_version_id:
            raise StaleWorkflowError("Workflow version changed after dry run; a new dry run is required.")
        if current_fingerprint != dry_run.workflow_snapshot_fingerprint:
            raise StaleWorkflowError("Workflow snapshot changed after dry run; a new dry run is required.")

        # Rebuild the patch server-side from the current n8n snapshot. Never trust a
        # client-supplied patched workflow body for an actual write.
        fresh_dry_run, patched = self.dry_runner.dry_run(current, proposal)
        if fresh_dry_run.workflow_snapshot_fingerprint != dry_run.workflow_snapshot_fingerprint:
            raise StaleWorkflowError("Workflow changed while rebuilding the approved patch.")

        update_body = serialize_workflow_for_update(patched)
        self.n8n.update_workflow(
            proposal.workflow_id,
            update_body,
            publish_if_active=False,
        )

        persisted = self.n8n.get_workflow(proposal.workflow_id)
        persisted_body = serialize_workflow_for_update(persisted)
        if persisted_body != update_body:
            raise WorkflowVerificationError(
                "n8n did not persist the exact approved workflow definition; retry was not started."
            )
        if self.dry_runner.structural_fingerprint(persisted) != dry_run.structural_fingerprint_before:
            raise WorkflowVerificationError(
                "Protected workflow structure changed after update; retry was not started."
            )

        retry = self.n8n.retry_execution(original_execution_id, load_workflow=True)
        retry_execution_id_value = retry.get("id")
        if retry_execution_id_value is None:
            raise WorkflowVerificationError("n8n retry response did not include an execution ID.")
        retry_execution_id = str(retry_execution_id_value)

        verified_execution = self.n8n.get_execution(retry_execution_id)
        retry_status = str(
            verified_execution.get("status") or retry.get("status") or "unknown"
        ).lower()
        if retry_status in _SUCCESS_STATUSES:
            verification = "success"
        elif retry_status in _FAILURE_STATUSES:
            verification = "failure"
        else:
            verification = "pending"

        return RemediationResponse(
            proposal_id=proposal_id,
            workflow_id=proposal.workflow_id,
            original_execution_id=original_execution_id,
            workflow_version_before=current_version,
            workflow_version_after=self.dry_runner.workflow_version_id(persisted),
            update_applied=True,
            publish_if_active=False,
            retry_started=True,
            retry_execution_id=retry_execution_id,
            retry_status=retry_status,
            verification=verification,
            evidence=[
                "Approval matched the latest stored dry-run version and snapshot fingerprint.",
                "The current n8n workflow matched the approved snapshot before mutation.",
                "The patch was rebuilt server-side from the current workflow.",
                "The workflow update was saved with publishIfActive=false.",
                "The persisted writable workflow definition matched the approved update body.",
                "Protected workflow structure matched the pre-update fingerprint.",
                "The failed execution was retried once with loadWorkflow=true.",
                f"Retry verification status: {retry_status}.",
            ],
        )
