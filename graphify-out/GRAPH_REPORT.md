# ArchHub knowledge graph — 2026-05-24

Generated via `graphify` (AST extraction, 0 LLM tokens, $0 cost) and
filtered to drop vendored JS / minified bundles.

## Headline numbers

| Metric | Value |
|---|---|
| Files scanned | **543** |
| Nodes (post-filter) | **10 560** |
| Edges (post-filter) | **16 820** |
| Deduped nodes | 439 (173 exact + 246 fuzzy) |
| Confidence: EXTRACTED | 86 % |
| Confidence: INFERRED | 14 % |
| LLM tokens used | **0** |
| Cost | **$0** |

Relation breakdown:
- `calls` — 8 968 (function-to-function invocation)
- `contains` — 8 357 (file→symbol)
- `rationale_for` — 2 292 (AgDR / docstring → code)
- `method` — 2 219
- `imports` — 1 278
- `uses` — 1 106
- `imports_from` — 973
- `inherits` — 157
- `references` — 54
- `re_exports` — 29
- `extends` — 7

## Top 25 god nodes (highest-connected, noise filtered)

| Conn | Symbol | Verdict |
|---|---|---|
| 135 | `app/web_ui/studio_lm.jsx` | THE giant — 3,900 lines of JSX in one file. Hot zone. Plan: progressive extraction to React components. |
| 125 | `app/chat_window/py` | Composer surface — natural hub |
| 121 | `app/studio_shell/py` | App shell — wraps everything |
| 102 | `app/bridge.py` | QWebChannel — Python↔JS contract. Critical. |
| 100 | `connectors/base/OpResult` | Uniform connector return type. Every op touches it. |
| 89 | `app/tool_engine/py` | LLM tool surface |
| 85 | `app/bridge/safe_json` | Bridge serialization layer |
| 77 | `workflows/runner/WorkflowRunner` | Graph executor |
| 61 | `workflows/graph/Port` | Typed port — AgDR-0001 substrate |
| 59 | `tests/test_library_validator.py` | Library-validation test surface |
| 58 | `app/llm_router.py` | LLM provider routing |
| 58 | `mcp/node_mcp/NodeMcpServer` | MCP node-tool server |
| 57 | `workflows/graph/Workflow` | Graph data model |
| 56 | `QWidget` | PyQt6 base class (expected) |
| 56 | `workflows/graph/PortType` | Type enum |
| 54 | `app/settings_dialog.py` | Settings surface |
| 53 | `cloud_backend/db.py` | Backend SQLite |
| 53 | `tests/test_rest_connectors/TestTeamsOps.run` | Teams ops test |
| 50 | `app/chat_window/MessageBubble` | Chat UI atom |
| 50 | `app/session/Session` | Session state |
| 49 | `cloud_backend/db/connect` | DB connection mgmt |
| 49 | `tests/test_office_connectors.py` | Office connectors test |
| 46 | `app/secrets_store/load_setting` | Encrypted secrets loader |
| 45 | `QLabel` | PyQt6 (expected) |
| 44 | `tests/test_reality_smoke/make_args` | Smoke-test helper |

## What this tells us

1. **studio-lm.jsx is the hottest file.** 135 connections. Confirms what
   you already knew (3,900 lines, hard to navigate). The composer-first
   home redesign (refined-A) is the right wedge: extract the Home tab
   into its own component.

2. **bridge.py + safe_json = critical bottleneck.** 102 + 85
   connections. Every JS call goes through it. Any change here breaks
   everything. Keep test coverage tight.

3. **`OpResult` is the canonical contract.** 100 connections.
   Connectors / runner / Composer all touch it. Don't add fields
   lightly.

4. **Runner + Graph + Port** = 77 + 61 + 57 = the AgDR-0001 + AgDR-0040
   core. AgDR-0041 robustness ops slot here cleanly.

5. **Tests already mirror the structure.** `test_rest_connectors`,
   `test_library_validator`, `test_office_connectors`, `test_reality_smoke`
   all in the top 25. Test coverage tracks architecture hotspots.

## Refresh

Re-run via:

```bash
python -m graphify.extract . > graphify-out/extraction.json 2>&1
# Filter vendor noise + build via app/scripts/graphify_refresh.py (TODO)
```

Or after `/graphify` skill is restart-loaded:

```
/graphify .
```

Output regenerates `graphify-out/extraction.json` + `graph.json` + this
report. Cache lives in `graphify-out/cache/`.

## Next

See `docs/agdr/AgDR-0042-shared-memory-knowledge-graph.md` for the
proposal to extend this data model from dev tooling into ArchHub's
runtime memory layer (Library + Project + Composer turns + Decisions
in one queryable graph).
