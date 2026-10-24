from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings


class N8NClient:
    """Thin public-API client with explicit gates around side-effecting operations."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        if client is not None:
            self.client = client
            return

        headers = {"Accept": "application/json"}
        if settings.n8n_api_key:
            headers["X-N8N-API-KEY"] = settings.n8n_api_key
        self.client = httpx.Client(
            base_url=settings.n8n_base_url.rstrip("/"),
            headers=headers,
            timeout=settings.n8n_timeout_seconds,
        )

    def get_execution(self, execution_id: str) -> dict[str, Any]:
        response = self.client.get(
            f"/api/v1/executions/{execution_id}",
            params={
                "includeData": "true",
                "redactExecutionData": "true",
            },
        )
        response.raise_for_status()
        return response.json()

    def list_executions(
        self,
        limit: int = 100,
        cursor: str | None = None,
        workflow_id: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, str | int] = {
            "limit": max(1, min(limit, 100)),
            "includeData": "false",
        }
        if cursor:
            params["cursor"] = cursor
        if workflow_id:
            params["workflowId"] = workflow_id
        if status:
            params["status"] = status

        response = self.client.get("/api/v1/executions", params=params)
        response.raise_for_status()
        return response.json()

    def list_failed_executions(
        self,
        limit: int = 20,
        cursor: str | None = None,
        workflow_id: str | None = None,
    ) -> dict[str, Any]:
        return self.list_executions(
            limit=limit,
            cursor=cursor,
            workflow_id=workflow_id,
            status="error",
        )

    def find_retry_execution(
        self,
        original_execution_id: str,
        workflow_id: str,
        limit: int = 100,
        *,
        max_pages: int = 5,
    ) -> dict[str, Any] | None:
        """Search bounded metadata pages for a retry without starting a new execution.

        A missing result is *not* proof that no retry happened: callers must
        fail closed rather than issuing another retry after a crash.
        """
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _ in range(max_pages):
            payload = self.list_executions(limit=limit, cursor=cursor, workflow_id=workflow_id)
            executions = payload.get("data", [])
            if not isinstance(executions, list):
                return None
            for execution in executions:
                if not isinstance(execution, dict):
                    continue
                retry_of = execution.get("retryOf")
                execution_workflow = execution.get("workflowId")
                if (
                    retry_of is not None
                    and str(retry_of) == original_execution_id
                    and (execution_workflow is None or str(execution_workflow) == workflow_id)
                ):
                    return execution

            next_cursor = payload.get("nextCursor")
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
                return None
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return None

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        response = self.client.get(f"/api/v1/workflows/{workflow_id}")
        response.raise_for_status()
        return response.json()

    def update_workflow(
        self,
        workflow_id: str,
        workflow: dict[str, Any],
        *,
        publish_if_active: bool = False,
    ) -> dict[str, Any]:
        if not self.settings.allow_workflow_mutation:
            raise PermissionError("Workflow mutation is disabled by ALLOW_WORKFLOW_MUTATION=false.")
        response = self.client.put(
            f"/api/v1/workflows/{workflow_id}",
            params={"publishIfActive": str(publish_if_active).lower()},
            json=workflow,
        )
        response.raise_for_status()
        return response.json()

    def retry_execution(
        self,
        execution_id: str,
        *,
        load_workflow: bool = True,
    ) -> dict[str, Any]:
        if not self.settings.allow_execution_retry:
            raise PermissionError("Execution retry is disabled by ALLOW_EXECUTION_RETRY=false.")
        response = self.client.post(
            f"/api/v1/executions/{execution_id}/retry",
            json={"loadWorkflow": load_workflow},
        )
        response.raise_for_status()
        return response.json()
