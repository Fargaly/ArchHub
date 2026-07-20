---
id: AgDR-0059
title: BABOOM recipient-encrypted cross-device briefs
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

AgDR-0058 deliberately keeps the BABOOM device relay metadata-only. That is
safe for notification and receipt, but cannot make BABOOM a useful steward on
another enrolled device: an opaque ticket does not carry the task it is meant
to help with.

The missing capability must not turn the relay into a second planner, move a
task body into a Cell atom, or silently lower device-key custody. A recipient
must be able to receive a brief only after authenticated device enrollment,
and the cloud must remain unable to read it.

## Decision

Add an encrypted-brief adapter associated with an existing BABOOM command.

1. The source device first creates the Cell command and the metadata relay
   ticket described in AgDR-0058. The command id, source device, target
   device, payload digest, and expiry are immutable binding inputs. A brief is
   not a Cell fact and cannot exist without that command.
2. Each enrolled device owns two distinct non-exporting P-256 keys in the
   Windows Platform Crypto Provider: its existing ECDSA signing key for DPoP
   and a new ECDH recipient key for briefs. The encryption public JWK and
   thumbprint are enrolled with the signed device identity. Production may not
   fall back to a software, exportable, or shared recipient key.
3. A source creates an ephemeral P-256 sender key, derives a one-time shared
   secret for the enrolled target recipient public key, uses HKDF-SHA-256 with
   a domain-specific salt, then encrypts the UTF-8 brief with AES-256-GCM.
   The recipient uses its CNG private ECDH key to derive the same secret and
   decrypts locally. The static recipient private key is never exported.
4. AES-GCM additional authenticated data is canonical JSON containing the
   command id, source device, target device, payload digest, recipient-key
   thumbprint, and expiry. The cloud validates envelope shape and ownership,
   but stores only ephemeral public JWK, salt, nonce, ciphertext, ciphertext
   digest, recipient key thumbprint, and timestamps. It never stores or logs
   plaintext, an AES key, an ECDH secret, or an executable instruction.
5. Only the authenticated source device may put, replace, or revoke an
   unclaimed brief. Only the authenticated target device may fetch the current
   envelope, and a target must claim the existing relay command before
   decryption. Decryption delivers information only; it does not grant a
   model, host, filesystem, publish, or communication capability.
6. Revocation removes the current server envelope and blocks future fetches.
   It cannot erase plaintext that a target already decrypted or a result the
   target separately committed. The UI and receipts must state that boundary
   plainly.

## Consequences

- BABOOM can send an actual internal brief to an enrolled device while cloud
  storage remains ciphertext-only.
- Confidential and secret classification remain denied until explicit
  data-class policy and recipient authority are approved; encryption alone is
  not a universal exfiltration exception.
- A TPM/provider capability failure denies encrypted remote brief handling. It
  is reported as unavailable rather than silently using a weaker key store.
- Device re-enrollment/key rotation requires revocation and an explicit new
  enrollment. Existing envelopes bound to the old recipient thumbprint cannot
  be recovered by the new key.
- Required courts cover CNG sender/recipient interoperability, public-key and
  thumbprint binding, ciphertext-only persistence, cross-user and wrong-device
  denial, AAD tampering, source-only revocation, and the already-decrypted
  revocation limitation.

## Implementation Evidence

`nodelang.cell_device_keys.WindowsCngRecipientKey` provides the separate
non-exporting P-256 ECDH recipient key. Its Windows court proves interoperable
SHA-256 key material with a Python ephemeral P-256 sender; the envelope court
proves AES-GCM round-trip and AAD/ciphertext tamper denial. The cloud relay
stores the envelope as ciphertext-only, permits source-side replacement or
revocation only while queued, and permits target fetch only after claim. The
companion converts a decrypted brief into the existing approval-gated model
request path; it does not auto-run the task or grant a host capability.

This remains `proposed` pending founder acceptance and an explicit live
enrollment/release gate.
