"""Social media owner: one plain file, settings/social.json.

Office page, drafts, inbox, rules, digest, source reads, slides, prototype and
meeting state, plus the post approvals. Recovered from
social_research_community_backend.py (57c43f54^, Studio social and presentation
properties) with its validation and error text; only the store changed, from a
graph property to this file. The physical post boundary is SocialHttpHost,
recovered from social_http_host.py (9afdeaa4^).

No account, inbox, extraction, provider execution or verification is invented.
A post leaves only when the user approves its exact request on the one Approve
card (hook_decision.decide -> SocialSurface.apply).
"""
import copy
import hashlib
import http.client
import inspect
import json
import logging
import math
import ssl
import threading
import time
import uuid
from html.parser import HTMLParser
from urllib.parse import urlsplit

from .social_connectors import (
    MAX_RESPONSE_BYTES, PROVIDER_ORIGINS, Refusal, WORK_OPERATIONS,
    normalize_work_answer, refusal_answer, social_material_from_values, verify_prepared,
)

_LOCK = threading.RLock()
_LOG = logging.getLogger(__name__)
# Social media node: its typed parameters.
SOCIAL_NODE = {"id": "social.media", "params": {"state_limit_bytes": 65536, "closed_posts_limit": 50}}
# Draft account -> (social_connections network, Work operation, text argument).
POST_ROUTES = {"LinkedIn": ("linkedin", "linkedin.post", "text"),
               "Facebook": ("facebook", "facebook.page_post", "message"),
               "X": ("x", "x.post", "text")}


def open_item(what, why=""):
    """The visible notice for behaviour that has no owner yet (NODE-SPEC 1.7)."""
    return ("Not restored yet: %s. %s" % (what, why)).strip()


def empty_state():
    return {
        "social": {"office": dict.fromkeys(("name", "headline", "bio", "website", "audience"), ""),
                   "inbox": [], "drafts": [], "groups": [], "research": [], "tutorials": [],
                   "triaged": False, "digest": {"enabled": False, "time": "", "summary": ""}},
        "presentation": {"slides": [], "walkthrough": 0},
        "prototype": {"name": "", "samples": 0, "baseline": 0,
                      "status": "", "linkedModel": False, "pattern": None, "measurements": "", "features": []},
        "meeting": {"title": "", "calendarId": "", "platform": "", "agent": "", "status": "",
                    "consent": False, "transcript": [], "participants": [], "actions": [],
                    "actionOwners": {}, "actionTasks": {}},
        "meetingCalendar": [],
    }


class _PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


class SocialSurface:
    """The social owner over one JSON file: {"state": <Studio state>, "posts": [approval cards]}."""

    PUBLIC = ("get_state", "update_office_page", "save_social_draft", "discard_social_draft",
              "read_social_message", "triage_social_inbox", "reply_social_message",
              "set_social_group_rule", "set_social_digest", "generate_social_digest",
              "read_content_source", "add_slide", "edit_slide", "remove_slide", "reorder_slide",
              "set_prototype", "rebaseline_prototype", "check_verdict_pattern", "set_meeting",
              "set_meeting_action_owner", "bind_meeting_task", "import_meeting_calendar", "import_meeting_transcript", "set_source_read_seconds",
              "check_research_license", "save_research_decision", "bind_research_work")

    def __init__(self, store=None, *, task_exists=None, connection=None):
        if store is None:
            from .nograph_server import JsonFile
            from .session_files import profile_directory
            store = JsonFile(profile_directory() / "settings" / "social.json", {"state": {}})
        self.store = store
        self.lock = _LOCK
        self.guard = None
        self.task_exists = task_exists
        self.connection = connection

    def dispatch(self, operation, args):
        if type(operation) is not str or operation not in self.PUBLIC or type(args) is not list:
            raise ValueError("Choose a registered social operation.")
        function = getattr(self, operation)
        try:
            inspect.signature(function).bind(*args)
        except TypeError as error:
            raise ValueError("The action arguments changed. Refresh this screen.") from error
        with self.lock:
            result = function(*args)
            return {"result": result, "state": self.get_state()}

    def get_state(self):
        held = self.store.read().get("state") or {}
        state = empty_state()
        for key in state:
            if key in held:
                state[key] = {**state[key], **held[key]} if type(state[key]) is dict else held[key]
        return state

    def get_social_snapshot(self):
        return self.get_state()["social"]

    def _save(self, state, result):
        encoded = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode()) > SOCIAL_NODE["params"]["state_limit_bytes"]:
            raise ValueError("Your social content exceeds 64 KiB. Archive content before saving.")
        with self.lock:
            self.store.update({"state": json.loads(encoded)})
        return copy.deepcopy(result)

    @staticmethod
    def _values(values, allowed):
        if type(values) is not dict or not values or set(values) - set(allowed):
            raise ValueError("These fields cannot be changed by this action. Refresh and retry.")
        if any(type(v) is not str or len(v) > 16000 for v in values.values()):
            raise ValueError("Enter text within the 16000 character limit.")
        return values

    @staticmethod
    def _row(rows, identity):
        matches = [row for row in rows if row["id"] == identity]
        if len(matches) != 1:
            raise ValueError("That item is no longer in this graph. Refresh and choose it again.")
        return matches[0]

    def update_office_page(self, values):
        self._values(values, empty_state()["social"]["office"])
        state = self.get_state()
        state["social"]["office"].update(values)
        return self._save(state, state["social"]["office"])

    def save_social_draft(self, values):
        self._values(values, ("id", "platform", "kind", "title", "text", "schedule", "status", "messageId"))
        state = self.get_state()
        rows = state["social"]["drafts"]
        if not values.get("text", "").strip():
            raise ValueError("Write the post before saving it.")
        if values.get("platform") not in ("LinkedIn", "Instagram", "Facebook", "WhatsApp Business", "X", "TikTok", "YouTube"):
            raise ValueError("Choose a supported account.")
        if values.get("schedule"):
            from datetime import datetime
            try:
                datetime.fromisoformat(values["schedule"])
            except ValueError as error:
                raise ValueError("Choose a valid post date and time.") from error
        row = self._row(rows, values["id"]) if values.get("id") else {"id": uuid.uuid4().hex}
        if not values.get("id"):
            rows.append(row)
        row.update({key: value for key, value in values.items() if key not in {"status", "id"}})
        row["status"] = "Draft"
        return self._save(state, row)

    def discard_social_draft(self, identity):
        state = self.get_state()
        row = self._row(state["social"]["drafts"], identity)
        row["status"] = "Archived"
        return self._save(state, row)

    def read_social_message(self, identity):
        state = self.get_state()
        row = self._row(state["social"]["inbox"], identity)
        row["unread"] = False
        return self._save(state, row)

    def triage_social_inbox(self):
        state = self.get_state()
        rows = state["social"]["inbox"]
        # Triage is deterministic unread-first ordering, not an invented AI classification.
        rows.sort(key=lambda row: not row.get("unread", False))
        state["social"]["triaged"] = True
        return self._save(state, {"conversations": len(rows), "order": "Unread first"})

    def reply_social_message(self, identity, text):
        row = self._row(self.get_state()["social"]["inbox"], identity)
        return self.save_social_draft({"platform": row["platform"], "kind": "reply",
                                       "title": "", "text": text, "messageId": identity, "schedule": ""})

    def set_social_group_rule(self, identity, values):
        if type(values) is not dict or not values or set(values) - {"rule", "replyStyle", "autoSend", "digest"}:
            raise ValueError("Choose a group rule field.")
        for key, value in values.items():
            if key in {"autoSend", "digest"}:
                if type(value) is not bool:
                    raise ValueError("Choose on or off for this rule.")
            elif type(value) is not str:
                raise ValueError("Enter rule text.")
        if "replyStyle" in values and values["replyStyle"] not in {"Concise", "Warm", "Formal"}:
            raise ValueError("Choose a listed reply style.")
        state = self.get_state()
        row = self._row(state["social"]["groups"], identity)
        row.update(values)
        return self._save(state, row)

    def set_social_digest(self, values):
        if type(values) is not dict or not values or set(values) - {"enabled", "time"}:
            raise ValueError("Choose a digest setting.")
        if "enabled" in values and type(values["enabled"]) is not bool:
            raise ValueError("Choose on or off for the digest.")
        if "time" in values:
            from datetime import time
            try:
                time.fromisoformat(values["time"])
            except (ValueError, TypeError) as error:
                raise ValueError("Choose a valid digest time.") from error
        state = self.get_state()
        state["social"]["digest"].update(values)
        return self._save(state, state["social"]["digest"])

    def generate_social_digest(self):
        state = self.get_state()
        rows = state["social"]["inbox"]
        summary = "\n".join("%s · %s: %s" % (r["platform"], r["from"], r["text"]) for r in rows)
        state["social"]["digest"]["summary"] = summary or "No conversations in this graph."
        return self._save(state, state["social"]["digest"])

    def read_content_source(self, kind, source):
        """Read bounded public text, never claim video, mail or file extraction from a URL."""
        import http.client
        import ipaddress
        import socket
        if type(source) is not str or len(source) > 4096 or kind not in {"Web", "Video", "Mail", "File"}:
            raise ValueError("Choose a source kind and a valid HTTPS source URL.")
        parts = urlsplit(source)
        if kind in {"File", "Mail", "Video"}:
            from pathlib import Path
            from .pipeline_engines import _local_input_path
            path = Path(_local_input_path(source, label="source text or transcript file"))
            allowed = {"File": {".txt", ".md", ".csv", ".html"}, "Mail": {".eml"},
                       "Video": {".vtt", ".srt", ".txt"}}
            if path.suffix.lower() not in allowed[kind] or path.stat().st_size > 32768:
                raise ValueError("Choose a local %s text source within 32 KiB; use the source node for larger or binary media." % kind.lower())
            raw = path.read_bytes()
            text = raw.decode("utf-8-sig")
            if kind == "Mail":
                from email import policy
                from email.parser import BytesParser
                message = BytesParser(policy=policy.default).parsebytes(raw)
                part = message.get_body(preferencelist=("plain",))
                text = part.get_content() if part else ""
            if kind == "File" and path.suffix.lower() == ".html":
                parser = _PageText()
                parser.feed(text)
                text = "\n".join(parser.parts)
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if not lines:
                raise ValueError("This source contains no readable text. Choose another source.")
            row = {"id": uuid.uuid4().hex, "title": path.name, "source": str(path), "status": "Source read",
                   "sha256": hashlib.sha256(raw).hexdigest(), "summary": lines[0],
                   "transcript": lines, "keyFrames": []}
            return self._record_source(row)
        seconds = self.get_state()["social"].get("sourceReadSeconds")
        if type(seconds) not in (int, float) or not 1 <= seconds <= 60:
            raise ValueError("Choose the source read timeout in seconds, then read the source.")
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.port not in (None, 443):
            raise ValueError("Use a public HTTPS source without credentials or a custom port.")
        try:
            addresses = socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(r[4][0]).is_global for r in addresses):
                raise ValueError("Use a public source; local and private network addresses are refused.")
            # Pin the validated address; a second DNS answer cannot redirect to a private host.
            address = addresses[0][4][0]
            connection = http.client.HTTPSConnection(parts.hostname, timeout=seconds)
            connection._create_connection = lambda address_unused, timeout, source_address=None: socket.create_connection((address, 443), timeout)
            try:
                connection.request("GET", (parts.path or "/") + ("?" + parts.query if parts.query else ""),
                                   headers={"Accept": "text/plain,text/html", "Accept-Encoding": "identity"})
                response = connection.getresponse()
                if response.status != 200:
                    raise ValueError("Source returned HTTP %s. Open a direct readable source URL." % response.status)
                content_type = response.getheader("Content-Type", "")
                if not content_type.startswith(("text/plain", "text/html")):
                    raise ValueError("Choose a plain text or HTML source; this response needs its source reader node.")
                raw = response.read(32769)
                if len(raw) > 32768:
                    raise ValueError("Source exceeds 32 KiB. Use its source reader node for the full document.")
                text = raw.decode(response.headers.get_content_charset() or "utf-8")
            finally:
                connection.close()
        except (OSError, UnicodeError, http.client.HTTPException) as error:
            raise ValueError("Cannot read this source. Check the URL and connection, then retry.") from error
        if content_type.startswith("text/html"):
            parser = _PageText()
            parser.feed(text)
            lines = parser.parts
        else:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            raise ValueError("The source contains no readable text. Choose another source.")
        row = {"id": uuid.uuid4().hex, "title": source, "source": source, "status": "Page read",
               "sha256": hashlib.sha256(raw).hexdigest(), "summary": lines[0],
               "transcript": lines, "keyFrames": []}
        return self._record_source(row)

    def _record_source(self, row):
        with self.lock:
            if self.guard is not None:
                self.guard()
            state = self.get_state()
            state["social"]["research"].append(row)
            return self._save(state, row)

    def check_research_license(self, identity):
        import re
        state = self.get_state()
        row = self._row(state['social']['research'], identity)
        text = '\n'.join(row['transcript'])
        matches = re.findall(r'(?im)^.*(?:SPDX-License-Identifier:|MIT License|Apache License|GNU (?:GENERAL|AFFERO) PUBLIC LICENSE).*$', text)
        row['licenseEvidence'] = matches[:8]
        row['licenseStatus'] = '\n'.join(matches[:8]) if matches else 'No license declaration in the captured source. Read its LICENSE file before adopting.'
        return self._save(state, row)

    def save_research_decision(self, identity, values):
        self._values(values, ('decision', 'why', 'license'))
        if set(values) != {'decision', 'why', 'license'} or values['decision'] not in {'Adopt', 'Learn only', 'Skip'} or not values['why'].strip():
            raise ValueError('Choose Adopt, Learn only or Skip and explain why.')
        state = self.get_state()
        row = self._row(state['social']['research'], identity)
        if values['decision'] == 'Adopt':
            evidence = '\n'.join(row.get('licenseEvidence', []))
            if values['license'] not in {'MIT', 'Apache-2.0'} or not evidence or (
                    values['license'] == 'MIT' and 'MIT' not in evidence) or (
                    values['license'] == 'Apache-2.0' and not ('Apache' in evidence and '2.0' in evidence)):
                raise ValueError('Read and check the actual permissive LICENSE text before adopting. Learn only is available.')
        if any(row.get(k) != v for k, v in values.items()):
            row.pop('work', None)
        row.update(values)
        row['status'] = 'Decision recorded; application requires reviewed work' if values['decision'] == 'Adopt' else 'Decision recorded'
        return self._save(state, row)

    def _workshop_has(self, task):
        # Task existence is confirmed by the Workshop owner, never by reading its file here.
        return type(task) is str and bool(task) and callable(self.task_exists) and self.task_exists(task)

    def bind_research_work(self, identity, work):
        state = self.get_state()
        row = self._row(state['social']['research'], identity)
        if row.get('decision') != 'Adopt' or not self._workshop_has(work):
            raise ValueError('Choose the actual admitted application Work before linking this decision.')
        row.update(work=work, status='Application work queued; not applied')
        return self._save(state, row)

    def add_slide(self):
        state = self.get_state()
        row = {"id": uuid.uuid4().hex, "title": "", "body": "", "layout": "Title"}
        state["presentation"]["slides"].append(row)
        return self._save(state, row)

    def edit_slide(self, identity, values):
        self._values(values, ("title", "body", "layout"))
        if "layout" in values and values["layout"] not in {"Title", "Plan", "Result"}:
            raise ValueError("Choose a listed slide layout.")
        state = self.get_state()
        row = self._row(state["presentation"]["slides"], identity)
        row.update(values)
        return self._save(state, row)

    def remove_slide(self, identity):
        state = self.get_state()
        rows = state["presentation"]["slides"]
        row = self._row(rows, identity)
        rows.remove(row)
        return self._save(state, {"removed": identity})

    def reorder_slide(self, identity, before):
        state = self.get_state()
        rows = state["presentation"]["slides"]
        row, target = self._row(rows, identity), self._row(rows, before)
        if row is not target:
            rows.remove(row)
            rows.insert(rows.index(target), row)
        return self._save(state, row)

    def set_prototype(self, values):
        if type(values) is not dict or not values or set(values) - {"name", "threshold", "linkedModel", "measurements"}:
            raise ValueError("Choose a prototype setting.")
        if "name" in values and (type(values["name"]) is not str or len(values["name"]) > 500):
            raise ValueError("Enter a prototype name within 500 characters.")
        if "threshold" in values and (type(values["threshold"]) not in (float, int) or not 0 <= values["threshold"] <= 1):
            raise ValueError("Choose a deviation threshold between zero and one.")
        if "linkedModel" in values and type(values["linkedModel"]) is not bool:
            raise ValueError("Choose on or off for the linked model preference.")
        if "measurements" in values:
            self._measurements(values["measurements"])
        state = self.get_state()
        state["prototype"].update(values)
        return self._save(state, state["prototype"])

    @staticmethod
    def _measurements(text):
        import math
        if type(text) is not str or len(text) > 4096:
            raise ValueError("Enter comma-separated measured sample scores between zero and one.")
        try:
            values = [float(value.strip()) for value in text.split(",")]
        except ValueError as error:
            raise ValueError("Enter comma-separated measured sample scores between zero and one.") from error
        if not 2 <= len(values) <= 256 or any(not math.isfinite(value) or not 0 <= value <= 1 for value in values):
            raise ValueError("Supply between 2 and 256 measured scores, each between zero and one.")
        return values

    def rebaseline_prototype(self):
        import statistics
        state = self.get_state()
        row = state["prototype"]
        values = self._measurements(row.get("measurements", ""))
        row.update(baseline=statistics.mean(values), samples=len(values), status="Baseline saved",
                   baselineDigest=hashlib.sha256(row["measurements"].encode()).hexdigest())
        return self._save(state, row)

    def check_verdict_pattern(self):
        import statistics
        state = self.get_state()
        row = state["prototype"]
        values = self._measurements(row.get("measurements", ""))
        if not row.get("baselineDigest"):
            raise ValueError("Re-baseline the supplied measurements before inspecting their deviation.")
        if type(row.get("threshold")) not in (int, float):
            raise ValueError("Choose a deviation threshold before comparing samples.")
        mean = statistics.mean(values)
        deviation = abs(mean - row["baseline"])
        row.update(status="Compared", pattern="Mean deviation %.6g %s threshold %.6g" %
                   (deviation, "exceeds" if deviation > row["threshold"] else "is within", row["threshold"]),
                   features=[{"measure": "Samples", "value": len(values)}, {"measure": "Mean", "value": mean},
                             {"measure": "Baseline", "value": row["baseline"]}, {"measure": "Deviation", "value": deviation}])
        return self._save(state, row)

    def set_meeting(self, values):
        if type(values) is not dict or not values or set(values) - {"calendarId", "platform", "agent", "consent"}:
            raise ValueError("Choose a meeting setting.")
        state = self.get_state()
        if "calendarId" in values:
            calendar = self._row(state["meetingCalendar"], values["calendarId"])
            state["meeting"].update(title=calendar["title"], url=calendar["url"], source=calendar["source"], startsAt=calendar["startsAt"])
        if "platform" in values and values["platform"] not in {"Teams", "Zoom", "Google Meet"}:
            raise ValueError("Choose a listed meeting program.")
        if "agent" in values and (type(values["agent"]) is not str or not values["agent"]):
            raise ValueError("Choose a connected agent.")
        if "consent" in values and type(values["consent"]) is not bool:
            raise ValueError("Record consent as on or off.")
        if "consent" in values and not values["consent"] and state["meeting"]["status"] == "Transcribing":
            raise ValueError("Stop the live transcript before revoking its consent.")
        state["meeting"].update(values)
        return self._save(state, state["meeting"])

    def set_meeting_action_owner(self, index, owner):
        state = self.get_state()
        if type(index) is not int or not 0 <= index < len(state["meeting"]["actions"]) or type(owner) is not str or not owner.strip():
            raise ValueError("Choose an existing meeting action and an owner.")
        state["meeting"]["actionOwners"][str(index)] = owner
        return self._save(state, state["meeting"])

    def bind_meeting_task(self, index, task):
        state = self.get_state()
        if type(index) is not int or not 0 <= index < len(state["meeting"]["actions"]) or not state["meeting"]["actionOwners"].get(str(index)):
            raise ValueError("Choose an owned meeting action first.")
        if not self._workshop_has(task):
            raise ValueError("The task is not in this account. Refresh the Workshop.")
        state["meeting"]["actionTasks"][str(index)] = task
        return self._save(state, state["meeting"])

    def _local_text(self, source, extensions):
        from pathlib import Path
        from .pipeline_engines import _local_input_path
        path = Path(_local_input_path(source, label="meeting source"))
        if path.suffix.lower() not in extensions or path.stat().st_size > 32768:
            raise ValueError("Choose a supported meeting text source within 32 KiB.")
        raw = path.read_bytes()
        return path, raw.decode("utf-8-sig"), hashlib.sha256(raw).hexdigest()

    def import_meeting_calendar(self, source):
        path, text, digest = self._local_text(source, {".ics"})
        rows, event = [], None
        text = text.replace("\r\n ", "").replace("\n ", "")
        for line in text.splitlines():
            if line == "BEGIN:VEVENT":
                event = {}
            elif line == "END:VEVENT" and event is not None:
                if event.get("UID") and event.get("SUMMARY"):
                    rows.append({"id": event["UID"], "title": event["SUMMARY"],
                                 "url": event.get("URL", ""), "startsAt": event.get("DTSTART", ""),
                                 "source": str(path), "sha256": digest})
                event = None
            elif event is not None and ":" in line:
                key, value = line.split(":", 1)
                event[key.split(";", 1)[0]] = value
        if not rows:
            raise ValueError("The calendar file contains no named events with identities. Export a meeting as ICS and retry.")
        if len({r["id"] for r in rows}) != len(rows):
            raise ValueError("Choose an ICS export with distinct event identities; recurring exceptions need the Calendar node.")
        state = self.get_state()
        state["meetingCalendar"] = rows
        return self._save(state, rows)

    def import_meeting_transcript(self, source):
        path, text, digest = self._local_text(source, {".vtt", ".srt", ".txt"})
        state = self.get_state()
        if not state["meeting"]["consent"]:
            raise ValueError("Record transcript consent before importing the captured transcript.")
        rows, at = [], ""
        for line in text.splitlines():
            line = line.strip()
            if " --> " in line:
                at = line.split(" --> ", 1)[0]
            elif line and line != "WEBVTT" and not line.isdigit():
                rows.append({"id": hashlib.sha256((digest+str(len(rows))).encode()).hexdigest(),
                             "at": at, "speaker": "", "text": line,
                             "source": str(path), "sourceHash": digest})
        if not rows:
            raise ValueError("The transcript has no captured words. Choose a populated transcript source.")
        state["meeting"]["transcript"] = rows
        return self._save(state, rows)

    def set_source_read_seconds(self, seconds):
        if type(seconds) not in (int, float) or not 1 <= seconds <= 60:
            raise ValueError("Choose a source read timeout between 1 and 60 seconds.")
        state = self.get_state()
        state["social"]["sourceReadSeconds"] = seconds
        return self._save(state, {"seconds": seconds})

    # ---- posting: saved draft -> exact request -> one Approve card -> SocialHttpHost ----

    def _posts(self):
        return self.store.read().get("posts") or []

    def _post(self, root):
        row = next((row for row in self._posts() if row.get("id") == root), None) if type(root) is str else None
        if row is None:
            raise ValueError("This post review is no longer here. Refresh Social media.")
        return row

    def _set_post(self, root, **changes):
        # shortcut: the native MCP process writes posts through this same owner without a cross-process
        # file lock; a lost update is possible only when it races an app write. Add one if both get busy.
        with self.lock:
            posts = self._posts()
            next(row for row in posts if row["id"] == root).update(changes)
            self.store.update({"posts": _retained(posts)})

    def _connection(self, network):
        if callable(self.connection):
            return self.connection(network)
        from . import social_connections
        return social_connections.connection(network)

    def prepare_post(self, identity):
        """Rebuild the exact provider request for one saved draft and hold it for approval."""
        with self.lock:
            state = self.get_state()
            draft = self._row(state["social"]["drafts"], identity)
            if draft.get("status") != "Draft":
                raise ValueError("Only a saved draft can be reviewed for posting.")
            if draft.get("kind") == "reply":
                raise ValueError(open_item("sending replies", "Replies need the inbox reader, which has no owner yet."))
            route = POST_ROUTES.get(draft.get("platform"))
            if route is None:
                raise ValueError(open_item("posting to %s from a draft" % draft.get("platform"),
                                           "Its official API needs media or a recipient that a text draft does not hold."))
            if draft.get("schedule"):
                raise ValueError(open_item("timed posting", "Clear the post time to post when you approve it."))
            network, operation, argument = route
            connection = self._connection(network)
            if connection.get("state") != "connected" or not connection.get("account_id") or not connection.get("vault_entry"):
                raise ValueError("Connect %s with provider sign-in in Settings > Connections, then review the post again."
                                 % draft["platform"])
            inputs = {"operation": operation, "account_id": connection["account_id"],
                      "vault_entry": connection["vault_entry"], "arguments": {argument: draft["text"]}}
            try:
                _prepared, raw = social_material_from_values(inputs)
            except Refusal as refusal:
                raise ValueError("This post cannot be prepared: %s" % refusal.reason) from refusal
            digest = hashlib.sha256(raw).hexdigest()
            root = "social-post:" + hashlib.sha256((identity + "\n" + digest).encode()).hexdigest()[:32]
            posts = self._posts()
            if not any(row.get("id") == root for row in posts):
                posts.append({"id": root, "draft": identity, "platform": draft["platform"],
                              "account": connection.get("display_name") or connection["account_id"],
                              "inputs": inputs, "input_digest": digest, "operation": operation,
                              "text": draft["text"], "status": "pending", "created": time.time()})
                self.store.update({"posts": _retained(posts)})
            return self.card(root)

    def card(self, root):
        row = self._post(root)
        return {"id": root, "delegation": root, "work": row["draft"], "input_digest": row["input_digest"],
                "approvalKind": "social", "kind": "social", "who": "Social media",
                "title": "Post to " + row["platform"],
                "summary": "Sends from your %s account %s when you approve." % (row["platform"], row["account"]),
                "operation": row["operation"], "text": row["text"], "status": row["status"],
                "rows": [{"element": "Account", "before": "", "after": row["platform"] + " · " + row["account"]},
                         {"element": "Post", "before": "", "after": row["text"]}],
                "rubric": {}, "events": [], "receipt": row.get("receipt"), "error": row.get("error", "")}

    def reviews(self):
        return [self.card(row["id"]) for row in self._posts()]

    def pending(self):
        return [card for card in self.reviews() if card["status"] == "pending"]

    def apply(self, root, digest, decision, *, host=None):
        """The user's Approve or Deny on the exact request (hook_decision.decide calls this)."""
        with self.lock:
            row = self._post(root)
            if decision not in ("approve", "deny") or digest != row["input_digest"]:
                raise ValueError("Review the exact post shown before deciding.")
            if row["status"] != "pending":
                if (decision, row["status"]) in (("deny", "denied"), ("approve", "posted")):
                    return self.card(root)
                raise ValueError("This post is closed or needs reconciliation. Refresh Social media.")
            if decision == "deny":
                self._set_post(root, status="denied")
                return self.card(root)
            try:
                prepared, raw = social_material_from_values(row["inputs"])
            except Refusal as refusal:
                raise ValueError("This post cannot be prepared: %s" % refusal.reason) from refusal
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("The prepared request changed. Review the post again.")
            state = self.get_state()
            draft = next((d for d in state["social"]["drafts"] if d.get("id") == row["draft"]), None)
            if draft is None or draft.get("status") != "Draft" or draft.get("text") != row["text"]:
                raise ValueError("The draft changed after review. Review the post again.")
            try:
                outcome = (host or http_host()).execute(
                    prepared, row["inputs"]["vault_entry"], before_dispatch=lambda: self._set_post(root, status="dispatching"))
            except Refusal as refusal:
                self._set_post(root, status="failed", error=refusal.reason)
                raise ValueError("The post was not sent: %s" % refusal.reason) from refusal
            result = outcome["result"]
            if outcome["outcome"] == "succeeded":
                self._set_post(root, status="posted", receipt=result)
                draft.update(status="Posted", receipt={k: v for k, v in result.items() if k.endswith("_id")})
                self._save(state, draft)
            else:
                self._set_post(root, status="uncertain" if outcome["outcome"] == "uncertain" else "failed",
                               error=result.get("reason") or "No confirmed provider result is available.")
            return self.card(root)


def _retained(posts):
    """Open and uncertain posts are never evicted; closed ones keep the newest closed_posts_limit."""
    keep = SOCIAL_NODE["params"]["closed_posts_limit"]
    closed = [row for row in posts if row.get("status") in ("denied", "posted", "failed")]
    dropped = {id(row) for row in closed[:-keep]} if len(closed) > keep else set()
    return [row for row in posts if id(row) not in dropped]


def http_host():
    from .social_custody import social_credential
    return SocialHttpHost(social_credential)


def _failure(state, reason, *, uncertain=False):
    return {"outcome": "uncertain" if uncertain else "failed",
            "result": {"ok": False, "state": state, "reason": reason}}


class SocialHttpHost:
    """Execute a runtime-rebuilt request with a custody-owned token resolver.

    timeout_seconds bounds socket operations and elapsed response reading, not
    the operating system DNS resolver. No claim of a hard DNS deadline is made.
    The resolver atomically checks provider/account custody and returns the
    credential for that exact binding. A prior account-verifier call alone
    cannot protect against replacement before credential resolution.
    """

    def __init__(self, credential_resolver, *, timeout_seconds=20.0):
        if not callable(credential_resolver):
            raise TypeError("social credential resolver must be callable")
        if (type(timeout_seconds) not in (int, float)
                or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 60):
            raise ValueError("social HTTP timeout must be between zero and 60 seconds")
        self._credential_resolver = credential_resolver
        self._timeout = float(timeout_seconds)

    def execute(self, prepared, vault_entry, *, before_dispatch):
        verify_prepared(prepared)
        if prepared.operation not in WORK_OPERATIONS:
            raise Refusal("invalid_input", "operation has no admitted Work response contract")
        if (type(vault_entry) is not str or not vault_entry.strip()
                or len(vault_entry.encode("utf-8")) > 512 or "\0" in vault_entry
                or not callable(before_dispatch)):
            raise Refusal("invalid_input", "social custody or dispatch callback is invalid")
        headers = {}
        allowed = {"accept", "content-type", "linkedin-version", "x-restli-protocol-version"}
        for name, value in prepared.headers:
            if (type(name) is not str or type(value) is not str
                    or name.lower() not in allowed or name.lower() in headers
                    or len(value) > 512 or any(ord(char) < 32 or ord(char) > 126 for char in value)):
                raise Refusal("invalid_input", "social request headers are invalid")
            headers[name.lower()] = value
        try:
            token = self._credential_resolver(
                provider=prepared.provider, account_id=prepared.account_id,
                vault_entry=vault_entry,
            )
            if (type(token) is not str or not 1 <= len(token) <= 16384
                    or any(ord(char) < 33 or ord(char) > 126 for char in token)):
                raise ValueError("invalid credential")
        except Exception:
            return _failure("credential_unavailable", "The admitted credential could not be resolved.")

        # A refusal here propagates to the authority caller. No connection has
        # been constructed, and no HTTP request is silently retried.
        before_dispatch()
        parts = urlsplit(prepared.url)
        target = parts.path + ("?" + parts.query if parts.query else "")
        connection = None
        request_started = False
        deadline = time.monotonic() + self._timeout
        try:
            connection = http.client.HTTPSConnection(
                PROVIDER_ORIGINS[prepared.provider], 443, timeout=self._timeout,
                context=ssl.create_default_context())
            connection.connect()
            headers["authorization"] = "Bearer " + token
            headers["accept-encoding"] = "identity"
            headers["connection"] = "close"
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            connection.sock.settimeout(remaining)
            request_started = True
            connection.request(prepared.method, target, body=prepared.body, headers=headers)
            response = connection.getresponse()
            raw = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                part = response.read1(min(65536, MAX_RESPONSE_BYTES + 1 - len(raw)))
                if not part:
                    break
                raw.extend(part)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ValueError("oversize response")
            # Provider responses may echo bearer material. Never return such
            # bytes, even through a nominally successful normalized result.
            response_headers = dict(response.getheaders())
            if (token.encode("ascii") in raw
                    or any(token in str(value) for value in response_headers.values())):
                raise ValueError("credential reflected by provider")
            try:
                result = normalize_work_answer(prepared, response.status, response_headers, bytes(raw))
            except Refusal as refusal:
                result = refusal_answer(refusal)
            return {"outcome": ("succeeded" if result.get("ok") is True else
                                "uncertain" if result.get("state") == "uncertain" else "failed"),
                    "result": result}
        except Exception:
            if request_started and prepared.effect == "write":
                return _failure("uncertain", "The provider may have applied the request; reconcile before retrying.",
                                uncertain=True)
            return _failure("network_error" if request_started else "dispatch_not_connected",
                            "No confirmed provider result is available.")
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception as closing:  # noqa: BLE001 - the outcome above is already decided
                    _LOG.warning("social provider connection did not close cleanly: %s", type(closing).__name__)
