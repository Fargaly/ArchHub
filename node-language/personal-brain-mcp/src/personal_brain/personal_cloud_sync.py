"""Personal (USER-scope) cross-device brain sync through the ArchHub cloud.

Sibling to `sync_worker.SyncWorker` (which handles FIRM / PROJECT / COMMUNITY
CRDT sync over a local Transport). This worker is the PERSONAL path: it
converges the signed-in user's USER-scope fragments + skills across THEIR
devices through the EXISTING deployed cloud (`POST {cloud_base}/v1/brain/sync`),
per-user, private.

Why a sibling and not a SyncWorker scope add:
  * SyncWorker speaks the snapshot/Transport contract (push whole snapshot,
    pull whole snapshot, merge by `provenance.hlc` int). The cloud
    `/v1/brain/sync` speaks a DELTA contract (`{since_hlc, delta:{fragments,
    wiring}}` → `{accepted, rejected, new_hlc, merged}`) with a STRING hlc
    cursor. Different wire shape → a clean, isolated worker keeps the firm
    sync contract untouched (ADDITIVE mandate).
  * USER scope is private. The cloud keeps it in a per-user replica keyed on
    the token's user_id — never fanned out. The token IS the identity; we
    never send another user's data.

Privacy (HARD requirement — secrets NEVER leave):
  Every outbound fragment is routed through `redaction.redact_fragment` with a
  SECRET-ONLY redactor (`HeuristicRedactor(redact_proper_names=False)`), then
  re-checked against the same bare-secret prefixes the cloud rejects. A
  fragment that still carries a bare secret after redaction is DROPPED from the
  push (never sent). Only `op://` / `wcm://` / `env://` references survive — the
  resolved value stays on this machine. See `_sanitize_outbound`.

Resilience (HARD requirement — never crash, never block):
  No token → INERT (every tick is a logged no-op). Any network / HTTP / parse
  failure → that tick degrades to local-only, increments an error counter, and
  returns; the daemon keeps running. Uses urllib from the stdlib so there is no
  new dependency and no import-time failure.

Idempotency:
  A `since_hlc` cursor (cloud's string HLC) is persisted in brain_meta. Each
  tick pushes only what's new, applies the merged response, and advances the
  cursor to the cloud's `new_hlc`. Re-applying the same merged rows is a no-op
  because the local store upserts by id and we skip rows we already own.

Public surface (mirrors SyncWorker so the supervisor treats it uniformly):
    from personal_brain.personal_cloud_sync import PersonalCloudSync
    w = PersonalCloudSync(store, owner_user="<cloud user_id>")
    w.start(); w.tick(); w.stop(); w.status()
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .cloud_config import CloudConfig, load_cloud_config
from .models import (
    Confidence,
    Fragment,
    FragmentKind,
    Provenance,
    Scope,
    Skill,
    Visibility,
)
from . import redaction as _redaction
from .storage import BrainStore, _max_dt, _parse_iso


# ─────────────────────── brain_meta keys ────────────────────────────────

_META_SINCE_HLC = "personal_cloud_sync.since_hlc"
_META_LAST_SYNC = "personal_cloud_sync.last_sync_ts"
_META_LAST_RESULT = "personal_cloud_sync.last_result_json"
_META_ERRORS = "personal_cloud_sync.error_count"
# Set to the HTTP status (e.g. "401") when the SERVER verified our bearer and
# REJECTED it — i.e. db.user_for_token returned None (revoked / expired /
# unknown token). Its presence makes the worker INERT (it stops hammering the
# cloud with a dead token every interval) and is the signal the UI/CLI reads
# to prompt a fresh sign-in. Cleared the moment a tick succeeds again (e.g.
# after the user re-runs cloud_login and a new token lands) OR when the token
# itself changes (a new sign-in supersedes a stale rejection).
_META_AUTH_INVALID = "personal_cloud_sync.auth_invalid"
# Records WHICH token was rejected (fingerprint, never the raw secret) so a
# fresh sign-in with a DIFFERENT token clears the inert latch automatically —
# the rejection was about the old token, not the new one.
_META_AUTH_INVALID_TOKEN = "personal_cloud_sync.auth_invalid_token_fp"

# HTTP statuses that mean "the server VERIFIED this token and REJECTED it"
# (vs. a transient network / 5xx blip that should just be retried). 401 =
# missing/invalid/expired bearer (db.user_for_token → None); 403 = the token
# authenticated but is forbidden. Both are token-identity verdicts, not
# transient — retrying with the SAME token can never succeed, so we honor the
# server's verdict and go inert rather than spin forever.
_AUTH_REJECT_STATUSES = frozenset({401, 403})

# Default cursor the cloud replica understands (export_delta floor).
_HLC_FLOOR = "0000000000000000.00000000"

# Bare-secret prefixes that must NEVER cross to the cloud. Mirrors the cloud's
# `brain_replica._SECRET_LIKE_PREFIXES`; expanded to the full known set.
_SECRET_LIKE_PREFIXES = (
    "sk-", "sk_live_", "sk_test_", "rk_live_", "rk_test_",
    "AKIA", "AIza", "ghp_", "gho_", "ghu_", "ghs_", "ghr_",
    "xoxb-", "xoxp-", "xoxa-", "xoxr-", "xoxs-",
)
# Reference schemes that ARE safe to sync (resolution stays local).
_SAFE_REF_PREFIXES = ("op://", "wcm://", "env://", "inline:", "file://")

import re as _re

# Safe-reference matcher — stripped/stashed before secret detection so a
# reference is never touched or misread as a secret.
_REF_TOKEN_RE = _re.compile(
    r"\b(?:op|wcm|env)://[^\s\"'<>]+|\binline:[^\s\"'<>]+|\bfile://[^\s\"'<>]+"
)

# ONE comprehensive secret-token detector, matched ANYWHERE (re.search) — NOT
# startswith — so an embedded secret in a sentence ("prod key is AIza... use it")
# is caught. Used by BOTH the scrubber (_redact_secret_values_only) and the
# drop-gate (_looks_like_bare_secret) so the two can never diverge. That
# divergence WAS the leak (founder 2026-06-02 cross-device verify): scrub patterns
# lacked AIza/xoxb-/rk_live_ while the startswith drop-gate missed mid-text
# occurrences, so embedded Google/Slack/Stripe keys synced to the cloud verbatim.
# The leading lookbehind anchors the prefix at a non-alnum boundary so ordinary
# words ("task-12345678") don't false-positive. op:// refs are stripped first.
_SECRET_TOKEN_RE = _re.compile(
    r"(?<![A-Za-z0-9_\-])"
    r"(?:(?:sk-|sk_live_|sk_test_|rk_live_|rk_test_|AKIA|AIza|gh[pousr]_|xox[bpars]-)"
    r"[A-Za-z0-9_\-]{8,}"
    r"|eyJ[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,})"
)


def _strip_safe_refs(s: str) -> str:
    """Blank out op://·wcm://·env:// references so a secret-looking path inside
    a reference can't false-positive the secret search."""
    return _REF_TOKEN_RE.sub(" ", s)


def _looks_like_bare_secret(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    s = value.strip()
    if not s:
        return False
    # Search ANYWHERE (not startswith) after stripping safe references, so an
    # embedded credential anywhere in the field is caught.
    return bool(_SECRET_TOKEN_RE.search(_strip_safe_refs(s)))


def _extra_has_bare_secret(extra: Any) -> bool:
    """Recursively scan an `extra` payload (which may nest dicts/lists — e.g.
    extra.skill carries the full Skill dict) for any bare secret value."""
    if isinstance(extra, dict):
        return any(_extra_has_bare_secret(v) for v in extra.values())
    if isinstance(extra, (list, tuple)):
        return any(_extra_has_bare_secret(v) for v in extra)
    return _looks_like_bare_secret(extra)


# ─────────────────────── secret-only redaction ──────────────────────────
#
# Personal sync converges the user's OWN data across THEIR devices, so it must
# NOT do the aggressive upward-promotion redaction (which strips proper nouns,
# emails, file paths, URLs, money amounts — and, fatally, MANGLES `op://`
# references into `op:/<path>`). It must strip ONLY actual credential VALUES
# while preserving `op://`/`wcm://`/`env://` REFERENCES verbatim, so the
# receiving device can resolve the secret locally. We reuse the privacy
# layer's pattern list (single source of truth) but select only the
# unambiguous credential classes.

# Credential placeholder labels from redaction._PATTERNS that denote a real
# secret VALUE (not PII/path/url/amount). These are the only patterns we apply.
_SECRET_PLACEHOLDERS = frozenset({"<secret-key>", "<aws-key>", "<google-token>", "<jwt>"})

_SECRET_VALUE_PATTERNS = [
    (pat, repl) for (pat, repl, _label) in _redaction._PATTERNS
    if repl in _SECRET_PLACEHOLDERS
]

# (_re, _REF_TOKEN_RE and _SECRET_TOKEN_RE are defined above, beside the secret
# prefixes, so the scrubber and the drop-gate share one detector.)


def _redact_secret_values_only(text: str) -> str:
    """Strip credential VALUES from `text`, preserving op:// / wcm:// / env://
    references verbatim. Returns the sanitised text.

    1. Pull out safe references behind opaque sentinels so the secret/path
       patterns can't touch them.
    2. Apply ONLY the credential-value patterns (API keys, AWS, Google, JWT).
    3. Restore the references.
    """
    if not text or not isinstance(text, str):
        return text
    refs: list[str] = []

    def _stash(m):
        refs.append(m.group(0))
        return f"\x00REF{len(refs) - 1}\x00"

    protected = _REF_TOKEN_RE.sub(_stash, text)
    for pat, repl in _SECRET_VALUE_PATTERNS:
        protected = pat.sub(repl, protected)
    # Comprehensive backstop: scrub ANY remaining credential token anywhere
    # (covers AIza/xoxb-/rk_live_ etc. the placeholder-class patterns miss). Same
    # detector the drop-gate uses, so scrub + drop cannot diverge.
    protected = _SECRET_TOKEN_RE.sub("<redacted-secret>", protected)
    for i, ref in enumerate(refs):
        protected = protected.replace(f"\x00REF{i}\x00", ref)
    return protected


# ─────────────────────── result dataclass ───────────────────────────────


@dataclass
class PersonalSyncResult:
    """One tick's outcome (parallel to SyncCycleResult)."""

    ok: bool = True
    inert: bool = False                 # True when no token (signed-out)
    auth_invalid: bool = False          # True when the SERVER rejected our token (401/403)
    started_at: float = field(default_factory=time.time)
    duration_ms: float = 0.0
    pushed_fragments: int = 0
    pushed_skills: int = 0
    secrets_dropped: int = 0            # fragments withheld for carrying a secret
    accepted: int = 0                   # cloud-accepted rows
    rejected: int = 0                   # cloud-rejected rows
    merged_fragments: int = 0           # rows in the cloud's merged response
    applied_to_local: int = 0           # NEW rows written back into BrainStore
    since_hlc: str = ""                 # cursor used for THIS pull
    new_hlc: str = ""                   # cursor advanced to after this tick
    user_id: str = ""
    error: Optional[str] = None


# ─────────────────────── HTTP (stdlib only) ─────────────────────────────


def _http_post_json(
    url: str, payload: dict[str, Any], headers: dict[str, str], *, timeout_s: float,
) -> dict[str, Any]:
    """POST JSON, return parsed JSON. Raises on non-2xx / network error.

    Stdlib urllib only — no new dependency, no import-time risk.
    """
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _http_get_json(
    url: str, headers: dict[str, str], *, timeout_s: float,
) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


# ─────────────────────── the worker ─────────────────────────────────────


class PersonalCloudSync:
    """Personal USER-scope cloud sync engine.

    Spawned by the daemon at startup ALONGSIDE the firm SyncWorker, but only
    when a cloud token exists. Each tick:
      1. Builds a DELTA of local USER-scope fragments + skills (skills encoded
         as kind=skill fragments so they ride the same channel).
      2. Routes every fragment through the secret-only redactor; drops any that
         still carry a bare secret.
      3. POSTs {since_hlc, delta} to {cloud}/v1/brain/sync with the bearer.
      4. Applies the merged response back into BrainStore (pull/converge),
         skipping rows we already own.
      5. Advances the since_hlc cursor to the cloud's new_hlc.

    Thread-safe; `tick()` is callable synchronously for the CLI / tests.
    """

    def __init__(
        self,
        store: BrainStore,
        *,
        owner_user: Optional[str] = None,
        interval_s: float = 300.0,
        device_id: Optional[str] = None,
        config: Optional[CloudConfig] = None,
        config_loader=load_cloud_config,
        http_timeout_s: float = 20.0,
        logger=None,
    ):
        self.store = store
        self.owner_user = owner_user
        self.interval_s = max(5.0, interval_s)
        self.device_id = device_id or "device-default"
        # A pinned config (tests) OR a loader re-read each tick so a fresh
        # `cloud_login` takes effect WITHOUT a daemon restart.
        self._pinned_config = config
        self._config_loader = config_loader
        self.http_timeout_s = http_timeout_s
        self._log = logger

        self._tick_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_result: Optional[PersonalSyncResult] = None
        self._cycle_count = 0
        self._error_count = 0

    # ── config / identity ───────────────────────────────────────────

    def _config(self) -> CloudConfig:
        if self._pinned_config is not None:
            return self._pinned_config
        try:
            return self._config_loader()
        except Exception:
            # Never let a config read crash a tick — degrade to inert.
            return CloudConfig()

    def _effective_owner(self, cfg: CloudConfig) -> str:
        """Owner used to scope the USER fragments we push.

        Prefer the explicit owner_user passed by the daemon (the bound cloud
        user_id), else the user_id cached in cloud.json, else the bound owner
        from brain_meta, else 'founder'. The cloud re-scopes server-side by the
        token anyway — this just selects WHICH local USER rows to send.
        """
        if self.owner_user:
            return self.owner_user
        if cfg.user_id:
            return cfg.user_id
        try:
            bound = (self.store.get_meta("bound_owner_user") or "").strip()
            if bound:
                return bound
        except Exception:
            pass
        return "founder"

    def _logmsg(self, msg: str) -> None:
        if self._log is not None:
            try:
                self._log(msg)
                return
            except Exception:
                pass
        # Default: stderr, prefixed, flushed — visible in the daemon log.
        import sys
        print(f"[brain.personal-sync] {msg}", file=sys.stderr, flush=True)

    # ── lifecycle (mirrors SyncWorker) ───────────────────────────────

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="brain-personal-cloud-sync", daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_s: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)

    def _loop(self) -> None:
        # Run one tick immediately on start (so a fresh sign-in converges
        # without waiting a full interval), then on the interval.
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as ex:  # belt-and-suspenders; tick() also guards
                self._error_count += 1
                self._logmsg(f"tick crashed (contained): {type(ex).__name__}: {ex}")
            slept = 0.0
            while slept < self.interval_s and not self._stop_event.is_set():
                time.sleep(min(0.5, self.interval_s - slept))
                slept += 0.5

    # ── one cycle ────────────────────────────────────────────────────

    def tick(self) -> PersonalSyncResult:
        """Run one personal-sync cycle. Thread-safe. Never raises."""
        with self._tick_lock:
            result = PersonalSyncResult()
            t0 = time.perf_counter()
            cfg = self._config()

            # GATE: no token → inert no-op (logged, never crashes/blocks).
            if not cfg.is_signed_in:
                result.inert = True
                result.ok = True
                self._clear_auth_invalid()  # signed out cleanly — no stale latch
                result.duration_ms = (time.perf_counter() - t0) * 1000.0
                self._last_result = result
                return result

            # GATE: the SERVER already verified + rejected THIS token (401/403)
            # on a prior tick. Honor that verdict — go inert instead of
            # re-POSTing a known-dead bearer every interval (the 401-class
            # hardening: don't hammer the cloud with a token the server told
            # us is invalid). The latch is keyed to the rejected token's
            # fingerprint, so a fresh sign-in with a DIFFERENT token clears it
            # automatically and sync resumes without a daemon restart.
            if self._is_auth_invalid_for(cfg.token):
                result.inert = True
                result.auth_invalid = True
                result.ok = True
                result.user_id = cfg.user_id or self._effective_owner(cfg)
                result.duration_ms = (time.perf_counter() - t0) * 1000.0
                self._last_result = result
                return result
            # A token change since the last rejection supersedes the latch.
            self._clear_auth_invalid_if_token_changed(cfg.token)

            try:
                owner = self._effective_owner(cfg)
                result.user_id = cfg.user_id or owner

                # 1. Build the outbound delta from local USER-scope rows.
                frag_dicts = self._collect_user_fragments(owner)
                skill_frag_dicts = self._collect_user_skills_as_fragments(owner)

                # 2. Privacy: redact + drop bare-secret carriers.
                safe_fragments: list[dict[str, Any]] = []
                dropped = 0
                for fd in frag_dicts + skill_frag_dicts:
                    san = self._sanitize_outbound(fd)
                    if san is None:
                        dropped += 1
                        continue
                    safe_fragments.append(san)
                result.secrets_dropped = dropped
                result.pushed_fragments = len(frag_dicts) - sum(
                    1 for fd in frag_dicts if self._sanitize_outbound(fd) is None
                )
                result.pushed_skills = len(skill_frag_dicts)

                since_hlc = self._load_cursor()
                result.since_hlc = since_hlc

                payload = {
                    "since_hlc": since_hlc,
                    "delta": {"fragments": safe_fragments, "wiring": []},
                }

                # 3. Push + pull in one round-trip.
                resp = _http_post_json(
                    cfg.sync_url(), payload, cfg.auth_header(),
                    timeout_s=self.http_timeout_s,
                )

                result.accepted = int(resp.get("accepted") or 0)
                rejected = resp.get("rejected") or []
                result.rejected = len(rejected) if isinstance(rejected, list) else int(rejected or 0)
                merged = resp.get("merged") or {}
                merged_fragments = merged.get("fragments") or []
                result.merged_fragments = len(merged_fragments)

                # 4. Apply merged rows back into the local store (converge).
                result.applied_to_local = self._apply_merged(merged_fragments, owner)

                # 5. Advance the cursor to the cloud's new_hlc.
                new_hlc = (resp.get("new_hlc") or merged.get("new_hlc") or "").strip()
                if new_hlc:
                    self._save_cursor(new_hlc)
                    result.new_hlc = new_hlc
                else:
                    result.new_hlc = since_hlc

                result.ok = True
                result.duration_ms = (time.perf_counter() - t0) * 1000.0
                self._cycle_count += 1
                # A clean round-trip proves the token is good again — drop any
                # stale auth-invalid latch from a prior rejection.
                self._clear_auth_invalid()
                self._last_result = result
                self._persist_status(result)
                if dropped:
                    self._logmsg(
                        f"ok — pushed {len(safe_fragments)} (dropped {dropped} secret-bearing), "
                        f"applied {result.applied_to_local} from cloud"
                    )
                return result
            except urllib.error.HTTPError as ex:
                # The server VERIFIED our bearer and REJECTED it (401/403) —
                # db.user_for_token returned None for a revoked/expired/unknown
                # token. This is a token-identity verdict, NOT a transient blip:
                # retrying the SAME token can never succeed. Latch it (keyed to
                # this token's fingerprint) so subsequent ticks go inert instead
                # of hammering the cloud, and surface auth_invalid so the UI/CLI
                # prompts a fresh sign-in. Cleared on the next success or a
                # token change.
                if ex.code in _AUTH_REJECT_STATUSES:
                    return self._fail_auth(result, t0, cfg.token, ex.code, ex.reason)
                return self._fail(result, t0, f"HTTP {ex.code}: {ex.reason}")
            except urllib.error.URLError as ex:
                return self._fail(result, t0, f"network: {ex.reason}")
            except Exception as ex:
                return self._fail(result, t0, f"{type(ex).__name__}: {ex}")

    def _fail(self, result: PersonalSyncResult, t0: float, msg: str) -> PersonalSyncResult:
        """Degrade-to-local-only path: record + log, never raise."""
        self._error_count += 1
        result.ok = False
        result.error = msg
        result.duration_ms = (time.perf_counter() - t0) * 1000.0
        self._last_result = result
        self._persist_status(result)
        self._logmsg(f"degraded to local-only this tick: {msg}")
        return result

    def _fail_auth(self, result: PersonalSyncResult, t0: float, token: str,
                   code: int, reason: str) -> PersonalSyncResult:
        """The server verified + rejected our bearer (401/403). Latch the
        rejection (so future ticks go inert rather than re-POSTing a dead
        token) and surface auth_invalid for the UI/CLI to prompt re-sign-in.

        Distinct from `_fail`: this is NOT a transient degrade. We do NOT bump
        the generic error_count (this isn't a flaky-network event), we set
        result.auth_invalid, and we persist the latch keyed to the rejected
        token's fingerprint so a later sign-in with a fresh token clears it.
        """
        self._set_auth_invalid(token, code)
        result.ok = False
        result.auth_invalid = True
        result.error = f"auth_rejected: HTTP {code}: {reason}"
        result.duration_ms = (time.perf_counter() - t0) * 1000.0
        self._last_result = result
        self._persist_status(result)
        self._logmsg(
            f"token rejected by server (HTTP {code}) — going inert until a "
            f"fresh sign-in. Re-run cloud_login to resume cross-device sync."
        )
        return result

    # ── auth-invalid latch (honor the server's token verdict) ────────

    @staticmethod
    def _token_fp(token: str) -> str:
        """Stable, non-reversible fingerprint of a bearer token. Used to key
        the auth-invalid latch so a NEW token (fresh sign-in) is never treated
        as still-rejected. Never stores or logs the raw token."""
        import hashlib
        t = (token or "").strip()
        if not t:
            return ""
        return hashlib.sha256(t.encode("utf-8")).hexdigest()[:16]

    def _set_auth_invalid(self, token: str, code: int) -> None:
        """Persist the auth-invalid latch + the rejected token's fingerprint."""
        try:
            self.store.set_meta(_META_AUTH_INVALID, str(code))
            self.store.set_meta(_META_AUTH_INVALID_TOKEN, self._token_fp(token))
        except Exception:
            pass

    def _clear_auth_invalid(self) -> None:
        """Drop the auth-invalid latch (token is good again / signed out)."""
        try:
            if (self.store.get_meta(_META_AUTH_INVALID) or "").strip():
                self.store.set_meta(_META_AUTH_INVALID, "")
                self.store.set_meta(_META_AUTH_INVALID_TOKEN, "")
        except Exception:
            pass

    def _is_auth_invalid_for(self, token: str) -> bool:
        """True iff the latch is set AND it was set for THIS exact token. A
        different (fresh) token is never considered rejected — the verdict was
        about the old one."""
        try:
            latched = (self.store.get_meta(_META_AUTH_INVALID) or "").strip()
            if not latched:
                return False
            latched_fp = (self.store.get_meta(_META_AUTH_INVALID_TOKEN) or "").strip()
        except Exception:
            return False
        # No recorded fingerprint (legacy) → treat the latch as applying to the
        # current token (fail-safe: stay inert rather than hammer the cloud).
        if not latched_fp:
            return True
        return latched_fp == self._token_fp(token)

    def _clear_auth_invalid_if_token_changed(self, token: str) -> None:
        """If a latch exists but for a DIFFERENT token, clear it — a fresh
        sign-in supersedes a stale rejection of the old token."""
        try:
            latched = (self.store.get_meta(_META_AUTH_INVALID) or "").strip()
            if not latched:
                return
            latched_fp = (self.store.get_meta(_META_AUTH_INVALID_TOKEN) or "").strip()
        except Exception:
            return
        if latched_fp and latched_fp != self._token_fp(token):
            self._clear_auth_invalid()

    # ── collect local USER-scope rows ────────────────────────────────

    def _collect_user_fragments(self, owner: str) -> list[dict[str, Any]]:
        """All USER-scope, owner-owned fragments as wire dicts (excl. skills,
        which go through `_collect_user_skills_as_fragments`). Stamps a string
        HLC at top-level (the cloud replica's cursor field)."""
        out: list[dict[str, Any]] = []
        frags = self.store.list_fragments(
            scope_filter=[Scope.USER], owner_user=owner, limit=100000,
        )
        for f in frags:
            if f.kind == FragmentKind.SKILL:
                continue  # skills handled separately
            if f.owner_user != owner:
                continue  # strict per-user isolation — never send others' rows
            out.append(self._fragment_to_wire(f))
        return out

    def _collect_user_skills_as_fragments(self, owner: str) -> list[dict[str, Any]]:
        """USER-scope skills, encoded as kind=skill wire fragments.

        The cloud replica has only a `fragments` table — no `skills` table — so
        a personal skill rides as a kind=skill fragment whose `extra.skill`
        carries the full Skill payload. On pull we reconstruct the Skill.
        """
        out: list[dict[str, Any]] = []
        try:
            skills = self.store.list_skills(
                scope_filter=[Scope.USER], owner_user=owner, limit=100000,
            )
        except Exception:
            skills = []
        for s in skills:
            if s.owner_user != owner:
                continue
            try:
                payload = s.model_dump(mode="json")
            except Exception:
                continue
            prov = payload.get("provenance") or {}
            wire = {
                "id": f"skill:{s.id}",
                "kind": "skill",
                "text": s.description or s.name,
                "subject": s.name,
                "predicate": "skill",
                "object": None,
                "scope": "user",
                "visibility": "private",
                "owner_user": owner,
                "project_id": None,
                "firm_id": None,
                "confidence": "extracted",
                "provenance": prov,
                "extra": {"skill": payload, "is_personal_skill": True},
                "hlc": self._frag_hlc(prov),
            }
            out.append(wire)
        return out

    def _fragment_to_wire(self, f: Fragment) -> dict[str, Any]:
        """Fragment → cloud-replica wire dict (matching its `fragments`
        columns). HLC is taken from provenance.hlc when present (int → string)
        else a fresh string tick, placed at top-level."""
        try:
            prov = f.provenance.model_dump(mode="json")
        except Exception:
            prov = {}
        return {
            "id": f.id,
            "kind": f.kind.value if hasattr(f.kind, "value") else str(f.kind),
            "text": f.text or "",
            "subject": f.subject,
            "predicate": f.predicate,
            "object": f.object,
            "scope": "user",
            "visibility": f.visibility.value if hasattr(f.visibility, "value") else "private",
            "owner_user": f.owner_user,
            "project_id": f.project_id,
            "firm_id": f.firm_id,
            "confidence": f.confidence.value if hasattr(f.confidence, "value") else "extracted",
            "provenance": prov,
            "extra": f.extra or {},
            # Reinforcement evidence rides the wire — omitting these made the
            # pull-side upsert zero the local counters (sync wiped learning).
            "success_count": int(f.success_count or 0),
            "fail_count": int(f.fail_count or 0),
            "last_used_at": f.last_used_at.isoformat() if f.last_used_at else None,
            "hlc": self._frag_hlc(prov),
        }

    @staticmethod
    def _frag_hlc(prov: dict[str, Any]) -> str:
        """Derive the cloud's string HLC cursor for a fragment.

        The cloud orders by a `<unix_ms_zfill16>.<hex8>` string. The local
        brain stamps provenance.hlc as a 64-bit packed int (or 16-char hex).
        We map either into the cloud's lexical format using the physical-ms
        component so ordering stays causal. Falls back to now() when absent.
        """
        import secrets as _secrets
        from . import hlc as _hlc

        raw = prov.get("hlc") if isinstance(prov, dict) else None
        phys_ms: Optional[int] = None
        if isinstance(raw, int):
            phys_ms, _ = _hlc.unpack(raw)
        elif isinstance(raw, str) and raw:
            try:
                packed = int(raw, 16) if len(raw) == 16 else int(raw)
                phys_ms, _ = _hlc.unpack(packed)
            except Exception:
                phys_ms = None
        if not phys_ms or phys_ms <= 0:
            phys_ms = int(time.time() * 1000)
        return f"{phys_ms:016d}.{_secrets.token_hex(4)}"

    # ── privacy: secret-only redaction + drop ────────────────────────

    def _sanitize_outbound(self, frag: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Strip credential VALUES from a wire fragment, preserving op:// refs;
        return the sanitised copy, or None if it must be WITHHELD.

        Personal sync converges the user's OWN data across THEIR devices, so we
        must NOT strip the user's real content (proper nouns, file paths, URLs,
        emails) the way an upward COMMUNITY promotion would — that would corrupt
        the personal brain, AND it would mangle `op://` references into
        `op:/<path>`, making them unresolvable on the other device. Instead we:

          • redact ONLY actual credential VALUES (API keys / AWS / Google / JWT)
            from text/subject/object/predicate AND the skill body carried in
            extra.skill.body — via `_redact_secret_values_only`, which protects
            op://·wcm://·env:// references; then
          • HARD-DROP the whole fragment if a BARE secret STILL survives in any
            scanned field or anywhere in extra (defense in depth — the cloud
            rejects these too, but we never put one on the wire).

        Net guarantee: the resolved secret value NEVER leaves this machine; only
        op:// references (and the user's own non-secret content) sync.
        """
        sanitised = dict(frag)
        try:
            for field_name in ("text", "subject", "object", "predicate"):
                val = sanitised.get(field_name)
                if isinstance(val, str) and val:
                    sanitised[field_name] = _redact_secret_values_only(val)
            # Sanitise the skill body too (rides inside extra.skill for skills).
            extra = sanitised.get("extra")
            if isinstance(extra, dict):
                extra = dict(extra)
                skill = extra.get("skill")
                if isinstance(skill, dict) and isinstance(skill.get("body"), str):
                    skill = dict(skill)
                    skill["body"] = _redact_secret_values_only(skill["body"])
                    if isinstance(skill.get("description"), str):
                        skill["description"] = _redact_secret_values_only(skill["description"])
                    extra["skill"] = skill
                sanitised["extra"] = extra
        except Exception:
            # If redaction itself fails, fall back to the original + let the
            # hard gate below decide; never crash a tick on one fragment.
            sanitised = dict(frag)

        # Hard gate: never let a bare secret cross, even if a pattern missed it.
        for field_name in ("text", "subject", "object", "predicate"):
            if _looks_like_bare_secret(sanitised.get(field_name)):
                return None
        extra = sanitised.get("extra")
        if isinstance(extra, dict) and _extra_has_bare_secret(extra):
            return None
        return sanitised

    # ── apply merged rows back into the local store (pull) ───────────

    def _apply_merged(self, merged_fragments: list[dict[str, Any]], owner: str) -> int:
        """Write NEW remote rows into BrainStore. Idempotent — `write_fragment`
        / `upsert_skill` upsert by id, and we skip rows already present unless
        the remote HLC is newer. Returns count applied."""
        applied = 0
        for raw in merged_fragments:
            if not isinstance(raw, dict):
                continue
            kind = (raw.get("kind") or "fact").strip().lower()
            try:
                if kind == "skill":
                    if self._apply_remote_skill(raw, owner):
                        applied += 1
                else:
                    if self._apply_remote_fragment(raw, owner):
                        applied += 1
            except Exception as ex:
                # One malformed remote row never aborts the batch.
                self._logmsg(f"skip malformed remote row {raw.get('id')!r}: {ex}")
        return applied

    def _newer_than_local(self, fragment_id: str, remote_hlc_str: str) -> bool:
        """Decide whether to write a remote row. True if we don't have it, or
        the remote string-HLC is lexically newer than what we last applied for
        it. We track applied remote HLCs in brain_meta to keep idempotency
        cheap without re-deriving the local fragment's cloud-HLC."""
        if not remote_hlc_str:
            # No cursor on the remote row — only write if we lack it entirely.
            return self.store.get_fragment(fragment_id) is None
        key = f"personal_cloud_sync.applied_hlc.{fragment_id}"
        try:
            prev = (self.store.get_meta(key) or "").strip()
        except Exception:
            prev = ""
        if prev and remote_hlc_str <= prev:
            return False
        return True

    def _mark_applied(self, fragment_id: str, remote_hlc_str: str) -> None:
        if not remote_hlc_str:
            return
        try:
            self.store.set_meta(
                f"personal_cloud_sync.applied_hlc.{fragment_id}", remote_hlc_str,
            )
        except Exception:
            pass

    def _apply_remote_fragment(self, raw: dict[str, Any], owner: str) -> bool:
        fid = raw.get("id")
        if not fid:
            return False
        remote_hlc = str(raw.get("hlc") or "")
        if not self._newer_than_local(fid, remote_hlc):
            return False

        prov_dict = raw.get("provenance") or raw.get("provenance_json") or {}
        if isinstance(prov_dict, str):
            try:
                prov_dict = json.loads(prov_dict)
            except Exception:
                prov_dict = {}
        prov_dict.setdefault("contributing_agent", "personal-cloud-sync")
        prov_dict.setdefault("contributing_user", owner)
        try:
            prov = Provenance(**{
                k: v for k, v in prov_dict.items()
                if k in Provenance.__pydantic_fields__
            })
        except Exception:
            prov = Provenance(
                contributing_agent="personal-cloud-sync",
                contributing_user=owner,
            )

        extra = raw.get("extra") or raw.get("extra_json") or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}

        # Reinforcement merge — the upsert writes excluded.* verbatim, so a
        # remote row carrying 0/0/None must NEVER lower local evidence. Take
        # max(local, remote) per counter and the later last_used_at.
        local = self.store.get_fragment(fid)
        remote_success = int(raw.get("success_count") or 0)
        remote_fail = int(raw.get("fail_count") or 0)
        remote_used = _parse_iso(raw.get("last_used_at"))
        if local is not None:
            remote_success = max(remote_success, local.success_count)
            remote_fail = max(remote_fail, local.fail_count)
            remote_used = _max_dt(remote_used, local.last_used_at)

        fragment = Fragment(
            id=fid,
            kind=FragmentKind(raw.get("kind") or "fact"),
            text=raw.get("text") or "",
            subject=raw.get("subject"),
            predicate=raw.get("predicate"),
            object=raw.get("object"),
            scope=Scope.USER,
            visibility=Visibility.PRIVATE,
            owner_user=owner,                      # per-user isolation on import
            project_id=raw.get("project_id"),
            firm_id=raw.get("firm_id"),
            confidence=Confidence(raw.get("confidence") or "extracted"),
            provenance=prov,
            extra=extra if isinstance(extra, dict) else {},
            success_count=remote_success,
            fail_count=remote_fail,
            last_used_at=remote_used,
        )
        self.store.write_fragment(fragment)
        self._mark_applied(fid, remote_hlc)
        return True

    def _apply_remote_skill(self, raw: dict[str, Any], owner: str) -> bool:
        fid = raw.get("id")
        if not fid:
            return False
        remote_hlc = str(raw.get("hlc") or "")
        if not self._newer_than_local(fid, remote_hlc):
            return False

        extra = raw.get("extra") or raw.get("extra_json") or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}
        payload = (extra or {}).get("skill") if isinstance(extra, dict) else None
        if not isinstance(payload, dict):
            # Not a reconstructable skill payload — skip (don't fabricate one).
            return False

        # Force USER scope + this owner (private personal skill).
        payload = dict(payload)
        payload["scope"] = "user"
        payload["visibility"] = "private"
        payload["owner_user"] = owner
        prov = payload.get("provenance") or {}
        if isinstance(prov, dict):
            prov.setdefault("contributing_agent", "personal-cloud-sync")
            prov.setdefault("contributing_user", owner)
            payload["provenance"] = prov
        try:
            skill = Skill.model_validate(payload)
        except Exception:
            return False
        # Reinforcement merge — never lower local evidence with a remote copy
        # that has seen fewer uses. max(local, remote) per counter; later
        # last_used_at wins.
        local_sk = self.store.get_skill(skill.id)
        if local_sk is not None:
            skill.success_count = max(skill.success_count, local_sk.success_count)
            skill.fail_count = max(skill.fail_count, local_sk.fail_count)
            skill.last_used_at = _max_dt(skill.last_used_at, local_sk.last_used_at)
        self.store.upsert_skill(skill)
        self._mark_applied(fid, remote_hlc)
        return True

    # ── cursor + status persistence ──────────────────────────────────

    def _load_cursor(self) -> str:
        try:
            cur = (self.store.get_meta(_META_SINCE_HLC) or "").strip()
        except Exception:
            cur = ""
        return cur or _HLC_FLOOR

    def _save_cursor(self, new_hlc: str) -> None:
        try:
            self.store.set_meta(_META_SINCE_HLC, new_hlc)
        except Exception:
            pass

    def _persist_status(self, result: PersonalSyncResult) -> None:
        try:
            self.store.set_meta(
                _META_LAST_SYNC, datetime.now(timezone.utc).isoformat(),
            )
            self.store.set_meta(_META_LAST_RESULT, json.dumps(asdict(result)))
            self.store.set_meta(_META_ERRORS, str(self._error_count))
        except Exception:
            pass

    # ── status (mirrors SyncWorker.status shape) ─────────────────────

    def status(self) -> dict[str, Any]:
        cfg = self._config()
        # auth_invalid: the server verified + rejected the current token. The
        # UI/CLI reads this to prompt a fresh sign-in (vs. a transient error).
        # Only "active" when the latch applies to the token in effect right now
        # — a fresh sign-in clears it on the next tick.
        auth_invalid = bool(cfg.is_signed_in and self._is_auth_invalid_for(cfg.token))
        return {
            "running": self._thread is not None and self._thread.is_alive(),
            "kind": "personal-cloud-sync",
            "interval_s": self.interval_s,
            "transport": "archhub-cloud /v1/brain/sync",
            "signed_in": cfg.is_signed_in,
            "auth_invalid": auth_invalid,
            "needs_reauth": auth_invalid,   # alias the UI/CLI can key on
            "cloud": cfg.redacted(),
            "since_hlc": self._load_cursor(),
            "cycle_count": self._cycle_count,
            "error_count": self._error_count,
            "last_result": asdict(self._last_result) if self._last_result else None,
        }
