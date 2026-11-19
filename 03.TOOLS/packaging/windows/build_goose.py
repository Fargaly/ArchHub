"""Build goose.exe from the pinned Goose source plus ArchHub's patches, and write its receipt.

Upstream builds Windows the same way (Justfile release-windows, bundle-windows.yml):
cargo build --release --target x86_64-pc-windows-msvc -p goose-cli --bin goose.
The source is fetched by exact commit into --source, which must be empty or absent.
ArchHub's own lock, goose/Cargo.lock, must match the pin's cargo_lock_sha256 and replaces upstream's;
--seed-lock writes upstream's lock there once, only if its bytes are the pinned ones. --locked: no dependency moves.
Founder rule F5: an open-source product never ships unmodified, so an empty patch list refuses.
goose-pin.json is the one typed declaration: the goose.source node, whose params hold the pin and the ordered patches.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
if str(HERE.parents[1]) not in sys.path:
    sys.path.insert(0, str(HERE.parents[1]))   # 03.TOOLS (repo) or the release snapshot root: tools/ is beside packaging/
from tools.pipeline.strict_check import idle_or_away as desk_idle_or_away  # noqa: E402 - the presence guard heavy builds use


def idle_or_away():
    """R100 presence: a GitHub Actions runner has no founder at its desk, so it is away. Anywhere else the desk's own
    input age decides, and input that cannot be read counts as present (the build refuses on the founder's machine)."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return True
    return desk_idle_or_away()
PIN = HERE / "goose-pin.json"
OURS = HERE / "goose"


def sha(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def inputs(pin_path=PIN):
    """The engine inputs a build came from; staging refuses a cached build made from other ones."""
    return {"pin_sha256": sha(pin_path), "build_script_sha256": sha(__file__)}


def load_pin(pin_path=PIN):
    """The goose.source node's typed params: the pinned source, toolchain flags, lock digest and ordered patches."""
    node = json.loads(Path(pin_path).read_text(encoding="utf-8"))
    if not isinstance(node, dict) or node.get("id") != "goose.source" or not isinstance(node.get("params"), dict):
        raise ValueError("goose-pin.json must be the goose.source node with typed params")
    params = node["params"]
    if not isinstance(params.get("patches"), list) or not all(isinstance(name, str) for name in params["patches"]):
        raise ValueError("goose.source params.patches must be an ordered list of patch file names")
    return params


def patches(folder=OURS, pin_path=PIN):
    """The ordered patches: [[name, sha256], ...]. Order is part of the build. A listed file that is missing refuses."""
    names = load_pin(pin_path)["patches"]
    for name in names:
        if "/" in name or "\\" in name or name.startswith(".") or not name.endswith(".patch"):
            raise ValueError("Goose patch names must be plain .patch files: %s" % name)
    return [[name, sha(Path(folder) / "patches" / name)] for name in names]


def archhub_patches(folder=OURS, pin_path=PIN):
    """The patches a shippable build applies: never empty (F5, no stock Goose)."""
    series = patches(folder, pin_path)
    if not series:
        raise ValueError("Goose patch list is empty: ArchHub never ships stock Goose (founder rule F5)")
    return series


def check_lock(path, pin):
    if sha(path) != pin["cargo_lock_sha256"]:
        raise ValueError("Goose Cargo.lock differs from the pinned lock")


HIDDEN = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS   # Windows-only tool: no console, low priority


def _run(argv, cwd, env=None, capture=False):
    done = subprocess.run(argv, cwd=cwd, env=env, check=True, text=True, capture_output=capture, creationflags=HIDDEN)
    return done.stdout.strip() if capture else ""


def _cargo(cargo_build, cwd, env):
    """The heavy compile runs only while the desk is idle or away (founder rule R100), queued by run-heavy."""
    if idle_or_away():
        subprocess.run(cargo_build, cwd=cwd, env=env, check=True, text=True, creationflags=HIDDEN)
        return
    raise RuntimeError("Goose compile not started: the desktop is in use. Queue it again through run-heavy.")


def build(source, output, *, archhub_rev, pin_path=PIN, ours=OURS, seed_lock=False):
    pin = load_pin(pin_path)
    source, output = Path(source), Path(output)
    for folder in (source, output):
        if folder.exists() and any(folder.iterdir()):
            raise ValueError("Goose build folder must be empty: %s" % folder)
    series = archhub_patches(ours, pin_path)
    lock = Path(ours) / "Cargo.lock"
    if lock.exists():
        check_lock(lock, pin)
    elif not seed_lock:
        raise ValueError("ArchHub's Goose Cargo.lock is missing; run once with --seed-lock")
    source.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q"], source)
    _run(["git", "fetch", "-q", "--depth", "1", pin["repository"], pin["commit"]], source)
    _run(["git", "checkout", "-q", "--detach", "FETCH_HEAD"], source)
    if _run(["git", "rev-parse", "HEAD"], source, capture=True) != pin["commit"]:
        raise ValueError("Fetched Goose source is not the pinned commit")
    for name, _digest in series:
        _run(["git", "apply", "--whitespace=nowarn", str(Path(ours) / "patches" / name)], source)
    if not lock.exists():
        check_lock(source / "Cargo.lock", pin)   # seed only the pinned upstream bytes
        shutil.copyfile(source / "Cargo.lock", lock)
    shutil.copyfile(lock, source / "Cargo.lock")
    env = {**os.environ, "RUSTFLAGS": pin["rustflags"], "CARGO_INCREMENTAL": "0"}
    env.pop("CARGO_ENCODED_RUSTFLAGS", None)
    cargo_build = ["cargo", "build", "--release", "--locked", "--target", pin["target"], "-p", pin["package"], "--bin", pin["binary"]]
    _cargo(cargo_build, source, env)
    built = source / "target" / pin["target"] / "release" / (pin["binary"] + ".exe")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(built, output / "goose.exe")
    shutil.copyfile(source / "LICENSE", output / "LICENSE")
    receipt = {"schema_version": 1, "version": pin["version"], "upstream_repository": pin["repository"],
               "upstream_commit": pin["commit"], "archhub_rev": archhub_rev, "inputs": inputs(pin_path), "patches": series,
               "cargo_lock_sha256": sha(source / "Cargo.lock"),
               "toolchain": _run(["rustc", "-V"], source, env, capture=True), "rustflags": pin["rustflags"],
               "command": cargo_build, "license_sha256": sha(output / "LICENSE"), "executable_sha256": sha(output / "goose.exe")}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--archhub-rev", required=True)
    parser.add_argument("--seed-lock", action="store_true")
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output, archhub_rev=args.archhub_rev, seed_lock=args.seed_lock), indent=2))
