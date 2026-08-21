# AI diagnosis benchmark findings — measured v2

This note records the first completed real-model comparison on `evals/ai_diagnosis_v1.jsonl` before changing the advisory prompt architecture.

## Measured result

The 32-case challenge set produced:

| Metric | Qwen3-1.7B base | Tool-calling adapter |
|---|---:|---:|
| Overall classification accuracy | 31.25% | 25.00% |
| Accuracy on normalized valid outputs | 34.48% | 30.77% |
| Raw schema validity | 90.625% | 81.25% |
| Provider/parse failure rate | 0.00% | 18.75% |
| Deterministic challenge baseline | 12.50% | 12.50% |

The tool-calling adapter therefore regressed by 6.25 percentage points in overall diagnosis accuracy and by 9.375 percentage points in raw schema validity relative to the base model.

This is not treated as a failed experiment. The adapter was trained for structured tool routing, not incident diagnosis, so the result is evidence that task-specific fine-tuning does not automatically transfer to a different classification domain.

## Important prompt-architecture finding

Inspection of the case outputs showed strong anchoring to the deterministic baseline context. The model repeatedly copied the baseline confidence, root-cause wording, and escalation recommendation instead of producing an independent advisory assessment.

That input shape was unnecessary for safety. `GuardedDiagnosisEngine` already uses the deterministic diagnosis to decide whether AI may be called, and deterministic fields remain authoritative for retry safety and patch planning.

The production provider has therefore been changed so that:

1. deterministic diagnosis is still computed first and remains authoritative;
2. the deterministic diagnosis is **not serialized into the LLM prompt**;
3. the LLM receives only privacy-minimized failure metadata;
4. the system prompt contains explicit semantics for all eight failure classes;
5. the model is instructed to prefer the most specific supported class over `unknown`;
6. strict output validation and fail-closed behavior remain unchanged.

## Next experiment: de-anchored v3

Rerun the exact same 32 cases against the same two model variants with the new prompt/context. This isolates prompt/context architecture as the independent variable.

Primary success criteria are measured relative to the v2 baseline, not invented absolute thresholds:

- base-model accuracy > 31.25%;
- adapter accuracy > 25.00%;
- no regression in raw schema validity without a corresponding material accuracy gain;
- reduced over-prediction of `unknown` on known classes;
- confidence values and root-cause text no longer mechanically mirror the deterministic baseline.

If the de-anchored base model improves materially, keep the base model as the advisory baseline and optimize prompt/schema behavior before any new training. If performance remains weak, the next justified step is a diagnosis-specific dataset and QLoRA rather than reusing the tool-routing adapter.

Machine-readable v2 comparison: `evals/results/ai_diagnosis_qwen3_vs_adapter_comparison_v2.json`.
