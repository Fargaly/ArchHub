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
