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
