# AI Automation Doctor

**v1.1.0** — a production-shaped reliability service for failed n8n automations with bounded AI advisory diagnosis.

AI Automation Doctor turns failed n8n executions into privacy-minimized incidents, classifies likely root cause and retry safety, proposes a narrowly constrained retry patch, validates it against the current workflow, binds explicit human approval to the exact validated snapshot, and can execute a guarded **apply → verify → retry → verify** flow.

v1.1 adds an opt-in AI advisory for deterministic unknown/low-confidence failures. The deterministic diagnosis remains authoritative for failure class, retry safety, patch planning, approval, and remediation. The AI path is disabled by default, receives only privacy-minimized metadata, and cannot directly mutate workflow JSON.

## What this project demonstrates

- FastAPI service design around a real external automation platform
- deterministic failure diagnosis with measured regression suites
- bounded AI advisory analysis with strict output validation and fail-closed fallback
- privacy-minimized n8n execution ingestion and AI provider context
- workflow-aware structural validation rather than free-form JSON editing
- human-in-the-loop approval bound to `versionId` + SHA-256 snapshot evidence
- deny-by-default mutation policy
- durable remediation state and append-only operational timeline
- concurrency leases and idempotent completed-request replay
- crash recovery without blindly repeating workflow writes or retries
- Docker packaging, health/readiness, low-cardinality metrics, and CI safety gates

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
        +--> unknown / below AI threshold                        |
                    |                                             |
                    v                                             |
           privacy-minimized AI advisory                          |
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

## AI advisory safety boundary

The AI path exists to improve operator context for failures that the deterministic taxonomy cannot classify confidently. It is intentionally outside the control path for side effects.

- `AI_DIAGNOSIS_ENABLED=false` by default.
- With the default `AI_BASELINE_CONFIDENCE_THRESHOLD=0.80`, the current deterministic rules call AI only for `unknown` cases.
- Provider context excludes raw input snapshots, workflow snapshots, workflow names, node names, workflow IDs, and execution IDs.
- Provider output is a strict schema containing only advisory failure class, confidence, root cause, evidence, and recommended action.
- Extra output fields are rejected, including `retry_safe`, patches, approval decisions, or other undeclared data.
- Any provider, network, parsing, or validation error falls back to the deterministic result.
- `PatchPlanner` continues to consume the authoritative deterministic fields only.

The built-in provider targets OpenAI-compatible chat-completions endpoints so the advisory can be backed by a hosted model or a compatible local gateway without changing the safety contract.

## Safety contract

The automatic mutation surface is intentionally small.

Only one uniquely resolved n8n node may be changed, and only these node-level retry fields are allowlisted:

- `retryOnFail` — may only be enabled
- `maxTries` — bounded to 1–5
- `waitBetweenTries` — bounded to 250–60000 ms

Credentials, node identity/type/version, URLs, bodies, expressions, code/commands, workflow connections, workflow settings, and unrelated node parameters are outside the automatic patch allowlist.

Additional controls:

- `ALLOW_WORKFLOW_MUTATION=false` by default
- `ALLOW_EXECUTION_RETRY=false` by default
- both side-effect gates are preflighted before the first write
- enabling either gate requires `OPERATOR_TOKEN` for `/approve` and `/apply-retry`
- approval is impossible before a successful dry run
- a new dry run invalidates the previous approval
- approval is bound to the exact workflow version and snapshot fingerprint
- changed or ambiguous workflow state fails closed
- workflow updates always use `publishIfActive=false`
- retry starts only after exact persistence + protected-structure verification
- raw input/workflow snapshots are never persisted to SQLite
- completed remediation requests replay their persisted result without another write or retry

See [`SECURITY.md`](SECURITY.md) for deployment guidance and recovery semantics.

## Durable recovery semantics

The service stores incidents, patch proposals, validated dry runs, approvals, timeline events, and remediation stages in SQLite.

A per-proposal database lease blocks concurrent remediation attempts. Before each dangerous boundary, state is persisted. Recovery behavior is conservative:

- **process stops around workflow update:** the Doctor compares the current n8n writable workflow definition with the approved expected fingerprint. If the approved update already persisted, it continues without another update. If the workflow is still the exact approved original, it may safely continue the normal path. Anything else stops as stale/ambiguous.
- **process stops after retry may have been requested:** the Doctor looks for an n8n execution whose `retryOf` references the original execution. If that evidence exists, it resumes verification using that execution. If it cannot prove whether a retry already happened, it stops for manual reconciliation instead of risking a duplicate execution.
- **completed request repeated:** the persisted result is returned with `idempotent_replay=true`; no external side effect is repeated.

## Local setup

```bash
cp .env.example .env
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Default configuration keeps side effects and AI calls off:

```env
ALLOW_WORKFLOW_MUTATION=false
ALLOW_EXECUTION_RETRY=false
STATE_DB_PATH=./data/ai-automation-doctor.db
AI_DIAGNOSIS_ENABLED=false
```

To enable only the advisory AI layer with an OpenAI-compatible endpoint:

```env
AI_DIAGNOSIS_ENABLED=true
AI_API_BASE_URL=https://your-compatible-provider.example/v1
AI_API_KEY=replace-me-if-required
AI_MODEL=your-model-name
AI_TIMEOUT_SECONDS=20
AI_BASELINE_CONFIDENCE_THRESHOLD=0.80
```

For an explicitly enabled remediation deployment:

```env
N8N_BASE_URL=https://your-n8n.example.com
N8N_API_KEY=replace-me
ALLOW_WORKFLOW_MUTATION=true
ALLOW_EXECUTION_RETRY=true
OPERATOR_TOKEN=use-a-long-random-secret
STATE_DB_PATH=./data/ai-automation-doctor.db
```

Protect the service with TLS/network controls and use a currently patched n8n release before enabling side effects.

## Docker

```bash
docker build -t ai-automation-doctor:1.1.0 .
docker run --rm -p 8000:8000 \
  -v doctor-data:/app/data \
  --env-file .env \
  ai-automation-doctor:1.1.0
```

The SQLite path must live on persistent storage if restart recovery is required.

## API flow

### Health, readiness, metrics

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl http://localhost:8000/metrics
curl http://localhost:8000/v1/stats
```

### 1. Analyze a failed execution

Configured n8n fetch:

```bash
curl -X POST http://localhost:8000/v1/incidents/n8n/<execution-id>/analyze
```

Or ingest an already retrieved n8n failure payload:

```bash
curl -X POST http://localhost:8000/v1/incidents/ingest/n8n \
  -H 'content-type: application/json' \
  --data @failed-execution.json
```

When enabled and eligible, an AI advisory is returned under `diagnosis.ai_insight`. The top-level diagnosis fields remain the deterministic control result.

### 2. Dry-run the proposed patch against the current n8n workflow

```bash
curl -X POST http://localhost:8000/v1/patches/<proposal-id>/dry-run/n8n
```

The response contains only the validated diff and fingerprints, not a credential-bearing patched workflow body.

### 3. Approve

When side-effect gates are enabled, send the operator token:

```bash
curl -X POST http://localhost:8000/v1/patches/<proposal-id>/approve \
  -H 'content-type: application/json' \
  -H 'x-doctor-operator-token: <operator-token>' \
  -d '{"approved_by":"human-operator","note":"Reviewed retry-only diff"}'
```

### 4. Apply + retry + verify

```bash
curl -X POST http://localhost:8000/v1/patches/<proposal-id>/apply-retry \
  -H 'x-doctor-operator-token: <operator-token>'
```

### 5. Read the durable audit timeline

```bash
curl http://localhost:8000/v1/patches/<proposal-id>/timeline
```

## Measured evaluation

The v1.0 release baseline passed **46 automated tests** in GitHub Actions while retaining all earlier safety benchmarks. v1.1 adds dedicated regression coverage for the AI advisory boundary without weakening those deterministic gates.

| Suite | Cases | Result |
|---|---:|---:|
| Taxonomy V1 smoke | 9 | **100% classification + retry-safety** |
| Taxonomy V2 hard | 64 | **100% classification + retry-safety** |
| Patch Safety V1 | 22 | **100% decisions, 0% unsafe false accepts** |
| Remediation Safety V1 | 10 | **100% state-machine decisions, 0% unsafe writes, 0% unsafe retries** |

The v1.1 AI regression set covers high-confidence AI gating, advisory-only enrichment of unknown failures, fail-closed provider errors, privacy-minimized provider context, and rejection of outputs attempting to add retry or patch authority.

Machine-readable v1 evidence is committed at [`evals/results/v1_release_summary.json`](evals/results/v1_release_summary.json).

These are bounded deterministic regression results plus mocked AI-boundary tests. The datasets are synthetic/hand-labeled and remediation is exercised with mocks. They do **not** claim universal correctness for every n8n node, third-party API, model provider, distributed concurrency condition, or infrastructure failure, and this repository does not claim that its benchmark modified a live production n8n workflow.

## CI release gates

Every push and pull request runs:

1. package installation
2. Ruff linting
3. full pytest suite, including AI-boundary regressions
4. dedicated durability/recovery/security regression set
5. 9-case Taxonomy V1
6. 64-case hard Taxonomy V2
7. 22-case Patch Safety V1 with zero unsafe false accepts
8. 10-case Remediation Safety V1 with zero unsafe writes/retries
9. production Docker image build

## Operational limitations

- SQLite + its lease implementation is a **single-service-instance** production baseline. Do not enable side effects in a multi-replica deployment until the state/lease layer is replaced with an appropriate shared transactional store and distributed locking strategy.
- Retry verification performs one bounded read. A still-running n8n retry returns `pending`; no unbounded background polling is performed.
- If crash recovery cannot prove whether an execution retry already started, it deliberately stops for manual reconciliation.
- Built-in operator authentication is a shared-secret baseline. Stronger deployments should put the service behind mTLS/OIDC/workload identity or another trusted gateway.
- AI diagnosis is advisory only; deterministic diagnosis remains the control-plane source for retry safety and patch planning.
- No LLM is allowed to directly mutate workflow JSON.

## Release history

See [`CHANGELOG.md`](CHANGELOG.md).
