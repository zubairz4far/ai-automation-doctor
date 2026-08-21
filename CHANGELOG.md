# Changelog

## 1.2.1 — 2026-08-21

Evaluation-hardening release.

- Removed deterministic-baseline wording from the LLM context after measured evidence showed that it anchored small models to the baseline `unknown` class, confidence, and wording.
- Added explicit diagnosis taxonomy semantics and boundary guidance while keeping the AI advisory outside the control path for retry safety, patch planning, approval, and remediation.
- Added strict prompt guidance requiring one to eight non-empty evidence strings and preserving fail-closed schema validation.
- Added two balanced 32-case holdout sets with deterministic-abstention integrity tests so prompt changes are not repeatedly scored only on the development set.
- Recorded a first unseen holdout result of **87.5% overall accuracy** for both Qwen3-1.7B and the existing tool-calling adapter, with **93.75% raw schema validity** and **0% provider failures**.
- Recorded a second blind holdout result of **93.75% overall accuracy** for base Qwen3-1.7B versus **84.375%** for the tool-calling adapter, with **100% raw schema validity** and **0% provider failures** for both.
- Selected base `Qwen/Qwen3-1.7B` as the recommended diagnosis model. The tool-calling QLoRA remains a comparison target because its training objective does not consistently transfer to incident classification.
- Added machine-readable v1.2.1 benchmark evidence under `evals/results/`.

## 1.2.0 — 2026-08-21

Real-model diagnosis evaluation release.

- Added a 32-case hard AI diagnosis challenge set designed to make the deterministic engine abstain rather than succeed on keyword matches.
- Added a live OpenAI-compatible benchmark runner with configurable model, endpoint, timeout, output, and quality thresholds.
- Added baseline-vs-AI accuracy delta, schema validity, provider failure rate, valid-output accuracy, and per-class metrics.
- Added regression tests that lock the challenge set's deterministic-abstention property and evaluator scoring behavior.
- Documented local vLLM evaluation for Qwen3-1.7B and optional comparison against the existing QLoRA tool-calling adapter.
- Kept real-model calls out of CI so pull requests never require secrets, paid inference, or GPU access.

## 1.1.0 — 2026-08-21

Bounded AI diagnosis release.

- Added an opt-in OpenAI-compatible advisory diagnosis provider for low-confidence/unknown incidents.
- Kept deterministic failure class, confidence, retry safety, patch planning, approval, and remediation authoritative.
- Added strict AI output validation that rejects retry decisions, patch data, credentials, workflow JSON, and extra fields.
- Added privacy-minimized provider context that excludes raw input snapshots, workflow snapshots, workflow names, node names, execution IDs, and workflow IDs.
- Added fail-closed fallback to deterministic analysis on provider/network/runtime/validation failure.
- Added regression tests for AI gating, privacy minimization, unsafe-output rejection, and deterministic fallback.
- Kept AI diagnosis disabled by default and configurable through environment variables.

## 1.0.0 — 2026-08-17

Portfolio-ready reliability release.

- Added durable SQLite incident, dry-run, approval, timeline, and remediation state.
- Added lease-based concurrency protection for remediation attempts.
- Made completed remediation requests idempotent across process restarts.
- Added crash recovery around workflow writes using approved writable-definition fingerprints.
- Added fail-closed retry recovery using n8n `retryOf` execution metadata.
- Added persisted incident timeline, readiness, statistics, and Prometheus-compatible metrics endpoints.
- Prevented raw input/workflow snapshots from entering durable storage.
- Added operator-token protection when workflow mutation or execution retry is enabled.
- Promoted durability, recovery, privacy, and authentication tests to CI release gates.
- Retained the narrow retry-only mutation allowlist and all prior benchmark gates.

## 0.4.0 — 2026-08-17

- Added controlled apply → persistence verification → retry → verification state machine.
- Bound human approval to an exact workflow version and snapshot fingerprint.
- Added independent workflow-mutation and execution-retry gates.
- Added stale workflow detection and safe public-workflow update serialization.
- Added 10-case remediation safety benchmark.

## 0.3.0 — 2026-08-17

- Added workflow-aware dry-run patching.
- Aligned retry fields to n8n's node-level schema.
- Added structural invariants and 22-case patch-safety benchmark.

## 0.2.0 — 2026-08-17

- Added real n8n failed-execution normalization and API ingestion.
- Added privacy-minimized incident extraction.
- Expanded diagnosis evaluation to a 64-case hard suite.

## 0.1.0 — 2026-08-17

- Initial FastAPI reliability-agent baseline.
- Deterministic failure taxonomy, constrained patch planner, human approval model, Docker, tests, and CI.
