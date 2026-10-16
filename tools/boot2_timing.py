"""Paired BOOT2 timing on an owned synthetic clean runtime, never live state."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import time

from tests_replica.test_clean_server_visual_projection import (
    _issue_clean_session, _json, _provision_clean_runtime, _start_clean_server,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="archhub-boot2-") as directory:
        os.environ["LOCALAPPDATA"] = directory
        built, provider = _provision_clean_runtime(Path(directory))
        authority = built.location.authority
        _issue_clean_session(built, token="boot2-timing", csrf="boot2-timing-csrf")
        revision = authority.store.revision
        cells = len(authority.store.snapshot().cells)
        timings = []
        derive = __import__("nodelang.application_server", fromlist=["derive_clean_scope_interactions"])
        lens = __import__("nodelang.unified_application_lens", fromlist=["_catalogue"])
        originals = [(derive, "derive_clean_scope_interactions"), (lens, "_catalogue")]
        for module, name in originals:
            function = getattr(module, name)

            def measured(*positional, _function=function, _name=name, **keywords):
                start = time.perf_counter()
                try:
                    return _function(*positional, **keywords)
                finally:
                    timings.append({"phase": _name, "seconds": time.perf_counter() - start})

            setattr(module, name, measured)
        start = time.perf_counter()
        server = _start_clean_server(built, provider)
        constructed = time.perf_counter()
        try:
            status, home = _json(server.url, "/api/universal/canvas?screen=home", token="boot2-timing")
            home_at = time.perf_counter()
            ready = getattr(server, "_boot_ready", None)
            if ready is not None:
                assert ready.wait(30)
                assert server._boot_error is None
            warmed = time.perf_counter()
            # On baseline the selector is absent: retain the explicit refusal,
            # then measure the full canvas it actually makes Home wait for.
            baseline_status = status
            if status != 200:
                status, home = _json(server.url, "/api/universal/canvas", token="boot2-timing")
                home_at = time.perf_counter()
            assert status == 200, home
            assert authority.store.revision == revision
            report = {"fixture": "synthetic clean runtime; no live store copied",
                      "real_audit_cells": 6014884, "fixture_cells": cells,
                      "documented_cell_scale_factor": 6014884 / cells,
                      "scaling_limit": "Cell ratio only; no linear latency extrapolation or installed-app claim",
                      "constructor_start_seconds": constructed - start,
                      "home_ready_seconds": home_at - start,
                      "warmup_complete_seconds": warmed - start,
                      "home_selector_status": baseline_status,
                      "revision_before": revision, "revision_after": authority.store.revision,
                      "phases": timings}
            Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2), flush=True)
        finally:
            server.close()
            authority.store.close()


if __name__ == "__main__":
    main()
