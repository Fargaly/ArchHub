---
slug: create-firm
title: Create your firm
prerequisites:
  - ArchHub is running and the brain daemon is alive.
  - You haven't already joined a firm on this device.
scope: user
replay_skill_id: sk-create-firm
freshness:
  source_paths:
    - personal-brain-mcp/src/personal_brain/firm.py
  last_verified: 2026-05-26
generator: manual
---

# Create your firm

> Become the admin of a new firm and invite a teammate. After this,
> anything you mark as firm-scoped (skills, tutorials, decisions) syncs
> across every seat in your firm.

A **firm** in ArchHub is the boundary that says "this knowledge belongs
to my company." You don't need a server — firms are peer-to-peer,
signed by a key that lives only on your device.

## Prerequisites

- ArchHub is running.
- The brain daemon is alive — the green dot in **Settings → Brain** is
  lit. (If it's not, see *Mint your first skill* for the brain-up
  command.)
- You haven't already joined a firm on this device. Check
  **Settings → Firm**. If a firm name is shown, leave it first.

## Steps

1. **Open Settings → Firm.** Click the gear (⚙) menu in ArchHub's
   top-right, then **Firm** in the side list. You should see a panel
   titled "No firm yet."

2. **Click "Create firm."** A short form asks for a firm name. Pick
   something memorable — your colleagues will see it on their invite.

3. **Submit the form.** ArchHub generates an ed25519 signing key on
   your device (private key never leaves your machine), then writes
   the firm identity to the brain. The panel switches to show:
   - Your firm name.
   - Your role: **admin**.
   - One seat counted (you).

4. **Click "Invite a teammate."** ArchHub mints a short-lived,
   cryptographically-signed invite token. The token is valid for 24
   hours by default and can be revoked.

5. **Copy the token and send it to your teammate.** They paste it
   into their ArchHub under Settings → Firm → "Accept invite."

6. **Watch the seat count increase.** Once your teammate accepts,
   their seat fragment syncs into your firm graph and the seat count
   in your panel ticks up to two.

## Expected outcome

In your ArchHub window:

- **Settings → Firm** shows your firm name at the top.
- Your role reads **admin**.
- The seat list shows you and any teammates who have accepted invites.

Your teammate, on their machine, sees the same firm name and a role of
**seat** (not admin — only the device that created the firm holds the
admin private key).

## Replay this tutorial

<!-- replay-button-placeholder
Renderer replaces this with a live "Replay" button that creates a
sandboxed test firm, invites a synthetic seat, and verifies the
end-to-end flow still works.
-->

## Why this exists

A firm is how ArchHub draws the line between "my notes" and "the
company's knowledge." Skills you mint as **firm-scoped** sync to every
seat. Tutorials minted from firm-scoped traces sync the same way. There
is no shared server in the middle — your firm graph is a peer-to-peer
mesh signed by your firm's key.

If you ever need to stop being a firm admin, the **Leave firm** button
drops your local membership. Other seats keep their record until they
sync next.

---

<details>
<summary>Engineering details (collapsed by default)</summary>

- Source: `personal-brain-mcp/src/personal_brain/firm.py::create_firm`
  and `create_invite_token`.
- Cryptography: ed25519 (via `cryptography` library) when available,
  HMAC-SHA256 fallback otherwise.
- Invite tokens are base64url-encoded JSON payloads + signature; they
  carry the firm public key so the joining device can verify offline.

</details>
