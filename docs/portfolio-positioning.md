# AI Automation Doctor — Portfolio Positioning

## One-line pitch

A production-shaped reliability service for failed n8n automations that combines deterministic safety controls with bounded AI diagnosis and human-approved remediation.

## Why it matters

Most automation demos stop at “LLM reads an error and suggests a fix.” This project treats remediation as a reliability and safety problem instead:

- deterministic rules remain authoritative for retry safety and mutation decisions
- AI is advisory-only and receives privacy-minimized context
- workflow changes are constrained to a tiny retry-only allowlist
- approvals are bound to the exact workflow version and SHA-256 snapshot evidence
- crash recovery, leases, idempotency, and replay semantics are explicit
- model selection is backed by blind real-model evaluation rather than preference

## Measured evidence

- Qwen3-1.7B: 93.75% accuracy on the second blind 32-case diagnosis holdout
- raw schema validity: 100%
- provider failures: 0%
- taxonomy V2 hard suite: 64/64 classification + retry-safety
- patch safety V1: 22/22 decisions with 0 unsafe false accepts
- remediation safety V1: 10/10 state-machine decisions with 0 unsafe writes and 0 unsafe retries

These are bounded synthetic/hand-labeled evaluation results, not a claim of universal production accuracy.

## Technical signal

The project demonstrates FastAPI service design, structured LLM boundaries, evaluation-driven model selection, workflow-aware validation, human-in-the-loop safety, SQLite durability, concurrency leases, idempotent remediation, Docker packaging, GitHub Actions, GHCR publishing, and browser-level demo verification with Playwright.

## Interview summary

The key design decision was to keep the model outside the authority boundary. The model can improve diagnosis for difficult failures, but retry safety, patch generation, approval, and side effects remain deterministic and auditable. A blind evaluation also showed that the base Qwen3-1.7B model outperformed the existing tool-calling QLoRA adapter for this diagnosis task, so the project documents that result instead of forcing a fine-tuned-model superiority claim.
