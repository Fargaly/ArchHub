"""Slice 7 — bipartite ACL + redaction tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from personal_brain.acl import (
    AccessDecision,
    Identity,
    can_promote,
    can_read,
    can_write_to_scope,
    filter_for_reader,
)
from personal_brain.models import Scope, Visibility
from personal_brain.redaction import (
    HeuristicRedactor,
    redact_fragment,
)


# ─────────────────────── ACL — read ────────────────────────────────────


def _frag(scope, owner="founder", project=None, firm=None,
           visibility="private", **kw):
    return {
        "id": "f-1", "kind": "fact", "text": "x",
        "scope": scope, "visibility": visibility,
        "owner_user": owner, "project_id": project, "firm_id": firm,
        **kw,
    }


def test_user_scope_owner_reads_own():
    f = _frag(Scope.USER.value, owner="founder")
    me = Identity(user_id="founder")
    assert can_read(f, reader=me).allow


def test_user_scope_other_user_blocked():
    f = _frag(Scope.USER.value, owner="founder")
    other = Identity(user_id="teammate")
    d = can_read(f, reader=other)
    assert not d.allow
    assert "user-scoped" in d.reason


def test_project_scope_member_reads():
    f = _frag(Scope.PROJECT.value, owner="founder", project="tower-a")
    member = Identity(user_id="other", project_id="tower-a")
    assert can_read(f, reader=member).allow


def test_project_scope_non_member_blocked():
    f = _frag(Scope.PROJECT.value, owner="founder", project="tower-a")
    outsider = Identity(user_id="other", project_id="other-project")
    assert not can_read(f, reader=outsider).allow


def test_project_owner_always_reads():
    f = _frag(Scope.PROJECT.value, owner="founder", project="tower-a")
    owner = Identity(user_id="founder", project_id=None)
    assert can_read(f, reader=owner).allow


def test_firm_scope_seat_reads():
    f = _frag(Scope.FIRM.value, owner="founder", firm="archhub-inc")
    seat = Identity(user_id="t", firm_id="archhub-inc")
    assert can_read(f, reader=seat).allow


def test_firm_scope_other_firm_blocked():
    f = _frag(Scope.FIRM.value, owner="founder", firm="archhub-inc")
    other_firm = Identity(user_id="t", firm_id="competitor-ltd")
    assert not can_read(f, reader=other_firm).allow


def test_global_scope_open_to_all():
    f = _frag(Scope.GLOBAL.value, owner="archive")
    anyone = Identity(user_id="anyone")
    assert can_read(f, reader=anyone).allow


def test_community_requires_subscription():
    f = _frag(Scope.COMMUNITY.value, owner="archive",
              community_id="aec-firms")
    unsub = Identity(user_id="x")
    sub = Identity(user_id="y", community_subscriptions=["aec-firms"])
    assert not can_read(f, reader=unsub).allow
    assert can_read(f, reader=sub).allow


def test_expired_fragment_denied():
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    f = _frag(Scope.USER.value, owner="founder", valid_until=yesterday)
    me = Identity(user_id="founder")
    d = can_read(f, reader=me)
    assert not d.allow
    assert "expired" in d.reason


def test_filter_for_reader_drops_denied():
    f1 = _frag(Scope.USER.value, owner="founder")
    f2 = _frag(Scope.USER.value, owner="teammate")
    f2["id"] = "f-2"
    me = Identity(user_id="founder")
    visible = filter_for_reader([f1, f2], reader=me)
    ids = {f["id"] for f in visible}
    assert ids == {"f-1"}


# ─────────────────────── ACL — write ───────────────────────────────────


def test_write_user_scope_always_allowed():
    actor = Identity(user_id="anyone")
    assert can_write_to_scope(actor=actor, target_scope=Scope.USER).allow


def test_write_firm_requires_firm_membership():
    actor = Identity(user_id="x", firm_id="archhub-inc")
    d = can_write_to_scope(actor=actor, target_scope=Scope.FIRM,
                            target_firm_id="archhub-inc")
    assert d.allow
    d2 = can_write_to_scope(actor=actor, target_scope=Scope.FIRM,
                             target_firm_id="competitor")
    assert not d2.allow


def test_write_community_requires_subscription_and_redaction():
    actor = Identity(user_id="x", community_subscriptions=["aec"])
    d = can_write_to_scope(actor=actor, target_scope=Scope.COMMUNITY,
                            target_community_id="aec")
    assert d.allow
    assert d.redaction_required


def test_write_global_maintainers_only():
    actor = Identity(user_id="x", is_maintainer=False)
    d = can_write_to_scope(actor=actor, target_scope=Scope.GLOBAL)
    assert not d.allow

    maint = Identity(user_id="m", is_maintainer=True)
    d2 = can_write_to_scope(actor=maint, target_scope=Scope.GLOBAL)
    assert d2.allow


# ─────────────────────── promotion ─────────────────────────────────────


def test_promote_user_to_firm_by_owner_member():
    f = _frag(Scope.USER.value, owner="founder")
    actor = Identity(user_id="founder", firm_id="archhub-inc")
    d = can_promote(f, actor=actor, target_scope=Scope.FIRM,
                     target_firm_id="archhub-inc")
    assert d.allow


def test_promote_user_to_firm_blocked_when_not_owner():
    f = _frag(Scope.USER.value, owner="founder")
    actor = Identity(user_id="teammate", firm_id="archhub-inc")
    d = can_promote(f, actor=actor, target_scope=Scope.FIRM,
                     target_firm_id="archhub-inc")
    assert not d.allow
    assert "owner" in d.reason


def test_promote_firm_to_community_requires_redaction():
    f = _frag(Scope.FIRM.value, owner="founder", firm="archhub-inc")
    actor = Identity(user_id="founder", firm_id="archhub-inc",
                     community_subscriptions=["aec"])
    d = can_promote(f, actor=actor, target_scope=Scope.COMMUNITY,
                     target_community_id="aec")
    assert d.allow
    assert d.redaction_required


# ─────────────────────── redaction ─────────────────────────────────────


def test_redact_strips_email():
    r = HeuristicRedactor()
    out, findings = r.redact("Contact founder@archhub.io for details")
    assert "<email>" in out
    assert "founder@archhub.io" not in out
    assert any("email" in f for f in findings)


def test_redact_strips_secret_keys():
    r = HeuristicRedactor()
    out, _ = r.redact("API key sk-1234567890abcdef1234 fails")
    assert "<secret-key>" in out
    assert "sk-1234567890" not in out


def test_redact_strips_aws_keys():
    r = HeuristicRedactor()
    out, _ = r.redact("AKIA1234567890ABCDEF accessed s3")
    assert "<aws-key>" in out


def test_redact_strips_money_amounts():
    r = HeuristicRedactor()
    out, _ = r.redact("Revenue was USD 1,500,000 Q3")
    assert "<amount>" in out


def test_redact_strips_known_entity():
    r = HeuristicRedactor(known_entities=["Tower-A", "ClientX"])
    out, findings = r.redact("Tower-A was billed to ClientX last week")
    assert "Tower-A" not in out
    assert "ClientX" not in out
    assert "<entity>" in out


def test_redact_preserves_common_technical_nouns():
    r = HeuristicRedactor()
    out, _ = r.redact("The User invoked the Project Memory")
    # These are common technical nouns — must NOT redact them
    assert "User" in out or "<name>" not in out
    # Capitalised but technical → kept (this is a heuristic; documented
    # in COMMON_TECHNICAL_NOUNS list)


def test_redact_fragment_attaches_policy_id():
    frag = {
        "id": "f-1", "text": "Contact john.smith@example.com for invoice",
        "subject": "Smith", "object": "$200 owed",
        "provenance": {
            "contributing_agent": "claude",
            "contributing_user": "founder",
            "created_at": "2026-05-25",
        },
    }
    redacted, report = redact_fragment(frag)
    assert redacted["text"] != frag["text"]
    assert "<email>" in redacted["text"]
    assert "<amount>" in redacted["object"]
    # Provenance: contributing_user hashed, policy_id recorded
    prov = redacted["provenance"]
    assert "contributing_user" not in prov
    assert "contributing_user_hash" in prov
    assert prov["redaction_policy_id"] == report.policy_id
    assert report.findings


def test_redact_fragment_idempotent_on_already_clean():
    frag = {
        "id": "f-1", "text": "no PII here",
        "provenance": {"contributing_agent": "x", "contributing_user": "founder"},
    }
    redacted, report = redact_fragment(frag)
    # text unchanged (no patterns matched); but provenance still rewritten
    assert redacted["text"] == "no PII here"
    assert "contributing_user_hash" in redacted["provenance"]
