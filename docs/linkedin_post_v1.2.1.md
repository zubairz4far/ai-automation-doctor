# LinkedIn Post — AI Automation Doctor v1.2.1

I spent the last few iterations trying to improve an LLM-based diagnosis layer for failed n8n automations.

The interesting part: **the biggest improvement did not come from another fine-tune.**

My first real-model benchmark was weak:

- Qwen3-1.7B: **31.25% accuracy**
- my tool-calling QLoRA adapter: **25.0%**

At first that looked like a model problem.

It was mostly an architecture/evaluation problem.

The LLM was receiving the deterministic baseline diagnosis in its context. On difficult cases, the baseline intentionally returned `unknown` with low confidence. The small models started copying that answer, confidence, and wording instead of independently diagnosing the failure.

So I changed the design:

- removed the deterministic answer from the LLM context
- kept deterministic logic authoritative for retry safety and remediation
- added explicit failure-taxonomy semantics
- tightened `configuration` vs `data_mapping`
- tightened `webhook` vs `network`
- required strict JSON with non-empty evidence
- stopped tuning on the same benchmark and created fresh holdouts

The progression:

| Evaluation | Base Qwen | Tool-calling adapter |
|---|---:|---:|
| Initial run | 31.25% | 25.0% |
| De-anchored dev set | 81.25% | 84.375% |
| First unseen holdout | 87.5% | 87.5% |
| Second blind holdout | **93.75%** | 84.375% |

On the final blind run, base Qwen also reached **100% schema validity** with **0% provider failures**.

Another useful result: the fine-tuned adapter did **not** win.

It was trained for tool routing, not incident diagnosis. The blind benchmark showed that base Qwen generalized better for this task, so the production recommendation is the base model.

That is the part I like about this project: the answer was not “fine-tune more.” It was to fix context design, evaluation leakage, taxonomy boundaries, and safety architecture first.

The LLM is still advisory-only. It cannot approve a patch, decide retry safety, mutate workflow JSON, or execute a retry. Those stay behind deterministic controls and human approval.

Repo: https://github.com/zubairz4far/ai-automation-doctor

#AI #MachineLearning #LLM #MLOps #AIEngineering #n8n #Automation #Qwen #FastAPI #Evaluation
