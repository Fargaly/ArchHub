"""Keep the cloud image's hash-locked packages in sync with its input manifest."""

import re
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version


ROOT = Path(__file__).resolve().parents[2]
CLOUD = ROOT / "03.TOOLS" / "packaging" / "cloud"


def target_environment():
    dockerfile = (CLOUD / "Dockerfile").read_text(encoding="utf-8")
    base = re.search(r"^FROM python:(\d+\.\d+\.\d+)[-@]", dockerfile, re.MULTILINE)
    assert base, "Expected the cloud image to pin a CPython patch version"
    version = base.group(1)
    return {
        "implementation_name": "cpython",
        "implementation_version": version,
        "platform_python_implementation": "CPython",
        "python_version": version.rsplit(".", 1)[0],
        "python_full_version": version,
        "os_name": "posix",
        "sys_platform": "linux",
        "platform_system": "Linux",
        "platform_machine": "x86_64",
    }


def requirement_lines(text):
    for line in re.sub(r"\\\r?\n", " ", text).splitlines():
        value = line.partition("#")[0].strip()
        if value:
            yield value


def check_lock(manifest, lock, target):
    pins = {}
    for line in requirement_lines(lock):
        requirement, *hashes = re.split(r"\s+--hash=", line)
        entry = Requirement(requirement.strip())
        name = canonicalize_name(entry.name)
        assert hashes and all(re.fullmatch(r"sha256:[0-9a-fA-F]{64}", h.strip()) for h in hashes), (
            f"{name}: missing or invalid SHA-256"
        )
        specs = list(entry.specifier)
        assert len(specs) == 1 and specs[0].operator == "==" and "*" not in specs[0].version, (
            f"{name}: expected one exact version"
        )
        if entry.marker is None or entry.marker.evaluate(target):
            assert name not in pins, f"{name}: duplicate active pin"
            pins[name] = Version(specs[0].version)

    for line in requirement_lines(manifest):
        requirement = Requirement(line)
        if requirement.marker is not None and not requirement.marker.evaluate(target):
            continue
        name = canonicalize_name(requirement.name)
        assert requirement.url is None, f"{name}: the cloud manifest must specify a version constraint"
        assert name in pins, f"{name}: missing from the cloud lock"
        assert pins[name] in requirement.specifier, (
            f"{name}: locked {pins[name]} does not satisfy {requirement.specifier}"
        )


def test_cloud_lock_matches_manifest():
    check_lock(
        (ROOT / "requirements-cloud.txt").read_text(encoding="utf-8"),
        (CLOUD / "requirements.lock").read_text(encoding="utf-8"),
        target_environment(),
    )


VALID_HASH = "--hash=sha256:" + "a" * 64


@pytest.mark.parametrize(("manifest", "lock", "problem"), [
    ("uvicorn>=0.46,<1", f"fastapi==0.136.1 {VALID_HASH}", "uvicorn: missing"),
    ("uvicorn>=0.46,<1", "uvicorn==0.46.0", "uvicorn: missing or invalid SHA-256"),
    ("uvicorn", f"uvicorn==0.46.0 {VALID_HASH} --hash=sha256:no", "uvicorn: missing or invalid"),
    ("cryptography>=50.0.2,<51", f"cryptography==50.0.1 {VALID_HASH}", "does not satisfy"),
    ("uvicorn>=0.46,<1", f"uvicorn==1.0.0 {VALID_HASH}", "does not satisfy"),
])
def test_rejects_drift(manifest, lock, problem):
    with pytest.raises(AssertionError, match=problem):
        check_lock(manifest, lock, target_environment())


def test_uses_linux_markers_and_normalized_names():
    manifest = "Rpds_Py>=0.30; sys_platform == 'linux'\npywin32; sys_platform == 'win32'"
    check_lock(manifest, f"rpds-py==0.30.0 {VALID_HASH}", target_environment())
