# ArchHub roadmap (autonomous-loop source)

> Machine-readable seed for `agents/roadmap_source.py`.
> Each `- [ ]` item is an OPEN backlog item the dispatcher will pick up.
> Tag with `#P0` / `#P1` / `#P2` for priority. Department hints in
> parentheses route the item to the right dept (`eng`, `qa`, `docs`,
> `ops`, `rnd`).
>
> When an item ships, MOVE it to "Done — last 7 days" and the loop will
> mark its hash in `agents/state/completed_roadmap_ids.txt` on the next
> tick.

## NEXT 7 DAYS

- [x] #P0 Frontend invite acceptance page — `GET /invite` in cloud_backend/main.py, magic-link PKCE → accept (eng) — shipped 2026-05-17
- [x] #P0 Per-company quota enforcement in `proxy.chat_completions` (eng) — already shipped v1.3.3 (quota_remaining_for_actor / increment_usage_for_actor, test_company_quota.py); confirmed 2026-05-17
- [x] #P0 Desktop UI captures profile fields on first run (firm, role, discipline) (eng) — shipped 2026-05-17
- [x] #P1 Owner-transfer flow in companies endpoints (eng) — POST /v1/companies/{cid}/transfer-ownership, shipped 2026-05-17
- [x] #P1 `marketplace_panel.py` rewire to call `marketplace_client` (cloud-backed) (eng) — _load_catalog/_pack_to_item + cloud install path, local seed fallback; shipped 2026-05-17

## NEXT 30 DAYS

- [x] #P1 Frontend Trust Center page (mirror `docs/TRUST_CENTER.md`) (docs) — landing/security.html, linked from index footer; shipped 2026-05-17
- [x] #P2 archhub.icns + Linux AppImage release artifacts (ops) — `scripts/build_icon.py` packs PNG-payload `.icns` (ic07–ic14, 32–1024px) + verifies; `build-linux.yml` rewired AppDir→appimagetool `.AppImage`; `packaging/linux/{AppRun,ArchHub.desktop}`; shipped 2026-05-17
- [x] #P2 Welcome email sequence (Resend templates) (docs) — send_welcome_email + _wrap shell, fires on new-account register; shipped 2026-05-17
- [x] #P2 Customer admin dashboard (eng) — GET /dashboard, magic-link auth → account/plan/quota + companies + team roster; shipped 2026-05-17

## LATER

- [ ] #P2 Civil 3D connector (blocked on Autodesk licence funding) (rnd)
- [x] #P2 Email-match tightening on invite acceptance (require matching user email) (eng) — `accept_invite` returns `403 invite_email_mismatch` unless the signed-in user's email equals the invited address (both normalized); `/invite` page surfaces a clear message; +2 tests (mismatch rejected, case-insensitive match); shipped 2026-05-17
- [ ] #P2 SOC 2 Type I audit (triggered by first enterprise prospect with budget) (ops)

## Done — last 7 days

<!-- autopopulated by agents/roadmap_dispatcher.py — do not edit by hand -->
