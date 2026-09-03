"""Structural courts for returning-device remote session admission."""
from __future__ import annotations

import ast
from pathlib import Path

import nodelang.remote_native_cloud_login as remote_login


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "nodelang" / "remote_native_cloud_login.py"
PLAN = ROOT / "REMOTE-DEVICE-SESSION-AUTHORITY.md"


def test_remote_login_reads_one_caller_store_without_a_shadow_authority():
    source = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    constructed = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "CellStore" not in constructed
    assert "register_device_custody" not in source
    assert "provision_device_binding" not in source
    assert "FastAPI" not in source
    assert "ThreadingHTTPServer" not in source
    assert "sqlite" not in source.lower()
    assert "postgres" not in source.lower()
    assert remote_login.RemoteNativeCloudLoginBroker.__module__ == (
        "nodelang.remote_native_cloud_login"
    )


def test_remote_device_authority_plan_answers_the_required_questions():
    text = PLAN.read_text(encoding="utf-8")
    for heading in (
        "## 1. What",
        "## 2. Why",
        "## 3. How",
        "## 4. Who",
        "## 5. When",
        "## 6. Where",
        "## 7. Evidence and required courts",
    ):
        assert heading in text
    for standard in (
        "OpenID Connect Core 1.0",
        "RFC 8252",
        "RFC 7636",
        "RFC 8414",
        "RFC 9207",
        "RFC 9449",
        "RFC 9700",
        "RFC 7009",
    ):
        assert standard in text
    assert "OIDC alone is not an acceptable first-device root of trust." in text
    assert "no production OIDC client/issuer is released" in text
