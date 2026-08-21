import json

import httpx

from app.models.schemas import ExecutionFailure
from app.services.ai_diagnoser import OpenAICompatibleInsightProvider
from app.services.diagnoser import DiagnosisEngine


def test_prompt_defines_boundary_rules_without_baseline_anchoring():
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
                                    "confidence": 0.82,
                                    "root_cause": "The selected connector contract is incompatible with the request.",
                                    "evidence": ["Selected action expects a different request contract."],
                                    "recommended_action": "Review the selected action and node configuration.",
                                }
                            )
                        }
                    }
                ]
            },
        )

    failure = ExecutionFailure(
        execution_id="prompt-contract",
        workflow_id="workflow-1",
        node_type="n8n-nodes-base.httpRequest",
        error_message="Selected action expects a different request contract.",
    )
    baseline = DiagnosisEngine().diagnose(failure)
    provider = OpenAICompatibleInsightProvider(
        base_url="http://ai.local/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )

    insight = provider.analyze(failure, baseline)
    assert insight is not None

    system_prompt = captured["messages"][0]["content"]
    user_context = json.loads(captured["messages"][1]["content"])

    assert "configuration rather than data_mapping" in system_prompt
    assert "webhook rather than network" in system_prompt
    assert "Opaque vendor/internal/policy codes" in system_prompt
    assert "do not invent evidence to avoid unknown" in system_prompt
    assert "deterministic_baseline" not in user_context
    assert "retry_safe" not in json.dumps(user_context)
