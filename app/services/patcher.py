from __future__ import annotations

from uuid import uuid4

from app.models.schemas import (
    Diagnosis,
    ExecutionFailure,
    FailureClass,
    PatchOperation,
    PatchProposal,
    RiskLevel,
)


def escape_path_segment(value: str) -> str:
    """Escape a logical path segment using JSON Pointer escaping rules."""
    return value.replace("~", "~0").replace("/", "~1")


class PatchPlanner:
    """Creates conservative logical patches using n8n node-level retry fields."""

    def propose(self, failure: ExecutionFailure, diagnosis: Diagnosis) -> PatchProposal | None:
        node = failure.failed_node
        if not node:
            return None

        node_segment = escape_path_segment(node)
        operations: list[PatchOperation] = []
        risk = RiskLevel.MEDIUM

        if diagnosis.failure_class == FailureClass.RATE_LIMIT:
            operations = [
                PatchOperation(
                    op="add",
                    path=f"/nodes/{node_segment}/retryOnFail",
                    value=True,
                    reason="Enable bounded retry behavior for upstream throttling.",
                ),
                PatchOperation(
                    op="add",
                    path=f"/nodes/{node_segment}/maxTries",
                    value=3,
                    reason="Cap retries to avoid runaway execution loops.",
                ),
                PatchOperation(
                    op="add",
                    path=f"/nodes/{node_segment}/waitBetweenTries",
                    value=2000,
                    reason="Add delay between attempts to reduce immediate re-throttling.",
                ),
            ]
            risk = RiskLevel.LOW
        elif diagnosis.failure_class in {FailureClass.TIMEOUT, FailureClass.NETWORK}:
            operations = [
                PatchOperation(
                    op="add",
                    path=f"/nodes/{node_segment}/retryOnFail",
                    value=True,
                    reason="Transient transport failures are retry candidates.",
                ),
                PatchOperation(
                    op="add",
                    path=f"/nodes/{node_segment}/maxTries",
                    value=2,
                    reason="Keep retries bounded.",
                ),
            ]
            risk = RiskLevel.LOW
        else:
            return None

        return PatchProposal(
            proposal_id=str(uuid4()),
            workflow_id=failure.workflow_id,
            diagnosis=diagnosis,
            operations=operations,
            risk=risk,
            requires_human_approval=True,
            auto_apply_allowed=False,
            validation_notes=[
                "Only n8n node-level retry fields are proposed.",
                "No credential values are added or modified.",
                "No Code/Execute Command node content is generated.",
                "Proposal must pass workflow-aware validation before application.",
            ],
        )
