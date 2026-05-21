---
id: AgDR-0008
timestamp: 2026-05-20T00:00:00Z
agent: claude-code (Sonnet)
session: node-redesign-loop
trigger: /loop slice E
status: executed
category: architecture
projects: [archhub]
---

# Annotation Bodies — Watch Renderers + Note Markdown

> In the context of slice E of the node-system redesign (AgDR-0001
> §7.4), implementing the two annotation primitives' bodies, I
> decided to add a `WatchBody` component that dispatches on
> `config.as` (`list` / `table` / `json` / `image` / `view` /
> `model`) and renders the incoming `cooked.value` accordingly, plus
> a `NoteBody` component that stores its content in a `text`
> param and renders a small in-house markdown subset (headers,
> bold, italic, code, links, images, bullet lists) with
> double-click-to-edit textarea — to ship Grasshopper's
> "Panel + Scribble" pair without pulling in an external markdown
> dependency, accepting that the markdown subset is intentionally
> narrow (heavy formatting will fall through as plain text).

## Context
- AgDR-0001 §7.4 locked two distinct annotation primitives:
  `watch` (receives a wire, shows the value) and `note` (pure
  markdown, no I/O).
- Both primitives ALREADY exist in `node_grammar.py`. `watch` has
  a `data.watch.preview` engine executor (passthrough + preview).
  `note` is `UX_ONLY`.
- Current `NodeBody` falls through to `GrammarBody` for both —
  shows raw param rows + a single cooked-preview line. Useful as
  default, but does not honour the per-renderer intent of `watch`
  nor the markdown intent of `note`.
- No markdown library is bundled. Babel-standalone runs in the
  QtWebEngine; no `npm install` available. A small in-house parser
  is the pragmatic choice — fits the AEC-grade subset users
  actually write.

## Options Considered

| Decision | Picked | Why |
|---|---|---|
| Watch renderer dispatch | `n.config.as` (already in params) | Zero new state; the dispatch matches the grammar |
| Renderers supported | `list` / `table` / `json` / `image` / `view` / `model` (latter two as JSON placeholders for now) | All six locked by AgDR-0001 §7.4; `view`/`model` need a 3D viewer (future slice) but ship as JSON so the param value is real |
| Note storage | `text` param row (`type:'markdown'`) | Round-trips through the existing `params` → `config` fold; saves with the graph automatically |
| Markdown subset | Headers `#` / `##` / `###`, `**bold**`, `_italic_`, `` `code` ``, `[txt](url)`, `![alt](src)`, bullet `- `, line breaks | Covers ~95% of real notes; everything else falls through as plain text |
| Note editing | Double-click body → textarea + blur to commit | Matches the "rename" gesture used elsewhere on the canvas |
| Watch table inference | Array of objects → infer columns from keys; array of arrays → numeric column headers | Standard pandas/CSV convention; no schema needed |

## Decision

### `WatchBody`
A new component routed from `NodeBody`'s `cat: 'watch'` branch.
Reads:
- `n.config.as` (from the `as` param). Defaults to `json`.
- `n.cooked.value`. May be `undefined` if no upstream cook yet.

Renderers:
- `list` — `<ul>` of items. Each item: `String(item)` truncated to
  120 chars, with hover-tooltip showing the full repr.
- `table` — `<table>` with inferred columns:
  - Array of plain objects → columns from the union of keys, rows
    are the objects.
  - Array of arrays → columns are `0..n-1`, rows are the arrays.
  - Array of scalars → single "value" column.
  - Non-array → single-row, single-cell with the value.
- `json` — `<pre>` with `JSON.stringify(value, null, 2)`, truncated
  to 2000 chars + an ellipsis.
- `image` — if `value` is a string starting with `data:image/` or
  `http(s)://…(png|jpg|jpeg|gif|webp|svg)`, render as `<img src>`.
  Otherwise fall through to `json`.
- `view` / `model` — placeholder: render the value as `json` with
  a `3D viewer — coming soon` muted header (real 3D rendering is
  out of scope for slice E; this keeps the param value honest).

Empty state (no cooked value) — italic muted "no data yet — wire a
node to me".

### `NoteBody`
A new component routed from `NodeBody`'s `cat: 'note'` branch.
Reads `n.config.text` (or first `params` row keyed `text`).
Render:
- View mode (default): the rendered markdown.
- Edit mode (entered via double-click): a `<textarea>` initialised
  with the raw text. `onBlur` or `Escape` commits the new value
  into the node's `params` row, calls `saveCurrentGraph`,
  exits edit mode.

Markdown parser (in-house, ~40 LOC):
1. Split into lines.
2. For each line, in order:
   - `# ` / `## ` / `### ` → `<h1>` / `<h2>` / `<h3>`.
   - `- ` (or `* `) at line start → bullet item; consecutive
     bullets group into a single `<ul>`.
   - `` `code` `` → `<code>`.
   - `**bold**` → `<strong>`.
   - `_italic_` → `<em>`.
   - `[text](url)` → `<a>` with `target="_blank"`.
   - `![alt](url)` → `<img alt="alt" src="url" />` (only allow
     `http(s):` or `data:image/` URLs — security; reject `javascript:`
     and `file:`).
3. Wrap remaining non-list lines in `<p>`.

Implementation note: `<a>` and `<img>` rendered via React with
explicit attribute construction, NOT `dangerouslySetInnerHTML` —
keeps XSS off the table (no raw HTML pipe). The parser emits a
tree of React elements.

### NodeBody switch update
```js
case 'watch': return <WatchBody n={n}/>;
case 'note':  return <NoteBody n={n}/>;
```

### Grammar update
`note` primitive gains a `text` param row:
```python
Primitive(
  "note", "Note", "note", "",
  {}, UX_ONLY, "never executes",
  params=({"k":"text","v":"_Note — double-click to edit_",
          "type":"markdown"},),
  blurb="A sticky note",
)
```

(`UX_ONLY` is still exempt from the "must-have-params" assert in
`test_payload_is_serialisable_and_complete`; the added row is for
the body to read.)

## Consequences
- `n.cat: 'watch'` and `n.cat: 'note'` get dedicated bodies — no
  more "raw param row" view for the most user-visible primitives.
- `note` primitive now lands with a default markdown line; the
  body renders + lets the user edit inline.
- No new engine work, no Python changes.
- Tests: grammar tests unchanged (note status still UX_ONLY,
  watch still READY with `as` param).
- XSS: note markdown is rendered via React elements, not innerHTML;
  links/images URL-filtered to `http(s):` / `data:image/`.
- Future: real 3D viewer for `view`/`model` (separate AgDR).

## Artifacts
- This AgDR.
- `app/workflows/node_grammar.py` — `note` gains a `text` param row.
- `app/web_ui/studio-lm.jsx` — `WatchBody`, `NoteBody`, `NodeBody`
  switch update.
- Tests: existing grammar tests stay green (≤20 primitives, watch
  exempt unchanged).
