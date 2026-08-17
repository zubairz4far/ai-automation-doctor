from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from app.models.schemas import (
    PatchOperation,
    PatchProposal,
    WorkflowDryRunResponse,
    WorkflowPatchChange,
)
from app.services.validator import ALLOWED_OPTION_PATHS, PatchValidator


class WorkflowDryRunError(ValueError):
    pass


_MISSING = object()


class WorkflowDryRunEngine:
    """Apply a validated proposal to a deep copy and prove protected structure is unchanged."""

    def __init__(self, validator: PatchValidator | None = None):
        self.validator = validator or PatchValidator()

    def dry_run(
        self,
        workflow: dict[str, Any],
        proposal: PatchProposal,
    ) -> tuple[WorkflowDryRunResponse, dict[str, Any]]:
        self.validator.validate(proposal)
        self._validate_workflow_shape(workflow, proposal.workflow_id)

        patched = deepcopy(workflow)
        nodes = patched["nodes"]
        original_nodes = workflow["nodes"]

        target_names: set[str] = set()
        changes: list[WorkflowPatchChange] = []
        target_indices: set[int] = set()

        for operation in proposal.operations:
            node_name, option_name = self._parse_path(operation.path)
            node_index = self._resolve_unique_node_index(nodes, node_name)
            target_names.add(node_name)
            target_indices.add(node_index)

            target = nodes[node_index]
            before = self._read_option(target, option_name)
            self._apply_option(target, option_name, operation)
            after = self._read_option(target, option_name)
            changes.append(
                WorkflowPatchChange(
                    node_name=node_name,
                    path=operation.path,
                    before=None if before is _MISSING else before,
                    after=after,
                    reason=operation.reason,
                )
            )

        if len(target_names) != 1:
            raise WorkflowDryRunError("A baseline dry run may target exactly one workflow node.")

        self._assert_protected_invariants(workflow, patched, target_indices)
        before_fingerprint = self._structural_fingerprint(workflow)
        after_fingerprint = self._structural_fingerprint(patched)
        if before_fingerprint != after_fingerprint:
            raise WorkflowDryRunError("Protected workflow structure changed during dry run.")

        # Extra defensive check: node count/order is stable after application.
        if [self._node_identity(node) for node in original_nodes] != [
            self._node_identity(node) for node in nodes
        ]:
            raise WorkflowDryRunError("Workflow node identity/order changed during dry run.")

        response = WorkflowDryRunResponse(
            proposal_id=proposal.proposal_id,
            workflow_id=proposal.workflow_id,
            target_nodes=sorted(target_names),
            changes=changes,
            structural_fingerprint_before=before_fingerprint,
            structural_fingerprint_after=after_fingerprint,
            validation_notes=[
                "Patch was applied to a deep copy only; no n8n write occurred.",
                "Connections, settings, node identity/type, position, webhook IDs, and credentials were preserved.",
                "Only allowlisted retry option leaves changed.",
            ],
        )
        return response, patched

    @staticmethod
    def _validate_workflow_shape(workflow: dict[str, Any], proposal_workflow_id: str) -> None:
        if not isinstance(workflow, dict):
            raise WorkflowDryRunError("Workflow must be a JSON object.")
        nodes = workflow.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            raise WorkflowDryRunError("Workflow must contain a non-empty nodes array.")
        if not isinstance(workflow.get("connections", {}), dict):
            raise WorkflowDryRunError("Workflow connections must be an object.")
        if not isinstance(workflow.get("settings", {}), dict):
            raise WorkflowDryRunError("Workflow settings must be an object.")

        workflow_id = workflow.get("id")
        if workflow_id is not None and str(workflow_id) != proposal_workflow_id:
            raise WorkflowDryRunError("Patch proposal workflow ID does not match the workflow snapshot.")

        for node in nodes:
            if not isinstance(node, dict):
                raise WorkflowDryRunError("Every workflow node must be an object.")
            if not isinstance(node.get("name"), str) or not node["name"]:
                raise WorkflowDryRunError("Every workflow node must have a non-empty name.")

    def _resolve_unique_node_index(self, nodes: list[dict[str, Any]], node_name: str) -> int:
        matches = [index for index, node in enumerate(nodes) if node.get("name") == node_name]
        if not matches:
            raise WorkflowDryRunError(f"Target node not found: {node_name}")
        if len(matches) > 1:
            raise WorkflowDryRunError(f"Target node name is not unique: {node_name}")
        return matches[0]

    @staticmethod
    def _parse_path(path: str) -> tuple[str, str]:
        parts = path.split("/")
        if len(parts) != 6 or parts[:2] != ["", "nodes"]:
            raise WorkflowDryRunError(f"Unsupported logical patch path: {path}")
        if parts[3:5] != ["parameters", "options"]:
            raise WorkflowDryRunError(f"Unsupported logical patch path: {path}")
        option_name = parts[5]
        if option_name not in ALLOWED_OPTION_PATHS:
            raise WorkflowDryRunError(f"Option is not allowlisted: {option_name}")
        return WorkflowDryRunEngine._unescape_segment(parts[2]), option_name

    @staticmethod
    def _unescape_segment(value: str) -> str:
        # Reject malformed JSON Pointer escape sequences rather than guessing.
        index = 0
        output: list[str] = []
        while index < len(value):
            if value[index] != "~":
                output.append(value[index])
                index += 1
                continue
            if index + 1 >= len(value) or value[index + 1] not in {"0", "1"}:
                raise WorkflowDryRunError("Malformed escaped node segment in patch path.")
            output.append("~" if value[index + 1] == "0" else "/")
            index += 2
        node_name = "".join(output)
        if not node_name:
            raise WorkflowDryRunError("Patch path contains an empty node name.")
        return node_name

    @staticmethod
    def _read_option(node: dict[str, Any], option_name: str) -> Any:
        parameters = node.get("parameters")
        if not isinstance(parameters, dict):
            return _MISSING
        options = parameters.get("options")
        if not isinstance(options, dict):
            return _MISSING
        return options.get(option_name, _MISSING)

    @staticmethod
    def _apply_option(node: dict[str, Any], option_name: str, operation: PatchOperation) -> None:
        parameters = node.setdefault("parameters", {})
        if not isinstance(parameters, dict):
            raise WorkflowDryRunError("Target node parameters are not an object.")
        options = parameters.setdefault("options", {})
        if not isinstance(options, dict):
            raise WorkflowDryRunError("Target node parameters.options is not an object.")

        if operation.op == "replace" and option_name not in options:
            raise WorkflowDryRunError(f"replace requires an existing option: {option_name}")
        options[option_name] = deepcopy(operation.value)

    @staticmethod
    def _assert_protected_invariants(
        original: dict[str, Any],
        patched: dict[str, Any],
        target_indices: set[int],
    ) -> None:
        original_top = {key: value for key, value in original.items() if key != "nodes"}
        patched_top = {key: value for key, value in patched.items() if key != "nodes"}
        if original_top != patched_top:
            raise WorkflowDryRunError("Top-level workflow metadata/connections/settings changed.")

        original_nodes = original["nodes"]
        patched_nodes = patched["nodes"]
        if len(original_nodes) != len(patched_nodes):
            raise WorkflowDryRunError("Workflow node count changed.")

        for index, (before_node, after_node) in enumerate(zip(original_nodes, patched_nodes, strict=True)):
            if index not in target_indices:
                if before_node != after_node:
                    raise WorkflowDryRunError("A non-target workflow node changed.")
                continue

            before_outer = {key: value for key, value in before_node.items() if key != "parameters"}
            after_outer = {key: value for key, value in after_node.items() if key != "parameters"}
            if before_outer != after_outer:
                raise WorkflowDryRunError("Protected target-node metadata changed.")

            before_parameters = before_node.get("parameters", {})
            after_parameters = after_node.get("parameters", {})
            if not isinstance(before_parameters, dict) or not isinstance(after_parameters, dict):
                raise WorkflowDryRunError("Target node parameters are malformed.")

            before_non_options = {
                key: value for key, value in before_parameters.items() if key != "options"
            }
            after_non_options = {
                key: value for key, value in after_parameters.items() if key != "options"
            }
            if before_non_options != after_non_options:
                raise WorkflowDryRunError("Non-option node parameters changed.")

            before_options = before_parameters.get("options", {})
            after_options = after_parameters.get("options", {})
            if not isinstance(before_options, dict) or not isinstance(after_options, dict):
                raise WorkflowDryRunError("Target node options are malformed.")
            before_protected = {
                key: value for key, value in before_options.items() if key not in ALLOWED_OPTION_PATHS
            }
            after_protected = {
                key: value for key, value in after_options.items() if key not in ALLOWED_OPTION_PATHS
            }
            if before_protected != after_protected:
                raise WorkflowDryRunError("A non-allowlisted node option changed.")

    @staticmethod
    def _node_identity(node: dict[str, Any]) -> dict[str, Any]:
        return {
            key: deepcopy(node.get(key))
            for key in ("id", "name", "type", "typeVersion", "position", "webhookId", "credentials")
        }

    def _structural_fingerprint(self, workflow: dict[str, Any]) -> str:
        protected = {
            "name": workflow.get("name"),
            "connections": workflow.get("connections", {}),
            "settings": workflow.get("settings", {}),
            "nodes": [self._node_identity(node) for node in workflow["nodes"]],
        }
        encoded = json.dumps(protected, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(encoded).hexdigest()
