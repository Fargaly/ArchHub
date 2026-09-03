"""Tier 0 connectors — comfyui + dashscope (2026-05-24).

Probe / op registration / OpResult contract. No live HTTP — we
monkeypatch urllib so tests run anywhere.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import connectors.comfyui_connector as comfy   # noqa: E402
import connectors.dashscope_connector as dash  # noqa: E402
from connectors.base import get, OpResult       # noqa: E402


# ── ComfyUI ────────────────────────────────────────────────────────


def test_comfyui_connector_registered():
    c = get("comfyui")
    assert c is not None
    assert c.host == "comfyui"
    assert c.mechanism == "rest"


def test_comfyui_ops_well_formed():
    c = get("comfyui")
    op_ids = {o.op_id for o in c.ops()}
    expected = {
        "comfyui.probe", "comfyui.list_models", "comfyui.queue_prompt",
        "comfyui.get_history", "comfyui.get_image", "comfyui.run_workflow",
    }
    assert expected.issubset(op_ids)


def test_comfyui_probe_handles_unreachable(monkeypatch):
    """Probe returns 'missing' when server is down — never raises."""
    monkeypatch.setattr(comfy, "_http_json",
                         lambda *a, **kw: (0, "connection refused"))
    res = comfy.ComfyUIConnector().probe()
    assert res["status"] == "missing"


def test_comfyui_queue_prompt_rejects_bad_json():
    res = comfy._queue_prompt(workflow="not-json{")
    assert not res.ok
    assert "invalid workflow JSON" in res.error


def test_comfyui_queue_prompt_via_op(monkeypatch):
    """Op contract — workflow dict goes through, OpResult comes back."""
    monkeypatch.setattr(comfy, "_http_json",
                         lambda *a, **kw: (200, {"prompt_id": "abc",
                                                  "number": 1}))
    op = get("comfyui").op("comfyui.queue_prompt")
    assert op is not None
    out = op.run(workflow={"3": {"class_type": "EmptyLatentImage"}})
    assert out.ok
    assert out.value["prompt_id"] == "abc"


# ── DashScope ──────────────────────────────────────────────────────


def test_dashscope_connector_registered():
    c = get("dashscope")
    assert c is not None
    assert c.host == "dashscope"


def test_dashscope_ops_well_formed():
    c = get("dashscope")
    op_ids = {o.op_id for o in c.ops()}
    expected = {
        "dashscope.probe", "dashscope.complete",
        "dashscope.vision_describe", "dashscope.image_edit",
        "dashscope.wan_i2v_async", "dashscope.task_poll",
    }
    assert expected.issubset(op_ids)


def test_dashscope_probe_missing_key(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    res = dash.DashscopeConnector().probe()
    assert res["status"] == "missing"
    assert "DASHSCOPE_API_KEY" in res["note"]


def test_dashscope_complete_returns_text(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    monkeypatch.setattr(dash, "_http",
                         lambda *a, **kw: (200, {"output": {
                             "choices": [{"message": {
                                 "content": "hello world"}}]}}))
    res = dash._complete(prompt="hi", model="qwen-turbo", max_tokens=8,
                          temperature=0.5)
    assert res.ok
    assert res.value["text"] == "hello world"


def test_dashscope_wan_i2v_async_returns_task_id(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    monkeypatch.setattr(dash, "_http",
                         lambda *a, **kw: (200, {"output": {
                             "task_id": "task_abc123"}}))
    res = dash._wan_i2v_async(image_url="https://x/y.jpg",
                                prompt="zoom in", duration_s=5)
    assert res.ok
    assert res.value["task_id"] == "task_abc123"


def test_dashscope_task_poll_returns_status(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    monkeypatch.setattr(dash, "_http",
                         lambda *a, **kw: (200, {"output": {
                             "task_status": "RUNNING"}}))
    res = dash._task_poll(task_id="task_abc")
    assert res.ok
    assert res.value["status"] == "RUNNING"


def test_dashscope_http_error_surfaces_as_opresult_fail(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    monkeypatch.setattr(dash, "_http",
                         lambda *a, **kw: (429, {"code": "Throttling"}))
    res = dash._complete(prompt="hi")
    assert not res.ok
    assert "429" in res.error
