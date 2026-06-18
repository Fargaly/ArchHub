# Team Roles and Permissions

> **Reference — not the roadmap.** `docs/ROADMAP.md` is the single source of
> truth for plans and milestones. This page describes how teams, roles, and
> seats work **today** (audited 2026-06-18 against `cloud_backend/companies.py`
> and the desktop Team controls).

A **company** is a team workspace — a practice, a studio, or a firm. One person
owns it, pays one subscription, and invites teammates by email. This page
explains who can do what.

## The three roles

There are three roles, in order of authority:

**owner > admin > member**

| You can… | owner | admin | member |
| --- | :---: | :---: | :---: |
| Use the workspace (chat, quota, AI) | yes | yes | yes |
| See the team and its members | yes | yes | yes |
| Switch into the workspace | yes | yes | yes |
| Invite a teammate (admin or member) | yes | yes | no |
| Set the seat count | yes | yes | no |
| Buy hosted-AI credits for the team | yes | yes | no |
| Change the team's AI mode | yes | yes | no |
| Edit company details (name, billing) | yes | no | no |
| Remove a member | yes | no | no |
| Transfer ownership | yes | no | no |

- **Owner** — exactly one per company, created automatically when the company is
  made. The owner is the only role that can edit company details, remove members,
  or hand the company to someone else.
- **Admin** — a trusted teammate who can grow and run the team (invite people, set
  seats, manage AI), but cannot remove members, edit billing, or transfer
  ownership.
- **Member** — full use of the workspace, read-only on the team itself.

## Seats per plan

Each plan ships with a starting seat count and a floor it cannot go below.
Seats move à la carte from the starting point — never below the minimum.

| Plan | Starts with | Minimum | Maximum |
| --- | :---: | :---: | :---: |
| Solo | 1 seat | 1 | 1 |
| Studio | 5 seats | 1 | unlimited |
| Firm | 10 seats | 10 | unlimited |

Solo is a single-person plan and does not create a team. Studio and Firm are
team plans, each with a company workspace. When an owner or admin changes the
seat count, the backend clamps it to the plan's floor automatically.

## How invites work

1. An **owner or admin** creates an invite for a specific email address and picks
   the new person's role — `admin` or `member`. An invite can never create a new
   owner.
2. The invite is **emailed** to that address as a link, and the team also gets a
   copy-able invite token in case email is not set up.
3. The invited person signs in and accepts. **Acceptance only works if their
   signed-in email matches the address the invite was sent to.** A forwarded
   link, a screenshot, or a leaked token cannot be used by anyone else — this is
   what stops a stranger from burning a paid seat.
4. Invites are **single-use** and **expire**. An accepted or expired invite
   cannot be reused.

**Seats are protected against over-inviting.** When the team is at its seat
limit, new invites are refused. The seat check counts current members *plus*
outstanding (unaccepted) invites, so you cannot send ten pending invites that
would all squeeze past a five-seat limit once accepted.

## Removing someone and handing over the team

- **Remove a member** — only the **owner** can do this. The owner cannot remove
  themselves (that would leave the team with no owner).
- **Transfer ownership** — only the **owner** can do this, and only to someone who
  is already a member. After the transfer, the new person becomes owner and the
  previous owner stays on as an **admin** (never dropped from the team). This is
  how an owner who wants to leave hands over first, then leaves.

## Billing follows your active workspace

You can belong to more than one team. At any moment you have one **active
workspace** — either your personal account or one of your teams. When a team is
active, that team's seat count, AI mode, message quota, and hosted-AI credits
apply to what you do. When no team is active, your personal account applies. You
switch your active workspace from the desktop or via the API.

## Where you manage this

- **In the cloud (the source of truth):** the company endpoints under
  `/v1/companies/*` — create a company, list your memberships, invite, accept,
  remove, transfer, set seats, and switch active workspace. See
  `docs/CLOUD_API.md` for the endpoint list and `docs/BACKEND_SPEC.md` for the
  exact rules.
- **In the desktop app:** ArchHub → Settings → Brain holds the team controls —
  create or join a firm, create an invite token (shown to owners/admins), and
  leave a firm. ArchHub → Settings → Account shows your signed-in identity and
  plan. The web dashboard at `https://archhub-cloud.fly.dev/dashboard` also shows
  your account and, when you belong to a team, the team roster.

The desktop controls call the same `/v1/companies/*` endpoints described above —
there is one roles model, enforced on the server, behind every surface.
