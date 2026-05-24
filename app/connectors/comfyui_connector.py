"""ComfyUI connector — REST client for a local or remote ComfyUI server.

Tier 0 of the AgDR-0042-adjacent assimilation (the founder's
ComfyUI / Alibaba research, 2026-05-24). ComfyUI workflows are
already graph-as-JSON; ArchHub workflows are graph-as-JSON; this
connector lets one cook the other via the server's `/prompt` REST
endpoint.

Configuration:
  COMFYUI_URL  (env or settings) — default http://127.0.0.1:8188
  COMFYUI_AUTH (optional)         — bearer token for hosted ComfyUI

Operations:
  comfyui.probe          — verify server is up + return version + queue depth
  comfyui.list_models    — `/object_info` model lists (checkpoints, LoRAs)
  comfyui.queue_prompt   — POST a workflow JSON to `/prompt`; returns prompt_id
  comfyui.get_history    — fetch `/history/<prompt_id>` for a queued job
  comfyui.get_image      — fetch `/view?filename=...&type=output` (bytes)
  comfyui.run_workflow   — convenience: queue + poll + return first image url

Honest-status contract: every method returns OpResult. A failed call
emits ok=False + an error string; downstream nodes see
upstream_error. No fabrication.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from .base import Connector, ConnectorOp, OpResult, ParamSpec, register


def _default_url() -> str:
    return (os.environ.get("COMFYUI_URL")
            or "http://127.0.0.1:8188").rstrip("/")


def _http_json(method: str, url: str, body: Optional[dict] = None,
                timeout: int = 20) -> tuple[int, Any]:
    """Tiny stdlib HTTP helper — keeps the connector dep-free.
    Returns (status_code, decoded_body or raw bytes on error)."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    auth = os.environ.get("COMFYUI_AUTH")
    if auth:
        headers["Authorization"] = f"Bearer {auth}"
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


# ── op implementations ─────────────────────────────────────────────


def _probe() -> OpResult:
    url = _default_url()
    code, body = _http_json("GET", f"{url}/system_stats", timeout=5)
    if code == 0:
        return OpResult.fail(f"unreachable: {body}", "comfyui.probe")
    if code >= 400:
        return OpResult.fail(f"HTTP {code}: {body}", "comfyui.probe")
    queue_depth = 0
    qcode, qbody = _http_json("GET", f"{url}/queue", timeout=5)
    if qcode < 400 and isinstance(qbody, dict):
        queue_depth = (len(qbody.get("queue_running") or [])
                       + len(qbody.get("queue_pending") or []))
    return OpResult(
        ok=True, op_id="comfyui.probe",
        value={"url": url, "queue_depth": queue_depth, "stats": body},
        value_preview=f"comfyui up · queue={queue_depth}")


def _list_models() -> OpResult:
    url = _default_url()
    code, body = _http_json("GET", f"{url}/object_info", timeout=10)
    if code >= 400 or not isinstance(body, dict):
        return OpResult.fail(f"list_models: HTTP {code}", "comfyui.list_models")
    # Extract checkpoint + LoRA + ControlNet model lists from the
    # object_info schema (Comfy stuffs them in node param enums).
    out: dict[str, list] = {"checkpoints": [], "loras": [],
                              "controlnets": []}
    try:
        ck = (body.get("CheckpointLoaderSimple", {})
                  .get("input", {}).get("required", {})
                  .get("ckpt_name", [[]])[0])
        if isinstance(ck, list):
            out["checkpoints"] = ck
        lo = (body.get("LoraLoader", {})
                  .get("input", {}).get("required", {})
                  .get("lora_name", [[]])[0])
        if isinstance(lo, list):
            out["loras"] = lo
        cn = (body.get("ControlNetLoader", {})
                  .get("input", {}).get("required", {})
                  .get("control_net_name", [[]])[0])
        if isinstance(cn, list):
            out["controlnets"] = cn
    except Exception:
        pass
    return OpResult(ok=True, op_id="comfyui.list_models", value=out,
                     value_preview=(f"{len(out['checkpoints'])} ckpt · "
                                    f"{len(out['loras'])} lora · "
                                    f"{len(out['controlnets'])} cn"))


def _queue_prompt(*, workflow: Any, client_id: str = "archhub"
                   ) -> OpResult:
    """Queue an API-format workflow JSON. Returns {prompt_id}."""
    if isinstance(workflow, str):
        try:
            workflow = json.loads(workflow)
        except Exception as ex:
            return OpResult.fail(f"invalid workflow JSON: {ex}",
                                  "comfyui.queue_prompt")
    if not isinstance(workflow, dict):
        return OpResult.fail("workflow must be an object",
                              "comfyui.queue_prompt")
    url = _default_url()
    code, body = _http_json("POST", f"{url}/prompt",
                              {"prompt": workflow,
                               "client_id": client_id})
    if code >= 400 or not isinstance(body, dict):
        return OpResult.fail(f"HTTP {code}: {body}",
                              "comfyui.queue_prompt")
    return OpResult(ok=True, op_id="comfyui.queue_prompt",
                     value={"prompt_id": body.get("prompt_id"),
                            "number": body.get("number")},
                     value_preview=f"queued · {body.get('prompt_id')}")


def _get_history(*, prompt_id: str) -> OpResult:
    url = _default_url()
    pid = (prompt_id or "").strip()
    if not pid:
        return OpResult.fail("prompt_id required",
                              "comfyui.get_history")
    code, body = _http_json("GET", f"{url}/history/{pid}", timeout=10)
    if code >= 400:
        return OpResult.fail(f"HTTP {code}: {body}",
                              "comfyui.get_history")
    return OpResult(ok=True, op_id="comfyui.get_history", value=body)


def _get_image(*, filename: str, subfolder: str = "",
                type: str = "output") -> OpResult:
    """Return raw image bytes for /view."""
    url = _default_url()
    qs = urllib.parse.urlencode({"filename": filename,
                                   "subfolder": subfolder,
                                   "type": type})
    full = f"{url}/view?{qs}"
    try:
        with urllib.request.urlopen(full, timeout=30) as r:
            data = r.read()
        return OpResult(ok=True, op_id="comfyui.get_image",
                         value={"url": full, "bytes": len(data),
                                "data": data},
                         value_preview=f"{len(data)} bytes")
    except Exception as ex:
        return OpResult.fail(f"{type(ex).__name__}: {ex}",
                              "comfyui.get_image")


def _merge_inputs_into_workflow(workflow: Any, inputs: Any) -> Any:
    """Apply per-node input overrides on top of a workflow JSON.

    AgDR-0041 D3·B (2026-05-25) — typed upstream nodes feed workflow
    params dynamically. Shape of `inputs`:
        {"<node_id>": {"<param>": <value>, ...}, ...}
    For each node_id in `inputs`, sets workflow[node_id]["inputs"][param] =
    value. Falls through when inputs is empty/None or workflow isn't a dict.
    Returns the (possibly mutated copy of the) workflow.
    """
    if not inputs or not isinstance(inputs, dict):
        return workflow
    if not isinstance(workflow, dict):
        return workflow
    # Shallow copy of workflow + each touched node so we don't mutate
    # the caller's dict (Skills cache the workflow JSON).
    out = dict(workflow)
    for node_id, overrides in inputs.items():
        if not isinstance(overrides, dict):
            continue
        node = out.get(str(node_id))
        if not isinstance(node, dict):
            continue
        node_copy = dict(node)
        node_inputs = dict(node_copy.get("inputs") or {})
        for k, v in overrides.items():
            node_inputs[k] = v
        node_copy["inputs"] = node_inputs
        out[str(node_id)] = node_copy
    return out


def _run_workflow(*, workflow: Any, client_id: str = "archhub",
                    poll_seconds: int = 60,
                    inputs: Any = None) -> OpResult:
    """Convenience: queue + poll history every 1s until done or
    poll_seconds elapsed; return first output image url.

    D3·B: `inputs` overrides workflow node params before queue. See
    `_merge_inputs_into_workflow` for the shape."""
    workflow = _merge_inputs_into_workflow(workflow, inputs)
    q = _queue_prompt(workflow=workflow, client_id=client_id)
    if not q.ok:
        return q
    pid = q.value["prompt_id"]
    deadline = time.time() + poll_seconds
    while time.time() < deadline:
        time.sleep(1.0)
        h = _get_history(prompt_id=pid)
        if not h.ok:
            continue
        if isinstance(h.value, dict) and pid in h.value:
            entry = h.value[pid]
            outputs = entry.get("outputs") or {}
            images = []
            for node_id, out in outputs.items():
                for img in (out.get("images") or []):
                    images.append(img)
            if images:
                first = images[0]
                url = _default_url()
                qs = urllib.parse.urlencode({
                    "filename": first.get("filename"),
                    "subfolder": first.get("subfolder", ""),
                    "type": first.get("type", "output"),
                })
                return OpResult(
                    ok=True, op_id="comfyui.run_workflow",
                    value={"prompt_id": pid,
                            "images": images,
                            "first_url": f"{url}/view?{qs}"},
                    value_preview=f"{len(images)} image(s)")
    return OpResult.fail(f"timeout after {poll_seconds}s",
                          "comfyui.run_workflow")


# ── connector class ────────────────────────────────────────────────


class ComfyUIConnector(Connector):
    host = "comfyui"
    display_name = "ComfyUI"
    mechanism = "rest"

    def probe(self) -> dict:
        url = _default_url()
        code, body = _http_json("GET", f"{url}/system_stats", timeout=3)
        if code == 0:
            return {"status": "missing",
                    "note": f"no ComfyUI server at {url}",
                    "detail": {"url": url, "error": body}}
        if code >= 400:
            return {"status": "loaded_dead",
                    "note": f"{url} returned HTTP {code}",
                    "detail": {"url": url, "body": body}}
        return {"status": "live",
                "note": f"ComfyUI live at {url}",
                "detail": {"url": url, "stats": body}}

    def build_ops(self) -> list:
        return [
            ConnectorOp(
                op_id="comfyui.probe", host="comfyui", kind="read",
                label="Probe server",
                description="Reach the ComfyUI server, return version + queue depth.",
                inputs=[], output_type="object", fn=_probe),
            ConnectorOp(
                op_id="comfyui.list_models", host="comfyui", kind="read",
                label="List models",
                description="Read /object_info for checkpoints, LoRAs, ControlNets.",
                inputs=[], output_type="object", fn=_list_models),
            ConnectorOp(
                op_id="comfyui.queue_prompt", host="comfyui", kind="action",
                label="Queue workflow",
                description="POST a ComfyUI API-format workflow JSON to /prompt.",
                inputs=[
                    ParamSpec(id="workflow", label="Workflow JSON",
                              type="text", required=True),
                    ParamSpec(id="client_id", label="Client id",
                              type="text", default="archhub"),
                ],
                output_type="object", fn=_queue_prompt),
            ConnectorOp(
                op_id="comfyui.get_history", host="comfyui", kind="read",
                label="Get history",
                description="Fetch /history/<prompt_id> for a queued job.",
                inputs=[ParamSpec(id="prompt_id", label="Prompt id",
                                    type="text", required=True)],
                output_type="object", fn=_get_history),
            ConnectorOp(
                op_id="comfyui.get_image", host="comfyui", kind="read",
                label="Get image",
                description="Fetch /view?filename=... — returns image bytes.",
                inputs=[
                    ParamSpec(id="filename",  label="Filename", type="text",
                              required=True),
                    ParamSpec(id="subfolder", label="Subfolder", type="text"),
                    ParamSpec(id="type",      label="Type", type="text",
                              default="output"),
                ],
                output_type="any", fn=_get_image),
            ConnectorOp(
                op_id="comfyui.run_workflow", host="comfyui", kind="action",
                label="Run workflow (queue + poll)",
                description=("Convenience — queue the workflow then poll "
                             "history until done; return first output image url."),
                inputs=[
                    ParamSpec(id="workflow",      label="Workflow JSON",
                              type="text", required=True),
                    ParamSpec(id="client_id",     label="Client id",
                              type="text", default="archhub"),
                    ParamSpec(id="poll_seconds",  label="Poll seconds",
                              type="number", default=60),
                ],
                output_type="object", fn=_run_workflow),
        ]


register(ComfyUIConnector())
