# Contributing to ArchHub

Thanks for contributing.

## Setup

### Desktop app

```bash
git clone https://github.com/Fargaly/ArchHub
cd ArchHub
pip install -r app/requirements.txt
python app/main.py
```

### Relay (optional)

```bash
cd relay
npm install
npm run dev
```

## Project layout

- `app/` — desktop app (PyQt6), workflow engine, skill system, provider clients.
- `relay/` — cloud relay APIs and Supabase integration.
- `payload/` — host-side bridge/connectors and source integrations.
- `agents/` — automation and task runners.
- `docs/` — user/developer documentation.
- `tests/` — python test suite.

## Contribution types

### 1) Skills

- Add or improve seed skills in `app/skills/`.
- Keep prompts explicit and deterministic where possible.
- Include a short usage example in your PR description.

### 2) Connectors

- Keep connector APIs schema-driven and minimal.
- Prefer additive changes to avoid breaking existing skills.
- Document host-specific assumptions in docs.

### 3) LLM providers

- Add provider clients under `app/llm_providers/`.
- Keep auth/key handling consistent with existing providers.
- Ensure graceful fallback behavior.

### 4) Docs

- Keep user-facing copy concrete and verifiable.
- Align pricing statements with `docs/PRICING_STATUS.md`.

## Coding expectations

- Make focused PRs with one primary intent.
- Avoid unrelated refactors.
- Preserve backward compatibility for existing skills where practical.
- Update docs when behavior changes.

## Testing

Run relevant checks before opening a PR:

```bash
pytest -q
```

If you changed relay code:

```bash
cd relay
npm test
```

If environment limitations prevent a full run, note that explicitly in the PR.

## Pull requests

Include:

- What changed
- Why it changed
- How you tested
- Any known limitations

For larger features, open an issue first to align direction.
