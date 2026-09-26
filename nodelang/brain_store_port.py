"""Port the retired personal Brain store into the application's own graph.

Founder decision 2026-09-15/16: the application's Brain replaces the legacy
personal-brain daemon, and its store is ported first. This is the one runner
for that port. It adds no second memory owner: facts go through
``cell_brain_legacy_import`` (and so ``cell_brain_memory``), skills through
``cell_brain_skills`` (through the same owner filter and secret screen as
facts), and the legacy wiring rows become ``setup`` memory,
the kind the memory owner already has for machine setup.

The source is always opened ``mode=ro``. There is no default source, owner
mapping or graph path: the caller names each one, so a court can point this
at a copy and a cutover names the file it means. Every source row is either
in the graph after the run or counted under a named skip reason -- every table
of the source file and every row of it, including the ones the application
Brain does not model -- and a second run changes nothing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import commit_intent
from .cell_brain_legacy_import import (
    _epoch_ms,
    _skip_reason,
    import_legacy_fragments,
    read_legacy_fragments,
)
from .cell_brain_memory import memories, remember
from .cell_brain_secrets import assert_no_credential_in_text, assert_not_a_secret
from .cell_brain_skills import SKILL_LIBRARY_ROOT, mint_skill, read_skill
from .cell_protocols import read_relation
from .cell_session_state import open_session
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell

FOUNDER_OWNER_ROOT = "app:identity:founder"
PORT_SESSION_ROOT = "app:sessions:legacy-brain-port"
PORT_ORIGIN = "legacy-brain-port"
LEGACY_SKILL_PREFIX = "app:brain:legacy-skill:"
LEGACY_RECORD_PREFIX = "app:brain:legacy-record:"
WIRING_PREFIX = "legacy-wiring:"
SKILL_COLUMNS = ("id", "name", "description", "body", "scope", "owner_user",
                 "provenance_json", "minted_at")
WIRING_COLUMNS = ("name", "device_id", "kind", "endpoint", "capabilities_json",
                  "status", "last_seen")


@dataclass
class PortReport:
    source_facts: int = 0
    source_skills: int = 0
    source_wiring: int = 0
    facts_imported: int = 0
    facts_unchanged: int = 0
    facts_skipped: dict = field(default_factory=dict)
    skills_minted: int = 0
    skills_skipped: dict = field(default_factory=dict)
    skills_unchanged: int = 0
    wiring_imported: int = 0
    wiring_unchanged: int = 0
    graph_facts: int = 0
    graph_skills: int = 0
    graph_wiring: int = 0
    tables: dict = field(default_factory=dict)

    def accounted(self):
        """Every counted source row landed in the graph or has a named skip."""
        skipped = sum(self.facts_skipped.values())
        return {
            "facts": self.graph_facts + skipped == self.source_facts,
            "skills": self.graph_skills + sum(self.skills_skipped.values()) == self.source_skills,
            "wiring": self.graph_wiring == self.source_wiring,
            "tables": bool(self.tables) and all(
                entry["rows"] == entry["ported"] + sum(entry["skipped"].values())
                for entry in self.tables.values()),
        }


def _read_ro(path, table, columns):
    source = Path(path)
    if not source.is_file():
        raise InvalidCell("no legacy brain file at %s" % source)
    connection = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT %s FROM %s ORDER BY 1, 2" % (", ".join(columns), table)
        ).fetchall()
    finally:
        connection.close()
    return tuple(dict(zip(columns, row)) for row in rows)


def _skill_skip_reason(row, owner_users, *texts, name=None):
    """The same admission as facts: the named owners' own rows, no secrets.

    A skill name is an identifier: long snake_case names such as
    drive_a_live_revit_session_through_its_broker look like a high-entropy
    token to the whole-field secret test, so the name is screened only for a
    credential written inside it. Descriptions and bodies get both screens.
    """
    if row.get("scope") != "user":
        return "scope:%s" % row.get("scope")
    if row.get("owner_user") not in owner_users:
        return "other-owner"
    try:
        if isinstance(name, str):
            assert_no_credential_in_text(name, "legacy skill name")
        for text in texts:
            if isinstance(text, str):
                assert_not_a_secret(text, "legacy skill text")
                assert_no_credential_in_text(text, "legacy skill text")
    except InvalidCell:
        return "looks-like-a-secret"
    return None


# Tables of the legacy file the application Brain does not model, and why.
_UNMODELLED = {
    "access_log": "access history, not memory (bounded records, SPEC 3.3)",
    "brain_meta": "the retired daemon's own settings and sync cursors",
    "reputation": "federation peer scores; the application Brain has no federation",
    "secret_refs": "secret references stay references; the graph has its own secret owner",
    "sqlite_sequence": "sqlite bookkeeping",
}


def _owner_reason(owner):
    return "other-owner:unknown" if owner in (None, "", "unknown") else "other-owner"


def _account_tables(source_path, fragments_outcome, skills_outcome, wiring_rows, graph_wiring):
    """Every table and every row of the source: ported, or skipped with a reason."""
    source = Path(source_path)
    connection = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        names = [name for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        counts = {name: connection.execute('SELECT count(*) FROM "%s"' % name.replace('"', '""')).fetchone()[0]
                  for name in names}
    finally:
        connection.close()
    tables = {}
    for name in names:
        rows = counts[name]
        if name == "fragments":
            outcomes = fragments_outcome
        elif name == "skills":
            outcomes = skills_outcome
        elif name == "wiring":
            outcomes = ["ported"] * min(graph_wiring, wiring_rows) + ["not-in-graph"] * max(0, wiring_rows - graph_wiring)
        else:
            base = name.split("_fts", 1)[0]
            reason = ("derived full-text index of %s" % base if "_fts" in name
                      else _UNMODELLED.get(name, "table not modelled by the application Brain"))
            outcomes = [reason] * rows
        skipped = {}
        for outcome in outcomes:
            if outcome != "ported":
                skipped[outcome] = skipped.get(outcome, 0) + 1
        tables[name] = {"rows": rows, "ported": sum(1 for o in outcomes if o == "ported"), "skipped": skipped}
    return tables


def _digest(*parts):
    return hashlib.sha256("\x00".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def ensure_port_session(store, *, session_root=PORT_SESSION_ROOT, owner_root=FOUNDER_OWNER_ROOT):
    if session_root not in store.snapshot().cells:
        open_session(store, session_root=session_root, owner_root=owner_root)
    return session_root


def _port_skill(store, protocol, *, source_key, name, purpose, body, provenance):
    skill_id = LEGACY_SKILL_PREFIX + _digest(source_key)
    if skill_id in store.snapshot().cells:
        return False
    record = LEGACY_RECORD_PREFIX + _digest(source_key)
    payload = json.dumps({"source": source_key, "body": body, "provenance": provenance},
                         sort_keys=True, ensure_ascii=False)
    if record not in store.snapshot().cells:
        store.commit(store.snapshot().revision, create=(
            Cell(record, NULL_CELL_ID, NULL_CELL_ID, payload.encode("utf-8")),))
    mint_skill(store, protocol, skill_id=skill_id,
               name=(name or source_key).strip() or source_key,
               purpose=(purpose or name or source_key).strip() or source_key,
               learned_from=(record,))
    return True


def _graph_legacy_skills(snapshot, protocol):
    if SKILL_LIBRARY_ROOT not in snapshot.cells:
        return 0
    return sum(
        1 for member in read_relation(snapshot, SKILL_LIBRARY_ROOT, budget=1_000_000)
        if member.role_id == protocol.role("definition-dependency")
        and member.participant_id.startswith(LEGACY_SKILL_PREFIX)
        and read_skill(snapshot, protocol, member.participant_id)
    )


def port_legacy_brain(store, protocol, source_path, *, owner_users,
                      session_root=PORT_SESSION_ROOT, owner_root=FOUNDER_OWNER_ROOT):
    """Port facts, skills and wiring for the named legacy owners into ``store``."""
    owner_users = tuple(dict.fromkeys(owner_users))
    if not owner_users:
        raise InvalidCell("the legacy owner mapping must be named")
    report = PortReport()
    ensure_port_session(store, session_root=session_root, owner_root=owner_root)

    # Federated community setup rows belong to no personal owner: they are not
    # facts (brain.health counts the same way) and are accounted per table below.
    all_fragments = read_legacy_fragments(source_path)
    fragments = [row for row in all_fragments if row.get("scope") != "community"]
    skill_ids = {row["id"] for row in fragments
                 if row.get("kind") == "skill" and row.get("scope") == "user"
                 and row.get("owner_user") in owner_users}
    skill_fragments = [row for row in fragments if row["id"] in skill_ids]
    fact_rows = [row for row in fragments if row["id"] not in skill_ids]
    report.source_facts = len(fact_rows)

    # Facts: the existing importer once per named legacy owner; rows no named
    # owner admits are counted once as other-owner.
    admitted_ids = set()
    for owner_user in owner_users:
        mine = [row for row in fact_rows if row.get("owner_user") == owner_user]
        result = import_legacy_fragments(store, mine, session_root=session_root,
                                         owner_user=owner_user, origin=PORT_ORIGIN)
        report.facts_imported += result.imported
        report.facts_unchanged += result.unchanged
        for reason, count in result.skipped.items():
            report.facts_skipped[reason] = report.facts_skipped.get(reason, 0) + count
        admitted_ids.update(row["id"] for row in mine)
    for row in fact_rows:
        if row["id"] not in admitted_ids:
            reason = _owner_reason(row.get("owner_user"))
            report.facts_skipped[reason] = report.facts_skipped.get(reason, 0) + 1

    # Skills: the skills table plus the named owners' skill-kind fragments.
    skills = _read_ro(source_path, "skills", SKILL_COLUMNS)
    report.source_skills = len(skills) + len(skill_fragments)
    skills_outcome, skill_fragment_outcome = [], {}
    for row in skills:
        reason = _skill_skip_reason(row, owner_users, row["description"], row["body"], name=row["name"])
        skills_outcome.append(reason or "ported")
        if reason is not None:
            report.skills_skipped[reason] = report.skills_skipped.get(reason, 0) + 1
            continue
        minted = _port_skill(store, protocol, source_key="skills:" + row["id"],
                             name=row["name"], purpose=row["description"],
                             body=row["body"], provenance=row["provenance_json"])
        report.skills_minted += minted
        report.skills_unchanged += not minted
    for row in skill_fragments:
        text = (row["text"] or "").strip()
        reason = _skill_skip_reason(row, owner_users, text)
        skill_fragment_outcome[row["id"]] = reason or "ported"
        if reason is not None:
            report.skills_skipped[reason] = report.skills_skipped.get(reason, 0) + 1
            continue
        minted = _port_skill(store, protocol, source_key="fragments:" + row["id"],
                             name=text.splitlines()[0][:120] if text else row["id"],
                             purpose=text, body=text, provenance=row["provenance_json"])
        report.skills_minted += minted
        report.skills_unchanged += not minted

    # Wiring: machine setup knowledge, kept as setup memory.
    wiring = _read_ro(source_path, "wiring", WIRING_COLUMNS)
    report.source_wiring = len(wiring)
    for row in wiring:
        before = store.snapshot().revision
        text = ("Legacy Brain wiring (retired brainwrap era): %s %s on %s, status %s, "
                "capabilities %s" % (row["kind"], row["name"], row["device_id"],
                                     row["status"], row["capabilities_json"]))
        remember(store, session_root=session_root,
                 fragment_id=WIRING_PREFIX + _digest(row["device_id"], row["name"]),
                 text=text, kind="setup", origin=PORT_ORIGIN,
                 clock=_epoch_ms(row["last_seen"]) or 1, confidence="extracted")
        changed = store.snapshot().revision != before
        report.wiring_imported += changed
        report.wiring_unchanged += not changed

    snapshot = store.snapshot()
    held = memories(snapshot, session_root=session_root, include_forgotten=True)
    held_ids = {m.fragment_id for m in held}
    report.graph_wiring = sum(1 for m in held if m.fragment_id.startswith(WIRING_PREFIX))
    report.graph_facts = sum(1 for row in fact_rows if row["id"] in held_ids)
    report.graph_skills = _graph_legacy_skills(snapshot, protocol)

    fragments_outcome = []
    for row in all_fragments:
        if row.get("scope") == "community":
            fragments_outcome.append("scope:community")
        elif row["id"] in skill_fragment_outcome:
            fragments_outcome.append(skill_fragment_outcome[row["id"]])
        elif row["id"] in held_ids:
            fragments_outcome.append("ported")
        elif row.get("owner_user") in owner_users:
            fragments_outcome.append(_skip_reason(row, row.get("owner_user")) or "refused")
        else:
            fragments_outcome.append(_owner_reason(row.get("owner_user")))
    report.tables = _account_tables(source_path, fragments_outcome, skills_outcome,
                                    len(wiring), report.graph_wiring)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, help="legacy brain.db (opened mode=ro)")
    parser.add_argument("--state", required=True, help="the application graph sqlite path")
    parser.add_argument("--owner-user", action="append", required=True,
                        help="a legacy owner_user that is the founder (repeat)")
    args = parser.parse_args(argv)
    from .application_server import ApplicationServer
    server = ApplicationServer(universal_state_path=Path(args.state))
    try:
        with commit_intent.declare(commit_intent.MIGRATION, actor="app:archhub",
                                   reason="port the retired personal Brain store"):
            report = port_legacy_brain(server.universal_store,
                                       server.universal_registry.assembly_protocol,
                                       args.source, owner_users=args.owner_user)
    finally:
        server.close()
    print(json.dumps({**asdict(report), "accounted": report.accounted()}, sort_keys=True))
    return 0 if all(report.accounted().values()) else 1


if __name__ == "__main__":
    sys.exit(main())