from __future__ import annotations

from functools import lru_cache
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.models.schemas import ExecutionFailure
from app.services.ai_diagnoser import GuardedDiagnosisEngine, OpenAICompatibleInsightProvider
from app.services.patcher import PatchPlanner

router = APIRouter()


class DemoAnalyzeRequest(BaseModel):
    error_message: str = Field(min_length=3, max_length=1200)
    node_type: str = Field(default="n8n-nodes-base.httpRequest", max_length=200)
    failed_node: str = Field(default="HTTP Request", min_length=1, max_length=200)
    error_stack: str | None = Field(default=None, max_length=1600)
    error_code: str | None = Field(default=None, max_length=120)
    status_code: int | None = Field(default=None, ge=100, le=599)


@lru_cache
def _demo_diagnoser() -> GuardedDiagnosisEngine:
    settings = get_settings()
    provider = None
    if settings.ai_diagnosis_enabled and settings.ai_api_base_url and settings.ai_model:
        provider = OpenAICompatibleInsightProvider(
            base_url=settings.ai_api_base_url,
            api_key=settings.ai_api_key,
            model=settings.ai_model,
            timeout_seconds=settings.ai_timeout_seconds,
        )
    return GuardedDiagnosisEngine(
        provider=provider,
        enabled=settings.ai_diagnosis_enabled,
        confidence_threshold=settings.ai_baseline_confidence_threshold,
    )


@router.post("/v1/demo/analyze")
def demo_analyze(request: DemoAnalyzeRequest) -> dict[str, object]:
    """Analyze a failure without durable state or side-effect capability."""

    failure = ExecutionFailure(
        execution_id=f"demo-{uuid4().hex[:12]}",
        workflow_id="demo-workflow",
        workflow_name="Interactive demo",
        failed_node=request.failed_node,
        node_type=request.node_type,
        error_message=request.error_message,
        error_stack=request.error_stack,
        error_code=request.error_code,
        status_code=request.status_code,
    )
    diagnosis = _demo_diagnoser().diagnose(failure)
    patch = PatchPlanner().propose(failure, diagnosis)
    settings = get_settings()

    ai_configured = bool(
        settings.ai_diagnosis_enabled and settings.ai_api_base_url and settings.ai_model
    )
    return {
        "mode": "read_only_demo",
        "diagnosis": diagnosis.model_dump(mode="json"),
        "patch_preview": patch.model_dump(mode="json") if patch else None,
        "ai": {
            "configured": ai_configured,
            "advisory_attached": diagnosis.ai_insight is not None,
            "recommended_model": "Qwen/Qwen3-1.7B",
        },
        "safety": {
            "durable_state_write": False,
            "workflow_mutation": False,
            "execution_retry": False,
            "approval": False,
            "patch_preview_only": True,
        },
    }


@router.get("/demo", response_class=HTMLResponse)
def demo_page() -> HTMLResponse:
    return HTMLResponse(_DEMO_HTML)


_DEMO_HTML = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>AI Automation Doctor — Interactive Demo</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #090b10;
      --panel: #11151d;
      --line: #293141;
      --text: #f4f6fb;
      --muted: #98a2b3;
      --good: #86efac;
      --accent: #8ab4ff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: radial-gradient(circle at 20% 0, #172033 0, #090b10 38%);
      font: 15px/1.5 Inter, ui-sans-serif, system-ui, -apple-system, sans-serif;
      color: var(--text);
    }
    .shell { max-width: 1180px; margin: auto; padding: 38px 22px 70px; }
    .eyebrow {
      font-size: 12px;
      letter-spacing: .14em;
      text-transform: uppercase;
      color: var(--accent);
      font-weight: 700;
    }
    .hero {
      display: grid;
      grid-template-columns: 1.35fr .65fr;
      gap: 24px;
      align-items: end;
      margin: 12px 0 26px;
    }
    .hero h1 {
      font-size: clamp(36px, 6vw, 72px);
      line-height: .98;
      margin: 0;
      letter-spacing: -.055em;
    }
    .hero p { margin: 0; color: var(--muted); font-size: 17px; }
    .badges, .samples { display: flex; gap: 8px; flex-wrap: wrap; }
    .badges { margin-top: 18px; }
    .badge {
      border: 1px solid var(--line);
      background: #0d1118;
      border-radius: 999px;
      padding: 7px 10px;
      color: #cdd5e3;
      font-size: 12px;
    }
    .metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 28px 0; }
    .metric, .card {
      border: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(23, 28, 38, .94), rgba(14, 18, 25, .94));
      border-radius: 18px;
    }
    .metric { padding: 18px; }
    .metric strong { display: block; font-size: 27px; letter-spacing: -.04em; }
    .metric span, .note, .footer { color: var(--muted); font-size: 12px; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
    .card { padding: 20px; }
    .card h2 { margin: 0 0 14px; font-size: 18px; }
    .label {
      display: block;
      margin: 13px 0 6px;
      color: #c8d0dc;
      font-size: 12px;
      font-weight: 650;
    }
    .samples { margin-bottom: 12px; }
    .samples button, button.primary {
      border: 1px solid var(--line);
      background: #151b25;
      color: var(--text);
      border-radius: 10px;
      padding: 9px 12px;
      cursor: pointer;
    }
    .samples button:hover { border-color: #53627a; }
    textarea, input {
      width: 100%;
      border: 1px solid var(--line);
      background: #0b0f16;
      color: var(--text);
      border-radius: 11px;
      padding: 11px 12px;
      outline: none;
    }
    textarea { min-height: 144px; resize: vertical; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    button.primary {
      width: 100%;
      margin-top: 14px;
      background: #e9eef8;
      color: #0b0e13;
      font-weight: 800;
      border-color: #e9eef8;
      padding: 12px;
    }
    .note { margin-top: 10px; }
    .result { min-height: 420px; }
    .empty {
      height: 360px;
      display: grid;
      place-items: center;
      text-align: center;
      color: var(--muted);
      border: 1px dashed var(--line);
      border-radius: 14px;
    }
    .result-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .pill {
      border-radius: 999px;
      padding: 5px 9px;
      font-size: 11px;
      font-weight: 800;
      background: #112219;
      color: var(--good);
      border: 1px solid #245331;
    }
    .kv {
      display: grid;
      grid-template-columns: 150px 1fr;
      gap: 8px 14px;
      padding: 10px 0;
      border-bottom: 1px solid #222936;
    }
    .kv b { color: #aab4c3; font-size: 12px; }
    .confidence { height: 8px; background: #252c38; border-radius: 999px; overflow: hidden; margin-top: 6px; }
    .confidence i { display: block; height: 100%; background: #a9c7ff; width: 0; }
    .evidence { margin: 8px 0 0; padding-left: 18px; color: #d8deea; }
    .advisory { margin-top: 15px; border: 1px solid #283b59; background: #10192a; border-radius: 13px; padding: 13px; }
    .safe { margin-top: 15px; border: 1px solid #294735; background: #101c16; border-radius: 13px; padding: 13px; }
    .ops {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
      background: #090d13;
      border-radius: 10px;
      padding: 10px;
      overflow: auto;
      color: #c8d5e7;
    }
    .footer { margin-top: 24px; }
    .spinner { display: none; margin-right: 8px; }
    .loading .spinner { display: inline; }
    .loading { opacity: .8; }
    @media (max-width: 800px) {
      .hero, .grid { grid-template-columns: 1fr; }
      .metrics { grid-template-columns: 1fr 1fr; }
      .row { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
<main class="shell">
  <div class="eyebrow">AI Automation Doctor · v1.3 demo</div>
  <section class="hero">
    <div>
      <h1>Diagnose failure.<br>Keep control deterministic.</h1>
      <div class="badges">
        <span class="badge">read-only demo</span>
        <span class="badge">no workflow writes</span>
        <span class="badge">no retries</span>
        <span class="badge">human-gated production path</span>
      </div>
    </div>
    <p>A production-shaped n8n reliability system where the LLM can explain difficult incidents, but cannot mutate workflows, approve patches, or decide retry safety.</p>
  </section>
  <section class="metrics">
    <div class="metric"><strong>93.75%</strong><span>second-blind base Qwen accuracy</span></div>
    <div class="metric"><strong>100%</strong><span>raw schema validity</span></div>
    <div class="metric"><strong>0%</strong><span>provider failures in blind run</span></div>
    <div class="metric"><strong>60+</strong><span>automated safety and API tests</span></div>
  </section>
  <section class="grid">
    <div class="card">
      <h2>Failure input</h2>
      <div class="samples">
        <button data-sample="auth">Authentication</button>
        <button data-sample="rate">Rate limit</button>
        <button data-sample="timeout">Timeout</button>
        <button data-sample="mapping">Data mapping</button>
        <button data-sample="opaque">Unknown</button>
      </div>
      <label class="label">Error message</label>
      <textarea id="message">Upstream gateway did not answer before the operation response window expired.</textarea>
      <div class="row">
        <div><label class="label">Node type</label><input id="nodeType" value="n8n-nodes-base.httpRequest"></div>
        <div><label class="label">HTTP status</label><input id="statusCode" inputmode="numeric" placeholder="optional"></div>
      </div>
      <div class="row">
        <div><label class="label">Error code</label><input id="errorCode" placeholder="optional"></div>
        <div><label class="label">Node name</label><input id="nodeName" value="HTTP Request"></div>
      </div>
      <button class="primary" id="analyze"><span class="spinner">◌</span>Analyze safely</button>
      <div class="note">This endpoint does not persist the incident and cannot call approval, mutation, or retry operations.</div>
    </div>
    <div class="card result" id="result">
      <div class="empty"><div><strong>No analysis yet</strong><br>Choose a sample or enter an n8n failure, then run the read-only analyzer.</div></div>
    </div>
  </section>
  <div class="footer">Measured benchmark values are from the committed 32-case second blind holdout. The benchmark is synthetic/hand-labeled and is not a claim of universal production accuracy.</div>
</main>
<script>
const messageEl = document.getElementById('message');
const nodeTypeEl = document.getElementById('nodeType');
const statusCodeEl = document.getElementById('statusCode');
const errorCodeEl = document.getElementById('errorCode');
const nodeNameEl = document.getElementById('nodeName');
const analyzeEl = document.getElementById('analyze');
const resultEl = document.getElementById('result');

const samples = {
  auth: {
    message: 'Remote service rejected the signed request for the active principal.',
    code: 'SIGNATURE_REJECTED',
    status: '401'
  },
  rate: {
    message: 'Partner capacity window is exhausted for this tenant; retry after the usage window resets.',
    code: 'CAPACITY_WINDOW',
    status: '429'
  },
  timeout: {
    message: 'Upstream gateway did not answer before the operation response window expired.',
    code: 'DEADLINE_EXCEEDED',
    status: '504'
  },
  mapping: {
    message: 'Expression resolved to a string but the valid node configuration expects an object record for this item.',
    code: 'ITEM_SHAPE_MISMATCH',
    status: ''
  },
  opaque: {
    message: 'Vendor returned internal policy state VND-734 with no documented transport or request-contract meaning.',
    code: 'VND-734',
    status: ''
  }
};

document.querySelectorAll('[data-sample]').forEach((button) => {
  button.addEventListener('click', () => {
    const sample = samples[button.dataset.sample];
    messageEl.value = sample.message;
    errorCodeEl.value = sample.code;
    statusCodeEl.value = sample.status;
  });
});

const escapeHtml = (value) => String(value ?? '').replace(
  /[&<>"']/g,
  (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  })[char]
);

function render(data) {
  const diagnosis = data.diagnosis;
  const advisory = diagnosis.ai_insight;
  const patch = data.patch_preview;
  const confidence = Math.round(diagnosis.confidence * 100);
  const evidence = (diagnosis.evidence || [])
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join('');

  const advisoryHtml = advisory
    ? `<div class="advisory">
         <div class="result-head"><b>AI advisory</b><span class="pill">advisory only</span></div>
         <div class="kv"><b>Class</b><span>${escapeHtml(advisory.failure_class)}</span></div>
         <div class="kv"><b>Confidence</b><span>${Math.round(advisory.confidence * 100)}%</span></div>
         <div class="kv"><b>Root cause</b><span>${escapeHtml(advisory.root_cause)}</span></div>
         <div class="kv"><b>Recommended</b><span>${escapeHtml(advisory.recommended_action)}</span></div>
       </div>`
    : `<div class="advisory">
         <b>AI advisory</b>
         <p>${data.ai.configured
           ? 'The live provider did not attach an advisory for this case.'
           : 'Live AI is not configured in this deployment. The production benchmark recommendation is Qwen/Qwen3-1.7B.'}</p>
       </div>`;

  const operations = patch
    ? (patch.operations || [])
        .map((operation) => `${escapeHtml(operation.op)} ${escapeHtml(operation.path)} = ${escapeHtml(JSON.stringify(operation.value))}`)
        .join('\n')
    : 'No retry patch is proposed for this deterministic class.';

  resultEl.innerHTML = `
    <div class="result-head"><h2>Diagnosis</h2><span class="pill">read-only</span></div>
    <div class="kv"><b>Failure class</b><span>${escapeHtml(diagnosis.failure_class)}</span></div>
    <div class="kv"><b>Confidence</b><span>${confidence}%<div class="confidence"><i style="width:${confidence}%"></i></div></span></div>
    <div class="kv"><b>Retry safe</b><span>${diagnosis.retry_safe ? 'Yes — deterministic decision' : 'No — deterministic decision'}</span></div>
    <div class="kv"><b>Root cause</b><span>${escapeHtml(diagnosis.root_cause)}</span></div>
    <div class="kv"><b>Evidence</b><ul class="evidence">${evidence}</ul></div>
    <div class="kv"><b>Recommended</b><span>${escapeHtml(diagnosis.recommended_action)}</span></div>
    ${advisoryHtml}
    <div class="safe">
      <div class="result-head"><b>Patch preview</b><span class="pill">never applied here</span></div>
      <pre class="ops">${operations}</pre>
      <div class="note">workflow mutation: disabled · execution retry: disabled · approval: disabled · durable write: disabled</div>
    </div>`;
}

analyzeEl.addEventListener('click', async () => {
  analyzeEl.classList.add('loading');
  analyzeEl.disabled = true;
  resultEl.innerHTML = '<div class="empty"><div>Running deterministic diagnosis and optional advisory…</div></div>';

  try {
    const body = {
      error_message: messageEl.value,
      node_type: nodeTypeEl.value,
      failed_node: nodeNameEl.value,
      error_code: errorCodeEl.value || null,
      status_code: statusCodeEl.value ? Number(statusCodeEl.value) : null
    };
    const response = await fetch('/v1/demo/analyze', {
      method: 'POST',
      headers: {'content-type': 'application/json'},
      body: JSON.stringify(body)
    });
    if (!response.ok) {
      throw new Error((await response.text()) || `HTTP ${response.status}`);
    }
    render(await response.json());
  } catch (error) {
    resultEl.innerHTML = `<div class="empty"><div><strong>Analysis failed</strong><br>${escapeHtml(error.message)}</div></div>`;
  } finally {
    analyzeEl.classList.remove('loading');
    analyzeEl.disabled = false;
  }
});
</script>
</body>
</html>'''
