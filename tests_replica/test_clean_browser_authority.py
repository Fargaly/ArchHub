from __future__ import annotations

from pathlib import Path
import threading
import time
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import nodelang.clean_browser_authority as clean_browser_authority
from nodelang.cell_attention import (
    active_focus,
    install_attention_protocol,
    open_attention_protocol,
)
from nodelang.cell_browser_sessions import BrowserSessionDenied
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.clean_browser_authority import (
    install_clean_browser_authority,
    issue_clean_browser_session,
    open_clean_browser_authority,
    revise_clean_browser_focus,
    revoke_clean_browser_session,
    verify_clean_browser_session,
)
from nodelang.unified_application_lens import project_unified_scope
from nodelang.unified_authority import (
    relation_members,
    BootstrapManifest,
    composition_root,
    create_unified_authority,
    enroll_session,
    open_unified_authority,
)
from nodelang.universal_cell import CellStore, Conflict, InvalidCell


PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
PUBLIC = PRIVATE.public_key().public_bytes(
    serialization.Encoding.Raw,
    serialization.PublicFormat.Raw,
)
AUTHORITY_SECRET = b"clean-browser-authority-key" + b"0" * 5


class _Caller:
    def __init__(self, authority, private_key=PRIVATE, session_root=None):
        self.actor_root = authority.manifest.principal_root
        self.session_root = (
            authority.manifest.bootstrap_session_root
            if session_root is None
            else session_root
        )
        self.public_key = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        self._private_key = private_key

    def sign(self, payload: bytes) -> bytes:
        return self._private_key.sign(payload)


def _provider():
    return MemorySigningKeyProvider(
        "clean-browser-authority",
        AUTHORITY_SECRET,
    )


def _authority(store=None, provider=None):
    return create_unified_authority(
        store or CellStore(),
        provider or _provider(),
        key_id="clean-browser-authority",
        application_label="ArchHub",
        principal_label="Founder",
        bootstrap_session_label="Clean browser authority court",
        bootstrap_session_public_key=PUBLIC,
        composition_labels=("Interface", "Workshop", "Agent Sessions"),
    )


def _focus_ready_authority(store=None, provider=None):
    return _authority(store, provider)


def _second_caller(authority, caller, label="Second browser"):
    private_key = Ed25519PrivateKey.generate()
    session_root = enroll_session(
        authority,
        label,
        private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        ),
        session_container_root=composition_root(
            authority,
            "Agent Sessions",
            caller=caller,
        ),
        caller=caller,
        command_id=str(uuid.uuid4()),
    ).root_id
    return _Caller(authority, private_key, session_root)


def test_browser_protocol_is_one_graph_and_semantically_unique_across_commands():
    authority = _authority()
    caller = _Caller(authority)
    first = install_clean_browser_authority(
        authority,
        caller=caller,
        command_id=str(uuid.uuid4()),
    )
    revision = authority.store.revision
    cell_count = len(authority.store.snapshot().cells)

    second = install_clean_browser_authority(
        authority,
        caller=caller,
        command_id=str(uuid.uuid4()),
    )

    assert first.graph_id == second.graph_id == authority.manifest.graph_id
    assert first.root_id == second.root_id
    assert first.protocol.root_id == second.protocol.root_id
    assert authority.store.revision == revision
    assert len(authority.store.snapshot().cells) == cell_count
    assert all(
        str(uuid.UUID(root)) == root
        for root in (
            first.root_id,
            first.protocol.root_id,
            *first.protocol.roles.values(),
            *first.protocol.states.values(),
        )
    )



def test_two_sessions_racing_first_install_have_one_winner_and_zero_growth_retry(
    monkeypatch,
):
    authority = _authority()
    caller = _Caller(authority)
    other = _second_caller(authority, caller)
    # install_clean_browser_authority installs the attention protocol as a
    # prerequisite, which is itself one idempotent commit. Settle it before
    # the baseline so this court measures the browser install alone; without
    # this the assertion below counts a prerequisite as a second racer.
    install_attention_protocol(
        authority,
        caller=caller,
        command_id=str(uuid.uuid5(uuid.uuid4(), "attention-protocol")),
    )
    base_revision = authority.store.revision
    base_cell_count = len(authority.store.snapshot().cells)
    barrier = threading.Barrier(2, timeout=10.0)
    original_compile = clean_browser_authority._compile_source
    outcomes = []
    outcome_lock = threading.Lock()

    def synchronized_compile():
        barrier.wait()
        return original_compile()

    monkeypatch.setattr(
        clean_browser_authority,
        "_compile_source",
        synchronized_compile,
    )

    def install(active_caller, command_id):
        try:
            result = install_clean_browser_authority(
                authority,
                caller=active_caller,
                command_id=command_id,
            )
            outcome = ("success", active_caller, command_id, result)
        except Exception as exc:  # Captured for exact race assertions below.
            outcome = ("failure", active_caller, command_id, exc)
        with outcome_lock:
            outcomes.append(outcome)

    command_a = str(uuid.uuid4())
    command_b = str(uuid.uuid4())
    left = threading.Thread(target=install, args=(caller, command_a))
    right = threading.Thread(target=install, args=(other, command_b))
    left.start()
    right.start()
    left.join(timeout=20.0)
    right.join(timeout=20.0)
    assert not left.is_alive()
    assert not right.is_alive()

    successes = [item for item in outcomes if item[0] == "success"]
    failures = [item for item in outcomes if item[0] == "failure"]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0][3], Conflict)
    winner = successes[0][3]
    assert winner.graph_id == authority.manifest.graph_id
    assert authority.store.revision == base_revision + 1
    assert len(authority.store.snapshot().cells) > base_cell_count

    accepted_revision = authority.store.revision
    accepted_cell_count = len(authority.store.snapshot().cells)
    losing_caller = failures[0][1]
    losing_command = failures[0][2]
    retry = install_clean_browser_authority(
        authority,
        caller=losing_caller,
        command_id=losing_command,
    )
    assert retry.root_id == winner.root_id
    assert retry.protocol.root_id == winner.protocol.root_id
    assert authority.store.revision == accepted_revision
    assert len(authority.store.snapshot().cells) == accepted_cell_count


def test_two_browser_sessions_are_isolated_bound_and_fail_closed():
    authority = _authority()
    caller_a = _Caller(authority)
    browser = install_clean_browser_authority(
        authority,
        caller=caller_a,
        command_id=str(uuid.uuid4()),
    )
    caller_b = _second_caller(authority, caller_a)
    token_a, csrf_a = "browser-a-token", "browser-a-csrf"
    token_b, csrf_b = "browser-b-token", "browser-b-csrf"

    issued_a = issue_clean_browser_session(
        authority,
        browser,
        token=token_a,
        csrf_token=csrf_a,
        lifetime_seconds=120.0,
        caller=caller_a,
        command_id=str(uuid.uuid4()),
    )
    issued_b = issue_clean_browser_session(
        authority,
        browser,
        token=token_b,
        csrf_token=csrf_b,
        lifetime_seconds=120.0,
        caller=caller_b,
        command_id=str(uuid.uuid4()),
    )

    assert issued_a.graph_id == issued_b.graph_id == authority.manifest.graph_id
    assert issued_a.root_id != issued_b.root_id
    assert issued_a.subject_root == issued_b.subject_root == caller_a.actor_root
    assert issued_a.view_root == caller_a.session_root
    assert issued_b.view_root == caller_b.session_root
    assert issued_a.tenant_root == issued_b.tenant_root == authority.manifest.application_root
    assert issued_a.accepted_revision < issued_b.accepted_revision
    assert issued_b.revision == authority.store.revision
    assert verify_clean_browser_session(
        authority,
        browser,
        issued_a.root_id,
        token=token_a,
        csrf_token=csrf_a,
        require_csrf=True,
    ).root_id == issued_a.root_id
    assert verify_clean_browser_session(
        authority,
        browser,
        issued_b.root_id,
        token=token_b,
        csrf_token=csrf_b,
        require_csrf=True,
    ).root_id == issued_b.root_id
    with pytest.raises(BrowserSessionDenied, match="credential"):
        verify_clean_browser_session(
            authority,
            browser,
            issued_a.root_id,
            token=token_b,
        )
    with pytest.raises(BrowserSessionDenied, match="CSRF"):
        verify_clean_browser_session(
            authority,
            browser,
            issued_b.root_id,
            token=token_b,
            csrf_token=csrf_a,
            require_csrf=True,
        )
    with pytest.raises(BrowserSessionDenied, match="expired"):
        verify_clean_browser_session(
            authority,
            browser,
            issued_a.root_id,
            token=token_a,
            now=time.time() + 3601.0,
        )

    atoms = b"\n".join(
        cell.atom for cell in authority.store.snapshot().cells.values()
    )
    assert token_a.encode() not in atoms
    assert csrf_a.encode() not in atoms
    assert token_b.encode() not in atoms
    assert csrf_b.encode() not in atoms


def test_signed_issue_revoke_and_replay_bind_exact_revisions_and_zero_growth():
    authority = _authority()
    caller = _Caller(authority)
    browser = install_clean_browser_authority(
        authority,
        caller=caller,
        command_id=str(uuid.uuid4()),
    )
    issue_command = str(uuid.uuid4())
    request = dict(
        token="replay-browser-token",
        csrf_token="replay-browser-csrf",
        lifetime_seconds=300.0,
        caller=caller,
        command_id=issue_command,
    )
    issued = issue_clean_browser_session(authority, browser, **request)
    accepted_revision = issued.accepted_revision

    _second_caller(authority, caller, label="Unrelated graph commit")
    revision_after_unrelated = authority.store.revision
    cell_count = len(authority.store.snapshot().cells)
    replay = issue_clean_browser_session(authority, browser, **request)

    assert replay.replayed is True
    assert replay.root_id == issued.root_id
    assert replay.accepted_revision == accepted_revision
    assert replay.revision == revision_after_unrelated
    assert authority.store.revision == revision_after_unrelated
    assert len(authority.store.snapshot().cells) == cell_count

    with pytest.raises(InvalidCell, match="credential.*registered"):
        issue_clean_browser_session(
            authority,
            browser,
            token=request["token"],
            csrf_token=request["csrf_token"],
            lifetime_seconds=request["lifetime_seconds"],
            caller=caller,
            command_id=str(uuid.uuid4()),
        )
    assert authority.store.revision == revision_after_unrelated
    assert len(authority.store.snapshot().cells) == cell_count

    revoke_command = str(uuid.uuid4())
    revoked = revoke_clean_browser_session(
        authority,
        browser,
        issued.root_id,
        reason="Founder signed out",
        caller=caller,
        command_id=revoke_command,
    )
    with pytest.raises(BrowserSessionDenied, match="revoked"):
        verify_clean_browser_session(
            authority,
            browser,
            issued.root_id,
            token=request["token"],
        )
    revoke_revision = authority.store.revision
    revoke_count = len(authority.store.snapshot().cells)
    replayed_revoke = revoke_clean_browser_session(
        authority,
        browser,
        issued.root_id,
        reason="Founder signed out",
        caller=caller,
        command_id=revoke_command,
    )
    assert replayed_revoke.replayed is True
    assert replayed_revoke.accepted_revision == revoked.accepted_revision
    assert replayed_revoke.revision == revoke_revision
    assert authority.store.revision == revoke_revision
    assert len(authority.store.snapshot().cells) == revoke_count


def test_browser_authority_reopens_and_replays_without_a_second_authority(tmp_path):
    database = tmp_path / "clean-browser-authority.sqlite3"
    provider = _provider()
    store = CellStore(database)
    authority = _authority(store, provider)
    caller = _Caller(authority)
    browser = install_clean_browser_authority(
        authority,
        caller=caller,
        command_id=str(uuid.uuid4()),
    )
    command_id = str(uuid.uuid4())
    request = dict(
        token="persistent-browser-token",
        csrf_token="persistent-browser-csrf",
        lifetime_seconds=300.0,
        caller=caller,
        command_id=command_id,
    )
    issued = issue_clean_browser_session(authority, browser, **request)
    manifest = authority.manifest.to_json()
    graph_id = authority.manifest.graph_id
    revision = store.revision
    count = len(store.snapshot().cells)
    store.close()

    reopened_store = CellStore(database)
    reopened = open_unified_authority(
        reopened_store,
        BootstrapManifest.from_json(manifest),
        provider,
    )
    reopened_browser = open_clean_browser_authority(reopened, caller=caller)
    replay = issue_clean_browser_session(reopened, reopened_browser, **request)

    assert reopened.manifest.graph_id == reopened_browser.graph_id == graph_id
    assert reopened_browser.root_id == browser.root_id
    assert replay.root_id == issued.root_id
    assert replay.replayed is True
    assert replay.accepted_revision == issued.accepted_revision
    assert replay.revision == revision
    assert reopened_store.revision == revision
    assert len(reopened_store.snapshot().cells) == count
    assert verify_clean_browser_session(
        reopened,
        reopened_browser,
        issued.root_id,
        token=request["token"],
        csrf_token=request["csrf_token"],
        require_csrf=True,
    ).root_id == issued.root_id
    reopened_store.close()


def test_focus_protocol_bootstraps_and_reopens_cleanly(tmp_path):
    database = tmp_path / "clean-browser-focus.sqlite3"
    provider = _provider()
    store = CellStore(database)
    authority = _authority(store, provider)
    caller = _Caller(authority)
    browser = install_clean_browser_authority(
        authority,
        caller=caller,
        command_id=str(uuid.uuid4()),
    )
    other = _second_caller(authority, caller, label="Other admitted session")
    issued = issue_clean_browser_session(
        authority,
        browser,
        token="focus-browser-token",
        csrf_token="focus-browser-csrf",
        lifetime_seconds=300.0,
        caller=caller,
        command_id=str(uuid.uuid4()),
    )
    workshop_root = composition_root(authority, "Workshop", caller=caller)
    interface_root = composition_root(authority, "Interface", caller=caller)
    scope_root = authority.manifest.application_root
    base_revision = authority.store.revision
    command_id = str(uuid.uuid4())
    first = revise_clean_browser_focus(
        authority,
        browser,
        issued.root_id,
        scope_root=scope_root,
        selected_roots=(workshop_root,),
        primary_root=workshop_root,
        caller=caller,
        command_id=command_id,
        expected_revision=base_revision,
    )
    protocol = open_attention_protocol(authority.store.snapshot())
    active = active_focus(
        authority.store.snapshot(),
        protocol,
        session_root=issued.view_root,
    )
    assert active is not None
    assert active.root_id == first.root_id
    assert active.scope_root == scope_root
    assert active.primary_root == workshop_root
    assert active.selected_roots == (workshop_root,)
    accepted_revision = first.revision
    accepted_cell_count = len(authority.store.snapshot().cells)
    _second_caller(authority, caller, label="Unrelated graph commit")
    replay = revise_clean_browser_focus(
        authority,
        browser,
        issued.root_id,
        scope_root=scope_root,
        selected_roots=(workshop_root,),
        primary_root=workshop_root,
        caller=caller,
        command_id=command_id,
        expected_revision=base_revision,
    )
    assert replay.replayed is True
    assert replay.root_id == first.root_id
    assert replay.revision == accepted_revision
    assert len(authority.store.snapshot().cells) > accepted_cell_count
    no_growth_revision = authority.store.revision
    no_growth_count = len(authority.store.snapshot().cells)
    same_state = revise_clean_browser_focus(
        authority,
        browser,
        issued.root_id,
        scope_root=scope_root,
        selected_roots=(workshop_root,),
        primary_root=workshop_root,
        caller=caller,
        command_id=str(uuid.uuid4()),
        expected_revision=no_growth_revision,
    )
    assert same_state.replayed is False
    assert same_state.root_id == first.root_id
    assert same_state.receipt_root
    assert same_state.revision > no_growth_revision
    assert authority.store.revision == same_state.revision
    assert len(authority.store.snapshot().cells) > no_growth_count
    second_result = revise_clean_browser_focus(
        authority,
        browser,
        issued.root_id,
        scope_root=scope_root,
        selected_roots=(interface_root, workshop_root),
        primary_root=interface_root,
        caller=caller,
        command_id=str(uuid.uuid4()),
        expected_revision=same_state.revision,
    )
    after_second = authority.store.snapshot()
    assert second_result.revision == after_second.revision
    current = active_focus(after_second, protocol, session_root=issued.view_root)
    assert current is not None
    assert current.primary_root == interface_root
    assert current.selected_roots == (interface_root, workshop_root)
    with pytest.raises(BrowserSessionDenied, match="another view session"):
        revise_clean_browser_focus(
            authority,
            browser,
            issued.root_id,
            scope_root=scope_root,
            selected_roots=(workshop_root,),
            primary_root=workshop_root,
            caller=other,
            command_id=str(uuid.uuid4()),
            expected_revision=after_second.revision,
        )
    revoked = revoke_clean_browser_session(
        authority,
        browser,
        issued.root_id,
        reason="focus revoked",
        caller=caller,
        command_id=str(uuid.uuid4()),
    )
    with pytest.raises(BrowserSessionDenied, match="revoked"):
        revise_clean_browser_focus(
            authority,
            browser,
            issued.root_id,
            scope_root=scope_root,
            selected_roots=(workshop_root,),
            primary_root=workshop_root,
            caller=caller,
            command_id=str(uuid.uuid4()),
            expected_revision=revoked.revision,
        )
    manifest = authority.manifest.to_json()
    graph_id = authority.manifest.graph_id
    focus_root = current.root_id
    final_revision = authority.store.revision
    store.close()

    reopened_store = CellStore(database)
    reopened = open_unified_authority(
        reopened_store,
        BootstrapManifest.from_json(manifest),
        provider,
    )
    reopened_browser = open_clean_browser_authority(reopened, caller=caller)
    reopened_focus = active_focus(
        reopened_store.snapshot(),
        open_attention_protocol(reopened_store.snapshot()),
        session_root=issued.view_root,
    )
    assert reopened.manifest.graph_id == reopened_browser.graph_id == graph_id
    assert reopened_focus is not None
    assert reopened_focus.root_id == focus_root
    assert reopened_focus.primary_root == interface_root
    assert reopened_focus.selected_roots == (interface_root, workshop_root)
    assert reopened_store.revision == final_revision
    reopened_store.close()


def test_fresh_same_focus_command_commits_receipt_not_false_replay(tmp_path):
    database = tmp_path / "clean-browser-focus-noop.sqlite3"
    provider = _provider()
    store = CellStore(database)
    authority = _focus_ready_authority(store, provider)
    caller = _Caller(authority)
    browser = install_clean_browser_authority(
        authority,
        caller=caller,
        command_id=str(uuid.uuid4()),
    )
    issued = issue_clean_browser_session(
        authority,
        browser,
        token="focus-noop-token",
        csrf_token="focus-noop-csrf",
        lifetime_seconds=300.0,
        caller=caller,
        command_id=str(uuid.uuid4()),
    )
    workshop_root = composition_root(authority, "Workshop", caller=caller)
    scope_root = authority.manifest.application_root
    first_command = str(uuid.uuid4())
    first_revision = authority.store.revision
    first = revise_clean_browser_focus(
        authority,
        browser,
        issued.root_id,
        scope_root=scope_root,
        selected_roots=(workshop_root,),
        primary_root=workshop_root,
        caller=caller,
        command_id=first_command,
        expected_revision=first_revision,
    )
    replay = revise_clean_browser_focus(
        authority,
        browser,
        issued.root_id,
        scope_root=scope_root,
        selected_roots=(workshop_root,),
        primary_root=workshop_root,
        caller=caller,
        command_id=first_command,
        expected_revision=first_revision,
    )
    assert replay.replayed is True
    assert replay.receipt_root == first.receipt_root
    before_noop_revision = authority.store.revision
    before_noop_count = len(authority.store.snapshot().cells)
    _second_caller(authority, caller, label="Fresh no-op unrelated commit")
    fresh_same = revise_clean_browser_focus(
        authority,
        browser,
        issued.root_id,
        scope_root=scope_root,
        selected_roots=(workshop_root,),
        primary_root=workshop_root,
        caller=caller,
        command_id=str(uuid.uuid4()),
        expected_revision=authority.store.revision,
    )
    assert fresh_same.replayed is False
    assert fresh_same.receipt_root
    assert authority.store.revision > before_noop_revision
    assert len(authority.store.snapshot().cells) >= before_noop_count
    with pytest.raises(InvalidCell, match="idempotency key was reused"):
        revise_clean_browser_focus(
            authority,
            browser,
            issued.root_id,
            scope_root=scope_root,
            selected_roots=(
                composition_root(authority, "Interface", caller=caller),
                workshop_root,
            ),
            primary_root=workshop_root,
            caller=caller,
            command_id=first_command,
            expected_revision=authority.store.revision,
        )
    store.close()


def test_expired_or_future_browser_session_cannot_revise_focus(monkeypatch):
    authority = _focus_ready_authority()
    caller = _Caller(authority)
    browser = install_clean_browser_authority(
        authority,
        caller=caller,
        command_id=str(uuid.uuid4()),
    )
    workshop_root = composition_root(authority, "Workshop", caller=caller)
    scope_root = authority.manifest.application_root
    expired = issue_clean_browser_session(
        authority,
        browser,
        token="focus-expired-token",
        csrf_token="focus-expired-csrf",
        lifetime_seconds=0.001,
        caller=caller,
        command_id=str(uuid.uuid4()),
    )
    time.sleep(0.02)
    with pytest.raises(BrowserSessionDenied, match="expired"):
        verify_clean_browser_session(
            authority,
            browser,
            expired.root_id,
            token="focus-expired-token",
            csrf_token="focus-expired-csrf",
            require_csrf=True,
        )
    with pytest.raises(BrowserSessionDenied, match="expired"):
        revise_clean_browser_focus(
            authority,
            browser,
            expired.root_id,
            scope_root=scope_root,
            selected_roots=(workshop_root,),
            primary_root=workshop_root,
            caller=caller,
            command_id=str(uuid.uuid4()),
            expected_revision=authority.store.revision,
        )
    original_time = time.time
    future_start = original_time() + 600.0
    monkeypatch.setattr(time, "time", lambda: future_start)
    future = issue_clean_browser_session(
        authority,
        browser,
        token="focus-future-token",
        csrf_token="focus-future-csrf",
        lifetime_seconds=300.0,
        caller=caller,
        command_id=str(uuid.uuid4()),
    )
    monkeypatch.setattr(time, "time", original_time)
    with pytest.raises(BrowserSessionDenied, match="expired"):
        verify_clean_browser_session(
            authority,
            browser,
            future.root_id,
            token="focus-future-token",
            csrf_token="focus-future-csrf",
            require_csrf=True,
        )
    with pytest.raises(BrowserSessionDenied, match="expired"):
        revise_clean_browser_focus(
            authority,
            browser,
            future.root_id,
            scope_root=scope_root,
            selected_roots=(workshop_root,),
            primary_root=workshop_root,
            caller=caller,
            command_id=str(uuid.uuid4()),
            expected_revision=authority.store.revision,
        )


def test_project_unified_scope_denies_foreign_view_focus_projection():
    authority = _focus_ready_authority()
    caller = _Caller(authority)
    other = _second_caller(authority, caller, label="Foreign lens caller")
    browser = install_clean_browser_authority(
        authority,
        caller=caller,
        command_id=str(uuid.uuid4()),
    )
    issued = issue_clean_browser_session(
        authority,
        browser,
        token="foreign-view-token",
        csrf_token="foreign-view-csrf",
        lifetime_seconds=300.0,
        caller=caller,
        command_id=str(uuid.uuid4()),
    )
    workshop_root = composition_root(authority, "Workshop", caller=caller)
    scope_root = authority.manifest.application_root
    revise_clean_browser_focus(
        authority,
        browser,
        issued.root_id,
        scope_root=scope_root,
        selected_roots=(workshop_root,),
        primary_root=workshop_root,
        caller=caller,
        command_id=str(uuid.uuid4()),
        expected_revision=authority.store.revision,
    )
    with pytest.raises(InvalidCell, match="view"):
        project_unified_scope(
            authority,
            scope_root,
            caller=other,
            view_root=issued.view_root,
        )


def test_same_caller_browser_credentials_share_focus_and_different_callers_stay_isolated():
    authority = _focus_ready_authority()
    caller = _Caller(authority)
    other = _second_caller(authority, caller, label="Different caller isolation")
    browser = install_clean_browser_authority(
        authority,
        caller=caller,
        command_id=str(uuid.uuid4()),
    )
    scope_root = authority.manifest.application_root
    workshop_root = composition_root(authority, "Workshop", caller=caller)
    interface_root = composition_root(authority, "Interface", caller=caller)
    issued_a = issue_clean_browser_session(
        authority,
        browser,
        token="shared-focus-a",
        csrf_token="shared-focus-a-csrf",
        lifetime_seconds=300.0,
        caller=caller,
        command_id=str(uuid.uuid4()),
    )
    issued_b = issue_clean_browser_session(
        authority,
        browser,
        token="shared-focus-b",
        csrf_token="shared-focus-b-csrf",
        lifetime_seconds=300.0,
        caller=caller,
        command_id=str(uuid.uuid4()),
    )
    assert issued_a.view_root == issued_b.view_root == caller.session_root
    revise_clean_browser_focus(
        authority,
        browser,
        issued_a.root_id,
        scope_root=scope_root,
        selected_roots=(workshop_root,),
        primary_root=workshop_root,
        caller=caller,
        command_id=str(uuid.uuid4()),
        expected_revision=authority.store.revision,
    )
    shared = project_unified_scope(
        authority,
        scope_root,
        caller=caller,
        view_root=issued_b.view_root,
    )
    assert shared.selected_root == workshop_root
    assert shared.selected_roots == (workshop_root,)
    other_issued = issue_clean_browser_session(
        authority,
        browser,
        token="isolated-focus-c",
        csrf_token="isolated-focus-c-csrf",
        lifetime_seconds=300.0,
        caller=other,
        command_id=str(uuid.uuid4()),
    )
    isolated = project_unified_scope(
        authority,
        scope_root,
        caller=other,
        view_root=other_issued.view_root,
    )
    assert isolated.selected_root is None
    assert isolated.selected_roots == ()
    revise_clean_browser_focus(
        authority,
        browser,
        other_issued.root_id,
        scope_root=scope_root,
        selected_roots=(interface_root,),
        primary_root=interface_root,
        caller=other,
        command_id=str(uuid.uuid4()),
        expected_revision=authority.store.revision,
    )
    caller_projection = project_unified_scope(
        authority,
        scope_root,
        caller=caller,
        view_root=issued_a.view_root,
    )
    other_projection = project_unified_scope(
        authority,
        scope_root,
        caller=other,
        view_root=other_issued.view_root,
    )
    assert caller_projection.selected_root == workshop_root
    assert other_projection.selected_root == interface_root


def test_clean_browser_authority_has_no_parallel_server_store_or_token_ledger():
    source = (
        Path(__file__).resolve().parents[1]
        / "nodelang"
        / "clean_browser_authority.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "CellStore(",
        "sqlite3",
        "jsonl",
        "HTTPServer",
        "ThreadingHTTPServer",
        "session_token =",
        "csrf_token =",
        "bootstrap_token =",
        "clean_application_server",
        "clean_application_view",
    )
    assert all(term not in source for term in forbidden)


def test_installing_on_a_graph_with_enrolled_sessions_orphans_none_of_them():
    """Pre-existing enrolments survive the install untouched.

    The live graph enrolled its agent fleet before the browser authority
    existed, and the install ran against it with every enrolment standing.
    A freshly bootstrapped fixture cannot reach this case -- it has no
    pre-existing sessions to break -- which is exactly how an install that
    re-parented or re-keyed session state would pass every court and orphan
    a production fleet. Enrolments here are created BEFORE the install, and
    afterwards each must still sign an accepted command, not merely still
    appear in a listing: presence is plumbing, signing is water.
    """
    authority = _authority()
    caller = _Caller(authority)
    enrolled = [
        _second_caller(authority, caller, label="Pre-install agent %d" % index)
        for index in range(3)
    ]
    sessions_root = composition_root(
        authority, "Agent Sessions", caller=caller
    )
    before_members = {
        member.participant_id
        for member in relation_members(
            authority.store.snapshot(), sessions_root
        )
    }
    assert all(
        agent.session_root in before_members for agent in enrolled
    )

    installed = install_clean_browser_authority(
        authority,
        caller=caller,
        command_id=str(uuid.uuid4()),
    )

    after_members = {
        member.participant_id
        for member in relation_members(
            authority.store.snapshot(), sessions_root
        )
    }
    assert before_members.issubset(after_members), (
        "the install removed pre-existing agent sessions: %r"
        % sorted(before_members - after_members)
    )
    for agent in enrolled:
        issued = issue_clean_browser_session(
            authority,
            installed,
            token="survivor-%s" % agent.session_root,
            csrf_token="survivor-csrf-%s" % agent.session_root,
            lifetime_seconds=120.0,
            caller=agent,
            command_id=str(uuid.uuid4()),
        )
        assert issued.view_root == agent.session_root, (
            "a pre-existing session no longer binds as itself after the "
            "install"
        )
