# .archhub session format v1

A UTF-8 JSON document with `format: "archhub"`, `version: 1`, stable `id`, `title`, `nodes`, `wires`, `groups`, `notes`, and `viewport`. The document is the in-memory Canvas state; Open never executes it.

Each node has `id`, engine `type`, `params` and `position: {x,y}`. Optional `item` selects the existing Library card; otherwise the engine's declared Library sockets are used. Optional title, parent, children, presentation, frozen/pinned flags and JSON result retain editor and output state. Unknown engines survive opening and produce a clear missing-engine refusal on Run.

Each wire has a stable `id`, `from: {node,socket}`, `to: {node,socket}`, and optional `rule` using the existing stem wire condition grammar. One wire per input; cycles refuse before engine effects. Named socket values are delivered in topological order. A failed node retains its error and downstream nodes show Blocked. Effects use existing Enforce and engine-local approval boundaries.

Save validates first, writes and fsyncs one temporary file in the destination directory, then uses atomic replacement. A failed write preserves the old destination. Recent paths and per-session recovery files are local metadata under `%LOCALAPPDATA%/ArchHub/sessions-files/`; the portable document contains no account identity, local recent paths, tokens or secrets. No execution occurs on file drop or Open.

Limits: 8 MiB UTF-8 document, 10,000 nodes, 50,000 wires. The JSON schema is `ARCHHUB.schema.json`; runtime validation additionally checks identity uniqueness, group membership, wire endpoints and finite numbers. File association and a native Save As picker are installer/launcher integration hooks and must be admitted with that owner.
