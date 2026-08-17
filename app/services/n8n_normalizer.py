from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from app.models.schemas import ExecutionFailure


class N8NExecutionNormalizationError(ValueError):
    pass


class N8NExecutionNormalizer:
    """Convert n8n execution/API error payloads into the internal incident schema.

    The normalizer intentionally extracts only diagnosis-relevant metadata. It does
    not retain node credentials, full workflow JSON, or raw input/output items.
    """

    FAILED_STATUSES: ClassVar[frozenset[str]] = frozenset({"error", "crashed"})

    def normalize(self, payload: Mapping[str, Any]) -> ExecutionFailure:
        status = self._as_text(payload.get("status"))
        if status and status.lower() not in self.FAILED_STATUSES:
            raise N8NExecutionNormalizationError(
                f"Execution status {status!r} is not a failed execution status."
            )

        data = self._mapping(payload.get("data"))
        result_data = self._mapping(data.get("resultData"))
        workflow_data = self._mapping(payload.get("workflowData"))

        error = self._mapping(result_data.get("error"))
        last_node = self._first_text(
            result_data.get("lastNodeExecuted"),
            self._mapping(error.get("node")).get("name"),
            self._mapping(payload.get("n8nDetails")).get("nodeName"),
        )

        if not error:
            error = self._find_run_error(result_data.get("runData"), last_node)

        node = self._mapping(error.get("node"))
        ui_details = self._mapping(payload.get("n8nDetails"))
        error_details = self._mapping(error.get("errorDetails"))
        payload_error_details = self._mapping(payload.get("errorDetails"))

        execution_id = self._first_text(payload.get("id"), payload.get("executionId"))
        workflow_id = self._first_text(payload.get("workflowId"), workflow_data.get("id"))
        if not execution_id:
            raise N8NExecutionNormalizationError("Execution payload is missing an execution ID.")
        if not workflow_id:
            raise N8NExecutionNormalizationError("Execution payload is missing a workflow ID.")

        message = self._first_text(
            error.get("message"),
            error.get("errorMessage"),
            payload.get("errorMessage"),
            error.get("description"),
            payload.get("errorDescription"),
        )
        if not message:
            raise N8NExecutionNormalizationError("Execution payload does not contain a usable error message.")

        raw_code = self._first_text(
            error.get("httpCode"),
            error.get("statusCode"),
            error_details.get("httpCode"),
            payload_error_details.get("httpCode"),
        )
        status_code = self._http_status(raw_code)

        stack_parts = [
            self._as_text(error.get("stack")),
            self._stack_trace(ui_details.get("stackTrace")),
            self._raw_messages(error.get("messages")),
            self._raw_messages(error_details.get("rawErrorMessage")),
            self._raw_messages(payload_error_details.get("rawErrorMessage")),
            self._as_text(error.get("description")),
            self._as_text(payload.get("errorDescription")),
        ]
        error_stack = "\n".join(part for part in stack_parts if part) or None

        failed_node = self._first_text(last_node, node.get("name"), ui_details.get("nodeName"))
        node_type = self._first_text(
            node.get("type"),
            ui_details.get("nodeType"),
            self._node_type_from_workflow(workflow_data, failed_node),
        )

        return ExecutionFailure(
            execution_id=execution_id,
            workflow_id=workflow_id,
            workflow_name=self._first_text(workflow_data.get("name"), payload.get("workflowName")),
            failed_node=failed_node,
            node_type=node_type,
            error_message=message,
            error_stack=error_stack,
            error_code=raw_code,
            status_code=status_code,
        )

    def _find_run_error(self, run_data: Any, last_node: str | None) -> dict[str, Any]:
        run_mapping = self._mapping(run_data)
        candidate_names = [last_node] if last_node else list(run_mapping)
        for name in candidate_names:
            if not name:
                continue
            runs = run_mapping.get(name)
            if not isinstance(runs, list):
                continue
            for run in reversed(runs):
                run_mapping_item = self._mapping(run)
                error = self._mapping(run_mapping_item.get("error"))
                if error:
                    return error
        return {}

    def _node_type_from_workflow(
        self, workflow_data: Mapping[str, Any], failed_node: str | None
    ) -> str | None:
        if not failed_node:
            return None
        nodes = workflow_data.get("nodes")
        if not isinstance(nodes, list):
            return None
        for node in nodes:
            node_mapping = self._mapping(node)
            if self._as_text(node_mapping.get("name")) == failed_node:
                return self._as_text(node_mapping.get("type"))
        return None

    @staticmethod
    def _mapping(value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, Mapping) else {}

    @staticmethod
    def _as_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _first_text(self, *values: Any) -> str | None:
        for value in values:
            text = self._as_text(value)
            if text:
                return text
        return None

    @staticmethod
    def _http_status(raw_code: str | None) -> int | None:
        if not raw_code or not raw_code.isdigit():
            return None
        value = int(raw_code)
        return value if 100 <= value <= 599 else None

    def _stack_trace(self, value: Any) -> str | None:
        if isinstance(value, list):
            return "\n".join(str(item) for item in value if item)
        return self._as_text(value)

    def _raw_messages(self, value: Any) -> str | None:
        if isinstance(value, list):
            return "\n".join(str(item) for item in value if item)
        return self._as_text(value)
