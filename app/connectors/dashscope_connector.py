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
  dashscope.balance        — live account balance via Alibaba BSS
                             QueryAccountBalance (RAM AccessKey, op:// resolved)
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
import datetime as _dt
import hashlib
import hmac
import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Optional

from .base import Connector, ConnectorOp, OpResult, ParamSpec, register


def _base() -> str:
    return (os.environ.get("DASHSCOPE_BASE")
            or "https://dashscope-intl.aliyuncs.com").rstrip("/")


def _key() -> str:
    return os.environ.get("DASHSCOPE_API_KEY", "")


# ── secret resolution (op://) — reuse the ONE canonical resolver ─────
#
# AccessKey credentials for the billing call are op:// references, never
# inlined. We resolve through personal_brain.secret_resolver (op CLI ->
# Windows Credential Manager / keyring -> OP_<VAULT>_<ITEM>_<FIELD> env) —
# the SAME resolver archhub_mcp_server uses for DASHSCOPE_API_KEY. A
# non-op:// value (or a bare env var) passes through unchanged.

def _resolve_secret(ref: str) -> Optional[str]:
    """Resolve an op:// reference to its value via the repo's canonical
    resolver, with a self-contained fallback if personal_brain isn't on the
    path. Returns None when an op:// ref cannot be resolved by any backend.
    Never logs or echoes the value."""
    if not ref:
        return None
    try:
        import sys
        here = os.path.dirname(os.path.abspath(__file__))
        src = os.path.abspath(
            os.path.join(here, os.pardir, os.pardir,
                         "personal-brain-mcp", "src"))
        if os.path.isdir(src) and src not in sys.path:
            sys.path.append(src)
        from personal_brain.secret_resolver import resolve_secret
        return resolve_secret(ref)
    except Exception:
        pass
    # Fallback equivalent of secret_resolver (keeps the connector usable
    # standalone, e.g. in app/ without the brain checkout).
    if not ref.startswith("op://"):
        return ref
    parts = ref[len("op://"):].split("/")
    if len(parts) < 3 or not all(parts[:3]):
        return None
    vault, item, field = parts[0], parts[1], parts[2]
    try:
        import shutil
        import subprocess
        if shutil.which("op"):
            p = subprocess.run(["op", "read", ref], capture_output=True,
                               text=True, timeout=5.0)
            if p.returncode == 0 and (p.stdout or "").strip():
                return p.stdout.strip()
    except Exception:
        pass
    try:
        import keyring
        v = keyring.get_password(f"{vault}/{item}", field)
        if v and v.strip():
            return v.strip()
    except Exception:
        pass

    def _n(s: str) -> str:
        return s.upper().replace("/", "_").replace("-", "_")

    env = os.environ.get(f"OP_{_n(vault)}_{_n(item)}_{_n(field)}")
    return env or None


# Canonical op:// references for the Alibaba RAM AccessKey pair used by the
# billing (BSS OpenAPI) call. DASHSCOPE_AK_* env vars override for dev/CI.
_AK_ID_REF = "op://archhub/aliyun/access_key_id"
_AK_SECRET_REF = "op://archhub/aliyun/access_key_secret"


def _access_key() -> tuple[Optional[str], Optional[str]]:
    """Resolve the (AccessKey ID, AccessKey secret) pair the BSS billing
    API requires. Order: explicit DASHSCOPE_AK_ID / DASHSCOPE_AK_SECRET env
    (dev/CI escape hatch) -> op:// references via the canonical resolver."""
    ak_id = (os.environ.get("DASHSCOPE_AK_ID")
             or _resolve_secret(_AK_ID_REF))
    ak_secret = (os.environ.get("DASHSCOPE_AK_SECRET")
                 or _resolve_secret(_AK_SECRET_REF))
    return ak_id, ak_secret


# BSS (billing) endpoint. The international Model Studio key lives in the
# ap-southeast-1 (Singapore) account, whose BSS region endpoint is
# business.ap-southeast-1.aliyuncs.com; the China-site endpoint is
# business.aliyuncs.com. DASHSCOPE_BILLING_BASE overrides (also lets the
# test point at a stub). Selection follows DASHSCOPE_BASE: an -intl base
# implies the international BSS host.
def _billing_base() -> str:
    override = os.environ.get("DASHSCOPE_BILLING_BASE")
    if override:
        return override.rstrip("/")
    if "-intl" in _base() or "intl" in _base():
        return "https://business.ap-southeast-1.aliyuncs.com"
    return "https://business.aliyuncs.com"


def _rpc_sign(params: dict, ak_secret: str, method: str = "POST") -> str:
    """Compute the Alibaba Cloud RPC-style signature (HMAC-SHA1) over the
    request parameters. This is the documented BSS/RPC scheme: percent-encode
    + sort params, build the string-to-sign, HMAC-SHA1 with `<secret>&`, then
    base64. Pure + deterministic so it is unit-testable without a network."""
    def _pe(s: str) -> str:
        # RFC3986 percent-encoding per the Alibaba signature spec.
        return (urllib.parse.quote(str(s), safe="~")
                .replace("+", "%20").replace("*", "%2A").replace("%7E", "~"))

    items = sorted((k, v) for k, v in params.items())
    canon = "&".join(f"{_pe(k)}={_pe(v)}" for k, v in items)
    string_to_sign = f"{method}&{_pe('/')}&{_pe(canon)}"
    digest = hmac.new((ak_secret + "&").encode("utf-8"),
                      string_to_sign.encode("utf-8"),
                      hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


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


def _balance() -> OpResult:
    """Capture the real DashScope/Model-Studio account balance.

    DashScope's own ``sk-`` API exposes NO billing/usage endpoint — spend
    lives in Alibaba Cloud's BSS (Billing) OpenAPI ``QueryAccountBalance``
    (RPC, version 2017-12-14), which authenticates with a RAM AccessKey
    pair (ID + secret) and HMAC-SHA1 request signing — a DIFFERENT credential
    than the model-call key. This op makes that real signed call when the
    AccessKey pair resolves (op:// -> resolver), and returns the live
    ``AvailableAmount`` + ``Currency`` + credit figures.

    Honest-status contract: when the AccessKey pair is NOT configured, this
    returns ``ok=False`` naming the exact op:// references to set — it NEVER
    fabricates a balance and NEVER raises. The model key alone cannot read
    billing, so a present DASHSCOPE_API_KEY does not make this succeed."""
    ak_id, ak_secret = _access_key()
    if not ak_id or not ak_secret:
        missing = []
        if not ak_id:
            missing.append(_AK_ID_REF)
        if not ak_secret:
            missing.append(_AK_SECRET_REF)
        return OpResult(
            ok=False, op_id="dashscope.balance",
            error=("Alibaba AccessKey not configured — DashScope billing "
                   "(BSS QueryAccountBalance) needs a RAM AccessKey pair, "
                   "not the model sk- key. Set " + " and ".join(missing)
                   + " (or DASHSCOPE_AK_ID / DASHSCOPE_AK_SECRET) and "
                   "re-run. The balance is genuinely unreadable without it."),
            value={"available": None, "currency": None,
                   "billing_base": _billing_base(),
                   "needs": missing, "configured": False},
            value_preview="balance unavailable · AccessKey not set")

    # Build the canonical RPC request, sign it, POST it.
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    params: dict = {
        "Action": "QueryAccountBalance",
        "Version": "2017-12-14",
        "Format": "JSON",
        "AccessKeyId": ak_id,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureVersion": "1.0",
        "SignatureNonce": uuid.uuid4().hex,
        "Timestamp": now,
    }
    params["Signature"] = _rpc_sign(params, ak_secret, "POST")
    body = urllib.parse.urlencode(params).encode("utf-8")
    url = _billing_base() + "/"
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            code, resp = r.status, json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            code, resp = e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            code, resp = e.code, str(e)
    except Exception as e:
        return OpResult(ok=False, op_id="dashscope.balance",
                        error=f"BSS billing endpoint unreachable: {e}",
                        value={"available": None, "currency": None,
                               "billing_base": _billing_base(),
                               "configured": True},
                        value_preview="balance probe failed · unreachable")

    if code >= 400 or not isinstance(resp, dict):
        return OpResult(ok=False, op_id="dashscope.balance",
                        error=f"HTTP {code}: {resp}",
                        value={"available": None, "currency": None,
                               "billing_base": _billing_base(),
                               "raw": resp, "configured": True},
                        value_preview=f"balance probe failed · HTTP {code}")
    # BSS wraps a Code/Success envelope; a non-Success body is an honest fail.
    if resp.get("Success") is False or (resp.get("Code")
                                        not in (None, "Success", "200")):
        return OpResult(ok=False, op_id="dashscope.balance",
                        error=(f"BSS QueryAccountBalance rejected: "
                               f"{resp.get('Code')} {resp.get('Message')}"),
                        value={"available": None, "currency": None,
                               "billing_base": _billing_base(),
                               "raw": resp, "configured": True},
                        value_preview="balance probe failed · "
                                      + str(resp.get("Code")))
    data = resp.get("Data") or {}
    available = data.get("AvailableAmount")
    currency = data.get("Currency")
    return OpResult(
        ok=True, op_id="dashscope.balance",
        value={"available": available, "currency": currency,
               "available_cash": data.get("AvailableCashAmount"),
               "credit": data.get("CreditAmount"),
               "mybank_credit": data.get("MybankCreditAmount"),
               "billing_base": _billing_base(),
               "request_id": resp.get("RequestId"),
               "configured": True, "raw": resp},
        value_preview=f"balance {available} {currency}".strip())


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
            ConnectorOp(op_id="dashscope.balance", host="dashscope",
                         kind="read", label="Account balance",
                         description=("Live DashScope/Model-Studio account "
                                       "balance via Alibaba BSS "
                                       "QueryAccountBalance (needs a RAM "
                                       "AccessKey pair, op:// resolved). "
                                       "Reports honestly when unconfigured — "
                                       "never fabricates a figure."),
                         inputs=[], output_type="object", fn=_balance),
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
