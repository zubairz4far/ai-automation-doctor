from pathlib import Path

from app.models.schemas import AIInsight, FailureClass
from app.services.diagnoser import DiagnosisEngine
from scripts.evaluate_ai_diagnosis import build_failure, evaluate_rows, load_rows

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals/ai_diagnosis_v1.jsonl"


class LabelProvider:
    name = "label-provider"
    model = "label-model"

    def analyze(self, failure, baseline):
        expected = failure.error_code
        return AIInsight(
            failure_class=FailureClass(expected),
            confidence=0.9,
            root_cause="Fixture prediction.",
            evidence=["Fixture label"],
            recommended_action="Manual review.",
            provider=self.name,
            model=self.model,
        )


class FailingProvider:
    name = "failing-provider"
    model = "failing-model"

    def analyze(self, failure, baseline):
        raise ValueError("malformed provider output")


def test_ai_challenge_dataset_is_nonempty_and_baseline_abstains():
    rows = load_rows(DATASET)
    engine = DiagnosisEngine()

    assert len(rows) == 32
    for row in rows:
        result = engine.diagnose(build_failure(row))
        assert result.failure_class == FailureClass.UNKNOWN, row["id"]


def test_evaluator_scores_valid_model_predictions():
    rows = [
        {
            "id": "case-1",
            "expected_class": "authentication",
            "error_message": "opaque failure one",
            "error_code": "authentication",
        },
        {
            "id": "case-2",
            "expected_class": "network",
            "error_message": "opaque failure two",
            "error_code": "network",
        },
    ]

    summary = evaluate_rows(rows, LabelProvider(), model_name="label-model")

    assert summary["cases"] == 2
    assert summary["baseline_unknown_rate"] == 1.0
    assert summary["baseline_accuracy"] == 0.0
    assert summary["ai_accuracy"] == 1.0
    assert summary["schema_validity_rate"] == 1.0
    assert summary["provider_failure_rate"] == 0.0
    assert summary["ai_accuracy_delta_pp"] == 100.0


def test_evaluator_counts_provider_failures_without_crashing():
    rows = [
        {
            "id": "case-1",
            "expected_class": "configuration",
            "error_message": "opaque failure",
        }
    ]

    summary = evaluate_rows(rows, FailingProvider(), model_name="failing-model")

    assert summary["cases"] == 1
    assert summary["ai_accuracy"] == 0.0
    assert summary["schema_validity_rate"] == 0.0
    assert summary["provider_failure_rate"] == 1.0
    assert summary["details"][0]["error_kind"] == "provider_or_parse_failure"
