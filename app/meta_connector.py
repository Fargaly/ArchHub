"""Meta-connector — ArchHub uses the LLM to write its own adapters.

The standard answer to "how do I get a Revit 2023 connector?" is no longer
"compile this C# project from `payload/sources/`". It's: ArchHub asks Claude
to generate one, validates it, installs it, and tests it live.

This module owns that pattern. It exposes one entry point per host family:

    generate_blender_addon(version, ctx) -> GeneratedSource
    generate_revit_addin(version, ctx)   -> GeneratedSource
    generate_acad_plugin(version, ctx)   -> GeneratedSource

All three call the LLM router with a strict system prompt that pins the
ArchHub connector contract — the contract is what the LLM is required to
implement, regardless of host language.

The generated source is then either:
  - written to `payload/<host>/<version>/...` directly (Python), or
  - written to a temp dir and handed to auto_build for compilation (C#).

Generation is cheap (one LLM call, ~5-20s) but cached by content hash so
repeating it on the same host+version is free. The static `payload/sources/`
becomes a checked-in fallback for offline use, not the primary path.

This is the principle: ArchHub is its own first user of the LLM.
"""
from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Contract — what every generated adapter must implement.
# ---------------------------------------------------------------------------

CONNECTOR_CONTRACT_BLENDER = """\
You are generating a single-file Blender addon (Python, Blender 3.6+ and 4.x
compatible) that implements ArchHub's standard connector contract.

The addon MUST:

1. Define `bl_info` with name "ArchHub Connector" and version (1, 0, 0).

2. On `register()`, start a localhost HTTP server on port 9876 (configurable
   via env var ARCHHUB_BLENDER_PORT). The server MUST run on a background
   thread, and it MUST marshal all calls that touch `bpy.data` or
   `bpy.context` onto Blender's main thread via `bpy.app.timers.register`
   with a one-shot callback. Never modify Blender data from a worker thread.

3. Expose four endpoints:

   GET  /ping
        -> 200 {"ok": true, "version": "<addon version>", "blender": "<bpy.app.version_string>"}

   GET  /info
        -> 200 {"ok": true, "filepath": "...", "scene": "...",
                "active_object": "<name or null>", "object_count": N,
                "engine": "CYCLES|EEVEE|...", "frame": N}

   POST /execute   body: {"code": "<python source>"}
        Executes the code in a fresh dict with `bpy` and `bmesh` injected.
        Captures stdout. Returns:
        -> 200 {"ok": true, "stdout": "...",
                "result": <whatever the user code assigned to `result`, JSON-safe>}
        On exception:
        -> 200 {"ok": false, "error": "<traceback>"}

   POST /render    body: {"output_path": "<absolute path>",
                          "engine": "CYCLES|BLENDER_EEVEE",
                          "samples": N (optional),
                          "resolution": [W, H] (optional)}
        -> 200 {"ok": true, "output_path": "..."}
        on failure {"ok": false, "error": "..."}

4. On `unregister()`, stop the HTTP server cleanly.

Rules of generation:

- Use only the Python standard library plus `bpy` / `bmesh`. Do NOT import
  flask, fastapi, requests, numpy, or anything else outside stdlib.
- Use `http.server.ThreadingHTTPServer` and a single handler class.
- All responses are JSON. Always set `Content-Type: application/json`.
- Wrap every endpoint in try/except so a single bad request never kills
  the server.
- Print a single startup line on register() so the user can see it in
  Blender's console: `[ArchHub] connector listening on 127.0.0.1:9876`.
- The whole addon must be one file. No imports from sibling modules.

Output: ONLY the Python source code of the addon. No markdown fences. No
explanatory prose. Just the code, ready to save as `archhub_connector.py`.
"""


CONNECTOR_CONTRACT_ACAD = """\
You are generating an AutoCAD plug-in written in C# that implements ArchHub's
standard connector contract for AutoCAD version {version}.

Targets (match the .NET runtime AutoCAD loads):
- AutoCAD 2024 and earlier: .NET Framework 4.8 (net48)
- AutoCAD 2025 and later:   .NET 8 (net8.0-windows)

Reference the managed AutoCAD .NET API assemblies (copy-local FALSE — they
ship with AutoCAD): AcMgd.dll, AcDbMgd.dll, AcCoreMgd.dll, plus AcCui.dll
where needed.

The plug-in MUST:

1. Implement `IExtensionApplication` (Initialize / Terminate).

2. On Initialize, start a `System.Net.HttpListener` on
   http://localhost:48885/ on a background thread. If 48885 is busy, walk
   forward through 48886..48899 and bind the first free port (the ArchHub
   broker scans this range). Print the bound port to the AutoCAD command
   line via `Application.DocumentManager.MdiActiveDocument.Editor.WriteMessage`.

3. Marshal every call that touches the AutoCAD database or document onto
   AutoCAD's main thread. HttpListener callbacks run on a worker thread, and
   the AutoCAD .NET API is single-threaded-apartment — use
   `Application.DocumentManager.ExecuteInCommandContextAsync` (2025+) or, for
   net48, post the work through a registered `Application.Idle` handler /
   `Document.SendStringToExecute` so the database is only touched in the
   document context. Never call the database API directly from the listener
   thread.

4. Expose endpoints (all responses JSON, Content-Type application/json):

   GET  /ping
        -> 200 {"status": "ok", "service": "acad-mcp", "version": "<plugin ver>",
                "acad": "<Application.Version>"}

   GET  /info
        -> 200 {"status": "ok", "document": "<active dwg name>",
                "path": "<full path or empty>", "acad_version": "...",
                "dwg_count": N}

   POST /execute   body: {"code": "<C# snippet>"} OR
                        {"command": "<AutoCAD command line string>"}
        For a `command`: send it to the active document command line and
        report it dispatched (AutoCAD runs it asynchronously).
        For `code`: Roslyn-compile + run the snippet with `Document doc`,
        `Database db`, and `Editor ed` in scope, inside a
        `using (Transaction tr = db.TransactionManager.StartTransaction())`
        block; if the snippet does not commit, auto-roll-back. Return any
        JSON-safe object the snippet assigns to a `result` local.
        -> 200 {"status": "ok", "result": <result>, "stdout": "..."}
        on failure {"status": "error", "error": "<message/traceback>"}

5. On Terminate, stop the HttpListener cleanly.

Rules of generation:
- Wrap every endpoint in try/catch so one bad request never kills the listener.
- Use only the .NET BCL + the AutoCAD managed API. No third-party HTTP/JSON
  frameworks beyond System.Text.Json (or a tiny hand-rolled JSON writer).
- Print one startup line to the command line:
  `[ArchHub] AutoCAD connector listening on http://localhost:<port>/`.

Output the .csproj and the .cs files separately, each preceded by a header
line of the form `### FILE: <relative path>` and followed by the file
contents. Nothing else.
"""


CONNECTOR_CONTRACT_REVIT = """\
You are generating a Revit external application written in C# that implements
ArchHub's standard connector contract for Revit version {version}.

Targets:
- Revit 2024 and earlier: .NET Framework 4.8 (net48)
- Revit 2025 and later:   .NET 8 (net8.0-windows)

The add-in MUST:

1. Implement `IExternalApplication` with OnStartup / OnShutdown.
2. On startup, start an `HttpListener` on http://localhost:48884/ on a
   background thread.
3. Marshal Revit document mutations onto Revit's UI thread via
   `ExternalEvent` + a custom `IExternalEventHandler` queue.
4. Expose endpoints: GET /ping, GET /info, POST /execute (Roslyn-compiled
   C# snippet that has `Document doc` and `UIDocument uidoc` in scope and
   may return any JSON-safe object via a `result` local).
5. Wrap every transaction inside a `using (Transaction tx = ...)` block;
   if the user code does not commit, auto-roll-back.

Output the .csproj and the .cs files separately, each preceded by a header
line of the form `### FILE: <relative path>` and followed by the file
contents. Nothing else.
"""


# ---------------------------------------------------------------------------
# Generated source object + cache.
# ---------------------------------------------------------------------------

@dataclass
class GeneratedSource:
    host:    str                              # "blender" / "revit" / "acad"
    version: str                              # "4.1" / "2025"
    files:   dict[str, str]                   # relative path -> source text
    model:   str                              # which LLM produced it
    cache_path: Optional[Path] = None         # where it was cached on disk


def _cache_dir() -> Path:
    base = Path(__file__).resolve().parent.parent / "payload" / "_generated"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _cache_key(host: str, version: str, contract: str) -> str:
    h = hashlib.sha256()
    h.update(host.encode()); h.update(b"|")
    h.update(version.encode()); h.update(b"|")
    h.update(contract.encode())
    return h.hexdigest()[:16]


def _try_cache(host: str, version: str, contract: str) -> Optional[GeneratedSource]:
    key = _cache_key(host, version, contract)
    p = _cache_dir() / f"{host}_{version}_{key}.txt"
    if not p.exists(): return None
    raw = p.read_text(encoding="utf-8")
    files = _parse_multifile(raw)
    if not files: return None
    return GeneratedSource(host=host, version=version, files=files,
                           model="cached", cache_path=p)


def _save_cache(host: str, version: str, contract: str,
                files: dict[str, str], model: str) -> Path:
    key = _cache_key(host, version, contract)
    p = _cache_dir() / f"{host}_{version}_{key}.txt"
    blob = ""
    for rel, src in files.items():
        blob += f"### FILE: {rel}\n{src}\n"
    p.write_text(blob, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Multi-file parser — for outputs that contain multiple files (Revit/AutoCAD).
# Single-file outputs (Blender) skip this and use the raw text directly.
# ---------------------------------------------------------------------------

_FILE_HEADER = re.compile(r"^###\s*FILE:\s*(.+)\s*$", re.MULTILINE)


def _parse_multifile(text: str) -> dict[str, str]:
    matches = list(_FILE_HEADER.finditer(text))
    if not matches:
        return {}
    out: dict[str, str] = {}
    for i, m in enumerate(matches):
        rel = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out[rel] = text[start:end].strip("\n") + "\n"
    return out


# ---------------------------------------------------------------------------
# Validation — fail fast if the LLM produced obviously broken code.
# ---------------------------------------------------------------------------

def _validate_python(src: str) -> Optional[str]:
    """Return None if the source parses, else the error message."""
    try:
        ast.parse(src)
    except SyntaxError as e:
        return f"Generated Python has a syntax error: {e}"
    # Sanity checks against the contract
    if "bl_info" not in src:
        return "Missing bl_info — not a valid Blender addon."
    if "register" not in src or "unregister" not in src:
        return "Missing register()/unregister() — not a valid Blender addon."
    if "9876" not in src and "ARCHHUB_BLENDER_PORT" not in src:
        return "Addon does not bind the contract port."
    return None


# ---------------------------------------------------------------------------
# Entry points — what the rest of the app calls.
# ---------------------------------------------------------------------------

def generate_blender_addon(version: str, router,
                           on_progress: Optional[Callable[[str, int, str], None]] = None,
                           force_regenerate: bool = False) -> GeneratedSource:
    """Generate (or load from cache) the Blender connector addon for `version`.

    `router` is the LLMRouter; we call router.complete with no tools, asking
    it for the addon source. The response is validated before returning.
    """
    on_progress = on_progress or (lambda *_: None)
    on_progress("Preparing", 5, f"Blender {version}")

    contract = CONNECTOR_CONTRACT_BLENDER
    if not force_regenerate:
        hit = _try_cache("blender", version, contract)
        if hit is not None:
            on_progress("Cache hit", 100, str(hit.cache_path))
            return hit

    on_progress("Asking the model to write the addon", 20, "")
    prompt = (
        f"Generate the addon for Blender version {version}. "
        f"Follow the contract exactly. Output only Python source.\n\n"
        f"{contract}"
    )
    chunks: list[str] = []
    response = router.complete(
        history=[{"role": "user", "content": prompt}],
        model="auto",
        on_chunk=lambda piece: chunks.append(piece),
        on_tool_invocation=lambda _inv: None,
    )
    on_progress("Validating generated code", 75, response.model)

    src = (response.text or "").strip()
    # Strip code fences if the model added them
    src = re.sub(r"^```(?:python)?\s*\n", "", src)
    src = re.sub(r"\n```\s*$", "", src)

    err = _validate_python(src)
    if err is not None:
        raise RuntimeError(f"Generated Blender addon failed validation: {err}")

    files = {"archhub_connector.py": src}
    cache_path = _save_cache("blender", version, contract, files, response.model)
    on_progress("Done", 100, str(cache_path))
    return GeneratedSource(host="blender", version=version, files=files,
                           model=response.model, cache_path=cache_path)


def generate_revit_addin(version: str, router,
                         on_progress: Optional[Callable[[str, int, str], None]] = None,
                         force_regenerate: bool = False) -> GeneratedSource:
    """Generate the C# Revit add-in for the requested Revit major version."""
    on_progress = on_progress or (lambda *_: None)
    on_progress("Preparing", 5, f"Revit {version}")

    contract = CONNECTOR_CONTRACT_REVIT.format(version=version)
    if not force_regenerate:
        hit = _try_cache("revit", version, contract)
        if hit is not None:
            on_progress("Cache hit", 100, str(hit.cache_path))
            return hit

    on_progress("Asking the model to write the add-in", 20, "")
    prompt = (
        f"Generate the Revit add-in. Follow the contract exactly. "
        f"Output ONLY the files using the `### FILE: <path>` header convention.\n\n"
        f"{contract}"
    )
    chunks: list[str] = []
    response = router.complete(
        history=[{"role": "user", "content": prompt}],
        model="auto",
        on_chunk=lambda piece: chunks.append(piece),
        on_tool_invocation=lambda _inv: None,
    )
    on_progress("Parsing generated files", 75, response.model)

    files = _parse_multifile(response.text or "")
    if not files:
        raise RuntimeError("Generated Revit add-in did not include any files.")
    if not any(p.endswith(".cs") for p in files):
        raise RuntimeError("Generated Revit add-in is missing the .cs source.")
    if not any(p.endswith(".csproj") for p in files):
        raise RuntimeError("Generated Revit add-in is missing the .csproj.")

    cache_path = _save_cache("revit", version, contract, files, response.model)
    on_progress("Done", 100, str(cache_path))
    return GeneratedSource(host="revit", version=version, files=files,
                           model=response.model, cache_path=cache_path)


def _validate_csharp_files(files: dict[str, str], host: str,
                           must_contain: tuple[str, ...]) -> Optional[str]:
    """Validate a multi-file C# connector output. Returns None when valid,
    else a human error message. Checks the structural contract — a .cs + a
    .csproj exist and the .cs names the required contract tokens — without
    needing a compiler (that's `auto_build`'s job at install time)."""
    if not files:
        return f"Generated {host} plug-in did not include any files."
    if not any(p.endswith(".cs") for p in files):
        return f"Generated {host} plug-in is missing the .cs source."
    if not any(p.endswith(".csproj") for p in files):
        return f"Generated {host} plug-in is missing the .csproj."
    cs_blob = "\n".join(src for p, src in files.items() if p.endswith(".cs"))
    missing = [tok for tok in must_contain if tok not in cs_blob]
    if missing:
        return (f"Generated {host} plug-in is missing required contract "
                f"element(s): {', '.join(missing)}")
    return None


@dataclass
class UnavailableConnector:
    """A typed, honest 'could not generate' result — the meta-connector's
    answer when generation genuinely can't proceed (no LLM router, the model
    returned nothing usable, validation failed). It is the AutoCAD/Revit
    parallel of a connector's `missing`/`unauthorized` honest status: the
    caller gets a structured value it can show, NOT an exception.

    `ok` is always False; `host`/`version` echo the request; `reason` is a
    machine code; `detail` is a plain-English explanation; `fallback` names
    the static `payload/sources/` path callers can fall back to (offline)."""
    host: str
    version: str
    reason: str            # "no_router" | "empty_generation" | "validation_failed"
    detail: str
    fallback: Optional[str] = None
    ok: bool = False


def generate_acad_plugin(version: str, router,
                         on_progress: Optional[Callable[[str, int, str], None]] = None,
                         force_regenerate: bool = False):
    """Generate (or load from cache) the AutoCAD connector plug-in for
    `version`, mirroring `generate_revit_addin`. Same shape: one LLM call
    pinned to the ArchHub AutoCAD connector contract, validated, cached by
    content hash.

    NEVER raises for an unavailable path — when generation genuinely can't
    proceed (no router, empty model output, validation failure) it returns a
    typed `UnavailableConnector` (the honest-degrade contract: "one master
    connector per host" degrades, it does not throw `NotImplementedError`).
    """
    on_progress = on_progress or (lambda *_: None)
    on_progress("Preparing", 5, f"AutoCAD {version}")

    # NB: .replace (not .format) — the contract body contains literal JSON
    # braces ({"status": "ok"} examples) that str.format would choke on.
    contract = CONNECTOR_CONTRACT_ACAD.replace("{version}", str(version))
    if not force_regenerate:
        hit = _try_cache("acad", version, contract)
        if hit is not None:
            on_progress("Cache hit", 100, str(hit.cache_path))
            return hit

    if router is None:
        # No LLM router wired — honest typed unavailable, never a raise.
        on_progress("Unavailable", 100, "no LLM router")
        return UnavailableConnector(
            host="acad", version=version, reason="no_router",
            detail="No LLM router is available to generate the AutoCAD "
                   "connector. Wire a model in Settings, or use the static "
                   "payload/sources/ fallback offline.",
            fallback=str(_static_fallback_dir("acad")))

    on_progress("Asking the model to write the plug-in", 20, "")
    prompt = (
        f"Generate the AutoCAD plug-in. Follow the contract exactly. "
        f"Output ONLY the files using the `### FILE: <path>` header convention.\n\n"
        f"{contract}"
    )
    chunks: list[str] = []
    response = router.complete(
        history=[{"role": "user", "content": prompt}],
        model="auto",
        on_chunk=lambda piece: chunks.append(piece),
        on_tool_invocation=lambda _inv: None,
    )
    on_progress("Parsing generated files", 75, getattr(response, "model", ""))

    files = _parse_multifile(getattr(response, "text", "") or "")
    if not files:
        on_progress("Unavailable", 100, "empty generation")
        return UnavailableConnector(
            host="acad", version=version, reason="empty_generation",
            detail="The model returned no usable plug-in files. Retry, or "
                   "use the static payload/sources/ fallback offline.",
            fallback=str(_static_fallback_dir("acad")))

    # Structural validation against the AutoCAD contract.
    err = _validate_csharp_files(
        files, "AutoCAD",
        must_contain=("IExtensionApplication", "HttpListener", "48885"))
    if err is not None:
        on_progress("Unavailable", 100, "validation failed")
        return UnavailableConnector(
            host="acad", version=version, reason="validation_failed",
            detail=err, fallback=str(_static_fallback_dir("acad")))

    cache_path = _save_cache("acad", version, contract, files,
                             getattr(response, "model", "unknown"))
    on_progress("Done", 100, str(cache_path))
    return GeneratedSource(host="acad", version=version, files=files,
                           model=getattr(response, "model", "unknown"),
                           cache_path=cache_path)


def _static_fallback_dir(host: str) -> Path:
    """The checked-in static source dir a caller can build offline when
    LLM generation is unavailable. Path is reported even if it doesn't yet
    exist — it names WHERE the offline fallback lives."""
    return (Path(__file__).resolve().parent.parent
            / "payload" / "sources" / host)
