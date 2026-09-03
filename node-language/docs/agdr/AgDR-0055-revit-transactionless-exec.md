---
id: AgDR-0055
title: Revit transactionless script execution support — allow read-only UI operations (like view activation) outside database transactions
timestamp: 2026-06-11
agent: antigravity (Gemini 2.0)
session: revit-transactionless-exec
status: proposed
category: connectors
projects: [archhub]
supersedes: null
superseded_by: null
---

## Context

In the Revit API, UI-only operations (such as changing the active view via `UIDocument.ActiveView` or `UIDocument.RequestViewChange()`) are strictly forbidden while a database transaction is open. Attempting to set these properties inside a transaction throws `InvalidOperationException: Cannot change the active view of a modifiable document`.

Currently, the RevitMCP C# broker wraps all arbitrary C# script execution inside a database transaction (`using (var tx = new Transaction(doc, txName)) { tx.Start(); ... }`) in its `/exec` route. As a result, the Python connector's attempt to switch to a named view before taking a viewport screenshot (`revit.export_viewport` with the `view` parameter specified) always fails when executing the view activation script.

To support exporting screenshots from different camera viewports for high-fidelity rendering, we must allow running C# scripts without starting a database transaction.

## Proposed Changes

We introduce an optional `"no_transaction": true` parameter in the `/exec` request body. When active:
1. The RevitMCP Core skips transaction creation and runs the compiled C# script directly.
2. The Python connector (`revit_connector.py`) is updated to pass this flag when running UI-only operations (such as view activation before viewport export).

## Options Considered

### Option A: dedicated `/activate_view` HTTP endpoint in the C# broker
Add a new route `/activate_view` that executes on the UI thread without a transaction, switching to the named view.
* *Pros:* Simple.
* *Cons:* Requires defining a new HTTP endpoint and custom C# routing logic. Less flexible if we need other transactionless operations (e.g., querying properties, closing views, UI interactions).

### Option B: optional `"no_transaction"` parameter in the `/exec` endpoint (CHOSEN)
Extend the existing `/exec` route to support transactionless execution via a boolean flag in the payload.
* *Pros:* Extremely flexible. Allows any future read-only or UI-only scripts to run outside transactions without modifying C# broker routes again. Keeps the core API surface minimal.
* *Cons:* Requires C# script authors to exercise care (modifying the model without a transaction will fail in Revit, but since it returns the API error, it is safe and fail-fast).

## Consequences

- The C# script compiler shim and execution pipeline remain fully backward-compatible.
- `revit_connector.py` is updated to pass `no_transaction=True` when activating views, allowing `export_viewport(view='...')` to succeed instantly.
- Multi-angle rendering can be automated seamlessly across distinct viewports in the model.
