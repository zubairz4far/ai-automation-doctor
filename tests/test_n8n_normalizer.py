import pytest

from app.services.n8n_normalizer import N8NExecutionNormalizationError, N8NExecutionNormalizer


def test_normalizes_public_api_execution_without_retaining_credentials():
    payload = {
        "id": "987",
        "workflowId": "wf-1",
        "status": "error",
        "workflowData": {
            "id": "wf-1",
            "name": "Lead sync",
            "nodes": [
                {
                    "name": "HTTP Request",
                    "type": "n8n-nodes-base.httpRequest",
                    "credentials": {"httpHeaderAuth": {"id": "secret-id", "name": "Prod"}},
                }
            ],
        },
        "data": {
            "resultData": {
                "lastNodeExecuted": "HTTP Request",
                "error": {
                    "message": "Authorization failed - please check your credentials",
                    "httpCode": "401",
                    "stack": "NodeApiError: Authorization failed",
                    "node": {
                        "name": "HTTP Request",
                        "type": "n8n-nodes-base.httpRequest",
                        "credentials": {
                            "httpHeaderAuth": {"id": "secret-id", "name": "Prod"}
                        },
                    },
                },
            }
        },
    }

    failure = N8NExecutionNormalizer().normalize(payload)

    assert failure.execution_id == "987"
    assert failure.workflow_id == "wf-1"
    assert failure.workflow_name == "Lead sync"
    assert failure.failed_node == "HTTP Request"
    assert failure.node_type == "n8n-nodes-base.httpRequest"
    assert failure.status_code == 401
    assert "secret-id" not in failure.model_dump_json()
    assert failure.workflow_snapshot is None
    assert failure.input_snapshot is None


def test_falls_back_to_run_data_error():
    payload = {
        "id": "988",
        "workflowId": "wf-2",
        "status": "error",
        "data": {
            "resultData": {
                "lastNodeExecuted": "Gmail Trigger",
                "runData": {
                    "Gmail Trigger": [
                        {
                            "error": {
                                "message": "The connection cannot be established",
                                "httpCode": "EAI_AGAIN",
                                "description": "getaddrinfo EAI_AGAIN www.googleapis.com",
                                "node": {
                                    "name": "Gmail Trigger",
                                    "type": "n8n-nodes-base.gmailTrigger",
                                },
                            }
                        }
                    ]
                },
            }
        },
    }

    failure = N8NExecutionNormalizer().normalize(payload)

    assert failure.failed_node == "Gmail Trigger"
    assert failure.error_code == "EAI_AGAIN"
    assert failure.status_code is None
    assert "EAI_AGAIN" in (failure.error_stack or "")


def test_normalizes_ui_style_error_export():
    payload = {
        "id": "989",
        "workflowId": "wf-3",
        "status": "error",
        "errorMessage": "Too many requests",
        "errorDetails": {
            "httpCode": "429",
            "rawErrorMessage": ["429 - rate limit exceeded"],
        },
        "n8nDetails": {
            "nodeName": "HTTP Request",
            "nodeType": "n8n-nodes-base.httpRequest",
            "stackTrace": ["NodeApiError: Too many requests"],
        },
    }

    failure = N8NExecutionNormalizer().normalize(payload)

    assert failure.error_message == "Too many requests"
    assert failure.status_code == 429
    assert failure.failed_node == "HTTP Request"


def test_rejects_successful_execution():
    with pytest.raises(N8NExecutionNormalizationError, match="not a failed execution"):
        N8NExecutionNormalizer().normalize(
            {
                "id": "990",
                "workflowId": "wf-4",
                "status": "success",
                "data": {"resultData": {}},
            }
        )


def test_rejects_payload_without_error_message():
    with pytest.raises(N8NExecutionNormalizationError, match="usable error message"):
        N8NExecutionNormalizer().normalize(
            {
                "id": "991",
                "workflowId": "wf-5",
                "status": "error",
                "data": {"resultData": {}},
            }
        )
