from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from app.models.schemas import ExecutionFailure, FailureClass
from app.services.ai_diagnoser import AIInsightProvider, OpenAICompatibleInsightProvider
from app.services.diagnoser import DiagnosisEngine

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate a real OpenAI-compatible model on hard AI diagnosis cases."
    )
    parser.add_argument("--dataset", default="evals/ai_diagnosis_v1.jsonl")
    parser.add_argument("--output", default="evals/results/ai_diagnosis_v1.json")
    parser.add_argument(
        "--api-base-url",
        default=os.getenv("AI_API_BASE_URL", "http://localhost:8000/v1"),
    )
    parser.add_argument("--api-key", default=os.getenv("AI_API_KEY"))
    parser.add_argument("--model", default=os.getenv("AI_MODEL", "Qwen/Qwen3-1.7B"))
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--min-ai-accuracy", type=float, default=0.0)
    parser.add_argument("--min-schema-validity", type=float, default=0.0)
    parser.add_argument("--max-provider-failure-rate", type=float, default=1.0)
    parser.add_argument("--min-baseline-unknown-rate", type=float, default=1.0)
    return parser.parse_args()


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load_rows(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if limit is not None:
        rows = rows[:limit]
    if not rows:
        raise ValueError("AI diagnosis benchmark dataset is empty.")
    return rows


def build_failure(row: dict[str, Any]) -> ExecutionFailure:
    return ExecutionFailure(
        execution_id=row["id"],
        workflow_id="ai-eval-fixture",
        failed_node=row.get("failed_node") or "HTTP Request",
        node_type=row.get("node_type") or "n8n-nodes-base.httpRequest",
        error_message=row["error_message"],
        error_stack=row.get("error_stack"),
        error_code=row.get("error_code"),
        status_code=row.get("status_code"),
    )


def evaluate_rows(
    rows: list[dict[str, Any]],
    provider: AIInsightProvider,
    *,
    model_name: str,
) -> dict[str, Any]:
    baseline_engine = DiagnosisEngine()
    baseline_correct = 0
    baseline_unknown = 0
    ai_correct = 0
    valid_outputs = 0
    schema_failures = 0
    provider_failures = 0
    expected_counts: Counter[str] = Counter()
    per_class_correct: defaultdict[str, int] = defaultdict(int)
    per_class_valid: defaultdict[str, int] = defaultdict(int)
    details: list[dict[str, Any]] = []

    for row in rows:
        expected = row["expected_class"]
        FailureClass(expected)
        expected_counts[expected] += 1
        failure = build_failure(row)
        baseline = baseline_engine.diagnose(failure)
        baseline_ok = baseline.failure_class.value == expected
        baseline_correct += int(baseline_ok)
        baseline_unknown += int(baseline.failure_class == FailureClass.UNKNOWN)

        predicted: str | None = None
        error_kind: str | None = None
        try:
            insight = provider.analyze(failure, baseline)
            if insight is None:
                provider_failures += 1
                error_kind = "empty_provider_result"
            else:
                predicted = insight.failure_class.value
                valid_outputs += 1
                per_class_valid[expected] += 1
                if predicted == expected:
                    ai_correct += 1
                    per_class_correct[expected] += 1
        except ValidationError:
            schema_failures += 1
            error_kind = "schema_validation"
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
            provider_failures += 1
            error_kind = "provider_or_parse_failure"

        details.append(
            {
                "id": row["id"],
                "expected_class": expected,
                "baseline_class": baseline.failure_class.value,
                "baseline_confidence": baseline.confidence,
                "baseline_ok": baseline_ok,
                "ai_class": predicted,
                "ai_ok": predicted == expected if predicted is not None else False,
                "error_kind": error_kind,
            }
        )

    cases = len(rows)
    ai_accuracy = ai_correct / cases
    baseline_accuracy = baseline_correct / cases
    schema_validity = valid_outputs / cases
    provider_failure_rate = provider_failures / cases
    schema_failure_rate = schema_failures / cases

    per_class = {}
    for label, count in sorted(expected_counts.items()):
        valid = per_class_valid[label]
        per_class[label] = {
            "cases": count,
            "valid_outputs": valid,
            "correct": per_class_correct[label],
            "overall_accuracy": per_class_correct[label] / count,
            "accuracy_on_valid_outputs": per_class_correct[label] / valid if valid else 0.0,
        }

    return {
        "dataset": "evals/ai_diagnosis_v1.jsonl",
        "model": model_name,
        "cases": cases,
        "baseline_accuracy": baseline_accuracy,
        "baseline_unknown_rate": baseline_unknown / cases,
        "ai_accuracy": ai_accuracy,
        "ai_accuracy_delta_pp": (ai_accuracy - baseline_accuracy) * 100,
        "schema_validity_rate": schema_validity,
        "schema_failure_rate": schema_failure_rate,
        "provider_failure_rate": provider_failure_rate,
        "ai_accuracy_on_valid_outputs": ai_correct / valid_outputs if valid_outputs else 0.0,
        "per_class": per_class,
        "details": details,
    }


def main() -> None:
    args = parse_args()
    dataset = resolve_path(args.dataset)
    rows = load_rows(dataset, args.limit)
    provider = OpenAICompatibleInsightProvider(
        base_url=args.api_base_url,
        api_key=args.api_key,
        model=args.model,
        timeout_seconds=args.timeout_seconds,
    )
    summary = evaluate_rows(rows, provider, model_name=args.model)
    summary["dataset"] = str(dataset.relative_to(ROOT)) if dataset.is_relative_to(ROOT) else str(dataset)

    output = resolve_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k not in {"details", "per_class"}}, indent=2))

    if summary["baseline_unknown_rate"] < args.min_baseline_unknown_rate:
        raise SystemExit("Baseline unknown rate is below the configured challenge-set threshold.")
    if summary["ai_accuracy"] < args.min_ai_accuracy:
        raise SystemExit("AI diagnosis accuracy is below the configured benchmark threshold.")
    if summary["schema_validity_rate"] < args.min_schema_validity:
        raise SystemExit("AI schema-validity rate is below the configured benchmark threshold.")
    if summary["provider_failure_rate"] > args.max_provider_failure_rate:
        raise SystemExit("AI provider failure rate is above the configured benchmark threshold.")


if __name__ == "__main__":
    main()
