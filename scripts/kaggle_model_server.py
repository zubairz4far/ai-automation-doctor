from __future__ import annotations

import os
import threading
import time
import uuid
from contextlib import asynccontextmanager, nullcontext
from typing import Any

import torch
from fastapi import FastAPI, HTTPException
from peft import PeftModel
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE_MODEL = os.getenv("BASE_MODEL", "Qwen/Qwen3-1.7B")
ADAPTER_REPO = os.getenv("ADAPTER_REPO", "zubairz4far/qwen3-1.7b-tool-calling")
ADAPTER_ALIAS = os.getenv("ADAPTER_ALIAS", "tool-calling")
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
MAX_NEW_TOKENS = int(os.getenv("MAX_NEW_TOKENS", "320"))

_lock = threading.Lock()
_tokenizer: Any = None
_model: Any = None


class ChatRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    temperature: float | None = None
    max_tokens: int | None = None


def _load() -> None:
    global _tokenizer, _model
    if _model is not None:
        return
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is required. Enable a Kaggle GPU accelerator.")

    _tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)
    base = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.float16,
        device_map={"": 0},
        low_cpu_mem_usage=True,
        trust_remote_code=True,
    )
    base.eval()
    _model = PeftModel.from_pretrained(
        base,
        ADAPTER_REPO,
        adapter_name=ADAPTER_ALIAS,
        is_trainable=False,
    )
    _model.eval()


@asynccontextmanager
async def lifespan(_: FastAPI):
    _load()
    yield


app = FastAPI(
    title="Kaggle local OpenAI-compatible Qwen server",
    lifespan=lifespan,
)


def _render_prompt(messages: list[dict[str, Any]]) -> str:
    kwargs = {
        "tokenize": False,
        "add_generation_prompt": True,
    }
    try:
        return _tokenizer.apply_chat_template(
            messages,
            enable_thinking=False,
            **kwargs,
        )
    except TypeError:
        return _tokenizer.apply_chat_template(messages, **kwargs)


def _generate(model_name: str, messages: list[dict[str, Any]], max_tokens: int | None) -> str:
    prompt = _render_prompt(messages)
    inputs = _tokenizer(prompt, return_tensors="pt").to("cuda")
    input_tokens = int(inputs["input_ids"].shape[-1])
    limit = max(32, min(max_tokens or MAX_NEW_TOKENS, 512))

    if model_name == ADAPTER_ALIAS:
        _model.set_adapter(ADAPTER_ALIAS)
        adapter_context = nullcontext()
    elif model_name in {BASE_MODEL, "base"}:
        adapter_context = _model.disable_adapter()
    else:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown model '{model_name}'. Use '{BASE_MODEL}' or '{ADAPTER_ALIAS}'.",
        )

    with _lock, adapter_context, torch.inference_mode():
        output = _model.generate(
            **inputs,
            max_new_tokens=limit,
            do_sample=False,
            use_cache=True,
            pad_token_id=_tokenizer.eos_token_id,
        )

    generated = output[0][input_tokens:]
    return _tokenizer.decode(generated, skip_special_tokens=True).strip()


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": _model is not None,
        "cuda": torch.cuda.is_available(),
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "base_model": BASE_MODEL,
        "adapter": ADAPTER_REPO,
        "loaded": _model is not None,
    }


@app.get("/v1/models")
def models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {"id": BASE_MODEL, "object": "model"},
            {"id": ADAPTER_ALIAS, "object": "model"},
        ],
    }


@app.post("/v1/chat/completions")
def chat_completions(request: ChatRequest) -> dict[str, Any]:
    started = time.time()
    content = _generate(request.model, request.messages, request.max_tokens)
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
        "object": "chat.completion",
        "created": int(started),
        "model": request.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
