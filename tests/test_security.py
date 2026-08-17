import json
import sqlite3

from fastapi.testclient import TestClient

import app.main as main_module
from app.core.config import Settings
from app.models.schemas import ExecutionFailure
from app.services.incidents import IncidentService
from app.services.state_store import SQLiteStateStore


def test_raw_snapshots_are_not_written_to_durable_incident_state(tmp_path):
    db_path = tmp_path / "doctor.db"
    settings = Settings(state_db_path=str(db_path))
    incidents = IncidentService(settings=settings, store=SQLiteStateStore(str(db_path)))

    incidents.analyze(
        ExecutionFailure(
            execution_id="privacy-execution",
            workflow_id="workflow-privacy",
            failed_node="HTTP Request",
            error_message="429 Too Many Requests",
            status_code=429,
            input_snapshot={"password": "customer-secret-value"},
            workflow_snapshot={"credentials": {"apiKey": "workflow-secret-value"}},
        )
    )

    with sqlite3.connect(db_path) as connection:
        failure_json = connection.execute("SELECT failure_json FROM incidents").fetchone()[0]

    durable = json.loads(failure_json)
    assert durable["input_snapshot"] is None
    assert durable["workflow_snapshot"] is None
    assert "customer-secret-value" not in failure_json
    assert "workflow-secret-value" not in failure_json


def test_side_effect_enabled_http_boundary_requires_operator_token(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(
            allow_workflow_mutation=True,
            allow_execution_retry=True,
            operator_token="test-operator-token",
        ),
    )
    client = TestClient(main_module.app)

    unauthorized = client.post(
        "/v1/patches/not-a-real-proposal/approve",
        json={"approved_by": "operator"},
    )
    assert unauthorized.status_code == 401

    authenticated = client.post(
        "/v1/patches/not-a-real-proposal/approve",
        headers={"x-doctor-operator-token": "test-operator-token"},
        json={"approved_by": "operator"},
    )
    assert authenticated.status_code == 404


def test_side_effect_enabled_http_boundary_requires_configured_operator_token(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(
            allow_workflow_mutation=True,
            allow_execution_retry=True,
            operator_token=None,
        ),
    )
    client = TestClient(main_module.app)

    response = client.post(
        "/v1/patches/not-a-real-proposal/apply-retry",
        headers={"x-doctor-operator-token": "anything"},
    )
    assert response.status_code == 503
