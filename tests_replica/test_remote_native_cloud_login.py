"""Structural courts for returning-device remote session admission."""
from __future__ import annotations

import ast
from pathlib import Path

import nodelang.cell_native_auth as remote_login


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "nodelang" / "cell_native_auth.py"


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
        "nodelang.cell_native_auth"
    )
