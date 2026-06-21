"""Brain-as-folders backend (brain_facts.list_facts / edit_fact / delete_fact).

Founder 2026-06-21: the brain must be an explorable + editable folder system.
These tests prove the grouping into top-level folders by type, that the four
founder-named folders (User / Feedback / Projects / Reference) are always
present, and that edit + soft/hard delete are REAL writes through the store.
"""

from datetime import datetime, timezone

import pytest

from personal_brain.models import Fragment, FragmentKind, Provenance
from personal_brain import brain_facts as bf


def _mk(fid, kind, text, **kw):
    now = datetime.now(timezone.utc)
    prov = Provenance(
        source_uri="test", created_at=now,
        contributing_agent="test", contributing_user="Fargaly",
    )
    return Fragment(id=fid, kind=kind, text=text, owner_user="Fargaly",
                    provenance=prov, **kw)


class FakeStore:
    def __init__(self, frags):
        self.d = {f.id: f for f in frags}

    def list_fragments(self, *, owner_user=None, limit=1000):
        return list(self.d.values())

    def get_fragment(self, fid):
        return self.d.get(fid)

    def write_fragment(self, frag):
        self.d[frag.id] = frag
        return True

    def delete_fragment(self, fid):
        return self.d.pop(fid, None) is not None


@pytest.fixture
def store():
    return FakeStore([
        _mk("f1", FragmentKind.FACT, "User prefers terracotta", predicate="preference"),
        _mk("f2", FragmentKind.FACT, "JPD17 villa at port", predicate="note", project_id="P-JPD17"),
        _mk("f3", FragmentKind.FACT, "never restart Revit", predicate="feedback"),
        _mk("f4", FragmentKind.FACT, "locked architecture direction X", predicate="decision"),
        _mk("f5", FragmentKind.FACT, "node inventory has 197 nodes", predicate="capability"),
        _mk("f6", FragmentKind.SKILL, "revfix workflow"),
        _mk("f7", FragmentKind.DOCUMENT, "ROADMAP indexed"),
        _mk("f8", FragmentKind.TRACE, "session residue"),
    ])


def test_facts_group_into_expected_folders(store):
    res = bf.list_facts(store)
    assert res["ok"]
    assert res["total"] == 8
    by_id = {rec["id"]: rec["type"]
             for f in res["folders"] for rec in f["facts"]}
    assert by_id == {
        "f1": "user", "f2": "projects", "f3": "feedback", "f4": "decisions",
        "f5": "capability", "f6": "skills", "f7": "reference", "f8": "traces",
    }


def test_four_founder_folders_always_present_even_when_empty():
    res = bf.list_facts(FakeStore([]))
    ids = {f["id"] for f in res["folders"]}
    assert {"user", "feedback", "projects", "reference"} <= ids


def test_each_fact_record_has_name_desc_body(store):
    res = bf.list_facts(store)
    rec = next(r for f in res["folders"] for r in f["facts"] if r["id"] == "f1")
    assert rec["name"] and rec["desc"] and rec["body"] == "User prefers terracotta"


def test_edit_fact_persists(store):
    out = bf.edit_fact(store, "f1", "User prefers warm terracotta tones")
    assert out["ok"] and out["edited"]
    assert store.get_fragment("f1").text == "User prefers warm terracotta tones"


def test_edit_fact_rejects_empty_and_missing(store):
    assert bf.edit_fact(store, "f1", "   ")["ok"] is False
    assert bf.edit_fact(store, "missing", "x")["ok"] is False


def test_soft_delete_archives_and_drops_from_active(store):
    out = bf.delete_fact(store, "f2")
    assert out["ok"] and out["deleted"] and out["hard"] is False
    assert store.get_fragment("f2").valid_until is not None
    res = bf.list_facts(store)
    assert "f2" not in {r["id"] for f in res["folders"] for r in f["facts"]}
    # ...but recoverable: it reappears when archived are included.
    res_all = bf.list_facts(store, include_archived=True)
    assert "f2" in {r["id"] for f in res_all["folders"] for r in f["facts"]}


def test_hard_delete_removes_row(store):
    out = bf.delete_fact(store, "f8", hard=True)
    assert out["ok"] and out["hard"]
    assert store.get_fragment("f8") is None
