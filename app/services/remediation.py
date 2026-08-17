from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from app.models.schemas import RemediationResponse
from app.services.incidents import IncidentService
from app.services.n8n_client import N8NClient
from app.services.state_store import RemediationLeaseError
from app.services.workflow_dry_run import WorkflowDryRunEngine


class RemediationError(RuntimeError):
    pass


class StaleWorkflowError(RemediationError):
    pass


class WorkflowVerificationError(RemediationError):
    pass


class RemediationInProgressError(RemediationError):
    pass


class RetryRecoveryRequiredError(RemediationError):
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


def workflow_definition_fingerprint(workflow: dict[str, Any]) -> str:
    writable = serialize_workflow_for_update(workflow)
    encoded = json.dumps(writable, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


class ControlledRemediationService:
    """Crash-resumable apply → verify → retry with idempotency and fail-closed recovery."""

    def __init__(self, incidents: IncidentService, n8n: N8NClient):
        self.incidents = incidents
        self.n8n = n8n
        self.dry_runner: WorkflowDryRunEngine = incidents.dry_runner
        self.store = incidents.store
        self.lease_seconds = incidents.settings.remediation_lease_seconds

    def apply_retry_verify(self, proposal_id: str) -> RemediationResponse:
        try:
            state = self.store.claim_remediation(proposal_id, self.lease_seconds)
        except RemediationLeaseError as exc:
            raise RemediationInProgressError(str(exc)) from exc

        if state.get("response_json"):
            completed = RemediationResponse.model_validate_json(state["response_json"])
            return completed.model_copy(
                update={"idempotent_replay": True, "resumed_from_stage": "completed"}
            )

        owner = str(state["lease_owner"])
        resumed_from_stage = str(state.get("stage") or "claimed")
        finished = False
        try:
            response = self._run(
                proposal_id,
                owner,
                state,
                resumed_from_stage=None if resumed_from_stage == "claimed" else resumed_from_stage,
            )
            self.store.complete_remediation(proposal_id, owner, response)
            self.store.append_event(
                proposal_id,
                "remediation_completed",
                {
                    "verification": response.verification,
                    "retry_execution_id": response.retry_execution_id,
                    "resumed_from_stage": response.resumed_from_stage,
                },
            )
            finished = True
            return response
        finally:
            if not finished:
                self.store.release_remediation(
                    proposal_id,
                    owner,
                    "remediation attempt interrupted or failed before completion",
                )

    def _run(
        self,
        proposal_id: str,
        owner: str,
        state: dict[str, Any],
        resumed_from_stage: str | None,
    ) -> RemediationResponse:
        proposal = self.incidents.get_proposal(proposal_id)
        original_execution_id = self.incidents.get_execution_id(proposal_id)
        dry_run = self.incidents.get_dry_run(proposal_id)
        approval = self.incidents.get_approval(proposal_id)

        if not self.n8n.settings.allow_workflow_mutation:
            raise PermissionError("Workflow mutation is disabled by ALLOW_WORKFLOW_MUTATION=false.")
        if not self.n8n.settings.allow_execution_retry:
            raise PermissionError("Execution retry is disabled by ALLOW_EXECUTION_RETRY=false.")

        if approval.workflow_snapshot_fingerprint != dry_run.workflow_snapshot_fingerprint:
            raise RemediationError("Approval is not bound to the latest validated dry-run snapshot.")
        if approval.workflow_version_id != dry_run.workflow_version_id:
            raise RemediationError("Approval is not bound to the latest validated workflow version.")

        stage = str(state.get("stage") or "claimed")
        expected_update_fingerprint = state.get("expected_update_fingerprint")
        workflow_version_before = state.get("workflow_version_before")

        if stage in {"claimed", "workflow_update_starting"}:
            current = self.n8n.get_workflow(proposal.workflow_id)
            current_version = self.dry_runner.workflow_version_id(current)
            current_snapshot = self.dry_runner.snapshot_fingerprint(current)

            if stage == "workflow_update_starting" and expected_update_fingerprint:
                if workflow_definition_fingerprint(current) == expected_update_fingerprint:
                    self._verify_protected_structure(current, dry_run.structural_fingerprint_before)
                    self.store.set_remediation_stage(
                        proposal_id,
                        owner,
                        "workflow_verified",
                        lease_seconds=self.lease_seconds,
                    )
                    self.store.append_event(
                        proposal_id,
                        "workflow_update_recovered",
                        {"action": "observed already-persisted approved workflow definition"},
                    )
                    stage = "workflow_verified"
                    workflow_version_before = workflow_version_before or dry_run.workflow_version_id
                elif self._matches_approved_original(current, dry_run):
                    stage = "claimed"
                else:
                    raise StaleWorkflowError(
                        "Workflow state is neither the approved original nor the approved patched definition; automatic recovery stopped."
                    )

            if stage == "claimed":
                if dry_run.workflow_version_id is not None and current_version != dry_run.workflow_version_id:
                    raise StaleWorkflowError(
                        "Workflow version changed after dry run; a new dry run is required."
                    )
                if current_snapshot != dry_run.workflow_snapshot_fingerprint:
                    raise StaleWorkflowError(
                        "Workflow snapshot changed after dry run; a new dry run is required."
                    )

                fresh_dry_run, patched = self.dry_runner.dry_run(current, proposal)
                if fresh_dry_run.workflow_snapshot_fingerprint != dry_run.workflow_snapshot_fingerprint:
                    raise StaleWorkflowError("Workflow changed while rebuilding the approved patch.")

                update_body = serialize_workflow_for_update(patched)
                expected_update_fingerprint = workflow_definition_fingerprint(update_body)
                workflow_version_before = current_version
                self.store.set_remediation_stage(
                    proposal_id,
                    owner,
                    "workflow_update_starting",
                    expected_update_fingerprint=expected_update_fingerprint,
                    workflow_version_before=workflow_version_before,
                    lease_seconds=self.lease_seconds,
                )
                self.store.append_event(
                    proposal_id,
                    "workflow_update_starting",
                    {
                        "publish_if_active": False,
                        "workflow_version_before": workflow_version_before,
                        "definition_fingerprint": expected_update_fingerprint,
                    },
                )

                self.n8n.update_workflow(
                    proposal.workflow_id,
                    update_body,
                    publish_if_active=False,
                )
                persisted = self.n8n.get_workflow(proposal.workflow_id)
                self._verify_persisted(
                    persisted,
                    expected_update_fingerprint,
                    dry_run.structural_fingerprint_before,
                )
                self.store.set_remediation_stage(
                    proposal_id,
                    owner,
                    "workflow_verified",
                    lease_seconds=self.lease_seconds,
                )
                self.store.append_event(
                    proposal_id,
                    "workflow_verified",
                    {
                        "workflow_version_after": self.dry_runner.workflow_version_id(persisted),
                        "definition_fingerprint": expected_update_fingerprint,
                    },
                )
                stage = "workflow_verified"

        if expected_update_fingerprint is None:
            refreshed = self.store.get_remediation(proposal_id) or {}
            expected_update_fingerprint = refreshed.get("expected_update_fingerprint")
            workflow_version_before = workflow_version_before or refreshed.get("workflow_version_before")
        if expected_update_fingerprint is None:
            raise WorkflowVerificationError("Approved workflow definition fingerprint is missing.")

        persisted = self.n8n.get_workflow(proposal.workflow_id)
        self._verify_persisted(
            persisted,
            str(expected_update_fingerprint),
            dry_run.structural_fingerprint_before,
        )

        retry_execution_id: str | None = state.get("retry_execution_id")
        retry_status_hint: str | None = None

        if stage == "retry_starting":
            finder = getattr(self.n8n, "find_retry_execution", None)
            recovered = finder(original_execution_id, proposal.workflow_id) if callable(finder) else None
            if not recovered:
                raise RetryRecoveryRequiredError(
                    "A retry may already have been requested before the previous process stopped; no second retry was started because duplicate execution cannot be ruled out."
                )
            retry_execution_id = str(recovered["id"])
            retry_status_hint = str(recovered.get("status") or "unknown")
            self.store.set_remediation_stage(
                proposal_id,
                owner,
                "retry_started",
                retry_execution_id=retry_execution_id,
                lease_seconds=self.lease_seconds,
            )
            self.store.append_event(
                proposal_id,
                "retry_recovered",
                {"retry_execution_id": retry_execution_id},
            )
            stage = "retry_started"

        if stage == "workflow_verified":
            self.store.set_remediation_stage(
                proposal_id,
                owner,
                "retry_starting",
                lease_seconds=self.lease_seconds,
            )
            self.store.append_event(
                proposal_id,
                "retry_starting",
                {"original_execution_id": original_execution_id, "load_workflow": True},
            )
            retry = self.n8n.retry_execution(original_execution_id, load_workflow=True)
            retry_execution_id_value = retry.get("id")
            if retry_execution_id_value is None:
                raise WorkflowVerificationError("n8n retry response did not include an execution ID.")
            retry_execution_id = str(retry_execution_id_value)
            retry_status_hint = str(retry.get("status") or "unknown")
            self.store.set_remediation_stage(
                proposal_id,
                owner,
                "retry_started",
                retry_execution_id=retry_execution_id,
                lease_seconds=self.lease_seconds,
            )
            self.store.append_event(
                proposal_id,
                "retry_started",
                {"retry_execution_id": retry_execution_id},
            )
            stage = "retry_started"

        if stage != "retry_started" or not retry_execution_id:
            refreshed = self.store.get_remediation(proposal_id) or {}
            retry_execution_id = retry_execution_id or refreshed.get("retry_execution_id")
        if not retry_execution_id:
            raise WorkflowVerificationError("Retry execution ID is missing from durable state.")

        verified_execution = self.n8n.get_execution(str(retry_execution_id))
        retry_status = str(
            verified_execution.get("status") or retry_status_hint or "unknown"
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
            workflow_version_before=(
                str(workflow_version_before) if workflow_version_before is not None else None
            ),
            workflow_version_after=self.dry_runner.workflow_version_id(persisted),
            update_applied=True,
            publish_if_active=False,
            retry_started=True,
            retry_execution_id=str(retry_execution_id),
            retry_status=retry_status,
            verification=verification,
            resumed_from_stage=resumed_from_stage,
            evidence=[
                "Approval matched the latest durable dry-run version and snapshot fingerprint.",
                "A SQLite lease prevented concurrent remediation attempts for this proposal.",
                "The current n8n workflow matched either the approved source snapshot or the already-persisted approved definition.",
                "The patch was rebuilt server-side; no client-supplied patched body was trusted.",
                "The workflow update used publishIfActive=false and the persisted writable definition was fingerprint-verified.",
                "Protected workflow structure matched the pre-update fingerprint.",
                "Execution retry was started at most once by the normal path; crash recovery requires evidence before reusing an existing retry.",
                f"Retry verification status: {retry_status}.",
            ],
        )

    def _matches_approved_original(self, current: dict[str, Any], dry_run: Any) -> bool:
        current_version = self.dry_runner.workflow_version_id(current)
        if dry_run.workflow_version_id is not None and current_version != dry_run.workflow_version_id:
            return False
        return self.dry_runner.snapshot_fingerprint(current) == dry_run.workflow_snapshot_fingerprint

    def _verify_persisted(
        self,
        persisted: dict[str, Any],
        expected_update_fingerprint: str,
        protected_fingerprint: str,
    ) -> None:
        if workflow_definition_fingerprint(persisted) != expected_update_fingerprint:
            raise WorkflowVerificationError(
                "n8n did not persist the exact approved workflow definition; retry was not started."
            )
        self._verify_protected_structure(persisted, protected_fingerprint)

    def _verify_protected_structure(
        self,
        workflow: dict[str, Any],
        protected_fingerprint: str,
    ) -> None:
        if self.dry_runner.structural_fingerprint(workflow) != protected_fingerprint:
            raise WorkflowVerificationError(
                "Protected workflow structure changed after update; retry was not started."
            )
