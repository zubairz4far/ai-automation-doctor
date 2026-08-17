from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.models.schemas import ExecutionFailure
from app.services.diagnoser import DiagnosisEngine

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate deterministic failure classification.")
    parser.add_argument(
        "--dataset",
        default="evals/failure_taxonomy_v1.jsonl",
        help="JSONL dataset path relative to the repository root.",
    )
    parser.add_argument(
        "--output",
        default="evals/results/taxonomy_v1.json",
        help="Output JSON path relative to the repository root.",
    )
    parser.add_argument("--min-classification-accuracy", type=float, default=1.0)
    parser.add_argument("--min-retry-safety-accuracy", type=float, default=1.0)
    return parser.parse_args()


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def main() -> None:
    args = parse_args()
    dataset = resolve_path(args.dataset)
    rows = [json.loads(line) for line in dataset.read_text().splitlines() if line.strip()]
    if not rows:
        raise SystemExit("Taxonomy benchmark dataset is empty.")

    engine = DiagnosisEngine()
    correct_class = 0
    correct_retry = 0
    details = []

    for row in rows:
        result = engine.diagnose(
            ExecutionFailure(
                execution_id=row["id"],
                workflow_id="fixture",
                failed_node=row.get("failed_node") or "HTTP Request",
                node_type=row.get("node_type") or "n8n-nodes-base.httpRequest",
                error_message=row["error_message"],
                error_stack=row.get("error_stack"),
                error_code=row.get("error_code"),
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
                "expected_retry_safe": row["retry_safe"],
                "predicted_retry_safe": result.retry_safe,
                "retry_ok": retry_ok,
                "confidence": result.confidence,
            }
        )

    classification_accuracy = correct_class / len(rows)
    retry_safety_accuracy = correct_retry / len(rows)
    summary = {
        "dataset": str(dataset.relative_to(ROOT)),
        "cases": len(rows),
        "classification_accuracy": classification_accuracy,
        "retry_safety_accuracy": retry_safety_accuracy,
        "details": details,
    }
    output = resolve_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "details"}, indent=2))

    if classification_accuracy < args.min_classification_accuracy:
        raise SystemExit("Classification accuracy is below the configured benchmark threshold.")
    if retry_safety_accuracy < args.min_retry_safety_accuracy:
        raise SystemExit("Retry-safety accuracy is below the configured benchmark threshold.")


if __name__ == "__main__":
    main()
