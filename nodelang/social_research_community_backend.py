"""Studio social and presentation properties in the existing authorised graph.

No account, inbox, extraction, provider execution or verification is invented.
External work remains with the existing Workshop and its approval owners.
"""
import copy
import hashlib
import inspect
import json
import uuid
from html.parser import HTMLParser
from urllib.parse import urlsplit


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


class SocialResearchCommunityBackend:
    """One graph-property adapter. A detached instance can only read empty state."""

    PUBLIC = ("get_state", "update_office_page", "save_social_draft", "discard_social_draft",
              "read_social_message", "triage_social_inbox", "reply_social_message",
              "set_social_group_rule", "set_social_digest", "generate_social_digest",
              "read_content_source", "add_slide", "edit_slide", "remove_slide", "reorder_slide",
              "set_prototype", "rebaseline_prototype", "check_verdict_pattern", "set_meeting",
              "set_meeting_action_owner", "bind_meeting_task", "import_meeting_calendar", "import_meeting_transcript", "set_source_read_seconds",
              "check_research_license", "save_research_decision", "bind_research_work")
    PROPERTY = "studio.social-research"

    def __init__(self, store=None, registry=None, context=None, *, lock=None, guard=None):
        from contextlib import nullcontext
        self.lock = lock if lock is not None else nullcontext()
        self.guard = guard
        self.graph = None
        if store is not None:
            from .canvas_graph_owner import CanvasOwner
            self.graph = CanvasOwner(store, registry, context)

    def dispatch(self, operation, args):
        if type(operation) is not str or operation not in self.PUBLIC or type(args) is not list:
            raise ValueError("Choose a registered social operation.")
        function = getattr(self, operation)
        try:
            inspect.signature(function).bind(*args)
        except TypeError as error:
            raise ValueError("The action arguments changed. Refresh this screen.") from error
        result = function(*args)
        return {"result": result, "state": self.get_state()}

    def _owner(self):
        if self.graph is None:
            return None
        from .universal_pipeline import _owner_properties
        canvas = self.graph.canvas()
        properties = _owner_properties(self.graph.store.snapshot(), self.graph.registry)
        matches = [node["id"] for node in canvas["nodes"] if self.PROPERTY in properties.get(node["id"], {})]
        if len(matches) > 1:
            raise ValueError("More than one social node owns this graph. Reconcile their content before editing.")
        return matches[0] if matches else None

    def get_state(self):
        owner = self._owner()
        if not owner:
            return empty_state()
        row = self.graph._rows(None, owner).get(self.PROPERTY)
        return json.loads(row["value"])

    def get_social_snapshot(self):
        return self.get_state()["social"]

    def _save(self, state, result):
        encoded = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode()) > 65536:
            raise ValueError("This graph's social content exceeds 64 KiB. Archive content before saving.")
        if self.graph is None:
            raise ValueError("Open a graph before saving this action.")
        owner = self._owner()
        if owner:
            self.graph.set_property(owner, self.PROPERTY, encoded)
        else:
            from .universal_pipeline import create_engine_node
            create_engine_node(self.graph.store, self.graph.registry, title="Social media",
                engine="library.think", properties={self.PROPERTY: encoded},
                authentication_context=self.graph.context)
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

    def bind_research_work(self, identity, work):
        from .universal_application import project_universal_governed_work
        state = self.get_state()
        row = self._row(state['social']['research'], identity)
        works = project_universal_governed_work(self.graph.store, self.graph.registry,
                                               authentication_context=self.graph.context)
        if row.get('decision') != 'Adopt' or work not in {w['root'] for w in works}:
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
        # Task existence is confirmed by the Workshop owner before this projection binding.
        from .universal_application import project_universal_governed_work
        rows = project_universal_governed_work(self.graph.store, self.graph.registry,
                                              authentication_context=self.graph.context)
        if task not in {row["root"] for row in rows}:
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
