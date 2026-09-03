"""BrainReplica — per-user, server-side mirror of the desktop brain.

Track D, section 5 of `docs/CONTENT-ECOSYSTEM-2026-05-26.md`.

Privacy contract (BRAIN-FIRST mandate · 2026-05-25 · founder):
  ZERO resolved secrets are persisted in the cloud replica. The desktop
  brain stores `op://`, `wcm://`, `env://`, `inline:` REFERENCES only (per
  `app/resolver_registry.py`); this replica accepts those same prefixes and
  REJECTS any fragment whose `text`, `subject`, `object`, or extra payload
  looks like a bare credential. Resolution happens on the user's machine,
  never here.

Storage layout (per-scope, GDPR-ready) — SLICE 17 FANOUT:
  cloud_backend/data/replicas/<user_id>/brain.db        ← USER scope (private)
  cloud_backend/data/replicas/firm/<firm_key>/brain.db  ← FIRM scope (shared)
  cloud_backend/data/replicas/community/<cid>/brain.db  ← COMMUNITY (shared)

  * USER scope stays per-user (the `users.id` UUID from `cloud_backend/db.py`).
    `owner_user` is FORCED to the replica's user, so one person's private
    facts can never leak into another's private replica — this is the
    contract `TestPerUserIsolation` pins.
  * FIRM + COMMUNITY scope are SHARED replicas keyed by `firm_id` /
    `community_id`. Two devices that belong to the same firm/community push
    into the SAME shared db, so device B pulls device A's firm/community
    facts. Here `owner_user` is PRESERVED (the real contributing teammate),
    because the whole point is cross-device/cross-member convergence.

  Slice 17 = the FANOUT: a single device's `export_delta` returns its own
  USER rows MERGED with every firm/community replica it is a member of. The
  set of firm/community keys a caller may read is resolved server-side from
  their cloud account (company memberships) + the keys they push — never
  trusted blindly from the wire (see `BrainReplica.open(..., firm_keys=,
  community_keys=)` and `main.brain_sync`).

GDPR: deleting the per-user dir + revoking tokens erases the user's PRIVATE
state. Shared firm/community rows the user CONTRIBUTED are tombstoned by HLC
like any other fragment; the shared replica itself outlives any one member
(it is the firm's/community's, not the user's), mirroring how a shared Git
remote outlives one clone.

Design notes:
  * We intentionally do NOT `import personal_brain.storage.BrainStore`.
    Importing pulls a heavy transitive tree (Loro CRDT, FTS rebuilders,
    embedding workers) that doesn't belong in the cloud surface yet. The
    cloud replica is a sync endpoint — accept deltas, return merged deltas,
    track a `last_hlc` watermark per replica.
  * The HLC/CRDT merge is REUSED verbatim across all three scopes: the same
    `INSERT ... ON CONFLICT(id) DO UPDATE ... WHERE excluded.hlc >
    fragments.hlc` last-writer-wins rule makes every apply idempotent +
    commutative. No parallel sync engine is minted.
  * Schema is the subset of `personal-brain-mcp/src/personal_brain/storage.py`
    the cloud needs: `fragments`, `wiring`, plus a `meta` table storing the
    HLC watermark. No FTS, no skills tables.

ANTI-LIE disclosure: `apply_delta` / `export_delta` / the fanout are exercised
by `tests/test_brain_fanout.py` (2-user cross-device convergence + idempotent
merge) and wired into the live `/v1/brain/sync` FastAPI route in `main.py`.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Filesystem layout
# ---------------------------------------------------------------------------
# The replicas root is env-driven via config.REPLICAS_ROOT so the per-user
# brain.db files land on the Fly persistent volume (/data/replicas) in
# production and under cloud_backend/data/replicas locally — see
# config._default_replicas_root(). On Fly the ephemeral container FS is
# wiped on redeploy, so persisting replicas off the /data volume would lose
# every user's cloud brain. We fall back to the historical local path if
# config can't be imported (defensive — keeps this module importable on its
# own). Tests monkeypatch this module-level value directly.
_HERE = Path(__file__).resolve().parent
try:
    import config as _config
    DEFAULT_REPLICAS_ROOT = Path(_config.REPLICAS_ROOT)
except Exception:
    DEFAULT_REPLICAS_ROOT = _HERE / "data" / "replicas"


# Slice-17 fanout: shared replicas live under reserved subdirectories of the
# same root. `firm/` + `community/` can never collide with a per-user dir
# because a `users.id` is `u_...` (db._user_id) and path-traversal is rejected
# in open(); these literal names are not valid user_ids.
_FIRM_SUBDIR = "firm"
_COMMUNITY_SUBDIR = "community"

# Scopes that fan out to a SHARED replica (converge across devices/members)
# vs. the private per-user replica. USER (and PROJECT, until it gets its own
# fanout key) stay private-per-user.
_SHARED_SCOPES = frozenset({"firm", "community"})


def _safe_key(value: str) -> str:
    """Sanitise a firm/community key into a filesystem-safe directory name.

    Keys come from cloud company ids (`co_...`) or brain community ids
    (`comm-<slug>-<rand>`); both are already URL-safe, but we defend in depth
    so a hand-crafted delta can't traverse out of the replicas root. Returns
    a slug of `[A-Za-z0-9._-]`; empty / unsafe input raises ValueError so a
    bad key fails loudly instead of writing to the wrong place.
    """
    if not value or not isinstance(value, str):
        raise ValueError("scope key required")
    cleaned = "".join(
        c if (c.isalnum() or c in "._-") else "_" for c in value.strip()
    )
    cleaned = cleaned.strip("._-")
    if not cleaned or cleaned in (".", ".."):
        raise ValueError(f"unsafe scope key: {value!r}")
    return cleaned[:128]


def _community_key_of(fragment: dict) -> Optional[str]:
    """Resolve the COMMUNITY replica key for a fragment.

    Community fragments (from personal_brain.community_groups) carry their
    `community_id` in `extra.community_id`; some also stamp it on `firm_id`.
    Falls back to `subject` for the `community` record fragment itself
    (predicate=='community', subject==community_id). Returns None when no key
    can be found — caller drops the row from the community fanout rather than
    guessing.
    """
    extra = fragment.get("extra") or fragment.get("extra_json")
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    if isinstance(extra, dict):
        cid = extra.get("community_id")
        if cid:
            return str(cid)
    if fragment.get("firm_id"):
        return str(fragment["firm_id"])
    if fragment.get("predicate") == "community" and fragment.get("subject"):
        return str(fragment["subject"])
    return None


# Reference schemes accepted as "this is a SECRET REFERENCE, not a secret".
# Mirrors `app/resolver_registry.py` (Track D2 ResolverRegistry pattern).
_SAFE_REF_PREFIXES = ("op://", "wcm://", "env://", "inline:", "file://")

# Bare-string patterns that almost always indicate a leaked credential.
# We don't try to be exhaustive — we want clear false positives flagged at
# the API boundary so the desktop can re-encode + retry. Real PII redaction
# is Slice 7's job; this is the secrets-leak guard.
_SECRET_LIKE_PREFIXES = (
    "sk-",            # Anthropic / OpenAI
    "sk_live_",       # Stripe / ArchHub bearer (also our own token format!)
    "sk_test_",
    "rk_live_",
    "AKIA",           # AWS access key
    "AIza",           # Google API key
    "ghp_",           # GitHub personal access token
    "xoxb-",          # Slack bot
)


# ---------------------------------------------------------------------------
# Schema — subset of personal_brain.storage that the cloud needs
# ---------------------------------------------------------------------------
_SCHEMA = """
CREATE TABLE IF NOT EXISTS fragments (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    subject TEXT,
    predicate TEXT,
    object TEXT,
    scope TEXT NOT NULL DEFAULT 'user',
    visibility TEXT NOT NULL DEFAULT 'private',
    owner_user TEXT NOT NULL,
    project_id TEXT,
    firm_id TEXT,
    confidence TEXT NOT NULL DEFAULT 'extracted',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    valid_from TEXT,
    valid_until TEXT,
    extra_json TEXT,
    hlc TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_fragments_hlc ON fragments(hlc);
CREATE INDEX IF NOT EXISTS idx_fragments_kind ON fragments(kind, scope);

CREATE TABLE IF NOT EXISTS wiring (
    name TEXT NOT NULL,
    device_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    endpoint TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    last_seen TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (name, device_id)
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _hlc_now() -> str:
    """Hybrid Logical Clock — millisecond timestamp + monotonic counter.

    Cloud-side we don't have a real Loro CRDT clock yet (Slice 17), so we
    issue a tick that's lexicographically ordered + collision-resistant.
    Format: `<unix_ms_zfill16>.<random_hex8>`."""
    import secrets as _secrets
    return f"{int(time.time() * 1000):016d}.{_secrets.token_hex(4)}"


# Comprehensive secret-token detector, matched ANYWHERE (re.search) -- NOT
# startswith -- so an embedded secret in a sentence ("the key is AIza... ok") is
# caught. Defense-in-depth parity with the daemon's PersonalCloudSync detector;
# the old startswith-only gate let embedded Google(AIza)/Slack(xoxb-)/Stripe
# (rk_live_) keys through (founder 2026-06-02). The leading lookbehind anchors
# the prefix at a non-alnum boundary so ordinary hyphenated text ("task-12345678")
# does not false-positive. op:// / wcm:// / env:// refs are stripped first.
import re as _re

_REF_TOKEN_RE = _re.compile(
    r"\b(?:op|wcm|env)://[^\s\"'<>]+|\binline:[^\s\"'<>]+|\bfile://[^\s\"'<>]+"
)
_SECRET_TOKEN_RE = _re.compile(
    r"(?<![A-Za-z0-9_\-])"
    r"(?:(?:sk-|sk_live_|sk_test_|rk_live_|rk_test_|AKIA|AIza|gh[pousr]_|xox[bpars]-)"
    r"[A-Za-z0-9_\-]{8,}"
    r"|ya29\.[A-Za-z0-9_\-]{6,}"
    r"|eyJ[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,})"
)


def _is_secret_like(value: Any) -> bool:
    """True if `value` carries a bare credential ANYWHERE in it.

    A literal `op://...` / `wcm://...` reference is SAFE (resolution happens on
    the user's machine). A bare `sk-ant-...` / `AIza...` / `xoxb-...` is NOT --
    that's a resolved secret leaking into the cloud (BRAIN-FIRST + ANTI-LIE).
    Searches anywhere (not just the field start) so an EMBEDDED secret is
    caught; safe op:// references are stripped first so they never match.
    """
    if not isinstance(value, str):
        return False
    s = value.strip()
    if not s:
        return False
    stripped = _REF_TOKEN_RE.sub(" ", s)
    return bool(_SECRET_TOKEN_RE.search(stripped))


def _is_secret_anywhere(obj: Any) -> bool:
    """Recursively scan a value (str / dict / list) for a bare secret."""
    if isinstance(obj, str):
        return _is_secret_like(obj)
    if isinstance(obj, dict):
        return any(_is_secret_anywhere(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return any(_is_secret_anywhere(v) for v in obj)
    return False


def _fragment_has_secret(fragment: dict) -> Optional[str]:
    """Return the reason if the fragment carries a bare secret value, else
    None. Scans the top-level string fields + (recursively) the extras."""
    for field in ("text", "subject", "object", "predicate"):
        if _is_secret_like(fragment.get(field)):
            return f"{field} contains bare secret-like value"
    extra = fragment.get("extra")
    if extra is None:
        extra = fragment.get("extra_json")
    if _is_secret_anywhere(extra):
        return "extra contains bare secret-like value"
    return None


# ---------------------------------------------------------------------------
# BrainReplica
# ---------------------------------------------------------------------------
class BrainReplica:
    """Per-user server-side brain.db mirror.

    Usage::

        replica = BrainReplica.open(user_id="abc-123")
        merge_result = replica.apply_delta({
            "fragments": [...],
            "wiring": [...],
        })
        delta = replica.export_delta(since_hlc="0000000000000000.00000000")
        BrainReplica.delete(user_id="abc-123")   # GDPR
    """

    def __init__(self, user_id: str, db_path: Path,
                 *, root: Optional[Path] = None,
                 owner_force: bool = True,
                 firm_keys: Optional[list[str]] = None,
                 community_keys: Optional[list[str]] = None):
        self.user_id = user_id
        self.db_path = db_path
        self.root = root or DEFAULT_REPLICAS_ROOT
        # When True (the per-user replica) every applied row's owner_user is
        # forced to this replica's user — privacy isolation. Shared firm /
        # community replicas open with owner_force=False so the real
        # contributing teammate is preserved across devices.
        self.owner_force = owner_force
        # The firm / community replica keys this caller is ALLOWED to read on
        # export. Resolved server-side (company membership + pushed keys);
        # the fanout export unions these shared replicas into the result.
        self.firm_keys = list(firm_keys or [])
        self.community_keys = list(community_keys or [])
        self._connect_kw = {"check_same_thread": False}

    # -- factory + lifecycle ----------------------------------------------
    @classmethod
    def open(cls, user_id: str,
             root: Optional[Path] = None,
             *,
             firm_keys: Optional[list[str]] = None,
             community_keys: Optional[list[str]] = None) -> "BrainReplica":
        """Open (creating if needed) the per-user (USER-scope) replica.

        `firm_keys` / `community_keys` are the shared-replica keys this caller
        may read on `export_delta` (Slice-17 fanout). They are resolved by the
        caller (main.brain_sync) from the user's cloud account + the scopes
        they push — NOT trusted blindly from the wire. Omitting them keeps the
        legacy self-replica-only behaviour (backwards compatible)."""
        if not user_id or not isinstance(user_id, str):
            raise ValueError("user_id required (must be the cloud_backend.db.users.id)")
        # Defence in depth: refuse path-traversal in user_id.
        if "/" in user_id or "\\" in user_id or ".." in user_id:
            raise ValueError(f"unsafe user_id: {user_id!r}")
        root = root or DEFAULT_REPLICAS_ROOT
        user_dir = root / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        db_path = user_dir / "brain.db"
        replica = cls(user_id=user_id, db_path=db_path, root=root,
                      owner_force=True,
                      firm_keys=firm_keys, community_keys=community_keys)
        replica._ensure_schema()
        return replica

    @classmethod
    def open_shared(cls, scope: str, key: str,
                    root: Optional[Path] = None) -> "BrainReplica":
        """Open (creating if needed) a SHARED firm/community replica.

        `scope` is 'firm' or 'community'; `key` is the firm_id / community_id.
        Shared replicas live under `<root>/<scope>/<key>/brain.db` and open
        with `owner_force=False` so the contributing teammate's owner_user is
        preserved (cross-device convergence is the whole point). `user_id` is
        recorded as the synthetic `<scope>:<key>` for logging only — it is
        never written onto rows (owner_force is off)."""
        if scope == "firm":
            sub = _FIRM_SUBDIR
        elif scope == "community":
            sub = _COMMUNITY_SUBDIR
        else:
            raise ValueError(f"shared scope must be firm|community, got {scope!r}")
        safe = _safe_key(key)
        root = root or DEFAULT_REPLICAS_ROOT
        shared_dir = root / sub / safe
        shared_dir.mkdir(parents=True, exist_ok=True)
        db_path = shared_dir / "brain.db"
        replica = cls(user_id=f"{scope}:{safe}", db_path=db_path, root=root,
                      owner_force=False)
        replica._ensure_schema()
        return replica

    @classmethod
    def delete(cls, user_id: str,
               root: Optional[Path] = None) -> bool:
        """GDPR right-to-erasure: remove the user's entire replica directory.

        Returns True if a directory existed + was removed, False otherwise.
        Token revocation is the caller's responsibility (db.delete_tokens_for_user
        in cloud_backend/db.py, when that ships).

        Implementation note: on Windows, sqlite holds file locks until the
        owning connection is closed. We force-GC any lingering connections
        + retry rmtree once with a small backoff before giving up — this
        mirrors how `app/memory/graph.py` handles the same OS-level quirk.
        """
        root = root or DEFAULT_REPLICAS_ROOT
        user_dir = root / user_id
        if not user_dir.exists():
            return False
        import gc, time as _t
        # First pass: clear any lingering sqlite connections held by tests
        # / dev sessions on the same path.
        gc.collect()
        last_err: Optional[Exception] = None
        for attempt in range(5):
            try:
                shutil.rmtree(user_dir, ignore_errors=False)
                return True
            except PermissionError as ex:
                last_err = ex
                gc.collect()
                _t.sleep(0.05 * (attempt + 1))
        # Final fallback: best-effort ignore_errors to satisfy GDPR's
        # "right to erasure" intent even if a stray lock survives. We log
        # via stderr so ops sees the leak.
        import sys as _sys
        print(f"BrainReplica.delete: forced removal of {user_dir} after "
              f"locked retries (last error: {last_err})", file=_sys.stderr)
        shutil.rmtree(user_dir, ignore_errors=True)
        return not user_dir.exists()

    # -- schema -----------------------------------------------------------
    def _ensure_schema(self) -> None:
        with sqlite3.connect(self.db_path, **self._connect_kw) as con:
            con.executescript(_SCHEMA)
            con.commit()

    def _conn(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, **self._connect_kw)
        con.row_factory = sqlite3.Row
        return con

    # -- HLC watermark ----------------------------------------------------
    def last_hlc(self) -> str:
        with self._conn() as con:
            r = con.execute("SELECT value FROM meta WHERE key = 'last_hlc'").fetchone()
            return r["value"] if r else "0000000000000000.00000000"

    def _set_last_hlc(self, hlc: str) -> None:
        with self._conn() as con:
            con.execute(
                "INSERT INTO meta (key, value) VALUES ('last_hlc', ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (hlc,),
            )
            con.commit()

    # -- durable shared-scope read-set (Slice-17 fanout) ------------------
    # The user's OWN replica remembers which firm/community shared replicas it
    # has contributed to, so a LATER empty pull still unions them — device A's
    # firm/community facts remain visible to device A (and to A's other
    # devices) across sessions, not only on the request that pushed them.
    # Company-membership firm keys are resolved fresh server-side each call;
    # THIS set additionally captures keys a member contributed to (e.g. a
    # community joined by code, which the cloud has no membership table for).
    def _get_key_set(self, meta_key: str) -> list[str]:
        with self._conn() as con:
            r = con.execute("SELECT value FROM meta WHERE key = ?",
                            (meta_key,)).fetchone()
        if not r or not r["value"]:
            return []
        try:
            v = json.loads(r["value"])
            return [str(k) for k in v] if isinstance(v, list) else []
        except Exception:
            return []

    def _add_to_key_set(self, meta_key: str, keys: list[str]) -> None:
        if not keys:
            return
        merged = sorted(set(self._get_key_set(meta_key)) | {str(k) for k in keys})
        with self._conn() as con:
            con.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (meta_key, json.dumps(merged)),
            )
            con.commit()

    def contributed_firm_keys(self) -> list[str]:
        return self._get_key_set("contributed_firm_keys")

    def contributed_community_keys(self) -> list[str]:
        return self._get_key_set("contributed_community_keys")

    # -- single-fragment CRUD (the unified /v1/memory backing) ------------
    # These let db.py treat the replica `fragments` table as the ONE
    # canonical per-user fact store (cloud-brain-unify 2026-05-31). A
    # "memory fact" is just a fragment; the /v1/memory DAO writes here so a
    # fact added via /v1/memory and a fragment synced via /v1/brain/sync
    # land in the SAME table. Secret-leak gate still applies on write.
    def get_fragment(self, frag_id: str) -> Optional[dict]:
        """Return one fragment by its TEXT id (decoded provenance/extra),
        or None. Includes the implicit sqlite rowid as `_rowid`."""
        with self._conn() as con:
            r = con.execute(
                "SELECT rowid AS _rowid, id, kind, text, subject, predicate,"
                " object, scope, visibility, owner_user, project_id, firm_id,"
                " confidence, provenance_json, valid_from, valid_until,"
                " extra_json, hlc, created_at, updated_at"
                " FROM fragments WHERE id = ?",
                (frag_id,),
            ).fetchone()
        if r is None:
            return None
        d = dict(r)
        d["provenance"] = json.loads(d.pop("provenance_json") or "{}")
        d["extra"] = json.loads(d.pop("extra_json") or "{}")
        return d

    def upsert_fragment(self, fragment: dict) -> dict:
        """Insert (or update-on-conflict) a single fragment, forcing
        owner_user to this replica's user. Returns {id, rowid, hlc}.

        Used by the /v1/memory DAO: a fact is a fragment. The same
        secret-leak gate as apply_delta runs so /v1/memory cannot smuggle a
        bare credential past the privacy contract either.

        If `id` is omitted, a fresh fragment is created and its stable id is
        derived from the sqlite rowid as `mf-<rowid>` (the memory-fact
        namespace) so the public integer fact-id the API exposes round-trips
        1:1 with a fragment.
        """
        if not isinstance(fragment, dict):
            raise ValueError("fragment must be an object")
        reason = _fragment_has_secret(fragment)
        if reason:
            raise ValueError(f"secret_blocked: {reason}")
        hlc = fragment.get("hlc") or _hlc_now()
        fid = fragment.get("id")
        with self._conn() as con:
            if not fid:
                # Create with a temporary unique id, then rename to the
                # rowid-derived stable id so the API's integer fact-id and
                # the fragment id are one mapping.
                import secrets as _secrets
                tmp = f"mf-tmp-{_secrets.token_hex(8)}"
                cur = con.execute(
                    "INSERT INTO fragments"
                    " (id, kind, text, subject, predicate, object,"
                    "  scope, visibility, owner_user, project_id, firm_id,"
                    "  confidence, provenance_json, valid_from, valid_until,"
                    "  extra_json, hlc)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        tmp,
                        fragment.get("kind") or "fact",
                        fragment.get("text") or "",
                        fragment.get("subject"),
                        fragment.get("predicate"),
                        fragment.get("object"),
                        fragment.get("scope") or "user",
                        fragment.get("visibility") or "private",
                        self.user_id,
                        fragment.get("project_id"),
                        fragment.get("firm_id"),
                        fragment.get("confidence") or "extracted",
                        json.dumps(fragment.get("provenance") or {}),
                        fragment.get("valid_from"),
                        fragment.get("valid_until"),
                        json.dumps(fragment.get("extra") or {}),
                        hlc,
                    ),
                )
                rowid = int(cur.lastrowid or 0)
                fid = f"mf-{rowid}"
                con.execute("UPDATE fragments SET id = ? WHERE rowid = ?",
                            (fid, rowid))
                con.commit()
            else:
                con.execute(
                    "INSERT INTO fragments"
                    " (id, kind, text, subject, predicate, object,"
                    "  scope, visibility, owner_user, project_id, firm_id,"
                    "  confidence, provenance_json, valid_from, valid_until,"
                    "  extra_json, hlc)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(id) DO UPDATE SET"
                    "   kind = excluded.kind,"
                    "   text = excluded.text,"
                    "   subject = excluded.subject,"
                    "   predicate = excluded.predicate,"
                    "   object = excluded.object,"
                    "   scope = excluded.scope,"
                    "   visibility = excluded.visibility,"
                    "   project_id = excluded.project_id,"
                    "   firm_id = excluded.firm_id,"
                    "   confidence = excluded.confidence,"
                    "   provenance_json = excluded.provenance_json,"
                    "   valid_from = excluded.valid_from,"
                    "   valid_until = excluded.valid_until,"
                    "   extra_json = excluded.extra_json,"
                    "   hlc = excluded.hlc,"
                    "   updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                    (
                        fid,
                        fragment.get("kind") or "fact",
                        fragment.get("text") or "",
                        fragment.get("subject"),
                        fragment.get("predicate"),
                        fragment.get("object"),
                        fragment.get("scope") or "user",
                        fragment.get("visibility") or "private",
                        self.user_id,
                        fragment.get("project_id"),
                        fragment.get("firm_id"),
                        fragment.get("confidence") or "extracted",
                        json.dumps(fragment.get("provenance") or {}),
                        fragment.get("valid_from"),
                        fragment.get("valid_until"),
                        json.dumps(fragment.get("extra") or {}),
                        hlc,
                    ),
                )
                r = con.execute(
                    "SELECT rowid AS rid FROM fragments WHERE id = ?",
                    (fid,)).fetchone()
                rowid = int(r["rid"]) if r else 0
                con.commit()
        # Advance the watermark so the next /v1/brain/sync export surfaces
        # this fact to the user's other devices (both APIs, one store).
        if hlc > self.last_hlc():
            self._set_last_hlc(hlc)
        return {"id": fid, "rowid": rowid, "hlc": hlc}

    def patch_fragment(self, frag_id: str, **fields) -> bool:
        """Update selected columns of one fragment in place. Recognised
        keys: text, subject, predicate, object, scope, visibility,
        confidence, valid_until, extra (dict, replaces), hlc. Returns True
        if a row was touched. owner_user is never patchable (cloud never
        accepts a cross-user rewrite via this path)."""
        existing = self.get_fragment(frag_id)
        if existing is None:
            return False
        col_map = {
            "text": "text", "subject": "subject", "predicate": "predicate",
            "object": "object", "scope": "scope", "visibility": "visibility",
            "confidence": "confidence", "valid_until": "valid_until",
        }
        sets: list[str] = []
        params: list = []
        for k, col in col_map.items():
            if k in fields and fields[k] is not None:
                # Re-run the secret gate on any text-ish field being set.
                if k in ("text", "subject", "object", "predicate") and \
                        _is_secret_like(fields[k]):
                    raise ValueError(
                        f"secret_blocked: {k} contains bare secret-like value")
                sets.append(f"{col} = ?")
                params.append(fields[k])
        if "extra" in fields and isinstance(fields["extra"], dict):
            sets.append("extra_json = ?")
            params.append(json.dumps(fields["extra"]))
        hlc = fields.get("hlc") or _hlc_now()
        sets.append("hlc = ?")
        params.append(hlc)
        sets.append("updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
        params.append(frag_id)
        with self._conn() as con:
            con.execute(
                f"UPDATE fragments SET {', '.join(sets)} WHERE id = ?",
                tuple(params),
            )
            con.commit()
        if hlc > self.last_hlc():
            self._set_last_hlc(hlc)
        return True

    def list_fragments(self, *, kind: Optional[str] = None,
                       include_invalid: bool = False,
                       limit: int = 200) -> list[dict]:
        """List fragments (newest-updated first), decoded. `kind` filters
        (memory facts are kind='fact'); include_invalid keeps tombstoned
        (valid_until set) rows."""
        where: list[str] = []
        params: list = []
        if kind:
            where.append("kind = ?")
            params.append(kind)
        if not include_invalid:
            where.append("valid_until IS NULL")
        sql = (
            "SELECT rowid AS _rowid, id, kind, text, subject, predicate,"
            " object, scope, visibility, owner_user, project_id, firm_id,"
            " confidence, provenance_json, valid_from, valid_until,"
            " extra_json, hlc, created_at, updated_at FROM fragments"
        )
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC, rowid DESC LIMIT ?"
        params.append(int(limit))
        with self._conn() as con:
            rows = con.execute(sql, tuple(params)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["provenance"] = json.loads(d.pop("provenance_json") or "{}")
            d["extra"] = json.loads(d.pop("extra_json") or "{}")
            out.append(d)
        return out

    # -- apply / export ---------------------------------------------------
    def _write_fragment_row(self, con: sqlite3.Connection,
                            frag: dict, hlc: str) -> None:
        """Idempotent HLC/CRDT upsert of one fragment into THIS replica.

        The merge rule is the reuse point (scope.reuse): last-writer-wins by
        HLC via `ON CONFLICT(id) DO UPDATE ... WHERE excluded.hlc >
        fragments.hlc`. Re-applying the same row is a no-op (idempotent); two
        devices applying in any order converge (commutative).

        `owner_user`: forced to this replica's user when `owner_force` (the
        private per-user replica) so a person's USER facts can't be attributed
        to someone else; PRESERVED from the wire on shared firm/community
        replicas so the real contributing teammate survives cross-device.
        """
        owner = self.user_id if self.owner_force else (
            frag.get("owner_user") or self.user_id)
        con.execute(
            "INSERT INTO fragments"
            " (id, kind, text, subject, predicate, object,"
            "  scope, visibility, owner_user,"
            "  project_id, firm_id, confidence,"
            "  provenance_json, valid_from, valid_until,"
            "  extra_json, hlc)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET"
            "   text = excluded.text,"
            "   subject = excluded.subject,"
            "   predicate = excluded.predicate,"
            "   object = excluded.object,"
            "   scope = excluded.scope,"
            "   visibility = excluded.visibility,"
            "   owner_user = excluded.owner_user,"
            "   confidence = excluded.confidence,"
            "   provenance_json = excluded.provenance_json,"
            "   valid_from = excluded.valid_from,"
            "   valid_until = excluded.valid_until,"
            "   extra_json = excluded.extra_json,"
            "   hlc = excluded.hlc,"
            "   updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
            " WHERE excluded.hlc > fragments.hlc",
            (
                frag.get("id"),
                frag.get("kind") or "fact",
                frag.get("text") or "",
                frag.get("subject"),
                frag.get("predicate"),
                frag.get("object"),
                frag.get("scope") or "user",
                frag.get("visibility") or "private",
                owner,
                frag.get("project_id"),
                frag.get("firm_id"),
                frag.get("confidence") or "extracted",
                json.dumps(frag.get("provenance") or {}),
                frag.get("valid_from"),
                frag.get("valid_until"),
                json.dumps(frag.get("extra") or {}),
                hlc,
            ),
        )

    def apply_delta(self, delta: dict) -> dict:
        """Merge a delta from the desktop brain — with Slice-17 scope fanout.

        delta = {
            "fragments": [ {id, kind, text, subject, predicate, object,
                            scope, visibility, owner_user, hlc, extra},
                           ... ],
            "wiring":    [ {name, device_id, kind, endpoint, status}, ... ],
            "since_hlc": optional cursor the caller had locally
        }

        Routing (only on the private per-user replica, owner_force=True):
          * scope == 'user'/'project' → THIS user's private replica.
          * scope == 'firm'           → shared firm replica keyed by firm_id.
          * scope == 'community'      → shared community replica keyed by the
                                        fragment's community_id.
        Shared replicas reuse the SAME idempotent HLC merge. The set of shared
        keys this delta touched is returned as `firm_keys` / `community_keys`
        so the caller's `export_delta` can union them back (device B then sees
        device A's firm/community facts).

        On a shared replica (owner_force=False) every fragment lands locally —
        no further routing — so the recursion bottoms out.

        Returns {"accepted", "rejected", "new_hlc", "firm_keys",
                 "community_keys"}.
        """
        if not isinstance(delta, dict):
            raise ValueError("delta must be a JSON object")
        fragments = list(delta.get("fragments") or [])
        wiring = list(delta.get("wiring") or [])
        if not isinstance(fragments, list):
            raise ValueError("delta.fragments must be a list")
        if not isinstance(wiring, list):
            raise ValueError("delta.wiring must be a list")

        accepted = 0
        rejected: list[dict] = []
        max_hlc = self.last_hlc()
        new_hlc = _hlc_now()

        # Shared-scope rows are partitioned out and applied to their shared
        # replicas after the local write batch (separate sqlite files).
        firm_routes: dict[str, list[dict]] = {}
        community_routes: dict[str, list[dict]] = {}
        touched_firm_keys: set[str] = set()
        touched_community_keys: set[str] = set()

        with self._conn() as con:
            for frag in fragments:
                if not isinstance(frag, dict):
                    rejected.append({"id": None, "reason": "not an object"})
                    continue
                # Privacy gate — reject anything carrying a bare secret.
                reason = _fragment_has_secret(frag)
                if reason:
                    rejected.append({"id": frag.get("id"),
                                     "reason": f"secret_blocked: {reason}"})
                    continue
                fid = frag.get("id")
                if not fid:
                    rejected.append({"id": None, "reason": "missing id"})
                    continue
                hlc = frag.get("hlc") or new_hlc
                scope = (frag.get("scope") or "user").strip().lower()

                # Slice-17 routing: on the private replica, firm/community
                # rows go to their SHARED replica instead of this user's db.
                if self.owner_force and scope in _SHARED_SCOPES:
                    if scope == "firm":
                        key = frag.get("firm_id")
                        if not key:
                            rejected.append({
                                "id": fid,
                                "reason": "firm scope fragment missing firm_id"})
                            continue
                        firm_routes.setdefault(str(key), []).append(frag)
                    else:  # community
                        key = _community_key_of(frag)
                        if not key:
                            rejected.append({
                                "id": fid,
                                "reason": "community fragment missing community_id"})
                            continue
                        community_routes.setdefault(str(key), []).append(frag)
                    if hlc > max_hlc:
                        max_hlc = hlc
                    accepted += 1
                    continue

                # USER / PROJECT (or any scope on a shared replica) → here.
                if hlc > max_hlc:
                    max_hlc = hlc
                self._write_fragment_row(con, frag, hlc)
                accepted += 1

            # Wiring is small + safe — no secret scan needed (names + URLs
            # only, never tokens). Wiring is per-device, kept on the user db.
            for w in wiring:
                if not isinstance(w, dict):
                    continue
                if not (w.get("name") and w.get("device_id")):
                    continue
                con.execute(
                    "INSERT INTO wiring"
                    " (name, device_id, kind, endpoint, status, last_seen)"
                    " VALUES (?,?,?,?,?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))"
                    " ON CONFLICT(name, device_id) DO UPDATE SET"
                    "   kind = excluded.kind,"
                    "   endpoint = excluded.endpoint,"
                    "   status = excluded.status,"
                    "   last_seen = excluded.last_seen",
                    (w["name"], w["device_id"],
                     w.get("kind") or "mcp",
                     w.get("endpoint") or "",
                     w.get("status") or "active"),
                )
            con.commit()

        # Apply the partitioned shared-scope rows to their shared replicas.
        # Each is an independent sqlite file using the SAME HLC merge.
        for key, frags in firm_routes.items():
            try:
                shared = BrainReplica.open_shared("firm", key, root=self.root)
                shared.apply_delta({"fragments": frags})
                touched_firm_keys.add(_safe_key(key))
            except ValueError as ex:
                for f in frags:
                    rejected.append({"id": f.get("id"),
                                     "reason": f"firm route failed: {ex}"})
                    accepted -= 1
        for key, frags in community_routes.items():
            try:
                shared = BrainReplica.open_shared("community", key, root=self.root)
                shared.apply_delta({"fragments": frags})
                touched_community_keys.add(_safe_key(key))
            except ValueError as ex:
                for f in frags:
                    rejected.append({"id": f.get("id"),
                                     "reason": f"community route failed: {ex}"})
                    accepted -= 1

        self._set_last_hlc(max_hlc if max_hlc > new_hlc else new_hlc)
        # Durably remember the shared keys this user contributed to, so future
        # (even empty) pulls keep unioning them — cross-session persistence of
        # the fanout read-set.
        if self.owner_force:
            self._add_to_key_set("contributed_firm_keys", sorted(touched_firm_keys))
            self._add_to_key_set("contributed_community_keys",
                                 sorted(touched_community_keys))
        return {
            "accepted": accepted,
            "rejected": rejected,
            "new_hlc": self.last_hlc(),
            # Keys this delta contributed to — the caller adds them to the
            # read-set so the very same sync round-trips firm/community facts.
            "firm_keys": sorted(touched_firm_keys),
            "community_keys": sorted(touched_community_keys),
        }

    def _own_fragments(self, since: str) -> list[dict]:
        """Rows from THIS replica's db with hlc > since (decoded)."""
        with self._conn() as con:
            frag_rows = con.execute(
                "SELECT id, kind, text, subject, predicate, object,"
                " scope, visibility, owner_user, project_id, firm_id,"
                " confidence, provenance_json, valid_from, valid_until,"
                " extra_json, hlc, created_at, updated_at"
                " FROM fragments WHERE hlc > ? ORDER BY hlc ASC",
                (since,),
            ).fetchall()
        out: list[dict] = []
        for r in frag_rows:
            d = dict(r)
            d["provenance"] = json.loads(d.pop("provenance_json") or "{}")
            d["extra"] = json.loads(d.pop("extra_json") or "{}")
            out.append(d)
        return out

    def export_delta(self, since_hlc: str = "") -> dict:
        """Return the caller's MERGED brain delta — the Slice-17 fanout read.

        Unions, with hlc > since_hlc:
          * this user's OWN replica (USER + PROJECT scope, private), PLUS
          * every shared FIRM replica in `self.firm_keys`, PLUS
          * every shared COMMUNITY replica in `self.community_keys`.

        So a SECOND device of the same user (same firm_keys) — or a DIFFERENT
        teammate in the same firm/community — pulls the firm/community facts
        the first device pushed, while USER-scope rows stay private to each
        user's own replica. The read-set (firm_keys/community_keys) is set by
        the caller from the account's memberships + the keys just pushed; this
        method never widens it.

        Duplicate ids across replicas (shouldn't happen — user vs shared dbs
        are disjoint by scope) are de-duped last-writer-wins by HLC so the
        union itself stays idempotent.
        """
        since = since_hlc or "0000000000000000.00000000"
        # de-dupe by id, keeping the highest HLC (commutative union).
        by_id: dict[str, dict] = {}

        def _absorb(rows: list[dict]) -> None:
            for d in rows:
                fid = d.get("id")
                if not fid:
                    continue
                prev = by_id.get(fid)
                if prev is None or (d.get("hlc") or "") > (prev.get("hlc") or ""):
                    by_id[fid] = d

        _absorb(self._own_fragments(since))

        for key in self.firm_keys:
            try:
                shared = BrainReplica.open_shared("firm", key, root=self.root)
                _absorb(shared._own_fragments(since))
            except ValueError:
                continue  # unsafe/empty key — skip, never crash the export
        for key in self.community_keys:
            try:
                shared = BrainReplica.open_shared("community", key, root=self.root)
                _absorb(shared._own_fragments(since))
            except ValueError:
                continue

        fragments = sorted(by_id.values(), key=lambda d: d.get("hlc") or "")

        # Wiring stays per-device on the user's own replica.
        with self._conn() as con:
            wiring_rows = con.execute(
                "SELECT name, device_id, kind, endpoint, status, last_seen"
                " FROM wiring"
            ).fetchall()
        wiring = [dict(r) for r in wiring_rows]
        return {
            "fragments": fragments,
            "wiring": wiring,
            "new_hlc": self.last_hlc(),
        }
