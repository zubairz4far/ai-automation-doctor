# Changelog

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
