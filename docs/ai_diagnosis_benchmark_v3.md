# AI diagnosis benchmark v3

## Measured development-set result

The 32-case `evals/ai_diagnosis_v1.jsonl` challenge set was rerun after removing deterministic-baseline diagnosis text from the model context and adding explicit class semantics.

| Model | Previous accuracy | De-anchored accuracy | Delta | Raw schema validity |
|---|---:|---:|---:|---:|
| Qwen3-1.7B | 31.25% | 81.25% | +50.0 pp | 100% |
| tool-calling QLoRA adapter | 25.00% | 84.375% | +59.375 pp | 100% |

The adapter is now 3.125 percentage points above base Qwen on this development set. Both models produced strict-schema-valid output on all 32 cases with no evidence normalization required.

The improvement is attributable to prompt/context architecture, not a new training run. The previous prompt exposed the deterministic `unknown` diagnosis, confidence, root-cause wording, and recommendation to the advisory model. Small models copied that anchor heavily. The v3 prompt keeps deterministic gating outside the model and asks the advisory classifier to infer independently from privacy-minimized failure metadata.

## Remaining development-set errors

Base Qwen misses six cases:

- one webhook case as network
- three configuration cases as data mapping
- two opaque unknown cases as network

The tool-calling adapter misses five:

- three configuration cases as data mapping
- two opaque unknown cases as network

The next prompt revision therefore clarifies three general class boundaries:

1. node/action/mode/resource/request-contract problems are `configuration`; runtime item/field/type/selector/expression mismatches are `data_mapping`
2. absent callback listeners/routes/registrations are `webhook`; `network` requires explicit transport/connectivity evidence
3. opaque vendor/internal/policy states without direct evidence for another class are `unknown`, not automatically `network`

## Holdout policy

Because the v1 dataset has now influenced prompt design, it is a development set and should not be used as the primary evidence for the next revision.

`evals/ai_diagnosis_holdout_v2.jsonl` is a new balanced 32-case holdout with four cases for each class. CI locks two properties before any model score is accepted:

- exactly four cases per class
- deterministic baseline returns `unknown` at confidence `0.35` for every case

Do not tune the prompt on individual holdout mistakes before recording the first complete base/adapter result. If the holdout result is materially weaker than the development score, expand the taxonomy or create a separate training/development corpus before changing the holdout.

## Safety boundary

None of these changes give the model control-plane authority. Deterministic diagnosis remains authoritative for retry safety and patch planning; AI output is advisory-only, extra fields are rejected, and provider/parse/schema failures fail closed to the deterministic result.
