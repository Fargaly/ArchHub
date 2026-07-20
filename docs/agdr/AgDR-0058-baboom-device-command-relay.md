---
id: AgDR-0058
title: BABOOM device-bound command relay
timestamp: 2026-07-18
agent: Codex
session: baboom-node-native-steward
status: proposed
category: architecture
projects: [archhub, baboom]
supersedes: null
superseded_by: null
---

## Context

BABOOM has one persisted Universal Cell authority rooted at
`gm:node:orch_baboom_assistant`. It can observe work, surface a compact
thought, accept a reply, delegate bounded model work, and now retain a
device-addressed command lifecycle. The command journal must be replicated to
an enrolled device without turning the cloud into a second BABOOM authority.

ArchHub already has a cloud service with user authentication and durable
cross-device sync, plus Node Language contracts for TPM-backed device custody,
device-bound cloud sessions, DPoP proof, and replay detection. Replacing those
with a second BABOOM brain, an unauthenticated web queue, or raw task payloads
in cloud storage would violate the one-authority and privacy constraints.

## Decision

Add a bounded BABOOM relay under `/v1/baboom/` with these rules:

1. The Universal Cell command record remains the source of semantic truth.
   The relay is an adapter transport and has no independent task planner,
   model authority, or capability executor.
2. A device enrolls by proving possession of a P-256 public key after an
   authenticated, short-lived challenge. A later request must bind the bearer
   token to that enrolled device key through an RFC 9449-style DPoP proof,
   a one-time nonce, and a replay-recorded proof identifier.
3. The relay stores only user-owned device identity, command id, source/target
   device ids, redacted summary, payload digest, timestamps, lifecycle, and
   bounded receipt code. It never accepts task bodies, model prompts, raw
   screen/audio data, secrets, client data, or an executable instruction.
4. Only the owner can address their own enrolled target device; only that
   target can claim or settle a command. Source cancellation, expiry, and every
   terminal outcome are durable transport receipts.
5. Claiming is delivery acknowledgement, not permission to perform an effect.
   A target-side BABOOM adapter must still obtain the specific released
   capability and user approval before it writes, sends, publishes, or changes
   a host/model.
6. The source Cell command id and creation timestamp are device-authenticated
   relay metadata. Each device mirrors the same command root in its local Cell
   replica; the cloud timestamp is not permitted to replace the command identity.

## Consequences

- A bearer-token leak alone cannot submit, read, claim, or settle BABOOM relay
  work without the registered device proof key.
- A relay compromise exposes bounded metadata and, where the source explicitly
  shared it, ciphertext only. End-to-end encrypted payload delivery is
  governed separately by AgDR-0059 and does not alter command authority.
- The first delivery slice supports work notification and acknowledgement
  across devices. The companion client uses the existing non-exportable Windows
  CNG key, server-issued enrollment payload, and ArchHub desktop cloud-client
  token authority. It remains opt-in and inactive until an explicit live
  enrollment/release gate enables it.
- The relay ticket remains opaque. A real brief is a separate recipient-bound
  envelope under AgDR-0059, available only after the target claims the ticket.
- This does not claim mobile presence, meeting attendance, voice, screen
  capture, Notion writes, or autonomous remote action.
- Endpoint courts must prove cross-user isolation, unregistered-device denial,
  invalid/expired/replayed DPoP proof denial, target-only claim/settlement,
  idempotent submit, source-only cancellation, and metadata redaction.

## Implementation Evidence

The bounded command relay, Cell replica import, source receipt recovery, and
companion client courts pass. The recipient-encrypted extension is implemented
and covered under AgDR-0059; neither decision is live-enrolled or released in
the running companion without an explicit founder gate.
