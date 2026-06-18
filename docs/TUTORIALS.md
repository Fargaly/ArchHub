# ArchHub — guide-throughs (v1.6)

> Reference — not the roadmap; see [docs/ROADMAP.md](ROADMAP.md).

Step-by-step walkthroughs of every surface, with screenshots from the live
v1.6.1 app. For the deeper technical reference, see
[BACKEND_SPEC.md](BACKEND_SPEC.md), [USER_DATABASE.md](USER_DATABASE.md),
[PERMISSIONS.md](PERMISSIONS.md), [CLOUD_API.md](CLOUD_API.md), and
[BRAIN.md](BRAIN.md).

---

## 1. The home screen — sessions + status

When you open ArchHub you land on Home: every session as a card, and a status
bar across the top.

![Home screen with the top status bar](images/v1.6/home-account.png)

The top bar, left to right:

- **Model strip** — the model the AI will use. `Auto (router picks)` lets the
  router choose; click it to pin a specific model.
- **Brain chip** — `brain · 64s · 668f · ready` means the brain is live with 64
  skills and 668 facts. It shows real counts the moment the app opens.
- **Account chip** — `Signed in` (and your plan + remaining messages once the
  meter loads). Click it for account / sign-out. Covered in section 5.
- **Graph health** — `graph · healthy`. Click it to open the Self-Heal Inspector
  (section 7).

Each session card shows its state (idle / running), when it was last touched,
the title, a preview of the last message, and the hosts it used. Click any card
to open it. `+ new canvas` starts a fresh one; `Sync sessions` (section 6) pushes
them to the cloud.

---

## 2. The canvas — nodes, wires, run

Opening a session drops you on its canvas: a graph of typed nodes (hosts, AI
steps, filters, connector operations) wired together.

![A session canvas](images/v1.6/canvas.png)

- **Place** a node from the library (Cmd-K, or the Nodes rail on the left).
- **Wire** an output socket to an input socket — every wire is a real data
  segment, saved with the session.
- **Run** the graph (or a single node); results materialise on the canvas and
  persist.
- **Edit inline** — right-click a node, drag to rewire, edit params in the
  inspector. Every change auto-saves to the session.

The canvas is the materialised, inspectable surface; the composer (chat) drives
and edits it.

---

## 3. The Brain — your intelligence layer

The brain sits between what you say and what the AI does. Click the brain chip
to open it.

![The Brain view](images/v1.6/brain.png)

- **Top of mind** — the notes and decisions the brain is leaning on right now;
  brighter cards are more active. Each shows when it was learned and last used.
- **Project filter** — narrow to one project (BBC4, BH3D, P-674, P-679, …).
- **Search your brain** — find any memory by meaning, not just keyword.
- **Back up my brain** — encrypted sync of your brain to the cloud, so it follows
  you across machines.

You never have to manage the brain by hand. It grows as you work: every
successful result flows back in, so it gets smarter each session.

---

## 4. The Router — models + fallback

ArchHub routes each request to the right model and falls back automatically when
one is unavailable.

- Leave the model strip on `Auto (router picks)` and the router chooses based on
  the task (vision, modeling, quick edits, long reasoning).
- When a provider is out of credit or refuses a tool, the router switches and
  shows a short note under the answer (for example, `anthropic quota — switching
  provider…` then `answered by <model>`).
- The model strip reflects real state: the routed model, and any blocked
  providers greyed with the reason.

You always know which model answered and why — no silent black box.

---

## 5. Your account + the cloud

ArchHub Cloud holds your account, plan, usage, and (opt-in) brain backup. The
account chip on the top bar is your entry point.

![The account menu](images/v1.6/account-menu.png)

- **Signed in** with your email, plan (Solo / Studio / Firm), and remaining
  messages.
- Click the chip to open the account menu / Settings → Account for billing and
  sign-out.
- Sign-in is a real browser flow (magic-link or Google); your token is stored
  encrypted on the machine. See [CLOUD_API.md](CLOUD_API.md).

Your data lives on a persistent, encrypted cloud database that survives
redeploys — details in [USER_DATABASE.md](USER_DATABASE.md).

---

## 6. Sessions in the cloud

Sessions are saved locally as node graphs and can sync to the cloud so they
follow you between machines.

- On Home, click **Sync sessions** in the Sessions header. A `synced <when>`
  badge shows the last sync.
- Large attachments are skipped past a size cap so the sync stays fast (the skip
  is logged, never silent).
- Sessions still work fully offline; cloud sync is the cross-device layer.

---

## 7. Self-Heal Inspector

ArchHub repairs its own connections — host reconnects, connector reloads, graph
repairs — and the inspector shows them as a live timeline. Click the
`graph · healthy` chip to open it.

![Self-Heal Inspector](images/v1.6/self-heal.png)

- A **stat header** — total self-heals this session, when the last one happened,
  and counts by kind.
- A **recovery timeline** — each real recovery with its kind, target, detail, and
  time.
- An **honest empty state** — `No self-heals yet — connectors are healthy` when
  nothing has needed repair. It never shows fabricated rows.

---

## 8. Team + permissions

Open Settings → Team to manage your firm and teammates.

- **Start a firm**, then **invite teammates by email** with a role:
  owner, admin, or member.
- The **members list** shows each person's role; owners and admins can change
  roles or remove members; members are read-only.
- Seats are bounded by your plan. The model is enforced server-side — see
  [PERMISSIONS.md](PERMISSIONS.md).

---

## 9. Updating ArchHub

When a new release is available, ArchHub shows an **update banner** with a
one-click install that downloads the signed release and relaunches onto the new
version. You can also check from Settings. No manual download, no reinstall.
