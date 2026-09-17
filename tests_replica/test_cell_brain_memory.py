"""Courts for graph-held personal memory.

The legacy brain kept every fact in a SQLite table beside the graph and handed
the graph hash receipts. These courts hold the replacement to the graph's own
laws: a memory is Cells; it has exactly one owner, read from the session the
call acts in and never passed by the caller; a memory lands whole or not at
all; its text and state travel by the sync law; a replay changes nothing; and
two replicas converge whatever order records arrive in.

Credential-shaped fixtures are assembled at runtime so repository secret
scanners do not see literal tokens in this file.
"""
from __future__ import annotations

import itertools
import random
import string

import pytest

from nodelang import cell_brain_ownership as ownership
from nodelang.cell_brain_memory import (
    FORGOTTEN,
    LIVE,
    MEMORY_ROOT,
    entry_root,
    export_memories,
    forget,
    memories,
    merge_memories,
    recall_memory,
    remember,
)
from nodelang.cell_protocols import build_relation
from nodelang.cell_session_state import ACTIVE, CLOSED, move_to, open_session
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, Conflict, InvalidCell

FOUNDER = "app:users:founder"
COLLEAGUE = "app:users:colleague"
FOUNDER_SESSION = "app:sessions:founder-desktop"
COLLEAGUE_SESSION = "app:sessions:colleague-laptop"

_DIGITS = "0123456789"
_HEX = "0123456789abcdef"

# Credentials inside prose. The review's first eight (brain-review/probes.py P7)
# and the second review's misses (probes2.py), built at runtime.
CREDENTIALS_IN_PROSE = (
    "OpenAI key for the renderer is " + "sk" + "-proj-AbCdEf" + _DIGITS + "XyZabc",
    "Authorization: " + "Bea" + "rer eyJhbGciOiJIUzI1NiJ9" + ".eyJzdWIiOiIxIn0.c2lnbmF0dXJlMTIz",
    "use github token " + "gh" + "p_" + _DIGITS + "abcdefABCDEF" + _DIGITS + "abcd for CI",
    "the NAS password is hunter2hunter2",
    "AWS " + "AK" + "IAIOSFODNN7EXAMPLE with wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "-----BEGIN OPENSSH " + "PRIVATE KEY----- b3BlbnNzaC1rZXktdjEAAAAABG5vbmU",
    "maps key " + "AI" + "zaSyA" + _DIGITS + "abcdefghijklmnopqrstu",
    "api_key = " + "sk" + "-live-" + _DIGITS + "abcdef",
    "export " + "PGPASS" + "WORD=hunter22 before psql",
    "staging DB_" + "PASS" + "WORD=Sup3rS3cret!",
    "postgresql://archhub:" + "Pa55w0rd" + "@db.internal:5432/brain",
    "Authorization: " + "Ba" + "sic YWRtaW46cGFzc3dvcmQxMjM=",
    "OpenAI key " + "sk" + "-proj-Ab" + "​" + "CdEf" + _DIGITS + "XyZabc",
    "the NAS password is correcthorsebatterystaple",
    "secret half wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY on its own",
    "Authorization: " + "Bea" + "rer 9f8e7d6c5b4a39281706f5e4d3c2b1a0",
    # review round 3: invisible separators that are not Unicode Cf
    "OpenAI key " + "sk" + "-proj-Ab" + "\u034f" + "CdEf" + _DIGITS + "XyZabc",
    "OpenAI key " + "sk" + "-proj-Ab" + "\u3164" + "CdEf" + _DIGITS + "XyZabc",
    # review round 3: a full-width keyword is the same keyword after NFKC
    "export PG" + "\uff30\uff21\uff33\uff33" + "WORD=hunter22 before psql",
)

ORDINARY_SENTENCES = (
    "the wifi password is on the fridge",
    "Revit 2025 broker listens on :48885",
    "slice hash 735b529994d3a9c640d9aa0a0ddd37a78f6d44e84594b0b406dbdf23abe836d1",
    "drawing set at https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456/view",
    "call getBrainMemoryExportSinceClock2Owner after the sync",
    "integrity sha384-oqVuAfXRKap7fdgcCY5uykM6+R9GqQ8K/uxy9rx7HNQlGYl1kPzQho1wx4JwY8wC",
    "see 70.HANDOFFS/claude-codex-link-20260914/brain-port/sprint1-fixes/MANIFEST.txt",
)


def _store():
    store = CellStore()
    store.commit(store.revision, create=(
        Cell(FOUNDER, NULL_CELL_ID, NULL_CELL_ID, b"founder"),
        Cell(COLLEAGUE, NULL_CELL_ID, NULL_CELL_ID, b"colleague"),
    ))
    open_session(store, session_root=FOUNDER_SESSION, owner_root=FOUNDER)
    open_session(store, session_root=COLLEAGUE_SESSION, owner_root=COLLEAGUE)
    return store


def _remember(store, fragment_id="fact-rate", text="Site rate is 450 AED/m2",
              clock=10, origin="desktop", kind="fact", session=FOUNDER_SESSION):
    return remember(store, session_root=session, fragment_id=fragment_id, text=text,
                    kind=kind, origin=origin, clock=clock)


def _recall(snapshot, fragment_id="fact-rate", session=FOUNDER_SESSION):
    return recall_memory(snapshot, fragment_id, session_root=session)


def test_a_remembered_fact_is_read_back_with_its_owner_and_provenance():
    store = _store()
    _remember(store)
    memory = _recall(store.snapshot())
    assert memory.text == "Site rate is 450 AED/m2"
    assert (memory.kind, memory.confidence, memory.owner_root, memory.state) == (
        "fact", "extracted", FOUNDER, LIVE)
    assert (memory.text_origin, memory.text_clock) == ("desktop", 10)


def test_the_memory_is_held_as_cells_in_the_graph_not_beside_it():
    store = _store()
    _remember(store)
    snapshot = store.snapshot()
    assert MEMORY_ROOT in snapshot.cells
    held_text = [c for c in snapshot.cells.values()
                 if c.atom == "Site rate is 450 AED/m2".encode("utf-8")]
    assert len(held_text) == 1
    assert held_text[0].id.startswith(MEMORY_ROOT + ":entry:")


# --- review HIGH 1: the owner comes from the session, never from the caller --

@pytest.mark.parametrize("call", [
    lambda s: remember(s, owner_root=FOUNDER, fragment_id="fact-rate", text="tampered",
                       kind="fact", origin="colleague-laptop", clock=200),
    lambda s: forget(s, owner_root=FOUNDER, fragment_id="fact-rate",
                     origin="colleague-laptop", clock=200),
])
def test_no_call_accepts_an_owner_named_by_the_caller(call):
    store = _store()
    _remember(store)
    settled = store.snapshot().revision
    with pytest.raises(TypeError):
        call(store)
    assert store.snapshot().revision == settled


@pytest.mark.parametrize("pretend", (FOUNDER, "app:users:nobody", "", None))
def test_a_caller_cannot_act_for_an_account_by_naming_it_as_the_session(pretend):
    store = _store()
    _remember(store, text="founder rate 450")
    settled = store.snapshot().revision
    with pytest.raises(InvalidCell):
        remember(store, session_root=pretend, fragment_id="fact-rate", text="tampered",
                 kind="fact", origin="colleague-laptop", clock=200)
    with pytest.raises(InvalidCell):
        forget(store, session_root=pretend, fragment_id="fact-rate",
               origin="colleague-laptop", clock=200)
    assert store.snapshot().revision == settled
    assert _recall(store.snapshot()).text == "founder rate 450"


def test_a_colleague_session_cannot_forget_edit_read_export_or_merge_founder_memory():
    store = _store()
    _remember(store, text="founder rate 450", clock=10)
    founder_export = export_memories(store.snapshot(), session_root=FOUNDER_SESSION)
    settled = store.snapshot().revision
    with pytest.raises(InvalidCell):
        forget(store, session_root=COLLEAGUE_SESSION, fragment_id="fact-rate",
               origin="colleague-laptop", clock=99)
    with pytest.raises(InvalidCell):
        merge_memories(store, founder_export, session_root=COLLEAGUE_SESSION)
    assert store.snapshot().revision == settled
    snapshot = store.snapshot()
    assert _recall(snapshot, session=COLLEAGUE_SESSION) is None
    assert memories(snapshot, session_root=COLLEAGUE_SESSION, include_forgotten=True) == ()
    _remember(store, text="tampered", clock=200, origin="colleague-laptop",
              session=COLLEAGUE_SESSION)
    founder = _recall(store.snapshot())
    assert (founder.text, founder.state) == ("founder rate 450", LIVE)


def test_a_closed_session_acts_for_nobody():
    store = _store()
    _remember(store)
    move_to(store, FOUNDER_SESSION, ACTIVE)
    move_to(store, FOUNDER_SESSION, CLOSED)
    settled = store.snapshot().revision
    with pytest.raises(InvalidCell):
        _remember(store, text="after close", clock=50)
    with pytest.raises(InvalidCell):
        _recall(store.snapshot())
    assert store.snapshot().revision == settled


def test_a_memory_bound_to_someone_else_is_neither_reachable_nor_listed():
    store = _store()
    _remember(store, fragment_id="fact-t", text="to be transferred")
    root = entry_root(FOUNDER, "fact-t")
    store.commit(store.snapshot().revision, create=(
        Cell("app:test:role:party", NULL_CELL_ID, NULL_CELL_ID, b"party"),))
    consent = build_relation(store, (("app:test:role:party", FOUNDER),
                                     ("app:test:role:party", root)))
    ownership.transfer_owner(store, subject_root=root, to_owner_root=COLLEAGUE,
                             consent_root=consent.root_id)
    snapshot = store.snapshot()
    with pytest.raises(InvalidCell):
        _recall(snapshot, "fact-t")
    with pytest.raises(InvalidCell):
        forget(store, session_root=FOUNDER_SESSION, fragment_id="fact-t",
               origin="desktop", clock=99)
    assert memories(snapshot, session_root=COLLEAGUE_SESSION, include_forgotten=True) == ()


def test_the_same_source_id_under_two_owners_is_two_memories():
    store = _store()
    _remember(store, text="founder note", clock=10)
    _remember(store, text="colleague note", clock=5, session=COLLEAGUE_SESSION)
    snapshot = store.snapshot()
    assert _recall(snapshot).text == "founder note"
    assert _recall(snapshot, session=COLLEAGUE_SESSION).text == "colleague note"


# --- review HIGH 2: credentials inside prose, without refusing ordinary text --

@pytest.mark.parametrize("text", CREDENTIALS_IN_PROSE)
def test_a_credential_inside_a_sentence_is_refused_without_writing_or_echoing(text):
    store = _store()
    settled = store.snapshot().revision
    with pytest.raises(InvalidCell) as refused:
        _remember(store, text=text)
    assert store.snapshot().revision == settled
    assert text not in str(refused.value)


@pytest.mark.parametrize("text", ORDINARY_SENTENCES)
def test_ordinary_sentences_are_still_remembered(text):
    store = _store()
    _remember(store, text=text)
    assert _recall(store.snapshot()).text == text


def test_a_credential_in_a_source_id_or_origin_is_refused_without_echo():
    store = _store()
    token = "gh" + "p_" + _DIGITS + "abcdefABCDEF" + _DIGITS + "abcd"
    settled = store.snapshot().revision
    for options in ({"fragment_id": token}, {"origin": token}):
        with pytest.raises(InvalidCell) as refused:
            _remember(store, **options)
        assert token not in str(refused.value)
    assert store.snapshot().revision == settled


@pytest.mark.parametrize("field,value", [
    ("kind", "skill"), ("kind", "secret_ref"), ("kind", "banana"),
    ("text", "   "), ("fragment_id", ""),
])
def test_what_is_not_a_personal_memory_is_refused_without_writing(field, value):
    store = _store()
    before = store.snapshot().revision
    arguments = {"fragment_id": "fact-rate", "text": "Site rate is 450 AED/m2",
                 "kind": "fact"}
    arguments[field] = value
    with pytest.raises(InvalidCell):
        remember(store, session_root=FOUNDER_SESSION, origin="desktop", clock=10,
                 **arguments)
    assert store.snapshot().revision == before


# --- sync law ---------------------------------------------------------------

def test_a_newer_edit_wins_and_an_older_one_is_ignored():
    store = _store()
    _remember(store, text="rate 400", clock=10)
    _remember(store, text="rate 450", clock=20)
    _remember(store, text="rate 300", clock=5)
    assert _recall(store.snapshot()).text == "rate 450"


def test_remembering_the_same_thing_again_changes_nothing():
    store = _store()
    _remember(store)
    settled = store.snapshot().revision
    _remember(store)
    assert store.snapshot().revision == settled


def test_a_memory_cannot_change_kind_by_being_remembered_again():
    store = _store()
    _remember(store)
    with pytest.raises(InvalidCell):
        _remember(store, kind="setup", clock=30)


def test_forgetting_hides_a_memory_but_keeps_what_it_was():
    store = _store()
    _remember(store, clock=10)
    forget(store, session_root=FOUNDER_SESSION, fragment_id="fact-rate",
           origin="desktop", clock=15)
    snapshot = store.snapshot()
    assert memories(snapshot, session_root=FOUNDER_SESSION) == ()
    kept = _recall(snapshot)
    assert (kept.state, kept.text) == (FORGOTTEN, "Site rate is 450 AED/m2")


def test_an_older_remember_cannot_undo_a_newer_forget_but_a_newer_one_can():
    store = _store()
    _remember(store, clock=10)
    forget(store, session_root=FOUNDER_SESSION, fragment_id="fact-rate",
           origin="desktop", clock=15)
    _remember(store, clock=12)
    assert _recall(store.snapshot()).state == FORGOTTEN
    _remember(store, text="rate confirmed again", clock=40)
    memory = _recall(store.snapshot())
    assert (memory.state, memory.text) == (LIVE, "rate confirmed again")


def test_forgetting_something_never_remembered_is_refused():
    with pytest.raises(InvalidCell):
        forget(_store(), session_root=FOUNDER_SESSION, fragment_id="fact-missing",
               origin="desktop", clock=1)


def test_memories_are_listed_per_owner_and_kind():
    store = _store()
    _remember(store, fragment_id="fact-rate")
    _remember(store, fragment_id="setup-revit", text="Revit 2025 on :48885", kind="setup")
    _remember(store, fragment_id="fact-colleague", text="Prefers A1 sheets",
              session=COLLEAGUE_SESSION)
    snapshot = store.snapshot()
    assert {m.fragment_id for m in memories(snapshot, session_root=FOUNDER_SESSION)} == {
        "fact-rate", "setup-revit"}
    assert [m.fragment_id for m in memories(
        snapshot, session_root=FOUNDER_SESSION, kind="setup")] == ["setup-revit"]
    assert [m.fragment_id for m in memories(
        snapshot, session_root=COLLEAGUE_SESSION)] == ["fact-colleague"]


def test_every_arrival_order_reaches_the_same_memory():
    source = _store()
    _remember(source, clock=10, origin="desktop")
    _remember(source, text="rate 450", clock=20, origin="phone")
    forget(source, session_root=FOUNDER_SESSION, fragment_id="fact-rate",
           origin="desktop", clock=25)
    _remember(source, fragment_id="setup-revit", text="Revit 2025 on :48885",
              kind="setup", clock=30)
    records = export_memories(source.snapshot(), session_root=FOUNDER_SESSION)
    reference = None
    for order in itertools.permutations(records):
        replica = _store()
        merge_memories(replica, order, session_root=FOUNDER_SESSION)
        state = tuple(_recall(replica.snapshot(), fid) for fid in ("fact-rate", "setup-revit"))
        reference = reference or state
        assert state == reference
    assert reference == (_recall(source.snapshot(), "fact-rate"),
                         _recall(source.snapshot(), "setup-revit"))


def test_merging_the_same_export_twice_changes_nothing():
    source = _store()
    _remember(source)
    replica = _store()
    records = export_memories(source.snapshot(), session_root=FOUNDER_SESSION)
    merge_memories(replica, records, session_root=FOUNDER_SESSION)
    settled = replica.snapshot().revision
    merge_memories(replica, records, session_root=FOUNDER_SESSION)
    assert replica.snapshot().revision == settled


def test_export_since_a_clock_leaves_older_memories_alone():
    store = _store()
    _remember(store, fragment_id="fact-old", clock=5)
    _remember(store, fragment_id="fact-new", clock=50)
    assert [m.fragment_id for m in export_memories(
        store.snapshot(), session_root=FOUNDER_SESSION, since_clock=20)] == ["fact-new"]


# --- review MEDIUM: merge is all-or-nothing, and one record is one commit ----

def test_a_bare_random_key_half_is_refused_whatever_its_letters():
    """Review round 3: the lower-case-run limit admitted about a quarter of
    random 40-character key halves (probes3.py P12: 484 of 2000)."""
    rng = random.Random(20260917)
    alphabet = string.ascii_letters + string.digits + "+/"
    admitted = 0
    for _ in range(400):
        store = _store()
        key = "".join(rng.choice(alphabet) for _ in range(40))
        try:
            _remember(store, text="aws secret " + key + " for the render farm")
        except InvalidCell as refused:
            assert key not in str(refused)
            continue
        admitted += 1
    assert admitted <= 8, admitted


def test_a_bare_32_character_key_is_refused_whatever_its_letters():
    """Review round 3: a 32-character base62 API key (the shortest the word rule
    looks at) was admitted 176 times in 400 by the lower-case-run limit."""
    rng = random.Random(20260917)
    alphabet = string.ascii_letters + string.digits
    admitted = 0
    for _ in range(400):
        key = "".join(rng.choice(alphabet) for _ in range(32))
        try:
            _remember(_store(), text="dashscope key " + key + " for renders")
        except InvalidCell as refused:
            assert key not in str(refused)
            continue
        admitted += 1
    assert admitted <= 20, admitted


def test_a_merge_carrying_one_new_id_with_two_kinds_writes_nothing():
    """Review round 3: the precheck only compared records with the graph, so a
    batch naming one NEW id as a fact and as a setup wrote the first
    (probes3.py P10)."""
    as_fact, as_setup = _store(), _store()
    _remember(as_fact, fragment_id="fact-dup", text="filed as a fact", clock=11)
    _remember(as_setup, fragment_id="fact-dup", text="filed as a setup", kind="setup",
              clock=12, origin="laptop")
    batch = (export_memories(as_fact.snapshot(), session_root=FOUNDER_SESSION)[0],
             export_memories(as_setup.snapshot(), session_root=FOUNDER_SESSION)[0])
    for order in (batch, tuple(reversed(batch))):
        replica = _store()
        settled = replica.snapshot().revision
        with pytest.raises(InvalidCell):
            merge_memories(replica, order, session_root=FOUNDER_SESSION)
        assert replica.snapshot().revision == settled


def test_a_merge_with_one_bad_record_writes_nothing():
    source = _store()
    _remember(source, fragment_id="fact-new", text="brand new", clock=20)
    _remember(source, fragment_id="fact-a", text="filed as a setup", kind="setup", clock=11)
    records = export_memories(source.snapshot(), session_root=FOUNDER_SESSION)
    for order in (records, tuple(reversed(records))):
        replica = _store()
        _remember(replica, fragment_id="fact-a", text="filed as a fact", clock=5)
        settled = replica.snapshot().revision
        with pytest.raises(InvalidCell):
            merge_memories(replica, order, session_root=FOUNDER_SESSION)
        assert replica.snapshot().revision == settled
        assert _recall(replica.snapshot(), "fact-new") is None


# --- F2: every memory write lands whole or not at all ------------------------

class _FailingStore:
    def __init__(self, inner, fail_at, error):
        self.inner, self.fail_at, self.error, self.commits = inner, fail_at, error, 0

    def snapshot(self):
        return self.inner.snapshot()

    @property
    def revision(self):
        return self.inner.revision

    def commit(self, *args, **kwargs):
        self.commits += 1
        if self.commits == self.fail_at:
            raise self.error("injected")
        return self.inner.commit(*args, **kwargs)


def _commits(store, write):
    counter = _FailingStore(store, 10 ** 9, RuntimeError)
    write(counter)
    return counter.commits


def _whole(snapshot, fragment_id, pairs):
    memory = _recall(snapshot, fragment_id)
    listed = [m.fragment_id for m in memories(snapshot, session_root=FOUNDER_SESSION,
                                             include_forgotten=True)]
    if memory is None:
        assert fragment_id not in listed
        return None
    assert fragment_id in listed
    assert (memory.text, memory.state) in pairs
    return memory.text, memory.state


@pytest.mark.parametrize("error", (RuntimeError, Conflict))
def test_a_failure_at_any_commit_of_a_new_memory_leaves_none_or_a_whole_one(error):
    write = lambda s: _remember(s, fragment_id="fact-x", text="x")
    fresh = _commits(_store(), write)
    warm = _store()
    _remember(warm, fragment_id="fact-warm", text="registries exist")
    assert _commits(warm, write) == 1
    for fail_at in range(1, fresh + 1):
        store = _store()
        try:
            write(_FailingStore(store, fail_at, error))
        except (RuntimeError, Conflict):
            pass
        outcome = _whole(store.snapshot(), "fact-x", {("x", LIVE)})
        if error is Conflict:
            assert outcome == ("x", LIVE)


@pytest.mark.parametrize("error", (RuntimeError, Conflict))
def test_an_edit_and_a_merged_forget_land_text_and_state_together(error):
    def prepared():
        store = _store()
        _remember(store, fragment_id="fact-e", text="v1", clock=10)
        forget(store, session_root=FOUNDER_SESSION, fragment_id="fact-e",
               origin="desktop", clock=15)
        return store

    edit = lambda s: _remember(s, fragment_id="fact-e", text="v2 confirmed again", clock=20)
    assert _commits(prepared(), edit) == 1
    before, after = ("v1", FORGOTTEN), ("v2 confirmed again", LIVE)
    store = prepared()
    try:
        edit(_FailingStore(store, 1, error))
    except (RuntimeError, Conflict):
        pass
    assert _whole(store.snapshot(), "fact-e", {before, after}) in {before, after}

    source = _store()
    _remember(source, fragment_id="fact-f", text="gone", clock=10)
    forget(source, session_root=FOUNDER_SESSION, fragment_id="fact-f",
           origin="desktop", clock=12)
    records = export_memories(source.snapshot(), session_root=FOUNDER_SESSION)
    replica = _store()
    _remember(replica, fragment_id="warm", text="registries exist")
    try:
        merge_memories(_FailingStore(replica, 1, error), records,
                       session_root=FOUNDER_SESSION)
    except (RuntimeError, Conflict):
        pass
    assert _whole(replica.snapshot(), "fact-f", {("gone", FORGOTTEN)}) in {
        None, ("gone", FORGOTTEN)}
