"""Community owner: one plain file, settings/community.json.

Knowledge networks keep the rules of cell_brain_community.py (9afdeaa4^): hearing
a peer needs a subscription, anything a peer sends lands QUARANTINED with its
provenance, a judgement is final, a rejection is kept so the same claim is
answered from the record, and a claim that reads like a credential is refused.
Groups, invitations, the marketplace search, the listing draft and the project
charge draft are the Community screen's own records (community-tools.jsx).
Validation is recovered from domains/community.py (9afdeaa4^): non-empty
identifiers and no raw secret in any field.

Anything that would leave this PC (sending an invitation, joining with a code,
installing or publishing a marketplace pack, collecting a charge) has no owner
yet and answers a visible "Not restored yet" notice. Nothing is invented.
"""
import copy
import hashlib
import json
import re
import threading
import uuid

from .runtime_credentials import assert_not_a_secret
from .social_surface import open_item

_LOCK = threading.RLock()
QUARANTINED, ADMITTED, REJECTED = "quarantined", "admitted", "rejected"
_STATUS = {QUARANTINED: "Quarantine", ADMITTED: "Accepted", REJECTED: "Rejected"}
_EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,63}")
_SECRET_WORDS = ("password", "passwd", "secret", "credential", "api_key", "apikey",
                 "access_token", "refresh_token", "private_key", "signing_key", "token")


def _identifier(value, label):
    clean = str(value).strip() if type(value) is str else ""
    if not clean or len(clean) > 200:
        raise ValueError("%s must be a non-empty name of at most 200 characters" % label)
    return clean


def _reject_raw_secrets(value, path="input"):
    if isinstance(value, dict):
        for raw_name, item in value.items():
            name = str(raw_name).casefold().replace("-", "_")
            if any(word in name for word in _SECRET_WORDS):
                raise ValueError("%s.%s may contain a raw secret; keep secrets in the Credential Manager" % (path, raw_name))
            _reject_raw_secrets(item, "%s.%s" % (path, raw_name))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_raw_secrets(item, "%s[%d]" % (path, index))
    elif type(value) is str and value:
        assert_not_a_secret(value, path)


def empty_state():
    return {"peers": [], "incoming": [], "groups": [], "joinStatus": "", "marketQuery": "",
            "listing": {"title": "", "price": 0, "creatorShare": 0},
            "charge": {"client": "", "project": "", "basis": "", "amount": 0}, "charges": []}


# Studio command -> its submitted inputs, in argument order (api.js restCommand).
COMMANDS = {
    "createCommunityGroup": ("name",), "issueCommunityInvite": ("group", "email"),
    "revokeCommunityInvite": ("group", "invite"), "verifyCommunityInvite": (), "joinCommunityGroup": (),
    "setMarketplace": ("values",), "installMarketplaceItem": ("item",), "proposeMarketplaceListing": (),
    "setProjectCharge": ("values",), "proposeProjectCharge": (),
}
_OBJECT_INPUTS = {"values"}


def bindings():
    """The owner's commands as canvas interaction bindings (the System graph exposes them)."""
    return [{"control": name, "interaction": "owner:community:" + name, "event": "activate",
             "event_facts": [{"source": "submitted", "input": key} for key in inputs]}
            for name, inputs in COMMANDS.items()]


class CommunityOwner:
    PUBLIC = ("community_state", "subscribe_community", "review_community_pattern")

    def __init__(self, store=None):
        if store is None:
            from .nograph_server import JsonFile
            from .session_files import profile_directory
            store = JsonFile(profile_directory() / "settings" / "community.json", {})
        self.store = store

    # -- file ---------------------------------------------------------------
    def _read(self):
        held = self.store.read() or {}
        state = empty_state()
        state.update({key: held[key] for key in state if key in held})
        return state

    def _save(self, state):
        encoded = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode()) > 65536:
            raise ValueError("Community records exceed 64 KiB. Remove old invitations or charges first.")
        self.store.write(json.loads(encoded))

    def view(self, state=None):
        state = self._read() if state is None else state
        subscribed = {p["id"] for p in state["peers"] if p.get("subscribed")}
        return {"peers": [{"id": p["id"], "name": p["name"], "subscribed": p["id"] in subscribed}
                          for p in sorted(state["peers"], key=lambda p: p["id"])],
                "patterns": [{"id": r["id"], "title": r["claim"][:80], "description": r["claim"],
                              "source": r["peer"], "status": _STATUS[r["verdict"]]}
                             for r in sorted(state["incoming"], key=lambda r: (r["peer"], r["claim"]))],
                "groups": copy.deepcopy(state["groups"]), "joinStatus": state["joinStatus"],
                "marketQuery": state["marketQuery"], "listing": dict(state["listing"]),
                "charge": dict(state["charge"]), "charges": copy.deepcopy(state["charges"]),
                "marketplace": []}

    # -- canvas-op reads and edits (api.js communityOperation) ---------------
    def dispatch(self, operation, args):
        if operation not in self.PUBLIC or type(args) is not list:
            raise ValueError("Choose a registered Community operation.")
        return getattr(self, operation)(*args)

    def community_state(self):
        return self.view()

    def join(self, community_id):
        """Hear from a community: its peer, subscribed once (brain_community_sync.join)."""
        name = _identifier(community_id, "community id")
        with _LOCK:
            state = self._read()
            root = "community:" + name
            peer = next((p for p in state["peers"] if p["id"] == root), None)
            if peer is None:
                state["peers"].append({"id": root, "name": name, "subscribed": True})
            else:
                peer["subscribed"] = True
            self._save(state)
            return root

    def subscribe_community(self, identity):
        """Toggle hearing from an existing peer. Hearing is not believing."""
        with _LOCK:
            state = self._read()
            peer = next((p for p in state["peers"] if p["id"] == identity), None)
            if peer is None:
                raise ValueError("Choose an existing community peer, then retry.")
            peer["subscribed"] = not peer.get("subscribed")
            self._save(state)
            return self.view(state)

    def receive(self, peer, claim):
        """Take something in. It arrives quarantined and is never applied on arrival."""
        claim = claim.strip() if type(claim) is str else ""
        if not claim:
            raise ValueError("an empty claim is not a claim")
        assert_not_a_secret(claim, "incoming claim")
        with _LOCK:
            state = self._read()
            if not any(p["id"] == peer and p.get("subscribed") for p in state["peers"]):
                raise ValueError("nothing is accepted from a peer we did not subscribe to")
            root = "incoming:%s:%s" % (peer, hashlib.sha256(claim.encode("utf-8")).hexdigest()[:24])
            if any(r["id"] == root for r in state["incoming"]):
                raise ValueError("this claim from this peer was already received")
            state["incoming"].append({"id": root, "peer": peer, "claim": claim, "verdict": QUARANTINED})
            self._save(state)
            return root

    def review_community_pattern(self, identity, decision):
        with _LOCK:
            state = self._read()
            row = next((r for r in state["incoming"] if r["id"] == identity), None)
            if row is None or decision not in ("Accept", "Quarantine", "Reject", "Recheck"):
                raise ValueError("Choose an existing pattern and a listed review decision.")
            if decision == "Recheck":
                raise ValueError("Request a fresh evidence check from this pattern in Workshop before judging again.")
            if row["verdict"] != QUARANTINED:
                raise ValueError("This pattern already has a final judgement. Review a fresh incoming claim.")
            if decision in ("Accept", "Reject"):
                row["verdict"] = ADMITTED if decision == "Accept" else REJECTED
                self._save(state)
            return self.view(state)

    # -- Studio commands (community-tools.jsx through restCommand) ----------
    def command(self, control, facts):
        inputs = COMMANDS.get(control)
        if inputs is None:
            raise ValueError("Choose a Community command.")
        if type(facts) is not list or [f.get("input") if type(f) is dict else None for f in facts] != list(inputs):
            raise ValueError("The Community command inputs changed. Refresh and retry.")
        args = []
        for fact in facts:
            value = fact.get("value")
            if type(value) is not str:
                raise ValueError("Community command values must be submitted text.")
            if fact["input"] in _OBJECT_INPUTS:
                try:
                    value = json.loads(value)
                except ValueError as error:
                    raise ValueError("Community values must be an object.") from error
            args.append(value)
        with _LOCK:
            result = getattr(self, control)(*args)
            return {"result": result, "community": self.view()}

    def _group(self, state, identity):
        group = next((g for g in state["groups"] if g["id"] == identity), None)
        if group is None:
            raise ValueError("This group is no longer here. Refresh Community.")
        return group

    def createCommunityGroup(self, name):
        name = _identifier(name, "Group name")
        _reject_raw_secrets(name, "group name")
        state = self._read()
        if any(g["name"].casefold() == name.casefold() for g in state["groups"]):
            raise ValueError("A group with this name already exists.")
        group = {"id": "group:" + uuid.uuid4().hex, "name": name, "owner": "You", "status": "Active on this PC",
                 "members": ["You"], "invites": []}
        state["groups"].append(group)
        self._save(state)
        return group

    def issueCommunityInvite(self, group, email):
        email = email.strip() if type(email) is str else ""
        if not _EMAIL.fullmatch(email):
            raise ValueError("Enter your colleague's email address.")
        state = self._read()
        row = self._group(state, group)
        if any(r["email"].casefold() == email.casefold() and r["status"] != "Revoked" for r in row["invites"]):
            raise ValueError("This colleague already has an open invitation.")
        invite = {"id": "invite:" + uuid.uuid4().hex, "email": email,
                  "status": "Saved on this PC · not sent (invitation delivery is not restored yet)"}
        row["invites"].append(invite)
        self._save(state)
        return invite

    def revokeCommunityInvite(self, group, invite):
        state = self._read()
        row = next((r for r in self._group(state, group)["invites"] if r["id"] == invite), None)
        if row is None:
            raise ValueError("This invitation is no longer here. Refresh Community.")
        row["status"] = "Revoked"
        self._save(state)
        return row

    def setMarketplace(self, values):
        if type(values) is not dict or not values or set(values) - {"marketQuery", "listing"}:
            raise ValueError("Choose a marketplace search or listing field.")
        state = self._read()
        if "marketQuery" in values:
            if type(values["marketQuery"]) is not str or len(values["marketQuery"]) > 200:
                raise ValueError("Search with at most 200 characters.")
            state["marketQuery"] = values["marketQuery"]
        if "listing" in values:
            listing = values["listing"]
            if (type(listing) is not dict or set(listing) != {"title", "price", "creatorShare"}
                    or type(listing["title"]) is not str or len(listing["title"]) > 200
                    or type(listing["price"]) not in (int, float) or not 0 <= listing["price"] <= 100000
                    or type(listing["creatorShare"]) not in (int, float) or not 0 <= listing["creatorShare"] <= 100):
                raise ValueError("A listing needs a title, a price from 0 and a creator share from 0 to 100.")
            _reject_raw_secrets(listing, "listing")
            state["listing"] = listing
        self._save(state)
        return {"marketQuery": state["marketQuery"], "listing": state["listing"]}

    def setProjectCharge(self, values):
        if type(values) is not dict or not values or set(values) - {"client", "project", "basis", "amount"}:
            raise ValueError("Choose a charge field.")
        for key, value in values.items():
            if key == "amount":
                if type(value) not in (int, float) or not 0 <= value <= 10000000:
                    raise ValueError("Enter an amount from 0.")
            elif key == "basis":
                if value not in ("Per project", "Per workflow run"):
                    raise ValueError("Choose a listed charge basis.")
            elif type(value) is not str or len(value) > 200:
                raise ValueError("Enter %s within 200 characters." % key)
        _reject_raw_secrets(values, "charge")
        state = self._read()
        state["charge"].update(values)
        self._save(state)
        return state["charge"]

    @staticmethod
    def verifyCommunityInvite():
        raise ValueError(open_item("verifying a community invitation",
                                   "Joining needs the ArchHub cloud join code and your signed-in account."))

    @staticmethod
    def joinCommunityGroup():
        raise ValueError(open_item("joining a community group",
                                   "Joining needs the ArchHub cloud join code and your signed-in account."))

    @staticmethod
    def installMarketplaceItem(item):
        raise ValueError(open_item("installing from the marketplace",
                                   "Signed pack download and verification have no owner in this release."))

    @staticmethod
    def proposeMarketplaceListing():
        raise ValueError(open_item("publishing a marketplace listing",
                                   "Publishing needs a signed pack, the Approve card and your ArchHub account."))

    @staticmethod
    def proposeProjectCharge():
        raise ValueError(open_item("collecting a project charge",
                                   "Collection needs a payment provider on your account; nothing was charged."))
