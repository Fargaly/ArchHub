# GUARDOWNSCRATCH hermetic test evidence

Owner: lane/guard-own-scratch-2. Scope: tests only; no installed-hook acceptance.

`delete_guard.snapshot.txt` is the historical unmodified external guard snapshot
preserved by the earlier lane at `.cache/guardownscratch-hook-base.py`. Its bytes
are authenticated by SHA-256
`2e527535c61359fd07df68c4e829064652ab4f298f248657e1e8a87116e4d269`,
recorded in committed `04.DOCS/FAILURE_LOG.md` at `47fb42e5`. It was not obtained
by reading the live hook in this repair. It becomes a committed fixture here;
no claim is made that the external governance folder has a Git revision.

`delete_guard.patch` is regenerated against that snapshot, not copied from a
cached candidate. It is a test-only candidate: structured process inventory may
waive recent markers only for trace-proven TEMP/claude cleanup and verified
inventory. Live users still refuse. An exact ordinary temp lane root can contain
inner junctions: scanning skips the junction targets and deletion unlinks them.
Legacy process behavior without recent markers is retained.

`02.TESTS/tests_replica/test_external_delete_guard.py` reconstructs the candidate
by checking and applying the patch to a disposable copy of the committed snapshot.
Both inputs come from Git HEAD; neither the live hook nor `.cache` is an input.
Repository boundary tests stay in `test_guard_own_scratch.py` and exercise
`decide`/`render` as well as the explicitly labeled predicate checks.

Review source: e988 `9f954081`, supplied by the founder; that reference is not an
available local Git commit. This supersedes stale blanket refusal expectations:
ordinary temp is disposable, unchanged bytes survive an mtime-only touch, inner
junctions do not make the lane root unsafe, and traces never authorize workspace
files outside TEMP/claude.

The junction proofs from `07cfc452` are restored with the current repository
entry helper. The PowerShell proof uses the current interpreter (`sys.executable`
passed explicitly), not a bare Python command. No hook or policy is replaced.
