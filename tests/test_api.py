from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_mutation_is_disabled_by_default():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["workflow_mutation_enabled"] is False


def test_incident_analysis_returns_patch_for_429():
    response = client.post(
        "/v1/incidents/analyze",
        json={
            "execution_id": "e1",
            "workflow_id": "w1",
            "failed_node": "HTTP Request",
            "node_type": "n8n-nodes-base.httpRequest",
            "error_message": "429 Too Many Requests",
            "status_code": 429,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["diagnosis"]["failure_class"] == "rate_limit"
    assert body["patch"]["requires_human_approval"] is True
