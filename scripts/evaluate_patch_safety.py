from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.models.schemas import (
    Diagnosis,
    FailureClass,
    PatchOperation,
    PatchProposal,
    RiskLevel,
)
from app.services.validator import PatchValidationError, PatchValidator

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate patch-validator safety decisions.")
    parser.add_argument(
        "--dataset",
        default="evals/patch_safety_v1.jsonl",
        help="JSONL dataset path relative to the repository root.",
    )
    parser.add_argument(
        "--output",
        default="evals/results/patch_safety_v1.json",
        help="Output JSON path relative to the repository root.",
    )
    parser.add_argument("--min-decision-accuracy", type=float, default=1.0)
    parser.add_argument("--max-false-accept-rate", type=float, default=0.0)
    return parser.parse_args()


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def baseline_diagnosis() -> Diagnosis:
    return Diagnosis(
        failure_class=FailureClass.RATE_LIMIT,
        confidence=0.99,
        root_cause="Fixture throttling failure.",
        evidence=["HTTP 429 detected."],
        recommended_action="Use bounded retry/backoff.",
        retry_safe=True,
    )


def main() -> None:
    args = parse_args()
    dataset = resolve_path(args.dataset)
    rows = [json.loads(line) for line in dataset.read_text().splitlines() if line.strip()]
    if not rows:
        raise SystemExit("Patch safety benchmark dataset is empty.")

    validator = PatchValidator()
    correct = 0
    unsafe_cases = 0
    false_accepts = 0
    safe_cases = 0
    false_rejects = 0
    details = []

    for row in rows:
        expected_valid = bool(row["expected_valid"])
        safe_cases += int(expected_valid)
        unsafe_cases += int(not expected_valid)
        proposal = PatchProposal(
            proposal_id=row["id"],
            workflow_id="workflow-fixture",
            diagnosis=baseline_diagnosis(),
            operations=[PatchOperation(**operation) for operation in row["operations"]],
            risk=RiskLevel.LOW,
            requires_human_approval=row.get("requires_human_approval", True),
            auto_apply_allowed=row.get("auto_apply_allowed", False),
        )

        error: str | None = None
        try:
            validator.validate(proposal)
            predicted_valid = True
        except PatchValidationError as exc:
            predicted_valid = False
            error = str(exc)

        decision_ok = predicted_valid == expected_valid
        correct += int(decision_ok)
        false_accepts += int(not expected_valid and predicted_valid)
        false_rejects += int(expected_valid and not predicted_valid)
        details.append(
            {
                "id": row["id"],
                "expected_valid": expected_valid,
                "predicted_valid": predicted_valid,
                "decision_ok": decision_ok,
                "validation_error": error,
            }
        )

    decision_accuracy = correct / len(rows)
    false_accept_rate = false_accepts / unsafe_cases if unsafe_cases else 0.0
    false_reject_rate = false_rejects / safe_cases if safe_cases else 0.0
    summary = {
        "dataset": str(dataset.relative_to(ROOT)),
        "cases": len(rows),
        "safe_cases": safe_cases,
        "unsafe_cases": unsafe_cases,
        "decision_accuracy": decision_accuracy,
        "false_accept_rate": false_accept_rate,
        "false_reject_rate": false_reject_rate,
        "details": details,
    }

    output = resolve_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: value for key, value in summary.items() if key != "details"}, indent=2))

    if decision_accuracy < args.min_decision_accuracy:
        raise SystemExit("Patch safety decision accuracy is below the configured threshold.")
    if false_accept_rate > args.max_false_accept_rate:
        raise SystemExit("Patch safety false-accept rate exceeds the configured threshold.")


if __name__ == "__main__":
    main()
