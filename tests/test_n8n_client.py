import httpx
import pytest

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


def test_update_workflow_is_disabled_by_default():
    client = N8NClient(Settings())

    with pytest.raises(PermissionError, match="ALLOW_WORKFLOW_MUTATION=false"):
        client.update_workflow("wf", {"name": "x", "nodes": [], "connections": {}, "settings": {}})


def test_retry_execution_is_disabled_by_default():
    client = N8NClient(Settings())

    with pytest.raises(PermissionError, match="ALLOW_EXECUTION_RETRY=false"):
        client.retry_execution("execution-1")


def test_update_uses_draft_only_publish_flag():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        assert request.method == "PUT"
        return httpx.Response(200, json={"id": "wf"})

    http_client = httpx.Client(
        base_url="https://n8n.example.com",
        transport=httpx.MockTransport(handler),
    )
    client = N8NClient(
        Settings(n8n_base_url="https://n8n.example.com", allow_workflow_mutation=True),
        client=http_client,
    )

    client.update_workflow(
        "wf",
        {"name": "x", "nodes": [], "connections": {}, "settings": {}},
        publish_if_active=False,
    )

    assert seen["publishIfActive"] == "false"


def test_retry_uses_current_saved_workflow():
    captured_body: bytes | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_body
        captured_body = request.content
        assert request.method == "POST"
        assert request.url.path == "/api/v1/executions/execution-1/retry"
        return httpx.Response(200, json={"id": "retry-1", "status": "success"})

    http_client = httpx.Client(
        base_url="https://n8n.example.com",
        transport=httpx.MockTransport(handler),
    )
    client = N8NClient(
        Settings(n8n_base_url="https://n8n.example.com", allow_execution_retry=True),
        client=http_client,
    )

    client.retry_execution("execution-1", load_workflow=True)

    assert captured_body == b'{"loadWorkflow":true}'
