from app.models.schemas import ExecutionFailure, FailureClass
from app.services.diagnoser import DiagnosisEngine


def failure(message: str, code: int | None = None) -> ExecutionFailure:
    return ExecutionFailure(
        execution_id="e1",
        workflow_id="w1",
        workflow_name="Lead sync",
        failed_node="HTTP Request",
        node_type="n8n-nodes-base.httpRequest",
        error_message=message,
        status_code=code,
    )


def test_auth_failure_is_not_retry_safe():
    result = DiagnosisEngine().diagnose(failure("401 Unauthorized", 401))
    assert result.failure_class == FailureClass.AUTH
    assert result.retry_safe is False


def test_rate_limit_is_retry_safe():
    result = DiagnosisEngine().diagnose(failure("Too Many Requests", 429))
    assert result.failure_class == FailureClass.RATE_LIMIT
    assert result.retry_safe is True


def test_mapping_failure_detected():
    result = DiagnosisEngine().diagnose(failure("Cannot read properties of undefined"))
    assert result.failure_class == FailureClass.DATA_MAPPING
