import json

import httpx

from app.models.schemas import AIInsight, ExecutionFailure, FailureClass
from app.services.ai_diagnoser import GuardedDiagnosisEngine, OpenAICompatibleInsightProvider


class StubProvider:
    name = "stub"
    model = "stub-model"

    def __init__(self, insight: AIInsight | None = None, error: Exception | None = None):
        self.insight = insight
        self.error = error
        self.calls = 0

    def analyze(self, failure, baseline):
        self.calls += 1
        if self.error:
            raise self.error
        return self.insight


def unknown_failure() -> ExecutionFailure:
    return ExecutionFailure(
        execution_id="execution-unknown",
        workflow_id="workflow-1",
        workflow_name="Sensitive customer workflow",
        failed_node="Customer Secret Node",
        node_type="n8n-nodes-base.httpRequest",
        error_message="Upstream returned a strange vendor-specific failure",
        input_snapshot={"customer_email": "private@example.com"},
        workflow_snapshot={"credentials": {"apiKey": "never-send-this"}},
    )


def test_high_confidence_deterministic_result_skips_ai():
    provider = StubProvider(
        AIInsight(
            failure_class=FailureClass.UNKNOWN,
            confidence=0.99,
            root_cause="Should not be used.",
            evidence=["unused"],
            recommended_action="unused",
            provider="stub",
            model="stub-model",
        )
    )
    engine = GuardedDiagnosisEngine(provider=provider, enabled=True)

    result = engine.diagnose(
        ExecutionFailure(
            execution_id="e429",
            workflow_id="w1",
            failed_node="HTTP Request",
            error_message="Too many requests",
            status_code=429,
        )
    )

    assert result.failure_class == FailureClass.RATE_LIMIT
    assert result.retry_safe is True
    assert result.ai_insight is None
    assert provider.calls == 0


def test_unknown_result_gets_advisory_without_changing_authoritative_fields():
    provider = StubProvider(
        AIInsight(
            failure_class=FailureClass.CONFIGURATION,
            confidence=0.83,
            root_cause="A vendor-specific configuration mismatch is plausible.",
            evidence=["Vendor-specific failure text"],
            recommended_action="Inspect the node configuration manually.",
            provider="stub",
            model="stub-model",
        )
    )
    engine = GuardedDiagnosisEngine(provider=provider, enabled=True)

    result = engine.diagnose(unknown_failure())

    assert result.failure_class == FailureClass.UNKNOWN
    assert result.confidence == 0.35
    assert result.retry_safe is False
    assert result.ai_insight is not None
    assert result.ai_insight.failure_class == FailureClass.CONFIGURATION
    assert provider.calls == 1


def test_provider_failure_falls_back_to_deterministic_result():
    provider = StubProvider(error=RuntimeError("provider unavailable"))
    engine = GuardedDiagnosisEngine(provider=provider, enabled=True)

    result = engine.diagnose(unknown_failure())

    assert result.failure_class == FailureClass.UNKNOWN
    assert result.retry_safe is False
    assert result.ai_insight is None
    assert provider.calls == 1


def test_provider_receives_privacy_minimized_context_without_baseline_anchoring():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "failure_class": "configuration",
                                    "confidence": 0.76,
                                    "root_cause": "Likely vendor-specific configuration issue.",
                                    "evidence": ["Unclassified vendor error"],
                                    "recommended_action": "Inspect the node configuration manually.",
                                }
                            )
                        }
                    }
                ]
            },
        )

    provider = OpenAICompatibleInsightProvider(
        base_url="http://ai.local/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    engine = GuardedDiagnosisEngine(provider=provider, enabled=True)

    result = engine.diagnose(unknown_failure())

    assert result.ai_insight is not None
    user_context = json.loads(captured["messages"][1]["content"])
    serialized = json.dumps(user_context)
    assert "private@example.com" not in serialized
    assert "never-send-this" not in serialized
    assert "Sensitive customer workflow" not in serialized
    assert "Customer Secret Node" not in serialized
    assert "input_snapshot" not in serialized
    assert "workflow_snapshot" not in serialized
    assert "deterministic_baseline" not in user_context
    assert "retry_safe" not in serialized
    assert set(user_context) == {
        "node_type",
        "error_message",
        "error_stack",
        "error_code",
        "status_code",
    }


def test_provider_normalizes_single_evidence_string():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "failure_class": "configuration",
                                    "confidence": 0.76,
                                    "root_cause": "Likely vendor-specific configuration issue.",
                                    "evidence": "Unclassified vendor error",
                                    "recommended_action": "Inspect the node configuration manually.",
                                }
                            )
                        }
                    }
                ]
            },
        )

    provider = OpenAICompatibleInsightProvider(
        base_url="http://ai.local/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    engine = GuardedDiagnosisEngine(provider=provider, enabled=True)

    result = engine.diagnose(unknown_failure())

    assert result.ai_insight is not None
    assert result.ai_insight.evidence == ["Unclassified vendor error"]


def test_provider_output_cannot_smuggle_retry_or_patch_decisions():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "failure_class": "network",
                                    "confidence": 0.99,
                                    "root_cause": "Claimed transient network issue.",
                                    "evidence": ["model guess"],
                                    "recommended_action": "Retry automatically.",
                                    "retry_safe": True,
                                    "patch": {"op": "replace", "path": "/credentials"},
                                }
                            )
                        }
                    }
                ]
            },
        )

    provider = OpenAICompatibleInsightProvider(
        base_url="http://ai.local/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    engine = GuardedDiagnosisEngine(provider=provider, enabled=True)

    result = engine.diagnose(unknown_failure())

    assert result.failure_class == FailureClass.UNKNOWN
    assert result.retry_safe is False
    assert result.ai_insight is None
