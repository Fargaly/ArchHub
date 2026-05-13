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

- [ ] #P0 Frontend invite acceptance page — cloud_backend has the API; needs HTML (eng)
- [ ] #P0 Per-company quota enforcement in `proxy.chat_completions` (eng)
- [ ] #P0 Desktop UI captures profile fields on first run (firm, role, discipline) (eng)
- [ ] #P1 Owner-transfer flow in companies endpoints (eng)
- [ ] #P1 `marketplace_panel.py` rewire to call `marketplace_client` (cloud-backed) (eng)

## NEXT 30 DAYS

- [ ] #P1 Frontend Trust Center page (mirror `docs/TRUST_CENTER.md`) (docs)
- [ ] #P2 archhub.icns + Linux AppImage release artifacts (ops)
- [ ] #P2 Welcome email sequence (Resend templates) (docs)
- [ ] #P2 Customer admin dashboard (eng)

## LATER

- [ ] #P2 Civil 3D connector (blocked on Autodesk licence funding) (rnd)
- [ ] #P2 Email-match tightening on invite acceptance (require matching user email) (eng)
- [ ] #P2 SOC 2 Type I audit (triggered by first enterprise prospect with budget) (ops)

## Done — last 7 days

<!-- autopopulated by agents/roadmap_dispatcher.py — do not edit by hand -->
