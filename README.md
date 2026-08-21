# AI Automation Doctor

**v1.3.0** — a production-shaped reliability service for failed n8n automations with deterministic safety controls, bounded AI diagnosis, human-approved remediation, durable recovery, blind real-model evaluation, and a read-only interactive demo.

AI Automation Doctor ingests failed n8n executions, produces a privacy-minimized incident, classifies likely failure cause and retry safety, proposes only narrowly allowlisted retry changes, validates them against the current workflow snapshot, binds human approval to that exact validated state, and can execute a guarded **apply → verify → retry → verify** flow.

The LLM is advisory-only. It cannot decide retry safety, modify workflow JSON, approve a patch, or execute a retry.

## Interactive demo

Run the service and open:

```text
http://localhost:8000/demo
```

The demo lets you choose sample failures or enter your own n8n error metadata and inspect:

- deterministic failure class, confidence, evidence, and retry-safety decision
- optional AI advisory diagnosis when an OpenAI-compatible provider is configured
- the bounded retry-patch preview produced from deterministic fields
- the model-selection benchmark evidence used by the project
- an explicit safety panel showing that demo mutation, retry, approval, and durable writes are disabled

`POST /v1/demo/analyze` is **read-only by construction**. It does not use the durable incident store and it has no path to approval, workflow mutation, or execution retry. A generated patch is only an in-memory preview.

## Measured result

The latest second-blind 32-case diagnosis holdout produced:

| Model | Accuracy | Raw schema validity | Provider failure |
|---|---:|---:|---:|
| **Qwen3-1.7B** | **93.75%** | **100%** | **0%** |
| Tool-calling QLoRA adapter | 84.375% | 100% | 0% |

A prior unseen 32-case holdout produced **87.5% accuracy for both models** with **93.75% raw schema validity** and **0% provider failures**.

The base model is therefore the recommended diagnosis model for v1.3.0. The existing tool-calling adapter remains a useful comparison target, but its fine-tuning objective does not consistently transfer to incident diagnosis.

Machine-readable evidence is committed under `evals/results/`, including `ai_diagnosis_release_summary_v1.2.1.json`.

## What this project demonstrates

- FastAPI service design around a real external automation platform
- deterministic failure taxonomy with measured regression suites
- bounded OpenAI-compatible AI advisory diagnosis
- blind real-model evaluation with balanced development and holdout sets
- privacy-minimized provider context with no deterministic-answer anchoring
- strict structured-output validation and fail-closed fallback
- read-only interactive product demo separated from the durable mutation path
- workflow-aware structural validation rather than free-form JSON editing
- human approval bound to `versionId` + SHA-256 snapshot evidence
- deny-by-default mutation policy
- durable SQLite remediation state and append-only timeline
- lease-based concurrency protection and idempotent replay
- crash recovery that avoids repeating uncertain writes or retries
- Docker packaging, readiness/health endpoints, metrics, and CI safety gates

## Architecture

```text
n8n failed execution
        |
        v
privacy-minimized normalizer
        |
        v
deterministic diagnosis + retry-safety classifier
        |
        +--> high-confidence result ------------------------------+
        |                                                        |
        +--> unknown / low confidence                            |
                    |                                             |
                    v                                             |
           privacy-minimized AI advisory                          |
           (no baseline answer is sent to the model)              |
           (no retry/patch/approval authority)                    |
                    |                                             |
                    +---------------------+                       |
                                          v                       v
                              authoritative deterministic diagnosis
                                          |
                                          v
                              constrained retry patch proposal
                                          |
                                          v
                               deny-by-default validator
                                          |
                                          v
                                  current workflow fetch
                                          |
                                          v
                          workflow-aware dry run on deep copy
                                          |
                                          +--> versionId
                                          +--> full snapshot SHA-256
                                          +--> protected-structure fingerprint
                                          +--> safe before/after diff
                                          |
                                          v
                         human approval bound to validated snapshot
                                          |
                                          v
                         SQLite remediation lease + durable stage
                                          |
                                          v
                       stale-state preflight + server-side rebuild
                                          |
                                          v
                         PUT workflow with publishIfActive=false
                                          |
                                          v
                         refetch + exact persistence verification
                                          |
                                          v
                          retry original execution + verification
                                          |
                                          v
                           persist timeline + idempotent result
```

The `/demo` path branches before durable incident storage: it runs diagnosis plus patch planning in memory and returns a preview only.

## AI advisory boundary

The AI path exists only to improve operator context for failures that the deterministic taxonomy cannot classify confidently.

- `AI_DIAGNOSIS_ENABLED=false` by default.
- With the default `AI_BASELINE_CONFIDENCE_THRESHOLD=0.80`, the current deterministic rules normally call AI only for `unknown` cases.
- The provider receives only node type, bounded error text/stack, error code, and status code.
- Raw input snapshots, workflow snapshots, workflow names, node names, workflow IDs, execution IDs, and the deterministic baseline diagnosis are excluded.
- Output is restricted to advisory failure class, confidence, root cause, evidence, and recommended action.
- Extra fields such as `retry_safe`, patches, credentials, workflow JSON, commands, or approval decisions are rejected.
- Provider, network, parsing, or validation failures fall back to the deterministic result.
- `PatchPlanner` continues to consume authoritative deterministic fields only.

The removal of deterministic-baseline text from the model input was evidence-driven: the first live run showed that small models copied the baseline `unknown` class, `0.35` confidence, and wording. De-anchoring plus explicit taxonomy semantics produced the dominant accuracy gain.

## Real-model evaluation

The repository contains three balanced 32-case sets across authentication, rate limit, timeout, network, data mapping, webhook, configuration, and unknown failures.

- `evals/ai_diagnosis_v1.jsonl` — development set
- `evals/ai_diagnosis_holdout_v2.jsonl` — first unseen holdout
- `evals/ai_diagnosis_holdout_v3.jsonl` — second blind holdout

Integrity tests require the deterministic engine to abstain on every case, so the sets measure incremental advisory value rather than easy keyword matching.

Measured progression:

| Stage | Base Qwen | Tool-calling adapter | Raw schema validity |
|---|---:|---:|---:|
| Initial live run | 31.25% | 25.0% | 90.625% / 81.25% |
| De-anchored development run | 81.25% | 84.375% | 100% / 100% |
| First unseen holdout | 87.5% | 87.5% | 93.75% / 93.75% |
| **Second blind holdout** | **93.75%** | **84.375%** | **100% / 100%** |

On the second blind set, base Qwen missed only two cases: one webhook-vs-network boundary and one configuration-vs-data-mapping boundary. This is a bounded synthetic benchmark, not a claim of universal production accuracy.

See [`docs/real_model_evaluation.md`](docs/real_model_evaluation.md) for methodology, commands, limitations, and the optional manual regression gate.

## Safety contract

Only one uniquely resolved n8n node may be changed, and only these node-level retry fields are allowlisted:

- `retryOnFail` — may only be enabled
- `maxTries` — bounded to 1–5
- `waitBetweenTries` — bounded to 250–60000 ms

Credentials, node identity/type/version, URLs, bodies, expressions, code/commands, workflow connections, workflow settings, and unrelated node parameters are outside the automatic patch allowlist.

Additional controls:

- `ALLOW_WORKFLOW_MUTATION=false` by default
- `ALLOW_EXECUTION_RETRY=false` by default
- both side-effect gates are preflighted before the first write
- enabling either gate requires `OPERATOR_TOKEN` for approval/remediation endpoints
- approval is impossible before a successful dry run
- a new dry run invalidates the previous approval
- approval is bound to the exact workflow version and snapshot fingerprint
- changed or ambiguous workflow state fails closed
- workflow updates always use `publishIfActive=false`
- retry starts only after exact persistence and protected-structure verification
- raw input/workflow snapshots are never persisted to SQLite
- completed remediation requests replay their persisted result without another write or retry
- `/v1/demo/analyze` cannot write durable state, approve, mutate, or retry

See [`SECURITY.md`](SECURITY.md) for deployment guidance and recovery semantics.

## Durable recovery semantics

A per-proposal database lease blocks concurrent remediation attempts. Before each dangerous boundary, state is persisted.

- If the process stops around workflow update, the Doctor compares the current writable workflow definition with the approved expected fingerprint and refuses ambiguous state.
- If the process stops after a retry may have been requested, the Doctor looks for an n8n execution whose `retryOf` references the original execution. If it cannot prove whether a retry happened, it stops for manual reconciliation.
- Repeating a completed remediation request returns the persisted result with `idempotent_replay=true`; no external side effect is repeated.

## Local setup

```bash
cp .env.example .env
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Then open `http://localhost:8000/demo` for the read-only UI.

Default configuration keeps side effects and AI calls off:

```env
ALLOW_WORKFLOW_MUTATION=false
ALLOW_EXECUTION_RETRY=false
STATE_DB_PATH=./data/ai-automation-doctor.db
AI_DIAGNOSIS_ENABLED=false
```

Enable only the advisory AI layer with an OpenAI-compatible endpoint:

```env
AI_DIAGNOSIS_ENABLED=true
AI_API_BASE_URL=http://localhost:8000/v1
AI_API_KEY=
AI_MODEL=Qwen/Qwen3-1.7B
AI_TIMEOUT_SECONDS=20
AI_BASELINE_CONFIDENCE_THRESHOLD=0.80
```

## Docker

```bash
docker build -t ai-automation-doctor:1.3.0 .
docker run --rm -p 8000:8000 \
  -v doctor-data:/app/data \
  --env-file .env \
  ai-automation-doctor:1.3.0
```

The SQLite path must live on persistent storage if restart recovery is required.

## API flow

Read-only interactive demo:

```bash
curl http://localhost:8000/demo
curl -X POST http://localhost:8000/v1/demo/analyze \
  -H 'content-type: application/json' \
  -d '{"error_message":"429 Too Many Requests","status_code":429}'
```

Analyze a failed n8n execution:

```bash
curl -X POST http://localhost:8000/v1/incidents/n8n/<execution-id>/analyze
```

Dry-run the constrained patch against the current workflow:

```bash
curl -X POST http://localhost:8000/v1/patches/<proposal-id>/dry-run/n8n
```

Approve the exact validated snapshot when side-effect gates are enabled:

```bash
curl -X POST http://localhost:8000/v1/patches/<proposal-id>/approve \
  -H 'content-type: application/json' \
  -H 'x-doctor-operator-token: <operator-token>' \
  -d '{"approved_by":"human-operator","note":"Reviewed retry-only diff"}'
```

Apply, verify, retry, and verify:

```bash
curl -X POST http://localhost:8000/v1/patches/<proposal-id>/apply-retry \
  -H 'x-doctor-operator-token: <operator-token>'
```

Read the durable timeline:

```bash
curl http://localhost:8000/v1/patches/<proposal-id>/timeline
```

Health and operational endpoints:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl http://localhost:8000/metrics
curl http://localhost:8000/v1/stats
```

## Measured deterministic safety suites

| Suite | Cases | Result |
|---|---:|---:|
| Taxonomy V1 smoke | 9 | **100% classification + retry-safety** |
| Taxonomy V2 hard | 64 | **100% classification + retry-safety** |
| Patch Safety V1 | 22 | **100% decisions, 0% unsafe false accepts** |
| Remediation Safety V1 | 10 | **100% state-machine decisions, 0% unsafe writes, 0% unsafe retries** |
| AI Diagnosis second blind | 32 | **93.75% base-Qwen accuracy, 100% schema validity** |

Live model inference is intentionally not a CI dependency: pull requests require no provider secret, paid inference, or GPU runner.

## Limitations

- SQLite plus its lease implementation is a single-service-instance production baseline, not a distributed lock for multi-replica deployment.
- Retry verification performs one bounded read; a still-running retry returns `pending`.
- If crash recovery cannot prove whether an execution retry started, it stops for manual reconciliation.
- Built-in operator authentication is a shared-secret baseline; stronger deployments should sit behind mTLS/OIDC/workload identity or another trusted gateway.
- The AI benchmark sets are synthetic and hand-labeled. They measure controlled regression behavior, not production incident prevalence or universal model correctness.
- The interactive demo does not persist incidents and intentionally cannot demonstrate live workflow mutation or retry.
- No LLM is allowed to directly mutate workflow JSON.

## Release history

See [`CHANGELOG.md`](CHANGELOG.md).
