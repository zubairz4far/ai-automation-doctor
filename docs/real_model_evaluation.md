# Real-model AI diagnosis evaluation

v1.2 adds a reproducible live-model benchmark for the advisory diagnosis layer. The benchmark does not change the safety contract: deterministic diagnosis remains authoritative for retry safety, patch planning, approval, and remediation.

## Challenge set

`evals/ai_diagnosis_v1.jsonl` contains 32 synthetic, hand-labeled cases across:

- authentication
- rate limiting / capacity exhaustion
- latency / deadline failures
- network / transport failures
- data mapping
- callback / webhook registration
- node configuration
- genuinely unknown provider failures

The cases deliberately avoid the deterministic engine's high-confidence keywords. CI locks the requirement that the deterministic baseline returns `unknown` for every case. That makes the set useful for measuring whether an advisory model adds information rather than repeating easy rules.

## Option A: Qwen3-1.7B baseline with vLLM

Install vLLM in a GPU environment and start the OpenAI-compatible server:

```bash
pip install vllm
vllm serve Qwen/Qwen3-1.7B --host 0.0.0.0 --port 8000
```

Run the benchmark from this repository:

```bash
python -m scripts.evaluate_ai_diagnosis \
  --api-base-url http://localhost:8000/v1 \
  --model Qwen/Qwen3-1.7B \
  --output evals/results/ai_diagnosis_qwen3_1.7b.json
```

The first real run should establish a baseline without invented pass/fail thresholds. After reviewing that result, freeze explicit thresholds for future model comparisons.

## Option B: compare the existing tool-calling QLoRA adapter

The existing Hugging Face adapter can be served alongside the base model through vLLM LoRA support:

```bash
vllm serve Qwen/Qwen3-1.7B \
  --host 0.0.0.0 \
  --port 8000 \
  --enable-lora \
  --lora-modules tool-calling=zubairz4far/qwen3-1.7b-tool-calling
```

Then evaluate the adapter by using its served LoRA name as the model:

```bash
python -m scripts.evaluate_ai_diagnosis \
  --api-base-url http://localhost:8000/v1 \
  --model tool-calling \
  --output evals/results/ai_diagnosis_tool_calling_adapter.json
```

This adapter was trained for structured tool routing rather than incident diagnosis, so it is a comparison target, not an assumed improvement.

## Hosted OpenAI-compatible endpoint

The same benchmark works with a hosted provider or private gateway:

```bash
export AI_API_BASE_URL=https://provider.example/v1
export AI_API_KEY=replace-me
export AI_MODEL=provider-model-name
python -m scripts.evaluate_ai_diagnosis
```

The API key is never written to the benchmark result.

## Metrics

The output JSON includes:

- deterministic baseline accuracy
- deterministic baseline unknown rate
- AI overall classification accuracy
- AI accuracy delta in percentage points
- strict-schema validity rate
- schema failure rate
- provider/network/parse failure rate
- AI accuracy on valid outputs
- per-class results
- case-level predictions

Provider outputs still pass through the strict `AIInsightPayload` schema. Attempts to return undeclared fields such as retry decisions or patches are rejected instead of becoming control-plane instructions.

## Optional gates after a baseline is frozen

Once a measured model baseline is reviewed, the same command can enforce thresholds:

```bash
python -m scripts.evaluate_ai_diagnosis \
  --api-base-url http://localhost:8000/v1 \
  --model your-model \
  --min-ai-accuracy 0.75 \
  --min-schema-validity 0.95 \
  --max-provider-failure-rate 0.05
```

Do not copy these example values into a release gate until they are justified by an actual measured run.
