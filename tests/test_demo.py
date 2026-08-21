from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_demo_page_exposes_measured_result_and_read_only_boundary():
    response = client.get("/demo")

    assert response.status_code == 200
    assert "93.75%" in response.text
    assert "read-only demo" in response.text
    assert "no workflow writes" in response.text
    assert "/v1/demo/analyze" in response.text


def test_demo_analysis_returns_preview_without_side_effect_capability():
    response = client.post(
        "/v1/demo/analyze",
        json={
            "error_message": "429 Too Many Requests",
            "status_code": 429,
            "error_code": "RATE_LIMITED",
            "failed_node": "HTTP Request",
            "node_type": "n8n-nodes-base.httpRequest",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "read_only_demo"
    assert body["diagnosis"]["failure_class"] == "rate_limit"
    assert body["patch_preview"] is not None
    assert body["patch_preview"]["auto_apply_allowed"] is False
    assert body["patch_preview"]["requires_human_approval"] is True
    assert body["safety"] == {
        "durable_state_write": False,
        "workflow_mutation": False,
        "execution_retry": False,
        "approval": False,
        "patch_preview_only": True,
    }


def test_demo_unknown_failure_does_not_invent_a_patch():
    response = client.post(
        "/v1/demo/analyze",
        json={
            "error_message": "Vendor returned internal policy state VND-734.",
            "error_code": "VND-734",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["patch_preview"] is None
    assert body["safety"]["workflow_mutation"] is False
    assert body["safety"]["execution_retry"] is False
