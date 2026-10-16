# Website and documentation source inventory

This table names source ownership. Court receipts and exact file hashes are in RESULT-COHMAIN2.md; no installed-app or live deployment verdict is implied.

| Surface | Source | Check |
| --- | --- | --- |
| Public website and documentation export | `nodelang/site_export.py`, graph composition in `nodelang/cell_website.py` | `tests_replica/test_website_public_routes.py`, `test_website_truth.py` |
| Node docs and tutorial content | `site_export.project_documentation` / `documentation_pages`, from the published catalogue | `tests_replica/test_done_needs_docs.py`; mounted Studio docs court |
| In-app Docs | `studio-lm.jsx` presents server `canvas.documentation`; no parallel prose/index store | `tests_js/studio_design_screens.test.cjs`, `studio_docs_coherence.test.cjs` |
| Connector docs | Operation catalogue plus selected `HOST_ARTIFACTS.json`; live app registry remains separate | `test_website_truth.py::test_connector_docs_use_reviewed_index_and_never_infer_a_live_host` |
| Documentation build | `site_export.documentation_build_id`: `BUILD_ID` or `BUILD_METADATA.json` | metadata-file and rendered header/body courts in `test_website_truth.py` |
| Public claims | Source-qualified current capability text, banned-claim admission on rendered export | `test_website_truth.py`, rendered and sealed p4 court |
| Public domain and installation | `https://archhub.io`, released download record; app provider connection | `test_website_public_routes.py`, `studio_rail_shortcuts.test.cjs` |
| Upgrade leftovers | Installer package excludes legacy docs; exact known v1 bytes archived on update | `test_website_package_docs.py` |

Removed inventory claims: Docs Router/Relay readiness sections and references to deleted `website_docs_text.py`; stale literal line numbers and pinned September build text. Public deployment remains owned by 717.
