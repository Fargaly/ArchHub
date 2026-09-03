# Signoff — Settings → Brain panel

**Date frozen**: 2026-05-25
**AgDR**: [AgDR-0044](../../../agdr/AgDR-0044-personal-brain-mcp.md) + [AgDR-0045](../../../agdr/AgDR-0045-settings-brain-unified.md)
**Founder signoff**: 2026-05-25 — "sign off and go"
**Prototype source**: [index.html](./index.html)

This prototype IS the spec per PROTOTYPE-IS-CONTRACT MANDATE. The
shipped Settings → Brain JSX must mirror it 1:1. Material differences
are bugs; deviations require a new AgDR.

## Pixel-anchored sections (read-only after sign-off)

1. **Header** — title + status pulse (live/degraded/offline)
2. **Master switch + daemon controls** (Enable Brain · Restart · Stop · View log · Autostart toggle)
3. **Live stats** — 4 tiles: Skills · Facts · MCPs Wired · Uptime
4. **Connected agents** — per-client rows with logo + path + status + toggle
5. **Rescan + Auto-Wire** button + Preview config files
6. **Sync across devices** — mode dropdown · folder picker · spatial-Speckle toggle
7. **Tuning & safety** — R1 R2 R3 R4 toggles · LLM critic picker
8. **Privacy & secrets** — secret refs only · redaction on promote · audit log
9. **Danger zone** — Export · Clear cache · Reset brain

## Future sections to add (not part of this signoff, separate AgDR required)

- Settings → Firm (Slice 9-11 surfaces) — Create firm · Invite · Seats list
- Settings → Communities (Slice 14 surfaces) — Browse · Subscribe · Reputation panel

These currently exist as MCP tools but have no UI; opening them in a
separate signed prototype keeps the surface boundaries clean.
