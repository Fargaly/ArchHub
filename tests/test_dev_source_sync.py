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
