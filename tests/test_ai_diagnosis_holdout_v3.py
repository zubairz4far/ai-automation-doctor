import json
from collections import Counter
from pathlib import Path

from app.models.schemas import ExecutionFailure, FailureClass
from app.services.diagnoser import DiagnosisEngine

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "ai_diagnosis_holdout_v3.jsonl"


def test_second_blind_holdout_is_balanced_and_deterministic_baseline_abstains():
    rows = [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]

    assert len(rows) == 32
    counts = Counter(row["expected_class"] for row in rows)
    assert counts == {
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
        failure = ExecutionFailure(
            execution_id=row["id"],
            workflow_id="blind-holdout-v3",
            failed_node="HTTP Request",
            node_type=row.get("node_type") or "n8n-nodes-base.httpRequest",
            error_message=row["error_message"],
            error_stack=row.get("error_stack"),
            error_code=row.get("error_code"),
            status_code=row.get("status_code"),
        )
        diagnosis = engine.diagnose(failure)
        assert diagnosis.failure_class == FailureClass.UNKNOWN, row["id"]
