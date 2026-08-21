import json
from collections import Counter
from pathlib import Path

from app.models.schemas import ExecutionFailure, FailureClass
from app.services.diagnoser import DiagnosisEngine


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "ai_diagnosis_holdout_v2.jsonl"


def test_holdout_is_balanced_and_deterministic_baseline_abstains():
    rows = [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]
    assert len(rows) == 32
    assert Counter(row["expected_class"] for row in rows) == {
        "authentication": 4,
        "rate_limit": 4,
        "timeout": 4,
        "network": 4,
        "data_mapping": 4,
        "webhook": 4,
        "configuration": 4,
        "unknown": 4,
    }

    engine = DiagnosisEngine()
    for row in rows:
        FailureClass(row["expected_class"])
        diagnosis = engine.diagnose(
            ExecutionFailure(
                execution_id=row["id"],
                workflow_id="holdout-fixture",
                failed_node="HTTP Request",
                node_type=row["node_type"],
                error_message=row["error_message"],
                error_stack=row.get("error_stack"),
                error_code=row.get("error_code"),
                status_code=row.get("status_code"),
            )
        )
        assert diagnosis.failure_class == FailureClass.UNKNOWN, row["id"]
        assert diagnosis.confidence == 0.35, row["id"]
