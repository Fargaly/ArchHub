# Workshop: one place for agent work

The desktop binds `http://127.0.0.1:8474/coordination` on every normal launch.
Local requests use the existing desktop route shape:
`{"method":"POST","path":"/api/universal/baboom-command-execute","body":{"utterance":"run revit.read"}}`.
Workshop requests use `/api/universal/agent-mail/send` (POST), `read` (GET), and
`declare` (POST), with their existing mailbox bodies. The application supplies
the account from `cloud_session`; a payload cannot set an account or authority.
The response includes that account, or null while signed out or verification is
pending. Account verification does not block the local listener.
There is no signed coordination envelope, caller key, adoption or idle prerequisite.
The surface shares the desktop CellStore and open conversation connection;
it forwards ordinary routes to `dispatch_universal_machine_route`, retaining
their Work, privacy and physical host-effect checks. Host and Origin validation
and the 64 KiB input bound remain on the loopback HTTP boundary.
Historical signed-authority verification remains an explicit migration/audit API;
normal startup does not bind it. Closing the desktop drains admitted coordination
requests before closing the graph; an unsettled request keeps its owner open.
The existing stdio/Session Link mailbox call uses this surface while it is
running. Only a refused TCP connection falls back to the existing closed-app
profile mailbox; HTTP refusals, timeouts and uncertain sends are never replayed.
The desktop observes the actual TCP client process and admits its own OS user,
preserving the other-people boundary without an application key. Process details
only label public messages/declarations; requests cannot supply them or an account.
Native declaration identity stays stable during sign-in.
Settings -> Workspaces uses the same surface: POST `/api/universal/workspace-roots` is the
owner's own workspace-roots route with the settings admission the route already expects, and
GET `/api/universal/workspace-roots-state` is the owner's current revision and registry digest.
The signed statement, caller key, nonce and canonical-instance manifest are gone with the key layer.

Backend design API: POST `/api/universal/workshop` with the existing browser session/CSRF headers and `{action:"data-api",function,args,root,scope,request_id}`. `workshop_api.py` implements `listAgentsWorking`, `listTasks`, `sendToBaboom`, `setTaskStatus`, `reassignTask`, `setTaskDelegate`, `queueTaskMessage`, `settleQueuedMessage`, `steerTask`, `addTaskReview`, and `resolveTaskReview`. Existing approve/decline routes retain their authority. Work roots are task IDs; declarations carry that Work root separately from the reply's message ID. Completion/review state comes from governed Work evidence, never a fabricated UI status. A bounded thread sets `messagesTruncated` and provides an existing MCP `read(since=0)` continuation; callers continue `next_since` and follow the Work references/reply chain.

Provider entry specifications all name `archhub-agent`: Claude/Codex/Antigravity/OpenCode use the native MCP owner, Goose's adopted ACP adapter supplies that same stdio extension, and BABOOM uses `ApplicationServer.shared_agent_mail`. A specification is not proof that an external client's configuration is installed or authenticated. Explicit selection never falls back to an unrelated provider. Goose/BABOOM task starts retain their existing built-in workflow; this API returns a named non-dispatch outcome for unsupported native dispatch. Codex completion lacks a discovered target process binding and remains uncertain; Antigravity requires actual matching client metadata. No all-six live-connectivity claim follows from the two-agent qualification.

The release builder requires a fresh `python -m tools.real_app_check.agentlink_release --profile-parent <lane> --output <receipt>` run: real OpenCode and packaged Goose exchange authenticated Workshop messages, both read one overlap notice, and OpenCode performs write/read/write/list. The same headless OpenCode session must read an explicitly trusted outside-cwd rule file and recover file work after a failed MCP call. No `--auto`, fixture replay, cached PASS or install is permitted. The governance loader accepts explicit `trustedDirectories`; the config hook allows those roots and agent rule folders while keeping the native gate. Failed native tool events pair their exact call's failed receipt; unrelated uncertain effects are never replayed. Pending native tasks post at most three thread follow-ups, then report uncertainty.

Every agent uses the existing archhub-agent MCP server:

- declare(task, paths, status, request_id): one plain task line, the founder request, exact files/folders/hosts, and working/blocked/done. Update when scope or status changes. Initial connector presence says task details pending until the agent declares its task; it never pretends to know the request.
- read(since=0): public shared notes plus current declaration nodes and their sockets. Continue with next_since while more; declarations_more/declarations_after continue large declaration pages. include_archived also reads finished/expired nodes. Normal reads do not write heartbeat revisions.
- send(to, text, reply_to=''): one public addressed note. Use another agent's sender_label, '*' for everyone, or 'founder' for every new finding, proposal or decision. reply_to is the coordination note's message id, so agreement remains in the same visible thread.

The app supplies identity from the existing authenticated local pipe and host session context. Tool arguments cannot override an agent/session/sender. Codex/OpenCode host metadata and connector-owned Claude/Gemini/Goose environment identifiers are namespaced under OS-observed process identity. Distinct connectors cannot overwrite each other's declaration. A connector's process exit or done state archives its node automatically; archived nodes remain readable.

Workshop shows Who is doing what, exact paths/status, and field sockets. Founder inbox is a filtered lens of the same public messages, with full findings reachable through the existing history reader. Home's working count reads current working declarations from that same source. An overlap posts one idempotent shared coordination note containing both declarations. Both agents can read it; they reply in its thread and split paths or finish/yield. This never locks the founder's work.

Stop/commit reminders are advisory. Private conversation contents and client data keep their existing audience; built-in agent notices carry source references rather than copying those replies into the public room. An addressed note is a recorded message, not proof that its recipient has executed a task.

At installation, the existing governance owner archives BOARD.md into its digest and retires its dispatch writers. Session Link's public chat commands already forward to this same mailbox in this patch; old bridge creation commands do not launch peer-chat pipes. Native task execution stays an application-owned action adapter, carrying a mailbox pointer and receiving its result through the same mailbox, not another reply pipe.

This lane does not install, touch live profiles, or claim installed activation. Backend release acceptance uses real isolated OpenCode and Goose MCP clients plus the HTTP/Work owner. The design owner and integration owner retain browser/plate verification and the installed cutover check.

Native task completion is confirmed only when provider discovery supplies an OS process identity matching the declaration's observed process generation. OpenCode supplies its process as runtimeId. Codex list_threads supplies no per-target PID; its task can be dispatched, but this adapter reports completion as uncertain/recipient_identity_unverified. A matching thread label alone never upgrades that result. Both agents can still declare, read and reply in Workshop.
