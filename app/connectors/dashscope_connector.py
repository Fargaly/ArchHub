"""Alibaba DashScope connector — Qwen / Qwen-VL / Wan API client.

Tier 0 of the founder's 2026-05-24 ComfyUI / Alibaba research. Cheap
LLM + vision + image-to-video — pricing per the assimilation prototype:

  Qwen3 Max          $0.36 / $1.43 per M token
  Qwen3 Plus / Turbo $0.33 / $1.95 per M token
  Qwen3-VL Plus      $0.14 / $0.41 per M token  ← vision
  Qwen-Image edit    ~$0.02 / image
  Wan 2.5 i2v fast   $0.035 / clip   ← cheapest video on market
  Wan 2.6 i2v        $0.07 / clip
  Wan 2.7 i2v        $0.10 / clip

Configuration:
  DASHSCOPE_API_KEY (env or settings) — Alibaba sk-... key
  DASHSCOPE_BASE    optional, default https://dashscope-intl.aliyuncs.com

Operations (Tier 0 — text + vision text; Tier 1 will add image-gen +
video-gen async polling):
  dashscope.probe          — verify key + endpoint reachable
  dashscope.complete       — text generation (Qwen3 series)
  dashscope.vision_describe — Qwen3-VL Plus on an image URL or base64
  dashscope.image_edit     — Qwen-Image edit (image-to-image)
  dashscope.wan_i2v_async  — kick a Wan i2v job; returns task_id
  dashscope.wan_poll       — poll a Wan task_id for completion

Honest-status contract: every method returns OpResult. Network /
auth / quota failures emit ok=False; downstream sees upstream_error.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from .base import Connector, ConnectorOp, OpResult, ParamSpec, register


def _base() -> str:
    return (os.environ.get("DASHSCOPE_BASE")
            or "https://dashscope-intl.aliyuncs.com").rstrip("/")


def _key() -> str:
    return os.environ.get("DASHSCOPE_API_KEY", "")


def _http(method: str, path: str, body: Optional[dict] = None,
           timeout: int = 60, extra_headers: Optional[dict] = None
           ) -> tuple[int, Any]:
    key = _key()
    if not key:
        return 0, "DASHSCOPE_API_KEY not set"
    headers = {"Authorization": f"Bearer {key}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)
    url = f"{_base()}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                   headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw.decode("utf-8"))
            except Exception:
                return r.status, raw
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, str(e)
    except Exception as e:
        return 0, str(e)


# ── ops ─────────────────────────────────────────────────────────────


def _probe() -> OpResult:
    if not _key():
        return OpResult.fail("DASHSCOPE_API_KEY not set",
                              "dashscope.probe")
    # Cheapest verify — one short Qwen turn.
    body = {
        "model": "qwen-turbo",
        "input": {"messages": [
            {"role": "user", "content": "ping"}]},
        "parameters": {"max_tokens": 4},
    }
    code, resp = _http("POST",
                        "/api/v1/services/aigc/text-generation/generation",
                        body, timeout=15)
    if code >= 400:
        return OpResult.fail(f"HTTP {code}: {resp}", "dashscope.probe")
    if code == 0:
        return OpResult.fail(f"unreachable: {resp}", "dashscope.probe")
    return OpResult(ok=True, op_id="dashscope.probe",
                     value={"base": _base(), "model": "qwen-turbo",
                            "resp": resp},
                     value_preview=f"dashscope live · {_base()}")


def _complete(*, prompt: str, model: str = "qwen-plus",
                max_tokens: int = 1024, temperature: float = 0.7
                ) -> OpResult:
    body = {
        "model": model,
        "input": {"messages": [
            {"role": "user", "content": prompt}]},
        "parameters": {"max_tokens": int(max_tokens),
                        "temperature": float(temperature),
                        "result_format": "message"},
    }
    code, resp = _http("POST",
                        "/api/v1/services/aigc/text-generation/generation",
                        body, timeout=60)
    if code >= 400 or code == 0:
        return OpResult.fail(f"HTTP {code}: {resp}", "dashscope.complete")
    try:
        msg = resp["output"]["choices"][0]["message"]["content"]
    except Exception:
        msg = str(resp)
    return OpResult(ok=True, op_id="dashscope.complete",
                     value={"text": msg, "raw": resp},
                     value_preview=msg[:80])


def _vision_describe(*, image_url: str, prompt: str = "Describe this image.",
                       model: str = "qwen-vl-plus") -> OpResult:
    body = {
        "model": model,
        "input": {"messages": [{
            "role": "user",
            "content": [
                {"image": image_url},
                {"text": prompt},
            ],
        }]},
    }
    code, resp = _http("POST",
                        "/api/v1/services/aigc/multimodal-generation/generation",
                        body, timeout=60)
    if code >= 400 or code == 0:
        return OpResult.fail(f"HTTP {code}: {resp}",
                              "dashscope.vision_describe")
    try:
        # Multimodal returns a list of content blocks
        out_content = resp["output"]["choices"][0]["message"]["content"]
        if isinstance(out_content, list):
            text = "".join(b.get("text", "") for b in out_content
                            if isinstance(b, dict))
        else:
            text = str(out_content)
    except Exception:
        text = str(resp)
    return OpResult(ok=True, op_id="dashscope.vision_describe",
                     value={"text": text, "raw": resp},
                     value_preview=text[:80])


def _image_edit(*, prompt: str, image_url: str,
                  model: str = "qwen-image-edit",
                  n: int = 1) -> OpResult:
    body = {
        "model": model,
        "input": {"prompt": prompt, "ref_img": image_url},
        "parameters": {"n": int(n)},
    }
    code, resp = _http("POST",
                        "/api/v1/services/aigc/image2image/image-synthesis",
                        body, timeout=120,
                        extra_headers={"X-DashScope-Async": "enable"})
    if code >= 400 or code == 0:
        return OpResult.fail(f"HTTP {code}: {resp}", "dashscope.image_edit")
    # Async — returns a task_id; caller polls dashscope.task_poll.
    try:
        task_id = resp["output"]["task_id"]
    except Exception:
        task_id = None
    return OpResult(ok=True, op_id="dashscope.image_edit",
                     value={"task_id": task_id, "raw": resp},
                     value_preview=f"task queued · {task_id}")


def _wan_i2v_async(*, image_url: str, prompt: str = "",
                     model: str = "wan2.5-i2v-plus",
                     duration_s: int = 5) -> OpResult:
    """Wan image-to-video. Async — returns task_id."""
    body = {
        "model": model,
        "input": {"image_url": image_url, "prompt": prompt},
        "parameters": {"duration": int(duration_s)},
    }
    code, resp = _http("POST",
                        "/api/v1/services/aigc/video-generation/video-synthesis",
                        body, timeout=60,
                        extra_headers={"X-DashScope-Async": "enable"})
    if code >= 400 or code == 0:
        return OpResult.fail(f"HTTP {code}: {resp}",
                              "dashscope.wan_i2v_async")
    try:
        task_id = resp["output"]["task_id"]
    except Exception:
        task_id = None
    return OpResult(ok=True, op_id="dashscope.wan_i2v_async",
                     value={"task_id": task_id, "raw": resp},
                     value_preview=f"i2v task queued · {task_id}")


def _task_poll(*, task_id: str) -> OpResult:
    """Poll any async DashScope task (image-edit / wan i2v)."""
    if not task_id:
        return OpResult.fail("task_id required", "dashscope.task_poll")
    code, resp = _http("GET", f"/api/v1/tasks/{task_id}", timeout=20)
    if code >= 400 or code == 0:
        return OpResult.fail(f"HTTP {code}: {resp}",
                              "dashscope.task_poll")
    try:
        status = resp["output"]["task_status"]
    except Exception:
        status = "UNKNOWN"
    return OpResult(ok=True, op_id="dashscope.task_poll",
                     value={"status": status, "raw": resp},
                     value_preview=f"task {task_id[:8]}… · {status}")


# ── connector class ────────────────────────────────────────────────


class DashscopeConnector(Connector):
    host = "dashscope"
    display_name = "Alibaba DashScope"
    mechanism = "rest"

    def probe(self) -> dict:
        if not _key():
            return {"status": "missing",
                    "note": "DASHSCOPE_API_KEY not set",
                    "detail": {"base": _base()}}
        # Cheap reachability check (no LLM call).
        try:
            req = urllib.request.Request(_base(),
                                          headers={"Authorization": f"Bearer {_key()}"})
            urllib.request.urlopen(req, timeout=5).read()
            return {"status": "live",
                    "note": f"dashscope reachable at {_base()}",
                    "detail": {"base": _base()}}
        except Exception as ex:
            return {"status": "loaded_dead",
                    "note": f"dashscope endpoint unreachable: {ex}",
                    "detail": {"base": _base(), "error": str(ex)}}

    def build_ops(self) -> list:
        return [
            ConnectorOp(op_id="dashscope.probe", host="dashscope",
                         kind="read", label="Probe API",
                         description="Smoke-test with one cheap Qwen-Turbo turn.",
                         inputs=[], output_type="object", fn=_probe),
            ConnectorOp(op_id="dashscope.complete", host="dashscope",
                         kind="read", label="Text completion",
                         description=("Qwen3 text generation (qwen-turbo / "
                                       "qwen-plus / qwen-max)."),
                         inputs=[
                             ParamSpec(id="prompt", label="Prompt",
                                        type="text", required=True),
                             ParamSpec(id="model",  label="Model",
                                        type="choice", default="qwen-plus",
                                        options=["qwen-turbo", "qwen-plus",
                                                 "qwen-max", "qwen3-max"]),
                             ParamSpec(id="max_tokens", label="Max tokens",
                                        type="number", default=1024),
                             ParamSpec(id="temperature", label="Temperature",
                                        type="number", default=0.7),
                         ],
                         output_type="string", fn=_complete),
            ConnectorOp(op_id="dashscope.vision_describe", host="dashscope",
                         kind="read", label="Vision describe",
                         description=("Qwen-VL-Plus on an image URL — returns "
                                       "a text description / classification."),
                         inputs=[
                             ParamSpec(id="image_url", label="Image URL",
                                        type="text", required=True),
                             ParamSpec(id="prompt", label="Prompt",
                                        type="text",
                                        default="Describe this image."),
                             ParamSpec(id="model", label="Model",
                                        type="choice", default="qwen-vl-plus",
                                        options=["qwen-vl-plus",
                                                 "qwen-vl-max"]),
                         ],
                         output_type="string", fn=_vision_describe),
            ConnectorOp(op_id="dashscope.image_edit", host="dashscope",
                         kind="action", label="Image edit (async)",
                         description=("Qwen-Image edit — image-to-image with "
                                       "a prompt. Returns task_id; poll with "
                                       "dashscope.task_poll."),
                         inputs=[
                             ParamSpec(id="prompt", label="Prompt",
                                        type="text", required=True),
                             ParamSpec(id="image_url", label="Source image URL",
                                        type="text", required=True),
                             ParamSpec(id="model", label="Model",
                                        type="text", default="qwen-image-edit"),
                             ParamSpec(id="n", label="Variations",
                                        type="number", default=1),
                         ],
                         output_type="object", fn=_image_edit),
            ConnectorOp(op_id="dashscope.wan_i2v_async", host="dashscope",
                         kind="action", label="Wan image-to-video (async)",
                         description=("Cheapest i2v on the market — Wan 2.5/2.6/2.7. "
                                       "Returns task_id; poll with dashscope.task_poll."),
                         inputs=[
                             ParamSpec(id="image_url", label="Source image URL",
                                        type="text", required=True),
                             ParamSpec(id="prompt", label="Prompt",
                                        type="text"),
                             ParamSpec(id="model", label="Model",
                                        type="choice",
                                        default="wan2.5-i2v-plus",
                                        options=["wan2.5-i2v-plus",
                                                 "wan2.6-i2v-plus",
                                                 "wan2.7-i2v-plus"]),
                             ParamSpec(id="duration_s", label="Duration (s)",
                                        type="number", default=5),
                         ],
                         output_type="object", fn=_wan_i2v_async),
            ConnectorOp(op_id="dashscope.task_poll", host="dashscope",
                         kind="read", label="Poll async task",
                         description=("Poll any DashScope async task (image_edit / "
                                       "wan_i2v) and return its current status + "
                                       "results on completion."),
                         inputs=[ParamSpec(id="task_id", label="Task id",
                                            type="text", required=True)],
                         output_type="object", fn=_task_poll),
        ]


register(DashscopeConnector())
