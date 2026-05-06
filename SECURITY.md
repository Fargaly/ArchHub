# Security policy

ArchHub runs LLM-generated code against the user's local AEC tools, holds
provider API tokens, and (optionally) syncs Skills to a private GitHub
repo. That makes this a security-sensitive desktop application — not a
toy script. This document describes how we treat security and how to
report a problem.

## Reporting a vulnerability

**Do not** open a public GitHub issue for security problems.

- Use **Private vulnerability reporting** on this repository:
  https://github.com/Fargaly/ArchHub/security/advisories/new
- Or email: `security@archhub.app` _(active once domain is registered;
  in the interim, fall back to the Private Vulnerability Reporting flow
  above)_.

Include:
- ArchHub version (`⚙ → About` shows the commit hash).
- Operating system + version.
- Steps to reproduce.
- Impact assessment (what an attacker could achieve).
- Any working PoC.

We aim to acknowledge within **3 business days** and ship a fix within
**14 days** for high-severity issues. Coordinated disclosure is
expected; we credit reporters in the release notes unless they ask
otherwise.

## Threat model

ArchHub's threats split into four buckets:

### 1. Local execution of LLM-generated code

ArchHub deliberately runs code emitted by an LLM inside the user's
modelling applications (Revit C# via Roslyn, Blender Python via `bpy`,
3ds Max via `pymxs`, AutoCAD C# via Roslyn). This is the **product**;
it cannot be removed without removing the product.

Mitigations:
- **Tool whitelisting per Skill.** Each Skill's
  `llm.complete_with_tools` node carries an `allowed_tools` list. The
  LLM cannot call tools outside that list during a Skill run.
- **Transactions.** Every Revit / AutoCAD edit is wrapped in a named
  Transaction. The user can Undo any Skill run from the host
  application's Undo history.
- **Pre-flight reachability check.** Connectors are only invoked when
  the matching host application is running and reachable. Prevents the
  LLM from emitting code into a vacuum and falling back to "paste this
  yourself" prompts.
- **Connector ports listen on `localhost` only.** RevitMCP /
  BlenderMCP / Max MCP / AcadMCP HTTP listeners bind to `127.0.0.1`,
  not `0.0.0.0`. Same-host attackers are still in scope; remote
  attackers are not.

Out of scope: defending against an LLM that the user has explicitly
told to wipe their model. ArchHub assumes the LLM is acting in good
faith on behalf of the user; it does not sandbox the host application
itself.

### 2. Credentials at rest

Provider API keys (Anthropic / OpenAI / Google / OpenRouter / Speckle /
firm relay token) live on the user's machine. ArchHub never sees them
during normal operation; the `secrets_store` module reads them from
the OS keyring on demand.

Storage:
- **Primary:** Windows Credential Manager via the `keyring` Python
  package. Encrypted at rest by Windows DPAPI; tied to the user's
  Windows logon session.
- **Fallback:** an XOR-obfuscated file at
  `%LOCALAPPDATA%\ArchHub\secrets.dat`. Used only when `keyring`
  cannot be loaded (rare). The `_PAD` constant in `secrets_store.py`
  is intentionally documented as **not secure**; it exists to keep
  casual filesystem readers from grepping plaintext keys, not to
  defeat a determined attacker. **If you depend on this fallback, you
  are operating outside our threat model.**

ArchHub never logs API keys. Stack traces from LLM provider clients
are surfaced in the chat with the body redacted by the SDK before we
see it.

### 3. Cloud Skill sync

When the user enables cloud sync, ArchHub creates a **private**
`<owner>/ArchHub-data` repo on their GitHub account and clones it
locally. Pushes happen via the user's existing `gh auth login`
credentials — ArchHub never holds a long-lived GitHub token in its own
storage.

- The data repo is created **private by default**. ArchHub never sets
  it public, and never adds collaborators.
- Skill JSON files contain workflow definitions. They do **not**
  contain API keys, host secrets, or render outputs.
- The user can browse, audit, fork, or delete the data repo from
  GitHub directly at any time.

### 4. Code-supply-chain integrity

The desktop app is shipped as an Inno Setup `.exe` installer built by
GitHub Actions on every `v*.*.*` tag. We rely on:

- **Reproducible CI.** `installer/setup.iss` is checked into the repo;
  the `Release` workflow runs it on a clean `windows-latest` runner.
  Anyone can audit the build by reading the workflow + script.
- **Signed releases (in progress).** Until our SignPath Foundation
  application is approved, installers are unsigned. Windows
  SmartScreen will warn on first run. The hash of every release `.exe`
  is published in the Releases page and can be compared against the
  CI build artifact.
- **Vendored Python source.** The installer ships ArchHub's `.py`
  files plus a `requirements.txt` the user's `pip` resolves into
  their `--user` site-packages. Direct dependencies are pinned in
  `requirements.txt`; transitive dependencies are validated by
  Dependabot.
- **Dependabot + CodeQL.** Both run on every push and weekly. High-
  severity findings block merges via branch protection (planned).

## What we do — concretely

| Surface | Control |
|---|---|
| Repo visibility | Public, MIT-licensed source. Private repo for end-user Skill data. |
| Secret detection | GitHub Secret Scanning + Push Protection enabled at the org level. |
| Dependency CVEs | Dependabot alerts + auto-update PRs. Weekly scans on pip / nuget / GitHub Actions. |
| Static analysis | CodeQL on Python + JavaScript, security-extended query suite. |
| Code-signing | SignPath.io Foundation (Authenticode) — application pending. |
| HTTPS | Enforced on `fargaly.github.io/ArchHub/` and (future) `archhub.app`. |
| Auth handling | Delegated to the user's `gh` CLI / OS keyring. ArchHub never persists tokens itself. |
| LLM connectivity | Direct from the user's machine to the chosen provider — no ArchHub-operated middlebox in the BYO-key path. |
| Cloud relay (Studio) | Rate-limited per-user; firm-scoped tokens; audit log retained 90 days; encrypted at rest. _Built once $5k MRR justifies it; not running yet._ |

## Operational hardening (this repo)

- Branch protection on `main`: required status checks (CodeQL pass,
  CI green), no direct push for non-admins (planned once external
  contributors join).
- Signed commits encouraged (not mandatory while we're a single-dev
  project).
- All releases produced by the `Release` GitHub Actions workflow with
  read-only checkout token + scoped `contents: write` permission for
  publishing release assets only.

## What we do **not** claim

- We do not ship a sandbox for the user's modelling applications.
- We do not encrypt the user's local Skill cache (it lives inside a
  Git checkout that inherits NTFS ACLs from `%LOCALAPPDATA%`).
- We do not vet the content of LLM responses for prompt-injection
  payloads. If your modelling project file contains attacker-
  controlled text, an LLM may execute that text as instructions. Treat
  Skills the same way you'd treat a Grasshopper definition someone
  emailed you: don't run untrusted ones blind.

## Update policy

Security fixes are tagged as `vX.Y.(Z+1)` patch releases and pushed
within 14 days of confirmed reports. The in-app updater fetches them
automatically via GitHub Releases. Users can verify the local commit
hash matches a tagged release at any time via `⚙ → About`.

---

_Last reviewed: 2026-05-06. Next review: when v1.0 ships or after any
material change to the threat surface (e.g. when the cloud relay goes
live)._
