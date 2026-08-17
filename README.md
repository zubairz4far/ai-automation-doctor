# AI Automation Doctor

A production-shaped reliability agent for automation platforms, starting with n8n.

The system ingests a failed execution, classifies the root cause, proposes a constrained workflow patch when the failure is safely patchable, validates the proposal against a deny-by-default mutation policy, and requires explicit human approval before any workflow write-back.

## Why this project exists

Automation teams spend significant time opening failed executions, interpreting node errors, deciding whether a retry is safe, changing workflow JSON, and explaining incidents to clients. This project turns that debugging loop into an evaluated, observable system without pretending every failure should be autonomously fixed.

## V0 architecture

```text
n8n failure / Error Workflow / API execution
              |
              v
        Failure normalizer
              |
              v
    Deterministic diagnosis baseline
              |
      +-------+--------+
      |                |
 retry-safe?        risky/unknown
      |                |
      v                v
 constrained       human diagnosis
 patch planner        queue
      |
      v
 safety validator
      |
      v
 human approval
      |
      v
 n8n workflow write-back (disabled by default)
      |
      v
 retry + verification + incident report
```

## Safety contract

- workflow mutation is disabled by default
- every patch requires explicit human approval
- credential paths are forbidden
- node type/version mutation is forbidden in the baseline
- generated Code/Execute Command content is forbidden
- patch operation count is bounded
- auth/data-mapping/unknown failures do not receive automatic retry patches
- external retry loops must be bounded

## Current failure taxonomy

- authentication / authorization
- rate limiting
- timeouts
- network failures
- data/expression mapping failures
- webhook routing failures
- configuration failures
- unknown / escalate

## API

Run locally:

```bash
cp .env.example .env
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Analyze a failure:

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

## Evaluation plan

V1 starts with deterministic taxonomy accuracy and patch-safety invariants. The next benchmark will add realistic n8n execution payloads, ambiguous failures, misleading stack traces, unsafe-fix traps, credential errors, and cases where the correct action is to refuse mutation.

## Next milestones

1. execution payload normalizer for real n8n failure JSON
2. 50+ case failure-diagnosis benchmark
3. workflow-aware patch application against fixture workflow JSON
4. dry-run diff and structural validation
5. n8n retry + post-fix verification adapter
6. model-assisted diagnosis compared against deterministic baseline
7. incident timeline, metrics, and client-facing report
8. optional MCP tools after the core reliability loop is measured
