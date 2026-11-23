"""Seed only the installed witness's private run folder and exercise the Home data owners."""

import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace


def exercise(app, out, mode, build):
    state = Path(os.environ["ARCHHUB_TEST_STATE_DIR"]).resolve(strict=True)
    assert state.name == "state" and state.parent.name.startswith("run-")
    assert (
        state.parent.parent == out
        and Path.home().resolve() == state.parent / "USERPROFILE"
    )
    assert (
        state != app
        and Path(sys.executable).resolve() == app / ".venv/Scripts/python.exe"
    )
    assert build and (app / "BUILD_ID").read_text().strip() == build
    sys.path.insert(0, str(app))
    from nodelang import nograph_server, session_files, workshop_mailbox, workshop_tasks

    assert workshop_mailbox.profile_database().resolve().is_relative_to(state)
    assert session_files.sessions_directory().resolve().is_relative_to(state)
    task = "qa-home-lease"
    lease = None if mode == "missing" else time.time() + 600
    paths = {}
    with workshop_mailbox.application_history() as history:
        db = history._db
        if mode == "seed":
            workshop_tasks._ensure(history)
            now = workshop_tasks._now()
            db.execute(
                "INSERT INTO workshop_tasks(id,title,status,owner,lease_until,created_by,created_at,updated_at) "
                "VALUES (?,?,'claimed','qa',?,'qa',?,?)",
                (task, "Home lease control", lease, now, now),
            )
            for kind in ("untouched", "edited"):
                identity = "declared-home-qa-" + kind
                title = kind.title() + " Home QA"
                paths[kind] = workshop_tasks._start_session(identity, title)
                # A retired registration gets an archived task row. Its document is left intact.
                db.execute(
                    "INSERT INTO workshop_tasks(id,title,status,session_path,archived,created_by,created_at,updated_at) "
                    "VALUES (?,?,'done',?,1,'qa',?,?)",
                    (identity, title, paths[kind], now, now),
                )
        elif mode in ("missing", "restored"):
            assert (
                db.execute(
                    "UPDATE workshop_tasks SET lease_until=? WHERE id=?", (lease, task)
                ).rowcount
                == 1
            )
        else:
            raise ValueError(mode)

    request = SimpleNamespace(
        method="POST",
        body={"action": "data-api", "function": "listTasks", "args": [True]},
    )
    try:
        rows = nograph_server.r_workshop(None, request)["result"]
        assert any(row["id"] == task for row in rows)
    finally:
        nograph_server._close_store_version()
    if mode != "seed":
        return

    files = session_files.SessionFiles()
    edited = paths["edited"]
    document = session_files.read_document(edited)
    assert not session_files.session_fields(document, edited)["authoredRegistration"]
    changed = files.dispatch(
        {
            "action": "param-op",
            "document": document,
            "op": "add",
            "args": ["start", "Design tolerance", "number", 2.5],
        }
    )["document"]
    files.dispatch({"action": "save", "document": changed, "path": edited})
    for kind, filename in paths.items():
        reopened = session_files.read_document(filename)
        assert session_files.session_fields(reopened, filename)[
            "authoredRegistration"
        ] == (kind == "edited")
        if kind == "edited":
            assert (
                next(node for node in reopened["nodes"] if node["id"] == "start")[
                    "params"
                ]["design_tolerance"]
                == 2.5
            )
    print(json.dumps(paths))


if __name__ == "__main__":
    exercise(
        Path(sys.argv[1]).resolve(strict=True),
        Path(sys.argv[2]).resolve(strict=True),
        *sys.argv[3:],
    )
