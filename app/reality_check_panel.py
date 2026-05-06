"""Reality Check — one-click end-to-end smoke test.

Pings every connector, runs a sanity invocation against each live one,
and checks the LLM router can complete a one-token request. The user
gets a per-system green/red verdict instead of having to suspect each
layer when something goes wrong.

Useful when a Skill misbehaves: open Reality Check, see which dot is
red, fix that one thing.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Optional

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)


# Connector ports we know about. (label, ping_url, /exec or /execute_python url, sample payload)
_PROBES: list[tuple[str, str, str, dict, str]] = [
    (
        "Revit",
        "http://localhost:48884/ping",
        "http://localhost:48884/exec",
        {"code": "result = Doc.Title;", "transaction_name": "ArchHub: probe"},
        "result",
    ),
    (
        "AutoCAD",
        "http://localhost:48885/ping",
        "http://localhost:48885/exec",
        {"code": "result = Doc.Name;"},
        "result",
    ),
    (
        "3ds Max",
        "http://localhost:48886/max-mcp/ping",
        "http://localhost:48886/max-mcp/exec",
        {"code": "result = rt.maxFileName"},
        "result",
    ),
    (
        "Blender",
        "http://localhost:9876/ping",
        "http://localhost:9876/exec",
        {"code": "import bpy; result = bpy.data.filepath or '(unsaved)'"},
        "result",
    ),
]


class _ProbeWorker(QObject):
    finished = pyqtSignal(list)        # list of dicts

    def __init__(self, router):
        super().__init__()
        self._router = router

    def run(self) -> None:
        results: list[dict] = []
        for label, ping_url, exec_url, payload, return_key in _PROBES:
            entry = {"label": label, "ping": False, "exec": False,
                     "exec_value": None, "error": None, "ms": 0}
            t0 = time.time()
            try:
                with urllib.request.urlopen(ping_url, timeout=1.5) as r:
                    entry["ping"] = (200 <= r.status < 300)
            except Exception as ex:
                entry["error"] = f"ping: {type(ex).__name__}: {ex}"
                entry["ms"] = int((time.time() - t0) * 1000)
                results.append(entry)
                continue

            t0 = time.time()
            try:
                req = urllib.request.Request(
                    exec_url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10.0) as r:
                    body = json.loads(r.read().decode("utf-8"))
                if (body or {}).get("status") == "ok":
                    entry["exec"] = True
                    entry["exec_value"] = body.get(return_key)
                else:
                    entry["error"] = f"exec: {(body or {}).get('error', 'unknown')}"
            except Exception as ex:
                entry["error"] = f"exec: {type(ex).__name__}: {ex}"
            entry["ms"] = int((time.time() - t0) * 1000)
            results.append(entry)

        # LLM check — one tiny prompt, expect any response within 10s.
        llm_entry = {"label": "LLM router", "ping": False, "exec": False,
                     "exec_value": None, "error": None, "ms": 0}
        t0 = time.time()
        try:
            providers = self._router.configured_providers()
            llm_entry["ping"] = bool(providers)
            if not providers:
                llm_entry["error"] = "no provider configured (sign in via Settings)"
            else:
                resp = self._router.complete(
                    [{"role": "user", "content": "Reply with exactly the word READY."}],
                    model="auto",
                )
                txt = (resp.text or "").strip().upper()
                llm_entry["exec"] = "READY" in txt
                llm_entry["exec_value"] = (resp.text or "")[:60]
                if not llm_entry["exec"]:
                    llm_entry["error"] = f"unexpected reply: {txt[:80]!r}"
        except Exception as ex:
            llm_entry["error"] = f"{type(ex).__name__}: {ex}"
        llm_entry["ms"] = int((time.time() - t0) * 1000)
        results.append(llm_entry)

        self.finished.emit(results)


class RealityCheckDialog(QDialog):
    """Modal that runs the probe + renders per-system verdicts."""

    def __init__(self, router, parent=None):
        super().__init__(parent)
        self.router = router
        self.setWindowTitle("ArchHub — Reality Check")
        self.setObjectName("panel")
        self.setMinimumWidth(560)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())

        body = QFrame()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(24, 18, 24, 12)
        bv.setSpacing(8)
        self._body_layout = bv
        self._status = QLabel("Probing every connector + LLM…")
        self._status.setObjectName("settingsSubtitle")
        bv.addWidget(self._status)
        outer.addWidget(body, 1)

        outer.addWidget(self._build_footer())

        self._start_probe()

    def _build_header(self) -> QFrame:
        hf = QFrame(); hf.setObjectName("panelHeader")
        v = QVBoxLayout(hf); v.setContentsMargins(28, 22, 28, 16); v.setSpacing(4)
        t = QLabel("Reality Check"); t.setObjectName("panelTitle")
        s = QLabel("End-to-end smoke test of every system ArchHub depends on.")
        s.setObjectName("panelSubtitle"); s.setWordWrap(True)
        v.addWidget(t); v.addWidget(s)
        return hf

    def _build_footer(self) -> QFrame:
        f = QFrame(); f.setObjectName("panelFooter")
        h = QHBoxLayout(f); h.setContentsMargins(20, 12, 20, 14); h.setSpacing(8)
        self._rerun_btn = QPushButton("↻ Re-run")
        self._rerun_btn.setObjectName("ghostButton")
        self._rerun_btn.clicked.connect(self._start_probe)
        h.addWidget(self._rerun_btn)
        h.addStretch(1)
        close = QPushButton("Close")
        close.setObjectName("primaryButton")
        close.clicked.connect(self.accept)
        h.addWidget(close)
        return f

    def _start_probe(self) -> None:
        # Wipe old rows
        while self._body_layout.count() > 1:
            item = self._body_layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
        self._status.setText("Probing every connector + LLM…")
        self._rerun_btn.setEnabled(False)

        self._worker = _ProbeWorker(self.router)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._render_results)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _render_results(self, results: list) -> None:
        self._rerun_btn.setEnabled(True)
        self._status.setText("Per-system verdict:")
        for r in results:
            row = QFrame(); row.setObjectName("providerRow")
            hl = QHBoxLayout(row); hl.setContentsMargins(14, 10, 14, 10); hl.setSpacing(10)

            if r["exec"]:
                dot = "✓"; color = "#7ed957"
            elif r["ping"]:
                dot = "◐"; color = "#e6b35c"
            else:
                dot = "✗"; color = "#d97757"
            icon = QLabel(dot); icon.setStyleSheet(f"color:{color};font-size:18px;font-weight:600;")
            hl.addWidget(icon)

            label = QLabel(f"<b>{r['label']}</b>")
            label.setObjectName("providerName")
            hl.addWidget(label)

            if r["exec"]:
                detail = f"<i style='color:#a09a90;'>{r['ms']} ms · {str(r['exec_value'])[:80]}</i>"
            elif r["ping"]:
                detail = f"<i style='color:#e6b35c;'>reachable but exec failed: {(r['error'] or '')[:120]}</i>"
            else:
                detail = f"<i style='color:#d97757;'>{(r['error'] or 'unreachable')[:120]}</i>"
            d = QLabel(detail); d.setObjectName("providerStatus"); d.setWordWrap(True)
            hl.addWidget(d, 1)

            self._body_layout.addWidget(row)

        # Aggregate verdict
        all_green = all(r["exec"] for r in results)
        any_red = any(not r["ping"] and not r["exec"] for r in results)
        if all_green:
            self._status.setText("✅ Every system is healthy.")
        elif any_red:
            self._status.setText("⚠️ Some systems are unreachable. Open the matching app + connector.")
        else:
            self._status.setText("◐ Reachable but degraded. See per-system messages.")
