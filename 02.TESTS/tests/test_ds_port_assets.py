"""The actual Studio asset owner serves DS without widening its public boundary.

Calls the real pure asset reader unbound: no server, session, graph or live service
is created. Compiled bytes are those produced by the lane's explicit build.
"""
from pathlib import Path

import pytest

from nodelang.application_server import _CleanAuthorityHttpServer


STUDIO = Path(__file__).resolve().parents[2] / "01.APP/nodelang" / "studio"


@pytest.mark.parametrize("name", ["ds/index.jsx", "compiled/ds-index.js"])
def test_actual_studio_asset_owner_serves_shared_design_system(name):
    expected = (STUDIO / name).read_bytes()
    assert expected, "the built design-system asset contains real source/code"
    actual = _CleanAuthorityHttpServer._clean_studio_asset(None, name)
    assert actual == expected


@pytest.mark.parametrize("name", [
    "../AUTHORITY.md",
    "ds/../../AUTHORITY.md",
    "compiled/../ds/index.jsx",
    "archive/atlas-engine.jsx",
])
def test_actual_studio_asset_owner_refuses_traversal_and_archived_modules(name):
    with pytest.raises(FileNotFoundError, match="Studio asset not found"):
        _CleanAuthorityHttpServer._clean_studio_asset(None, name)
