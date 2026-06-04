# Cloud database — live round-trip verification (2026-05-28)

**Verdict:** The cloud database RUNS and the brain-sync round-trip is verified
LIVE end-to-end. A real uvicorn process served real HTTP; a posted fragment
physically landed in a per-user sqlite replica; two users got isolated replica
directories; a bare secret was rejected at the boundary; and GDPR erasure
physically removed one user's replica while the other survived.

This supersedes the wave-5 Track-D status of "primitives shipped · not
live-verified" (the disclosure banner in `brain_replica.py` noting "the FastAPI
server it plugs into is not started by this session").

## What ran

- App: `cloud_backend/main.py` → `main:app` (FastAPI 0.136.x), served by
  `uvicorn` on `http://127.0.0.1:8788`, real OS process (PID 59412).
- Startup log:
  ```
  INFO:     Started server process [59412]
  INFO:     Application startup complete.
  INFO:     Uvicorn running on http://127.0.0.1:8788 (Press CTRL+C to quit)
  ```

## Routes exercised (from main.py)

- `GET  /healthz`            → Fly.io health check
- `POST /v1/brain/sync`      → apply a brain delta to the per-user replica
- `DELETE /v1/brain/sync`    → GDPR right-to-erasure (drop the replica dir)
- (sanity) `GET /v1/billing/plans` → public plan catalog

**Auth scheme:** bearer token in `Authorization: Bearer <token>`. The sync
routes call `_require_user(authorization)` → `_bearer()` extracts the token →
`db.user_for_token(token)` resolves the user (joins `tokens` → `users`). Tokens
are minted by `db.issue_token(user_id)` (format `ah_live_<urlsafe>`); users come
from `db.get_or_create_user(email)`. For this verification two real users +
tokens were minted directly in the server's `archhub_cloud.db`, mirroring how
`tests/test_brain_sync_endpoint.py::_signed_in_user` authenticates.

Test users (minted live):
- USER1 = `u_19e6fdbbbbe_37fb4d30a85e`
- USER2 = `u_19e6fdbbbca_d81f5efa761e`

## Health probe

```
$ curl -s -i http://127.0.0.1:8788/healthz
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json

{"ok":true,"ts":1779993119}
```

## [A/B] Auth enforced (live)

```
$ curl -X POST .../v1/brain/sync            (no Authorization)      -> HTTP 401
$ curl -X POST .../v1/brain/sync  -H "Authorization: Bearer notarealtoken"
                                                                    -> HTTP 401
```

## [C] POST /v1/brain/sync — one fragment + wiring, USER1

Request body:
```json
{"since_hlc":"","delta":{
  "fragments":[{"id":"frag-live-001","kind":"fact",
    "text":"Project BBC4 uses Revit 2025.","subject":"BBC4",
    "predicate":"uses","object":"Revit 2025",
    "hlc":"0000000000000001.aaaaaaaa"}],
  "wiring":[{"name":"revit","device_id":"dev-LIVE","kind":"mcp",
    "endpoint":"http://localhost:48884"}]}}
```

Response (HTTP 200):
```json
{"accepted":1,"rejected":[],"new_hlc":"0001779993141967.63229abd",
 "merged":{"fragments":[{"id":"frag-live-001","kind":"fact",
   "text":"Project BBC4 uses Revit 2025.","subject":"BBC4","predicate":"uses",
   "object":"Revit 2025","scope":"user","visibility":"private",
   "owner_user":"u_19e6fdbbbbe_37fb4d30a85e","confidence":"extracted",
   "hlc":"0000000000000001.aaaaaaaa","provenance":{},"extra":{}}],
  "wiring":[{"name":"revit","device_id":"dev-LIVE","kind":"mcp",
   "endpoint":"http://localhost:48884","status":"active"}],
  "new_hlc":"0001779993141967.63229abd"}}
```

## The on-disk proof — the fragment actually landed in the per-user sqlite

```
data/replicas/u_19e6fdbbbbe_37fb4d30a85e/brain.db

sqlite> SELECT id,kind,text,subject,predicate,object,owner_user,hlc,scope,visibility FROM fragments;
fragment rows: 1
{'id': 'frag-live-001', 'kind': 'fact', 'text': 'Project BBC4 uses Revit 2025.',
 'subject': 'BBC4', 'predicate': 'uses', 'object': 'Revit 2025',
 'owner_user': 'u_19e6fdbbbbe_37fb4d30a85e', 'hlc': '0000000000000001.aaaaaaaa',
 'scope': 'user', 'visibility': 'private'}

sqlite> SELECT name,device_id,kind,endpoint,status FROM wiring;
{'name': 'revit', 'device_id': 'dev-LIVE', 'kind': 'mcp',
 'endpoint': 'http://localhost:48884', 'status': 'active'}

sqlite> SELECT key,value FROM meta;
{'key': 'last_hlc', 'value': '0001779993141967.63229abd'}
```

The `owner_user` column was stamped server-side to USER1's id (the cloud never
trusts a client-supplied owner — `brain_replica.apply_delta` forces
`self.user_id`).

## [D] Second user → isolated replica (live)

USER2 POST `{"fragments":[{"id":"frag-USER2-only","text":"Firm-2 confidential note.","hlc":"...bbbbbbbb"}]}`
→ `accepted:1`, response `owner_user` = `u_19e6fdbbbca_d81f5efa761e`.

Two isolated directories on disk:
```
data/replicas/u_19e6fdbbbbe_37fb4d30a85e    (USER1)
data/replicas/u_19e6fdbbbca_d81f5efa761e    (USER2)
```
USER2's brain.db contains ONLY its own fragment:
```
{'id': 'frag-USER2-only', 'text': 'Firm-2 confidential note.',
 'object': None, 'owner_user': 'u_19e6fdbbbca_d81f5efa761e'}
```

## [E] Bare-secret delta REJECTED at the boundary (privacy guarantee, live)

USER1 POST with one safe reference + two bare secrets:
- `good-ref`  → `object: "op://vault/anthropic/key"`  (a reference — allowed)
- `bad-leak`  → `object: "sk-ant-1234567890abcdef"`   (bare secret)
- `bad-aws`   → `text:   "AKIAIOSFODNN7EXAMPLE"`        (bare secret)

Response (HTTP 200):
```json
{"accepted":1,
 "rejected":[
   {"id":"bad-leak","reason":"secret_blocked: object contains bare secret-like value"},
   {"id":"bad-aws","reason":"secret_blocked: text contains bare secret-like value"}],
 "new_hlc":"0001779993165261.b9b2d4ff", "merged":{...good-ref + frag-live-001...}}
```

The `op://` reference was accepted; both bare credentials were rejected with
`secret_blocked` reasons. Resolution stays on the user's machine — zero resolved
secrets persist in the cloud replica.

Disk audit — grep all replica DBs for `sk-ant` / `AKIA` / `sk_live_` / `ghp_`:
```
secret hits across all replica DBs: 0
```

## [F] Cross-user isolation (live)

USER1 read-back (empty delta) returns ONLY `frag-live-001` + `good-ref`.
`frag-USER2-only` is absent; neither bare secret appears.

## [G] DELETE /v1/brain/sync — GDPR erasure (live)

```
$ curl -X DELETE .../v1/brain/sync  -H "Authorization: Bearer <USER1 token>"
{"deleted":true,"user_id":"u_19e6fdbbbbe_37fb4d30a85e"}
```
On disk after erasure:
```
USER1 dir exists: False      <- physically removed
USER2 dir exists: True       <- erasure is per-user / isolated
remaining dirs: ['u_19e6fdbbbca_d81f5efa761e']
```

## [H] Erasure is idempotent (live)

```
$ curl -X DELETE .../v1/brain/sync  -H "Authorization: Bearer <USER1 token>"
{"deleted":false,"user_id":"u_19e6fdbbbbe_37fb4d30a85e"}
```

## Bugs found / fixed

None. The server stood up and the full round-trip passed on the first run; no
changes to `main.py` or `brain_replica.py` were required.

## Tests

```
$ python -m pytest tests/test_brain_sync_endpoint.py -q
7 passed, 2 warnings in 2.92s

$ python -m pytest tests/ -q
193 passed, 2 warnings in 49.69s
```
(The 2 warnings are a pre-existing FastAPI `on_event` deprecation, unrelated to
brain sync.)

## ANTI-LIE LIE-CHECK (brain-sync cloud database)

| Feature | Primitive | Runtime (process listens) | Live-verified (curl + sqlite) | Cross-user verified |
|---|---|---|---|---|
| POST /v1/brain/sync → per-user replica write | ✓ | ✓ uvicorn PID 59412 on :8788 | ✓ row shown in brain.db | ✓ |
| Per-user isolation | ✓ | ✓ | ✓ two dirs, no cross-leak | ✓ |
| Bare-secret rejection at boundary | ✓ | ✓ | ✓ rejected + 0 disk hits | ✓ |
| DELETE /v1/brain/sync → erasure | ✓ | ✓ | ✓ dir physically gone | ✓ |

Caveat (honest scope): the data plane is a passive per-user mirror. Real CRDT
federation transport / multi-device replay is still Slice 17 (as the
`brain_replica.py` banner states). What is verified live here is exactly the
shipped surface: authenticated delta apply → isolated sqlite persistence →
secret-rejection → erasure. The desktop client is not wired to call this
endpoint yet (no UI affordance pushes a delta) — so per DEFINITION-OF-SHIPPED
the *cloud server* is live-verified, while the *end-to-end desktop→cloud sync
button* remains "wired but not exposed."

## Repro

The server was launched with:
```
python -m uvicorn main:app --host 127.0.0.1 --port 8788   # cwd = cloud_backend/
```
Users/tokens minted via `db.get_or_create_user(email)` + `db.issue_token(id)`.
Transient artifacts (`archhub_cloud.db`, `data/replicas/`, `uvicorn.log`) are
gitignored / removed; they are not part of the commit.
