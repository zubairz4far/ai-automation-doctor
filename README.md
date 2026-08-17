# AI Automation Doctor

**v0.3.0** — an evaluated reliability system for failed automations, starting with n8n.

The system ingests failed n8n executions, converts them into privacy-minimized incidents, classifies likely root causes and retry safety, proposes tightly constrained retry patches for supported transient failures, and can now apply those proposals to a **deep copy of real n8n workflow JSON** to produce a validated dry-run diff. Workflow mutation remains disabled by default and no dry-run endpoint writes to n8n.

## Why this project exists

Automation teams spend significant time opening failed executions, interpreting node errors, deciding whether retry is safe, changing workflow JSON, proving the change did not damage the workflow, retrying the execution, and explaining the incident to clients. AI Automation Doctor turns that loop into an evaluated reliability system without pretending every failure should be autonomously fixed.

## Architecture

```text
n8n failed execution / Error Workflow / API payload
                       |
                       v
               n8n execution normalizer
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
             +--> allowlisted retry option changes
             +--> before/after diff
             +--> structural fingerprint
             +--> protected invariant checks
             |
             v
          human approval
             |
             v
   workflow mutation (still disabled by default)
             |
             v
      retry + post-fix verification
             ^
             |
       NEXT MILESTONE
```

## Completed milestones

### v0.2.0 — real n8n execution ingestion

- real n8n execution payload normalization
- `data.resultData.error` and `lastNodeExecuted` extraction
- fallback extraction from per-node `runData` errors
- API-style and UI-style n8n failure export support
- direct raw-payload ingestion endpoint
- configured n8n execution fetch + analysis endpoint
- metadata-only failed-execution listing in the n8n client
- detailed execution fetch requests redaction
- credentials, workflow bodies, and raw execution items excluded from normalized incidents
- deterministic status precedence for 401/403, 429, 408, and 504
- transport-code coverage including `ECONNREFUSED`, `ENOTFOUND`, `EAI_AGAIN`, `ECONNRESET`, `ECONNABORTED`, and `ETIMEDOUT`
- conservative `unknown` handling for ambiguous failures
- 64-case adversarial failure-classification benchmark

### v0.3.0 — workflow-aware dry-run patching

- logical node addressing with JSON Pointer escaping for node names containing `/` or `~`
- exact unique-node resolution against n8n's array-based `nodes` structure
- dry-run application to a deep copy; caller workflow remains unchanged
- allowlist limited to `retryOnFail`, `maxTries`, and `waitBetweenTries`
- strict retry bounds and type validation
- single-target-node policy
- workflow-ID mismatch rejection
- duplicate target-node-name rejection
- `replace` requires an existing option
- connections and settings must remain byte-for-byte equivalent as parsed JSON
- non-target nodes must remain unchanged
- target node ID, name, type, typeVersion, position, webhook ID, and credentials are protected
- all non-allowlisted target-node parameters/options are protected
- structural fingerprint before/after must match
- dry-run API returns only the safe change preview and fingerprints, not the credential-bearing workflow snapshot
- 22-case patch-safety trap benchmark

## Safety contract

- workflow mutation is disabled by default
- every patch requires explicit human approval
- auto-apply is forbidden by the baseline policy
- patch operation count is bounded
- one baseline patch may target exactly one workflow node
- credentials cannot be changed
- node type/version cannot be changed
- node IDs, names, positions, webhook IDs, connections, and workflow settings cannot be changed by the dry-run engine
- generated Code/Execute Command content is outside the patch allowlist
- arbitrary URL/body/expression edits are outside the patch allowlist
- `retryOnFail` may only be enabled
- `maxTries` is bounded to 1–5
- `waitBetweenTries` is bounded to 250–60000 ms
- ambiguous failures fail closed to `unknown`
- authentication, mapping, configuration, webhook, and unknown failures do not receive automatic retry proposals
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
```

```bash
curl -X POST http://localhost:8000/v1/incidents/n8n/123/analyze
```

### Dry-run a generated patch against workflow JSON

First analyze an incident and capture its `patch.proposal_id`. Then send the workflow snapshot to:

```bash
curl -X POST http://localhost:8000/v1/patches/<proposal-id>/dry-run \
  -H 'content-type: application/json' \
  --data '{"workflow": {"id":"...","name":"...","nodes":[],"connections":{},"settings":{}}}'
```

The response contains the target node, before/after values for the allowlisted changes, validation notes, and matching structural fingerprints. It intentionally does **not** return the full patched workflow.

## Measured evaluation

### Failure diagnosis

| Suite | Cases | Classification accuracy | Retry-safety accuracy |
|---|---:|---:|---:|
| Taxonomy V1 smoke | 9 | 100% | 100% |
| Taxonomy V2 hard suite | 64 | **100%** | **100%** |

The 64-case V2 suite includes status/message conflicts, credential failures, throttling, timeout and transport errors, mapping failures, webhook-vs-ordinary-404 traps, explicit configuration failures, and ambiguous cases where the intended answer is `unknown` with no retry.

Machine-readable summary: `evals/results/taxonomy_v2_summary.json`.

### Patch safety

| Suite | Cases | Safe cases | Unsafe traps | Decision accuracy | Unsafe false accepts | Safe false rejects |
|---|---:|---:|---:|---:|---:|---:|
| Patch Safety V1 | 22 | 3 | 19 | **100%** | **0%** | **0%** |

The trap suite includes credential edits, node type/version edits, Code/Execute Command content, arbitrary URL changes, workflow settings/connections changes, excessive or invalid retries, multi-node patches, missing approval, and auto-apply attempts.

Measured in GitHub Actions run `32011308725` on commit `aa0e28ef5b36183e0b9bcc82c593c3aed9731ff4`. Machine-readable summary: `evals/results/patch_safety_v1_summary.json`.

These benchmark scores are **bounded regression results**, not universal accuracy or safety claims. The datasets are synthetic and hand-labeled. Real production distributions, unknown node-specific behavior, and model-assisted diagnosis require separate evaluation.

## CI

Every push and pull request gates:

1. package installation
2. Ruff linting
3. unit/API/integration tests
4. 9-case taxonomy V1 benchmark
5. 64-case hard taxonomy V2 benchmark
6. 22-case patch-safety benchmark with a required 0% unsafe false-accept rate
7. production Docker image build

At the measured v0.3.0 dry-run milestone, CI reported **23 tests passed**, all three benchmark gates passed, and the Docker build completed successfully.

## Why dry-run comes before write-back

n8n workflows are structured objects with an array of nodes plus connections and settings. The public workflow schema requires the core workflow fields and also exposes read-only/versioning metadata. The Doctor therefore does not treat a proposed string path as permission to edit arbitrary JSON. The patch is first resolved against the actual workflow structure, applied to a copy, and checked against protected invariants.

This is also important because current n8n workflow editing is versioned: saved changes and published production behavior are distinct concerns. Write-back and execution retry therefore need their own explicit state machine rather than being hidden inside the patch planner.

## Next milestone — controlled apply, retry, and verification

The next stage will add the first mutation-capable path, but keep it gated:

1. fetch the current workflow and record its version/fingerprint
2. run and store a successful dry-run result
3. require explicit human approval after that dry run
4. rebuild the patched workflow from the current version rather than trusting a client-supplied patched body
5. serialize only fields accepted by the n8n public workflow API
6. reject stale workflow/version or fingerprint mismatches
7. keep `ALLOW_WORKFLOW_MUTATION=false` as the default hard gate
8. when enabled, perform one approved update
9. retry the failed execution with bounded behavior
10. fetch the retry result and verify success/failure
11. produce an incident timeline/report containing diagnosis, patch, approval, update, retry, and verification evidence

Model-assisted diagnosis and MCP tools remain later stages. Any agentic component must beat the deterministic and structural safety baselines without increasing unsafe mutations.
