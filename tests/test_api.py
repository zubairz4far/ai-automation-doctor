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


def test_n8n_ingestion_normalizes_and_diagnoses_execution():
    response = client.post(
        "/v1/incidents/ingest/n8n",
        json={
            "id": "execution-42",
            "workflowId": "workflow-7",
            "status": "error",
            "data": {
                "resultData": {
                    "lastNodeExecuted": "HTTP Request",
                    "error": {
                        "message": "Too many requests",
                        "httpCode": "429",
                        "node": {
                            "name": "HTTP Request",
                            "type": "n8n-nodes-base.httpRequest",
                        },
                    },
                }
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["diagnosis"]["failure_class"] == "rate_limit"
    assert body["diagnosis"]["retry_safe"] is True
    assert body["patch"]["requires_human_approval"] is True


def test_n8n_ingestion_rejects_successful_execution():
    response = client.post(
        "/v1/incidents/ingest/n8n",
        json={
            "id": "execution-43",
            "workflowId": "workflow-7",
            "status": "success",
            "data": {"resultData": {}},
        },
    )

    assert response.status_code == 422
