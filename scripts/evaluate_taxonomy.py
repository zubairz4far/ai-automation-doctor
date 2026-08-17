from __future__ import annotations

import json
from pathlib import Path

from app.models.schemas import ExecutionFailure
from app.services.diagnoser import DiagnosisEngine


def main() -> None:
    dataset = Path("evals/failure_taxonomy_v1.jsonl")
    rows = [json.loads(line) for line in dataset.read_text().splitlines() if line.strip()]
    engine = DiagnosisEngine()
    correct_class = 0
    correct_retry = 0
    details = []

    for row in rows:
        result = engine.diagnose(
            ExecutionFailure(
                execution_id=row["id"],
                workflow_id="fixture",
                failed_node="HTTP Request",
                node_type="n8n-nodes-base.httpRequest",
                error_message=row["error_message"],
                status_code=row.get("status_code"),
            )
        )
        class_ok = result.failure_class.value == row["expected_class"]
        retry_ok = result.retry_safe == row["retry_safe"]
        correct_class += int(class_ok)
        correct_retry += int(retry_ok)
        details.append(
            {
                "id": row["id"],
                "expected_class": row["expected_class"],
                "predicted_class": result.failure_class.value,
                "class_ok": class_ok,
                "retry_ok": retry_ok,
                "confidence": result.confidence,
            }
        )

    summary = {
        "cases": len(rows),
        "classification_accuracy": correct_class / len(rows),
        "retry_safety_accuracy": correct_retry / len(rows),
        "details": details,
    }
    out = Path("evals/results/taxonomy_v1.json")
    out.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "details"}, indent=2))


if __name__ == "__main__":
    main()
