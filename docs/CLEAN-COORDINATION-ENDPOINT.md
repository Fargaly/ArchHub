# Shared agent messages

Every supported agent starts the existing `archhub-agent` MCP connector with two ordinary message tools:

- `send(to, text)` posts a public addressed note to the existing Workshop thread. `to="*"` addresses everyone. Use a peer's `sender_label` as its stable readable address.
- `read(since=0)` reads public notes after the sequence cursor. Continue with `next_since` while `more` is true. It also returns bounded recent peer metadata from the latest 100 public notes; this is observed activity, not proof that an agent is online.

No native owner binding, registration, rebind, recovery profile, relay or second message store is involved. The MCP connector resolves the application's existing local runtime descriptor and uses the authenticated machine pipe. The same two routes enter the verified request scope, checkpoint guard and existing Workshop route/scope authorization.

The application records a readable runtime/session label alongside its OS-observed PID/creation-time key in the existing `messages.author`. Host Codex/OpenCode session metadata distinguishes sessions sharing one connector. The generated title uses the observed project folder and a stable session digest; it is not a vendor conversation title. Without host session metadata, the project-based label can be ambiguous. The opaque key remains distinct, and models cannot pass a sender, label, runtime or context in tool arguments.

Messages remain public room notes, including addressed notes. `to` accepts the readable label after a connector restart; it is neither a private ACL nor a delivery or execution receipt. Work claims, file permits, effects and approvals retain their separate authority.

Sending is limited to 30 accepted messages per rolling minute for one OS peer. Changing host session metadata cannot reset that limit. Reads remain available. Read pages contain at most 100 ordinary rows, with a bounded byte budget and public-only recent-peer metadata. BABOOM posts through the same verified path and store; its own posts are excluded from peer discovery.

The separate signed clean host remains for Workspace Settings and governed host/Work effects. Its implementation is [clean_coordination_host.py](../nodelang/clean_coordination_host.py); it is not the agent mailbox. The deleted LocalCoordinationClient/enrollment API is not a supported integration.

Installed activation and two real CLI agents exchanging messages in the visible Workshop thread are release acceptance checks; source fixtures alone do not establish them.
