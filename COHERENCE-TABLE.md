# COHERENCE-1 Claim Inventory

| Claim | True/false against code | Fix/evidence |
|---|---|---|
| Public domain is `archhub.io`, not `get.archhub.app`. | True | Installer uses `#define AppURL "https://archhub.io"` (`packaging/windows/setup.iss:13`); cloud defaults to `https://api.archhub.io` (`cloud_backend/config.py:297`); Docs install copy uses `archhub.io` (`nodelang/studio/studio-lm.jsx:10660`). |
| Docs Nodes page lists fixed categories. | False | Replaced with `buildDocsProjection` from `AH_LIBRARY` / live library (`nodelang/studio/studio-lm.jsx:10427`, `nodelang/studio/studio-lm.jsx:10471`); court asserts each catalogue node has a docs row (`tests_js/studio_design_screens.test.cjs:155`). |
| Docs Connectors page lists fixed supported hosts. | False | Replaced with host-registry rows from `LM_HOSTS` (`nodelang/studio/studio-lm.jsx:10441`, `nodelang/studio/studio-lm.jsx:10706`); court asserts registry row appears (`tests_js/studio_design_screens.test.cjs:158`). |
| Docs Router status is a real owner fact. | True after fix | Docs status reads `ARCHHUB_MODEL_READINESS`, the same readiness published by model reads (`nodelang/studio/studio-lm.jsx:538`, `nodelang/studio/studio-lm.jsx:10452`). |
| Docs Relay status is a real owner fact. | True after fix | Docs reads `readCloudPublishConsent`; Settings Permissions already reads and toggles the same owner (`nodelang/studio/studio-lm.jsx:10530`, `nodelang/studio/studio-lm.jsx:8593`). |
| Website says “bring your own key” / provider key wording. | False per lane wording rule | Replaced public copy with provider/credential wording (`nodelang/cell_website.py:1022`, `nodelang/cell_website.py:1420`, `nodelang/website_docs_text.py:129`). |
| Website/tutorial says most Settings shortcuts do nothing. | False/stale | Replaced with current limits that do not contradict implemented shortcuts (`nodelang/website_docs_text.py:135`). |
| Public website content is generated, not hand-written HTML. | True | Exporter reads `cell_website.py`/`website_docs_text.py`; `public_site/README.md:4` documents `site_export` as the source. |
