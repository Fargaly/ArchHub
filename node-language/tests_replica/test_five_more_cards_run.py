"""Five more library cards run: think, match_skill, embed, draft_email, notify.

Each had a reason it could not run; each reason is now answered by
something this build already has (the model route, the skills catalogue,
the brain recall, the open Outlook, the tray). Every engine keeps the two
laws of the library: nothing invented, one meaning per operation.
"""
from __future__ import annotations

import os
from pathlib import Path

from nodelang import library_engines as L
from nodelang import model_router, pipeline_engines
from nodelang.agent_composer import NO_MODEL_CHOSEN

ROOT = Path(__file__).resolve().parents[1]


def test_think_uses_the_picked_route_and_never_a_hidden_default(monkeypatch):
    seen = {}

    def route_chat(route, messages, **options):
        seen["route"] = route
        seen["user"] = messages[-1]["content"]
        return {"text": "2 walls, 8 400 mm total"}

    monkeypatch.setattr(model_router, "route_chat", route_chat)
    monkeypatch.delenv("ARCHHUB_AGENT_MODEL", raising=False)
    out, said = L.think({"prompt": "total wall length", "model": "openrouter/x/y"},
                        {"in": [{"length_mm": 4200}, {"length_mm": 4200}]})
    assert out["out"] == "2 walls, 8 400 mm total" and "openrouter/x/y answered" in said
    assert seen["route"] == "openrouter/x/y" and "4200" in seen["user"]
    out, said = L.think({"prompt": "anything"}, {})
    assert out["out"] == [] and said == NO_MODEL_CHOSEN


def test_think_says_who_refused(monkeypatch):
    def refuse(route, messages, **options):
        raise model_router.ModelRouteRefused("no key for openrouter")

    monkeypatch.setattr(model_router, "route_chat", refuse)
    out, said = L.think({"prompt": "x", "model": "openrouter/x/y"}, {})
    assert out["out"] == [] and said.startswith("openrouter/x/y refused: no key")


def test_match_skill_ranks_by_word_overlap_and_says_so(monkeypatch):
    rows = [
        {"name": "revit-room-tags", "source": "claude", "description": "tag rooms in the active Revit view", "path": "x"},
        {"name": "bbc4-submittal-qc", "source": "codex", "description": "check a submittal against the master", "path": "y"},
    ]
    monkeypatch.setattr(pipeline_engines, "skills_catalogue", lambda p, f: ({"out": rows}, "2 skill(s)"))
    out, said = L.match_skill({"intent": "tag the rooms in revit"}, {})
    assert [r["name"] for r in out["out"]] == ["revit-room-tags"] and out["out"][0]["score"] >= 2
    assert "word overlap, not a model" in said
    out, said = L.match_skill({}, {})
    assert out["out"] == [] and "no intent" in said


def test_embed_is_the_brain_recall(monkeypatch):
    asked = {}

    def brain_call(tool, arguments):
        asked["tool"] = tool
        asked["arguments"] = dict(arguments)
        return '{"facts": [{"id": 1, "text": "walls are 200 mm"}, {"id": 2, "text": "doors 900 mm"}]}'

    monkeypatch.setattr(pipeline_engines, "_brain_call", brain_call)
    out, said = L.embed({"query": "wall thickness"}, {})
    assert asked == {"tool": "brain.context", "arguments": {"prompt": "wall thickness"}}
    assert len(out["out"]) == 2 and said.startswith("2 recalled fact(s)")

    def silent(tool, arguments):
        raise pipeline_engines.BrainSilent("nothing listening on 8473")

    monkeypatch.setattr(pipeline_engines, "_brain_call", silent)
    out, said = L.embed({"query": "x"}, {})
    assert out["out"] == [] and said.startswith("no recall:")


def test_notify_lands_on_the_registered_surface_or_says_there_is_none(monkeypatch):
    monkeypatch.setattr(L, "_NOTIFY_SURFACE", [])
    out, said = L.notify({"message": "sheet set published"}, {})
    assert out["out"] == "sheet set published" and "no desktop surface registered" in said
    shown = []
    L.set_notify_surface(lambda title, message: shown.append((title, message)))
    out, said = L.notify({"title": "ArchHub", "message": "sheet set published"}, {})
    assert shown == [("ArchHub", "sheet set published")] and said.startswith("shown on the desktop")
    out, said = L.notify({}, {})
    assert out["out"] == [] and "nothing to say" in said


def test_draft_email_opens_a_draft_and_never_sends(monkeypatch):
    class Mail:
        def __init__(self):
            self.calls = []
        def Display(self):
            self.calls.append("Display")
        def Send(self):
            self.calls.append("Send")

    class Outlook:
        def __init__(self):
            self.mail = Mail()
        def CreateItem(self, kind):
            assert kind == 0
            return self.mail

    outlook = Outlook()
    monkeypatch.setattr(L, "_OUTLOOK", [lambda: outlook])
    out, said = L.draft_email({"to": "eng@firm.com", "subject": "Sheets"}, {"in": "Set 03 attached"})
    assert outlook.mail.To == "eng@firm.com" and outlook.mail.Body == "Set 03 attached"
    assert outlook.mail.calls == ["Display"], "a draft on screen, never Send"
    assert out["out"]["chars"] == 15 and "you send it" in said
    monkeypatch.setattr(L, "_OUTLOOK", [lambda: None])
    out, said = L.draft_email({"body": "x"}, {})
    assert out["out"] == [] and "Outlook is not open" in said


def test_the_launcher_registers_its_tray_as_the_notify_surface():
    launcher = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    assert "set_notify_surface(" in launcher
    block = launcher[launcher.index("class _Notifier"):]
    assert "asked = _signal(str, str)" in block and "_tray.showMessage(title, message)" in block
    assert "_notifier.asked.emit(" in block, "a queued signal, not a cross-thread widget call"


def test_every_card_now_runs():
    assert L.LIBRARY_ITEMS_WITHOUT_ENGINE == {}
    for item, reason in L.LIBRARY_ITEMS_WITHOUT_ENGINE.items():
        assert reason, item


def test_vision_sends_the_image_as_a_data_url_with_the_picked_model(monkeypatch):
    seen = {}

    def route_chat(route, messages, **options):
        seen["route"] = route
        seen["parts"] = messages[0]["content"]
        return {"text": "a plan: 4 rooms, walls 200 mm"}

    monkeypatch.setattr(model_router, "route_chat", route_chat)
    monkeypatch.delenv("ARCHHUB_AGENT_MODEL", raising=False)
    sample = ROOT / "nodelang" / "samples" / "sample-plan.png"
    assert sample.is_file()
    out, said = L.vision({"model": "openrouter/x/vision", "prompt": "rooms?"}, {"in": str(sample)})
    assert out["out"].startswith("a plan") and out["image_path"] == str(sample)
    assert seen["route"] == "openrouter/x/vision" and "sample-plan.png" in said
    text, image = seen["parts"]
    assert text == {"type": "text", "text": "rooms?"}
    assert image["type"] == "image_url" and image["image_url"]["url"].startswith("data:image/png;base64,")
    out, said = L.vision({"prompt": "rooms?"}, {"in": str(sample)})
    assert out["out"] == [] and said == NO_MODEL_CHOSEN


def test_vision_is_honest_about_a_missing_or_unreadable_file(tmp_path, monkeypatch):
    monkeypatch.setattr(model_router, "route_chat", lambda *a, **k: {"text": "never"})
    out, said = L.vision({"model": "openrouter/x/vision", "image_path": str(tmp_path / "nope.png")}, {})
    assert out["out"] == [] and "does not exist" in said
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    out, said = L.vision({"model": "openrouter/x/vision", "image_path": str(tmp_path / "notes.txt")}, {})
    assert out["out"] == [] and "not an image" in said
    out, said = L.vision({"model": "openrouter/x/vision"}, {})
    assert out["out"] == [] and "no image_path" in said


def test_publish_pdf_exports_the_sheets_through_the_live_revit(monkeypatch, tmp_path):
    from nodelang import clean_revit_adapter as adapter
    sent = {}
    monkeypatch.setattr(adapter, "live_sessions", lambda: [
        {"port": 48885, "revit_version": "2025", "document": "P-664.rvt"}])

    def call(port, route, body=None, timeout=None):
        sent["port"], sent["route"], sent["body"] = port, route, dict(body or {})
        return {"status": "ok", "result": {"sheets": 2, "folder": str(tmp_path),
                                           "files": [str(tmp_path / "A101.pdf"), str(tmp_path / "A102.pdf")]}}

    monkeypatch.setattr(adapter, "_call", call)
    out, said = L.publish_pdf({"sheets": "A101, A102", "folder": str(tmp_path)}, {})
    assert sent["port"] == 48885 and sent["route"] == "/exec"
    code = sent["body"]["code"]
    assert "PDFExportOptions" in code and "Doc.Export(folder, sheets, options)" in code
    assert 'new List<string>{"A101", "A102"}' in code
    assert code.lstrip().startswith("var folder = " + __import__("json").dumps(str(tmp_path)))
    assert out["out"] == [str(tmp_path / "A101.pdf"), str(tmp_path / "A102.pdf")]
    assert said.startswith("2 PDF(s) in") and "P-664.rvt" in said

    monkeypatch.setattr(adapter, "_call", lambda *a, **k: {"status": "error", "error": "no sheet to publish"})
    out, said = L.publish_pdf({}, {})
    assert out["out"] == [] and said == "Revit refused: no sheet to publish"

    monkeypatch.setattr(adapter, "live_sessions", lambda: [])
    out, said = L.publish_pdf({}, {})
    assert out["out"] == [] and said == "no Revit session is listening"


def _revit(monkeypatch, result):
    from nodelang import clean_revit_adapter as adapter
    sent = {}
    monkeypatch.setattr(adapter, "live_sessions", lambda: [
        {"port": 48885, "revit_version": "2025", "document": "P-664.rvt"}])

    def call(port, route, body=None, timeout=None):
        sent["port"], sent["route"], sent["body"] = port, route, dict(body or {})
        return {"status": "ok", "result": result}

    monkeypatch.setattr(adapter, "_call", call)
    return sent


def test_tag_rooms_tags_the_untagged_rooms_of_the_active_view(monkeypatch):
    sent = _revit(monkeypatch, {"tagged": 6, "skipped": 2, "view": "Level 1"})
    out, said = L.tag_rooms({}, {})
    code = sent["body"]["code"]
    assert "Doc.Create.NewRoomTag(" in code and "OST_Rooms" in code and "already.Contains(room.Id" in code
    assert sent["body"]["transaction_name"] == "ArchHub tag rooms" and 'new Transaction(Doc, "ArchHub tag rooms")' in code
    assert out["tagged"] == 6 and said == "6 room(s) tagged, 2 skipped, in Level 1 of P-664.rvt"


def test_place_tags_tags_one_category_with_or_without_a_leader(monkeypatch):
    sent = _revit(monkeypatch, {"tagged": 11, "skipped": 0, "category": "Doors", "view": "Level 1"})
    out, said = L.place_tags({"category": "Doors", "leader": "false"}, {})
    code = sent["body"]["code"]
    assert "IndependentTag.Create(Doc, view.Id, new Reference(e), leader" in code
    assert 'var catName = "Doors";' in code and "bool leader = false;" in code
    assert "GetTaggedLocalElementIds()" in code, "already tagged elements are skipped"
    assert out["tagged"] == 11 and said == "11 doors tagged, 0 skipped, in Level 1"


def test_place_on_sheet_places_named_views_and_makes_the_sheet_if_missing(monkeypatch):
    sent = _revit(monkeypatch, {"sheet": "A101", "placed": ["Level 1", "Level 2"], "skipped": ["Roof"]})
    out, said = L.place_on_sheet({"sheet": "A101"}, {"in": [{"name": "Level 1"}, {"name": "Level 2"}, {"name": "Roof"}]})
    code = sent["body"]["code"]
    assert 'var number = "A101";' in code and 'new List<string>{"Level 1", "Level 2", "Roof"}' in code
    assert "ViewSheet.Create(Doc, tb)" in code and "Viewport.CanAddViewToSheet" in code and "Viewport.Create(" in code
    assert out["placed"] == ["Level 1", "Level 2"] and said == "2 view(s) on sheet A101, 1 skipped"
    out, said = L.place_on_sheet({}, {})
    assert out["out"] == [] and said == "no sheet number given"


def test_revit_authoring_is_honest_without_a_session(monkeypatch):
    from nodelang import clean_revit_adapter as adapter
    monkeypatch.setattr(adapter, "live_sessions", lambda: [])
    for engine, params in ((L.tag_rooms, {}), (L.place_tags, {"category": "Doors"}),
                           (L.place_on_sheet, {"sheet": "A101", "views": "Level 1"})):
        out, said = engine(params, {})
        assert out["out"] == [] and said == "no Revit session is listening"


class _SpeckleWire:
    def __init__(self, answers):
        self.answers = list(answers)
        self.sent = []

    def __call__(self, request, timeout=None):
        self.sent.append(request)
        payload = self.answers.pop(0)
        wire = self

        class _Response:
            def __enter__(self):
                return self
            def __exit__(self, *unused):
                return False
            def read(self):
                return __import__("json").dumps(payload).encode("utf-8")
        return _Response()


def test_push_speckle_uploads_one_object_and_commits_it_to_the_branch():
    wire = _SpeckleWire([{}, {"data": {"commitCreate": "c0ffee42"}}])
    rows = [{"id": 1, "type": "Basic Wall", "length_mm": 4200}]
    out, said = L.push_speckle({"project": "abc123", "branch": "archhub/main", "message": "walls"}, {"in": rows},
                               opener=wire, environ={"SPECKLE_TOKEN": "spk-live"})
    upload, commit = wire.sent
    assert upload.full_url == "https://app.speckle.systems/objects/abc123"
    assert upload.headers["Authorization"] == "Bearer spk-live"
    sent = __import__("json").loads(upload.data.decode("utf-8"))
    assert len(sent) == 1 and sent[0]["rows"] == rows and sent[0]["count"] == 1
    assert sent[0]["id"] == L._speckle_object_id(sent[0]), "the id is the sha of the object"
    body = __import__("json").loads(commit.data.decode("utf-8"))
    assert commit.full_url == "https://app.speckle.systems/graphql" and "commitCreate" in body["query"]
    assert body["variables"]["commit"] == {"streamId": "abc123", "branchName": "archhub/main",
                                           "objectId": sent[0]["id"], "message": "walls",
                                           "sourceApplication": "ArchHub"}
    assert out["out"]["commit_id"] == "c0ffee42" and out["out"]["rows"] == 1
    assert said == "commit c0ffee42 on archhub/main (1 rows) at https://app.speckle.systems"


def test_push_speckle_is_honest_about_no_rows_no_project_no_token_and_a_refusal():
    out, said = L.push_speckle({"project": "abc123"}, {}, environ={"SPECKLE_TOKEN": "x"})
    assert out["out"] == [] and said == "nothing is wired in"
    out, said = L.push_speckle({}, {"in": [{"a": 1}]}, environ={"SPECKLE_TOKEN": "x"})
    assert out["out"] == [] and said == "no Speckle project id given"
    out, said = L.push_speckle({"project": "abc123"}, {"in": [{"a": 1}]}, environ={}, secrets_loader=lambda name: "")
    assert out["out"] == [] and said.startswith("no Speckle token")
    wire = _SpeckleWire([{}, {"errors": [{"message": "branch not found"}]}])
    out, said = L.push_speckle({"project": "abc123", "branch": "nope"}, {"in": [{"a": 1}]},
                               opener=wire, environ={}, secrets_loader=lambda name: "spk-store")
    assert out["out"] == [] and said == "Speckle refused: branch not found"
    assert wire.sent[0].headers["Authorization"] == "Bearer spk-store", "the secrets store is asked by name"
