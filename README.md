# AI Automation Doctor

**v0.4.0** — an evaluated reliability system for failed automations, starting with n8n.

AI Automation Doctor ingests failed n8n executions, converts them into privacy-minimized incidents, classifies root cause and retry safety, proposes narrowly constrained retry patches, validates them against real workflow structure, binds human approval to an exact workflow snapshot, and now implements a guarded **apply → retry → verify** path.

Both workflow mutation and execution retry remain **disabled by default**. The mutation-capable path has been validated with deterministic mocks and CI; this repository does not claim that a live production n8n workflow was mutated during the benchmark.

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
        v
constrained retry patch proposal
        |
        v
deny-by-default patch validator
        |
        v
current n8n workflow fetch
        |
        v
workflow-aware dry run on deep copy
        |
        +--> exact versionId
        +--> SHA-256 snapshot fingerprint
        +--> protected structural fingerprint
        +--> safe before/after diff
        |
        v
human approval bound to that exact snapshot
        |
        v
apply preflight
        |
        +--> mutation gate enabled?
        +--> retry gate enabled?
        +--> current version still matches?
        +--> current snapshot still matches?
        |
        v
server-side patch rebuild
        |
        v
write-safe n8n workflow serialization
        |
        v
PUT workflow with publishIfActive=false
        |
        v
refetch + persistence/invariant verification
        |
        v
retry failed execution once with loadWorkflow=true
        |
        v
fetch retry execution once
        |
        +--> success
        +--> failure
        +--> pending
```

## Completed milestones

### v0.2.0 — real n8n execution ingestion

- normalizes `data.resultData.error` and `lastNodeExecuted`
- falls back to per-node `runData` errors
- supports API-style and UI-style n8n failure exports
- exposes raw-payload ingestion and configured execution-fetch analysis endpoints
- requests execution-data redaction on detailed fetches
- excludes credentials, full workflow bodies, and raw execution items from normalized incidents
- gives explicit HTTP status and transport signals precedence over ambiguous message text
- fails ambiguous failures closed to `unknown`
- includes a 64-case adversarial diagnosis benchmark

### v0.3.0 — workflow-aware dry-run patching

The current n8n node schema exposes `retryOnFail`, `maxTries`, and `waitBetweenTries` as node-level fields. The Doctor's mutation allowlist is limited to those fields.

- logical node addressing with JSON Pointer escaping
- unique target resolution against n8n's array-based `nodes`
- patch application to a deep copy only
- strict retry bounds and types
- single-target-node policy
- workflow-ID and duplicate-node rejection
- protected connections/settings and all non-target nodes
- protected target-node credentials, parameters, identity, type/version, position, and webhook ID
- structural fingerprint before/after must match
- safe diff returned without returning a patched credential-bearing workflow body
- 22-case unsafe-patch trap benchmark

### v0.4.0 — controlled apply, retry, and verification

- server-side dry-run endpoint can fetch the current workflow directly from n8n
- every stored dry run records the workflow `versionId` and SHA-256 of the exact workflow snapshot
- human approval is impossible before a successful dry run
- approval records are bound to that exact version and fingerprint
- a new dry run invalidates any previous approval
- current workflow is fetched again immediately before mutation
- changed `versionId` blocks mutation
- same-version but changed snapshot also blocks mutation
- patch is rebuilt server-side from the current n8n workflow; no client-supplied patched body is trusted for write-back
- update body is reconstructed from an explicit public-workflow field allowlist
- workflow and node read-only metadata are stripped before update
- workflow mutation and execution retry have independent hard gates, both preflighted before the first write
- update always uses `publishIfActive=false`
- persisted writable workflow definition must match the approved update before retry
- protected workflow structure is verified again after persistence
- original failed execution is retried exactly once with `loadWorkflow=true`
- retry execution is fetched once and reported as `success`, `failure`, or `pending`
- 10-case remediation state-machine benchmark enforces zero unsafe writes and zero unsafe retries

## Safety contract

- `ALLOW_WORKFLOW_MUTATION=false` by default
- `ALLOW_EXECUTION_RETRY=false` by default
- both gates must be enabled before the first workflow write
- every mutation requires a successful dry run followed by explicit human approval
- approval is tied to one exact workflow version and snapshot
- stale workflows require a new dry run and new approval
- auto-apply is forbidden by the patch policy
- one patch may target exactly one node
- only node-level `retryOnFail`, `maxTries`, and `waitBetweenTries` are mutable
- `retryOnFail` may only be enabled
- `maxTries` is bounded to 1–5
- `waitBetweenTries` is bounded to 250–60000 ms
- credentials, node type/version, arbitrary URLs, bodies, expressions, code/commands, workflow connections, and settings are outside the patch allowlist
- persisted workflow mismatch blocks execution retry
- updates are saved with `publishIfActive=false`, avoiding silent re-publication of an active workflow
- retry explicitly uses the newly saved workflow with `loadWorkflow=true`
- authentication, mapping, configuration, webhook, and unknown failures receive no automatic retry proposal
- ambiguous diagnosis fails closed to `unknown`

## API

Run locally:

```bash
cp .env.example .env
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Health exposes both side-effect gates:

```bash
curl http://localhost:8000/health
```

### 1. Analyze an n8n failure

```bash
curl -X POST http://localhost:8000/v1/incidents/n8n/<execution-id>/analyze
```

Or ingest a raw failed-execution payload:

```bash
curl -X POST http://localhost:8000/v1/incidents/ingest/n8n \
  -H 'content-type: application/json' \
  --data @failed-execution.json
```

### 2. Dry-run against the current n8n workflow

```bash
curl -X POST http://localhost:8000/v1/patches/<proposal-id>/dry-run/n8n
```

This fetches the current workflow server-side and stores its version/fingerprint with the validated diff.

A local/client-provided workflow dry-run endpoint also remains available for development:

```bash
curl -X POST http://localhost:8000/v1/patches/<proposal-id>/dry-run \
  -H 'content-type: application/json' \
  --data @workflow-request.json
```

### 3. Approve the validated snapshot

```bash
curl -X POST http://localhost:8000/v1/patches/<proposal-id>/approve \
  -H 'content-type: application/json' \
  -d '{"approved_by":"human-operator","note":"Reviewed retry-only diff"}'
```

Approval before dry-run returns a conflict. A later dry-run invalidates the previous approval.

### 4. Controlled apply + retry

This endpoint remains inert until both side-effect gates are explicitly enabled:

```bash
ALLOW_WORKFLOW_MUTATION=true
ALLOW_EXECUTION_RETRY=true
```

Then:

```bash
curl -X POST http://localhost:8000/v1/patches/<proposal-id>/apply-retry
```

The server refetches the workflow, rejects stale state, reconstructs the patch itself, saves a draft-only update, verifies persistence and structural invariants, retries the original failed execution once, and returns the first verification result.

## Measured evaluation

### Failure diagnosis

| Suite | Cases | Classification accuracy | Retry-safety accuracy |
|---|---:|---:|---:|
| Taxonomy V1 smoke | 9 | 100% | 100% |
| Taxonomy V2 hard suite | 64 | **100%** | **100%** |

### Patch safety

| Suite | Cases | Safe cases | Unsafe traps | Decision accuracy | Unsafe false accepts | Safe false rejects |
|---|---:|---:|---:|---:|---:|---:|
| Patch Safety V1 | 22 | 3 | 19 | **100%** | **0%** | **0%** |

### Remediation safety

| Suite | Cases | State-machine accuracy | Unsafe workflow writes | Unsafe execution retries |
|---|---:|---:|---:|---:|
| Remediation Safety V1 | 10 | **100%** | **0%** | **0%** |

The remediation suite covers successful verification, failed retry, pending retry, stale version, stale same-version snapshot, mutation gate disabled, retry gate disabled, missing dry run, missing approval, and persistence mismatch.

Measured in GitHub Actions run `32013203023` on commit `94ed1805e829984e331290a4d111787dc38c5112`. That run also reported **36 tests passed**, retained the 9/9 and 64/64 diagnosis gates, retained Patch Safety V1 at 22/22, and built the production Docker image successfully.

Durable machine-readable summaries:

- `evals/results/taxonomy_v2_summary.json`
- `evals/results/patch_safety_v1_summary.json`
- `evals/results/remediation_safety_v1_summary.json`

These are bounded regression results. The datasets are deterministic, synthetic/hand-labeled, and the remediation path is exercised with mocks rather than a live production n8n instance. They do not establish universal safety under every concurrency, network, node-specific, or third-party failure mode.

## CI

Every push and pull request gates:

1. package installation
2. Ruff linting
3. unit/API/integration tests
4. 9-case Taxonomy V1
5. 64-case hard Taxonomy V2
6. 22-case Patch Safety V1 with required 0% unsafe false accepts
7. 10-case Remediation Safety V1 with required 0% unsafe writes and 0% unsafe retries
8. production Docker image build

## Current limitations

- proposal, dry-run, and approval state is currently in process memory; a restart loses it
- the apply endpoint does not yet have a persistent idempotency record, so production exactly-once semantics are not claimed
- a crash or network failure after the workflow update but before retry needs durable recovery state
- retry verification performs one immediate read; a still-running execution is returned as `pending` rather than polled in the background
- the write serializer tracks the current n8n public API contract and should remain contract-tested as n8n evolves
- no live n8n production workflow was mutated as part of the committed benchmark
- diagnosis is still deterministic; model-assisted diagnosis has not been allowed into the mutation decision path

## Next milestone — durable incident state and idempotent recovery

Before adding an LLM agent, the mutation path needs durable operational semantics:

1. persist incidents, proposals, dry-run bindings, approvals, and remediation attempts in SQLite/PostgreSQL
2. assign idempotency keys so a repeated apply request cannot execute a second workflow update or second retry
3. record explicit remediation states such as `validated`, `approved`, `updating`, `updated`, `retrying`, `verified`, and `needs_recovery`
4. recover safely after process/network failure between update, verification, and retry
5. store an append-only audit timeline without storing raw credentials or execution items
6. produce a client/recruiter-readable incident report from that timeline
7. add concurrency and duplicate-request benchmark cases
8. only after this baseline is durable, add evidence-grounded model-assisted diagnosis and compare it against the deterministic classifier without weakening write safety
