from __future__ import annotations

import json
import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_dev_source_sync_copies_configured_checkout_without_relaunch(tmp_path):
    import dev_source_sync

    source = tmp_path / "source"
    install = tmp_path / "install"
    (source / ".git").mkdir(parents=True)
    _write(source / "VERSION", "1.3.2")
    _write(source / "app" / "main.py", "print('new main')\n")
    _write(source / "app" / "studio_shell.py", "NEW_UI = True\n")
    _write(source / "payload" / "bridge" / "server.py", "BRIDGE = True\n")
    _write(install / "settings.json", json.dumps({
        "enable_dev_source_sync": True,
        "dev_source_path": str(source),
        "theme": "dark",
    }))
    _write(install / "app" / "studio_shell.py", "OLD_UI = True\n")

    changed = dev_source_sync.maybe_sync_and_relaunch(
        install,
        ["main.py"],
        relaunch=False,
    )

    assert changed is True
    assert (install / "app" / "studio_shell.py").read_text(encoding="utf-8") == "NEW_UI = True\n"
    assert (install / "payload" / "bridge" / "server.py").exists()
    settings = json.loads((install / "settings.json").read_text(encoding="utf-8"))
    assert settings["theme"] == "dark"
    assert settings["enable_dev_source_sync"] is True
    assert settings["dev_source_path"] == str(source)

    changed_again = dev_source_sync.maybe_sync_and_relaunch(
        install,
        ["main.py"],
        relaunch=False,
    )
    assert changed_again is False


# ── pull_source_to_main: the "ALWAYS up-to-date" auto-pull (founder 2026-06-09) ──
import subprocess  # noqa: E402


def _g(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _init_main_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    _g(path, "init", "-b", "main")
    _g(path, "config", "user.email", "t@t.com")
    _g(path, "config", "user.name", "t")
    (path / "VERSION").write_text("1.0.0", encoding="utf-8")
    (path / "app").mkdir(exist_ok=True)
    (path / "app" / "main.py").write_text("x = 1\n", encoding="utf-8")
    _g(path, "add", "-A")
    _g(path, "commit", "-m", "init")
    return path


def test_pull_source_skips_on_feature_branch(tmp_path):
    """On a dev branch the pull is a NO-OP — never switches off the branch or
    touches HEAD (active dev runs exactly what's checked out)."""
    import dev_source_sync as d
    d._GIT_BROKEN = False
    repo = _init_main_repo(tmp_path / "r")
    _g(repo, "checkout", "-b", "feat")
    head = _g(repo, "rev-parse", "HEAD").stdout.strip()
    assert d.pull_source_to_main(repo) is False
    assert _g(repo, "rev-parse", "HEAD").stdout.strip() == head
    assert _g(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "feat"


def test_pull_source_skips_on_dirty_main(tmp_path):
    """On main with uncommitted edits the pull is a NO-OP — never clobbers
    work in progress."""
    import dev_source_sync as d
    d._GIT_BROKEN = False
    repo = _init_main_repo(tmp_path / "r")
    (repo / "app" / "main.py").write_text("DIRTY = 1\n", encoding="utf-8")
    head = _g(repo, "rev-parse", "HEAD").stdout.strip()
    assert d.pull_source_to_main(repo) is False
    assert (repo / "app" / "main.py").read_text(encoding="utf-8") == "DIRTY = 1\n"
    assert _g(repo, "rev-parse", "HEAD").stdout.strip() == head


def test_pull_source_fast_forwards_clean_main_to_remote(tmp_path):
    """On clean main, the pull fast-forwards to a remote that advanced — the
    merged-PR-reaches-the-app guarantee."""
    import dev_source_sync as d
    d._GIT_BROKEN = False
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _g(remote, "init", "--bare", "-b", "main")
    work = _init_main_repo(tmp_path / "work")
    _g(work, "remote", "add", "origin", str(remote))
    _g(work, "push", "-u", "origin", "main")
    # a second clone advances origin/main (simulating a merged PR)
    other = tmp_path / "other"
    _g(tmp_path, "clone", str(remote), str(other))
    _g(other, "config", "user.email", "t@t.com")
    _g(other, "config", "user.name", "t")
    (other / "app" / "main.py").write_text("ADVANCED = 1\n", encoding="utf-8")
    _g(other, "add", "-A")
    _g(other, "commit", "-m", "advance")
    _g(other, "push", "origin", "main")
    before = _g(work, "rev-parse", "HEAD").stdout.strip()
    assert d.pull_source_to_main(work) is True
    assert _g(work, "rev-parse", "HEAD").stdout.strip() != before
    assert (work / "app" / "main.py").read_text(encoding="utf-8") == "ADVANCED = 1\n"
