# AI Automation Doctor

**v0.2.0** — a production-shaped reliability system for failed automations, starting with n8n.

The system can ingest a failed n8n execution, normalize the error into a privacy-minimized incident record, classify the likely root cause, decide whether retry is safe, propose a constrained patch for supported transient failures, validate that proposal against a deny-by-default mutation policy, and require explicit human approval before any workflow write-back.

## Why this project exists

Automation teams spend significant time opening failed executions, interpreting node errors, deciding whether a retry is safe, changing workflow JSON, validating the change, and explaining incidents to clients. AI Automation Doctor turns that debugging loop into an evaluated reliability system without pretending every failure should be autonomously fixed.

## Current architecture

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
          human approval
             |
             v
   workflow mutation (disabled by default)
             |
             v
      retry + verification + incident report
             ^
             |
       NEXT MILESTONE
```

## Completed in v0.2.0

- real n8n execution payload normalization
- `data.resultData.error` and `lastNodeExecuted` extraction
- fallback extraction from per-node `runData` errors
- support for API-style and UI-style n8n failure exports
- direct raw-payload ingestion API
- configured n8n execution fetch + analysis API
- metadata-only failed-execution listing in the n8n client
- execution-data redaction requested when fetching detailed execution data
- credentials, full workflow bodies, and raw execution items excluded from normalized incidents
- deterministic precedence for explicit HTTP 401/403, 429, 408, and 504 statuses
- transport-code coverage including `ECONNREFUSED`, `ENOTFOUND`, `EAI_AGAIN`, `ECONNRESET`, `ECONNABORTED`, and `ETIMEDOUT`
- conservative handling of ambiguous 400/404/409/410/5xx failures
- webhook detection scoped to webhook nodes rather than treating every 404 as a webhook problem
- 64-case hard failure-classification benchmark
- CI gates for Ruff, tests, V1 benchmark, V2 hard benchmark, and Docker build

## Safety contract

- workflow mutation is disabled by default
- every workflow patch requires explicit human approval
- credential paths are forbidden
- node type/version mutation is forbidden in the baseline
- generated Code/Execute Command content is forbidden
- patch operation count is bounded
- authentication, data-mapping, configuration, webhook, and unknown failures do not receive automatic retry patches
- transient retries must be bounded
- ambiguous failures fail closed to `unknown` instead of being aggressively patched
- normalization does not retain credential references or raw execution item data

## Failure taxonomy

The deterministic baseline currently classifies:

- authentication / authorization
- rate limiting
- timeouts
- network failures
- data/expression mapping failures
- webhook routing/registration failures
- explicit configuration failures
- unknown / escalate

`unknown` is an intentional safety outcome. The system is expected to refuse mutation when evidence is insufficient.

## API

Run locally:

```bash
cp .env.example .env
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

### Analyze an already-normalized failure

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

### Ingest a raw n8n failed-execution payload

```bash
curl -X POST http://localhost:8000/v1/incidents/ingest/n8n \
  -H 'content-type: application/json' \
  --data @failed-execution.json
```

### Fetch and analyze an execution from n8n

Configure:

```bash
N8N_BASE_URL=https://your-n8n.example.com
N8N_API_KEY=replace-me
```

Then:

```bash
curl -X POST http://localhost:8000/v1/incidents/n8n/123/analyze
```

The n8n client requests detailed execution data with redaction enabled. The internal normalizer then keeps only diagnosis-relevant metadata rather than storing the entire execution object.

## Measured evaluation

### V1 smoke suite

| Suite | Cases | Classification accuracy | Retry-safety accuracy |
|---|---:|---:|---:|
| Taxonomy V1 | 9 | 100% | 100% |

### V2 hard suite

The V2 benchmark contains **64 hand-labeled adversarial cases** covering status/message conflicts, credential failures, throttling, timeout and transport failures, mapping errors, webhook-vs-ordinary-404 disambiguation, explicit configuration failures, and ambiguous cases where the correct output is `unknown` with no retry.

| Suite | Cases | Classification accuracy | Retry-safety accuracy |
|---|---:|---:|---:|
| Taxonomy V2 hard suite | 64 | **100%** | **100%** |

Measured in GitHub Actions run `32010646804` on commit `a90843b3fe299c0ea6279940e5447c1245fe93a0`. The machine-readable summary is committed at `evals/results/taxonomy_v2_summary.json`.

This score is deliberately treated as a **regression-baseline result**, not a universal-accuracy claim. The suite is synthetic and hand-labeled. Real production execution samples, distribution shift, unseen node-specific errors, and model-assisted diagnosis remain separate evaluation work.

## CI

Every push and pull request gates:

1. package installation
2. Ruff linting
3. unit/API/integration tests
4. V1 taxonomy regression benchmark
5. V2 64-case hard taxonomy benchmark
6. production Docker image build

At the v0.2.0 ingestion milestone, CI reports **15 tests passed**, both taxonomy suites at their required thresholds, and a successful Docker build.

## Next milestone — workflow-aware dry-run patching

The next engineering stage is not broader classification. It is proving that a proposed fix can be applied safely to real n8n workflow JSON without corrupting the workflow.

Planned work:

1. workflow fixture loader and node-address resolution
2. JSON Patch application against an immutable copy
3. before/after dry-run diff
4. structural invariants: node IDs/types/connections/credentials preserved
5. explicit allowlist of mutable parameter paths
6. unsafe-patch trap benchmark
7. patch validation endpoint that performs no n8n write
8. only after that: approved write-back, execution retry, and post-fix verification

Model-assisted diagnosis and MCP tools come later. The deterministic and structural safety baselines remain the reference that any agentic version must beat without increasing unsafe mutations.
