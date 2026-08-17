# AI Automation Doctor

**v0.3.0** — an evaluated reliability system for failed automations, starting with n8n.

AI Automation Doctor ingests failed n8n executions, converts them into privacy-minimized incidents, classifies likely root causes and retry safety, proposes tightly constrained retry patches for supported transient failures, and validates those patches against a deep copy of real n8n workflow JSON before any write is possible.

Workflow mutation remains disabled by default. The v0.3 dry-run path performs no n8n write.

## Architecture

```text
n8n failed execution / Error Workflow / API payload
                       |
                       v
               execution normalizer
                       |
                       v
         privacy-minimized incident record
                       |
                       v
          deterministic diagnosis baseline
                       |
             +---------+----------+
             |                    |
         retry-safe?          risky/unknown
             |                    |
             v                    v
       constrained patch       human diagnosis
           proposal               queue
             |
             v
       deny-by-default validator
             |
             v
     workflow-aware dry-run engine
             |
             +--> deep copy only
             +--> unique node resolution
             +--> node-level retry fields only
             +--> before/after diff
             +--> structural fingerprint
             +--> protected invariant checks
             |
             v
          human approval
             |
             v
   workflow mutation (disabled by default)
             |
             v
      retry + post-fix verification
             ^
             |
       NEXT MILESTONE
```

## Completed milestones

### v0.2.0 — real n8n execution ingestion

- normalizes `data.resultData.error` and `lastNodeExecuted`
- falls back to per-node `runData` errors
- supports API-style and UI-style n8n failure exports
- exposes raw-payload ingestion and configured execution-fetch analysis endpoints
- lists failed executions metadata-only through the n8n client
- requests redaction when fetching detailed execution data
- excludes credentials, full workflow bodies, and raw execution items from normalized incidents
- gives explicit HTTP 401/403, 429, 408, and 504 signals precedence over ambiguous message text
- recognizes transport codes including `ECONNREFUSED`, `ENOTFOUND`, `EAI_AGAIN`, `ECONNRESET`, `ECONNABORTED`, and `ETIMEDOUT`
- fails ambiguous cases closed to `unknown`
- includes a 64-case adversarial diagnosis benchmark

### v0.3.0 — workflow-aware dry-run patching

The current n8n node schema exposes `retryOnFail`, `maxTries`, and `waitBetweenTries` as node-level fields. The Doctor's patch allowlist is aligned to those fields.

- logical node addressing with JSON Pointer escaping for node names containing `/` or `~`
- unique target resolution against n8n's array-based `nodes` structure
- dry-run application to a deep copy; caller workflow remains unchanged
- allowlist limited to node-level `retryOnFail`, `maxTries`, and `waitBetweenTries`
- strict retry bounds and type validation
- single-target-node policy
- workflow-ID mismatch rejection
- duplicate target-node-name rejection
- `replace` requires an existing node field
- connections and settings must remain unchanged
- non-target nodes must remain unchanged
- on the target node, every field except the three allowlisted retry fields must remain unchanged
- parameters, credentials, node ID/name/type/typeVersion/position/webhook ID are therefore protected
- structural fingerprint before and after must match
- dry-run API returns only a safe change preview and fingerprints, not the credential-bearing workflow snapshot
- 22-case patch-safety trap benchmark

## Safety contract

- `ALLOW_WORKFLOW_MUTATION=false` by default
- every patch requires explicit human approval
- auto-apply is forbidden by the baseline policy
- patch operation count is bounded
- one baseline patch may target exactly one node
- credentials cannot be changed
- node ID/name/type/typeVersion/position/webhook ID cannot be changed
- workflow connections/settings cannot be changed
- arbitrary URL/body/expression/code/command changes are outside the allowlist
- `retryOnFail` may only be enabled
- `maxTries` is bounded to 1–5
- `waitBetweenTries` is bounded to 250–60000 ms
- authentication, mapping, configuration, webhook, and unknown failures receive no automatic retry patch
- ambiguous failures fail closed to `unknown`
- dry-run never performs an n8n write

## API

Run locally:

```bash
cp .env.example .env
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

### Analyze a normalized failure

```bash
curl -X POST http://localhost:8000/v1/incidents/analyze \
  -H 'content-type: application/json' \
  -d '{
    "execution_id":"123",
    "workflow_id":"abc",
    "failed_node":"HTTP Request",
    "node_type":"n8n-nodes-base.httpRequest",
    "error_message":"429 Too Many Requests",
    "status_code":429
  }'
```

### Ingest a raw n8n failed execution

```bash
curl -X POST http://localhost:8000/v1/incidents/ingest/n8n \
  -H 'content-type: application/json' \
  --data @failed-execution.json
```

### Fetch and analyze an execution from n8n

```bash
N8N_BASE_URL=https://your-n8n.example.com
N8N_API_KEY=replace-me
curl -X POST http://localhost:8000/v1/incidents/n8n/123/analyze
```

### Dry-run a generated patch

Analyze an incident, capture `patch.proposal_id`, then send the workflow snapshot to:

```bash
curl -X POST http://localhost:8000/v1/patches/<proposal-id>/dry-run \
  -H 'content-type: application/json' \
  --data @workflow-request.json
```

Example request shape:

```json
{
  "workflow": {
    "id": "workflow-id",
    "name": "Lead Intake",
    "nodes": [],
    "connections": {},
    "settings": {}
  }
}
```

The response contains target node, before/after allowlisted values, validation notes, and matching structural fingerprints. It intentionally does not return the full patched workflow.

## Measured evaluation

### Failure diagnosis

| Suite | Cases | Classification accuracy | Retry-safety accuracy |
|---|---:|---:|---:|
| Taxonomy V1 smoke | 9 | 100% | 100% |
| Taxonomy V2 hard suite | 64 | **100%** | **100%** |

The V2 suite includes status/message conflicts, credential failures, throttling, timeout and transport errors, mapping failures, webhook-vs-ordinary-404 traps, configuration failures, and ambiguous cases whose expected action is `unknown` with no retry.

Machine-readable result: `evals/results/taxonomy_v2_summary.json`.

### Patch safety

| Suite | Cases | Safe cases | Unsafe traps | Decision accuracy | Unsafe false accepts | Safe false rejects |
|---|---:|---:|---:|---:|---:|---:|
| Patch Safety V1 | 22 | 3 | 19 | **100%** | **0%** | **0%** |

The safe cases use the actual n8n node-level retry fields. Unsafe traps include credential edits, node type/version changes, Code/Execute Command content, arbitrary URL changes, workflow settings/connections changes, excessive or invalid retries, multi-node patches, approval bypass, and auto-apply attempts.

Corrected schema-aligned measurement: GitHub Actions run `32011661010`, commit `57848718a2d24609776e9deb30b452fd11f306c9`.

Machine-readable result: `evals/results/patch_safety_v1_summary.json`.

These scores are bounded regression results, not universal accuracy or safety claims. The evaluation sets are synthetic and hand-labeled; real production distributions and unseen node-specific behavior remain separate evaluation work.

## CI

Every push and pull request gates:

1. package installation
2. Ruff linting
3. unit/API/integration tests
4. 9-case Taxonomy V1
5. 64-case hard Taxonomy V2
6. 22-case Patch Safety V1 with required 0% unsafe false accepts
7. production Docker image build

On the corrected v0.3.0 schema-aligned run, CI reported **23 tests passed**, both diagnosis benchmarks passed, Patch Safety V1 passed at 100% with zero false accepts/rejects, and the Docker build succeeded.

## Why dry-run comes before write-back

An n8n workflow contains an array of nodes plus connections and settings. A proposed logical path is therefore not treated as permission to edit arbitrary workflow JSON. The Doctor resolves the intended node, applies only the three node-level retry fields to a copy, and checks all protected structure before returning a diff.

This creates a deterministic safety baseline for the later agentic layer: any model-assisted patcher must preserve the same invariants and must not increase unsafe mutations.

## Next milestone — controlled apply, retry, and verification

The first mutation-capable stage will remain tightly gated:

1. fetch the current workflow and record its version/fingerprint
2. store a successful dry-run result for the proposal
3. require explicit human approval **after** that dry-run
4. fetch the workflow again before applying
5. rebuild the patch from the current workflow instead of trusting a client-supplied patched body
6. serialize only fields accepted by the n8n public workflow API
7. reject stale workflow/version/fingerprint mismatches
8. keep `ALLOW_WORKFLOW_MUTATION=false` as the hard default gate
9. when explicitly enabled, perform one approved update
10. retry the failed execution with bounded behavior
11. fetch and verify the retry result
12. produce an incident timeline containing diagnosis, patch, dry-run, approval, update, retry, and verification evidence

Model-assisted diagnosis and MCP tools remain later stages. They must beat the deterministic and structural safety baselines without increasing unsafe mutations.
