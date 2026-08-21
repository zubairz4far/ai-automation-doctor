# Portfolio Case Study — AI Automation Doctor v1.2.1

## Problem

Rule-based automation reliability systems are safe and predictable, but they become weak on vendor-specific or ambiguous incident text that does not match known signatures. Adding an LLM can improve diagnosis, but it also introduces schema drift, hallucinated control decisions, privacy risk, and evaluation leakage.

AI Automation Doctor was built to test a safer architecture: keep deterministic diagnosis and remediation authoritative, then use a constrained LLM only as an advisory classifier for cases the rule engine cannot confidently classify.

## Architecture

The service is a FastAPI reliability layer around failed n8n executions.

1. Ingest and privacy-minimize failure metadata.
2. Run deterministic failure classification and retry-safety logic.
3. Call the LLM only for unknown/low-confidence cases.
4. Validate the LLM response against a strict advisory-only schema.
5. Keep retry safety and patch planning deterministic.
6. Generate only allowlisted retry-related changes.
7. Dry-run against the current workflow snapshot.
8. Bind human approval to exact version/fingerprint evidence.
9. Apply, verify persistence, retry, and verify under explicit side-effect gates.
10. Persist an audit timeline and recovery state in SQLite.

The model never receives workflow snapshots, input snapshots, credentials, workflow IDs, execution IDs, or the deterministic baseline answer.

## Evaluation design

A balanced eight-class benchmark was built for:

- authentication
- rate limit
- timeout
- network
- data mapping
- webhook
- configuration
- unknown

Each evaluation set contains 32 synthetic, hand-labeled hard cases. Integrity tests require the deterministic engine to return `unknown` for every benchmark row, making the model evaluation incremental rather than a replay of easy keyword rules.

The experiment progressed through a development set and two later holdouts. Once a holdout was inspected, it was no longer treated as blind.

## What failed first

The first real-model run was weak:

| Model | Accuracy | Raw schema validity |
|---|---:|---:|
| Qwen3-1.7B | 31.25% | 90.625% |
| Tool-calling QLoRA | 25.0% | 81.25% |

The key discovery was prompt/context anchoring. The model input included the deterministic baseline diagnosis. Small models copied the baseline's `unknown` class, `0.35` confidence, root-cause wording, and recommended action instead of independently classifying the incident.

## Changes made

### 1. Removed answer anchoring

The deterministic baseline remains responsible for deciding whether AI is called, but its diagnosis is no longer serialized into the LLM context.

### 2. Added explicit taxonomy semantics

The system prompt defines the eight failure classes and requires the most specific supported class.

### 3. Added boundary rules

Prompt boundaries explicitly distinguish:

- configuration from runtime data-mapping failures
- webhook registration/listener failures from transport/network failures
- opaque undocumented provider states from network errors

### 4. Strengthened structured-output discipline

The response schema permits only:

- failure class
- confidence
- root cause
- evidence
- recommended action

Extra retry, patch, credential, workflow, command, or approval fields are rejected. Evidence must contain non-empty strings.

### 5. Changed the evaluation workflow

After inspecting development errors, later improvements were scored on fresh holdouts instead of repeatedly optimizing and reporting the same 32 cases.

## Measured progression

| Stage | Qwen3-1.7B | Tool-calling adapter | Raw schema validity |
|---|---:|---:|---:|
| Initial live run | 31.25% | 25.0% | 90.625% / 81.25% |
| De-anchored development run | 81.25% | 84.375% | 100% / 100% |
| First unseen holdout | 87.5% | 87.5% | 93.75% / 93.75% |
| Second blind holdout | **93.75%** | 84.375% | **100% / 100%** |

Both models had 0% provider failures on the second blind run. Base Qwen was correct on 30/32 cases and led the adapter by 9.375 percentage points.

## Model-selection result

The existing QLoRA adapter was trained for structured tool routing, not incident diagnosis. It initially looked competitive after prompt repair, but the second blind holdout showed that base `Qwen/Qwen3-1.7B` generalizes better for this task.

The production recommendation is therefore the base model for diagnosis, while the QLoRA remains a separate tool-calling portfolio artifact.

## Safety engineering

The strongest part of the project is not the classification score alone. The design keeps uncertain model behavior outside the side-effect control plane:

- AI disabled by default
- deterministic retry safety authoritative
- deny-by-default patch allowlist
- no credential or arbitrary workflow mutation
- human approval bound to exact workflow evidence
- stale-state detection
- exact persistence verification
- explicit mutation/retry gates
- idempotent replay and crash recovery
- advisory provider failures fail closed

## Remaining limitations

The second blind benchmark is still synthetic and contains only 32 cases. Base Qwen missed one configuration-vs-data-mapping case and one webhook-vs-network case. These results do not establish universal production accuracy across n8n integrations or third-party APIs.

## What this project demonstrates

This project demonstrates practical AI engineering beyond model fine-tuning:

- diagnosing a weak benchmark rather than hiding it
- separating model problems from prompt/context problems
- preventing answer leakage and anchoring
- designing blind evaluation after tuning
- selecting a base model over a fine-tune when evidence supports it
- constraining LLMs behind deterministic safety controls
- integrating model evaluation with production-shaped reliability architecture

## Repository evidence

See:

- `README.md`
- `docs/real_model_evaluation.md`
- `RELEASE_NOTES_v1.2.1.md`
- `evals/results/ai_diagnosis_release_summary_v1.2.1.json`
