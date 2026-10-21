"""Court: publishing is the only way a fact is shared, and it refuses the client area.

Review of P3 (2026-09-29): classifying on write let any writer label client
content as a community class, and a regex over one spelling was bypassable.
Now brain.write never classifies, whatever the fragment asks; brain.publish is
the owner's deliberate act on ONE fact, and it refuses a fact that names the
client area or a project, however it is spelled.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from nodelang import app_brain
from nodelang.brain_store_port import FOUNDER_OWNER_ROOT
from nodelang.cell_brain_governance import COMMUNITY, SEALED, classification
from nodelang.cell_catalog import bootstrap_assembly_protocol
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore


@pytest.fixture
def brain(tmp_path, monkeypatch):
    # A workspace whose client area holds two client folders (names only are read).
    for folder in ("22.BBC4", "21.ACME"):
        (tmp_path / "20.CLIENTS" / folder).mkdir(parents=True)
    monkeypatch.setenv("ARCHHUB_WORKSPACE_ROOT", str(tmp_path))
    store = CellStore()
    protocol = bootstrap_assembly_protocol(store)
    store.commit(store.snapshot().revision, create=(
        Cell(FOUNDER_OWNER_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"owner"),))
    app_brain.bind(store, SimpleNamespace(
        authorization=SimpleNamespace(subject_root=FOUNDER_OWNER_ROOT), assembly_protocol=protocol))
    yield store
    app_brain.unbind(store)


def _add(fid, text, **extra):
    return app_brain.write([{"op": "add", "fragment": dict({"id": fid, "kind": "fact", "text": text}, **extra)}])


def _ceiling(store, fid):
    return classification(store.snapshot(), session_root=app_brain.SESSION_ROOT, fragment_id=fid).ceiling


def test_writing_never_shares_whatever_the_fragment_asks(brain):
    assert _add("f-ask", "Dimension stairs riser-first",
                share={"class": "published-skills", "stratum": "category"},
                data_class="behaviour-patterns") == {"ok": True, "written": 1}
    assert _ceiling(brain, "f-ask") == SEALED


def test_the_owner_publishes_one_fact(brain):
    _add("f-skill", "Dimension stairs riser-first")
    said = app_brain.publish("f-skill")
    assert said["ok"] is True and said["published"] is True, said
    assert _ceiling(brain, "f-skill") == COMMUNITY
    assert app_brain.call("brain.publish", {"fragment_id": "f-skill"})["ok"] is True


@pytest.mark.parametrize("text", [
    r"20.CLIENTS\22.BBC4 detail", "20_CLIENTS detail", "20 CLIENTS detail", "20%2ECLIENTS detail",
    "20%252ECLIENTS detail", "20\uff0eCLIENTS detail", r"see 22.BBC4\A-101", "22_BBC4 wall types",
    "21.ACME tower cores", "P-603 site layout", r"60.PERSONAL\budget",
    "20CLIENTS detail", "P603 layout", "20%25252ECLIENTS detail", "60PERSONAL budget",
    "22BBC4 wall types", "the 21acme podium", "BBC4 prefers A3 sheets",
], ids=["path", "underscore", "space", "percent", "double-percent", "full-width", "project-folder",
        "project-underscore", "client-folder", "project-code", "personal-area",
        "no-separator", "code-no-separator", "triple-percent", "personal-no-separator",
        "folder-no-separator", "folder-lowercase", "client-name-alone"])
def test_a_fact_naming_the_client_area_is_never_published(brain, text):
    _add("f-client", text)
    said = app_brain.publish("f-client")
    assert said["ok"] is False and "client area" in said["error"]
    assert _ceiling(brain, "f-client") == SEALED


def test_an_id_naming_the_client_area_is_refused_too(brain):
    _add("20.CLIENTS/22.BBC4/note", "Walls are 200 mm")
    assert app_brain.publish("20.CLIENTS/22.BBC4/note")["ok"] is False


def test_publishing_what_is_not_held_says_so(brain):
    assert app_brain.publish("f-nowhere") == {"ok": False, "error": "no such fact"}

@pytest.mark.parametrize("text", ["Dimension stairs riser-first", "Use 25mm gaps at door heads",
                                  "Revit 2025 keeps type P1 walls", "use 25 mm insulation",
                                  "wait 24 hours", "set 20 minutes", "R2 and 22 mm pipes", "A4 at p 120"])
def test_ordinary_practice_is_published(brain, text):
    _add("f-ok", text)
    assert app_brain.publish("f-ok")["published"] is True


def test_without_a_client_area_only_the_area_names_and_codes_are_refused(brain, monkeypatch, tmp_path):
    empty = tmp_path / "elsewhere"
    empty.mkdir()
    monkeypatch.setenv("ARCHHUB_WORKSPACE_ROOT", str(empty))
    assert not app_brain.names_the_client_area("BBC4 prefers A3 sheets")
    assert app_brain.names_the_client_area(r"20.CLIENTS\anything")
    assert app_brain.names_the_client_area("P-603 site")