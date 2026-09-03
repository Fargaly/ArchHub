# ArchHub v1.6.3 — release notes

> Reference — not the roadmap; see [docs/ROADMAP.md](ROADMAP.md).

The "fast again, and honest about itself" release. Two stray GPU hiccups had
quietly pinned the app to its slow safety mode forever — that's fixed, and it
now recovers on its own. The footer tells you the real version, a node's 3D
output shows real numbers instead of a "coming soon" sign, and the top bar no
longer shows the same chip twice.

## What you will see

- **The app is fast again — and stays fast.** ArchHub has always had a safety
  mode that turns off graphics acceleration if the screen would otherwise come
  up blank. The problem: once it switched, it never switched back, so two
  one-off glitches left it crawling in safety mode permanently. Now that switch
  **expires on its own** and the app retries full speed — after an hour, then
  longer if it keeps failing — so a brief hiccup no longer slows you down for
  good. You don't have to do anything.
- **The footer shows the real version.** The bottom strip used to read
  "v1.4 prototype" no matter what you were running. It now shows the live
  version — **v1.6.3** — read straight from the build.
- **A node's 3D output shows real numbers.** When a node produces a view or a
  model, its output panel used to say "3D VIEWER — COMING SOON." It now shows an
  honest summary of what's actually there — for example
  `GEOMETRY · Mesh · 1248 verts` — above the underlying data. No promise of a
  viewer that isn't there; a real, useful read-out instead.
- **The top bar is tidier.** The brain chip showed up twice in some views — now
  it's one. And the model indicator shows only the model the router actually
  chose, instead of a duplicate "Auto (router picks)" label sitting next to it.

## Also in this finalization (cloud sign-in)

- **Google sign-in fix — prepared, pending the cloud deploy.** Some Google
  sign-ins failed with "Security state mismatch." The cause: the app's own
  one-time security token wasn't being carried back through Google's round-trip,
  so the final handoff was rejected. The fix threads that token all the way
  through the signed state and echoes it back to the app — both security checks
  (the backend-signed state **and** the app's own token) stay in place, and the
  sign-in completes. The same change keeps the sign-in return address
  loopback-only, so a code can never be forwarded anywhere but your own machine.
  This change is **staged in review** (PR #185) and goes live with the next
  cloud release — deploying the cloud is a founder-gated step. The magic-link
  sign-in is unchanged.

## Under the hood

- The safety-mode switch is now a small dated record (when it last failed, and
  how many times in a row) instead of a permanent flag, with a backoff that
  grows 1 hour → 6 hours → 1 day → 1 week before each retry. When the record is
  older than its current window, it is cleared and full-speed graphics are tried
  again on the next launch. Covered by
  `tests/test_gpu_resilience.py::TestSoftwareRenderAutoRecovery`.
- The footer reads the version from the repo `VERSION` file via a real bridge
  call (`get_version`), gated on the app being ready, with a retry. Covered by
  `tests/test_version_footer_real.py`.
- The geometry read-out parses the actual node output (Speckle/geometry type +
  vertex / face / item counts) rather than rendering a placeholder.

## What did not change

- Your sessions, brain, and skills are untouched — this is a
  reliability-and-clarity release, not a data change.
- Magic-link sign-in, sessions cloud-sync, the Team screen, and the Self-Heal
  Inspector all behave exactly as in v1.6.0–v1.6.2.
