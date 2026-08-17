import httpx

from app.core.config import Settings
from app.services.n8n_client import N8NClient


def test_get_execution_requests_redacted_execution_data():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(
            200,
            json={"id": "123", "workflowId": "wf", "status": "error"},
        )

    http_client = httpx.Client(
        base_url="https://n8n.example.com",
        transport=httpx.MockTransport(handler),
    )
    client = N8NClient(Settings(n8n_base_url="https://n8n.example.com"), client=http_client)

    client.get_execution("123")

    assert seen["includeData"] == "true"
    assert seen["redactExecutionData"] == "true"


def test_list_failed_executions_is_metadata_only_and_bounded():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"data": [], "nextCursor": None})

    http_client = httpx.Client(
        base_url="https://n8n.example.com",
        transport=httpx.MockTransport(handler),
    )
    client = N8NClient(Settings(n8n_base_url="https://n8n.example.com"), client=http_client)

    client.list_failed_executions(limit=500, cursor="next", workflow_id="wf-7")

    assert seen["status"] == "error"
    assert seen["includeData"] == "false"
    assert seen["limit"] == "100"
    assert seen["cursor"] == "next"
    assert seen["workflowId"] == "wf-7"
