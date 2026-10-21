"""Brain store port court: facts, skills and wiring before = after.

The retired personal Brain (12.PRODUCTION personal-brain-mcp) keeps facts in
``fragments``, skills in ``skills`` and device wiring in ``wiring``. The
application's own Brain replaces it (founder decision 2026-09-15/16), so its
store is ported first. This court builds a SYNTHETIC legacy file in a temp
directory -- never the founder's -- and proves: every source fact is in the
graph or counted under a named skip; every skill and wiring row is in the
graph; the source file is never written; a second run changes nothing.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3

from nodelang.brain_store_port import FOUNDER_OWNER_ROOT, port_legacy_brain
from nodelang.cell_brain_memory import memories
from nodelang.cell_catalog import bootstrap_assembly_protocol
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore
from tests_replica.test_cell_brain_legacy_import import INSERT, LEGACY_FRAGMENTS_DDL

FOUNDER_ID = "u_founder_legacy"
FOUNDER_EMAIL = "founder@example.com"

SKILLS_DDL = """CREATE TABLE skills (id TEXT PRIMARY KEY, name TEXT NOT NULL,
 description TEXT NOT NULL, body TEXT NOT NULL, scope TEXT NOT NULL DEFAULT 'user',
 owner_user TEXT NOT NULL, provenance_json TEXT NOT NULL,
 minted_at TEXT NOT NULL DEFAULT '2026-09-01T00:00:00Z')"""
WIRING_DDL = """CREATE TABLE wiring (name TEXT NOT NULL, device_id TEXT NOT NULL,
 kind TEXT NOT NULL, endpoint TEXT, auth_method TEXT,
 capabilities_json TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'active',
 last_seen TEXT NOT NULL, PRIMARY KEY (name, device_id))"""


def _prov(hlc=None):
    body = {"contributing_agent": "claude-code", "created_at": "2026-09-01T10:00:00Z"}
    if hlc:
        body["hlc"] = hlc
    return json.dumps(body)


FRAGMENTS = (
    ("f1", "fact", "Site rate is 450 AED/m2", "user", FOUNDER_ID, "extracted", _prov("0001788256800000.a1"), None, 0),
    ("f2", "fact", "Client prefers A3 sheets", "user", FOUNDER_EMAIL, "extracted", _prov(), None, 0),
    ("f3", "fact", "Old note", "user", FOUNDER_ID, "extracted", _prov(), "2026-09-05T12:00:00.000Z", 0),
    ("f4", "mandate", "Reply in English", "user", FOUNDER_EMAIL, "extracted", _prov(), None, 0),
    ("f5", "fact", "A colleague private note", "user", "colleague@example.com", "extracted", _prov(), None, 0),
    ("f6", "fact", "Project rate", "project", FOUNDER_ID, "extracted", _prov(), None, 0),
    ("f7", "trace", "tool call log", "user", FOUNDER_ID, "extracted", _prov(), None, 0),
    ("f8", "fact", "the NAS password is hunter2hunter2", "user", FOUNDER_ID, "extracted", _prov(), None, 0),
    ("s1", "skill", "How to hatch\nUse ANSI31", "user", FOUNDER_EMAIL, "extracted", _prov(), None, 0),
    ("c1", "setup", "community setup row", "community", "federation-worker", "extracted", _prov(), None, 0),
    ("u1", "fact", "An unattributed note", "user", "unknown", "extracted", _prov(), None, 0),
)
SKILLS = (
    ("k1", "revision-clouds", "Draw revision clouds", "steps...", "user", FOUNDER_ID, _prov()),
    ("k2", "sheet-qa", "Full-sheet overlap review", "steps...", "project", "founder", _prov()),
    ("k3", "dwg-split", "Split a DWG", "steps...", "user", FOUNDER_ID, _prov()),
    ("k4", "colleague-skill", "A colleague private skill", "steps...", "user", "colleague@example.com", _prov()),
    ("k5", "nas-login", "Log in to the NAS", "the NAS password is hunter2hunter2", "user", FOUNDER_ID, _prov()),
)
WIRING = (
    ("git", "codex-app-05", "cli", None, None, '["status"]', "active", "2026-06-01T11:04:57Z"),
    ("claude", "founder-pc", "cli", None, None, '["read-only"]', "active", "2026-06-02T11:04:57Z"),
)


def _legacy(path):
    db = sqlite3.connect(path)
    db.execute(LEGACY_FRAGMENTS_DDL)
    db.execute(SKILLS_DDL)
    db.execute(WIRING_DDL)
    for row in FRAGMENTS:
        db.execute(INSERT, (*row, "2026-09-01T10:00:00.000Z", "2026-09-01T10:00:00.000Z"))
    db.executemany("INSERT INTO skills (id, name, description, body, scope, owner_user,"
                   " provenance_json) VALUES (?, ?, ?, ?, ?, ?, ?)", SKILLS)
    db.executemany("INSERT INTO wiring VALUES (?, ?, ?, ?, ?, ?, ?, ?)", WIRING)
    db.execute("CREATE TABLE access_log (id INTEGER PRIMARY KEY, fragment_id TEXT)")
    db.executemany("INSERT INTO access_log (fragment_id) VALUES (?)", [("f1",), ("f2",)])
    db.execute("CREATE TABLE brain_meta (key TEXT PRIMARY KEY, value TEXT)")
    db.execute("INSERT INTO brain_meta VALUES ('bound_owner_user', 'u_founder_legacy')")
    db.execute("CREATE VIRTUAL TABLE fragments_fts USING fts5(text)")
    db.execute("INSERT INTO fragments_fts (text) VALUES ('Site rate is 450 AED/m2')")
    db.commit()
    db.close()


def _graph():
    store = CellStore()
    protocol = bootstrap_assembly_protocol(store)
    store.commit(store.snapshot().revision, create=(
        Cell(FOUNDER_OWNER_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"founder"),))
    return store, protocol


def test_brain_port_counts_before_equal_after_and_rerun_changes_nothing(tmp_path):
    source = tmp_path / "brain-copy.db"
    _legacy(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    store, protocol = _graph()

    report = port_legacy_brain(store, protocol, source,
                               owner_users=(FOUNDER_ID, FOUNDER_EMAIL, "founder"))

    # facts: 10 non-community rows minus 1 skill-kind row = 9 counted
    assert report.source_facts == 9
    assert report.graph_facts == 4          # f1, f2, f3 (forgotten), f4
    assert report.facts_skipped == {
        "other-owner": 1, "other-owner:unknown": 1, "scope:project": 1, "kind:trace": 1,
        "looks-like-a-secret": 1}
    # k1, k3 and fragment s1 are the named owners' own; k2 is project-scoped,
    # k4 belongs to another owner, k5 carries a credential.
    assert report.source_skills == 6 and report.graph_skills == 3
    assert report.skills_skipped == {"scope:project": 1, "other-owner": 1, "looks-like-a-secret": 1}
    assert report.source_wiring == 2 and report.graph_wiring == 2
    assert report.accounted() == {"facts": True, "skills": True, "wiring": True, "tables": True}
    # Every table and every row of the source is accounted, nothing dropped.
    fragments = report.tables["fragments"]
    assert fragments["rows"] == len(FRAGMENTS)
    assert fragments["ported"] == 5 and fragments["skipped"]["scope:community"] == 1
    assert fragments["skipped"]["other-owner:unknown"] == 1
    assert report.tables["skills"] == {"rows": 5, "ported": 2, "skipped": {
        "scope:project": 1, "other-owner": 1, "looks-like-a-secret": 1}}
    assert report.tables["wiring"] == {"rows": 2, "ported": 2, "skipped": {}}
    assert report.tables["access_log"]["skipped"] == {
        "access history, not memory (bounded records, SPEC 3.3)": 2}
    assert report.tables["brain_meta"]["ported"] == 0 and report.tables["brain_meta"]["rows"] == 1
    assert report.tables["fragments_fts"]["skipped"] == {"derived full-text index of fragments": 1}
    assert all(t["rows"] == t["ported"] + sum(t["skipped"].values()) for t in report.tables.values())
    held = {m.fragment_id: m for m in memories(
        store.snapshot(), session_root="app:sessions:legacy-brain-port", include_forgotten=True)}
    assert held["f3"].state == "forgotten" and held["f1"].text == "Site rate is 450 AED/m2"
    assert all(m.owner_root == FOUNDER_OWNER_ROOT for m in held.values())

    revision = store.snapshot().revision
    again = port_legacy_brain(store, protocol, source,
                              owner_users=(FOUNDER_ID, FOUNDER_EMAIL, "founder"))
    assert (again.facts_imported, again.skills_minted, again.wiring_imported) == (0, 0, 0)
    assert store.snapshot().revision == revision
    assert again.accounted() == {"facts": True, "skills": True, "wiring": True, "tables": True}
    assert again.tables == report.tables
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest

def test_long_snake_case_skill_names_are_names_not_secrets(tmp_path):
    """The real legacy names that the whole-field entropy test took for tokens."""
    source = tmp_path / "names.db"
    _legacy(source)
    db = sqlite3.connect(source)
    names = ("drive_a_live_revit_session_through_its_broker_safely",
             "client_submittal_qc_master_register_vs_submittal_folder",
             "split_a_dwg_imperial_pattern_base_before_the_revit_link")
    db.executemany("INSERT INTO skills (id, name, description, body, scope, owner_user,"
                   " provenance_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   [("n%d" % i, name, "A real skill", "steps...", "user", FOUNDER_ID, _prov())
                    for i, name in enumerate(names)])
    credential_name = "api_key = " + "sk" + "-live-" + "0123456789" + "abcdef"   # assembled: no literal token
    db.execute("INSERT INTO skills (id, name, description, body, scope, owner_user, provenance_json)"
               " VALUES ('bad', ?, 'x', 'y', 'user', ?, ?)", (credential_name, FOUNDER_ID, _prov()))
    db.commit()
    db.close()
    store, protocol = _graph()
    report = port_legacy_brain(store, protocol, source, owner_users=(FOUNDER_ID, FOUNDER_EMAIL, "founder"))
    # k1, k3, s1 and the three long names land; the credential in a name does not.
    assert report.graph_skills == 6
    assert report.skills_skipped["looks-like-a-secret"] == 2   # k5 body + the credential name
