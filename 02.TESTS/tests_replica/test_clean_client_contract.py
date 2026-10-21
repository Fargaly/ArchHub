"""The client and the projector are two halves of one contract.

Every canvas court asserts what the projector emits; none had ever run the
browser client. The first real browser run found the projector emitting
control_catalog: [] where the client reads owner-matched control
presentations -- present, wrong shape, and invisible to both sides'
courts because neither half was ever measured against the other.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from nodelang.ui_runtime import UNIVERSAL_CANVAS_SCRIPT
from tests_replica.test_clean_server_visual_projection import (
    _project_current_visual,
    _provision_clean_runtime,
)


COURT_DIR = Path(__file__).parent / "client_court"
RENDERERS = (
    "renderStaticControls",
    "renderLibrary",
    "renderCanvas",
    "renderInspector",
    "renderToolbar",
)


def _node() -> str:
    found = shutil.which("node")
    if not found:
        pytest.skip("node is required to run the real client source")
    return found


def test_every_renderer_of_the_real_client_accepts_the_real_projection(
    tmp_path,
):
    """One verdict per renderer, from the client's own source.

    The client fails loud and renders in sequence, so a court asserting
    "it did not throw" goes green the moment the first unmet contract is
    satisfied and hides the four behind it. Each renderer is therefore run
    and recorded separately against one real projection, and the verdicts
    are asserted as a set. Failures after a genuine one are honest noise;
    a masked green is not.

    The demands come from the client source itself, never from a
    maintained list of expected keys -- such a list drifts exactly like
    the contract it exists to police, and would only court this session's
    reading of the client, which is the thing that was already wrong.
    """
    node = _node()
    built, _provider = _provision_clean_runtime(tmp_path)
    try:
        projection, _lens, _before, _after = _project_current_visual(built)
    finally:
        built.location.authority.store.close()

    client_path = tmp_path / "client.js"
    client_path.write_text(UNIVERSAL_CANVAS_SCRIPT, encoding="utf-8")
    projection_path = tmp_path / "projection.json"
    projection_path.write_text(json.dumps(projection), encoding="utf-8")

    completed = subprocess.run(
        [
            node,
            str(COURT_DIR / "run_renderers.cjs"),
            str(client_path),
            str(projection_path),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    report = json.loads(completed.stdout.strip().splitlines()[-1])

    assert report["loaded"], (
        "the real client source did not evaluate: %s" % report.get("error")
    )
    # A shim that invents what the server never served would turn real
    # failures into passes and make every verdict below meaningless.
    assert report["shim_honest"], (
        "the DOM shim answers selectors the server does not serve, so it "
        "is too permissive to trust"
    )
    # A value that is computed and reported but not asserted is not a guard,
    # it is a comment with extra steps. The refusal half of shim honesty --
    # that the shim rejects what a browser rejects -- was measured and
    # reported here and gated nothing, so a shim made permissive again would
    # have carried the failure in its own report while the court passed.
    unmet_shim = sorted(
        name for name, held in report["shim_checks"].items() if not held
    )
    assert unmet_shim == [], (
        "the DOM shim accepts operations a browser refuses (%s), so every "
        "verdict below is provisional" % ", ".join(unmet_shim)
    )

    verdicts = report["verdicts"]
    unmet = {
        name: verdicts.get(name, {}).get("error", "no verdict")
        for name in RENDERERS
        if not verdicts.get(name, {}).get("ok")
    }
    assert unmet == {}, (
        "the projector does not satisfy the client contract:\n%s"
        % "\n".join("  %s: %s" % item for item in sorted(unmet.items()))
    )
