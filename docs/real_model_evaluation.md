# Real-model AI diagnosis evaluation

AI Automation Doctor evaluates its advisory diagnosis layer separately from its deterministic control plane. The LLM can add operator context, but deterministic diagnosis remains authoritative for retry safety, patch planning, approval, and remediation.

## Evaluation design

The repository now uses three balanced 32-case sets across eight classes:

- authentication
- rate limit / capacity exhaustion
- timeout / deadline
- network / transport
- data mapping
- webhook / callback registration
- node / connector configuration
- genuinely unknown provider failures

Each set has four examples per class. Integrity tests require the deterministic engine to return `unknown` on every example, so these sets measure incremental advisory classification rather than easy deterministic keyword matches.

The original `evals/ai_diagnosis_v1.jsonl` is now treated as the development set because its failures were inspected while improving the prompt. `evals/ai_diagnosis_holdout_v2.jsonl` and `evals/ai_diagnosis_holdout_v3.jsonl` were created as fresh holdouts before their corresponding runs.

## Why the prompt changed

The first real-model run showed that both Qwen3-1.7B and the existing tool-calling QLoRA adapter copied the deterministic baseline's `unknown` class, `0.35` confidence, root-cause wording, and escalation action. That was an input-design problem: the advisory model was being asked to classify independently while simultaneously being shown the baseline answer.

The production provider was changed so the model receives only privacy-minimized failure metadata:

- node type
- error message
- bounded error stack
- error code
- status code

The deterministic baseline is still used to decide whether AI should be called, but it is not serialized into the model context. The system prompt now defines the taxonomy explicitly and gives boundary rules for configuration vs data mapping, webhook vs network, and opaque unknown failures.

## Measured results

### Development set

After de-anchoring and adding explicit taxonomy semantics:

| Model | Accuracy | Raw schema validity | Provider failure |
|---|---:|---:|---:|
| Qwen3-1.7B | 81.25% | 100% | 0% |
| Tool-calling adapter | 84.375% | 100% | 0% |

These scores are useful for development but are not the strongest generalization evidence because the set informed prompt changes.

### First unseen holdout

| Model | Accuracy | Raw schema validity | Provider failure |
|---|---:|---:|---:|
| Qwen3-1.7B | 87.5% | 93.75% | 0% |
| Tool-calling adapter | 87.5% | 93.75% | 0% |

The only schema failures were empty `evidence` arrays despite usable error text. The strict provider schema rejected them rather than weakening the contract.

### Second blind holdout

After adding generic evidence and taxonomy-boundary guidance, a second untouched holdout was evaluated:

| Model | Accuracy | Raw schema validity | Provider failure |
|---|---:|---:|---:|
| **Qwen3-1.7B** | **93.75%** | **100%** | **0%** |
| Tool-calling adapter | 84.375% | 100% | 0% |

Base Qwen3-1.7B missed two of 32 cases: one webhook-vs-network boundary and one configuration-vs-data-mapping boundary. The tool-calling adapter missed five cases, including rate-limit, timeout, webhook, and configuration boundaries.

The adapter was trained for structured tool routing, not incident diagnosis. These results show that its tool-calling fine-tune does not consistently transfer to this classification domain. **Base `Qwen/Qwen3-1.7B` is therefore the recommended diagnosis model for this release.**

Machine-readable evidence:

- `evals/results/ai_diagnosis_deanchored_v3_summary.json`
- `evals/results/ai_diagnosis_holdout_v4_comparison.json`
- `evals/results/ai_diagnosis_blind2_v5_comparison.json`
- `evals/results/ai_diagnosis_release_summary_v1.2.1.json`

## Reproducing a model run

Start an OpenAI-compatible endpoint. For base Qwen with vLLM:

```bash
pip install vllm
vllm serve Qwen/Qwen3-1.7B --host 0.0.0.0 --port 8000
```

Then run the repository evaluator against any dataset:

```bash
python -m scripts.evaluate_ai_diagnosis \
  --dataset evals/ai_diagnosis_holdout_v3.jsonl \
  --api-base-url http://localhost:8000/v1 \
  --model Qwen/Qwen3-1.7B \
  --output evals/results/local_qwen_holdout.json
```

The existing tool-calling adapter can still be compared using a LoRA-capable server:

```bash
vllm serve Qwen/Qwen3-1.7B \
  --host 0.0.0.0 \
  --port 8000 \
  --enable-lora \
  --lora-modules tool-calling=zubairz4far/qwen3-1.7b-tool-calling
```

## Metrics

The evaluator reports:

- deterministic baseline accuracy and unknown rate
- AI overall classification accuracy
- AI accuracy delta in percentage points
- strict-schema validity rate
- schema failure rate
- provider/network/parse failure rate
- AI accuracy on valid outputs
- per-class results
- case-level predictions

Provider output still passes through the strict `AIInsightPayload` contract. Extra fields such as retry decisions or patches are rejected instead of becoming control-plane instructions.

## Suggested manual quality gate

The second blind base-model run supports the following conservative manual regression gate for future diagnosis-model changes:

```bash
python -m scripts.evaluate_ai_diagnosis \
  --dataset evals/ai_diagnosis_holdout_v3.jsonl \
  --api-base-url http://localhost:8000/v1 \
  --model your-model \
  --min-ai-accuracy 0.85 \
  --min-schema-validity 0.95 \
  --max-provider-failure-rate 0.05
```

This is a regression gate for these synthetic holdouts, not a claim of universal production accuracy. Live-model inference remains outside CI so pull requests require no provider secret, paid inference, or GPU runner.
