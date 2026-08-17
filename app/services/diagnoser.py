from __future__ import annotations

from app.models.schemas import Diagnosis, ExecutionFailure, FailureClass


class DiagnosisEngine:
    """Deterministic baseline used as the evaluation anchor before adding an LLM."""

    def diagnose(self, failure: ExecutionFailure) -> Diagnosis:
        text = " ".join(
            part
            for part in [
                failure.error_message,
                failure.error_stack or "",
                failure.error_code or "",
            ]
            if part
        ).lower()
        code = failure.status_code
        node_hint = " ".join(
            part for part in [failure.failed_node or "", failure.node_type or ""] if part
        ).lower()

        # Explicit protocol status takes precedence over ambiguous message text.
        if code in {401, 403}:
            return self._diagnosis(
                failure,
                FailureClass.AUTH,
                0.98,
                "The failing node could not authenticate with its upstream service.",
                "HTTP 401/403 detected.",
                "Verify the referenced credential and its scopes; do not rotate or replace secrets automatically.",
                False,
            )

        if code == 429:
            return self._diagnosis(
                failure,
                FailureClass.RATE_LIMIT,
                0.99,
                "The upstream service throttled the workflow request.",
                "HTTP 429 detected.",
                "Add bounded retry/backoff or reduce request concurrency.",
                True,
            )

        if code in {408, 504}:
            return self._diagnosis(
                failure,
                FailureClass.TIMEOUT,
                0.97,
                "The request exceeded an upstream or gateway time limit.",
                f"HTTP {code} timeout status detected.",
                "Use bounded timeout/retry settings and verify the upstream latency before increasing limits.",
                True,
            )

        if self._contains(
            text,
            (
                "authorization failed",
                "authentication failed",
                "unauthorized",
                "forbidden",
                "invalid api key",
                "api key supplied",
                "oauth token",
                "oauth2",
                "credential is missing",
                "credentials are invalid",
                "access token expired",
                "token expired",
            ),
        ):
            return self._diagnosis(
                failure,
                FailureClass.AUTH,
                0.95,
                "The failing node likely has an authentication or credential problem.",
                "Credential/authentication language detected.",
                "Verify the referenced credential and scopes; never modify secrets automatically.",
                False,
            )

        if self._contains(
            text,
            (
                "rate limit",
                "too many requests",
                "quota exceeded",
                "ratelimitexceeded",
                "throttled",
                "retry-after",
            ),
        ):
            return self._diagnosis(
                failure,
                FailureClass.RATE_LIMIT,
                0.96,
                "The upstream service appears to be throttling requests.",
                "Rate-limit or throttling language detected.",
                "Add bounded exponential backoff and reduce concurrency where appropriate.",
                True,
            )

        if self._contains(text, ("timeout", "timed out", "etimedout", "econnaborted")):
            return self._diagnosis(
                failure,
                FailureClass.TIMEOUT,
                0.93,
                "The node exceeded its allowed response or execution time.",
                "Timeout signature detected.",
                "Increase timeout only within a bounded limit and use bounded retry/backoff.",
                True,
            )

        if self._contains(
            text,
            (
                "econnrefused",
                "enotfound",
                "eai_again",
                "econnreset",
                "socket hang up",
                "dns",
                "getaddrinfo",
                "network error",
                "connection refused",
                "temporary failure in name resolution",
            ),
        ):
            return self._diagnosis(
                failure,
                FailureClass.NETWORK,
                0.92,
                "The workflow could not reach the upstream host reliably.",
                "Network transport or name-resolution signature detected.",
                "Verify host reachability and retry only with bounded exponential backoff.",
                True,
            )

        if self._contains(
            text,
            (
                "cannot read properties of undefined",
                "expressionerror",
                "expression error",
                "paireditem",
                "paired item",
                "item linking",
                "referenced node is unexecuted",
                "no data found for item",
                "invalid expression",
                "missing input field",
            ),
        ):
            return self._diagnosis(
                failure,
                FailureClass.DATA_MAPPING,
                0.89,
                "The node likely expects data that is missing or mapped from the wrong item/path.",
                "Data/expression mapping signature detected.",
                "Inspect the failing expression against captured input before changing it.",
                False,
            )

        webhook_terms = (
            "requested webhook",
            "webhook route",
            "production webhook",
            "webhook is not registered",
        )
        if "webhook" in node_hint and (
            code == 404 or self._contains(text, webhook_terms)
        ):
            return self._diagnosis(
                failure,
                FailureClass.WEBHOOK,
                0.92,
                "The webhook route or registration is missing for the failing workflow.",
                "Webhook node plus route/404 evidence detected.",
                "Verify the production webhook URL, HTTP method, and workflow activation state.",
                False,
            )

        if self._contains(
            text,
            (
                "required parameter",
                "invalid url",
                "workflow has issues",
                "configuration issues",
                "missing required parameter",
                "bad request - please check your parameters",
                "invalid configuration",
            ),
        ):
            return self._diagnosis(
                failure,
                FailureClass.CONFIGURATION,
                0.87,
                "The failing node or workflow appears to be misconfigured.",
                "Explicit configuration/required-parameter language detected.",
                "Inspect the node configuration and validate required parameters before applying a change.",
                False,
            )

        return self._diagnosis(
            failure,
            FailureClass.UNKNOWN,
            0.35,
            "The failure does not match the deterministic baseline taxonomy.",
            "No high-confidence rule matched.",
            "Escalate to deeper analysis; do not mutate or automatically retry the workflow.",
            False,
        )

    def _diagnosis(
        self,
        failure: ExecutionFailure,
        failure_class: FailureClass,
        confidence: float,
        root_cause: str,
        reason: str,
        recommended_action: str,
        retry_safe: bool,
    ) -> Diagnosis:
        return Diagnosis(
            failure_class=failure_class,
            confidence=confidence,
            root_cause=root_cause,
            evidence=self._evidence(failure, reason),
            recommended_action=recommended_action,
            retry_safe=retry_safe,
        )

    @staticmethod
    def _contains(text: str, tokens: tuple[str, ...]) -> bool:
        return any(token in text for token in tokens)

    @staticmethod
    def _evidence(failure: ExecutionFailure, reason: str) -> list[str]:
        evidence = [reason, f"error={failure.error_message[:240]}"]
        if failure.failed_node:
            evidence.append(f"failed_node={failure.failed_node}")
        if failure.status_code:
            evidence.append(f"status_code={failure.status_code}")
        if failure.error_code and failure.error_code != str(failure.status_code):
            evidence.append(f"error_code={failure.error_code[:80]}")
        return evidence
