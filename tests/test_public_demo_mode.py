from fastapi.testclient import TestClient

import app.main as main_module


def test_public_demo_only_blocks_normal_api(monkeypatch):
    monkeypatch.setattr(main_module.settings, "public_demo_only", True)
    client = TestClient(main_module.app)

    demo = client.get("/demo")
    assert demo.status_code == 200

    analyze = client.post(
        "/v1/demo/analyze",
        json={
            "error_message": "429 Too Many Requests",
            "status_code": 429,
        },
    )
    assert analyze.status_code == 200
    assert analyze.json()["safety"]["workflow_mutation"] is False
    assert analyze.json()["safety"]["execution_retry"] is False

    blocked = client.post(
        "/v1/incidents/analyze",
        json={
            "execution_id": "public-demo-blocked",
            "workflow_id": "workflow-1",
            "error_message": "429 Too Many Requests",
            "status_code": 429,
        },
    )
    assert blocked.status_code == 404
    assert blocked.json()["detail"] == "This deployment exposes only the read-only public demo."


def test_public_demo_only_keeps_health_available(monkeypatch):
    monkeypatch.setattr(main_module.settings, "public_demo_only", True)
    client = TestClient(main_module.app)

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
