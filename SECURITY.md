# Security Policy

AI Automation Doctor can change n8n workflow definitions and request execution retries when explicitly enabled. Treat it as a privileged operations service.

## Safe defaults

The application ships with both side-effect gates disabled:

```env
ALLOW_WORKFLOW_MUTATION=false
ALLOW_EXECUTION_RETRY=false
```

Enabling either gate requires `OPERATOR_TOKEN`, and the HTTP boundary requires that shared secret in the `X-Doctor-Operator-Token` header for approval and apply/retry endpoints.

For production, terminate TLS in front of the service and restrict network access to trusted operators. A reverse proxy, workload identity, mTLS, or OIDC gateway can provide stronger authentication than the built-in shared-secret baseline.

## n8n requirements

Use a currently patched n8n release and review n8n security advisories before enabling mutation or retry. In particular, n8n's public execution-retry API had an authorization bypass tracked as `GHSA-h3jj-5f3v-3685`; n8n reports fixes in 2.25.7 and 2.26.2. Those versions are historical minimum fixes for that advisory, not a recommendation to remain on an old release.

Use an n8n API key with only the scopes needed by the deployment. Keep the n8n API endpoint private where possible.

## Data handling

- Raw execution items are not persisted by the Doctor.
- Caller-supplied `input_snapshot` and `workflow_snapshot` fields are cleared before durable incident storage.
- Detailed n8n execution fetches request execution-data redaction.
- Dry-run storage contains fingerprints and safe diffs, not a credential-bearing patched workflow body.
- Timeline events contain bounded operational metadata, not raw workflow or execution payloads.
- Never put `N8N_API_KEY`, `OPERATOR_TOKEN`, credentials, or `.env` files in Git.

The SQLite database can contain incident descriptions, workflow/execution identifiers, diagnoses, approvals, and operational audit history. Store it on a protected persistent volume with filesystem permissions appropriate for secrets-adjacent operational data. Back it up according to your retention requirements.

## Mutation safety boundary

The v1 automatic patch allowlist is intentionally narrow. A patch can target one uniquely resolved node and only the n8n node-level fields:

- `retryOnFail`
- `maxTries`
- `waitBetweenTries`

Credentials, node identity/type/version, arbitrary URLs/bodies/expressions, code/commands, connections, and workflow settings are not automatically mutable.

Every write requires a successful dry run followed by explicit approval bound to the exact workflow `versionId` and SHA-256 snapshot fingerprint. The workflow is fetched again before mutation. Stale or ambiguous state fails closed.

## Idempotency and crash recovery

SQLite-backed remediation state records each side-effect boundary. A lease prevents concurrent apply attempts for the same proposal.

If the process stops around a workflow update, recovery compares the current n8n workflow with the expected approved writable-definition fingerprint before continuing. It does not blindly repeat the update.

If the process stops after a retry may have been requested but before its execution ID was stored, recovery searches n8n execution metadata for an execution whose `retryOf` points at the original execution. If that evidence cannot be found, recovery stops with a manual-reconciliation error rather than risking a duplicate retry.

## Deployment limitations

The default durable store is SQLite and the lease is database-local. This is a single-service-instance production baseline. Multi-replica deployments require a shared transactional store and distributed lease/lock implementation before side effects should be enabled.

Retry verification performs a bounded immediate read. A nonterminal n8n execution is returned as `pending`; the service does not run an unbounded background poller.

The included evaluation suites use deterministic fixtures and mocks. They verify the implemented invariants but do not prove safety for every n8n node, third-party API, concurrency pattern, or infrastructure failure.

## Reporting a vulnerability

Do not open a public issue containing credentials, tokens, customer payloads, exploit details against a live system, or other sensitive information. Contact the repository owner privately before public disclosure when possible.
