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

Operations:
  dashscope.probe          — verify key + endpoint reachable
  dashscope.complete       — text generation (Qwen3 series)
  dashscope.vision_describe — Qwen3-VL Plus on an image URL or base64
  dashscope.text2image     — Wan / Qwen-Image text-to-image; returns task_id
  dashscope.image_edit     — Qwen multi-image edit (base + up to 2 refs)
  dashscope.wan_i2v_async  — kick a Wan i2v job; returns task_id
  dashscope.task_poll      — poll any async task_id for completion + result URLs

Honest-status contract: every method returns OpResult. Network /
auth / quota failures emit ok=False; downstream sees upstream_error.
"""
from __future__ import annotations

import base64
import json
import mimetypes
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


def _to_image_ref(s: str) -> str:
    """Normalise an image argument the API will accept. Local file paths are
    read + base64-encoded into a data URI; http(s) URLs and existing data URIs
    pass through untouched."""
    if not s:
        return s
    if s.startswith(("http://", "https://", "data:")):
        return s
    if os.path.exists(s):
        mime = mimetypes.guess_type(s)[0] or "image/png"
        with open(s, "rb") as f:
            b = base64.b64encode(f.read()).decode("ascii")
        return f"data:{mime};base64,{b}"
    return s  # let the API reject anything that isn't a real ref


def _image_edit(*, prompt: str, image: str, reference_image: str = "",
                  reference_image_2: str = "",
                  model: str = "qwen-image-edit-plus",
                  size: str = "", negative_prompt: str = "",
                  n: int = 1, download_dir: str = "") -> OpResult:
    """Reference-guided image edit. Pass a base `image` plus up to two
    reference images (paths, URLs, or data URIs) and an instruction. Uses the
    Qwen multimodal edit endpoint (synchronous, 1-3 images in). When
    download_dir is set, result image(s) are saved there and the paths
    returned — the result URLs expire in 24h, so download is immediate."""
    imgs = [x for x in (image, reference_image, reference_image_2) if x]
    if not imgs:
        return OpResult.fail("at least one image required",
                              "dashscope.image_edit")
    if len(imgs) > 3:
        return OpResult.fail("max 3 images (1 base + 2 references)",
                              "dashscope.image_edit")
    content: list = [{"image": _to_image_ref(x)} for x in imgs]
    content.append({"text": prompt})
    params: dict = {"n": int(n), "watermark": False}
    if size:
        params["size"] = size
    if negative_prompt:
        params["negative_prompt"] = negative_prompt
    body = {
        "model": model,
        "input": {"messages": [{"role": "user", "content": content}]},
        "parameters": params,
    }
    code, resp = _http("POST",
                        "/api/v1/services/aigc/multimodal-generation/generation",
                        body, timeout=180)
    if code >= 400 or code == 0:
        return OpResult.fail(f"HTTP {code}: {resp}", "dashscope.image_edit")
    urls: list = []
    try:
        for blk in resp["output"]["choices"][0]["message"]["content"]:
            if isinstance(blk, dict) and blk.get("image"):
                urls.append(blk["image"])
    except Exception:
        pass
    if not urls:
        return OpResult.fail(f"no image in response: {resp}",
                              "dashscope.image_edit")
    saved: list = []
    if download_dir:
        rid = str(resp.get("request_id", "edit"))[:8]
        os.makedirs(download_dir, exist_ok=True)
        for i, u in enumerate(urls):
            dst = os.path.join(download_dir, f"edit_{rid}_{i}.png")
            try:
                urllib.request.urlretrieve(u, dst)
                saved.append(dst)
            except Exception as ex:
                saved.append(f"DLfail:{ex}")
    return OpResult(ok=True, op_id="dashscope.image_edit",
                     value={"images": urls, "saved": saved, "raw": resp},
                     value_preview=(f"edited · {len(urls)} image(s)"
                                     + (f" · saved {len(saved)}" if saved
                                        else "")))


def _text2image(*, prompt: str, negative_prompt: str = "",
                  model: str = "wan2.2-t2i-flash",
                  size: str = "1024*1024", n: int = 1) -> OpResult:
    """Text-to-image (Wan / Qwen-Image). Async — returns task_id; poll
    with dashscope.task_poll, whose raw payload carries results[].url on
    completion. The text-to-image endpoint always runs async, so the
    X-DashScope-Async header is mandatory (the API 400s without it)."""
    body = {
        "model": model,
        "input": {"prompt": prompt,
                   "negative_prompt": negative_prompt or ""},
        "parameters": {"size": size, "n": int(n)},
    }
    code, resp = _http("POST",
                        "/api/v1/services/aigc/text2image/image-synthesis",
                        body, timeout=60,
                        extra_headers={"X-DashScope-Async": "enable"})
    if code >= 400 or code == 0:
        return OpResult.fail(f"HTTP {code}: {resp}", "dashscope.text2image")
    try:
        task_id = resp["output"]["task_id"]
    except Exception:
        task_id = None
    return OpResult(ok=True, op_id="dashscope.text2image",
                     value={"task_id": task_id, "model": model, "raw": resp},
                     value_preview=f"t2i task queued · {task_id}")


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
            ConnectorOp(op_id="dashscope.text2image", host="dashscope",
                         kind="action", label="Text to image (async)",
                         description=("Wan / Qwen-Image text-to-image. Turns a "
                                       "text prompt into an image. Returns "
                                       "task_id; poll with dashscope.task_poll "
                                       "for the result URL."),
                         inputs=[
                             ParamSpec(id="prompt", label="Prompt",
                                        type="text", required=True),
                             ParamSpec(id="negative_prompt",
                                        label="Negative prompt", type="text"),
                             ParamSpec(id="model", label="Model",
                                        type="choice", default="wan2.2-t2i-flash",
                                        options=["wan2.2-t2i-flash",
                                                 "wan2.2-t2i-plus",
                                                 "wanx2.1-t2i-turbo",
                                                 "wanx2.1-t2i-plus",
                                                 "qwen-image"]),
                             ParamSpec(id="size", label="Size (w*h)",
                                        type="text", default="1024*1024"),
                             ParamSpec(id="n", label="Variations",
                                        type="number", default=1),
                         ],
                         output_type="object", fn=_text2image),
            ConnectorOp(op_id="dashscope.image_edit", host="dashscope",
                         kind="action", label="Image edit (reference-guided)",
                         description=("Qwen multi-image edit. Base image + up "
                                       "to 2 reference images (paths, URLs, or "
                                       "data URIs) + an instruction. Synchronous; "
                                       "saves result to download_dir."),
                         inputs=[
                             ParamSpec(id="prompt", label="Instruction",
                                        type="text", required=True),
                             ParamSpec(id="image", label="Base image (path/URL)",
                                        type="text", required=True),
                             ParamSpec(id="reference_image",
                                        label="Reference image 1", type="text"),
                             ParamSpec(id="reference_image_2",
                                        label="Reference image 2", type="text"),
                             ParamSpec(id="model", label="Model",
                                        type="choice",
                                        default="qwen-image-edit-plus",
                                        options=["qwen-image-edit-plus",
                                                 "qwen-image-edit-max",
                                                 "qwen-image-2.0-pro",
                                                 "qwen-image-edit"]),
                             ParamSpec(id="size", label="Size (w*h, optional)",
                                        type="text"),
                             ParamSpec(id="negative_prompt",
                                        label="Negative prompt", type="text"),
                             ParamSpec(id="n", label="Variations",
                                        type="number", default=1),
                             ParamSpec(id="download_dir", label="Save to folder",
                                        type="text"),
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
