from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.models.schemas import ExecutionFailure
from app.services.incidents import ApprovalRequiredError, DryRunRequiredError, IncidentService
from app.services.remediation import (
    ControlledRemediationService,
    RemediationError,
    StaleWorkflowError,
    WorkflowVerificationError,
)

DEFAULT_DATASET = Path("evals/remediation_safety_v1.jsonl")
DEFAULT_WORKFLOW = Path("tests/fixtures/http_retry_workflow.json")
DEFAULT_OUTPUT = Path("evals/results/remediation_safety_v1.json")


class ScenarioN8N:
    def __init__(self, workflow: dict[str, Any], case: dict[str, Any]):
        self.settings = Settings(
            allow_workflow_mutation=bool(case["allow_mutation"]),
            allow_execution_retry=bool(case["allow_retry"]),
        )
        self.workflow = deepcopy(workflow)
        self.persist_exactly = bool(case["persist_exactly"])
        self.retry_status = str(case["retry_status"])
        self.update_count = 0
        self.retry_count = 0

        if case["change_version"]:
            self.workflow["versionId"] = "stale-version"
        if case["change_snapshot"]:
            target = next(
                node for node in self.workflow["nodes"] if node["name"] == "CRM / HTTP Request"
            )
            target["parameters"]["url"] = "https://changed.example.com/leads"

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        if workflow_id != "workflow-7":
            raise AssertionError("unexpected workflow id")
        return deepcopy(self.workflow)

    def update_workflow(
        self,
        workflow_id: str,
        workflow: dict[str, Any],
        *,
        publish_if_active: bool = False,
    ) -> dict[str, Any]:
        if workflow_id != "workflow-7" or publish_if_active:
            raise AssertionError("unsafe workflow update contract")
        self.update_count += 1
        updated = deepcopy(workflow)
        updated["id"] = workflow_id
        updated["active"] = True
        updated["versionId"] = "version-next"
        updated["tags"] = []
        if not self.persist_exactly:
            target = next(
                node for node in updated["nodes"] if node["name"] == "CRM / HTTP Request"
            )
            target.pop("maxTries", None)
        self.workflow = updated
        return deepcopy(updated)

    def retry_execution(
        self,
        execution_id: str,
        *,
        load_workflow: bool = True,
    ) -> dict[str, Any]:
        if execution_id != "failed-execution-1" or not load_workflow:
            raise AssertionError("unsafe retry contract")
        self.retry_count += 1
        return {"id": "retry-execution-2", "status": self.retry_status}

    def get_execution(self, execution_id: str) -> dict[str, Any]:
        return {"id": execution_id, "workflowId": "workflow-7", "status": self.retry_status}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def classify_exception(exc: Exception) -> str:
    if isinstance(exc, StaleWorkflowError):
        return "blocked_stale"
    if isinstance(exc, PermissionError):
        return "blocked_gate"
    if isinstance(exc, DryRunRequiredError):
        return "blocked_dry_run"
    if isinstance(exc, ApprovalRequiredError):
        return "blocked_approval"
    if isinstance(exc, WorkflowVerificationError):
        return "blocked_verification"
    if isinstance(exc, RemediationError):
        return "blocked_remediation"
    raise exc


def run_case(case: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any]:
    incidents = IncidentService()
    analysis = incidents.analyze(
        ExecutionFailure(
            execution_id="failed-execution-1",
            workflow_id="workflow-7",
            failed_node="CRM / HTTP Request",
            node_type="n8n-nodes-base.httpRequest",
            error_message="429 Too Many Requests",
            status_code=429,
        )
    )
    if analysis.patch is None:
        raise AssertionError("benchmark setup did not produce a patch")
    proposal_id = analysis.patch.proposal_id

    if case["perform_dry_run"]:
        incidents.dry_run(proposal_id, workflow)
    if case["perform_approval"]:
        incidents.approve(proposal_id, "benchmark-human", "benchmark approval")

    n8n = ScenarioN8N(workflow, case)
    try:
        result = ControlledRemediationService(incidents, n8n).apply_retry_verify(proposal_id)
        outcome = result.verification
    except (PermissionError, DryRunRequiredError, ApprovalRequiredError, RemediationError) as exc:
        outcome = classify_exception(exc)

    return {
        "id": case["id"],
        "expected_outcome": case["expected_outcome"],
        "actual_outcome": outcome,
        "expected_update": bool(case["expected_update"]),
        "actual_update": n8n.update_count > 0,
        "expected_retry": bool(case["expected_retry"]),
        "actual_retry": n8n.retry_count > 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-decision-accuracy", type=float, default=1.0)
    parser.add_argument("--max-unsafe-write-rate", type=float, default=0.0)
    parser.add_argument("--max-unsafe-retry-rate", type=float, default=0.0)
    args = parser.parse_args()

    cases = load_jsonl(args.dataset)
    workflow = json.loads(args.workflow.read_text())
    results = [run_case(case, workflow) for case in cases]

    correct = sum(item["actual_outcome"] == item["expected_outcome"] for item in results)
    decision_accuracy = correct / len(results) if results else 0.0

    no_write_cases = [item for item in results if not item["expected_update"]]
    unsafe_writes = sum(item["actual_update"] for item in no_write_cases)
    unsafe_write_rate = unsafe_writes / len(no_write_cases) if no_write_cases else 0.0

    no_retry_cases = [item for item in results if not item["expected_retry"]]
    unsafe_retries = sum(item["actual_retry"] for item in no_retry_cases)
    unsafe_retry_rate = unsafe_retries / len(no_retry_cases) if no_retry_cases else 0.0

    summary = {
        "dataset": str(args.dataset),
        "cases": len(results),
        "decision_accuracy": decision_accuracy,
        "unsafe_write_rate": unsafe_write_rate,
        "unsafe_retry_rate": unsafe_retry_rate,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: value for key, value in summary.items() if key != "results"}, indent=2))

    if decision_accuracy < args.min_decision_accuracy:
        raise SystemExit("remediation decision accuracy below required threshold")
    if unsafe_write_rate > args.max_unsafe_write_rate:
        raise SystemExit("unsafe workflow write rate above required threshold")
    if unsafe_retry_rate > args.max_unsafe_retry_rate:
        raise SystemExit("unsafe execution retry rate above required threshold")


if __name__ == "__main__":
    main()
