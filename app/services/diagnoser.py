from __future__ import annotations

from app.models.schemas import Diagnosis, ExecutionFailure, FailureClass


class DiagnosisEngine:
    """Deterministic baseline used as the evaluation anchor before adding an LLM."""

    def diagnose(self, failure: ExecutionFailure) -> Diagnosis:
        text = " ".join(
            part for part in [failure.error_message, failure.error_stack or ""] if part
        ).lower()
        code = failure.status_code

        if code in {401, 403} or any(
            token in text
            for token in ("unauthorized", "forbidden", "invalid api key", "invalid token", "oauth")
        ):
            return Diagnosis(
                failure_class=FailureClass.AUTH,
                confidence=0.96,
                root_cause="The failing node could not authenticate with its upstream service.",
                evidence=self._evidence(failure, "Authentication-related response or message detected."),
                recommended_action=(
                    "Verify the referenced credential and its scopes; do not rotate or replace secrets automatically."
                ),
                retry_safe=False,
            )

        if code == 429 or any(
            token in text for token in ("rate limit", "too many requests", "quota exceeded")
        ):
            return Diagnosis(
                failure_class=FailureClass.RATE_LIMIT,
                confidence=0.97,
                root_cause="The upstream service throttled the workflow request.",
                evidence=self._evidence(failure, "HTTP 429 or rate-limit language detected."),
                recommended_action="Add bounded retry/backoff or reduce request concurrency.",
                retry_safe=True,
            )

        if any(token in text for token in ("timeout", "timed out", "etimedout")):
            return Diagnosis(
                failure_class=FailureClass.TIMEOUT,
                confidence=0.92,
                root_cause="The node exceeded its allowed response or execution time.",
                evidence=self._evidence(failure, "Timeout signature detected."),
                recommended_action="Increase the node timeout only within a bounded limit and add retry/backoff.",
                retry_safe=True,
            )

        if any(
            token in text
            for token in ("econnrefused", "enotfound", "dns", "socket hang up", "network error")
        ):
            return Diagnosis(
                failure_class=FailureClass.NETWORK,
                confidence=0.91,
                root_cause="The workflow could not reach the upstream host reliably.",
                evidence=self._evidence(failure, "Network transport signature detected."),
                recommended_action="Verify host reachability and retry with bounded exponential backoff.",
                retry_safe=True,
            )

        if any(
            token in text
            for token in (
                "cannot read properties of undefined",
                "undefined",
                "expression",
                "paireditem",
                "item linking",
                "no data found",
            )
        ):
            return Diagnosis(
                failure_class=FailureClass.DATA_MAPPING,
                confidence=0.86,
                root_cause="The node likely expects data that is missing or mapped from the wrong item/path.",
                evidence=self._evidence(failure, "Data/expression mapping signature detected."),
                recommended_action="Inspect the failing expression against the captured input before changing it.",
                retry_safe=False,
            )

        if code == 404 and failure.node_type and "webhook" in failure.node_type.lower():
            return Diagnosis(
                failure_class=FailureClass.WEBHOOK,
                confidence=0.90,
                root_cause="The webhook route or target endpoint was not found.",
                evidence=self._evidence(failure, "Webhook node returned HTTP 404."),
                recommended_action="Verify the production webhook URL and workflow activation state.",
                retry_safe=False,
            )

        return Diagnosis(
            failure_class=FailureClass.UNKNOWN,
            confidence=0.35,
            root_cause="The failure does not match the deterministic baseline taxonomy.",
            evidence=self._evidence(failure, "No high-confidence rule matched."),
            recommended_action="Escalate to deeper analysis; do not mutate the workflow automatically.",
            retry_safe=False,
        )

    @staticmethod
    def _evidence(failure: ExecutionFailure, reason: str) -> list[str]:
        evidence = [reason, f"error={failure.error_message[:240]}"]
        if failure.failed_node:
            evidence.append(f"failed_node={failure.failed_node}")
        if failure.status_code:
            evidence.append(f"status_code={failure.status_code}")
        return evidence
