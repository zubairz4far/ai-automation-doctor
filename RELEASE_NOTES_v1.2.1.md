# AI Automation Doctor v1.2.1

## Evaluation-hardening release

v1.2.1 records the measured outcome of the real-model diagnosis work and hardens the model-selection methodology around blind evaluation rather than development-set tuning.

## Measured diagnosis results

Three balanced 32-case datasets are used across authentication, rate limit, timeout, network, data mapping, webhook, configuration, and unknown failures. Integrity tests require the deterministic engine to abstain on every benchmark case so the LLM is evaluated only on failures the rules engine cannot confidently classify.

| Stage | Qwen3-1.7B | Tool-calling QLoRA | Raw schema validity |
|---|---:|---:|---:|
| Initial live run | 31.25% | 25.0% | 90.625% / 81.25% |
| De-anchored development run | 81.25% | 84.375% | 100% / 100% |
| First unseen holdout | 87.5% | 87.5% | 93.75% / 93.75% |
| Second blind holdout | **93.75%** | 84.375% | **100% / 100%** |

Provider failure rate on the second blind holdout was 0% for both models.

## Main engineering finding

The dominant improvement did not come from another fine-tune. The first model input included the deterministic baseline diagnosis, which anchored small models to its `unknown` decision, `0.35` confidence, and explanatory wording. Removing that baseline answer from the model context and adding explicit taxonomy semantics produced the large accuracy gain.

Further improvements came from:

- explicit configuration-vs-data-mapping boundaries
- explicit webhook-vs-network boundaries
- treating opaque undocumented vendor states as `unknown` without invented transport evidence
- strict non-empty evidence requirements
- fresh holdouts after inspected benchmark failures

## Model selection

`Qwen/Qwen3-1.7B` is the recommended diagnosis model for v1.2.1.

The existing `zubairz4far/qwen3-1.7b-tool-calling` adapter remains a valid tool-routing portfolio artifact and comparison target, but its fine-tuning objective does not consistently improve incident diagnosis. On the second blind diagnosis holdout, base Qwen led the adapter by 9.375 percentage points.

## Remaining known limitations

On the second blind 32-case holdout, base Qwen missed two cases:

- one webhook-vs-network boundary
- one configuration-vs-data-mapping boundary

The 93.75% result is a bounded synthetic/hand-labeled benchmark. It is not a claim of universal n8n or production incident accuracy.

## Safety contract unchanged

The model is advisory-only. It cannot:

- decide retry safety
- approve remediation
- mutate workflow JSON
- choose unrestricted patches
- execute a retry

Deterministic diagnosis remains authoritative for control-plane decisions, and provider/network/parsing/schema failures fail closed to the deterministic result.

## Evidence

Machine-readable results are committed under `evals/results/`, including:

- `ai_diagnosis_deanchored_v3_summary.json`
- `ai_diagnosis_holdout_v4_summary.json`
- `ai_diagnosis_blind2_v5_comparison.json`
- `ai_diagnosis_release_summary_v1.2.1.json`

See `docs/real_model_evaluation.md` for reproduction and methodology.
