from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings


class N8NClient:
    """Thin public-API client. Mutation methods are gated by Settings."""

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

    def list_failed_executions(
        self,
        limit: int = 20,
        cursor: str | None = None,
        workflow_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, str | int] = {
            "status": "error",
            "limit": max(1, min(limit, 100)),
            "includeData": "false",
        }
        if cursor:
            params["cursor"] = cursor
        if workflow_id:
            params["workflowId"] = workflow_id

        response = self.client.get("/api/v1/executions", params=params)
        response.raise_for_status()
        return response.json()

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        response = self.client.get(f"/api/v1/workflows/{workflow_id}")
        response.raise_for_status()
        return response.json()

    def update_workflow(self, workflow_id: str, workflow: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.allow_workflow_mutation:
            raise PermissionError("Workflow mutation is disabled by ALLOW_WORKFLOW_MUTATION=false.")
        response = self.client.put(f"/api/v1/workflows/{workflow_id}", json=workflow)
        response.raise_for_status()
        return response.json()
