# LinkedIn launch post — AI Automation Doctor v1.3.0

I stopped fine-tuning the model and fixed the system around it.

That decision moved AI Automation Doctor from **31.25%** diagnosis accuracy to **93.75% on a second blind 32-case holdout**, with **100% raw schema validity** and **0% provider failures**.

Now the project has an interactive product demo too.

The interesting part is not the UI. It is the boundary behind it:

- deterministic logic still owns retry safety
- the LLM is advisory only
- the model cannot approve changes
- the model cannot mutate workflow JSON
- the model cannot execute retries
- public demo mode blocks the normal incident/remediation API entirely
- patch output in the demo is preview-only

The biggest model improvement came from removing the deterministic baseline answer from the LLM context. Small models were copying the baseline `unknown` class, `0.35` confidence, and wording instead of diagnosing independently.

After de-anchoring the prompt, defining failure-taxonomy boundaries, enforcing strict structured output, and validating on fresh holdouts:

**Initial base Qwen:** 31.25%
**De-anchored development run:** 81.25%
**First unseen holdout:** 87.5%
**Second blind holdout:** 93.75%

Base `Qwen/Qwen3-1.7B` also beat my tool-calling QLoRA adapter on the final diagnosis holdout, so I kept the base model for this task instead of forcing a fine-tune into production because it looked better on paper.

v1.3.0 now includes:

- FastAPI reliability service for failed n8n automations
- read-only `/demo` interface
- deterministic diagnosis + retry-safety controls
- optional OpenAI-compatible AI advisory layer
- bounded patch preview
- human approval and dry-run architecture for the real remediation path
- durable SQLite recovery and idempotency
- automated safety benchmarks and Docker CI
- public-demo-only runtime mode for safe portfolio deployment

Live demo: https://zubairz4far.github.io/ai-automation-doctor/
Repository: https://github.com/zubairz4far/ai-automation-doctor

The main lesson from this build: **before training another model, measure whether your context, control boundaries, and evaluation design are the actual problem.**

#AIEngineering #MachineLearning #LLM #FastAPI #n8n #Automation #MLOps #AIInfrastructure #SoftwareEngineering
