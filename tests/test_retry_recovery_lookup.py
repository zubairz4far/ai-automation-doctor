import httpx

from app.core.config import Settings
from app.services.n8n_client import N8NClient


def test_find_retry_execution_scans_metadata_without_execution_data():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "newer-unrelated",
                        "workflowId": "workflow-7",
                        "retryOf": None,
                        "status": "success",
                    },
                    {
                        "id": "retry-existing",
                        "workflowId": "workflow-7",
                        "retryOf": "failed-execution-1",
                        "status": "success",
                    },
                ],
                "nextCursor": None,
            },
        )

    http_client = httpx.Client(
        base_url="https://n8n.example.com",
        transport=httpx.MockTransport(handler),
    )
    client = N8NClient(Settings(n8n_base_url="https://n8n.example.com"), client=http_client)

    result = client.find_retry_execution("failed-execution-1", "workflow-7")

    assert result is not None
    assert result["id"] == "retry-existing"
    assert seen["workflowId"] == "workflow-7"
    assert seen["includeData"] == "false"
    assert seen["limit"] == "100"
    assert "status" not in seen


def test_find_retry_execution_scans_subsequent_pages():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        requests.append(cursor)
        if cursor is None:
            return httpx.Response(200, json={"data": [{"id": "unrelated", "retryOf": None}], "nextCursor": "second"})
        assert cursor == "second"
        return httpx.Response(200, json={"data": [
            {"id": "wrong-workflow", "workflowId": "other", "retryOf": "failed-execution-1"},
            {"id": "correct-retry", "workflowId": "workflow-7", "retryOf": "failed-execution-1"},
        ], "nextCursor": None})

    transport = httpx.MockTransport(handler)
    with httpx.Client(base_url="https://n8n.example.com", transport=transport) as http_client:
        client = N8NClient(Settings(n8n_base_url="https://n8n.example.com"), client=http_client)
        recovered = client.find_retry_execution("failed-execution-1", "workflow-7")
    assert recovered is not None
    assert recovered["id"] == "correct-retry"
    assert requests == [None, "second"]


def test_find_retry_execution_stops_on_cyclic_cursor():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("cursor"))
        return httpx.Response(200, json={"data": [], "nextCursor": "loop"})

    with httpx.Client(base_url="https://n8n.example.com", transport=httpx.MockTransport(handler)) as http_client:
        client = N8NClient(Settings(n8n_base_url="https://n8n.example.com"), client=http_client)
        assert client.find_retry_execution("failed-execution-1", "workflow-7") is None
    assert seen == [None, "loop"]


def test_find_retry_execution_caps_page_count():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("cursor"))
        return httpx.Response(200, json={"data": [], "nextCursor": f"page-{len(seen)}"})

    with httpx.Client(base_url="https://n8n.example.com", transport=httpx.MockTransport(handler)) as http_client:
        client = N8NClient(Settings(n8n_base_url="https://n8n.example.com"), client=http_client)
        assert client.find_retry_execution("failed-execution-1", "workflow-7", max_pages=3) is None
    assert len(seen) == 3
