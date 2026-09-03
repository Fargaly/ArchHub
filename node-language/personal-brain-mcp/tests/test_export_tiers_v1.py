"""AgDR-0054 slice 2a — export tier-filter (the legal/privacy dam at export).

Export-gating is the only reliable unlearning. Proves: quarantine never exports;
collective target takes only collective_ok; firm_private adds firm_private_only;
Tier-0 action_payload always exports; Tier-2 provider-prose is gated out unless
explicitly allowed; action-signal survives even when prose is dropped.
"""
from __future__ import annotations

from personal_brain.storage import BrainStore


def _ins(store, **kw):
    cols = {
        "id": kw["id"], "kind": "trace", "text": kw.get("text", "t"),
        "owner_user": "Fargaly", "provenance_json": "{}",
        "origin_kind": kw.get("origin_kind", "human_verified"),
        "training_rights_tier": kw.get("tier", "collective_ok"),
        "action_payload": kw.get("action", '{"op":"build_wall"}'),
        "language_payload": kw.get("lang"),
        "quarantine_flag": kw.get("quar", 0),
    }
    store._conn.execute(
        """INSERT INTO fragments(id,kind,text,owner_user,provenance_json,
            origin_kind,training_rights_tier,action_payload,language_payload,quarantine_flag)
           VALUES(:id,:kind,:text,:owner_user,:provenance_json,
            :origin_kind,:training_rights_tier,:action_payload,:language_payload,:quarantine_flag)""",
        cols,
    )
    store._conn.commit()


def _ids(rows):
    return {r["id"] for r in rows}


def test_collective_excludes_private_and_quarantine(tmp_path):
    s = BrainStore.open(tmp_path / "x.db")
    try:
        _ins(s, id="ok", tier="collective_ok")
        _ins(s, id="priv", tier="firm_private_only")
        _ins(s, id="never", tier="quarantine_never_trains")
        _ins(s, id="quar", tier="collective_ok", quar=1)
        got = _ids(s.export_trainable_fragments(target="collective"))
        assert got == {"ok"}, got  # only collective_ok, no private, no quarantined
    finally:
        s.close()


def test_firm_private_target_adds_private(tmp_path):
    s = BrainStore.open(tmp_path / "x.db")
    try:
        _ins(s, id="ok", tier="collective_ok")
        _ins(s, id="priv", tier="firm_private_only")
        _ins(s, id="never", tier="quarantine_never_trains")
        got = _ids(s.export_trainable_fragments(target="firm_private"))
        assert got == {"ok", "priv"}, got
    finally:
        s.close()


def test_provider_prose_gated_but_action_survives(tmp_path):
    s = BrainStore.open(tmp_path / "x.db")
    try:
        _ins(s, id="human", tier="collective_ok",
             origin_kind="human_verified", lang='{"note":"architect intent"}')
        _ins(s, id="model", tier="collective_ok",
             origin_kind="model_generated", lang='{"prose":"claude wrote this"}')
        rows = {r["id"]: r for r in s.export_trainable_fragments(target="collective")}
        # both export (Tier-0 action), but provider prose is dropped
        assert rows["human"]["language_payload"] is not None
        assert rows["model"]["language_payload"] is None
        assert rows["human"]["action_payload"] is not None
        assert rows["model"]["action_payload"] is not None  # action-signal survives
        # ...unless provider prose is explicitly allowed (founder ToS ruling)
        allowed = {r["id"]: r for r in
                   s.export_trainable_fragments(target="collective", allow_provider_prose=True)}
        assert allowed["model"]["language_payload"] is not None
    finally:
        s.close()
