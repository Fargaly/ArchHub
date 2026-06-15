"""Sanity gate — the web (Astro) Dockerfile build base must satisfy the Node
version contract declared in web/package.json `engines.node`.

Root cause this locks out (go-live regression): the web image built on
`node:20-alpine` while package.json pinned `astro: ^6.x`. Astro 6 dropped Node
18 AND 20 (min 22.12.0), so `npm run build` failed in the build stage. The fix
bumped the base to `node:22-alpine` and `engines.node` to `>=22.12.0`. This test
makes the two move in lock-step forever: if someone bumps `engines.node` (or the
astro major) without bumping the Dockerfile base — or downgrades the base — the
contract breaks and this test goes red BEFORE a broken image ships.

Pure stdlib + filesystem; no backend imports, no network, no Docker daemon.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

# cloud_backend/tests/ -> repo root -> web/
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_WEB = _REPO_ROOT / "web"
_DOCKERFILE = _WEB / "Dockerfile"
_PACKAGE_JSON = _WEB / "package.json"


def _node_major_from_dockerfile(text: str) -> int:
    """The major version in the build-stage `FROM node:<major>...` line."""
    m = re.search(r"^FROM\s+node:(\d+)", text, re.MULTILINE)
    assert m, "web/Dockerfile must have a `FROM node:<major>...` build stage"
    return int(m.group(1))


def _engines_min_major(pkg_text: str) -> int:
    """The minimum Node major from package.json engines.node (e.g. '>=22.12.0'
    -> 22)."""
    import json
    pkg = json.loads(pkg_text)
    spec = (pkg.get("engines") or {}).get("node") or ""
    m = re.search(r"(\d+)", spec)
    assert m, f"package.json engines.node must pin a version, got {spec!r}"
    return int(m.group(1))


@pytest.fixture
def dockerfile_text() -> str:
    assert _DOCKERFILE.exists(), f"missing {_DOCKERFILE}"
    return _DOCKERFILE.read_text(encoding="utf-8")


@pytest.fixture
def package_text() -> str:
    assert _PACKAGE_JSON.exists(), f"missing {_PACKAGE_JSON}"
    return _PACKAGE_JSON.read_text(encoding="utf-8")


def test_dockerfile_node_base_meets_engines_floor(dockerfile_text, package_text):
    """The Dockerfile build base major >= the engines.node minimum major."""
    base = _node_major_from_dockerfile(dockerfile_text)
    floor = _engines_min_major(package_text)
    assert base >= floor, (
        f"web/Dockerfile builds on node:{base} but package.json engines.node "
        f"requires >= {floor}. Bump the Dockerfile FROM base to node:{floor}"
        f"-alpine (this is the exact go-live break that node:20 caused)."
    )


def test_astro6_requires_node22_floor(package_text):
    """Guard the specific contract: while astro is v6+, the engines.node floor
    must be at least 22 (Astro 6's documented minimum is 22.12.0)."""
    import json
    pkg = json.loads(package_text)
    astro_spec = (pkg.get("dependencies") or {}).get("astro") or ""
    m = re.search(r"(\d+)", astro_spec)
    if not m:
        pytest.skip("astro not a direct dependency / unpinned")
    astro_major = int(m.group(1))
    floor = _engines_min_major(package_text)
    if astro_major >= 6:
        assert floor >= 22, (
            f"astro {astro_spec} needs Node >= 22.12.0, but engines.node floor "
            f"is {floor}. Astro 6 dropped Node 18 and 20."
        )


def test_dockerfile_not_pinned_to_dropped_node(dockerfile_text):
    """Belt-and-braces: the base is never one of the Node majors Astro 6 dropped
    (18 or 20) — the literal regression we are guarding against."""
    base = _node_major_from_dockerfile(dockerfile_text)
    assert base not in (18, 20), (
        f"web/Dockerfile base node:{base} is a version Astro 6 dropped — "
        f"`npm run build` will fail. Use node:22-alpine or newer."
    )
