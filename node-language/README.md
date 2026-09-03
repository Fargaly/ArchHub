# Node language

The Universal Cell kernel and the canvas that runs on it. One persisted
shape — `Cell(id, link0, link1, atom)` — an append-only journal, and an
application projected out of the graph rather than written beside it.

## Read these first, in this order

| file | what it settles |
|------|-----------------|
| `AUTHORITY.md` | which document wins when two disagree |
| `SPEC.md` | what the thing is, and §11 — the seventeen acceptance courts that define "done" |
| `RESEARCH-UNIVERSAL-CELL.md` | why the shape is this shape |

Nothing here is finished because it looks finished. A slice is done when
its applicable courts in `SPEC.md` §11 pass against its exact revision.

## Where the work is

| folder | what lives there |
|--------|------------------|
| `nodelang/` | the kernel of record. Everything the product actually runs. |
| `tests_replica/` | the courts. Run against a replica graph, not the live one. |
| `tests_domains/`, `tests_js/`, `tests/` | domain fixtures, the jsdom interaction probe, and one replica-server court |
| `evidence/` | `build_current_evidence.py` → `current-evidence.json`, the record that binds a green claim to a source hash |
| `desktop/` | the shell that opens the canvas as an application window |
| `packaging/`, `infrastructure/` | how it is built and where it is deployed |
| `public_site/`, `docs/` | the published site and its pages |
| `domain_sessions/` | saved graph sessions used as fixtures |
| `tools/` | scripts that drive the graph from outside: servers, sweeps, one-shot builders |
| `legacy_engine/` | the superseded engine (`node_lang.py`) and everything that imports it. Not the kernel. Nothing in `nodelang/` depends on it. |

## Running it

The owner process serves coordination on `8474` and the canvas on `8475`:

```bash
python -m nodelang.clean_coordination_service --host 127.0.0.1 --port 8474
```

Open `http://127.0.0.1:8475/`. A cold start shows the boot page, then the
canvas — measured at 9.3s to twenty-six cards on the live graph.

The live graph is `%LOCALAPPDATA%\ArchHub\unified-authority` and only one
process may own it at a time. Read it from anywhere else with
`immutable=1`; never open it for writing behind the owner's back.

## Running the courts

```bash
python -m pytest tests_replica -q
```

`pyproject.toml` sets `pythonpath = ["."]` and a court holds it there, so
top-level packages import by name: `nodelang`, `tools`, `legacy_engine`.

Two timing logs answer "why was that slow", both under the authority
directory: `boot-timing.log` (per boot phase) and `gesture-timing.log`
(per projection, with the lens split by phase).
