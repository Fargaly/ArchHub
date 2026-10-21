"""The founder review of the Community Brain (ADGR-0004).

Every community version a member contributes is recorded pending, with the
AUTHENTICATED pusher as its contributor. Members never read a version the
review has not admitted: every read of the merged replica passes through
``hold_unreviewed``. A reader always sees the versions the cloud recorded THEM
pushing (never a row's owner_user, which the wire can carry), and a withdrawal
passes only when it carries no text and has already expired. The founder
Cockpit lists and judges through /founder/api/community.
"""
from __future__ import annotations

from datetime import datetime, timezone

import db


def community_id_of(fragment) -> str:
    extra = fragment.get("extra") if isinstance(fragment.get("extra"), dict) else {}
    return str(extra.get("community_id") or "")


def _expired(stamp) -> bool:
    if not isinstance(stamp, str) or not stamp.strip():
        return False
    try:
        moment = datetime.fromisoformat(stamp.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment <= datetime.now(timezone.utc)


def is_withdrawal(fragment) -> bool:
    """A row that blanks a version: no text AND already expired. Nothing else."""
    return not str(fragment.get("text") or "").strip() and _expired(fragment.get("valid_until"))


def submit_versions(user_id, delta, merge_result, community_keys) -> None:
    rejected = {str(item.get("id")) for item in (merge_result.get("rejected") or [])
                if isinstance(item, dict)}
    members_of = set(community_keys)
    for fragment in (delta or {}).get("fragments") or []:
        if not isinstance(fragment, dict) or (fragment.get("scope") or "").lower() != "community":
            continue
        cid, fid = community_id_of(fragment), str(fragment.get("id") or "")
        if not cid or cid not in members_of or not fid or fid in rejected or is_withdrawal(fragment):
            continue
        db.submit_community_version(cid, fid, str(fragment.get("hlc") or ""),
                                    contributor=user_id, text=str(fragment.get("text") or ""))


def hold_unreviewed(user_id, merged):
    if not isinstance(merged, dict) or not isinstance(merged.get("fragments"), list):
        return merged
    visible: dict = {}
    kept = []
    for row in merged["fragments"]:
        if (not isinstance(row, dict) or (row.get("scope") or "").lower() != "community"
                or is_withdrawal(row)):
            kept.append(row)
            continue
        cid = community_id_of(row)
        if cid not in visible:
            visible[cid] = (db.admitted_community_versions(cid)
                            | db.contributed_community_versions(cid, user_id))
        if (str(row.get("id") or ""), str(row.get("hlc") or "")) in visible[cid]:
            kept.append(row)
    return dict(merged, fragments=kept)