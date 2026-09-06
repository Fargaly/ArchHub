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


def test_the_six_that_remain_say_why():
    assert set(L.LIBRARY_ITEMS_WITHOUT_ENGINE) == {"a_tags", "a_rooms", "c_sheet", "i_vis", "o_pdf", "o_spk"}
    for item, reason in L.LIBRARY_ITEMS_WITHOUT_ENGINE.items():
        assert reason, item
