# Runtime Deployment Ownership

Status: WIP source mechanism. This document does not claim live deployment.

## What

ArchHub uses one persistent loopback HTTP gateway and one replaceable Universal
Cell worker. The gateway owns no semantic data. It forwards only to the worker
generation proven by the worker's signed machine descriptor and graph-held runtime
ownership relation.

## Why

The previous Windows task launched `nodelang.application_server` directly on the
visible port. Updating the worker therefore meant replacing the visible listener,
and the task definition could drift because no product source recreated it.

The gateway keeps the visible origin stable while the worker is released and
reconstructed from the accepted Cell database. During replacement it returns a
bounded `503 Retry-After`, not a request to an unproven worker.

## How

1. `runtime_supervisor` binds the stable loopback origin.
2. It starts one worker on a private ephemeral loopback port.
3. The worker acquires runtime ownership in the Universal Cell graph and publishes
   a signed machine descriptor.
4. The supervisor reads `runtime-backend` through that signed machine transport.
5. The gateway admits the worker only when URL, generation, ownership root, and
   listening socket match the proof.
6. Browser handoff publishes the gateway origin; runtime backend proof continues
   to publish the private worker origin.
7. A separately accepted Work may release the worker through the authenticated
   handoff route. Before the graph transitions to draining, the worker requests
   an admission drain through inherited parent-child standard-I/O pipes. The
   supervisor verifies the exact active URL, generation, ownership root, and
   request nonce; stops new gateway admission; waits for admitted requests; and
   acknowledges the same tuple. Only then may the worker commit the signed graph
   transition. The supervisor starts the replacement and admits only a strictly
   newer graph-proven generation.

## Who

- The Universal Cell runtime ownership graph decides which worker is authoritative.
- The authenticated worker owns the application graph and signed machine pipe.
- The supervisor owns only the physical gateway and child-process lifecycle.
- The founder or an authorised Agent Session approves deployment Work.
- The independent Work court judges source and deployment evidence.

## When

The source mechanism is built and courted before installation. Registration of the
Windows task is explicit and does not start or stop a process. Live activation is a
separate deployment Work after resource and client-project constraints are clear.

## Where

- Semantic state: the one Universal Cell database selected by the accepted runtime.
- Physical descriptor and browser credentials: admitted DPAPI/local application
  custody outside the repository.
- Gateway and worker: numeric Windows loopback only.
- Task definition: generated from `packaging/windows/install_runtime_task.ps1`.

## Evidence And Boundaries

The source court proves public/private origin separation, exact signed generation
admission, monotonic replacement, bounded crash handling, secret-free arguments,
and the task policy. A later live court must prove task registration, graceful
handoff, gateway continuity, restart recovery, and exact graph root identity before
this mechanism is called deployed.

The same live court must also compare the architect-facing projection before and
after handoff: canvas scope and camera, visible nodes and wires, selection and focus,
properties panels and editable parameters, grouping and scope navigation, undo and
history, keyboard/pointer behavior, and the released design tokens. It must retain
the specification budgets of same-frame selection, pointer p95 at or below 16.7 ms,
local mutation acknowledgement at or below 100 ms, and bounded scope entry at or
below 150 ms. HTTP 200 with a visually changed, static, incomplete, or slower editor
is a failed deployment.

The operating-system process, socket, scheduled task, and DPAPI key bytes are
physical machinery. Their contracts, requests, grants, generation identity,
ownership, and outcomes remain graph evidence, as required by `SPEC.md` section
3.3 and sections 8-11.

The drain pipe is physical process coordination, not another message bus or data
authority. It is inherited only between the supervisor and its owned child, uses
bounded newline-delimited control records, carries no user/project data, and
cannot authorise the handoff: the worker first verifies the Agent Session, Work,
generation, ownership, and graph policy. A missing, stale, foreign, malformed, or
unacknowledged pipe record fails closed before the graph drain commit.

## CDE operational records

Source repair under review, not installed backend acceptance. New CDE write
permits and receipts use indexed tables in the same primary instance database.
Permission policy, agent identity, Work and container scope remain graph authority.
A permit or receipt does not create a layout node or graph revision per tool call.
SQLite writes compare the admitted graph revision inside their write transaction;
a stale admission fails before effects. A retried consumption returns the original
receipt, including its original digest and time, rather than inventing a new result.

Legacy graph-held evidence remains readable. No live history has been deleted,
no automatic database shrink is promised, and historical permit scans still need
a bounded migration/indexing path. Installed acceptance must cover same-instance
issue/consume/reopen, replay/expiry/revocation refusal, graph growth, and resource
cleanup. Source tests alone do not establish that live application behavior.

## Runtime presence storage

Runtime presence uses the same primary instance SQLite database. Stable session,
device and runtime bindings remain graph Cells. Frequently renewed `refreshed_at`
and `expires_at` values belong to indexed `runtime_presence_leases` records,
with migration and revocation metadata. Renewing an existing lease advances its
generation without adding graph revisions or Cells.

Renewal requires an authenticated device-proof session. A supplied
`expected_generation` must be a positive integer, never a boolean, and match the
current generation. When omitted, renewal uses the admitted binding's retained
generation. Deleted leases must remain revoked through migration and reopening.
The instance owner passes lease storage explicitly during restore; no global
snapshot registry or runtime replacement of `CellStore` methods is required.

Existing historical graph versions are preserved. This change does not compact
the database or automatically reduce its file size. Graph-root identity and
user-instance boundaries remain intact. Presence freshness does not grant gateway
ownership or authority to execute Work.

These are source behaviors, not proof of installed acceptance. Deployment must
separately verify migration, authenticated renewal without graph growth, refusal
of stale generations, and reopening against the installed instance while
preserving its state. Do not report the heartbeat repair as deployed from source
tests alone.

Legacy replay checks still scan graph-held historical permits until a verified
index migration exists. Each issue reads the registry once and decodes each
admitted permit from the same snapshot; it no longer re-reads the whole registry
for every permit. The normal permit reader still requires registration. This
reduces the legacy scan from quadratic to linear; it does not claim indexed
legacy lookup or installed save latency acceptance.

### CDE recovery lifecycle

Owned presence storage remains available until transport and workers drain, then
closes before recovery reservation. Both operational stores retain their handle
and propagate a close failure. Owned CDE storage closes on constructor failure
and normal shutdown. Final
recovery closes the quiesced auxiliary connection before reserving the primary
SQLite graph exclusively; leaving that second connection open blocked recovery
in a real fresh-instance check. Primary graph/content handles and fences remain
retained on preservation failure. A failed CDE close propagates and retains its
handle for explicit retry; it does not report success or detach the handle.

The fresh-instance start/final-recovery/verified-manifest/closed-handle check
passes in source. This does not establish installed acceptance or legacy-history
migration. The older recovery fixture currently fails while attempting to create
legacy graph conversation content and is not counted as passing coverage.

## Primary Windows References

- Microsoft TaskSettings:
  https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings
- Microsoft MultipleInstances policy:
  https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-multipleinstances
- Microsoft RestartOnFailure schema:
  https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-restartonfailure-settingstype-element
- Microsoft Register-ScheduledTask:
  https://learn.microsoft.com/powershell/module/scheduledtasks/register-scheduledtask
- Microsoft child-process redirected input/output:
  https://learn.microsoft.com/windows/win32/procthread/creating-a-child-process-with-redirected-input-and-output
- Python subprocess pipes:
  https://docs.python.org/3/library/subprocess.html#popen-constructor
