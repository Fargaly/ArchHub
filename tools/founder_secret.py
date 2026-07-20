#!/usr/bin/env python3
r"""founder_secret — the ONE bypass the executor cannot forge.

WHY THIS EXISTS
---------------
The old `.cs` guard honoured `ARCHHUB_ALLOW_CS_EDIT=1` — an env flag the agent
sets itself, so the guard had a self-held off-switch (it was theatre). Every
fail-closed safety gate in this repo needs an escape hatch for the FOUNDER
(who legitimately edits `.cs`, pushes to main, etc.) that the AGENT cannot use.

The mechanism: the founder stores a SECRET out-of-band (env that the agent's
session does not carry, or a file OUTSIDE the repo). The gate never sees the
plaintext baked into anything the agent controls; it only ever compares a
*provided* value's SHA-256 against the founder's stored digest. The agent can
set `ARCHHUB_FOUNDER_SIGNOFF=<value>` all it wants — without knowing the
plaintext that hashes to the founder's stored digest, it cannot produce a match.

  founder, once, out of band (NOT in the repo, NOT in the agent transcript):
    1. choose a passphrase P
    2. store sha256(P) in the ONE fixed file the hook reads (no env selects it):
         - file:  %USERPROFILE%\.archhub\founder_signoff.sha256   (Windows)
                  ~/.archhub/founder_signoff.sha256               (POSIX)
       The DIGEST is read ONLY from this out-of-band file. It is DELIBERATELY
       never read from any environment variable (and the file path is NOT
       env-overridable) — the agent controls os.environ, so any env-sourced or
       env-redirected digest would let the agent set BOTH the digest and a
       matching plaintext and forge the sign-off (jury 2026-06-04, FLAW 1).
    3. to authorise one risky action, run the command WITH the plaintext:
         ARCHHUB_FOUNDER_SIGNOFF=P  git commit ...
         ARCHHUB_FOUNDER_SIGNOFF=P  git push ...

FAIL-CLOSED CONTRACT
--------------------
  * No stored digest  -> AUTHORISED = False  (the gate BLOCKS; you cannot bypass
    a guard whose founder-secret was never provisioned). This is deliberate:
    "unset" is the safe state, not the open state.
  * Provided value missing / wrong  -> False.
  * Any internal error reading the digest -> False (fail-closed even on our own
    bug — the OPPOSITE of the brain-gate's fail-open default that this whole
    build is correcting).
  * Match  -> True.

HONEST RESIDUAL LIMITATION (documented, not hidden)
---------------------------------------------------
A local agent that runs in the SAME OS user account as the founder COULD, in
principle, read the digest file or the env var and try to reverse it — but a
SHA-256 digest is not reversible, and the agent still needs the PLAINTEXT to
produce a match. The real residual is: the same shell can run
`git commit --no-verify` / `git push --no-verify`, which skips local hooks
entirely. THAT cannot be closed locally — it requires SERVER-SIDE enforcement
(branch protection + a required CI check running the SAME gate) on a push token
the agent's shell does not hold. This module closes the *self-settable-env*
hole; the *--no-verify / same-user* hole is a true boundary for the founder
(see founder_setup_required in the build report).

Pure stdlib. No third-party deps. Importable (returns bools) AND runnable as a
CLI (exit 0 = authorised, exit 2 = not authorised) so the bash hooks can call
either form.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sys
from pathlib import Path
from typing import Optional

# Env the FOUNDER sets transiently to authorise ONE action (plaintext). This is
# the value CHECKED AGAINST the stored digest — it is fine for the agent to set
# it; without the plaintext that hashes to the file digest it cannot match.
PROVIDED_ENV = "ARCHHUB_FOUNDER_SIGNOFF"
# NOTE: there is intentionally NO digest-from-env path. An env-sourced digest is
# agent-forgeable (jury 2026-06-04, FLAW 1), so the digest is read ONLY from the
# fixed out-of-band file below. This name is retained solely so diagnostics can
# tell the founder NOT to expect an env to work.
DIGEST_ENV = "ARCHHUB_FOUNDER_SIGNOFF_SHA256"  # NOT read — see stored_digest()
# The ONE fixed file (OUTSIDE the repo, NOT env-selectable) holding the *digest*.
_DIGEST_FILENAME = "founder_signoff.sha256"


def _digest_file_candidates() -> list[Path]:
    """The FIXED out-of-band location(s) the hook reads the founder's stored
    digest from. OUTSIDE the repo tree so a repo-scoped agent edit cannot plant
    a digest — and, critically, NOT selectable by any agent-settable env.

    JURY 2026-06-04 (FLAW 1, second door): an earlier version also honoured an
    `ARCHHUB_FOUNDER_SIGNOFF_FILE` env that pointed the digest source at an
    ARBITRARY path. Because the agent controls os.environ, it could write its
    own digest file anywhere and aim that env at it, then set the matching
    `ARCHHUB_FOUNDER_SIGNOFF` plaintext — forging the sign-off through a
    different door (exactly the hole the env-DIGEST removal closed on the front
    door). That override is therefore REMOVED: the digest source is a single,
    non-overridable path under the founder's home that the agent's transcript
    does not get to redirect. (The founder, out of band, can still place the
    file there; an agent that already has the founder's OS-user shell is the
    documented residual the module's header covers — server-side enforcement is
    the only non-forgeable boundary for that.)"""
    out: list[Path] = []
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if home:
        out.append(Path(home) / ".archhub" / _DIGEST_FILENAME)
    return out


def _normalise_digest(raw: str) -> Optional[str]:
    """A stored digest is a 64-char lowercase hex sha256. Reject anything else
    (fail-closed: a malformed digest is treated as 'no digest')."""
    if not raw:
        return None
    candidate = raw.strip().lower()
    # tolerate an optional "sha256:" prefix
    if candidate.startswith("sha256:"):
        candidate = candidate[len("sha256:"):].strip()
    if len(candidate) != 64:
        return None
    try:
        int(candidate, 16)
    except ValueError:
        return None
    return candidate


def stored_digest() -> Optional[str]:
    """The founder's stored sha256 digest, or None if not provisioned.

    Source: ONLY the out-of-band digest file(s) the founder writes
    (~/.archhub/founder_signoff.sha256). The env var DIGEST_ENV is DELIBERATELY
    NOT read here: the agent controls os.environ, so reading the *digest* from
    env let the agent set BOTH the digest and the matching plaintext in one
    invocation and forge the founder sign-off (jury 2026-06-04 found exactly
    this). Removing the env-digest path closes that self-forge. (Residual,
    documented: a same-OS-user agent can still WRITE the digest file or run
    `git --no-verify`; the only truly non-forgeable enforcement is server-side
    branch protection + a required CI check on a token the agent does not hold.)
    Any read error is swallowed and treated as 'not provisioned' (fail-closed)."""
    for path in _digest_file_candidates():
        try:
            if path.is_file():
                first = path.read_text(encoding="utf-8", errors="replace").splitlines()
                if first:
                    norm = _normalise_digest(first[0])
                    if norm:
                        return norm
        except Exception:
            # fail-closed: an unreadable/odd digest file is 'no digest'
            continue
    return None


def is_authorised() -> bool:
    """True iff the founder provisioned a digest AND the current process carries
    a PROVIDED_ENV plaintext whose sha256 matches it. False on every gap
    (unset digest, missing/empty provided value, mismatch, or internal error).

    Constant-time-ish compare via hashlib.compare_digest on the hex strings."""
    try:
        digest = stored_digest()
        if not digest:
            return False  # FAIL-CLOSED: no founder secret provisioned
        provided = os.environ.get(PROVIDED_ENV, "")
        if not provided:
            return False
        got = hashlib.sha256(provided.encode("utf-8")).hexdigest()
        return hmac.compare_digest(got, digest)
    except Exception:
        return False  # FAIL-CLOSED on our own error


def status_line() -> str:
    """Human-readable one-liner for hook diagnostics (never leaks the secret)."""
    provisioned = stored_digest() is not None
    provided = bool(os.environ.get(PROVIDED_ENV, ""))
    if not provisioned:
        return ("founder-signoff NOT provisioned (no digest file at "
                f"~/.archhub/{_DIGEST_FILENAME}; ${DIGEST_ENV} is NOT a source "
                "— digest is file-only, never env) — fail-closed")
    if not provided:
        return (f"founder-signoff digest present, but ${PROVIDED_ENV} not set "
                "this invocation — not authorised")
    return ("founder-signoff digest present + ${} provided — {}".format(
        PROVIDED_ENV, "MATCH (authorised)" if is_authorised() else "MISMATCH (refused)"))


def _cli(argv: list[str]) -> int:
    # `--make-digest` is a FOUNDER convenience: hash a passphrase from stdin so
    # the founder never has to compute the digest by hand. It NEVER reads the
    # repo and NEVER stores anything — it just prints the hex for the founder to
    # place in their out-of-band store.
    if argv and argv[0] == "--make-digest":
        # Read from a pipe when stdin is not a TTY (avoids a getpass hang in
        # non-interactive shells); else prompt without echo.
        if not sys.stdin.isatty():
            secret = sys.stdin.readline().rstrip("\n")
        else:
            import getpass
            try:
                secret = getpass.getpass("Founder passphrase (not echoed): ")
            except Exception:
                secret = sys.stdin.readline().rstrip("\n")
        if not secret:
            print("empty passphrase — nothing to do", file=sys.stderr)
            return 2
        print(hashlib.sha256(secret.encode("utf-8")).hexdigest())
        return 0
    # default: report authorisation status as an exit code (for the hooks).
    if is_authorised():
        return 0
    sys.stderr.write("[founder-secret] " + status_line() + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
