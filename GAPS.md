2026-10-09 W8g

- Router: only `configuration.composer_model` is real today. The Workshop now shows one `Workshop model` control and per-task model/cost evidence. Per-job routing for separate inner-loop versus host-writing jobs remains unimplemented.
- Save as skill: removed the Workshop `Save as skill` button and `/api/universal/skills` `want:"save"` route. Existing `library.save_skill` writes a text skill file to a local path; it does not capture the admitted graph, prove Work COMPLETE server-side, reopen the graph, or provide a governed collision-safe graph write.
